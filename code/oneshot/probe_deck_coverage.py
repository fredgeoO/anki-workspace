"""诊断：按牌组聚合已学卡数量与复习日志覆盖情况。"""
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

print("cards total:", list(cur.execute("select count(*) from cards"))[0][0])
print("revlog total:", list(cur.execute("select count(*) from revlog"))[0][0])
print("distinct did in cards:", list(cur.execute("select count(distinct did) from cards"))[0][0])

decks = {d: (n.decode("utf-8", "replace") if isinstance(n, bytes) else str(n)).replace("\x1f", "::")
         for d, n in cur.execute("select id,name from decks")}
print("\ndid -> name (有卡的):")
cnt = defaultdict(int)
for did, c in cur.execute("select did, count(*) from cards group by did"):
    cnt[did] = c
for did, c in sorted(cnt.items(), key=lambda kv: -kv[1])[:12]:
    print(f"  {did} cards={c:5d}  {decks.get(did, '?')[:60]}")

# revlog coverage
print("\nrevlog 里的 cid 是否都在 cards 里:")
n_all = list(cur.execute("select count(*) from revlog"))[0][0]
n_join = list(cur.execute("select count(*) from revlog r where exists (select 1 from cards c where c.id=r.cid)"))[0][0]
print(f"  revlog={n_all}  能连上 cards 的={n_join}  孤儿={n_all - n_join}")

print("\n每张卡的 revlog 条数分布（前 10 种）:")
h = defaultdict(int)
for cid, n in cur.execute("select cid, count(*) from revlog group by cid"):
    h[min(n, 8)] += 1
for k in sorted(h):
    print(f"  {k}{'+' if k == 8 else ''} 次: {h[k]} 张卡")

print("\n按牌组统计（已学卡 = 有 revlog 的卡）:")
agg = defaultdict(lambda: {"cards": 0, "studied": 0, "sec": 0.0, "reps": 0})
rev = defaultdict(lambda: {"n": 0, "sec": 0.0})
for cid, did in cur.execute("select id,did from cards"):
    a = agg[did]
    a["cards"] += 1
    rows = list(cur.execute("select time from revlog where cid=?", (cid,)))
    if rows:
        a["studied"] += 1
        a["reps"] += len(rows)
        for (t,) in rows:
            if t <= 300_000:
                a["sec"] += t / 1000.0
for cid, t in cur.execute("select cid, time from revlog where time<=300000"):
    rev[0]["n"] += 1
    rev[0]["sec"] += t / 1000.0
print(f"  （全库可用的 revlog 耗时样本：{rev[0]['n']} 条，总 {rev[0]['sec']/3600:.1f} 小时）")
for did, a in sorted(agg.items(), key=lambda kv: -kv[1]["cards"])[:10]:
    print(f"  {decks.get(did,'?')[:52]:52s} cards={a['cards']:5d} studied={a['studied']:5d} "
          f"人均复习={a['reps']/max(a['studied'],1):5.2f} 人均秒={a['sec']/max(a['studied'],1):7.1f}")
con.close()
