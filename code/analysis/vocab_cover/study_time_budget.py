# -*- coding: utf-8 -*-
"""按「时间预算」算新卡上限：用自己 revlog 的实测单价 + 卡龄分层，把负荷拆成
「存量维护」与「新卡贡献」两部分，再反推新卡能放多少。

为什么要按卡龄分层
------------------
日语Anki配比方案.md 的公式「答题/天 ≈ 235 + 8 × 新卡/天」里的 8 是**前瞻估计**
（每张新卡头一个月产生的答题数）。如果直接拿它去减当前实测总量，会把「还没长大的
新卡」当成已经满负荷，反推出的存量会低到离谱（实测过：会算出 83 次/天）。
所以这里改成**直接测量**：

* 把窗口内每次答题按「答题时这张卡已经存在多少天」分层；
* 卡龄 ≤ 30 天 → **新卡贡献**；> 30 天 → **存量维护**；
* 每张新卡的月成本 L = 新卡层的答题数 ÷ 窗口内新引入的卡数（按组各算）
* 预计分钟数 = 存量分钟 + Σ(该组新卡/天 × L_分钟)

模型自校准：把当前的新卡量代回去必然复现实测值；外推到别的新卡量才是它的用处。

用法：python study_time_budget.py --target 120
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _deps import WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

SNAP = os.path.join(WSP.SNAPSHOTS, 'live', 'collection.anki2')
YOUNG_DAYS = 30
GROUPS = ('core6000', '考级词汇', '语法', '素材/例句')


def group_of(name: str):
    if not name:
        return None
    if '高频日语单词 6000' in name:
        return 'core6000'
    if '考级词汇' in name:
        return '考级词汇'
    if '语法' in name:
        return '语法'
    if '素材生词' in name or name.endswith('2-例句'):
        return '素材/例句'
    return None


def measure(days: int = 21) -> dict:
    con = sqlite3.connect('file:%s?mode=ro' % SNAP, uri=True)
    con.create_collation('unicase',
                         lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    cur = con.cursor()
    decks = {r[0]: r[1].replace('\x1f', '::') for r in cur.execute('SELECT id, name FROM decks')}
    card = {c: group_of(decks.get(d, '')) for c, d in cur.execute('SELECT id, did FROM cards')}
    first = dict(cur.execute('SELECT cid, MIN(id) FROM revlog GROUP BY cid'))
    newest = cur.execute('SELECT MAX(id) FROM revlog').fetchone()[0]
    cut = newest - days * 86400000

    # bucket[group][layer] = [answers, ms]
    bucket = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    active = set()
    for ts, cid, time_ in cur.execute('SELECT id, cid, time FROM revlog WHERE id > ?', (cut,)):
        g = card.get(cid)
        active.add(ts // 86400000)
        if not g:
            continue
        age_days = (ts - first[cid]) / 86400000.0
        layer = 'young' if age_days <= YOUNG_DAYS else 'old'
        bucket[g][layer][0] += 1
        bucket[g][layer][1] += time_

    new = collections.Counter()
    for cid, ts in first.items():
        if ts > cut:
            g = card.get(cid)
            if g:
                new[g] += 1
    con.close()

    nd = max(1, len(active))
    out = {'days': days, 'active_days': nd,
           'newest': dt.datetime.fromtimestamp(newest / 1000), 'groups': {}}
    for g in GROUPS:
        y, o = bucket[g]['young'], bucket[g]['old']
        out['groups'][g] = {
            'new_in_window': new[g], 'new_per_day': new[g] / nd,
            'young_answers_per_day': y[0] / nd, 'young_min_per_day': y[1] / 60000 / nd,
            'old_answers_per_day': o[0] / nd, 'old_min_per_day': o[1] / 60000 / nd,
            'answers_per_day': (y[0] + o[0]) / nd,
            'min_per_day': (y[1] + o[1]) / 60000 / nd,
            # 每张新卡在头 30 天里产生的答题数 / 分钟数
            'L_answers': (y[0] / new[g]) if new[g] else 0.0,
            'L_min': (y[1] / 60000 / new[g]) if new[g] else 0.0,
        }
    tot_y_a = sum(bucket[g]['young'][0] for g in GROUPS) / nd
    tot_y_m = sum(bucket[g]['young'][1] for g in GROUPS) / 60000 / nd
    tot_o_a = sum(bucket[g]['old'][0] for g in GROUPS) / nd
    tot_o_m = sum(bucket[g]['old'][1] for g in GROUPS) / 60000 / nd
    out['total'] = {
        'answers_per_day': tot_y_a + tot_o_a, 'min_per_day': tot_y_m + tot_o_m,
        'young_answers_per_day': tot_y_a, 'young_min_per_day': tot_y_m,
        'old_answers_per_day': tot_o_a, 'old_min_per_day': tot_o_m,
        'new_per_day': sum(new[g] for g in GROUPS) / nd,
    }
    return out


def project(m: dict, new_vocab: float, new_grammar: float) -> dict:
    """预计稳态每天答题数与分钟数。

    词汇新卡按 core6000 / 考级 / 素材 的实测月成本加权；语法新卡用语法组的月成本。
    """
    g = m['groups']
    vocab_w = [('core6000', 0.45), ('考级词汇', 0.45), ('素材/例句', 0.10)]
    L_voc_min = sum(g[k]['L_min'] * w for k, w in vocab_w)
    L_voc_ans = sum(g[k]['L_answers'] * w for k, w in vocab_w)
    L_g_min = g['语法']['L_min']
    L_g_ans = g['语法']['L_answers']
    t = m['total']
    minutes = t['old_min_per_day'] + new_vocab * L_voc_min + new_grammar * L_g_min
    answers = t['old_answers_per_day'] + new_vocab * L_voc_ans + new_grammar * L_g_ans
    return {'minutes': minutes, 'answers': answers,
            'L_voc_min': L_voc_min, 'L_voc_ans': L_voc_ans,
            'L_g_min': L_g_min, 'L_g_ans': L_g_ans,
            'old_min': t['old_min_per_day'], 'old_ans': t['old_answers_per_day']}


def main() -> int:
    ap = argparse.ArgumentParser(description='按时间预算反推新卡上限')
    ap.add_argument('--days', type=int, default=21)
    ap.add_argument('--target', type=float, default=120, help='目标分钟/天，默认 120')
    args = ap.parse_args()
    if not os.path.exists(SNAP):
        raise SystemExit('找不到快照 %s' % SNAP)

    m = measure(args.days)
    t = m['total']
    print('=== 按卡龄分层实测（最近 %d 个活跃日，截至 %s）==='
          % (m['active_days'], m['newest'].strftime('%Y-%m-%d')))
    print('  %-10s %-8s %8s %9s %9s %9s' % ('组', '层', '答题/天', '分钟/天', '秒/次', '新卡/天'))
    for g in GROUPS:
        d = m['groups'][g]
        for layer, key in (('新卡(≤30天)', 'young'), ('存量(>30天)', 'old')):
            a = d[key + '_answers_per_day']
            mi = d[key + '_min_per_day']
            print('  %-10s %-8s %8.1f %9.1f %9.1f %9s'
                  % (g, layer, a, mi, (mi * 60 / a) if a else 0,
                     ('%.1f' % d['new_per_day']) if layer.startswith('新卡') else ''))
    print('  %-10s %-8s %8.1f %9.1f %9.1f %9.1f'
          % ('合计', '全部', t['answers_per_day'], t['min_per_day'],
             t['min_per_day'] * 60 / t['answers_per_day'], t['new_per_day']))
    print('    其中 新卡层 %.1f 分钟/天，存量层 %.1f 分钟/天'
          % (t['young_min_per_day'], t['old_min_per_day']))
    print()
    print('=== 每张新卡的「头 30 天成本」（实测，用于外推）===')
    for g in GROUPS:
        d = m['groups'][g]
        if d['L_min']:
            print('  %-10s 每张新卡头 30 天：%.1f 次答题 / %.2f 分钟（≈%.1f 秒/次）'
                  % (g, d['L_answers'], d['L_min'], d['L_min'] * 60 / max(1e-9, d['L_answers'])))
    p0 = project(m, 0, 0)
    ph = project(m, t['new_per_day'] * 0.9, t['new_per_day'] * 0.1)
    print()
    print('  存量维护（不加任何新卡）≈ %.0f 分钟/天' % p0['minutes'])
    print('  模型自校准：代回当前新卡量 → %.0f 分钟/天（实测 %.0f）'
          % (ph['minutes'], t['min_per_day']))
    print('  词汇新卡月成本 %.2f 分钟/张；语法新卡月成本 %.2f 分钟/张'
          % (p0['L_voc_min'], p0['L_g_min']))
    print()
    print('=== 目标 %.0f 分钟/天 的配比 ===' % args.target)
    print('  %-20s %10s %10s %s' % ('配比', '答题/天', '分钟/天', ''))
    for nv, ng in ((0, 0), (10, 0), (15, 0), (20, 0), (25, 0), (30, 0),
                   (10, 3), (10, 5), (15, 3), (15, 5), (20, 5), (12, 8)):
        p = project(m, nv, ng)
        print('  词汇 %2d + 语法 %-2d     %10.0f %10.0f  %s'
              % (nv, ng, p['answers'], p['minutes'],
                 '✅' if abs(p['minutes'] - args.target) <= 10
                 else ('↑ 超' if p['minutes'] > args.target else '↓ 有余')))
    print()
    print('=== 反解：目标 %.0f 分钟下词汇能放多少 ===' % args.target)
    for ng in (0, 3, 5, 8, 10):
        lo, hi = 0.0, 200.0
        for _ in range(50):
            mid = (lo + hi) / 2
            if project(m, mid, ng)['minutes'] < args.target:
                lo = mid
            else:
                hi = mid
        print('  语法 %2d 张/天 → 词汇最多 %5.1f 张/天（合计 %5.1f 张新卡）'
              % (ng, lo, lo + ng))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
