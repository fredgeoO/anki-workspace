# -*- coding: utf-8 -*-
"""每集流水线驱动 —— **一条命令跑完阶段 2–5**，分支/重试/闸门/报告全在代码里。

为什么要这个文件
----------------
以前每一集是「六个能独立跑的命令 + 一个语言模型在旁边逐步判断」：
哪一步做完了、哪一批失败了、失败原因是机械问题还是语义问题，全靠 agent 读输出再决定下一步。
于是**代码与语言模型之间来回几十次**，而其中绝大多数根本不涉及语义。

现在把那份判断也做成代码：

    机械问题（结构、字符一致性、振假名覆盖、读音与既有先例冲突、批次完整性、
    Word 字段是否被改形状、音频原声能不能配上、字段是否真的写进去了）
        → 全部由脚本判、脚本修（`code/common/ruby_engine.py` 等）。
    语义问题（这句话怎么翻译、这个词值不值得收、这个读音到底是哪个）
        → 只在这一个地方问模型，而且是**一批一次**：
           阶段二：`needs_llm.json`（生成不出来/修不好的极少数卡）
           阶段四：`needs_llm.json`（候选词的词典形/是否成词）
           读音：`ruby_engine.py check` 的「待复核」短清单

用法
----
    # 演练（默认）：把该跑的都跑一遍，**不写 Anki**，最后打印一张表
    python code/execution/episode.py --tag "动画::<作品名>::<季>::第NN集" ^
        --input-tag "待标记" --plan "data/evidence/<集>/plan.json"

    # 真写（写完自动回读校验）
    python code/execution/episode.py --tag "…" --input-tag "待标记" --commit

    # 只跑某几个阶段（逗号分隔）
    python code/execution/episode.py --tag "…" --phases ruby,rank

阶段与「已完成就跳过」的判据
----------------------------
* `stage2` 补 AINote + Sentence HTML：scope 里 `AINote:` 为空的卡为 0 就跳过。
* `mine`   素材生词：`--input-tag`/`--tag` 下的例句卡扫候选；候选 0 就跳过。
* `audio`  生词配音：只给**本次 mine 新建的卡**（`nid:` 精确点名，不碰同标签下的旧卡）；
  本次没有新建卡时用 `--audio-tag` 指定补充范围，两者都没有就**跳过**（不回退成整副 deck）。
* `rank`   JitenAnimeRank：`freq_external.py field --all-notes`（幂等，只改值不对的）。
* `ruby`   振假名体检与修复（`ruby_engine.py check` + `apply --mode fix`）。
* `retag`  把 `--input-tag` 换成 `--tag`（导入时挂的 `待标记`）。

退出码：0 = 全部完成；3 = 只剩语义问题（已写进 needs_llm.json，见文件头注释）；
        其它非 0 = 某一步真的失败（原样回传）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(os.path.dirname(_HERE), 'common'), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import anki_api as AK        # noqa: E402
import paths as WSP          # noqa: E402
import ruby_engine as RE     # noqa: E402
import textio                # noqa: E402

PY = sys.executable
EXE = WSP.EXECUTION
TOOLS = WSP.TOOLS
ONESHOT = WSP.ONESHOT
GEN2 = os.path.join(WSP.DATA_PIPELINE, 'gen')
GEN4 = os.path.join(WSP.DATA_VOCAB, 'gen_mine')
CAND = os.path.join(WSP.DATA_VOCAB, 'mine_candidates.json')
RUNS = os.path.join(WSP.DATA_PIPELINE, 'runs')
JITEN_PLAN = os.path.join(WSP.DATA_PLANS, 'plan_activate_jiten.json')
NEEDS2 = os.path.join(GEN2, 'needs_llm.json')
NEEDS4 = os.path.join(GEN4, 'needs_llm.json')
PER_BATCH = 14               # 阶段二/四的批大小（口径见 SKILL.md）
DECK_EXAMPLE = '0-日本语学习::2-例句'


# ============================================================================
# 小工具
# ============================================================================
def run(script, args, label=None, allow=(0,)):
    """跑一个兄弟脚本（stdio 继承，退出码原样回）。"""
    if not os.path.exists(script):
        print('❌ 找不到脚本：%s' % script)
        return 2
    cmd = [PY, script] + [str(x) for x in args]
    print('\n→ %s %s' % (label or os.path.relpath(script, WSP.ROOT), ' '.join(str(x) for x in args)))
    sys.stdout.flush()
    rc = textio.run(cmd, stdout=None, stderr=None).returncode
    if rc not in allow:
        print('⛔ 上一步退出码 %d（不在允许集合 %s）' % (rc, allow))
    return rc


def batches(n, per=PER_BATCH):
    return max(1, -(-int(n) // per))


def count(query):
    return len(AK.find_notes(query))


def rel(path):
    return os.path.relpath(path, WSP.ROOT) if path else ''


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def dump_needs(path, why, key, rows):
    """落盘「只剩语义问题」的清单。

    **一条都没有就把旧文件删掉**：文件名写着 needs_llm，留个空壳会让人（和下一次的自己）
    以为还有活没干完 —— 与 `failed.json` 的处理口径一致。
    """
    if not rows:
        if os.path.exists(path):
            os.remove(path)
        return
    dump(path, {'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
                'why': why, key: rows})


# ============================================================================
# 阶段二：AINote + Sentence HTML
# ============================================================================
def stage2(a, rep):
    scope = a.input_tag or a.tag
    todo = count('tag:%s AINote:' % scope)
    rep['stage2'] = {'scope': scope, 'todo': todo}
    if not todo:
        print('\n[阶段二] tag:%s 没有 AINote 为空的卡 → 跳过' % scope)
        return 'skipped'
    print('\n[阶段二] 待生成 %d 张（%d 批）' % (todo, batches(todo)))
    extra = ['--srt', a.srt] if a.srt else (['--plan', a.plan] if a.plan else [])
    rc = run(os.path.join(EXE, 'pipeline.py'), ['split', '--tag', scope,
                                                '--batches', batches(todo)])
    if rc:
        return 'failed'
    rc = run(os.path.join(EXE, 'pipeline.py'), ['gen'])
    if rc:
        return 'failed'
    if os.path.exists(os.path.join(GEN2, 'failed.json')):
        run(os.path.join(EXE, 'pipeline.py'), ['gen', '--fix-failed', '--per-request', '3'],
            label='pipeline.py gen --fix-failed')
    # ★ 确定性修复：文本骨架 + 缺的 ruby 一律代码补，不问模型
    run(os.path.join(WSP.COMMON, 'ruby_engine.py'),
        ['repair', '--gen', GEN2, '--write'] + extra, label='ruby_engine.py repair')
    left = stage2_leftovers()
    dump_needs(NEEDS2, '这些卡结构上修不回来（通常是模型没返回/内容为空）—— 纯语义问题，'
                       '交给强模型按本文件补 output_NN.json 后重跑 episode.py', 'cards', left)
    rep['stage2'].update({'leftovers': len(left),
                          'needs_llm': rel(NEEDS2) if left else ''})
    if left:
        print('\n[阶段二] 只有 %d 张需要语言模型：%s' % (len(left), rel(NEEDS2)))
        return 'needs_llm'
    if not a.commit:
        print('\n[阶段二] 演练：产出已就绪，未写库（加 --commit 才写）')
        return 'dry'
    rc = run(os.path.join(EXE, 'pipeline.py'), ['write'])
    rep['stage2']['written'] = 'pipeline.py write'
    return 'failed' if rc else 'done'


def stage2_leftovers():
    """产出里有结构问题/AINote 空的卡（机械判据：直接问 check_cards）。"""
    man = os.path.join(GEN2, 'manifest.json')
    if not os.path.exists(man):
        return []
    out = []
    for m in json.load(open(man, encoding='utf-8')):
        path = os.path.join(GEN2, m['output'])
        if not os.path.exists(path):
            out.append({'batch': m['batch'], 'why': '还没有产出文件 %s' % m['output']})
            continue
        rows = json.load(open(path, encoding='utf-8'))
        for c in rows:
            sent = c.get('sentence') or ''
            html = c.get('SentenceHTML') or ''
            note = (c.get('AINote') or '').strip()
            if not note:
                out.append({'noteId': c.get('noteId'), 'sentence': sent,
                            'why': 'AINote 为空（模型没返回）'})
            else:
                hard, _soft = RE.validate(sent, html)
                if hard:
                    out.append({'noteId': c.get('noteId'), 'sentence': sent,
                                'why': '结构仍不合格：' + '；'.join(hard)[:200]})
    return out


# ============================================================================
# 阶段四：素材生词
# ============================================================================
def stage4(a, rep):
    scope = a.input_tag or a.tag
    rep['mine'] = {'scope': scope}
    if not count('deck:"%s" tag:"%s"' % (DECK_EXAMPLE, scope)):
        print('\n[阶段四] tag:%s 下没有例句卡 → 跳过' % scope)
        return 'skipped'
    rc = run(os.path.join(EXE, 'mine.py'), ['scan', '--tag', scope])
    if rc:
        return 'failed'
    cands = json.load(open(CAND, encoding='utf-8'))['candidates']
    rep['mine']['candidates'] = len(cands)
    if not cands:
        print('\n[阶段四] 没有候选 → 跳过')
        return 'skipped'
    rc = run(os.path.join(EXE, 'mine.py'), ['split', '--batches', batches(len(cands))])
    if rc:
        return 'failed'
    rc = run(os.path.join(EXE, 'mine.py'), ['gen'])
    if rc:
        return 'failed'
    if os.path.exists(os.path.join(GEN4, 'failed.json')):
        run(os.path.join(EXE, 'mine.py'), ['gen', '--fix-failed', '--per-request', '3'],
            label='mine.py gen --fix-failed')
    left = mine_leftovers()
    dump_needs(NEEDS4, '候选词的词典形/是否成词属于语义判断，判定方没给出一致答案 —— '
                       '交给强模型按本文件补 output_NN.json 后重跑 episode.py', 'entries', left)
    rep['mine']['leftovers'] = len(left)
    if left:
        print('\n[阶段四] 只有 %d 条需要语言模型：%s' % (len(left), rel(NEEDS4)))
        return 'needs_llm'
    rc = run(os.path.join(EXE, 'mine.py'), ['write'])          # 演练：出 dryrun_notes.json
    rep['mine']['payload'] = rel(os.path.join(GEN4, 'dryrun_notes.json'))
    if rc:
        return 'failed'
    if not a.commit:
        print('\n[阶段四] 演练：载荷见 %s，未写库' % rep['mine']['payload'])
        return 'dry'
    before_ids = set(AK.find_notes('note:"Japanese Vocabulary"'))
    rc = run(os.path.join(EXE, 'mine.py'), ['write', '--commit'])
    if rc:
        return 'failed'
    after_ids = set(AK.find_notes('note:"Japanese Vocabulary"'))
    new_ids = sorted(after_ids - before_ids)
    rep['mine']['created'] = len(new_ids)
    a._new_mine_ids = new_ids
    return 'done'


def mine_leftovers():
    """产出与输入对不上的条目（机械判据：形状是否同源、include=false 有没有 reason）。"""
    man = os.path.join(GEN4, 'manifest.json')
    if not os.path.exists(man):
        return []
    out = []
    for m in json.load(open(man, encoding='utf-8')):
        ip, op = os.path.join(GEN4, m['input']), os.path.join(GEN4, m['output'])
        if not os.path.exists(op):
            out.append({'batch': m['batch'], 'why': '还没有产出文件 %s' % m['output']})
            continue
        inp, res = json.load(open(ip, encoding='utf-8')), json.load(open(op, encoding='utf-8'))
        for i, (src, got) in enumerate(zip(inp, res)):
            w1, w2 = src.get('word') or '', got.get('word') or ''
            entry = {'输入候选': w1, '模型给的词': w2,
                     'sentence': (src.get('occurrences') or [{}])[0].get('sentence', '')[:80]}
            if not got.get('include'):
                if not (got.get('reason') or '').strip():
                    out.append(dict(entry, why='include=false 但没写 reason'))
                continue
            if not (w1 == w2 or w1 in w2 or w2 in w1):
                out.append(dict(entry, why='模型把候选改成了别的形状（要词典形，且要能与候选对得上）'))
        if len(inp) != len(res):
            out.append({'batch': m['batch'], 'why': '条数不一致：输入 %d / 产出 %d' % (len(inp), len(res))})
    return out


# ============================================================================
# 阶段五 / 排名字段 / 振假名 / 改标签
# ============================================================================
def stage_audio(a, rep):
    ids = getattr(a, '_new_mine_ids', None)
    if ids:
        args = ['--query', 'nid:' + ','.join(str(i) for i in ids)]
        label = '本次新建的 %d 张' % len(ids)
    elif a.audio_tag:
        args, label = ['--tag', a.audio_tag], '标签 %s' % a.audio_tag
    else:
        # ★ 没有目标就**跳过**，不要回退成"整副素材生词 deck"。
        # 那会把别的集的卡一起扫进来：它们的 Sentence 与来源例句卡对不上时会被判成"无原声"，
        # `apply --commit` 就把已有的 [sound:asbp_*] 原声改写成 TTS 兜底
        # （2026-10-11 实测：素材生词 deck 里 6 张被判"无原声"，其实都挂着原声）。
        print('\n[阶段五] 跳过：本次阶段四没有新建卡，也没给 --audio-tag → 没有配音目标。')
        print('  确实要给整个素材生词 deck 补音频时，显式加 --audio-tag "素材生词::<来源>"；')
        print('  直接跑 mine_audio.py 不给范围就是整副 deck —— 其中"原声配不上来源例句卡"的卡会被降级成 TTS。')
        rep['audio'] = {'scope': '(跳过：无目标)'}
        return 'skipped'
    print('\n[阶段五] 生词配音（%s）' % label)
    rc = run(os.path.join(EXE, 'mine_audio.py'), ['plan'] + args)
    if rc:
        return 'failed'
    rc = run(os.path.join(EXE, 'mine_audio.py'), ['apply'] + args)
    if rc:
        return 'failed'
    if not a.commit:
        print('\n[阶段五] 演练：音频已合成到 output/audio/，未写库')
        return 'dry'
    rc = run(os.path.join(EXE, 'mine_audio.py'), ['apply', '--commit'] + args)
    rep['audio'] = {'scope': label, 'committed': not rc}
    return 'failed' if rc else 'done'


def stage_rank(a, rep):
    print('\n[排名字段] JitenAnimeRank（--all-notes，幂等：只改值不对的）')
    args = ['field', '--plan', JITEN_PLAN, '--all-notes'] + (['--commit'] if a.commit else [])
    rc = run(os.path.join(WSP.ANALYSIS, 'vocab_cover', 'freq_external.py'), args)
    rep['rank'] = {'committed': bool(a.commit and not rc)}
    return 'failed' if rc else ('done' if a.commit else 'dry')


def stage_ruby(a, rep):
    extra = ['--srt', a.srt] if a.srt else (['--plan', a.plan] if a.plan else [])
    print('\n[振假名] 体检：结构不合格 / 读音冲突 / 待复核')
    rc = run(os.path.join(WSP.COMMON, 'ruby_engine.py'),
             ['check', '--query', 'tag:%s' % a.tag] + extra, allow=(0, 1))
    if a.commit:
        rc2 = run(os.path.join(WSP.COMMON, 'ruby_engine.py'),
                  ['apply', '--query', 'tag:%s' % a.tag, '--mode', 'fix', '--fix-ainote',
                   '--commit'] + extra)
        rep['ruby'] = {'fixed': not rc2}
        if rc2:
            return 'failed'
    rep.setdefault('ruby', {})['structural_bad'] = bool(rc)
    return 'done'


def stage_retag(a, rep):
    if not a.input_tag or a.input_tag == a.tag:
        print('\n[改标签] 没有 --input-tag（或与 --tag 相同）→ 跳过')
        return 'skipped'
    n = count('tag:%s' % a.input_tag)
    if not n:
        print('\n[改标签] tag:%s 下已经没有卡（多半是上一次已经改过）→ 跳过' % a.input_tag)
        return 'skipped'
    args = ['--query', 'tag:%s' % a.input_tag, '--remove', a.input_tag, '--add', a.tag]
    if a.commit:
        args.append('--commit')
    rc = run(os.path.join(ONESHOT, 'retag_notes.py'), args)
    rep['retag'] = {'from': a.input_tag, 'to': a.tag, 'committed': bool(a.commit and not rc)}
    return 'failed' if rc else ('done' if a.commit else 'dry')


# ============================================================================
STAGES = [('stage2', stage2), ('mine', stage4), ('audio', stage_audio),
          ('rank', stage_rank), ('ruby', stage_ruby), ('retag', stage_retag)]


def main():
    ap = argparse.ArgumentParser(description='每集流水线驱动（阶段 2–5 一条命令）')
    ap.add_argument('--tag', required=True, help='本集标签（最终标签）')
    ap.add_argument('--input-tag', default=None,
                    help='导入时挂的标签（如 待标记）；给了它会先按它干活，最后换成 --tag')
    ap.add_argument('--phases', default='all',
                    help='要跑的阶段，逗号分隔：%s（默认 all）' % '、'.join(s for s, _ in STAGES))
    ap.add_argument('--commit', action='store_true', help='真写库（不加则全链演练）')
    ap.add_argument('--srt', default=None, help='筛选后的 SRT（字幕自带注音，读音权威来源）')
    ap.add_argument('--plan', default=None, help='filter_subtitle.py 的 plan.json')
    ap.add_argument('--audio-tag', default=None, help='阶段五的补充范围（没有新建卡时用）')
    a = ap.parse_args()

    want = [s.strip() for s in a.phases.split(',') if s.strip()]
    if 'all' in want:
        want = [s for s, _ in STAGES]
    unknown = [s for s in want if s not in dict(STAGES)]
    if unknown:
        raise SystemExit('未知阶段：%s（可选 %s）' % (unknown, [s for s, _ in STAGES]))

    print('=' * 88)
    print('每集流水线驱动 ｜ 集标签 %s ｜ 导入标签 %s' % (a.tag, a.input_tag or '（同集标签）'))
    print('  阶段：%s ｜ 模式：%s' % ('、'.join(want), '★ 真写库' if a.commit else '演练（不写库）'))
    print('  机械问题归代码（ruby_engine / check_*），语义问题才写 needs_llm.json')
    print('=' * 88)

    rep = {'tag': a.tag, 'input_tag': a.input_tag, 'commit': bool(a.commit),
           'started_at': dt.datetime.now().isoformat(timespec='seconds'), 'stages': {}}
    rc = 0
    with AK.guard():
        for name, fn in STAGES:
            if name not in want:
                continue
            status = fn(a, rep['stages'])
            rep['stages'].setdefault(name, {})['status'] = status
            if status == 'failed':
                rc = 1
                break
            if status == 'needs_llm':
                rc = 3
                break

    rep['finished_at'] = dt.datetime.now().isoformat(timespec='seconds')
    rep['exit'] = rc
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    slug = re.sub(r'[^\w\u3040-\u30ff\u4e00-\u9fff]+', '_', a.tag)[:48].strip('_')
    path = os.path.join(RUNS, '%s-%s.json' % (stamp, slug))
    dump(path, rep)

    print('\n' + '=' * 88)
    print('阶段结果：')
    for name, info in rep['stages'].items():
        print('  %-8s %s' % (name, info.get('status')))
    print('运行记录：%s' % rel(path))
    if rc == 3:
        print('★ 只剩语义问题：%s / %s —— 让强模型按里面的条目补产出后重跑本命令'
              % (rel(NEEDS2), rel(NEEDS4)))
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
