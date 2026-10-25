# -*- coding: utf-8 -*-
"""通用能力：按 **Jiten 动漫词频名次** 给词汇卡打「值不值得背」的分档标签。

只做一件事：给三个词汇卡组里、名次落在切点内的笔记加
``词频::最佳停止词汇`` / ``词频::最佳上限词汇``。

**不写**任何字段，**不碰** ``due / ivl / factor / type / queue / reps / lapses``，
不改牌组、不加别的标签。

为什么按 Jiten 名次而不是「这几十集字幕里的词频」
------------------------------------------------
Jiten 的 Rank 是按「出现在多少部不同作品里」排的（见 ``data/freq/README.md``），
天然跨作品；而某一部剧里高频的词（设定词、角色语、古语）在 Jiten 上名次很差，
用单部语料排出来的词表换个题材就失效。所以「普遍适用于动画」的切点只能建在
Jiten 名次上，单部剧的专属词交给每集的 mine 流水线。

切点口径（2026-10 实测，样本 96 集 / 6 部 / 23 小时）
------------------------------------------------------
把 Jiten 名次换成「平均每个词在 23 小时动画里出现几次」（**没出现的词也进分母**，
否则会高估尾部词的收益）：

   名次段      每词出现/23h   约等于
   <= 6000        14.0        每 1.6 小时一次
   6001-12000      1.0-2.1    每 11-22 小时一次
   12001-24000     0.3-0.9    每 25-70 小时一次
   > 24000        0.04-0.3    每 70-500 小时一次

一个词背到成熟约 1.7 分钟（实测 5.7 次答题 × 18.2 秒），之后每年还要 2-10 次复习；
超过 24,000 名的词平均 70 小时以上才碰到一次，付不回这份永久维护税。

默认切点：
* ``--stop 12000``    <= 12,000  → ``词频::最佳停止词汇``（值得背，覆盖约 89%）
* ``--ceiling 24000`` 12,001-24,000 → ``词频::最佳上限词汇``（性价比递减，有余力再背；
  到 24,000 名累计覆盖约 95%）
* ``> 24,000`` 不打标签（可随时用 ``JitenAnimeRank`` 字段反查）

用法
----
::

    # 演练：只打印将打多少、哪些牌组（不写库）
    $PY code\\tools\\tag_freq_stop.py

    # 真写
    $PY code\\tools\\tag_freq_stop.py --commit

    # 换切点（会提示哪些旧标签要摘，加 --prune 才摘）
    $PY code\\tools\\tag_freq_stop.py --stop 10000 --ceiling 20000 --prune --commit

    # 回退：按 tags_freq_stop_applied.json 摘掉这两个标签
    $PY code\\tools\\tag_freq_stop.py --revert --commit

产物
----
* ``data/vocab_cover/backup_tags_freq_stop_<时间>.json``  写前快照（nid → 原 tags）
* ``data/vocab_cover/tags_freq_stop_applied.json``        本次打标记录，供 --revert
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
_VC = os.path.join(_CODE, 'analysis', 'vocab_cover')
sys.path.insert(0, os.path.join(_CODE, 'common'))
sys.path.insert(0, _VC)

import textio                    # noqa: E402  UTF-8 stdio 唯一入口
import anki_api as AK            # noqa: E402
import jp_decks as JD            # noqa: E402
from _deps import DATA_DIR, STATE_JSON, WSP as _WSP  # noqa: E402
from _norm import norm_word      # noqa: E402  词形归一唯一实现
from jiten_rank_bands import load_jiten_ranks  # noqa: E402

SCOPES = (JD.DECK_MINED, JD.DECK_CORE6000, JD.DECK_KAOKYU)
TAG_STOP = '词频::最佳停止词汇'
TAG_CEIL = '词频::最佳上限词汇'
TAGS = (TAG_STOP, TAG_CEIL)
WORD_FIELDS = ('Word', 'VocabKanji', 'Expression', 'Front', 'Vocabulary')
CSV_PATH = os.path.join(_WSP.DATA, 'freq', 'jiten_freq_Anime.csv')
STATE_NAME = 'tags_freq_stop_applied.json'
BACKUP_PREFIX = 'backup_tags_freq_stop_'
BATCH = 400


# ============================================================================
# 纯函数（不碰 Anki，测试可直接喂）
# ============================================================================
def tag_of(rank, stop, ceiling):
    """名次 -> 标签（None = 不打标签）。"""
    if rank is None:
        return None
    if rank <= stop:
        return TAG_STOP
    if rank <= ceiling:
        return TAG_CEIL
    return None


def pick_word(fields):
    for name in WORD_FIELDS:
        v = (fields or {}).get(name) or ''
        v = v.strip()
        if v:
            return v
    return ''


def plan(items, stop, ceiling):
    """items: [{nid, word, rank, tags, deck}] -> (to_add, to_remove, untouched)"""
    to_add, to_remove, untouched = [], [], []
    for it in items:
        want = tag_of(it['rank'], stop, ceiling)
        have = [t for t in TAGS if t in (it['tags'] or ())]
        if it['skip']:
            untouched.append(it)
            continue
        if want and want not in have:
            to_add.append((it, want))
            others = [t for t in have if t != want]
            if others:
                to_remove.append((it, others))
        elif not want and have:
            to_remove.append((it, have))
        else:
            untouched.append(it)
    return to_add, to_remove, untouched


# ============================================================================
# 取数
# ============================================================================
def fetch_notes():
    """三个词汇卡组里的全部笔记 -> [{nid, deck, fields, tags, model}]"""
    out = {}
    for deck in SCOPES:
        nids = AK.find_notes('deck:"%s"' % deck)
        print('  %-28s %6d 张笔记' % (deck.split('::')[-1], len(nids)))
        for batch in AK.chunks(nids, BATCH):
            for n in AK.notes_info(batch):
                out[n['noteId']] = {
                    'nid': n['noteId'],
                    'deck': deck,
                    'fields': {k: (v or {}).get('value', '')
                               for k, v in (n.get('fields') or {}).items()},
                    'tags': list(n.get('tags') or []),
                    'model': n.get('modelName', ''),
                }
    return list(out.values())


def build_items(notes, ranks, state):
    items = []
    no_word = 0
    for n in notes:
        raw = pick_word(n['fields'])
        w = norm_word(raw) if raw else ''
        if not w:
            no_word += 1
            items.append({'nid': n['nid'], 'word': '', 'rank': None,
                          'tags': n['tags'], 'deck': n['deck'], 'skip': True,
                          'known': False})
            continue
        rank = ranks.get(w)
        e = state.get(w) or {}
        items.append({'nid': n['nid'], 'word': w, 'raw': raw, 'rank': rank,
                      'tags': n['tags'], 'deck': n['deck'], 'skip': False,
                      'known': bool(e.get('known')), 'mature': bool(e.get('mature'))})
    return items, no_word


# ============================================================================
# 报告
# ============================================================================
def report(items, to_add, to_remove, no_word, stop, ceiling, prune):
    add_cnt = collections.Counter(t for _, t in to_add)
    rm_cnt = collections.Counter(t for _, ts in to_remove for t in ts)
    by_deck = collections.defaultdict(collections.Counter)
    for it, t in to_add:
        by_deck[it['deck'].split('::')[-1]][t] += 1

    keep_stop = [it for it in items if not it['skip'] and it['rank'] is not None
                 and it['rank'] <= stop]
    keep_ceil = [it for it in items if not it['skip'] and it['rank'] is not None
                 and stop < it['rank'] <= ceiling]
    norank = sum(1 for it in items if not it['skip'] and it['rank'] is None)
    tail = sum(1 for it in items if not it['skip'] and it['rank'] is not None
               and it['rank'] > ceiling)

    print('')
    print('=' * 88)
    print('分档标签计划')
    print('=' * 88)
    print('切点：<= %s 打「%s」；<= %s 打「%s」；以上不打' % (
        f'{stop:,}', TAG_STOP, f'{ceiling:,}', TAG_CEIL))
    print('')
    print('  名次 <= %-7s %6d 张笔记（已学 %d / 已成熟 %d）'
          % (f'{stop:,}', len(keep_stop), sum(1 for i in keep_stop if i['known']),
             sum(1 for i in keep_stop if i['mature'])))
    print('  名次 <= %-7s %6d 张笔记（已学 %d / 已成熟 %d）'
          % (f'{ceiling:,}', len(keep_ceil), sum(1 for i in keep_ceil if i['known']),
             sum(1 for i in keep_ceil if i['mature'])))
    print('  名次 >  %-7s %6d 张笔记（不打标签）' % (f'{ceiling:,}', tail))
    print('  Jiten 无档位      %6d 张笔记（不打标签，多为专名/惯用句/写法差异）' % norank)
    if no_word:
        print('  取不到词形        %6d 张笔记（跳过）' % no_word)
    print('')
    print('  本次将加：%s' % ('、'.join('%s %d' % (t, add_cnt[t]) for t in TAGS)
                            or '无'))
    if by_deck:
        for deck in sorted(by_deck):
            print('    %-14s %s' % (deck, '、'.join('%s %d' % (t.split('::')[-1], by_deck[deck][t])
                                                   for t in TAGS if by_deck[deck][t])))
    stale = sum(rm_cnt.values())
    print('  旧标签需摘除：%s%s' % ('、'.join('%s %d' % (t, rm_cnt[t]) for t in TAGS if rm_cnt[t]) or '无',
                                '' if prune else '（未加 --prune，本次不摘）'))

    for tag, pool in ((TAG_STOP, keep_stop), (TAG_CEIL, keep_ceil)):
        sample = [it for it, t in to_add if t == tag][:12]
        if sample:
            print('')
            print('  样例（%s）：%s' % (tag.split('::')[-1],
                                     '、'.join('%s(%s)' % (i['raw'] or i['word'], i['rank'])
                                               for i in sample)))


# ============================================================================
# 写库
# ============================================================================
def backup(items):
    path = os.path.join(DATA_DIR, BACKUP_PREFIX + dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
    os.makedirs(DATA_DIR, exist_ok=True)
    textio.dump_json({'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
                      'note_count': len(items),
                      'notes': {str(it['nid']): it['tags'] for it in items}}, path)
    return path


def do_apply(a):
    ranks = load_jiten_ranks(a.csv)
    state = json.load(open(a.state, encoding='utf-8'))['words']
    print('Jiten 词表 %d 条；卡组快照 %d 词（%s）'
          % (len(ranks), len(state), os.path.relpath(a.state, _WSP.ROOT)))
    print('读取三个词汇卡组……')
    notes = fetch_notes()
    items, no_word = build_items(notes, ranks, state)
    to_add, to_remove, _ = plan(items, a.stop, a.ceiling)
    report(items, to_add, to_remove, no_word, a.stop, a.ceiling, a.prune)

    if a.limit:
        to_add = to_add[:a.limit]
        print('\n  --limit %d：本次只处理前 %d 条新增' % (a.limit, len(to_add)))

    if not to_add and not (a.prune and to_remove):
        print('\n无需变更。')
        return 0

    print('')
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    if not a.commit:
        print('演练结束，未写库。确认无误后加 --commit。')
        return 0

    bpath = backup(items)
    print('写前备份：%s' % os.path.relpath(bpath, _WSP.ROOT))

    added = collections.defaultdict(list)
    removed = collections.defaultdict(list)
    failed = None
    try:
        for tag in TAGS:
            nids = [it['nid'] for it, t in to_add if t == tag]
            for batch in AK.chunks(nids, BATCH):
                AK.add_tags(batch, [tag])
                added[tag].extend(batch)      # 逐批记账：中途失败也不丢已写的 nid
        if a.prune:
            for tag in TAGS:
                nids = [it['nid'] for it, ts in to_remove if tag in ts]
                for batch in AK.chunks(nids, BATCH):
                    AK.remove_tags(batch, [tag])
                    removed[tag].extend(batch)
    except Exception as exc:                  # AnkiConnect 拒绝（如编辑器未关）时保留现场
        failed = exc

    # ---- 回读校验 ----
    def live_tags(nid_list):
        got = {}
        for batch in AK.chunks(nid_list, BATCH):
            for n in AK.notes_info(batch):
                got[n['noteId']] = set(n.get('tags') or [])
        return got

    bad = []
    for tag in TAGS:
        if not added[tag]:
            continue
        live = live_tags(added[tag])
        bad += [nid for nid in added[tag] if tag not in live.get(nid, set())]

    textio.dump_json({
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'stop': a.stop, 'ceiling': a.ceiling,
        'csv': a.csv,
        'tags': {tag: added[tag] for tag in TAGS},
        'removed': {tag: removed[tag] for tag in TAGS},
        'backup': bpath,
    }, os.path.join(DATA_DIR, STATE_NAME))

    print('')
    print('=' * 88)
    print('写入结果')
    print('=' * 88)
    for tag in TAGS:
        print('  %-22s 已加 %6d' % (tag, len(added[tag])))
    if failed is not None:
        print('  ✗ 中途失败：%s' % failed)
        print('    已写入的部分可用 --revert 摘除，或在 Anki 里关掉编辑窗口后重跑本命令（幂等，只补没打的）。')
        print('  回退：python code\\tools\\tag_freq_stop.py --revert --commit')
        return 2
    print('  回读校验%s' % ('：全部命中' if not bad else '失败 %d 条，请立即 --revert' % len(bad)))
    print('')
    print('回退：python code\\tools\\tag_freq_stop.py --revert --commit')
    print('Anki 搜索：tag:"%s" / tag:"%s"' % (TAG_STOP, TAG_CEIL))
    return 1 if bad else 0


def do_revert(a):
    path = os.path.join(DATA_DIR, STATE_NAME)
    if not os.path.exists(path):
        raise SystemExit('找不到回退记录：%s' % path)
    st = json.load(open(path, encoding='utf-8'))
    all_nids = sorted({nid for tag in TAGS for nid in (st.get('tags', {}).get(tag) or [])})
    print('回退：%d 个笔记，摘掉 %s' % (len(all_nids), ' / '.join(TAGS)))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才摘）'))
    if not a.commit:
        return 0
    for batch in AK.chunks(all_nids, BATCH):
        AK.remove_tags(batch, list(TAGS))
    left = 0
    for batch in AK.chunks(all_nids, BATCH):
        for n in AK.notes_info(batch):
            left += 1 if set(n.get('tags') or []) & set(TAGS) else 0
    print('已摘除；残留 %d 条%s' % (left, '' if not left else '，请检查'))
    return 1 if left else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='按 Jiten 动漫词频名次给词汇卡打「词频::最佳停止词汇/最佳上限词汇」（只加标签）')
    ap.add_argument('--stop', type=int, default=12000,
                    help='停止点名次（<=N 打「最佳停止词汇」，默认 12000）')
    ap.add_argument('--ceiling', type=int, default=24000,
                    help='上限名次（<=N 打「最佳上限词汇」，默认 24000）')
    ap.add_argument('--csv', default=CSV_PATH, help='Jiten 词频表')
    ap.add_argument('--state', default=STATE_JSON, help='卡组快照 vocab_state.json')
    ap.add_argument('--prune', action='store_true', help='顺带摘掉不再符合条件的旧标签')
    ap.add_argument('--limit', type=int, default=0, help='只处理前 N 条（0=全部）')
    ap.add_argument('--commit', action='store_true', help='真写库（不加则只演练）')
    ap.add_argument('--revert', action='store_true', help='按记录摘掉这两个标签')
    a = ap.parse_args(argv)
    if a.ceiling <= a.stop:
        ap.error('--ceiling 必须大于 --stop')
    with AK.guard():
        if a.revert:
            return do_revert(a)
        return do_apply(a)


if __name__ == '__main__':
    raise SystemExit(main())
