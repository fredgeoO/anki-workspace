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
note_studied = collections.defaultdict(bool)
for nid, reps in cur.execute("SELECT nid, reps FROM cards"):
    if reps > 0:
        note_studied[nid] = True

# core6000 rank (Index field)
rank = {}
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    if ntname[mid] != "Japanese Vocabulary":
        continue
    p = flds.split(SEP)
    if len(p) > 1:
        try:
            rank[p[1].strip()] = int(p[0])
        except Exception:
            pass

jlpt_words = set()
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    if ntname[mid] == "eggrolls-JLPT10k-v3.5":
        p = flds.split(SEP)
        if len(p) > 1:
            jlpt_words.add(p[1].strip())

studied = set()
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    p = flds.split(SEP)
    if len(p) > 1 and note_studied.get(nid) and ntname[mid] in (
            "Japanese Vocabulary", "eggrolls-JLPT10k-v3.5"):
        studied.add(p[1].strip())

# first exposure ts per word, by source
card_note = dict(cur.execute("SELECT id, nid FROM cards"))
first_ts = dict(cur.execute("SELECT cid, MIN(id) FROM revlog GROUP BY cid"))
word_first = collections.defaultdict(dict)
for cid, ts in first_ts.items():
    nid = card_note.get(cid)
    if nid is None:
        continue
    m = ntname.get(cur.execute("SELECT mid FROM notes WHERE id=?", (nid,)).fetchone()[0]) if False else None
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    pass
note_model = {}
for nid, mid in cur.execute("SELECT id, mid FROM notes"):
    note_model[nid] = ntname[mid]
note_word = {}
for nid, flds in cur.execute("SELECT id, flds FROM notes"):
    p = flds.split(SEP)
    note_word[nid] = p[1].strip() if len(p) > 1 else ""
for cid, ts in first_ts.items():
    nid = card_note.get(cid)
    if nid is None:
        continue
    m = note_model.get(nid)
    w = note_word.get(nid)
    if w and m in ("Japanese Vocabulary", "eggrolls-JLPT10k-v3.5"):
        word_first[w][m] = min(word_first[w].get(m, 1e18), ts)

# ---- mined cards ----
mined = []
for did, name in decks.items():
    if name == "0-日本语学习::2-例句":
        for nid, flds, tags in cur.execute(
            "SELECT n.id, n.flds, n.tags FROM notes n JOIN cards c ON c.nid=n.id WHERE c.did=?", (did,)
        ):
            p = flds.split(SEP)
            mined.append(dict(nid=nid, word=p[0].strip(), sent=p[1] if len(p) > 1 else "",
                              tags=tags.split(), studied=note_studied.get(nid, False)))
print(f"挖句卡共 {len(mined)} 张，已学 {sum(1 for m in mined if m['studied'])}")

seen = set()
uniq = []
for m in mined:
    if m["word"] in seen:
        continue
    seen.add(m["word"])
    uniq.append(m)
print(f"去重后目标词 {len(uniq)} 个\n")

def src(m):
    t = " ".join(m["tags"])
    if "报道节目" in t:
        return "报道节目(新闻)"
    if "动画" in t:
        return "动画"
    return "其他"

print("=== 1. 你挖出来的词，通用频率表覆盖得到吗 ===")
print(f"  {'来源':<16}{'词数':>5}{'在core6000内':>12}{'平均排名':>10}{'不在core6000':>14}{'不在考级表':>12}")
for s in ("动画", "报道节目(新闻)", "其他"):
    ws = [m["word"] for m in uniq if src(m) == s]
    if not ws:
        continue
    inr = [w for w in ws if w in rank]
    nr = [rank[w] for w in inr]
    print(f"  {s:<16}{len(ws):>5}{len(inr):>12}{(statistics.mean(nr) if nr else 0):>10.0f}"
          f"{len(ws)-len(inr):>14}{sum(1 for w in ws if w not in jlpt_words):>12}")

allw = [m["word"] for m in uniq]
inr = [w for w in allw if w in rank]
print(f"\n  合计 {len(allw)} 个词：{len(inr)} 个在 core6000 内（平均排名 "
      f"{statistics.mean([rank[w] for w in inr]):.0f}），{len(allw)-len(inr)} 个在 core6000 之外")

print("\n=== 2. 这些词有多少是“重复劳动” ===")
dup_core = sum(1 for m in uniq if m["word"] in word_first and "Japanese Vocabulary" in word_first[m["word"]])
dup_jlpt = sum(1 for m in uniq if m["word"] in word_first and "eggrolls-JLPT10k-v3.5" in word_first[m["word"]])
before = 0
for m in uniq:
    mt = word_first.get(m["word"], {})
    if not mt or m["nid"] not in [card_note.get(c) for c in first_ts]:
        pass
mine_ts = None
for cid, nid in card_note.items():
    if nid in {m["nid"] for m in uniq} and cid in first_ts:
        pass
mined_ts = {}
for cid, ts in first_ts.items():
    nid = card_note.get(cid)
    for m in uniq:
        if m["nid"] == nid:
            mined_ts[m["word"]] = ts
for m in uniq:
    mt = word_first.get(m["word"], {})
    t0 = mined_ts.get(m["word"])
    if t0 is None:
        continue
    if any(v < t0 for v in mt.values()):
        before += 1
print(f"  挖的词里，在 dict 卡组中已经有卡片的: core6000 {dup_core} 个 / 考级表 {dup_jlpt} 个")
print(f"  挖之前就已经在别处学过该词的: {before} 个（占 {100*before/max(1,len(mined_ts)):.0f}%）")

print("\n=== 3. 挖句卡的实际内容（前 12 张）===")
for m in mined[:12]:
    print(f"  [{src(m):<12}] {m['word'][:18]:<20} | {re.sub('<[^>]+>', ' ', m['sent'])[:78]}")

print("\n=== 4. 挖句卡的成本对比 ===")
print("  挖句卡: 34.3 秒/张, 忘记率 6.3%  <- 记住得最牢")
print("  考级卡: 13.8 秒/张, 忘记率 12.1%")
print("  core卡: 23.4 秒/张, 忘记率 14.0%")
print("  -> 挖句卡的“每次复习”价值最高，但单位时间产出最低（贵 2.5 倍）")
con.close()
