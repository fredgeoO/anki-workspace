import os, sqlite3, collections, datetime, statistics
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(os.path.join(HERE, "collection_snapshot.anki2"))
con.create_collation("unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
cur = con.cursor()
SEP = "\x1f"
decks = {r[0]: r[1].replace(SEP, "::") for r in cur.execute("SELECT id, name FROM decks")}
card_deck = {r[0]: r[1] for r in cur.execute("SELECT id, did FROM cards")}


def group(name):
    if not name:
        return "?"
    if "高频日语单词 6000" in name:
        return "core6000"
    if "考级词汇" in name:
        return "考级词汇"
    if "-解释" in name:
        return "语法-解释"
    if "例句" in name and "语法" in name:
        return "语法-例句"
    if name.endswith("2-例句"):
        return "挖句(2-例句)"
    return "其他"


DAY = 86400000
rows = list(cur.execute("SELECT id, cid, ease, time, type FROM revlog ORDER BY id"))

# --- per-day: total reps, new cards introduced, minutes ---
first_seen = {}
for ts, cid, ease, time_, type_ in rows:
    if cid not in first_seen:
        first_seen[cid] = ts

byday = collections.defaultdict(lambda: {"reps": 0, "ms": 0, "new": 0})
for ts, cid, ease, time_, type_ in rows:
    d = datetime.datetime.fromtimestamp(ts / 1000).date()
    byday[d]["reps"] += 1
    byday[d]["ms"] += time_
for cid, ts in first_seen.items():
    d = datetime.datetime.fromtimestamp(ts / 1000).date()
    byday[d]["new"] += 1

print("=== 最近 21 天实际节奏 ===")
print(f"  {'日期':<12}{'复习次数':>8}{'新卡':>6}{'用时(分)':>10}{'秒/次':>8}")
tot = {"reps": 0, "ms": 0, "new": 0}
for d in sorted(byday)[-21:]:
    v = byday[d]
    m = v["ms"] / 60000
    print(f"  {str(d):<12}{v['reps']:>8}{v['new']:>6}{m:>10.0f}{v['ms']/max(1,v['reps'])/1000:>8.1f}")
    tot["reps"] += v["reps"]; tot["ms"] += v["ms"]; tot["new"] += v["new"]
print(f"  {'21天合计':<12}{tot['reps']:>8}{tot['new']:>6}{tot['ms']/60000:>10.0f}"
      f"{tot['ms']/max(1,tot['reps'])/1000:>8.1f}")
print(f"  日均: {tot['reps']/21:.0f} 次复习, {tot['new']/21:.1f} 新卡, "
      f"{tot['ms']/60000/21:.1f} 分钟")

# --- recent days by deck group ---
print("\n=== 最近 7 天各类新卡（首次出现）===")
cut = max(byday) - datetime.timedelta(days=6)
g = collections.defaultdict(collections.Counter)
for cid, ts in first_seen.items():
    d = datetime.datetime.fromtimestamp(ts / 1000).date()
    if d >= cut:
        g[d][group(decks.get(card_deck.get(cid, 0), ""))] += 1
groups = sorted({k for c in g.values() for k in c})
print(f"  {'日期':<12}" + "".join(f"{x:>12}" for x in groups) + f"{'合计':>8}")
for d in sorted(g):
    row = g[d]
    print(f"  {str(d):<12}" + "".join(f"{row[x]:>12}" for x in groups) + f"{sum(row.values()):>8}")

# --- time per answer by group ---
print("\n=== 每类卡片平均答题耗时 ===")
t = collections.defaultdict(list)
for ts, cid, ease, time_, type_ in rows:
    t[group(decks.get(card_deck.get(cid, 0), ""))].append(time_ / 1000)
for k in sorted(t, key=lambda k: -statistics.mean(t[k])):
    v = t[k]
    print(f"  {k:<14} 次数={len(v):>6}  平均={statistics.mean(v):>5.1f}s  中位={statistics.median(v):>5.1f}s")

# --- forget rate by group (review-type answers only) ---
print("\n=== 各类遗忘率（仅复习型答题）===")
agg = collections.defaultdict(lambda: [0, 0])
for ts, cid, ease, time_, type_ in rows:
    if type_ == 1:
        k = group(decks.get(card_deck.get(cid, 0), ""))
        agg[k][0] += 1
        if ease == 1:
            agg[k][1] += 1
for k in sorted(agg):
    c, f = agg[k]
    print(f"  {k:<14} 复习次数={c:>6}  忘记率={100*f/max(1,c):>5.1f}%")

# --- projected load ---
print("\n=== 负荷推算（基于你自己的数据）===")
ratio = tot["reps"] / max(1, tot["new"])
sec = tot["ms"] / max(1, tot["reps"]) / 1000
print(f"  实测: 每引入 1 张新卡 ≈ {ratio:.1f} 次复习/天（近期稳态比）")
print(f"  实测: 每次答题 {sec:.1f} 秒")
for n in (63, 55, 45, 35, 25):
    reps = n * ratio
    print(f"  新卡 {n:>3}/天 -> 稳态约 {reps:>4.0f} 次复习/天 -> "
          f"{reps*sec/3600:>4.1f} 小时 -> 约 {reps*sec/1500:>4.1f} 个番茄钟(25min)")
con.close()
