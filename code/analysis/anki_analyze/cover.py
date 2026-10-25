import os, re, collections
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

HERE = os.path.dirname(os.path.abspath(__file__))
TDIR = os.path.join(HERE, "texts")


def load(fn):
    with open(os.path.join(HERE, fn), encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


known = load("known_words.txt")
mature = load("mature_words.txt")
allw = load("all_words.txt")
KANJI = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

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


MATCH = {}
for w in allw:
    for f in inflections(w):
        MATCH.setdefault(f, ("known" if w in known else "deck", w))
for f in FUNCTION:
    MATCH.setdefault(f, ("grammar", f))
MAXLEN = min(max(len(k) for k in MATCH), 10)

known_kanji = {c for w in known for c in w if KANJI.match(c)}
all_kanji = {c for w in allw for c in w if KANJI.match(c)}
KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fc]")


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
                hit = (MATCH[sub], L, sub)
                break
        if hit:
            (kind, base), L, sub = hit
            toks.append([kind, sub, base])
            i += L
        else:
            toks.append(["out", ch, ch])
            i += 1
    # merge consecutive unknowns into one OOV token
    merged = []
    for t in toks:
        if t[0] == "out" and merged and merged[-1][0] == "out":
            merged[-1][1] += t[1]
            merged[-1][2] += t[2]
        else:
            merged.append(t)
    # drop pure-symbol noise runs
    return [t for t in merged if len(t[1]) > 0 and t[1] not in ("ー", "っ", "ん")]


HIRA_ONLY = re.compile(r"^[\u3041-\u3096]+$")


def analyze(name, text, show=False):
    toks = tokenize(text)
    if show:
        print("   tokens:", " | ".join(f"{s}[{k[:2]}]" for k, s, b in toks[:70]))
    # a lone hiragana that is not in the dictionary is almost always a tokenisation
    # fragment (e.g. ご+ん+狐) rather than a standalone unknown word -> neutral
    content = [t for t in toks if t[0] != "grammar"
               and not (t[0] == "out" and len(t[1]) == 1 and HIRA_ONLY.match(t[1]))]
    c = collections.Counter(t[0] for t in content)
    tot = len(content)
    if not tot:
        return
    kc = sum(1 for ch in text if KANJI.match(ch))
    kk = sum(1 for ch in text if KANJI.match(ch) and ch in known_kanji)
    kka = sum(1 for ch in text if KANJI.match(ch) and ch in all_kanji)
    mt = sum(1 for t in content if t[0] == "known" and t[2] in mature)
    print(f"\n=== {name} ===")
    print(f"  chars={len(text)}  content-words={tot}  grammar-tokens={len(toks)-tot}")
    print(f"  word coverage:  known {100*c['known']/tot:.1f}%  (of which mature {100*mt/tot:.1f}%)"
          f"   in-deck-unstudied {100*c['deck']/tot:.1f}%   OOV {100*c['out']/tot:.1f}%")
    print(f"  kanji occurrence coverage: studied-words {100*kk/max(1,kc):.1f}%   "
          f"any-in-collection {100*kka/max(1,kc):.1f}%   kanji-occ={kc}")
    unk = collections.Counter(t[1] for t in content if t[0] == "out")
    print("  OOV sample:", "  ".join(f"{w}({n})" for w, n in unk.most_common(30)))


files = [f for f in sorted(os.listdir(TDIR)) if f.endswith(".txt")]
print("texts:", files)
first = True
for fn in files:
    with open(os.path.join(TDIR, fn), encoding="utf-8") as f:
        analyze(fn.replace(".txt", ""), f.read(), show=first)
    first = False
