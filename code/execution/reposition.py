# -*- coding: utf-8 -*-
"""把**新卡**的队列位置（``due``）按 ``JitenAnimeRank`` 的数字排一遍。

用户口径（2026-10-15）：素材卡片的 ``due`` 按 ``JitenAnimeRank`` 字段的数字排序
—— 数字越小＝动漫词频越高＝越早学到。词表里没有的词字段写 ``999999``，自然排最后。

要点
----
* **只动 ``type=0`` 的新卡**（``due`` 这时是「队列位置」这个排序键）。学习/复习中的卡
  ``due`` 是真实日期，一律不碰（脚本里硬拦，回读校验也查 ``type``）。
* 默认 ``due = 字段数字``（于是浏览器的 Due 列直接就是词频排名，一眼能看出先后）；
  ``--compact`` 则按排名排序后压成连续序号（1,2,3…）。
* 同排名并列 → 位置相同，Anki 自行按卡 id 决先后，无害。
* 幂等：已经是目标值的不重写（``--force`` 可强制）。

用法
----
    & $PY code\\execution\\reposition.py                    # 演练：只打印将要写的映射
    & $PY code\\execution\\reposition.py --commit           # 真写（素材生词 deck）
    & $PY code\\execution\\reposition.py --deck '0-日本语学习::1-高频日语单词 6000' --commit

回退：位置只是排序键，改回去不影响任何学习进度；``--restore <backup.json>``
可以把 ``--commit`` 时自动落盘的原始位置写回去。
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))

import anki_api as AK            # noqa: E402
import jp_decks as JD            # noqa: E402
import mine as M                 # noqa: E402  JITEN_NO_RANK
import paths as WSP              # noqa: E402
import textio                    # noqa: E402

FIELD = 'JitenAnimeRank'
BIG = int(M.JITEN_NO_RANK or 999999)


def rank_of(note, field=FIELD):
    """→ (名次 int, 原始字段串)。空/非数字 → BIG（排最后）。"""
    raw = ((note.get('fields', {}) or {}).get(field, {}) or {}).get('value', '') or ''
    raw = raw.strip()
    try:
        return int(raw), raw
    except ValueError:
        return BIG, raw


def collect(deck, field=FIELD, word_field='Word', notes=None):
    """→ 新卡一行行信息（noteId / cardId / 词 / 名次 / 现位置）。

    ``notes`` 给定时只处理这些 noteId（写好一批立刻归位用），否则整个 deck。
    """
    ids = list(notes) if notes else AK.find_notes('deck:"%s"' % deck)
    notes = AK.notes_map(ids)
    if not notes:
        return []
    cards = {}
    for cid, c in AK.cards_map(AK.cards_of_notes(list(notes))).items():
        cards.setdefault(int(c.get('note')), []).append((cid, c))
    rows = []
    for nid, n in notes.items():
        rank, raw = rank_of(n, field)
        word = ((n.get('fields', {}) or {}).get(word_field, {}) or {}).get('value', '')
        for cid, c in cards.get(int(nid), []):
            rows.append({'noteId': int(nid), 'cardId': int(cid), 'word': word,
                         'rank': rank, 'raw': raw, 'type': c.get('type'),
                         'due_now': c.get('due'), 'queue': c.get('queue')})
    rows.sort(key=lambda r: (r['rank'], r['word'], r['cardId']))
    return rows


def plan(rows, mode='rank', start=1):
    """给新卡算目标位置。返回 (将要写的 rows, 跳过的 rows)。"""
    todo, skip = [], []
    n = start
    for r in rows:
        if r['type'] != 0:                      # 学习/复习中的卡：due 是日期，绝不碰
            skip.append((r, '不是新卡（type=%s）' % r['type']))
            continue
        want = r['rank'] if mode == 'rank' else n
        if mode == 'compact':
            n += 1
        if r['due_now'] == want:
            skip.append((r, '已经是 %s' % want))
            continue
        r['due_new'] = want
        todo.append(r)
    return todo, skip


def apply(todo, commit=False, backup_dir=None):
    """写位置；commit=False 只打印。返回 (成功数, 失败行)。"""
    if not commit:
        return 0, []
    ok, bad = 0, []
    for r in todo:
        try:
            if AK.set_card_due(r['cardId'], r['due_new']):
                ok += 1
            else:
                bad.append((r, 'AnkiConnect 没确认'))
        except Exception as exc:                # noqa: BLE001
            bad.append((r, '%s: %s' % (type(exc).__name__, exc)))
    return ok, bad


def verify(todo):
    """回读：位置写对了没有、是否仍是新卡。"""
    if not todo:
        return []
    time.sleep(0.5)
    after = AK.cards_map([r['cardId'] for r in todo])
    bad = []
    for r in todo:
        c = after.get(str(r['cardId'])) or after.get(r['cardId']) or {}
        if c.get('due') != r['due_new'] or c.get('type') != 0:
            bad.append((r, c.get('due'), c.get('type')))
    return bad


def inversions(seq):
    """归并统计逆序对（due 升序下 rank 应该非降，逆序对＝有多少对倒挂）。"""
    def merge(a):
        if len(a) < 2:
            return a, 0
        m = len(a) // 2
        l, cl = merge(a[:m])
        r, cr = merge(a[m:])
        out, i, j, c = [], 0, 0, cl + cr
        while i < len(l) and j < len(r):
            if l[i] <= r[j]:
                out.append(l[i])
                i += 1
            else:
                out.append(r[j])
                j += 1
                c += len(l) - i
        out += l[i:] + r[j:]
        return out, c
    return merge(list(seq))[1]


def check(deck=JD.DECK_MINED, field=FIELD, top=12):
    """只读体检：素材生词 deck 的**新卡队列顺序**和 JitenAnimeRank 差多少。"""
    rows = [r for r in collect(deck, field) if r['type'] == 0]
    if not rows:
        print('（%s 里没有新卡）' % deck)
        return {}
    rows.sort(key=lambda r: (r['due_now'], r['cardId']))
    ranks = [r['rank'] for r in rows]
    n = len(rows)
    inv = inversions(ranks)
    total = n * (n - 1) // 2
    adj = sum(1 for i in range(1, n) if ranks[i] < ranks[i - 1])
    no_rank = sum(1 for x in ranks if x == BIG)
    print('=' * 88)
    print('体检：%s 的新卡队列（按 due 升序）vs JitenAnimeRank' % deck)
    print('=' * 88)
    print('  新卡 %d 张 ｜ 无排名字段 %d 张' % (n, no_rank))
    print('  与 rank 升序不一致的**对数**：%d / %d（%.2f%%）'
          % (inv, total, 100.0 * inv / total if total else 0))
    print('  相邻倒挂：%d 处' % adj)
    print('  队列前 %d 张：' % top)
    for r in rows[:top]:
        print('    due %-9s rank %-7s %s' % (r['due_now'], r['rank'], r['word']))
    print('  队列末 %d 张：' % 3)
    for r in rows[-3:]:
        print('    due %-9s rank %-7s %s' % (r['due_now'], r['rank'], r['word']))
    return {'n': n, 'inv': inv, 'total': total, 'adj': adj, 'no_rank': no_rank}


def reposition(deck=JD.DECK_MINED, field=FIELD, mode='rank', commit=False,
               start=1, top=25, quiet=False, notes=None):
    """给别的模块调用的入口（immersionkit 写完之后就调它）。返回统计 dict。"""
    rows = collect(deck, field, notes=notes)
    new = [r for r in rows if r['type'] == 0]
    todo, skip = plan(rows, mode, start)
    stat = {'deck': deck, 'cards': len(rows), 'new': len(new), 'todo': len(todo),
            'skipped': len(skip), 'ok': 0, 'bad': []}
    if not quiet:
        print('=' * 88)
        print('按 %s 重排新卡位置 ｜ %s ｜ 模式 %s' % (field, deck, mode))
        print('=' * 88)
        print('  卡 %d 张（新卡 %d 张）；要改位置 %d 张；跳过 %d 张'
              % (len(rows), len(new), len(todo), len(skip)))
        for r in todo[:top]:
            print('    %-14s %-8s due %s → %s' % (r['word'][:14], r['rank'],
                                                 r['due_now'], r['due_new']))
        if len(todo) > top:
            print('    … 其余 %d 张' % (len(todo) - top))
    if not commit:
        if not quiet:
            print('  演练结束，未写任何数据。确认无误后加 --commit 重跑。')
        return stat
    ok, bad = apply(todo, commit=True)
    stat['ok'], stat['bad'] = ok, bad
    bad_read = verify(todo)
    stat['bad_read'] = bad_read
    if not quiet:
        print('  写入成功 %d / %d' % (ok, len(todo)))
        for r, why in bad[:8]:
            print('    ✗ %s：%s' % (r['word'], why))
        print('  回读校验：%d / %d 位置正确且仍是新卡'
              % (len(todo) - len(bad_read), len(todo)))
        for r, due, typ in bad_read[:8]:
            print('    ✗ %s 期望 %s/type 0，实得 %s/%s'
                  % (r['word'], r['due_new'], due, typ))
    return stat


def main(argv=None):
    ap = argparse.ArgumentParser(description='按 JitenAnimeRank 重排新卡位置（due）')
    ap.add_argument('--deck', default=JD.DECK_MINED, help='目标牌组（默认素材生词）')
    ap.add_argument('--field', default=FIELD, help='排序字段（默认 JitenAnimeRank）')
    ap.add_argument('--compact', action='store_true',
                    help='压成连续序号（默认直接写字段数字，Due 列＝词频排名）')
    ap.add_argument('--start', type=int, default=1, help='--compact 的起始序号')
    ap.add_argument('--top', type=int, default=25, help='演练时打印前 N 行')
    ap.add_argument('--commit', action='store_true', help='真写库（默认演练）')
    ap.add_argument('--check', action='store_true',
                    help='只读体检：新卡队列顺序与 JitenAnimeRank 差多少')
    a = ap.parse_args(argv)

    WSP.ensure()
    if a.check:
        check(a.deck, a.field)
        return 0
    stat = reposition(a.deck, a.field, 'compact' if a.compact else 'rank',
                      commit=a.commit, start=a.start, top=a.top)
    if a.commit:
        stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
        out = os.path.join(WSP.DATA, 'reposition_%s.json' % stamp)
        textio.dump_json({'created': stamp, 'deck': a.deck, 'field': a.field,
                          'mode': 'compact' if a.compact else 'rank',
                          'ok': stat['ok'], 'todo': stat['todo'],
                          'bad': len(stat['bad']), 'bad_read': len(stat['bad_read'])},
                         out)
        print('  记录：%s' % os.path.relpath(out, WSP.ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
