import importlib.util, sys
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

SEEDS = (3, 11, 29, 47, 61)
BASE = dict(mod.TIME)


def run(plan, lapse, core_scale):
    mod.LAPSE_MULT = lapse
    mod.TIME = dict(BASE)
    for b in mod.ORDER:
        for t in (0, 1, 2):
            if b == "Core6000":
                mod.TIME[(b, t)] = BASE[(b, t)] * core_scale
    acc = [0.0, 0.0]
    for sd in SEEDS:
        daily = mod.run(plan, 400, seed=sd)
        c, s = mod.win(daily, 0, 180)
        acc[0] += c / len(SEEDS)
        acc[1] += s / len(SEEDS)
    mod.TIME = dict(BASE)
    return acc


PLANS = {
    "A 你的配置 (对白=2)": dict(core=15, vocab=5, gexp=2, gex=8, dlg=2),
    "B 你的配置 (对白=10)": dict(core=15, vocab=5, gexp=2, gex=8, dlg=10),
    "C 看字提到10 (对白=2)": dict(core=15, vocab=10, gexp=2, gex=8, dlg=2),
    "D 看字提到10 (对白=10)": dict(core=15, vocab=10, gexp=2, gex=8, dlg=10),
    "E 听辨15/看字15/语法10/对白2": dict(core=15, vocab=15, gexp=2, gex=8, dlg=2),
    "参考: 你原来的(52)": dict(core=20, vocab=15, gexp=4, gex=11, dlg=2),
}

for lapse, scale, tag in ((0.0, 1.0, "现状：lapse 0% + 听辨 21.8 秒（未改模板）"),
                          (0.25, 0.64, "已优化：lapse 25% + 听辨 14 秒（改模板后）")):
    print("=" * 100)
    print(tag)
    print("=" * 100)
    print(f"   {'方案':<30}{'新卡/天':>8}{'卡片/天':>10}{'分钟/天':>10}{'小时/天':>9}")
    for name, plan in PLANS.items():
        c, s = run(plan, lapse, scale)
        print(f"   {name:<30}{sum(plan.values()):>8}{c:>10.0f}{s/60:>10.0f}"
              f"{s/3600:>9.2f}")
    print()

print("=" * 100)
print("方案 A 的分区明细（已优化：lapse 25% + 听辨 14 秒；前180天平均）")
print("=" * 100)
mod.LAPSE_MULT = 0.25
mod.TIME = dict(BASE)
for b in mod.ORDER:
    for t in (0, 1, 2):
        if b == "Core6000":
            mod.TIME[(b, t)] = BASE[(b, t)] * 0.64
plan = PLANS["A 你的配置 (对白=2)"]
agg = {}
for sd in SEEDS:
    daily = mod.run(plan, 400, seed=sd)
    for b in mod.ORDER:
        c = sum(day[b][0] for day in daily[0:180]) / 180
        s = sum(day[b][1] for day in daily[0:180]) / 180
        a = agg.setdefault(b, [0.0, 0.0])
        a[0] += c / len(SEEDS)
        a[1] += s / len(SEEDS)
tc = sum(v[0] for v in agg.values())
ts = sum(v[1] for v in agg.values())
print(f"   {'分区':<12}{'卡片/天':>9}{'卡数占比':>9}{'分钟/天':>10}{'时间占比':>9}")
for b in mod.ORDER:
    c, s = agg[b]
    if c < 0.5:
        continue
    print(f"   {b:<12}{c:>9.0f}{c/tc*100:>8.1f}%{s/60:>10.1f}{s/ts*100:>8.1f}%")
print(f"   {'合计':<12}{tc:>9.0f}{100:>8.1f}%{ts/60:>10.1f}{100:>8.1f}%")
print(f"   → {ts/3600:.2f} 小时/天, 平均 {ts/tc:.1f} 秒/张")

print()
print("=" * 100)
print("对白例句牌组能不能撑住 10 张/天")
print("=" * 100)
db = mod.db
db.create_collation("unicase", lambda a, b: (a > b) - (a < b))
n = db.execute("""select count(*) from cards c join decks d on d.id=c.did
                  where d.name = '0-日本语学习::2-例句' and c.type=0""").fetchone()[0]
print(f"   对白例句剩余新卡: {n} 张  →  10 张/天 = {n/10:.0f} 天学完")
print(f"   语法解释剩余新卡: 377 张  →  2 张/天 = {377/2:.0f} 天学完")
print(f"   语法例句剩余新卡: 1362 张 →  8 张/天 = {1362/8:.0f} 天学完")
print(f"   看字(10k)剩余新卡: 8440 张 →  5 张/天 = {8440/5:.0f} 天 ({8440/5/365:.1f} 年)")
print(f"   听辨(Core)剩余新卡: 3622 张 → 15 张/天 = {3622/15:.0f} 天")
