"""Sweep new-cards/day (recommended ratio) with interval fuzz, multi-seed averaged."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import os
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

spec = importlib.util.spec_from_file_location(
    "plan", str(Path(__file__).resolve().parent / "anki_plan.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["plan"] = mod
spec.loader.exec_module(mod)

SHARE = {"vocab": 0.45, "core": 0.20, "gex": 0.20, "gexp": 0.08, "dlg": 0.07}
HORIZON = 420
SEEDS = (3, 11, 29)
WIN = [(0, 30), (30, 60), (60, 90), (90, 120), (120, 150), (150, 180),
       (180, 210), (210, 240), (0, 120), (0, 180), (0, 240)]


def mix(total):
    return {k: max(1, round(total * v)) for k, v in SHARE.items()}


def avg_windows(plan):
    acc = {w: [0.0, 0.0] for w in WIN}
    for sd in SEEDS:
        daily = mod.run(plan, HORIZON, seed=sd)
        for w in WIN:
            c, s = mod.win(daily, *w)
            acc[w][0] += c / len(SEEDS)
            acc[w][1] += s / len(SEEDS)
    return acc


print("=" * 118)
print("参数扫描（推荐配比：词汇45% 听辨20% 语法例句20% 语法解释8% 对白7%），3个随机种子平均，含间隔模糊")
print("=" * 118)
hdr = f"{'新卡/天':>7} | " + " | ".join(
    f"{'d' + str(a) + '-' + str(b):>11}" for a, b in WIN[:6])
print(hdr)
print("-" * 118)
best = {}
for total in (20, 24, 28, 32, 36, 40, 44):
    plan = mix(total)
    acc = avg_windows(plan)
    cells = [f"{acc[w][0]:>5.0f}/{acc[w][1]/60:>4.0f}m" for w in WIN[:6]]
    peak = max(acc[w][0] for w in WIN[:8])
    best[total] = (plan, acc, peak)
    print(f"{total:>7} | " + " | ".join(f"{c:>11}" for c in cells)
          + f"   峰值 {peak:.0f}")

print()
print("=" * 118)
print("候选方案分子")
print("=" * 118)
for total, (plan, acc, peak) in best.items():
    print(f"  合计 {total:>3}/天 → 词汇 {plan['vocab']:>2} | 听辨 {plan['core']:>2} | "
          f"语法解释 {plan['gexp']} | 语法例句 {plan['gex']:>2} | 对白 {plan['dlg']} "
          f"  ‖ 峰值 {peak:.0f} 张/天, 前180天均值 "
          f"{acc[(0,180)][0]:.0f} 张/{acc[(0,180)][1]/60:.0f} 分")

print()
print("=" * 118)
for total in (28, 32, 36):
    plan, acc, peak = best[total]
    print(f"\n### 合计 {total} 新卡/天 → 词汇{plan['vocab']} 听辨{plan['core']} "
          f"语法解释{plan['gexp']} 语法例句{plan['gex']} 对白{plan['dlg']}")
    print(f"  {'窗口':<16}{'卡片/天':>10}{'分钟/天':>11}{'小时/天':>10}{'秒/张':>8}")
    for name, w in [("前30天", (0, 30)), ("31-60天", (30, 60)), ("61-90天", (60, 90)),
                    ("91-120天", (90, 120)), ("121-150天", (120, 150)),
                    ("151-180天", (150, 180)), ("181-210天", (180, 210)),
                    ("211-240天", (210, 240))]:
        c, s = acc[w]
        print(f"  {name:<16}{c:>10.0f}{s/60:>11.0f}{s/3600:>10.2f}{s/max(c,1):>8.1f}")
