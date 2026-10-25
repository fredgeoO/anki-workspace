import os, re, sqlite3, collections
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(os.path.join(HERE, "collection_snapshot.anki2"))
con.create_collation("unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
cur = con.cursor()

# ---- word -> tier membership ----
core = collections.defaultdict(set)
studied, mature = set(), set()
for flds, tags in cur.execute(
    "SELECT n.flds, n.tags FROM notes n WHERE n.mid IN "
    "(SELECT id FROM notetypes WHERE name IN ('Japanese Vocabulary','eggrolls-JLPT10k-v3.5'))"
):
    parts = flds.split("\x1f")
    w = parts[1].strip() if len(parts) > 1 else ""
    if not w:
        continue
    for t in tags.split():
        m = re.match(r"jp-core::(\d)k$", t)
        if m:
            core[int(m.group(1))].add(w)

card_by_note = collections.defaultdict(list)
for nid, type_, ivl, reps in cur.execute("SELECT nid, type, ivl, reps FROM cards"):
    card_by_note[nid].append((type_, ivl, reps))

for nid, flds, tags in cur.execute(
    "SELECT n.id, n.flds, n.tags FROM notes n WHERE n.mid IN "
    "(SELECT id FROM notetypes WHERE name IN ('Japanese Vocabulary','eggrolls-JLPT10k-v3.5'))"
):
    parts = flds.split("\x1f")
    w = parts[1].strip() if len(parts) > 1 else ""
    if not w:
        continue
    cs = card_by_note.get(nid, [])
    if any(c[2] > 0 for c in cs):
        studied.add(w)
    if any(c[0] == 2 and c[1] >= 21 for c in cs):
        mature.add(w)
con.close()

allw = set().union(*core.values())
print("core bands:", {k: len(v) for k, v in sorted(core.items())}, "all core:", len(allw))

TIERS = [
    ("实际已学 (studied)", studied),
    ("core 1k", core[1]),
    ("core 1-2k", core[1] | core[2]),
    ("core 1-3k", set().union(*[core[i] for i in (1, 2, 3)])),
    ("core 1-4k", set().union(*[core[i] for i in (1, 2, 3, 4)])),
    ("core 1-5k", set().union(*[core[i] for i in (1, 2, 3, 4, 5)])),
    ("core 1-6k (全核心)", allw),
]

KANJI = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fc]")
HIRA_ONLY = re.compile(r"^[\u3041-\u3096]+$")
FUNCTION = set("""
の は が を に へ と で も や か ね よ な ぞ ぜ さ わ ん っ ー ば し て た だ です ます でし でしょ
から まで より だけ しか ほど など なんか くらい ぐらい ばかり こそ さえ でも ながら つつ たり だり
ました ません ませんでした でしょう だろう う よう みたい らしい そう べき はず
ない なかった ぬ ず れる られる せる させる たい たく たかった
こと もの ため ところ わけ つもり まま ほう とおり ばあい 場合 うち
そして しかし だから けれど けど ので のに つまり また まだ もう
これ それ あれ どれ ここ そこ あそこ どこ この その あの どの こんな そんな あんな どんな
いる いた います いて いない ある あり する した して します しない すれば しよう される させる
""".split())


def inflections(w):
    forms = {w}
    if len(w) < 2:
        return forms
    last, stem = w[-1], w[:-1]
    godan = {
        "う": ("わ", "い", "え", "お", "って", "った"), "く": ("か", "き", "け", "こ", "いて", "いた"),
        "ぐ": ("が", "ぎ", "げ", "ご", "いで", "いだ"), "す": ("さ", "し", "せ", "そ", "して", "した"),
        "つ": ("た", "ち", "て", "と", "って", "った"), "ぬ": ("な", "に", "ね", "の", "んで", "んだ"),
        "む": ("ま", "み", "め", "も", "んで", "んだ"), "ぶ": ("ば", "び", "べ", "ぼ", "んで", "んだ"),
        "る": ("ら", "り", "れ", "ろ", "って", "った"),
    }
    if last in godan:
        a, i_, e_, o_, te, ta = godan[last]
        A, I, E, O = stem + a, stem + i_, stem + e_, stem + o_
        forms |= {I + "ます", I + "ません", I + "ました", I + "ませんでした", I + "たい", I + "ながら",
                  I + "すぎる", I + "そう", A + "ない", A + "なかった", A + "ず", A + "れる", A + "せる",
                  E + "ば", E + "る", O + "う", stem + te, stem + te + "いる", stem + te + "います",
                  stem + te + "ください", stem + ta, stem + ta + "ら"}
        if last == "る":
            forms |= {stem + "ます", stem + "ません", stem + "ました", stem + "て", stem + "た",
                      stem + "ない", stem + "なかった", stem + "れば", stem + "よう",
                      stem + "られる", stem + "させる", stem + "たい", stem + "ろ"}
    if last == "い" and len(w) >= 3:
        st = w[:-1]
        forms |= {st + "く", st + "かった", st + "くない", st + "くなかった", st + "ければ",
                  st + "くて", st + "さ", st + "そう"}
    if w.endswith("する"):
        st = w[:-2]
        forms |= {st + x for x in ("します", "した", "して", "しない", "しなかった", "すれば",
                                   "しよう", "される", "させる", "したい", "している", "しています")}
    if w.endswith("来る"):
        st = w[:-2]
        forms |= {st + x for x in ("来ます", "来た", "来て", "来ない", "来れば", "来よう")}
    return forms


print("building map ...")
MATCH = {}
for w in allw:
    for f in inflections(w):
        MATCH.setdefault(f, w)
for f in FUNCTION:
    MATCH.setdefault(f, None)          # None = grammar
MAXLEN = min(max(len(k) for k in MATCH), 10)


def tokenize(text):
    toks, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if not (KANJI.match(ch) or KANA_RE.match(ch)):
            i += 1
            continue
        hit = None
        for L in range(min(MAXLEN, n - i), 0, -1):
            sub = text[i:i + L]
            if sub in MATCH:
                hit = (MATCH[sub], L)
                break
        if hit:
            base, L = hit
            toks.append([base if base is not None else "G", text[i:i + L]])
            i += L
        else:
            toks.append(["OOV", ch])
            i += 1
    merged = []
    for t in toks:
        if t[0] == "OOV" and merged and merged[-1][0] == "OOV":
            merged[-1][1] += t[1]
        else:
            merged.append(t)
    return [t for t in merged if t[0] != "G"
            and not (t[0] == "OOV" and len(t[1]) == 1 and HIRA_ONLY.match(t[1]))]


TDIR = os.path.join(HERE, "texts")
tok_cache = {}
for fn in sorted(os.listdir(TDIR)):
    if fn.endswith(".txt"):
        with open(os.path.join(TDIR, fn), encoding="utf-8") as f:
            tok_cache[fn.replace(".txt", "")] = tokenize(f.read())

names = list(tok_cache)
print("\n=== coverage curve: % of content words understood ===")
hdr = "  " + f"{'tier':<22}" + "".join(f"{n[:16]:>18}" for n in names) + f"{'words':>8}"
print(hdr)
for label, tier in TIERS:
    row = f"  {label:<22}"
    for n in names:
        toks = tok_cache[n]
        tot = len(toks)
        ok = sum(1 for b, s in toks if b in tier)
        row += f"{100*ok/max(1,tot):>17.1f}%"
    print(row + f"{len(tier):>8}")
print(f"\n  (mature-only actual knowledge = {len(mature)} words)")
