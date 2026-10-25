import os, re, sqlite3, collections, statistics
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
decks = {r[0]: r[1].replace(SEP, "::") for r in cur.execute("SELECT id, name FROM decks")}

dict_words = set()
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    if ntname[mid] in ("Japanese Vocabulary", "eggrolls-JLPT10k-v3.5"):
        p = flds.split(SEP)
        if len(p) > 1:
            dict_words.add(p[1].strip())


def deinflect(w):
    """return candidate dictionary forms"""
    c = set()
    if len(w) < 2:
        return c
    # adjective adverbial / past
    if w.endswith("く") or w.endswith("かった") or w.endswith("くて"):
        base = re.sub(r"(かった|くて|く)$", "", w)
        c.add(base + "い")
    # te / ta forms
    m = re.match(r"^(.*?)(って|て|った|た|んで|んだ|いて|いた|いで|いだ|して|した)$", w)
    if m:
        st = m.group(1)
        suf = m.group(2)
        for last in "うくぐすつぬむぶる":
            c.add(st + last)
        c.add(st + "る")
        c.add(st + "する")
    # negative / stem
    for suf in ("ます", "ません", "ました", "ない", "なかった", "れば", "よう", "たい", "ながら", "ず", "れる", "られる"):
        if w.endswith(suf) and len(w) > len(suf):
            st = w[: -len(suf)]
            for last in "うくぐすつぬむぶる":
                c.add(st + last)
            c.add(st + "る")
    # bare stem (e.g. 降り, 食べ)
    if w.endswith(("り", "き", "ぎ", "し", "ち", "に", "み", "び", "い")):
        st = w[:-1]
        for last in "うくぐすつぬむぶる":
            c.add(st + last)
    return {x for x in c if len(x) >= 2 and x != w}


mined = []
for did, name in decks.items():
    if name == "0-日本语学习::2-例句":
        for (flds,) in cur.execute(
            "SELECT n.flds FROM notes n JOIN cards c ON c.nid=n.id WHERE c.did=?", (did,)
        ):
            p = flds.split(SEP)
            mined.append((p[0].strip(), p[1] if len(p) > 1 else ""))
print(f"挖句卡 {len(mined)} 张\n")

print("=== A. 目标词是否辞书形 ===")
nonc = []
for w, s in mined:
    if w in dict_words:
        continue
    cands = deinflect(w) & dict_words
    if cands:
        nonc.append((w, sorted(cands)[:3]))
print(f"  目标词不在任何词表里、但能还原出词表内辞书形的: {len(nonc)} / {len(mined)}")
print(f"  即约 {100*len(nonc)/len(mined):.0f}% 的卡挖的是变形，而非辞书形")
print("  例：")
for w, c in nonc[:18]:
    print(f"    挖的是「{w}」 -> 辞书形应为 {c}")

print("\n=== B. 句长分布（Sentence 字段）===")
txt = [re.sub(r"<[^>]+>", "", s).strip() for w, s in mined]
L = [len(t) for t in txt]
print(f"  中位 {statistics.median(L):.0f} 字   平均 {statistics.mean(L):.0f} 字   最长 {max(L)} 字")
for lo, hi, lbl in ((0, 20, "<=20 字"), (20, 35, "21-35 字"), (35, 60, "36-60 字"), (60, 9999, ">60 字")):
    n = sum(1 for x in L if lo < x <= hi) if lo else sum(1 for x in L if x <= hi)
    print(f"    {lbl:<10} {n:>4}  ({100*n/len(L):.0f}%)")
print("  最长的 3 张：")
for t in sorted(txt, key=len, reverse=True)[:3]:
    print(f"    ({len(t)} 字) {t[:100]}")

print("\n=== C. 目标词与所在句子的关系 ===")
miss = 0
for w, s in mined:
    if w and w not in re.sub(r"<[^>]+>", "", s):
        miss += 1
print(f"  目标词在句中找不到原形的: {miss} 张（其余都是原样出现，说明是生词挖掘而非变形挖掘）")
con.close()
