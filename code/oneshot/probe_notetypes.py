"""One-shot: dump notetype fields/templates for the audio decks, to see which audio
plays on the question side and which on the answer side.

只读探针：经 anki_api.Snapshot（mode=ro）打开 workspace 快照
`data/snapshots/live/collection.anki2`，绝不直连 live 收藏（%APPDATA%\Anki2）。
"""
import gzip
import os
import re
import sys
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
import paths as WSP  # noqa: E402  路径唯一来源（code/common/paths.py）
import anki_api as AK  # noqa: E402  Anki 读写唯一接口（含离线快照 Snapshot）

DB = os.path.join(WSP.SNAPSHOTS, 'live', 'collection.anki2')


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


snap = AK.Snapshot.open(path=DB)

print("=== notetypes ===")
for row in snap.query("select id, name from notetypes"):
    print(f"  {row['id']}  {s(row['name'])}")

print("\n=== fields ===")
f = {}
for row in snap.query("select ntid, ord, name from fields"):
    f.setdefault(int(row['ntid']), []).append((int(row['ord']), s(row['name'])))

# templates: avoid the unicase collation by not ordering by name
print("\n=== templates (raw protobuf strings) ===")
for row in snap.query("select ntid, ord, name, config from templates"):
    txt = s(row['config'])
    print(f"\n--- ntid={row['ntid']} ord={row['ord']} name={s(row['name'])} bytes={len(txt)}")
    # pull printable runs
    for run in re.findall(r"[\x20-\x7e\u3000-\u9fff\uff00-\uffef\r\n]{12,}", txt):
        if any(k in run for k in ("{{", "<div", "sound", "script", "autoplay", "audio")):
            print("    " + run.strip().replace("\n", " | ")[:400])

print("\n=== notes per notetype ===")
cnt = {}
for row in snap.query("select mid from notes"):
    mid = int(row['mid'])
    cnt[mid] = cnt.get(mid, 0) + 1
nt_names = {int(r['id']): s(r['name']) for r in snap.query("select id, name from notetypes")}
for mid, c in sorted(cnt.items(), key=lambda kv: -kv[1]):
    nm = nt_names.get(mid)
    print(f"  {mid} {nm or '?'}  notes={c}  fields={len(f.get(mid, []))}")
    if nm and any(k in nm for k in ("6000", "JLPT", "例句", "语法", "单词", "日")):
        print("      fields:", [x[1] for x in sorted(f.get(mid, []))])
snap.close()
