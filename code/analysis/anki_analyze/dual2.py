import os, sqlite3, collections, statistics
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(os.path.join(HERE, "collection_snapshot.anki2"))
con.create_collation("unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
cur = con.cursor()
SEP = "\x1f"
ntname = {r[0]: r[1] for r in cur.execute("SELECT id, name FROM notetypes")}
CORE, JLPT = "Japanese Vocabulary", "eggrolls-JLPT10k-v3.5"

note_word = {}
note_model = {}
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    p = flds.split(SEP)
    note_word[nid] = p[1].strip() if len(p) > 1 else ""
    note_model[nid] = ntname[mid]

card_note = {}
for cid, nid in cur.execute("SELECT id, nid FROM cards"):
    card_note[cid] = nid

first_ts = dict(cur.execute("SELECT cid, MIN(id) FROM revlog GROUP BY cid"))
word_first = collections.defaultdict(dict)
for cid, ts in first_ts.items():
    nid = card_note.get(cid)
    if nid is None:
        continue
    m = note_model.get(nid, "")
    w = note_word.get(nid, "")
    if w and m in (CORE, JLPT):
        word_first[w][m] = min(word_first[w].get(m, 1e18), ts)
first_ts_int = {cid: ts for cid, ts in first_ts.items()}

# 只保留"两套表里都有这个词"的词，排除"不在另一套表里=更难"的混淆
both = {w for w in word_first if CORE in word_first[w] and JLPT in word_first[w]}
print(f"两套表都有、且至少一套已学的词: {len(both)}")

print("\n=== 严格对照：只统计两套表都收录的词 ===")
agg = collections.defaultdict(lambda: [0, 0])
for cid, ease, type_, ts in cur.execute("SELECT cid, ease, type, id FROM revlog"):
    if type_ != 1:
        continue
    nid = card_note.get(cid)
    if nid is None:
        continue
    m = note_model.get(nid, "")
    w = note_word.get(nid, "")
    if m not in (CORE, JLPT) or w not in both:
        continue
    other = JLPT if m == CORE else CORE
    ots = word_first[w].get(other)
    if ots is None or ots > ts:
        grp = "另一方向尚未学"
    else:
        grp = "另一方向已先学"
    k = (m, grp)
    agg[k][0] += 1
    if ease == 1:
        agg[k][1] += 1

for m in (CORE, JLPT):
    lbl = "听辨 core6000" if m == CORE else "见词回忆 考级"
    print(f"\n  {lbl}")
    base = None
    for g in ("另一方向尚未学", "另一方向已先学"):
        c, f = agg.get((m, g), [0, 0])
        if c:
            rate = 100 * f / c
            print(f"    {g:<12} 复习 {c:>5} 次   忘记率 {rate:>5.1f}%")
            if g == "另一方向尚未学":
                base = rate
            elif base:
                print(f"      -> 先学过另一方向，忘记率相对下降 {100*(base-rate)/base:.0f}%")

print("\n=== 两套表之间的“进度落差” ===")
core_studied = {w for w in both if CORE in word_first[w] and JLPT not in word_first[w]}
jlpt_studied = {w for w in both if JLPT in word_first[w] and CORE not in word_first[w]}
du = {w for w in both if CORE in word_first[w] and JLPT in word_first[w]}
print(f"  两个方向都学过:        {len(du)}")
print(f"  只学过听辨，等见词回忆: {len(core_studied)}")
print(f"  只学过见词回忆，等听辨: {len(jlpt_studied)}")

gaps = sorted(abs(word_first[w][CORE] - word_first[w][JLPT]) / 86400000 for w in du)
print(f"\n  已配对词的两方向间隔: 中位 {statistics.median(gaps):.0f} 天")

# gap vs retention (for pairs, on the later card)
print("\n=== 配对间隔 与 后学方向卡的忘记率 ===")
buckets = collections.defaultdict(lambda: [0, 0])
for cid, ease, type_, ts in cur.execute("SELECT cid, ease, type, id FROM revlog"):
    if type_ != 1:
        continue
    nid = card_note.get(cid)
    m = note_model.get(nid, "")
    w = note_word.get(nid, "")
    if w not in du or m not in (CORE, JLPT):
        continue
    other = JLPT if m == CORE else CORE
    if word_first[w][m] != first_ts_int.get(cid):
        continue
    gap = abs(word_first[w][CORE] - word_first[w][JLPT]) / 86400000
    lbl = "<=7天" if gap <= 7 else ("8-30天" if gap <= 30 else ">30天")
    buckets[lbl][0] += 1
    if ease == 1:
        buckets[lbl][1] += 1
for lbl in ("<=7天", "8-30天", ">30天"):
    c, f = buckets.get(lbl, [0, 0])
    if c:
        print(f"  {lbl:<8} 复习 {c:>5} 次   忘记率 {100*f/c:>5.1f}%")
con.close()
