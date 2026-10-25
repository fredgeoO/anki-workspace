import os, shutil, sqlite3
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

SRC = os.path.join(os.environ["APPDATA"], "Anki2", "账户 1", "collection.anki2")
DST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collection_snapshot.anki2")

if not os.path.exists(DST) or os.path.getsize(DST) != os.path.getsize(SRC):
    shutil.copy2(SRC, DST)
print("snapshot:", DST, os.path.getsize(DST))

con = sqlite3.connect(DST)


def unicase(a, b):
    a = a.casefold()
    b = b.casefold()
    return (a > b) - (a < b)


con.create_collation("unicase", unicase)
cur = con.cursor()
print("integrity:", cur.execute("PRAGMA integrity_check").fetchone()[0])

print("\n--- tables ---")
for (n,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(" ", n)

for t in ("notes", "cards", "revlog", "decks", "notetypes"):
    try:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})")]
        cnt = cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"\n{t} ({cnt} rows): {cols}")
    except Exception as e:
        print(f"\n{t}: {e}")

print("\n--- col row ---")
try:
    row = cur.execute("SELECT * FROM col").fetchone()
    cols = [d[0] for d in cur.description]
    for c, v in zip(cols, row):
        print(f"  {c}: {str(v)[:150]}")
except Exception as e:
    print("  ", e)

print("\n--- notetypes ---")
for mid, name in cur.execute("SELECT id, name FROM notetypes"):
    print(" ", mid, name)

print("\n--- decks ---")
for did, name in cur.execute("SELECT id, name FROM decks ORDER BY name"):
    print(" ", did, name)

print("\n--- sample note flds ---")
for mid, flds, tags in cur.execute("SELECT mid, flds, tags FROM notes LIMIT 3"):
    print(" mid=", mid, "tags=", tags)
    print("  flds:", repr(flds[:400]))

con.close()
