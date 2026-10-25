#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""词汇覆盖曲线分析 —— 「同作品挖 12 集」vs「不同作品各挖前 3 集」哪个覆盖更广？

口径（重要）
----
本工具只看**字幕里出现、而你库里还没有的词形**（未收录候选词），
它回答的是「**可选词汇池**」问题，不是「Anki 里能真正收录多少张卡」问题。

真实入库还要过三道闸门，所以本工具的绝对值会**偏高**：
  - `mine.py` 判定：可能是已知词的活用残片、碎片、非词 → 剔除
  - 一集里同一词只算一次（不重复出卡）
  - 例句卡选句的取舍

但**相对比较**（哪个方案覆盖面更广、第 N 集的边际有多大）不受影响，因为
三道闸门对两种方案是同向作用的。

用法
----
  python vocab_curve.py --series "Tensei Oujo" --ep tensei_oujo_s1e01 --ep ... [--ep ...]
  python vocab_curve.py --group 作品A::ep1 --group 作品A::ep2 ...   # 分组对比
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'common'))
sys.path.insert(0, os.path.join(_HERE, '..', 'execution'))
import paths as WSP      # noqa: E402
import textio            # noqa: E402

INDEX = os.path.join(WSP.DATA, 'evidence', 'subtitle_index.json')


def words_of(ep):
    """一集的「未收录候选词」集合（已按跨集碎片表 + 停用词过滤后写进 prefilter.csv）。"""
    p = os.path.join(WSP.EVIDENCE, ep, 'prefilter.csv')
    if not os.path.exists(p):
        raise SystemExit('缺少 %s' % p)
    s = set()
    with open(p, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            for w in (r.get('resid') or '').split(';'):
                if w:
                    s.add(w)
    return s


def main():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--ep', nargs='+', required=True, help='按顺序排好的集名')
    ap.add_argument('--label', default='')
    ap.add_argument('--out', help='把逐集明细写成 CSV')
    a = ap.parse_args()

    sets = {ep: words_of(ep) for ep in a.ep}
    total = set().union(*sets.values())

    print('=== %s：%d 集，未收录候选词并集 %d 个' % (a.label or '素材', len(a.ep), len(total)))
    print()
    print('| 集 | 本集候选词 | 其中「前几集没出现过」的新词 | 占全并集 | 累计并集 |')
    print('|---|---|---|---|---|')
    seen = set()
    rows = []
    for ep in a.ep:
        w = sets[ep]
        new = w - seen
        seen |= w
        print('| %s | %d | **%d** | %.1f%% | %d |'
              % (ep, len(w), len(new), 100 * len(new) / max(1, len(total)), len(seen)))
        rows.append({'ep': ep, 'uniq': len(w), 'new': len(new), 'cum': len(seen)})
    print()

    # 边际收益：第 N 集相对前 N-1 集还能带来百分之多少的新词
    print('边际收益（每多挖一集还能新增多少词）：')
    prev = 0
    for i, r in enumerate(rows, 1):
        print('  第 %d 集：+%d 词（相对前一集 %+.0f%%）'
              % (i, r['new'], 100 * (r['new'] - prev) / prev if prev else 0))
        prev = r['new']
    print()

    # 「不同作品各挖前 3 集」模拟：按集号分组（1-3 / 4-6 / 7-9 …）
    if len(a.ep) >= 6:
        print('模拟「同作品挖满 12 集」的边际：')
        for lo in range(0, len(a.ep), 3):
            blk = a.ep[lo:lo + 3]
            before = set().union(*[sets[e] for e in a.ep[:lo]]) if lo else set()
            after = set().union(*[sets[e] for e in blk]) - before
            print('  第 %d–%d 集（第 %d 组）：+%d 个前 %d 集没出现的词'
                  % (lo + 1, lo + len(blk), lo // 3 + 1, len(after), lo))

    if a.out:
        with open(a.out, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['ep', 'uniq', 'new', 'cum'])
            w.writeheader()
            w.writerows(rows)
        print('\n→ %s' % a.out)


if __name__ == '__main__':
    main()
