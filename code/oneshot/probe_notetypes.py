"""One-shot: dump notetype fields/templates for the audio decks, to see which audio
plays on the question side and which on the answer side.
"""
import gzip
import os
import re
import sqlite3
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

WS = r"<工作区根>"
DB = os.path.join(WS, r"data\snapshots\live\collection.anki2")
con = sqlite3.connect(DB)
cur = con.cursor()


def s(v):
    if isinstance(v, bytes):
        if v[:2] == b"\x1f\x8b":
            try:
                v = gzip.decompress(v)
            except Exception:
                pass
        try:
            return v.decode("utf-8")
        except Exception:
            return v.decode("utf-8", "replace")
    return str(v)


print("=== notetypes ===")
for ntid, name in cur.execute("select id, name from notetypes"):
    print(f"  {ntid}  {s(name)}")

print("\n=== fields ===")
f = {}
for ntid, ord_, name in cur.execute("select ntid, ord, name from fields"):
    f.setdefault(ntid, []).append((ord_, s(name)))

# templates: avoid the unicase collation by not ordering by name
print("\n=== templates (raw protobuf strings) ===")
for ntid, ord_, name, cfg in cur.execute("select ntid, ord, name, config from templates"):
    txt = s(cfg)
    print(f"\n--- ntid={ntid} ord={ord_} name={s(name)} bytes={len(txt)}")
    # pull printable runs
    for run in re.findall(r"[\x20-\x7e\u3000-\u9fff\uff00-\uffef\r\n]{12,}", txt):
        if any(k in run for k in ("{{", "<div", "sound", "script", "autoplay", "audio")):
            print("    " + run.strip().replace("\n", " | ")[:400])

print("\n=== notes per notetype ===")
cnt = {}
for (mid,) in cur.execute("select mid from notes"):
    cnt[mid] = cnt.get(mid, 0) + 1
for mid, c in sorted(cnt.items(), key=lambda kv: -kv[1]):
    nm = list(cur.execute("select name from notetypes where id=?", (mid,)))
    print(f"  {mid} {s(nm[0][0]) if nm else '?'}  notes={c}  fields={len(f.get(mid, []))}")
    if nm and any(k in s(nm[0][0]) for k in ("6000", "JLPT", "例句", "语法", "单词", "日")):
        print("      fields:", [x[1] for x in sorted(f.get(mid, []))])
con.close()
