# -*- coding: utf-8 -*-
"""近两天（昨天0点起）复习中答错/困难的卡片，输出单词 + 简单解释。"""
import os, sqlite3, json, re, html, sys, datetime as dt
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

DB = sys.argv[1] if len(sys.argv) > 1 else WSP.SNAP_ANKI_SNAP
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.create_collation("unicase", lambda a, b: (a > b) - (a < b))
con.row_factory = sqlite3.Row
cur = con.cursor()

now = dt.datetime.now()
start = now.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=1)
t0 = int(start.timestamp() * 1000)

# ---- model metadata: mid -> (name, [field names in order]) ----
mid2model = {}
for ntid, name in list(cur.execute("SELECT id, name FROM notetypes")):
    sub = con.cursor()
    cols = {r[0]: r[1] for r in sub.execute(
        "SELECT ord, name FROM fields WHERE ntid = ?", (ntid,))}
    mid2model[int(ntid)] = (name, [cols[i] for i in sorted(cols)])

rows = cur.execute(
    """
    SELECT r.id AS rid, r.cid, r.ease, r.type, r.ivl, r.lastIvl,
           c.nid, c.did, n.mid, n.flds, d.name AS deck
    FROM revlog r
    JOIN cards c  ON c.id = r.cid
    JOIN notes n  ON n.id = c.nid
    JOIN decks d  ON d.id = c.did
    WHERE r.id >= ? AND r.ease IN (1,2)
    """, (t0,)
).fetchall()

print(f"窗口: {start:%Y-%m-%d %H:%M} → {now:%Y-%m-%d %H:%M}")
print(f"重来/困难 作答记录数 = {len(rows)}")
byday = defaultdict(int)
for r in rows:
    byday[dt.datetime.fromtimestamp(r["rid"] / 1000).strftime("%Y-%m-%d")] += 1
print("按天:", dict(sorted(byday.items())))

def clean(s):
    s = re.sub(r"\[sound:[^\]]*\]", " ", s or "")
    s = re.sub(r"<br\s*/?>", " / ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

agg = defaultdict(lambda: {"again": 0, "hard": 0, "nid": 0, "mid": 0,
                           "deck": "", "last": 0})
for r in rows:
    a = agg[r["cid"]]
    a["again" if r["ease"] == 1 else "hard"] += 1
    a["nid"] = r["nid"]; a["mid"] = r["mid"]; a["deck"] = r["deck"]
    a["last"] = max(a["last"], r["rid"])

cids = list(agg.keys())
q = ",".join("?" * len(cids))
state = {r["id"]: dict(r) for r in cur.execute(
    f"SELECT id, type, queue, due, ivl, reps, lapses FROM cards WHERE id IN ({q})", cids)}

nids = sorted({a["nid"] for a in agg.values()})
notes = {}
for i in range(0, len(nids), 500):
    ch = nids[i:i + 500]
    qq = ",".join("?" * len(ch))
    for nr in cur.execute(f"SELECT id, flds FROM notes WHERE id IN ({qq})", ch):
        notes[nr["id"]] = nr["flds"]

def extract(mid, flds_raw):
    name, order = mid2model.get(mid, ("?", []))
    vals = (flds_raw or "").split("\x1f")
    d = {order[i]: vals[i] for i in range(min(len(order), len(vals)))}
    if name == "Japanese Vocabulary":
        return (name, clean(d.get("Word", "")) or clean(d.get("Index", "")),
                clean(d.get("Transliteration", "")), clean(d.get("Meaning", "")),
                clean(d.get("Part of Speech", "")))
    if name == "eggrolls-JLPT10k-v3.5":
        return (name, clean(d.get("VocabKanji", "")) or clean(d.get("VocabFurigana", "")),
                clean(d.get("VocabFurigana", "")), clean(d.get("VocabDefSC", "")),
                clean(d.get("VocabPoS", "")))
    ne = [(k, clean(d.get(k, ""))) for k in order]
    ne = [(k, v) for k, v in ne if v]
    return (name,
            clean(d.get("Card", "")) or (ne[0][1] if ne else "?"),
            clean(d.get("Bracket", "")),
            clean(d.get("MeaningCN", "")) or clean(d.get("MeaningJP", "")) or
            max((v for k, v in ne[1:]), key=len, default=""),
            "")

out = []
for cid, a in agg.items():
    name, word, read, mean, pos = extract(a["mid"], notes.get(a["nid"], "[]"))
    st = state.get(cid, {})
    out.append(dict(cid=cid, again=a["again"], hard=a["hard"], deck=a["deck"],
                    model=name, word=word, read=read, mean=mean, pos=pos,
                    lapses=st.get("lapses", 0), reps=st.get("reps", 0),
                    ivl=st.get("ivl", 0), type=st.get("type", 0), last=a["last"]))

out.sort(key=lambda x: (-x["again"], -x["hard"], x["word"]))
print(f"\n涉及卡片数 = {len(out)}  重来过 = {sum(1 for o in out if o['again'])}\n")

with open(os.path.join(WSP.DATA_WEAK, "weak_words_2d.json"),
          "w", encoding="utf-8") as fh:
    json.dump([{**o, "last": dt.datetime.fromtimestamp(o["last"] / 1000).strftime("%m-%d %H:%M")}
               for o in out], fh, ensure_ascii=False, indent=1)

for o in out:
    print(json.dumps({
        "last": dt.datetime.fromtimestamp(o["last"] / 1000).strftime("%m-%d %H:%M"),
        "again": o["again"], "hard": o["hard"], "lapses": o["lapses"],
        "type": o["type"], "ivl": o["ivl"], "model": o["model"][:12],
        "deck": o["deck"].replace("\x1f", "::"), "word": o["word"][:50],
        "read": o["read"][:30], "pos": o["pos"][:20], "mean": o["mean"][:130],
    }, ensure_ascii=False))
con.close()
