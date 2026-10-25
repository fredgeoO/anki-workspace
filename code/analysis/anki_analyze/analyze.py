import os, sqlite3, json, collections, datetime, re
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "collection_snapshot.anki2")
con = sqlite3.connect(DB)
con.create_collation("unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
cur = con.cursor()
SEP = "\x1f"

decks = {r[0]: r[1].replace(SEP, "::") for r in cur.execute("SELECT id, name FROM decks")}
ntname = {r[0]: r[1] for r in cur.execute("SELECT id, name FROM notetypes")}
flds_of = collections.defaultdict(list)
for ntid, ord_, name in cur.execute("SELECT ntid, ord, name FROM fields ORDER BY ntid, ord"):
    flds_of[ntid].append((ord_, name))


def field_index(ntid, want):
    for ord_, name in flds_of[ntid]:
        if name == want:
            return ord_
    return None


WORD_OF = {
    "Japanese Vocabulary": "Word",
    "eggrolls-JLPT10k-v3.5": "VocabKanji",
    "どんなときどう使う日本語表現文型Note": "Card",
    "Basic": "Word",
}

card_by_note = collections.defaultdict(list)
for nid, did, type_, queue, ivl, reps, lapses, factor in cur.execute(
    "SELECT nid, did, type, queue, ivl, reps, lapses, factor FROM cards"
):
    card_by_note[nid].append((did, type_, queue, ivl, reps, lapses, factor))

notes = []
for nid, mid, tags, flds in cur.execute("SELECT id, mid, tags, flds FROM notes"):
    model = ntname[mid]
    parts = flds.split(SEP)
    wi = field_index(mid, WORD_OF.get(model, "Word"))
    word = parts[wi].strip() if wi is not None and wi < len(parts) else ""
    cs = card_by_note.get(nid, [])
    studied = any(c[4] > 0 for c in cs)
    mature = any(c[1] == 2 and c[3] >= 21 for c in cs)
    maxivl = max((c[3] for c in cs), default=0)
    lapses = max((c[5] for c in cs), default=0)
    factor = min((c[6] for c in cs if c[4] > 0), default=0)
    did = cs[0][0] if cs else 0
    notes.append(dict(nid=nid, model=model, word=word, tags=tags.split(), did=did,
                      studied=studied, mature=mature, maxivl=maxivl, lapses=lapses, factor=factor))

print("total notes:", len(notes))

# ---------- vocabulary ----------
vocab = [n for n in notes if n["model"] in ("Japanese Vocabulary", "eggrolls-JLPT10k-v3.5")]
allw = {n["word"] for n in vocab if n["word"]}
known = {n["word"] for n in vocab if n["word"] and n["studied"]}
mature = {n["word"] for n in vocab if n["word"] and n["mature"]}
print(f"\n=== VOCAB ===\n  cards in collection: {len(vocab)}")
print(f"  unique words: {len(allw)}   studied: {len(known)}   mature(>=21d): {len(mature)}")

# JLPT bands via tags
band_of = {}
for n in vocab:
    for t in n["tags"]:
        if t.startswith("eggrolls-JLPT10k-v3.5::1-N5") or t == "eggrolls-JLPT10k-v3.5::1-N5":
            band_of[n["word"]] = "N5"
        elif t == "eggrolls-JLPT10k-v3.5::2-N4":
            band_of[n["word"]] = "N4"
        elif t == "eggrolls-JLPT10k-v3.5::3-N3::N3高频":
            band_of[n["word"]] = "N3-高频"
        elif t == "eggrolls-JLPT10k-v3.5::3-N3::N3中频":
            band_of[n["word"]] = "N3-中频"
        elif t == "eggrolls-JLPT10k-v3.5::3-N3::N3低频":
            band_of[n["word"]] = "N3-低频"
        elif t == "eggrolls-JLPT10k-v3.5::4-N2::N2高频":
            band_of[n["word"]] = "N2-高频"
        elif t == "eggrolls-JLPT10k-v3.5::4-N2::N2中频":
            band_of[n["word"]] = "N2-中频"
        elif t == "eggrolls-JLPT10k-v3.5::4-N2::N2低频":
            band_of[n["word"]] = "N2-低频"
        elif t == "eggrolls-JLPT10k-v3.5::5-N1::N1高频":
            band_of[n["word"]] = "N1-高频"
        elif t == "eggrolls-JLPT10k-v3.5::5-N1::N1中频":
            band_of[n["word"]] = "N1-中频"
        elif t == "eggrolls-JLPT10k-v3.5::5-N1::N1低频":
            band_of[n["word"]] = "N1-低频"

print("\n=== JLPT band coverage (unique words) ===")
bandwords = collections.defaultdict(set)
for w, b in band_of.items():
    bandwords[b].add(w)
order = ["N5", "N4", "N3-高频", "N3-中频", "N3-低频", "N2-高频", "N2-中频", "N2-低频", "N1-高频", "N1-中频", "N1-低频"]
print(f"  {'band':<10} {'total':>6} {'studied':>8} {'mature':>7} {'done%':>7}")
for b in order:
    ws = bandwords[b]
    s = len(ws & known)
    m = len(ws & mature)
    print(f"  {b:<10} {len(ws):>6} {s:>8} {m:>7} {100*s/max(1,len(ws)):>6.1f}%")

# jp-core bands
print("\n=== jp-core (frequency 1k-6k) coverage ===")
core = collections.defaultdict(set)
for n in vocab:
    for t in n["tags"]:
        m = re.match(r"jp-core::(\d)k$", t)
        if m:
            core[m.group(1)].add(n["word"])
for k in sorted(core):
    ws = core[k]
    print(f"  core::{k}k  total={len(ws):>5} studied={len(ws & known):>5} mature={len(ws & mature):>5}")

# overlap jp-core vs JLPT
jlpt_all = set().union(*bandwords.values())
core_all = set().union(*core.values())
print(f"\n  JLPT list unique: {len(jlpt_all)}   jp-core unique: {len(core_all)}")
print(f"  overlap (in both): {len(jlpt_all & core_all)}")
print(f"  studied that are NOT in JLPT list: {len(known - jlpt_all)}")
print(f"  studied that ARE in JLPT list: {len(known & jlpt_all)}")

# interval / stability
print("\n=== mastery depth (studied vocab) ===")
for lo, hi, lbl in [(1, 6, "<7d"), (7, 20, "7-20d"), (21, 89, "21-89d"), (90, 179, "90-179d"),
                    (180, 364, "180-364d"), (365, 99999, ">=365d")]:
    c = sum(1 for n in vocab if n["studied"] and lo <= n["maxivl"] <= hi)
    print(f"  {lbl:<10} {c:>5}")

# ---------- grammar ----------
print("\n=== GRAMMAR (表現文型) ===")
gram = [n for n in notes if n["model"] == "どんなときどう使う日本語表現文型Note"]
points = collections.defaultdict(lambda: [0, 0, 0])  # total, studied, mature
for n in gram:
    lv = "?"
    for t in n["tags"]:
        if t.startswith("日本語表現文型::N"):
            lv = t.split("::")[1]
    points[lv][0] += 1
    if n["studied"]:
        points[lv][1] += 1
    if n["mature"]:
        points[lv][2] += 1
tot = [0, 0, 0]
for lv in ["N5", "N4", "N3", "N2", "N1", "?"]:
    if lv in points:
        a = points[lv]
        print(f"  {lv:<4} points={a[0]:>4} studied={a[1]:>4} mature={a[2]:>4}  ({100*a[1]/max(1,a[0]):.0f}%)")
        tot = [tot[i] + a[i] for i in range(3)]
print(f"  ALL  points={tot[0]:>4} studied={tot[1]:>4} mature={tot[2]:>4}  ({100*tot[1]/max(1,tot[0]):.0f}%)")

# ---------- example-sentence deck / immersion ----------
print("\n=== immersion deck (2-例句) tags ===")
sent = [n for n in notes if decks.get(n["did"], "").endswith("2-例句")]
tg = collections.Counter()
for n in sent:
    for t in n["tags"]:
        tg[t.split("::")[0]] += 1
for t, c in tg.most_common():
    print(f"  {t}: {c}   (studied {sum(1 for n in sent if t in '::'.join(n['tags']) and n['studied'])})")

# ---------- revlog ----------
print("\n=== REVIEW LOG ===")
rl = list(cur.execute("SELECT id, cid, ease, ivl, lastIvl, factor, time, type FROM revlog"))
print("  entries:", len(rl))
DAY = 86400000
first = min(r[0] for r in rl)
last = max(r[0] for r in rl)
print("  first:", datetime.datetime.fromtimestamp(first / 1000).date(),
      " last:", datetime.datetime.fromtimestamp(last / 1000).date())
days = (last - first) / DAY
print(f"  span: {days:.0f} days")
tot_ms = sum(r[6] for r in rl)
print(f"  total time: {tot_ms/3600000:.1f} h   avg/day: {tot_ms/3600000/max(1,days):.1f} h")

bym = collections.defaultdict(lambda: [0, 0])
for r in rl:
    d = datetime.datetime.fromtimestamp(r[0] / 1000)
    key = f"{d.year}-{d.month:02d}"
    if r[7] == 1:
        bym[key][0] += 1
        if r[2] == 1:
            bym[key][1] += 1
print("\n  month    review-reps  again%")
for k in sorted(bym):
    c, f = bym[k]
    print(f"  {k}   {c:>8}   {100*f/max(1,c):>5.1f}%")

# first exposure success
firstrev = {}
for r in rl:
    if r[1] not in firstrev or r[0] < firstrev[r[1]][0]:
        firstrev[r[1]] = (r[0], r[2])
fa = sum(1 for v in firstrev.values() if v[1] == 1)
print(f"\n  cards ever reviewed: {len(firstrev)}  first-exposure 'again': {fa} ({100*fa/max(1,len(firstrev)):.1f}%)")

# lapses / leeches
lap = collections.Counter()
for n in notes:
    if n["studied"]:
        lap[min(n["lapses"], 20)] += 1
print("\n  lapses distribution (max per note, studied notes):")
for k in sorted(lap):
    if k >= 4 or k == 0:
        print(f"    {k}{'+' if k == 20 else ''} lapses: {lap[k]}")
leeches = [n for n in notes if "leech" in n["tags"] or n["lapses"] >= 8]
print(f"  cards with lapses>=8 or leech tag: {len(leeches)}")
worst = sorted([n for n in notes if n["studied"]], key=lambda n: -n["lapses"])[:25]
print("\n  worst cards:")
for n in worst:
    if n["lapses"] > 0:
        print(f"    {n['lapses']:>3} lapses  {n['word'][:22]:<24} {decks.get(n['did'],'')[-28:]}")

con.close()

for fn, s in (("known_words.txt", known), ("mature_words.txt", mature), ("all_words.txt", allw)):
    with open(os.path.join(HERE, fn), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(s)))
print("\nwrote word lists")
