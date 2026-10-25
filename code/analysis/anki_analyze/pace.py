import os, sqlite3, collections, datetime
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
nt = {r[0]: r[1] for r in cur.execute("SELECT id, name FROM notetypes")}

GRAM = [k for k, v in nt.items() if v.startswith("どんな")][0]
print("=== grammar note model: cards per deck (studied = reps>0) ===")
q = """SELECT c.did, c.type, c.reps, c.ivl FROM cards c JOIN notes n ON n.id=c.nid WHERE n.mid=?"""
agg = collections.defaultdict(lambda: [0, 0, 0])
for did, type_, reps, ivl in cur.execute(q, (GRAM,)):
    a = agg[decks.get(did, str(did))]
    a[0] += 1
    if reps > 0:
        a[1] += 1
    if type_ == 2 and ivl >= 21:
        a[2] += 1
for k in sorted(agg):
    t, s, m = agg[k]
    print(f"  {k:<52} cards={t:>5} studied={s:>5} mature={m:>5}")

# new-card introduction rate
DAY = 86400000
first = {}
for cid, ts in cur.execute("SELECT cid, id FROM revlog ORDER BY id"):
    if cid not in first:
        first[cid] = ts
byw = collections.Counter()
for cid, ts in first.items():
    d = datetime.datetime.fromtimestamp(ts / 1000)
    wk = d.strftime("%Y-W%W")
    byw[wk] += 1
print("\n=== new cards introduced per week (first exposure) ===")
for k in sorted(byw):
    print(f"  {k}: {byw[k]}")

# remaining new cards by deck group
print("\n=== unstudied (new) cards remaining, by group ===")
g = collections.defaultdict(int)
for did, name in decks.items():
    n = cur.execute(
        "SELECT count(*) FROM cards WHERE did=? AND reps=0 AND queue=0", (did,)
    ).fetchone()[0]
    if n:
        g[name] = n
for k in sorted(g):
    print(f"  {k:<58} {g[k]}")

# reviews per day last 21 days
print("\n=== reviews per day (last 21 days) ===")
byday = collections.Counter()
for (ts,) in cur.execute("SELECT id FROM revlog"):
    d = datetime.datetime.fromtimestamp(ts / 1000).date()
    byday[d] += 1
for d in sorted(byday)[-21:]:
    print(f"  {d}: {byday[d]}")

# ease distribution on studied cards + due load
print("\n=== due / scheduling ===")
today = datetime.date.today()
dd = collections.Counter()
for due, type_, queue, reps in cur.execute("SELECT due, type, queue, reps FROM cards WHERE queue IN (2,3)"):
    days = due - today.toordinal()
    dd["overdue" if days < 0 else ("today" if days == 0 else ("1-7d" if days <= 7 else ("8-30d" if days <= 30 else ">30d")))] += 1
for k in ("overdue", "today", "1-7d", "8-30d", ">30d"):
    print(f"  {k}: {dd[k]}")
con.close()
