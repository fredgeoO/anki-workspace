# -*- coding: utf-8 -*-
"""Read-only probe: POS label distributions in the two vocab decks, from a snapshot c.anki2 (Anki v3 schema)."""
import collections
import sqlite3
import os
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

DB = r"<工作区根>\data\snapshots\ankisnap2\c.anki2"
MODELS = {
    "Japanese Vocabulary": {"word": "Word", "pos": "Part of Speech"},
    "eggrolls-JLPT10k-v3.5": {"word": "VocabKanji", "pos": "VocabPoS"},
}

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = con.cursor()

mid_by_name = {name: mid for mid, name in cur.execute("SELECT id, name FROM notetypes")}
deck_names = {did: name for did, name in cur.execute("SELECT id, name FROM decks")}

out = []
for mname, fields in MODELS.items():
    mid = mid_by_name.get(mname)
    if mid is None:
        out.append(f"== {mname}: NOT FOUND ==")
        continue
    flds_order = [r[0] for r in cur.execute("SELECT name FROM fields WHERE ntid=? ORDER BY ord", (mid,))]
    wi = flds_order.index(fields["word"])
    pi = flds_order.index(fields["pos"])
    dids = [r[0] for r in cur.execute(
        "SELECT DISTINCT c.did FROM cards c JOIN notes n ON n.id=c.nid WHERE n.mid=?", (mid,))]
    deck_list = ", ".join(deck_names.get(d, str(d)) for d in dids)
    pos_counts = collections.Counter()
    n_notes = empty_word = 0
    samples = []
    total_mid = cur.execute("SELECT COUNT(*) FROM notes WHERE mid=?", (mid,)).fetchone()[0]
    out.append(f"(total notes for mid: {total_mid})")
    for (flds,) in cur.execute("SELECT flds FROM notes WHERE mid=?", (mid,)):
        parts = flds.split("\x1f") if "\x1f" in flds else flds.split("\t")
        if len(parts) <= max(wi, pi):
            continue
        w, p = parts[wi].strip(), parts[pi].strip()
        if not w:
            empty_word += 1
            continue
        n_notes += 1
        pos_counts[p] += 1
        if len(samples) < 6:
            samples.append((w, p))
    out.append(f"== {mname} (mid={mid}) decks=[{deck_list}] ==")
    out.append(f"notes with word: {n_notes}, empty word: {empty_word}")
    for pos, cnt in pos_counts.most_common():
        out.append(f"  {pos!r}: {cnt}")
    out.append("samples: " + repr(samples))
    out.append("")

con.close()
text = "\n".join(out)
with open(r"<工作区根>\code\oneshot\_pos_dist_out.txt", "w", encoding="utf-8") as f:
    f.write(text)
print("written _pos_dist_out.txt")
