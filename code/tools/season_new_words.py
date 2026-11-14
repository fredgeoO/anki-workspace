# -*- coding: utf-8 -*-
"""每季生词提取：给一季字幕目录，挑出这一季值得学的 550–800 个新词。

和 ``today-new`` 的分工
----------------------
* ``today-new`` 是**每天**的 30 个词，打 ``今天学习生词``，服务于当天的讲义/学习。
* 本脚本是**每季一次**的盘子：把整季 12–13 集过一遍，按「先通用、后作品」两层
  挑出一个季度的学习池（默认 550–800 个词），写清单；只有显式 ``--commit``
  才给这些词打季标签 ``本季生词::<作品>``。

筛选口径（2026-11-13 定）
-------------------------
1. **通用层**：``JitenAnimeRank <= 12000``（每词每季至少遇到一次）且本季出现、
   还没学（按笔记）、有 JAR 排名的词 → **全部优先收录**，按 Jiten 名次升序。
2. **作品层**：``12001 <= JitenAnimeRank <= 24000`` 且本季出现 ``>= 3`` 次
   （作品设定词/角色语在这里）→ 按本季出现次数降序补到上限。
3. **数量动态**：先收通用层，再用作品层补到 ``--max-words``（默认 800）；
   若总数不足 ``--min-words``（默认 550），自动放宽作品层（次数 3→2→1、
   Jiten 上限 24000→30000），放宽过程写进报告。**不硬凑、不写死**。
4. 超过 24000 名且本季只出现一两次的词不进池子 —— 那是「一辈子遇不到几十次」的
   静态成本收不回来的词（见 docs/reports/词频停止点与打标说明.md）。

边界
----
* 只读字幕与 Anki 词库；**不碰调度列**（due/ivl/factor/type/queue/reps/lapses）、
  不改字段、不建卡、不配音、不动专有词汇。
* 默认**只出清单不写库**；``--commit`` 才打季标签（写前备份、写后回读）。
* 标签默认 ``本季生词::<目录名>``（空格等替换成下划线），可用 ``--tag`` 覆盖。

用法
----
::

    # 只看清单（不写库）
    $PY code\\tools\\season_new_words.py "subtitles\\Sousou no Frieren"

    # 真写季标签
    $PY code\\tools\\season_new_words.py "subtitles\\Sousou no Frieren" --commit

    # 调口径：只收 Jiten<=10000，作品层要出现 >=5 次，最多 700 个
    $PY code\\tools\\season_new_words.py "subtitles\\Yuru Camp" ^
        --jiten-max 10000 --work-min-count 5 --max-words 700

    # 清空 / 回退一个季标签
    $PY code\\tools\\season_new_words.py "subtitles\\Yuru Camp" --clear --commit
    $PY code\\tools\\season_new_words.py --revert --commit

产物
----
* ``data/daily_new/season/<slug>.json`` —— 机器可读清单（面板消费）
* ``output/daily/season_new_<slug>.md`` —— 人读清单
* ``data/daily_new/season/state.json`` —— 上一次 commit 前的标签集合（--revert 用）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, _HERE)

import anki_api as AK            # noqa: E402  Anki 唯一通道
import paths as WSP              # noqa: E402  工作区路径
import textio                    # noqa: E402  UTF-8 唯一入口
import today_new_words as TN     # noqa: E402  复用候选/字段/统计
import subtitle_new_words as SW  # noqa: E402

# ============================================================================
# 配置（默认值来自 2026-11-13 的 19 部 12–13 集实测结论）
# ============================================================================
DEFAULT_JITEN_MAX = 12000          # 通用层上限：每词每季至少遇到一次
DEFAULT_WORK_JITEN_MIN = 12001     # 作品层起点（紧随通用层）
DEFAULT_WORK_JITEN_MAX = 24000     # 作品层上限：累计覆盖约 95%，再往后不值得做卡
DEFAULT_WORK_MIN_COUNT = 3         # 作品层要求本季出现次数
DEFAULT_MIN_WORDS = 550            # 每季目标下限
DEFAULT_MAX_WORDS = 800            # 每季目标上限
WORK_JITEN_HARD_MAX = 30000        # 候选不足时作品层最多放宽到这里
TAG_PREFIX = '本季生词::'
SEASON_DIR = os.path.join(WSP.DATA, 'daily_new', 'season')
STATE_PATH = os.path.join(SEASON_DIR, 'state.json')
OUTPUT_DIR = os.path.join(WSP.OUTPUT, 'daily')


def slug_of(path):
    """目录名 → 安全的文件名/标签片段（空格、路径分隔符、引号都换掉）。"""
    name = os.path.basename(os.path.normpath(str(path)))
    name = re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_')
    return name or 'season'


def default_tag(path):
    return TAG_PREFIX + slug_of(path)


def layer_of(item, jiten_max, work_min, work_max, work_min_count):
    """纯函数：一个候选属于通用层 / 作品层 / 池外。"""
    jar = int(item.get('jiten') or TN.UNRANKED)
    if jar <= int(jiten_max):
        return 'common'
    if (int(work_min) <= jar <= int(work_max)
            and int(item.get('occurrences') or 0) >= int(work_min_count)):
        return 'work'
    return 'out'


def _common_items(items, jiten_max):
    return [it for it in items
            if it.get('kind') != 'particle'
            and layer_of(it, jiten_max, 0, 0, 10**9) == 'common']


def _work_items(items, work_min, work_max, work_min_count):
    return [it for it in items
            if it.get('kind') != 'particle'
            and layer_of(it, -1, work_min, work_max, work_min_count) == 'work']


def is_noise(item):
    """只出现 1 次、且 Anki 标为惯用句/成句/词缀/代词的词 → 语气/拟声/切分碎片。

    本季出现 ≥2 次的同 tag 词保留（如 ただいま 出现 6 次，是真实对白用语）。
    """
    if int(item.get('occurrences') or 0) > 1:
        return False
    return bool(SW._bad_anki_pos(item.get('pos') or ''))


def annotate_items(items, index):
    """给候选补展示字段（读音/词性/牌组），并把噪声词剔掉。"""
    kept = []
    for it in items:
        TN.describe(it, index)
        if is_noise(it):
            continue
        kept.append(it)
    return kept


def plan_season(items, jiten_max=DEFAULT_JITEN_MAX,
                work_jiten_min=DEFAULT_WORK_JITEN_MIN,
                work_jiten_max=DEFAULT_WORK_JITEN_MAX,
                work_min_count=DEFAULT_WORK_MIN_COUNT,
                min_words=DEFAULT_MIN_WORDS, max_words=DEFAULT_MAX_WORDS):
    """候选 → (入选词, 口径明细)。纯函数，测试直接喂。

    规则（见模块 docstring）：通用层全收（Jiten 升序）→ 作品层按出现次数补到
    ``max_words``；不足 ``min_words`` 时逐级放宽作品层。**永远不超过 max_words。**
    """
    max_words = max(0, int(max_words))
    min_words = max(0, int(min_words))

    def attempt(work_hi, work_minc):
        common = sorted(_common_items(items, jiten_max),
                        key=lambda it: (-int(it['occurrences']), int(it['jiten']), it['word']))
        work = sorted(_work_items(items, work_jiten_min, work_hi, work_minc),
                      key=lambda it: (-int(it['occurrences']), int(it['jiten']), it['word']))
        picked = common[:max_words]
        if len(picked) < max_words:
            picked = picked + work[:max_words - len(picked)]
        return common, work, picked

    common, work, picked = attempt(work_jiten_max, work_min_count)
    used_hi, used_minc = int(work_jiten_max), int(work_min_count)
    relax = []

    while len(picked) < min_words:
        if used_minc > 1:
            nxt = 2 if used_minc >= 3 else 1
            relax.append({'from': used_minc, 'to': nxt,
                          'why': '总数不足 %d，作品层出现次数放宽到 >=%d' % (min_words, nxt)})
            used_minc = nxt
        elif used_hi < WORK_JITEN_HARD_MAX:
            relax.append({'from': used_hi, 'to': WORK_JITEN_HARD_MAX,
                          'why': '总数仍不足 %d，作品层 Jiten 上限放宽到 %d'
                                 % (min_words, WORK_JITEN_HARD_MAX)})
            used_hi = WORK_JITEN_HARD_MAX
        else:
            break
        common, work, picked = attempt(used_hi, used_minc)

    tagged = []
    for it in picked:
        row = dict(it)
        row['layer'] = layer_of(it, jiten_max, work_jiten_min, used_hi, used_minc)
        tagged.append(row)

    meta = {
        'jiten_max': int(jiten_max),
        'work_jiten_min': int(work_jiten_min),
        'work_jiten_max': int(used_hi),
        'work_min_count': int(used_minc),
        'common_total': len(common),
        'work_total': len(work),
        'picked': len(picked),
        'min_words': min_words,
        'max_words': max_words,
        'truncated': (len(common) + len(work)) > max_words,
        'relaxed': relax,
    }
    return tagged, meta


# ============================================================================
# 输入 / 输出
# ============================================================================
def season_sources(path):
    """一季 = 一个字幕目录（目录下所有字幕，不递归子目录）。"""
    if not os.path.isdir(path):
        raise SystemExit('每季生词需要字幕目录（一个目录 = 一季）：%s' % path)
    sources = TN.episode_sources(path)
    if len(sources) < 2:
        raise SystemExit('目录里只有 %d 个字幕文件，不像一季：%s'
                         % (len(sources), path))
    return sources


def _rel(path):
    try:
        return os.path.relpath(path, WSP.ROOT).replace('\\', '/')
    except ValueError:
        return path


def picked_row(item):
    """清单一行（JSON / 面板共用）。"""
    first = item.get('first') or {}
    return {
        'word': item.get('word') or '',
        'reading': item.get('reading') or SW.word_reading(item.get('word') or ''),
        'pos': item.get('pos') or '',
        'deck': item.get('deck') or '',
        'level': item.get('level') or '',
        'jiten': int(item.get('jiten') or 0),
        'occurrences': int(item.get('occurrences') or 0),
        'episodes': int(item.get('episodes') or 0),
        'layer': item.get('layer') or '',
        'first': {'episode': first.get('episode') or '',
                  'index': first.get('index'),
                  'start': first.get('start'),
                  'text': first.get('text') or ''},
        'notes': [int(x) for x in (item.get('notes') or [])],
    }


def build_payload(source, sources, params, meta, skipped, picked, plan=None,
                  write=None, tag='', candidates=0):
    rows = [picked_row(it) for it in picked]
    common = [r for r in rows if r['layer'] == 'common']
    work = [r for r in rows if r['layer'] == 'work']
    return {
        'schema': 1,
        'tool': 'season-new',
        'ok': True,
        'exit_code': 0,
        'source': source,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'window': {'episodes': len(sources),
                   'labels': [label for label, _ in sources]},
        'params': params,
        'counts': {
            'episodes': len(sources),
            'candidates': int(candidates),
            'common': len(common),
            'work': len(work),
            'picked': len(rows),
            'notes': sum(len(r['notes']) for r in rows),
            'skipped_no_rank': len(skipped.get('no_rank') or []),
            'skipped_notes': len(skipped.get('no_notes') or []),
            'skipped_reading': len(skipped.get('reading') or []),
        },
        'meta': meta,
        'tag': tag,
        'picked': rows,
        'plan': plan,
        'write': write,
        'artifacts': None,
    }


def _md_cell(text, limit=42):
    value = str(text or '').replace('|', '\\|').replace('\n', ' ')
    return value[:limit] + ('…' if len(value) > limit else '')


def report_md(source, sources, params, meta, picked, tag=''):
    rows = [picked_row(it) for it in picked]
    common = [r for r in rows if r['layer'] == 'common']
    work = [r for r in rows if r['layer'] == 'work']

    def table(rows_):
        out = ['| # | 词形 | 读音 | JAR | 本季次数 | 集数 | 首句 |',
               '|---|---|---|---|---|---|---|']
        for i, r in enumerate(rows_, 1):
            out.append('| %d | %s | %s | %s | %d | %d | %s |' % (
                i, _md_cell(r['word'], 24), _md_cell(r['reading'], 24),
                r['jiten'] or '—', r['occurrences'], r['episodes'],
                _md_cell((r['first'] or {}).get('text') or '', 34)))
        return out

    lines = [
        '# 每季生词：%s' % os.path.basename(os.path.normpath(source)),
        '',
        '> 生成时间 %s · %d 集 · 目标 %d–%d 个词 · 标签 `%s`'
        % (dt.datetime.now().strftime('%Y-%m-%d %H:%M'), len(sources),
           meta['min_words'], meta['max_words'], tag or '（本次未写）'),
        '',
        '## 构成',
        '',
        '| 层 | 口径 | 收录 |',
        '|---|---|---|',
        '| 通用层 | Jiten ≤ %d | %d 个 |' % (meta['jiten_max'], len(common)),
        '| 作品层 | Jiten %d–%d 且本季出现 ≥ %d 次 | %d 个 |'
        % (meta['work_jiten_min'], meta['work_jiten_max'],
           meta['work_min_count'], len(work)),
        '| **合计** | | **%d 个 / %d 张笔记** |'
        % (len(rows), sum(len(r['notes']) for r in rows)),
        '',
    ]
    if meta.get('relaxed'):
        lines.append('放宽记录：')
        for r in meta['relaxed']:
            lines.append('- %s（%s → %s）' % (r['why'], r['from'], r['to']))
        lines.append('')
    lines.append('候选不足时不会硬凑到下限；超过上限时按层内顺序截断。')
    lines.append('')
    lines.append('## 通用层（先学）')
    lines.append('')
    lines.extend(table(common) if common else ['（本季没有未学的通用层词。）'])
    lines.append('')
    lines.append('## 作品层（再补）')
    lines.append('')
    lines.extend(table(work) if work else ['（本季没有符合条件的作品层词。）'])
    lines.append('')
    return '\n'.join(lines)


def write_outputs(source, sources, params, meta, skipped, picked, plan=None,
                  write=None, tag='', candidates=0):
    slug = slug_of(source)
    os.makedirs(SEASON_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(SEASON_DIR, slug + '.json')
    md_path = os.path.join(OUTPUT_DIR, 'season_new_%s.md' % slug)
    payload = build_payload(source, sources, params, meta, skipped, picked,
                            plan=plan, write=write, tag=tag,
                            candidates=candidates)
    textio.dump_json(payload, json_path)
    textio.write_text(md_path, report_md(source, sources, params, meta,
                                         picked, tag=tag))
    return payload, json_path, md_path


# ============================================================================
# 主流程
# ============================================================================
def _tag_query(tag):
    return 'tag:"%s"' % tag


def do_pick(a, out=None):
    result = out if out is not None else {}
    sources = season_sources(a.input)
    index = SW.VocabIndex.load(scopes=TN.SCOPES)
    stats = TN.collect_stats(sources, index, include_names=a.include_names)
    items, skipped = TN.build_candidates(stats, index)
    before_filter = len(items)
    items = annotate_items(items, index)
    noise_removed = before_filter - len(items)
    picked, meta = plan_season(
        items, jiten_max=a.jiten_max, work_jiten_min=a.work_jiten_min,
        work_jiten_max=a.work_jiten_max, work_min_count=a.work_min_count,
        min_words=a.min_words, max_words=a.max_words)
    meta['noise_removed'] = noise_removed

    tag = (a.tag or default_tag(a.input)).strip()
    params = {
        'jitenMax': int(a.jiten_max),
        'workJitenMin': int(a.work_jiten_min),
        'workJitenMax': int(a.work_jiten_max),
        'workMinCount': int(a.work_min_count),
        'minWords': int(a.min_words),
        'maxWords': int(a.max_words),
        'includeNames': bool(a.include_names),
        'commit': bool(a.commit),
    }

    print('来源：%s' % a.input)
    print('窗口：%d 集（整季目录）' % len(sources))
    print('候选：%d 个词（有 JAR 排名、有未学笔记）' % len(items))
    print('  排除：无 JAR 排名 %d / 没有未学笔记 %d / 读音对不上 %d / 语气拟声 %d'
          % (len(skipped.get('no_rank') or []), len(skipped.get('no_notes') or []),
             len(skipped.get('reading') or []), noise_removed))
    print('口径：通用层 Jiten≤%d；作品层 %d–%d 且出现≥%d；目标 %d–%d 个'
          % (a.jiten_max, a.work_jiten_min, a.work_jiten_max,
             a.work_min_count, a.min_words, a.max_words))
    print('分层：通用层 %d 个 / 作品层 %d 个；本季收录 %d 个'
          % (meta['common_total'], meta['work_total'], meta['picked']))
    for r in meta.get('relaxed') or []:
        print('  放宽：%s（%s → %s）' % (r['why'], r['from'], r['to']))
    print('名单：%d 个词 / %d 张笔记（上限 %d）'
          % (len(picked), sum(len(it['notes']) for it in picked), a.max_words))

    if not picked:
        print('')
        print('没有可收录的词：本季候选不足，或都已学过。')
        payload, json_path, md_path = write_outputs(
            a.input, sources, params, meta, skipped, picked, tag=tag,
            candidates=len(items))
        result.update(payload)
        result.update({'ok': False, 'exit_code': 2,
                       'error': '没有可收录的词：本季候选不足，或都已学过。',
                       'artifacts': {'season_json': _rel(json_path),
                                     'report_md': _rel(md_path)}})
        return 2

    # 清单先落盘（演练也写，方便查看）；写库是另一回事。
    payload, json_path, md_path = write_outputs(
        a.input, sources, params, meta, skipped, picked, tag=tag,
        candidates=len(items))

    if not a.commit:
        print('')
        print('清单：%s' % _rel(md_path))
        print('数据：%s' % _rel(json_path))
        print('模式：演练（不写库；加 --commit 才给这些词打季标签）')
        payload.update({'ok': True, 'exit_code': 0, 'commit': False,
                        'dry_run': True,
                        'write': {'committed': False, 'verified': None,
                                  'removed': 0, 'added': 0, 'tagged': 0},
                        'artifacts': {'season_json': _rel(json_path),
                                      'report_md': _rel(md_path)}})
        textio.dump_json(payload, json_path)
        result.update(payload)
        return 0

    # ---- 写库：先现场复核，再写标签 ----
    picked, dropped = TN.live_check(picked)
    if dropped:
        print('')
        print('现场复核剔除：')
        for word, nid, why in dropped[:20]:
            print('  ⛔ %-10s %s%s' % (word, '' if nid is None else '（note %s）' % nid, why))
        if len(dropped) > 20:
            print('  … 共 %d 条' % len(dropped))
    if not picked:
        print('现场复核后没有可用的词：本次不改库。')
        result.update({'ok': False, 'exit_code': 2,
                       'error': '现场复核后没有可用的词：本次不改库。'})
        return 2

    old = set(int(x) for x in AK.find_notes(_tag_query(tag)))
    note_ids = sorted({int(nid) for it in picked for nid in it['notes']})
    plan = TN.diff_ids(old, note_ids)
    print('')
    print('标签：%s' % tag)
    print('旧标签：%d 个；保留 %d；摘除 %d；新增 %d'
          % (len(plan['old']), len(plan['keep']), len(plan['remove']), len(plan['add'])))

    os.makedirs(SEASON_DIR, exist_ok=True)
    textio.dump_json({
        'tag': tag,
        'source': a.input,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'before': plan['old'],
        'after': plan['new'],
    }, STATE_PATH)

    if plan['remove']:
        AK.remove_tags(plan['remove'], [tag])
    if plan['add']:
        AK.add_tags(plan['add'], [tag])

    after = set(int(x) for x in AK.find_notes(_tag_query(tag)))
    ok = after == set(plan['new'])
    print('')
    print('=' * 88)
    print('写入结果')
    print('=' * 88)
    print('  摘除 %d 个；新增 %d 个；当前「%s」共 %d 个'
          % (len(plan['remove']), len(plan['add']), tag, len(after)))
    print('  回读校验%s' % ('通过' if ok else '失败'))
    if not ok:
        print('  先跑 --revert --commit 恢复，再把缺失/多出的 noteId 报给用户。')

    payload.update({
        'ok': bool(ok), 'exit_code': 0 if ok else 1,
        'commit': True, 'dry_run': False,
        'plan': {'old': len(plan['old']), 'new': len(plan['new']),
                 'keep': len(plan['keep']), 'remove': len(plan['remove']),
                 'add': len(plan['add'])},
        'write': {'committed': True, 'verified': bool(ok),
                  'removed': len(plan['remove']), 'added': len(plan['add']),
                  'tagged': len(after)},
        'artifacts': {'season_json': _rel(json_path),
                      'report_md': _rel(md_path)},
    })
    textio.dump_json(payload, json_path)
    result.update(payload)
    print('')
    print('清单：%s' % _rel(md_path))
    print('数据：%s' % _rel(json_path))
    print('Anki 浏览器搜索：tag:"%s"' % tag)
    print('回退：python code\\tools\\season_new_words.py --revert --commit')
    return 0 if ok else 1


def do_clear(a):
    tag = (a.tag or (default_tag(a.input) if a.input else '')) or ''
    if not tag:
        raise SystemExit('--clear 需要 --tag，或给一个字幕目录（用默认季标签名）')
    old = set(int(x) for x in AK.find_notes(_tag_query(tag)))
    print('清空季标签：%s' % tag)
    print('当前命中 %d 个笔记' % len(old))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    if not a.commit:
        return 0
    textio.dump_json({
        'tag': tag, 'source': a.input or '--clear',
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'before': sorted(old), 'after': [],
    }, STATE_PATH)
    if old:
        AK.remove_tags(sorted(old), [tag])
    after = set(int(x) for x in AK.find_notes(_tag_query(tag)))
    print('已摘除 %d 个；当前剩 %d 个' % (len(old) - len(after), len(after)))
    return 0 if not after else 1


def do_revert(a):
    if not os.path.exists(STATE_PATH):
        raise SystemExit('找不到回退记录 %s（先确认确实用本脚本 --commit 过）' % STATE_PATH)
    st = textio.load_json(STATE_PATH)
    tag = st.get('tag') or ''
    before = [int(x) for x in (st.get('before') or [])]
    if not tag:
        raise SystemExit('回退记录里没有标签名；停手问用户。')
    old = set(int(x) for x in AK.find_notes(_tag_query(tag)))
    plan = TN.diff_ids(old, before)
    print('回退：恢复到上一次运行前的「%s」集合' % tag)
    print('当前 %d 个 → 目标 %d 个；摘除 %d；补回 %d'
          % (len(old), len(before), len(plan['remove']), len(plan['add'])))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    if not a.commit:
        return 0
    if plan['remove']:
        AK.remove_tags(plan['remove'], [tag])
    if plan['add']:
        alive = set(AK.notes_map(plan['add']))
        add = [nid for nid in plan['add'] if nid in alive]
        if add:
            AK.add_tags(add, [tag])
    after = set(int(x) for x in AK.find_notes(_tag_query(tag)))
    ok = after == set(before)
    st['reverted_at'] = dt.datetime.now().isoformat(timespec='seconds')
    st['after_actual'] = sorted(after)
    textio.dump_json(st, STATE_PATH)
    print('回读校验%s；当前 %d 个' % ('通过' if ok else '失败', len(after)))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='每季生词提取：一季字幕目录 → 550–800 个该学的新词清单（可选打季标签）')
    ap.add_argument('input', nargs='?', default=None,
                    help='一季的字幕目录（--clear/--revert 时可省）')
    ap.add_argument('--jiten-max', type=int, default=DEFAULT_JITEN_MAX,
                    help='通用层 Jiten 上限（默认 %d）' % DEFAULT_JITEN_MAX)
    ap.add_argument('--work-jiten-min', type=int, default=DEFAULT_WORK_JITEN_MIN,
                    help='作品层 Jiten 下限（默认 %d）' % DEFAULT_WORK_JITEN_MIN)
    ap.add_argument('--work-jiten-max', type=int, default=DEFAULT_WORK_JITEN_MAX,
                    help='作品层 Jiten 上限（默认 %d；候选不足时自动放宽到 %d）'
                         % (DEFAULT_WORK_JITEN_MAX, WORK_JITEN_HARD_MAX))
    ap.add_argument('--work-min-count', type=int, default=DEFAULT_WORK_MIN_COUNT,
                    help='作品层要求本季出现次数（默认 %d）' % DEFAULT_WORK_MIN_COUNT)
    ap.add_argument('--min-words', type=int, default=None,
                    help='每季目标下限（默认 %d；候选不足不硬凑；'
                         '--max-words 更小时自动跟着变小）' % DEFAULT_MIN_WORDS)
    ap.add_argument('--max-words', type=int, default=DEFAULT_MAX_WORDS,
                    help='每季目标上限（默认 %d）' % DEFAULT_MAX_WORDS)
    ap.add_argument('--include-names', action='store_true',
                    help='保留人名/专有名词（默认过滤）')
    ap.add_argument('--tag', default='',
                    help='季标签名（默认 本季生词::<目录名>）')
    ap.add_argument('--clear', action='store_true', help='清空一个季标签')
    ap.add_argument('--revert', action='store_true', help='恢复到上一次 --commit 前的标签集合')
    ap.add_argument('--json', action='store_true',
                    help='stdout 输出机器可读 JSON（人读日志转到 stderr）')
    ap.add_argument('--commit', action='store_true',
                    help='真写季标签（不加则只出清单，不写库）')
    a = ap.parse_args(argv)

    if a.clear and a.revert:
        ap.error('--clear 与 --revert 只能选一个')
    if not a.clear and not a.revert:
        if not a.input:
            ap.error('需要一季的字幕目录；--clear/--revert 才可省略')
        if a.min_words is None:
            a.min_words = min(DEFAULT_MIN_WORDS, a.max_words)
        if a.min_words < 0 or a.max_words < 0 or a.min_words > a.max_words:
            ap.error('要求 0 <= --min-words <= --max-words')
        if a.jiten_max < 0 or a.work_jiten_min < 0 or a.work_jiten_max < 0:
            ap.error('Jiten 名次参数不能为负')

    with AK.guard():
        if a.json:
            out = {}
            mode = 'clear' if a.clear else ('revert' if a.revert else 'pick')
            real_stdout = sys.stdout
            sys.stdout = sys.stderr
            try:
                if a.clear:
                    code = do_clear(a)
                elif a.revert:
                    code = do_revert(a)
                else:
                    code = do_pick(a, out)
            finally:
                sys.stdout = real_stdout
            if mode != 'pick':
                out = {'schema': 1, 'tool': 'season-new', 'mode': mode,
                       'ok': code == 0, 'exit_code': code, 'source': a.input}
            out.setdefault('mode', mode)
            out.setdefault('ok', code == 0)
            out.setdefault('exit_code', code)
            sys.stdout.flush()
            print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
            return code
        if a.clear:
            return do_clear(a)
        if a.revert:
            return do_revert(a)
        return do_pick(a)


if __name__ == '__main__':
    raise SystemExit(main())
