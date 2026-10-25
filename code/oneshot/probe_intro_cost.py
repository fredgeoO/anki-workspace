"""一次性：每个牌组「引入一张新卡」要多少分钟（首刷 + 后续复习的真实累计）。"""
import os
import sqlite3
from collections import defaultdict
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

WS = r"<工作区根>"
DB = os.path.join(WS, r"data\snapshots\live\collection.anki2")
con = sqlite3.connect(DB)
con.create_collation("unicase", lambda a, b: (a > b) - (a < b))
cur = con.cursor()


def txt(v):
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)


decks = {d: txt(n).replace("\x1f", "::") for d, n in cur.execute("select id,name from decks")}
print("decks sample:", [n for n in decks.values() if n.startswith("0-")][:6])

GROUPS = {
    "0-日本语学习::0-词汇::1-高频日语单词 6000": "Core6000",
    "0-日本语学习::0-词汇::2-考级词汇": "考级词汇10k",
    "0-日本语学习::1-语法": "语法",
    "0-日本语学习::2-例句": "对白例句",
    "0-日本语学习::0-词汇::0-素材生词": "素材生词",
}


def grp(name):
    for k, v in GROUPS.items():
        if name.startswith(k):
            return v
    return "其他"


did2g = {d: grp(n) for d, n in decks.items()}

agg = defaultdict(lambda: {"cards": 0, "sec": 0.0, "reps": 0, "first": [], "mid": [], "hist": []})
for cid, did in cur.execute("select id,did from cards"):
    g = did2g.get(did, "其他")
    rows = list(cur.execute("select time,ease from revlog where cid=? order by id", (cid,)))
    a = agg[g]
    a["cards"] += 1
    if not rows:
        continue
    a["reps"] += len(rows)
    tot = 0.0
    for i, (t, e) in enumerate(rows):
        if t > 300_000:
            continue
        tot += t / 1000.0
        if i == 0:
            a["first"].append(t / 1000.0)
    a["sec"] += tot
    if len(rows) >= 4:
        a["mid"].append(tot / 1000.0)
    a["hist"].append(len(rows))


def med(v):
    v = sorted(v)
    return v[len(v) // 2] if v else 0.0


print(f"\n{'牌组':14s} {'已学卡':>6s} {'人均复习':>7s} {'引入一张(分钟)':>13s} "
      f"{'首刷中位':>8s} {'4次后人均总秒':>12s}")
for g in ["Core6000", "考级词汇10k", "语法", "对白例句", "素材生词"]:
    a = agg.get(g)
    if not a or not a["cards"]:
        continue
    print(f"{g:14s} {a['cards']:6d} {a['reps']/a['cards']:7.2f} "
          f"{a['sec']/a['cards']/60:13.1f} {med(a['first']):7.1f}s {med(a['mid']):11.1f}s")

print("\n样本量说明：以上「引入一张」= 该牌组已学卡从第一次出现到现在的平均累计刷卡秒数")
print("（同一牌组内新旧卡混在一起，因此是历史平均，不是未来边际值）")
con.close()
