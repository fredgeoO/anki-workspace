import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'common'))
import textio  # noqa: E402,F401  UTF-8 stdio 唯一入口（import 即生效）

db = r"<工作区根>\data\snapshots\anki_snapshot.db"
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("TABLES:", tables)
print()
print("=== SCHEMA ===")
for table in tables:
    try:
        cur.execute(f"PRAGMA table_info({table})")
        cols = [(row[1], row[2]) for row in cur.fetchall()]
        print(f"{table}: {cols}")
    except Exception as e:
        print(f"{table}: ERROR {e}")
print()
print("=== COUNTS ===")
for table in tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"{table}: {cur.fetchone()[0]}")
    except Exception as e:
        print(f"{table}: ERROR {e}")
conn.close()
