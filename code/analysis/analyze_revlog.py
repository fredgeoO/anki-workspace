# -*- coding: utf-8 -*-
"""Anki 自评按钮校准分析：基于 revlog 原始作答记录。"""
import os, sys
import sqlite3, json, statistics, datetime as dt
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

DB = WSP.SNAP_ANKI_SNAP   # 离线快照（code/analysis/anki_analyze/introspect.py 可重建）
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
cur = con.cursor()

NAME = {1: "重来", 2: "困难", 3: "良好", 4: "简单"}
TNAME = {0: "学习(新/学)", 1: "复习", 2: "重学", 3: "筛选/ cram", 4: "手动", 5: "重排"}

def pct(n, d):
    return f"{100.0*n/d:.2f}%" if d else "n/a"

print("=" * 78)
print("0. 环境检查")
print("=" * 78)
col = cur.execute("SELECT * FROM col").fetchone()
conf = json.loads(col["conf"]) if col["conf"] else {}
print("col.ver =", col["ver"])
gc = cur.execute("SELECT id, name, config FROM deck_config").fetchall()
fsrs_hits = sum(1 for r in gc if b"fsrs" in bytes(r["config"]).lower())
print("deck_config 条数 =", len(gc), "| 二进制中出现 'fsrs' 的配置数 =", fsrs_hits)
ck = [r["KEY"] for r in cur.execute("SELECT KEY FROM config")]
print("config 表中的键:", ", ".join(sorted(ck))[:600])
print("col.conf 顶层键:", ", ".join(sorted(conf.keys()))[:600])


rows = cur.execute(
    "SELECT id, cid, ease, ivl, lastIvl, factor, time, type FROM revlog ORDER BY id"
).fetchall()
print("revlog 总条数 =", len(rows))
if rows:
    t0 = dt.datetime.fromtimestamp(rows[0]["id"] / 1000)
    t1 = dt.datetime.fromtimestamp(rows[-1]["id"] / 1000)
    print("时间跨度:", t0, "→", t1)

# ---------- 1. 全体按钮分布（含所有类型） ----------
print()
print("=" * 78)
print("1. 按钮总体分布（全部 revlog，含筛选/手动）")
print("=" * 78)
tot = Counter()
for r in rows:
    tot[r["ease"]] += 1
s = sum(tot.values())
for k in sorted(tot):
    print(f"  ease={k} {NAME.get(k,'?'):<4} {tot[k]:>7}  {pct(tot[k],s)}")
print(f"  合计 {s}")

# ---------- 2. 按作答时的卡片状态分类 ----------
print()
print("=" * 78)
print("2. 按「作答时卡片状态」拆分（排除手动/重排 type>=4）")
print("=" * 78)
main = [r for r in rows if r["type"] in (0, 1, 2) and 1 <= r["ease"] <= 4]
print(f"有效条数 = {len(main)}（剔除了 {len(rows)-len(main)} 条手动/重排/异常记录）")
byt = defaultdict(Counter)
for r in main:
    byt[r["type"]][r["ease"]] += 1
print()
print(f"{'状态':<12}{'条数':>8}{'重来':>9}{'困难':>9}{'良好':>9}{'简单':>9}")
for t in sorted(byt):
    c = byt[t]
    n = sum(c.values())
    print(f"{TNAME[t]:<12}{n:>8}" + "".join(
        f"{pct(c[k], n):>9}" for k in (1, 2, 3, 4)))

# ---------- 3. 真实保持率（复习卡） ----------
print()
print("=" * 78)
print("3. 复习卡的真实保持率（按上次间隔分组，Anki「True Retention」口径）")
print("=" * 78)
buckets = [(0, 0, "首次/学习"), (1, 1, "1天"), (2, 6, "2-6天(年轻)"), (7, 20, "7-20天(年轻)"),
           (21, 60, "21-60天(成熟)"), (61, 180, "61-180天(成熟)"), (181, 10 ** 9, "180天+(成熟)")]
rev = [r for r in main if r["type"] == 1]
print(f"复习卡作答数 = {len(rev)}")
print(f"{'上次间隔':<18}{'条数':>8}{'重来率(=失忆率)':>16}{'困难率':>10}{'简单率':>10}")
for lo, hi, lab in buckets:
    g = [r for r in rev if lo <= r["lastIvl"] <= hi]
    if not g:
        continue
    n = len(g)
    a = sum(1 for r in g if r["ease"] == 1)
    h = sum(1 for r in g if r["ease"] == 2)
    e = sum(1 for r in g if r["ease"] == 4)
    print(f"{lab:<18}{n:>8}{pct(a,n):>16}{pct(h,n):>10}{pct(e,n):>10}")

# ---------- 4. 自评的「区分度/校准」 ----------
print()
print("=" * 78)
print("4. 校准核心：按下某按钮后，这张卡下次回来时的失忆率")
print("=" * 78)
print("（若「困难」与「良好」的下次失忆率接近，说明这个区分没有信息量；")
print(" 若「简单」的下次失忆率明显更高，说明当时高估了自己）")
bycard = defaultdict(list)
for r in main:
    bycard[r["cid"]].append(r)
cur_e = lambda r: r["ease"]
nxt_e = {}
for cid, lst in bycard.items():
    for i in range(len(lst) - 1):
        nxt_e[(cid, lst[i]["id"])] = lst[i + 1]["ease"]

