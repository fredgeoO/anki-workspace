import os, sqlite3, collections, datetime
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(os.path.join(HERE, "collection_snapshot.anki2"))
con.create_collation("unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
cur = con.cursor()
rows = list(cur.execute("SELECT id, cid, ease, time, type FROM revlog ORDER BY id"))

print("=== 复习时间分布（按小时）===")
h = collections.defaultdict(lambda: [0, 0])
for ts, cid, ease, time_, type_ in rows:
    hr = datetime.datetime.fromtimestamp(ts / 1000).hour
    h[hr][0] += 1
    if ease == 1:
        h[hr][1] += 1
for hr in sorted(h):
    c, f = h[hr]
    bar = "#" * int(c / 120)
    print(f"  {hr:02d}:00  {c:>6}  忘记率 {100*f/c:>5.1f}%  {bar}")

print("\n=== 疲劳效应：当天第 N 张卡的忘记率 ===")
byday = collections.defaultdict(list)
for ts, cid, ease, time_, type_ in rows:
    d = datetime.datetime.fromtimestamp(ts / 1000).date()
    byday[d].append((ts, ease, time_))
print(f"  {'当天区间':<14}{'答题数':>8}{'忘记率':>8}{'平均耗时':>10}")
for lo, hi, lbl in ((0, 30, "第1-30张"), (30, 60, "31-60"), (60, 120, "61-120"),
                    (120, 200, "121-200"), (200, 999999, "200张以上")):
    c = f = 0
    ms = 0
    for d, lst in byday.items():
        lst.sort()
        for i, (ts, ease, time_) in enumerate(lst):
            if lo <= i < hi:
                c += 1
                ms += time_
                if ease == 1:
                    f += 1
    if c:
        print(f"  {lbl:<14}{c:>8}{100*f/c:>7.1f}%{ms/c/1000:>9.1f}s")

print("\n=== 一周中的分布 ===")
wd = collections.defaultdict(lambda: [0, 0])
for ts, cid, ease, time_, type_ in rows:
    k = datetime.datetime.fromtimestamp(ts / 1000).strftime("%a")
    wd[k][0] += 1
    if ease == 1:
        wd[k][1] += 1
for k in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
    if k in wd:
        c, f = wd[k]
        print(f"  {k}  {c:>6}  忘记率 {100*f/c:>5.1f}%")
con.close()
