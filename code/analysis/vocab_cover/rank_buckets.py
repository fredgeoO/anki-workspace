# -*- coding: utf-8 -*-
"""jitanAnimeRank 千词区间统计：每 1000 个词里，我学会的占多少。

对 Jiten Anime 词频表（``data/freq/jiten_freq_Anime.csv``）按 Rank 排序后，
**每 ``--bucket``（默认 1000）个词切一个区间**，逐区间统计这些词在 Anki 里
的学习状态，输出「已学占比」。

为什么不是直接按 Rank 值切区间
------------------------------
实测这份表的 ``Rank`` 是粗粒度分数：**211,518 行只有 31,853 个不同 Rank**，
尾部一个 Rank 能挂上几万个词（如 Rank 176614 独占 39,683 行），且部分 Rank
值整段缺失。按 Rank 值切区间会让「千词」忽多忽少、不可比。所以这里先排序、
再按词的个数等分 —— 每个区间恰好 1000 个词（最后一个除外）。

对词与去重
----------
* 每行 ``Word``（汉字形）+ ``Form``（假名形）是一个词条；词键取
  ``norm_word(Word)``（Word 为空才用 Form），与 ``collect_vocab.py`` 同一套
  归一（片假名转平假名等）。
* 同一词会以平假名 / 片假名两种写法各出现一行（如 は@2 与 ハ@140509）——
  合并成一个词，保留**更常用**的那个 Rank。211,518 行 -> 约 20.2 万个不同词。
* 「有卡 / 已学 / 成熟」按该词键查 ``vocab_state.json``：
  有卡 = Anki 里有这张词汇卡；已学 known = 至少复习过一次（reps > 0）；
  成熟 mature = 复习卡且间隔 >= 21 天。

用法::

    python code/analysis/vocab_cover/rank_buckets.py               # 默认 1000 词区间
    python code/analysis/vocab_cover/rank_buckets.py --bucket 500  # 换粒度

产物::

    data/vocab_cover/rank_bucket_stats.json   区间明细（供以后画图 / 复查）
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _deps import DATA_DIR, STATE_JSON, WSP  # noqa: E402
from _norm import norm_word  # noqa: E402
import textio as T  # noqa: E402


def load_words(csv_path: str):
    """CSV -> ``[(rank, key, display), ...]``，按词去重（同词取最常用 Rank）。"""
    best = {}
    with open(csv_path, encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            try:
                rank = int((row.get('Rank') or '').strip())
            except ValueError:
                continue
            word = (row.get('Word') or '').strip()
            form = (row.get('Form') or '').strip()
            if rank < 1 or not word and not form:
                continue
            k = norm_word(word) or norm_word(form)
            if not k:
                continue
            cur = best.get(k)
            if cur is None or rank < cur[0]:
                best[k] = (rank, word or form)
    return [(rank, k, disp) for k, (rank, disp) in best.items()]


def main() -> int:
    ap = argparse.ArgumentParser(description='jitanAnimeRank 千词区间已学占比统计')
    ap.add_argument('--csv', default=os.path.join(WSP.DATA, 'freq', 'jiten_freq_Anime.csv'),
                    help='Jiten 词频表 CSV（默认 Anime）')
    ap.add_argument('--state', default=STATE_JSON, help='词汇快照 vocab_state.json')
    ap.add_argument('--bucket', type=int, default=1000, help='每区间词数（默认 1000）')
    ap.add_argument('--out', default=os.path.join(DATA_DIR, 'rank_bucket_stats.json'),
                    help='JSON 产物路径')
    args = ap.parse_args()

    words = load_words(args.csv)
    words.sort(key=lambda t: (t[0], t[1]))          # 按 Rank，同分按词键（确定性）
    with open(args.state, encoding='utf-8') as fh:
        state_doc = json.load(fh)
    state = state_doc['words']

    nbuckets = (len(words) - 1) // args.bucket + 1
    print(f'词频表 {os.path.relpath(args.csv, WSP.ROOT)}：{len(words)} 个不同词（去重后，按 Rank 排序）')
    print(f'快照   {os.path.relpath(args.state, WSP.ROOT)}：生成于 {state_doc.get("generated_at", "?")}'
          f' · 词条 {len(state)}')
    print()

    head = (f"{'千词区间':>12}  {'Rank范围':>14}  {'词数':>5}  "
            f"{'有卡%':>7}  {'已学':>5} {'已学%':>7}  {'成熟':>5} {'成熟%':>7}")
    print(head)
    print('-' * len(head))

    buckets_out = []
    tot = {'total': 0, 'has_card': 0, 'known': 0, 'mature': 0}
    for b in range(nbuckets):
        grp = words[b * args.bucket:(b + 1) * args.bucket]
        st = {'total': len(grp), 'has_card': 0, 'known': 0, 'mature': 0}
        for rank, k, _disp in grp:
            e = state.get(k)
            if e is not None:
                st['has_card'] += 1
                if e.get('known'):
                    st['known'] += 1
                if e.get('mature'):
                    st['mature'] += 1
        for kk in tot:
            tot[kk] += st[kk]
        n = max(1, st['total'])
        buckets_out.append({
            'bucket': b + 1,
            'word_from': b * args.bucket + 1, 'word_to': (b + 1) * args.bucket,
            'rank_min': grp[0][0], 'rank_max': grp[-1][0],
            **st,
            'known_rate': round(st['known'] / n, 4),
            'mature_rate': round(st['mature'] / n, 4),
        })
        print(f"{b * args.bucket + 1:>5}-{(b + 1) * args.bucket:<7} "
              f"{grp[0][0]:>6}-{grp[-1][0]:<7} {st['total']:>5}  "
              f"{st['has_card'] / n * 100:>6.1f}%  "
              f"{st['known']:>5} {st['known'] / n * 100:>6.1f}%  "
              f"{st['mature']:>5} {st['mature'] / n * 100:>6.1f}%")

    n = max(1, tot['total'])
    print('-' * len(head))
    print(f"{'合计':>12} {'-':>14} {tot['total']:>5}  "
          f"{tot['has_card'] / n * 100:>6.1f}%  "
          f"{tot['known']:>5} {tot['known'] / n * 100:>6.1f}%  "
          f"{tot['mature']:>5} {tot['mature'] / n * 100:>6.1f}%")

    T.dump_json({
        'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
        'source_csv': os.path.relpath(args.csv, WSP.ROOT).replace('\\', '/'),
        'state_generated_at': state_doc.get('generated_at'),
        'bucket_size': args.bucket,
        'total_words': len(words),
        'totals': {**tot,
                   'known_rate': round(tot['known'] / n, 4),
                   'mature_rate': round(tot['mature'] / n, 4)},
        'buckets': buckets_out,
    }, args.out)

    # ------------------------------------------------------------- Markdown 报告
    md_path = os.path.splitext(args.out)[0] + '.md'
    lines = [
        f'# jitanAnimeRank 千词区间已学占比',
        '',
        f'- 生成时间：{_dt.datetime.now().isoformat(timespec="seconds")}',
        f'- 词频表：`{os.path.relpath(args.csv, WSP.ROOT).replace(chr(92), "/")}`'
        f'（去重后 **{len(words)}** 个不同词，按 Rank 排序）',
        f'- 词汇快照：`{os.path.relpath(args.state, WSP.ROOT).replace(chr(92), "/")}`'
        f'（生成于 {state_doc.get("generated_at", "?")}，词条 {len(state)}）',
        f'- 区间粒度：每 **{args.bucket}** 个词一个区间（最后一个可能不足）',
        '',
        '> **已学 known** = 有卡且至少复习过一次（reps > 0）；'
        '**成熟 mature** = 复习卡且间隔 ≥ 21 天。占比分母均为该区间词数。',
        '',
        f'| 千词区间 | Rank 范围 | 词数 | 有卡% | 已学 | 已学% | 成熟 | 成熟% |',
        f'|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for b in buckets_out:
        lines.append(
            f"| {b['word_from']}-{b['word_to']} "
            f"| {b['rank_min']}-{b['rank_max']} | {b['total']} "
            f"| {b['has_card'] / max(1, b['total']) * 100:.1f}% "
            f"| {b['known']} | {b['known_rate'] * 100:.1f}% "
            f"| {b['mature']} | {b['mature_rate'] * 100:.1f}% |")
    lines += [
        f"| **合计** | - | **{tot['total']}** "
        f"| **{tot['has_card'] / n * 100:.1f}%** "
        f"| **{tot['known']}** | **{tot['known'] / n * 100:.1f}%** "
        f"| **{tot['mature']}** | **{tot['mature'] / n * 100:.1f}%** |",
        '',
    ]
    T.write_text(md_path, '\n'.join(lines))
    print(f'\n写出 {os.path.relpath(args.out, WSP.ROOT)}')
    print(f'写出 {os.path.relpath(md_path, WSP.ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
