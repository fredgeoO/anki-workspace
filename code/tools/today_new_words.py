# -*- coding: utf-8 -*-
"""每天从一段文字/字幕里挑 N 个「今天要学」的生词，只打一个标签 ``今天学习生词``。

它解决的是什么
-------------
「今天学哪 N 个词」每天都要重新决定。本工具把这件事固定成一条可复跑的命令：

1. 从给定文字/字幕里找出 Anki 词汇卡组里**已有、但还没学过**的词
   （口径与 ``subtitle_new_words`` 完全一致：该词所有卡都是新卡 ``type == 0``）；
2. 按 ``JitenAnimeRank`` **升序**（数字越小 = 动漫里出现频率越高 = 越优先）取前 N 个；
   没有排名的词（空 / ``999999``）排在最后，只在名额没满时补位；
3. **先把全库旧的 ``今天学习生词`` 摘掉，再给今天选中的 N 个打上**，
   保证这个标签下的笔记数永远不超过 N（全量替换，同一天重跑也以最后一次为准）。

边界
----
* 只写 ``tags``：**不碰** ``due`` / ``ivl`` / ``factor`` / ``type`` / ``queue`` / ``reps`` / ``lapses``；
* 不改任何字段、不改牌组、不建卡、不配音、不动 ``3-专有词汇``；
* 一个词只标一张代表卡（core6000 / 考级 > 素材生词；新卡优先）；
* 已带 ``复习::*`` 的词仍可入选（今天学习集与字幕复习集互相独立）；
* 默认演练，显式 ``--commit`` 才真写。

用法
----
::

    # 演练（默认，不写库）
    $PY code\\tools\\today_new_words.py "字幕.srt"

    # 真写：先摘旧标签，再给今天 N 个打标签
    $PY code\\tools\\today_new_words.py "字幕.srt" --n 30 --commit

    # 纯文本 / 粘贴文字
    $PY code\\tools\\today_new_words.py "note.txt" --commit
    Get-Content draft.txt -Encoding UTF8 | & $PY code\\tools\\today_new_words.py - --commit

    # 只清空这个标签（不动别的 tag）
    $PY code\\tools\\today_new_words.py --clear --commit

    # 撤销上一次运行：恢复运行前的标签集合
    $PY code\\tools\\today_new_words.py --revert --commit

产物
----
* ``data/daily_new/<日期>/picked.json`` —— 本次候选 / 入选 / 剔除的机器可读记录
* ``output/daily/today_new_words.md`` —— 给人看的稳定路径报告
* ``data/daily_new/state.json`` —— 回退记录（运行前 / 运行后的 noteId 集合）
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, _HERE)

import anki_api as AK            # noqa: E402  Anki 唯一通道
import jp_decks as JD            # noqa: E402  牌组常量
import paths as WSP              # noqa: E402  工作区路径
import textio                    # noqa: E402  UTF-8 唯一入口
import subtitle_new_words as SW  # noqa: E402  字幕解析 / 词表匹配

# ============================================================================
# 配置
# ============================================================================
TAG = '今天学习生词'
UNRANKED = 999999
DEFAULT_N = 30
SCOPES = (JD.DECK_MINED, JD.DECK_CORE6000, JD.DECK_KAOKYU)   # 三个词汇卡组
DATA_ROOT = os.path.join(WSP.DATA, 'daily_new')
STATE_PATH = os.path.join(DATA_ROOT, 'state.json')
REPORT_PATH = os.path.join(WSP.OUTPUT, 'daily', 'today_new_words.md')


# ============================================================================
# 纯函数（不碰 Anki，测试直接喂）
# ============================================================================
def rank_of(word, index):
    """该词所有笔记里的最小 JitenAnimeRank；没有（或 999999）→ UNRANKED。"""
    best = UNRANKED
    for e in index.entries.get(word, ()):
        try:
            j = int(e.jiten or UNRANKED)
        except (TypeError, ValueError):
            j = UNRANKED
        if 0 < j < best:
            best = j
    return best


def rank_key(item):
    """Jiten 升序；无排名最后；同排名按本段出现次数降序，再按词形。"""
    r = int(item.get('jiten') or UNRANKED)
    ranked = r < UNRANKED
    return (0 if ranked else 1,
            r if ranked else 0,
            -int(item.get('occurrences') or 0),
            item.get('word') or '')


def select_words(words, index, n=DEFAULT_N):
    """词表 → 按优先级排好的前 N 个（``n <= 0`` 表示不截断）。"""
    items = []
    for w in words:
        it = dict(w)
        it['jiten'] = rank_of(w['word'], index)
        items.append(it)
    items.sort(key=rank_key)
    return items[:n] if n and n > 0 else items


def diff_ids(old_ids, new_ids):
    """旧标签集合 vs 今天入选集合 → 摘除 / 保留 / 新增。"""
    old, new = set(int(x) for x in old_ids), set(int(x) for x in new_ids)
    return {
        'old': sorted(old),
        'new': sorted(new),
        'remove': sorted(old - new),
        'keep': sorted(old & new),
        'add': sorted(new - old),
    }


def fmt_rank(r):
    return '—' if int(r or UNRANKED) >= UNRANKED else str(int(r))


# ============================================================================
# 候选与现场复核
# ============================================================================
def load_candidates(source, index):
    """文字/字幕 → 候选词（Anki 已有、所有卡都是新卡）。"""
    result = SW.extract(source, scopes=SCOPES, index=index, quiet=True)
    return result


def live_filter(items):
    """现场复核：卡还在、且 type==0。→ (保留, [(item, 原因)])。"""
    if not items:
        return [], []
    cmap = {int(c['cardId']): c
            for c in AK.cards_info([it['cardId'] for it in items])}
    kept, dropped = [], []
    for it in items:
        c = cmap.get(int(it['cardId']))
        if c is None:
            dropped.append((it, '卡已不存在'))
        elif int(c['type']) != 0:
            dropped.append((it, '已不是新卡（type=%s）' % c['type']))
        else:
            kept.append(it)
    return kept, dropped


def tagged_note_ids():
    return sorted(int(x) for x in AK.find_notes('tag:"%s"' % TAG))


# ============================================================================
# 输出
# ============================================================================
def _first_text(w, limit=42):
    text = ((w.get('first') or {}).get('text') or '').replace('\n', ' ')
    return text if len(text) <= limit else text[:limit] + '…'


def print_picked(items):
    if not items:
        return
    print('')
    print('今天要学的词（Jiten 数字越小越优先）：')
    for i, w in enumerate(items, 1):
        first = _first_text(w)
        print('  %2d. %-10s %-10s Jiten %-7s ｜%d 次｜%s%s'
              % (i, w['word'], w.get('reading') or '—', fmt_rank(w.get('jiten')),
                 int(w.get('occurrences') or 0),
                 (w.get('deck') or '').split('::')[-1],
                 ('｜「%s」' % first) if first else ''))


def _report_md(source, result, picked, dropped, plan, n, counts):
    meta = result['meta']
    c = counts
    lines = [
        '# 今天学习生词 · %s' % dt.date.today().isoformat(),
        '',
        '- 来源：`%s`' % source,
        '- 生成：%s' % meta['generated_at'],
        '- 上限：%d 个；候选：%d 个；入选：%d 个' % (n, c['candidates'], len(picked)),
        '- 旧标签：%d 个（保留 %d / 摘除 %d）；本次新增 %d'
        % (len(plan['old']), len(plan['keep']), len(plan['remove']), len(plan['add'])),
        '- 排序：`JitenAnimeRank` 升序；无排名（—）排最后，名额没满才补位',
        '',
        '## 今天要学',
        '',
        '| # | 词 | 读音 | Jiten | 本段次数 | 牌组 | 首句 |',
        '|---|---|---|---:|---:|---|---|',
    ]
    for i, w in enumerate(picked, 1):
        lines.append('| %d | %s | %s | %s | %d | %s | %s |' % (
            i, w['word'], w.get('reading') or '', fmt_rank(w.get('jiten')),
            int(w.get('occurrences') or 0),
            (w.get('deck') or '').split('::')[-1],
            _first_text(w, 60).replace('|', '\\|')))
    lines += ['']
    if dropped:
        lines += ['## 现场复核被剔除', '']
        for it, why in dropped:
            lines.append('- %s：%s' % (it['word'], why))
        lines += ['']
    if c['unranked']:
        lines += ['> 本次入选里有 %d 个词没有 Jiten 排名（显示 —），是名额没满时的补位。'
                  % c['unranked'], '']
    lines += [
        '> 回退：`python code\\tools\\today_new_words.py --revert --commit`',
        '> 清空：`python code\\tools\\today_new_words.py --clear --commit`',
        '',
    ]
    return '\n'.join(lines)


def write_outputs(source, result, picked, dropped, plan, n, counts):
    today = dt.date.today().isoformat()
    out_dir = os.path.join(DATA_ROOT, today)
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, 'picked.json')
    textio.dump_json({
        'tag': TAG,
        'source': source,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'n': n,
        'counts': counts,
        'plan': {'old': len(plan['old']), 'keep': len(plan['keep']),
                 'remove': len(plan['remove']), 'add': len(plan['add'])},
        'picked': [{
            'word': w['word'], 'reading': w.get('reading') or '',
            'pos': w.get('pos') or '', 'deck': w.get('deck') or '',
            'level': w.get('level') or '', 'occurrences': int(w.get('occurrences') or 0),
            'jiten': int(w.get('jiten') or UNRANKED), 'noteId': int(w['noteId']),
            'cardId': int(w['cardId']),
            'first': w.get('first'),
        } for w in picked],
        'dropped': [{'word': it['word'], 'reason': why} for it, why in dropped],
    }, json_path)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    textio.write_text(REPORT_PATH, _report_md(source, result, picked, dropped,
                                              plan, n, counts))
    return json_path, REPORT_PATH


# ============================================================================
# 主流程
# ============================================================================
def do_pick(a):
    index = SW.VocabIndex.load(scopes=SCOPES)
    result = load_candidates(a.input, index)
    words = result['words']

    all_ranked = select_words(words, index, 0)
    all_live, dropped = live_filter(all_ranked)
    picked = all_live[:a.n] if a.n and a.n > 0 else all_live

    counts = {
        'candidates': len(words),
        'eligible_live': len(all_live),
        'picked': len(picked),
        'unranked': sum(1 for w in picked
                        if int(w.get('jiten') or UNRANKED) >= UNRANKED),
    }

    plan = diff_ids(tagged_note_ids(), [w['noteId'] for w in picked])

    print('来源：%s' % a.input)
    print('候选：%d 个（Anki 已有、所有卡都是新卡）' % counts['candidates'])
    print('现场复核后可用：%d 个；入选：%d 个（上限 %d）'
          % (counts['eligible_live'], len(picked), a.n))
    print('旧标签：%d 个；保留 %d；摘除 %d；新增 %d'
          % (len(plan['old']), len(plan['keep']),
             len(plan['remove']), len(plan['add'])))
    print_picked(picked)

    if dropped:
        print('')
        print('现场复核剔除：')
        for it, why in dropped[:20]:
            print('  ⛔ %-10s %s' % (it['word'], why))
        if len(dropped) > 20:
            print('  … 共 %d 个' % len(dropped))

    if not picked:
        print('')
        print('没有可选的词：本次不改库，旧的「%s」原样保留。' % TAG)
        print('（若确实要清空，显式加 --clear --commit。）')
        return 2

    print('')
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    if not a.commit:
        print('演练结束，未写库。')
        print('（回退记录会写到 %s）' % STATE_PATH)
        return 0

    # 写库前留退路：先记下运行前的标签集合，再动库。
    textio.dump_json({
        'tag': TAG,
        'source': a.input,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'n': a.n,
        'before': plan['old'],
        'after': plan['new'],
        'words': [{'word': w['word'], 'noteId': int(w['noteId'])}
                  for w in picked],
    }, STATE_PATH)

    if plan['remove']:
        AK.remove_tags(plan['remove'], [TAG])
    if plan['add']:
        AK.add_tags(plan['add'], [TAG])

    after = tagged_note_ids()
    ok = set(after) == set(plan['new'])
    print('')
    print('=' * 88)
    print('写入结果')
    print('=' * 88)
    print('  摘除 %d 个；新增 %d 个；当前「%s」共 %d 个'
          % (len(plan['remove']), len(plan['add']), TAG, len(after)))
    print('  回读校验%s' % ('通过' if ok else '失败'))
    if not ok:
        missing = sorted(set(plan['new']) - set(after))
        extra = sorted(set(after) - set(plan['new']))
        print('  ⚠ 缺失 %d 个：%s' % (len(missing), missing[:10]))
        print('  ⚠ 多出 %d 个：%s' % (len(extra), extra[:10]))
        print('  先跑 --revert --commit 恢复到运行前，再把上面几个 noteId 报给用户。')

    json_path, report_path = write_outputs(a.input, result, picked, dropped,
                                          plan, a.n, counts)
    print('')
    print('产物：')
    print('  %s' % json_path)
    print('  %s' % report_path)
    print('')
    print('Anki 浏览器搜索：tag:"%s"' % TAG)
    print('回退：python code\\tools\\today_new_words.py --revert --commit')
    return 0 if ok else 1


def do_clear(a):
    old = tagged_note_ids()
    print('清空标签：%s' % TAG)
    print('当前命中 %d 个笔记' % len(old))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    if not a.commit:
        return 0
    textio.dump_json({
        'tag': TAG,
        'source': '--clear',
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'before': old,
        'after': [],
    }, STATE_PATH)
    if old:
        AK.remove_tags(old, [TAG])
    after = tagged_note_ids()
    print('已摘除 %d 个；当前剩 %d 个%s'
          % (len(old) - len(after), len(after),
             ('：' + str(after[:10])) if after else ''))
    return 0 if not after else 1


def do_revert(a):
    if not os.path.exists(STATE_PATH):
        raise SystemExit('找不到回退记录 %s（先确认确实跑过 --commit）' % STATE_PATH)
    st = textio.load_json(STATE_PATH)
    tag = st.get('tag') or TAG
    before = [int(x) for x in (st.get('before') or [])]
    if tag != TAG:
        raise SystemExit('回退记录的标签是 %s，不是 %s；停手问用户。' % (tag, TAG))
    plan = diff_ids(tagged_note_ids(), before)
    print('回退：恢复到上一次运行前的「%s」集合' % TAG)
    print('当前 %d 个 → 目标 %d 个；摘除 %d；补回 %d'
          % (len(plan['old']), len(before), len(plan['remove']), len(plan['add'])))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    if not a.commit:
        return 0
    if plan['remove']:
        AK.remove_tags(plan['remove'], [TAG])
    if plan['add']:
        # 只补回仍然存在的笔记，避免 AnkiConnect 对已删 note 报错。
        alive = set(AK.notes_map(plan['add']))
        add = [nid for nid in plan['add'] if nid in alive]
        if add:
            AK.add_tags(add, [TAG])
        gone = len(plan['add']) - len(add)
        if gone:
            print('  ⚠ %d 个旧笔记已不存在，未补回' % gone)
    after = tagged_note_ids()
    ok = set(after) == set(before)
    st['reverted_at'] = dt.datetime.now().isoformat(timespec='seconds')
    st['after_actual'] = after
    textio.dump_json(st, STATE_PATH)
    print('回读校验%s；当前 %d 个' % ('通过' if ok else '失败', len(after)))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='每天从文字/字幕挑 N 个今天要学的生词，只打标签「%s」' % TAG)
    ap.add_argument('input', nargs='?', default=None,
                    help='字幕（.srt/.vtt/.ass/.txt）或 - 读 stdin；--clear/--revert 时可省')
    ap.add_argument('--n', type=int, default=DEFAULT_N,
                    help='每天选多少个（默认 %d）' % DEFAULT_N)
    ap.add_argument('--clear', action='store_true', help='清空「%s」标签' % TAG)
    ap.add_argument('--revert', action='store_true', help='恢复到上一次运行前的标签集合')
    ap.add_argument('--commit', action='store_true', help='真写库（不加则只演练）')
    a = ap.parse_args(argv)

    if a.clear and a.revert:
        ap.error('--clear 与 --revert 只能选一个')
    if not a.clear and not a.revert:
        if not a.input:
            ap.error('需要输入文件（或 - 读 stdin）；--clear/--revert 才可省略')
        if a.n <= 0:
            ap.error('--n 必须大于 0')

    with AK.guard():
        if a.clear:
            return do_clear(a)
        if a.revert:
            return do_revert(a)
        return do_pick(a)


if __name__ == '__main__':
    raise SystemExit(main())
