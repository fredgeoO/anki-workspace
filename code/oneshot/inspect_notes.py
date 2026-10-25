import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'common'))
import textio  # noqa: E402,F401  UTF-8 stdio 唯一入口（import 即生效）

db = r"<工作区根>\data\snapshots\anki_snapshot.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

print("=== NOTETYPES ===")
cur.execute("SELECT id, name, mtime_secs, usn, config FROM notetypes")
for row in cur.fetchall():
    print(row)

print()
print("=== FIELDS ===")
cur.execute("SELECT ntid, ord, name, config FROM fields")
for row in cur.fetchall():
    print(row)

print()
print("=== TEMPLATES ===")
cur.execute("SELECT ntid, ord, name, mtime_secs, usn, config FROM templates")
for row in cur.fetchall():
    print(row)

print()
print("=== DECKS ===")
cur.execute("SELECT id, name, mtime_secs, usn, common, kind FROM decks")
for row in cur.fetchall():
    print(row)

print()
print("=== SAMPLE NOTES (first 5) ===")
cur.execute("SELECT id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data FROM notes LIMIT 5")
for row in cur.fetchall():
    print(row)
    print('---')

conn.close()
