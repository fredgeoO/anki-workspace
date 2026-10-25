"""按牌组统计「引入一张新卡的累计成本」，全部用一次 JOIN，避免逐卡查询。"""
import os
import sqlite3
from collections import defaultdict

WS = r"<工作区根>"
DB = os.path.join(WS, r"data\snapshots\live\collection.anki2")
con = sqlite3.connect(DB)
con.create_collation("unicase", lambda a, b: (a > b) - (a < b))
cur = con.cursor()

decks = {d: (n.decode("utf-8", "replace") if isinstance(n, bytes) else str(n)).replace("\x1f", "::")
         for d, n in cur.execute("select id,name from decks")}
GROUPS = [
    ("0-日本语学习::0-词汇::1-高频日语单词 6000", "Core6000"),
    ("0-日本语学习::0-词汇::2-考级词汇", "词汇10k"),
    ("0-日本语学习::1-语法", "语法"),
    ("0-日本语学习::2-例句", "对白例句"),
    ("0-日本语学习::0-词汇::0-素材生词", "素材生词"),
]


def grp(name):
    for k, v in GROUPS:
        if name.startswith(k):
            return v
    return name


print("cards:", list(cur.execute("select count(*) from cards"))[0][0],
      "revlog:", list(cur.execute("select count(*) from revlog"))[0][0])

# 每张卡的总耗时 / 复习次数 / 首次耗时，一次算完
per_card = {}
for cid, t, ease, rid in cur.execute("select cid, time, ease, id from revlog order by cid, id"):
    d = per_card.setdefault(cid, {"n": 0, "sec": 0.0, "first": None})
    d["n"] += 1
    if t <= 300_000:
        d["sec"] += t / 1000.0
        if d["first"] is None:
            d["first"] = t / 1000.0

agg = defaultdict(lambda: {"cards": 0, "studied": 0, "sec": 0.0, "reps": 0,
                           "first": [], "last_sec": []})
for cid, did in cur.execute("select id, did from cards"):
    g = grp(decks.get(did, "?"))
    a = agg[g]
    a["cards"] += 1
    d = per_card.get(cid)
    if not d:
        continue
    a["studied"] += 1
    a["reps"] += d["n"]
    a["sec"] += d["sec"]
    if d["first"] is not None:
        a["first"].append(d["first"])
    a["last_sec"].append(d["sec"])


def med(v):
    v = sorted(v)
    return v[len(v) // 2] if v else 0.0


print(f"\n{'牌组':12s} {'总卡':>6s} {'已学':>6s} {'人均复习':>7s} {'引入一张(分)':>12s} "
      f"{'首刷中位':>8s} {'累计中位':>8s}")
for g in ["Core6000", "词汇10k", "语法", "对白例句", "素材生词"]:
    a = agg.get(g)
    if not a or not a["studied"]:
        print(f"{g:12s} {'-':>6s} {'-':>6s}")
        continue
    print(f"{g:12s} {a['cards']:6d} {a['studied']:6d} {a['reps']/a['studied']:7.2f} "
          f"{a['sec']/a['studied']/60:12.1f} {med(a['first']):7.1f}s "
          f"{med(a['last_sec']):7.1f}s")

tot_h = sum(a["sec"] for a in agg.values()) / 3600
print(f"\n以上牌组累计刷卡 {tot_h:.1f} 小时（含音频播放与读答案）")
# 近期每天各牌组占比
print("\n近 14 天各牌组的时间占比（按 revlog 累计秒）:")
import time
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
cut = (max(r[0] for r in cur.execute("select id from revlog")) - 14 * 86400_000)
share = defaultdict(float)
for t, did in cur.execute("""select r.time, c.did from revlog r join cards c on c.id=r.cid
                             where r.id>=? and r.time<=300000""", (cut,)):
    share[grp(decks.get(did, "?"))] += t / 1000.0
tot = sum(share.values())
for g, sec in sorted(share.items(), key=lambda kv: -kv[1])[:8]:
    print(f"  {g[:40]:40s} {sec/60:7.1f} 分钟  {sec/tot*100:5.1f}%   ({sec/14/60:.1f} 分/天)")
print(f"  合计 {tot/60:.1f} 分钟 = {tot/14/60:.1f} 分钟/天")
con.close()
