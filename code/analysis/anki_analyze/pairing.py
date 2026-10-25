import os, sqlite3, collections
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

card_note = dict(cur.execute("SELECT id, nid FROM cards"))
note_studied = collections.defaultdict(bool)
for cid, nid, reps in cur.execute("SELECT id, nid, reps FROM cards"):
    if reps > 0:
        note_studied[nid] = True

core_list, jlpt_list = set(), set()
core_studied, jlpt_studied = set(), set()
core_band = {}
for nid, mid, flds, tags in cur.execute("SELECT id, mid, flds, tags FROM notes"):
    name = ntname[mid]
    p = flds.split(SEP)
    w = p[1].strip() if len(p) > 1 else ""
    if not w:
        continue
    st = note_studied.get(nid, False)
    if name == CORE:
        core_list.add(w)
        if st:
            core_studied.add(w)
        for t in tags.split():
            if t.startswith("jp-core::"):
                core_band[w] = t.split("::")[1]
    elif name == JLPT:
        jlpt_list.add(w)
        if st:
            jlpt_studied.add(w)

studied = core_studied | jlpt_studied
print(f"已学唯一词: {len(studied)}")
print(f"  core 表收录 {len(core_list)} / jlpt 表收录 {len(jlpt_list)} / 两表都收录 {len(core_list & jlpt_list)}")

print("\n=== 交叉表：已学的每一个词，两个方向的状态 ===")
both_studied = core_studied & jlpt_studied
core_only_lag = (core_studied & jlpt_list) - jlpt_studied      # 在 jlpt 表里，但还没学
core_only_never = core_studied - jlpt_list                     # jlpt 表根本没有这个词
jlpt_only_lag = (jlpt_studied & core_list) - core_studied      # 在 core 表里，但还没学
jlpt_only_never = jlpt_studied - core_list                     # core 表根本没有这个词
print(f"  两个方向都学过            {len(both_studied):>5}  ({100*len(both_studied)/len(studied):.0f}%)")
print(f"  听辨已做、见词回忆待做     {len(core_only_lag):>5}   <- 可配对，还没做")
print(f"  听辨已做、另一表没有此词   {len(core_only_never):>5}   <- 无法配对")
print(f"  见词回忆已做、听辨待做     {len(jlpt_only_lag):>5}   <- 可配对，还没做")
print(f"  见词回忆已做、另一表没此词 {len(jlpt_only_never):>5}   <- 无法配对")
tot_lag = len(core_only_lag) + len(jlpt_only_lag)
print(f"\n  >>> 可配对但还没配上的词: {tot_lag} 个")

print("\n=== 两套表的词频区间错位情况 ===")


def band_profile(words, label):
    c = collections.Counter(core_band.get(w, "不在core6000") for w in words)
    tot = sum(c.values())
    print(f"  {label} (n={tot})")
    for k in ["1k", "2k", "3k", "4k", "5k", "6k", "不在core6000"]:
        if c.get(k):
            print(f"     {k:<12} {c[k]:>5}  ({100*c[k]/tot:.0f}%)")


for did, name in [(None, None)]:
    pass
# 已学的 N2 高频 / N3 中频 词各自落在哪个 core 频段
bands = {}
for nid, mid, flds, tags in cur.execute("SELECT id, mid, flds, tags FROM notes"):
    if ntname[mid] != JLPT:
        continue
    p = flds.split(SEP)
    w = p[1].strip() if len(p) > 1 else ""
    for t in tags.split():
        if t.startswith("eggrolls-JLPT10k-v3.5::3-N3::N3中频"):
            bands.setdefault("N3中频", set()).add(w)
        elif t == "eggrolls-JLPT10k-v3.5::4-N2::N2高频":
            bands.setdefault("N2高频", set()).add(w)
for k, s in bands.items():
    band_profile(s & jlpt_studied, f"已学的 {k}")
band_profile(core_studied, "已学的 core6000 全部")
con.close()
