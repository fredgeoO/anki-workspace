import os, sqlite3, time, datetime, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

db = sys.argv[1] if len(sys.argv) > 1 else WSP.SNAP_ANKI_SNAPSHOT_DB
con = sqlite3.connect(db)
cur = con.cursor()
now = int(time.time())
cutoff = now - 86400

# sanity: what values does `ease` hold, and how fresh is the data?
print("sanity: distinct ease values (all time):")
for v, c in cur.execute("SELECT ease, COUNT(*) FROM revlog GROUP BY ease ORDER BY ease"):
    print(f"  ease={v}: {c}")
maxt = cur.execute("SELECT MAX(time) FROM revlog").fetchone()[0]
print("sanity: max review time:", datetime.datetime.fromtimestamp(maxt))

total, distinct, tmin, tmax = cur.execute(
    "SELECT COUNT(*), COUNT(DISTINCT cid), MIN(time), MAX(time) FROM revlog WHERE ease = 1 AND time >= ?",
    (cutoff,),
).fetchone()

print("---")
print("now     :", datetime.datetime.fromtimestamp(now))
print("cutoff  :", datetime.datetime.fromtimestamp(cutoff))
print("again_reviews_last_24h :", total)
print("distinct_cards         :", distinct)
if tmin:
    print("first_again:", datetime.datetime.fromtimestamp(tmin))
if tmax:
    print("last_again :", datetime.datetime.fromtimestamp(tmax))

print("--- by day (localtime) ---")
for d, c in cur.execute(
    "SELECT date(time,'unixepoch','localtime'), COUNT(*) FROM revlog WHERE ease=1 AND time>=? GROUP BY 1 ORDER BY 1",
    (cutoff,),
):
    print(d, c)

con.close()
