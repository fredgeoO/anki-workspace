# -*- coding: utf-8 -*-
"""前 N 词「全部成熟」的 ETA —— 简单估算版。

计划：核心卡牌 15 张/天 + 考级卡牌 15 张/天 = 30 张/天（两牌组有重叠）。

算法（小学数学）::

    对每个目标 N（前 1000 / 2000 / 3000 / 5000）把词分成四类：
      M  已成熟                       —— 完成
      K  已学未成熟（在途）           —— 继续复习，~2-3 周自然成熟
      P  还没学、但核心/考级里有卡    —— 要新学的词
      X  没卡（或只在素材生词里）     —— 本计划覆盖不到

    学完待学词的天数 ≈ ceil(P / 30)
    全部成熟 ≈ 学完天数 + 21 天        # 首学→间隔>=21天的 lag，
                                      # revlog 实测：中位 12 天 / p75 18 天
"""
from __future__ import annotations

import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _deps import DATA_DIR, STATE_JSON, WSP  # noqa: E402
from rank_buckets import load_words  # noqa: E402
import textio as T  # noqa: E402

PER_DAY = 30            # 核心 15 + 考级 15
LAG_DAYS = 21           # 首学 → 成熟（间隔>=21天）的保守 lag；实测中位 ~12-18 天
TARGETS = (1000, 2000, 3000, 5000)


def main() -> int:
    with open(STATE_JSON, encoding='utf-8') as fh:
        state_doc = json.load(fh)
    state = state_doc['words']

    words = load_words(os.path.join(WSP.DATA, 'freq', 'jiten_freq_Anime.csv'))
    words.sort(key=lambda t: (t[0], t[1]))
    top_sets = {n: [k for _, k, _ in words[:n]] for n in TARGETS}

    print(f'快照 {os.path.relpath(STATE_JSON, WSP.ROOT)}：生成于 {state_doc.get("generated_at", "?")}')
    print(f'计划 每天新卡 {PER_DAY} 张（核心15 + 考级15）；首学→成熟按 +{LAG_DAYS} 天计')
    print()

    out = {'generated_at': state_doc.get('generated_at'),
           'per_day': PER_DAY, 'lag_days': LAG_DAYS, 'targets': {}}
    for n in TARGETS:
        m = k = p = x = 0
        for key in top_sets[n]:
            e = state.get(key)
            if e and e.get('mature'):
                m += 1
            elif e and e.get('known'):
                k += 1
            elif e is not None and (e.get('core') is not None or e.get('jlpt')):
                p += 1
            else:
                x += 1
        learn_days = math.ceil(p / PER_DAY) if p else 0
        eta = learn_days + LAG_DAYS
        reachable = (m + k + p) / n * 100
        out['targets'][str(n)] = {'mature': m, 'in_progress': k, 'pending': p,
                                  'no_card': x, 'learn_days': learn_days,
                                  'eta_days': eta, 'reachable_pct': round(reachable, 1)}
        print(f'前{n}: 成熟 {m:>4} | 在途 {k:>3} | 待学 {p:>4} | 无卡 {x:>4}')
        tail = f'，但「无卡」{x} 个本计划学不到（可达上限 {reachable:.0f}%）' if x else ''
        print(f'      待学 {p} ÷ {PER_DAY}/天 ≈ {learn_days} 天学完，+{LAG_DAYS} 天成熟'
              f' → 约 {eta} 天（{eta/7:.1f} 周）后达标{tail}')

    print()
    d = state_doc.get('decks', {})
    for name, logical in (('核心 core6000', 'core6000'), ('考级 jlpt', 'jlpt')):
        info = d.get(logical, {})
        left = info.get('notes', 0) - info.get('studied', 0)
        print(f'{name}: 共 {info.get("notes", 0)} 词，剩 {left} 个未学'
              f' → 按 15/天约 {math.ceil(left / 15)} 天学完整个牌组')

    out_path = os.path.join(DATA_DIR, 'mature_eta.json')
    T.dump_json(out, out_path)
    print(f'\n写出 {os.path.relpath(out_path, WSP.ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
