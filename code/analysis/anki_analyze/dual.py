import os, re, sqlite3, sys, collections, datetime, statistics, json

HERE = os.path.dirname(os.path.abspath(__file__))
# code/common（jp_decks.py：牌组常量 + 标签→级别/频段；考级词汇已扁平化）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "common"))
import jp_decks as JD  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

con = sqlite3.connect(os.path.join(HERE, "collection_snapshot.anki2"))
con.create_collation("unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
cur = con.cursor()
SEP = "\x1f"
decks = {r[0]: r[1].replace(SEP, "::") for r in cur.execute("SELECT id, name FROM decks")}
ntname = {r[0]: r[1] for r in cur.execute("SELECT id, name FROM notetypes")}
card_deck = {r[0]: r[1] for r in cur.execute("SELECT id, did FROM cards")}

CORE = "Japanese Vocabulary"
JLPT = "eggrolls-JLPT10k-v3.5"

# ---- 1. audio field population ----
print("=== 1. 音频字段是否真的填上了（决定“听辨”是否成立）===")
stats = collections.defaultdict(lambda: [0, 0, 0])
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    name = ntname[mid]
    p = flds.split(SEP)
    if name == CORE and len(p) > 10:
        w_audio, s_audio = p[9].strip(), p[10].strip()
        stats["core6000"][0] += 1
        if w_audio:
            stats["core6000"][1] += 1
        if s_audio:
            stats["core6000"][2] += 1
    elif name == JLPT and len(p) > 14:
        w_audio = p[8].strip()
        s_audio = p[14].strip()
        stats["考级词汇"][0] += 1
        if w_audio:
            stats["考级词汇"][1] += 1
        if s_audio:
            stats["考级词汇"][2] += 1
for k, v in stats.items():
    print(f"  {k:<10} 笔记 {v[0]:>6}  有单词音频 {v[1]:>6} ({100*v[1]/v[0]:.0f}%)  "
          f"有例句音频 {v[2]:>6} ({100*v[2]/v[0]:.0f}%)")

# ---- gather cards ----
card_info = {}
for cid, nid, did, type_, queue, ivl, reps, lapses in cur.execute(
    "SELECT id, nid, did, type, queue, ivl, reps, lapses FROM cards"
):
    card_info[cid] = dict(nid=nid, did=did, type=type_, queue=queue, ivl=ivl, reps=reps, lapses=lapses)

note_word = {}
note_model = {}
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    p = flds.split(SEP)
    note_word[nid] = p[1].strip() if len(p) > 1 else ""
    note_model[nid] = ntname[mid]

first_ts = {}
for cid, ts in cur.execute("SELECT cid, MIN(id) FROM revlog GROUP BY cid"):
    first_ts[cid] = ts

# word -> {model: first_ts}
word_first = collections.defaultdict(dict)
word_cid = collections.defaultdict(dict)
for cid, info in card_info.items():
    w = note_word.get(info["nid"], "")
    m = note_model.get(info["nid"], "")
    if not w or cid not in first_ts:
        continue
    if m in (CORE, JLPT):
        word_first[w][m] = min(word_first[w].get(m, 1e18), first_ts[cid])
        word_cid[w][m] = cid

dual = [w for w in word_first if CORE in word_first[w] and JLPT in word_first[w]]
print(f"\n  两套都学过的词: {len(dual)}")
only_core = [w for w in word_first if CORE in word_first[w] and JLPT not in word_first[w]]
only_jlpt = [w for w in word_first if JLPT in word_first[w] and CORE not in word_first[w]]
print(f"  只做过听辨(core)，还没做见词回忆: {len(only_core)}")
print(f"  只做过见词回忆(考级)，还没做听辨: {len(only_jlpt)}")

# ---- 2. gap between the two directions ----
gaps = []
for w in dual:
    a, b = word_first[w][CORE], word_first[w][JLPT]
    gaps.append(abs(a - b) / 86400000)
if gaps:
    gaps.sort()
    print(f"\n=== 2. 同一个词两个方向的学习间隔（天）===")
    print(f"  中位 {statistics.median(gaps):.0f} 天   均值 {statistics.mean(gaps):.0f} 天")
    for lo, hi, lbl in ((0, 1, "同一天"), (1, 7, "1-7 天"), (7, 30, "8-30 天"),
                        (30, 90, "31-90 天"), (90, 99999, ">90 天")):
        n = sum(1 for g in gaps if lo <= g < hi)
        print(f"    {lbl:<10} {n:>5}  ({100*n/len(gaps):.0f}%)")

# ---- 3. cross-direction reinforcement effect ----
print("\n=== 3. 先做过另一方向的词，忘记率会不会更低？===")
rev = collections.defaultdict(lambda: [0, 0])


def bucket(cid_of_card, other_ts, ts):
    if other_ts is None:
        return "另一方向未学"
    if other_ts < ts:
        return "另一方向已先学"
    return "另一方向后学"


for cid, nid, ease, type_, ts in cur.execute("SELECT cid, 0, ease, type, id FROM revlog"):
    if type_ != 1:
        continue
    info = card_info.get(cid)
    if not info:
        continue
    w = note_word.get(info["nid"], "")
    m = note_model.get(info["nid"], "")
    if m not in (CORE, JLPT):
        continue
    other = JLPT if m == CORE else CORE
    ots = word_first.get(w, {}).get(other)
    b = bucket(cid, ots, ts)
    key = (m, b)
    rev[key][0] += 1
    if ease == 1:
        rev[key][1] += 1

for m in (CORE, JLPT):
    label = "听辨(core6000)" if m == CORE else "见词回忆(考级)"
    print(f"  {label}")
    for b in ("另一方向已先学", "另一方向后学", "另一方向未学"):
        c, f = rev.get((m, b), [0, 0])
        if c:
            print(f"    {b:<14} 复习 {c:>5} 次   忘记率 {100*f/c:>5.1f}%")

# ---- 4. where the two decks currently sit ----
print("\n=== 4. 两套表当前进度是否对齐 ===")
core_band = collections.defaultdict(set)
for nid, flds, tags in cur.execute("SELECT id, flds, tags FROM notes"):
    p = flds.split(SEP)
    w = p[1].strip() if len(p) > 1 else ""
    for t in tags.split():
        if t.startswith("jp-core::"):
            core_band[t.split("::")[1]].add(w)
studied_words = {w for w in word_first}
for k in sorted(core_band):
    s = core_band[k] & studied_words
    print(f"  {k}: 已学 {len(s):>4}/{len(core_band[k]):>4}")
# which N2-highfreq words already have listening done
# ⚠ 考级词汇已扁平化：N2 高频不再是子 deck，而是 eggrolls 标签
#   `eggrolls-JLPT10k-v3.5::4-N2::N2高频`（见 code/common/jp_decks.py）。
n2hf = set()
n2hf_tag = JD.level_tag('N2', '高频')
for flds, tags in cur.execute("SELECT flds, tags FROM notes"):
    if n2hf_tag not in (tags or "").split():
        continue
    p = flds.split(SEP)
    if len(p) > 1:
        n2hf.add(p[1].strip())
studied_n2 = {w for w in n2hf if w in word_first}
with_core = {w for w in studied_n2 if CORE in word_first.get(w, {})}
print(f"\n  你已学的 N2 高频词 {len(studied_n2)} 个，其中做过听辨的只有 {len(with_core)} 个 "
      f"({100*len(with_core)/max(1,len(studied_n2)):.0f}%)")
con.close()