for tlabel, tsel in (("复习卡(type=1)", 1), ("学习+重学(type=0,2)", 0)):
    print()
    print(f"-- {tlabel} --")
    print(f"{'按下':<8}{'次数':>8}{'下次失忆率':>12}{'下次仍按困难+':>14}{'平均间隔增长':>14}")
    for k in (1, 2, 3, 4):
        g = [r for r in main if r["type"] == tsel and r["ease"] == k and (r["cid"], r["id"]) in nxt_e]
        if not g:
            continue
        n = len(g)
        again = sum(1 for r in g if nxt_e[(r["cid"], r["id"])] == 1)
        hard = sum(1 for r in g if nxt_e[(r["cid"], r["id"])] == 2)
        # 间隔增长倍数（仅复习卡有意义）
        gr = [r["ivl"] / r["lastIvl"] for r in g if r["lastIvl"] and r["lastIvl"] > 0]
        gm = f"{statistics.mean(gr):.2f}x" if gr else "-"
        print(f"{NAME[k]:<8}{n:>8}{pct(again,n):>12}{pct(hard,n):>14}{gm:>14}")

# ---------- 5. 用时 ----------
print()
print("=" * 78)
print("5. 每个按钮的平均作答用时（毫秒）——「秒答」比例")
print("=" * 78)
for tsel, tlabel in ((1, "复习卡"), (0, "学习卡")):
    print(f"-- {tlabel} --")
    for k in (1, 2, 3, 4):
        g = [r["time"] for r in main if r["type"] == tsel and r["ease"] == k and r["time"] > 0]
        if not g:
            continue
        med = statistics.median(g)
        fast = sum(1 for x in g if x < 3000)
        print(f"  {NAME[k]:<4} n={len(g):>6} 中位数 {med/1000:>5.1f}s 平均 {statistics.mean(g)/1000:>5.1f}s  "
              f"<3秒占比 {pct(fast,len(g)):>7}")

# ---------- 6. 难度因子 / 易度变化 ----------
print()
print("=" * 78)
print("6. 易度因子(ease factor)变化 —— 复习卡上的失败是否在持续惩罚")
print("=" * 78)
cards = cur.execute("SELECT id, factor, ivl, type, reps, lapses FROM cards").fetchall()
fac = [c["factor"] for c in cards if c["type"] == 2 and c["factor"]]
if fac:
    print(f"复习中卡片数={len(fac)} 平均易度={statistics.mean(fac)/1000:.3f} "
          f"中位={statistics.median(fac)/1000:.3f} min={min(fac)/1000:.3f} max={max(fac)/1000:.3f}")
    low = sum(1 for f in fac if f < 2000)
    print(f"易度<2.00 的卡片 {low} 张 ({pct(low,len(fac))})  ← 反复失败被压低")
    hi = sum(1 for f in fac if f > 2600)
    print(f"易度>2.60 的卡片 {hi} 张 ({pct(hi,len(fac))})  ← 「简单」按得多")
lapses = [c["lapses"] for c in cards if c["type"] == 2]
reps = [c["reps"] for c in cards if c["type"] == 2 and c["reps"]]
if lapses:
    print(f"每张复习卡平均遗忘(lapse)次数 = {statistics.mean(lapses):.2f}，"
          f"0次占比 {pct(sum(1 for x in lapses if x==0), len(lapses))}")
if reps:
    print(f"复习卡平均总作答次数 = {statistics.mean(reps):.2f}")

# ---------- 7. 趋势：前后对比 ----------
print()
print("=" * 78)
print("7. 时间趋势：自评习惯是否在漂移（按自然月）")
print("=" * 78)
bym = defaultdict(Counter)
for r in main:
    d = dt.datetime.fromtimestamp(r["id"] / 1000)
    bym[f"{d.year}-{d.month:02d}"][r["ease"]] += 1
print(f"{'月份':<9}{'条数':>8}{'重来':>9}{'困难':>9}{'良好':>9}{'简单':>9}")
for m in sorted(bym):
    c = bym[m]
    n = sum(c.values())
    print(f"{m:<9}{n:>8}" + "".join(f"{pct(c[k],n):>9}" for k in (1, 2, 3, 4)))

# ---------- 8. 新卡首答 ----------
print()
print("=" * 78)
print("8. 新卡「第一次作答」的按钮分布（判断是否在学已知内容 / 是否高估）")
print("=" * 78)
first = {}
for r in rows:
    if r["ease"] in (1, 2, 3, 4):
        if r["cid"] not in first:
            first[r["cid"]] = r
c = Counter(r["ease"] for r in first.values())
n = sum(c.values())
print(f"卡片总数(有作答记录) = {n}")
for k in (1, 2, 3, 4):
    print(f"  {NAME[k]:<4} {c[k]:>7}  {pct(c[k],n)}")
print()
print("  这些「首答」发生在什么状态：")
tc = Counter(r["type"] for r in first.values())
for k in sorted(tc):
    print(f"    type={k} {TNAME.get(k,'?'):<10} {tc[k]:>7}  {pct(tc[k],n)}")

# ---------- 9. 学习步骤内的重复 ----------
print()
print("=" * 78)
print("9. 同一天内同一张卡被反复作答（学习步骤循环）情况")
print("=" * 78)
byday = defaultdict(list)
for r in main:
    d = dt.datetime.fromtimestamp(r["id"] / 1000).date()
    byday[(d, r["cid"])].append(r)
multi = {k: v for k, v in byday.items() if len(v) > 1}
print(f"同一张卡同一天被作答>1次的情况：{len(multi)} 次组合，"
      f"占当天卡片总数 {pct(len(multi), len(byday))}")
extra = sum(len(v) - 1 for v in multi.values())
print(f"其中额外重复作答次数 = {extra}")
