"""Analyze Anki revlog: per-deck review volume and real time-per-card.

Reads a *copy* of collection.anki2 (+ WAL/SHM) so the live collection is untouched.

⚠ 考级词汇已扁平化：原先 11 个按级别/频段切分的子 deck 合并成「2-考级词汇」一层，
  级别与频段改由 eggrolls 笔记标签区分（见 code/common/jp_decks.py）。所以本脚本
  的分区判定从「只看 deck 名」改成「deck 名 + 笔记标签」，扁平化前后的快照都能跑。
"""
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import jp_decks as JD  # noqa: E402
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

SRC = Path(WSP.ANKI_PROFILE)
TMP = Path(WSP.SNAPSHOTS) / "ankisnap"
TMP.mkdir(exist_ok=True)

for suffix in ("", "-wal", "-shm"):
    s = Path(str(SRC / "collection.anki2") + suffix)
    if s.exists():
        shutil.copy2(s, Path(str(TMP / "c.anki2") + suffix))

db = sqlite3.connect(str(TMP / "c.anki2"))
db.row_factory = sqlite3.Row

db.create_collation("unicase", lambda a, b: (a > b) - (a < b))
decks = {r["id"]: r["name"].replace("\x1f", "::")
         for r in db.execute("select id, name from decks")}
models = {r["id"]: r["name"] for r in db.execute("select id, name from notetypes")}

# 考级词汇的分支：笔记 id -> 分支名。全在同一个 deck 里，只能靠 eggrolls 标签分。
KAOKYU_NOTE_BRANCH = {}
for r in db.execute("select id, tags from notes"):
    tags = (r["tags"] or "").split()
    lv = JD.level_from_tags(tags)
    if not lv:
        continue
    band = JD.band_from_tags(tags)
    KAOKYU_NOTE_BRANCH[r["id"]] = "考级词汇-%s" % (
        band if band else lv)          # N5 / N4；高频 / 中频 / 低频

# 输出顺序（也是分区名的白名单）
BRANCHES = [
    "Core6000-听辨",
    "考级词汇-N5", "考级词汇-N4",
    "考级词汇-高频", "考级词汇-中频", "考级词汇-低频",
    "语法-解释", "语法-例句",
    "对白例句",
]

NOW_MS = int(time.time() * 1000)
DAY30 = NOW_MS - 30 * 86400_000
DAY7 = NOW_MS - 7 * 86400_000


def branch_of(name: str, nid=None) -> str:
    if name.startswith(JD.DECK_GRAMMAR):
        return "语法-解释" if name.endswith("-解释") else "语法-例句"
    if name == JD.DECK_CORE6000 or name.startswith(JD.DECK_CORE6000 + "::"):
        return "Core6000-听辨"
    if name == JD.DECK_KAOKYU or name.startswith(JD.DECK_KAOKYU + "::"):
        # 扁平化前：子 deck 名就带 {高,中,低}频；扁平化后：靠笔记标签。
        # 两条路都留着，于是旧快照也能复现原来的分区。
        for band in JD.BANDS:
            if band in name:
                return "考级词汇-%s" % band
        return KAOKYU_NOTE_BRANCH.get(nid, "考级词汇-其他")
    if name == JD.DECK_EXAMPLE or name.startswith(JD.DECK_EXAMPLE + "::"):
        return "对白例句"
    return "其他"


def analyze(cutoff_ms: int):
    rows = db.execute(
        "select r.id, r.ease, r.type, r.time, r.ivl, c.did, c.nid "
        "from revlog r join cards c on c.id = r.cid where r.id > ?",
        (cutoff_ms,)).fetchall()
    agg = defaultdict(lambda: {"n": 0, "ms": 0, "by_type": defaultdict(int),
                               "cards": set(), "again": 0})
    for r in rows:
        label = branch_of(decks.get(r["did"], "?"), r["nid"])
        a = agg[label]
        a["n"] += 1
        a["ms"] += r["time"]
        a["by_type"][r["type"]] += 1
        a["cards"].add(r["did"])
        if r["ease"] == 1:
            a["again"] += 1
    return agg


print("=" * 108)
print("A. 最近 30 天 每个分区的复习量 / 真实平均耗时")
print("=" * 108)
hdr = f"{'分区':<14}{'复习次数':>8}{'次/天':>8}{'总耗时h':>9}{'秒/张':>8}{'出错率%':>9}{'学习步':>7}{'复习':>7}{'重学':>7}"
print(hdr)
a30 = analyze(DAY30)
tot_n = tot_ms = 0
for label in BRANCHES:
    a = a30.get(label)
    if not a or a["n"] == 0:
        print(f"{label:<14}{'-':>8}")
        continue
    tot_n += a["n"]
    tot_ms += a["ms"]
    print(f"{label:<14}{a['n']:>8}{a['n']/30:>8.1f}{a['ms']/3.6e6:>9.1f}"
          f"{a['ms']/a['n']/1000:>8.1f}{a['again']/a['n']*100:>9.1f}"
          f"{a['by_type'][0]:>7}{a['by_type'][1]:>7}{a['by_type'][2]:>7}")
print("-" * 108)
print(f"{'合计':<14}{tot_n:>8}{tot_n/30:>8.1f}{tot_ms/3.6e6:>9.1f}{tot_ms/tot_n/1000:>8.1f}")

print()
print("=" * 108)
print("B. 最近 7 天 每个分区的复习量 / 真实平均耗时")
print("=" * 108)
print(hdr)
a7 = analyze(DAY7)
tot_n7 = tot_ms7 = 0
for label in BRANCHES:
    a = a7.get(label)
    if not a or a["n"] == 0:
        continue
    tot_n7 += a["n"]
    tot_ms7 += a["ms"]
    print(f"{label:<14}{a['n']:>8}{a['n']/7:>8.1f}{a['ms']/3.6e6:>9.1f}"
          f"{a['ms']/a['n']/1000:>8.1f}{a['again']/a['n']*100:>9.1f}"
          f"{a['by_type'][0]:>7}{a['by_type'][1]:>7}{a['by_type'][2]:>7}")
print("-" * 108)
print(f"{'合计':<14}{tot_n7:>8}{tot_n7/7:>8.1f}{tot_ms7/3.6e6:>9.1f}{tot_ms7/tot_n7/1000:>8.1f}")

print()
print("=" * 108)
print("C. 最近 30 天 新卡引入速度（每张卡在窗口内首次被复习）")
print("=" * 108)
rows = db.execute(
    "select c.did, c.nid, min(r.id) as first_rev from cards c join revlog r on r.cid = c.id "
    "group by c.id having first_rev > ?", (DAY30,)).fetchall()
intro = defaultdict(int)
for r in rows:
    intro[branch_of(decks.get(r["did"], "?"), r["nid"])] += 1
tot_intro = 0
for label in BRANCHES:
    n = intro.get(label, 0)
    tot_intro += n
    print(f"{label:<14}30天引入 {n:>5} 张   ≈ {n/30:>5.1f} 张/天")
print("-" * 108)
print(f"{'合计':<14}30天引入 {tot_intro:>5} 张   ≈ {tot_intro/30:>5.1f} 张/天")

print()
print("=" * 108)
print("D. 首次学习成本：新卡在最初 3 天内的平均复习次数")
print("=" * 108)
rows = db.execute(
    "select c.id, c.did, c.nid, count(r.id) as n, min(r.id) as f, max(r.id) as l, "
    "sum(r.time) as ms from cards c join revlog r on r.cid = c.id "
    "group by c.id having f > ?", (DAY30,)).fetchall()
by_branch = defaultdict(lambda: {"cards": 0, "revs": 0, "ms": 0})
for r in rows:
    b = by_branch[branch_of(decks.get(r["did"], "?"), r["nid"])]
    b["cards"] += 1
    b["revs"] += r["n"]
    b["ms"] += r["ms"]
for label in BRANCHES:
    b = by_branch.get(label)
    if not b or b["cards"] == 0:
        continue
    print(f"{label:<14}新卡 {b['cards']:>5} 张  平均 {b['revs']/b['cards']:.1f} 次复习/张  "
          f"首月平均 {b['ms']/b['cards']/1000:.0f} 秒/张")

print()
print("=" * 108)
print("E. 全库笔记类型（note type）分布")
print("=" * 108)
rows = db.execute(
    "select n.mid, count(distinct c.id) as cards, count(distinct n.id) as notes "
    "from cards c join notes n on n.id = c.nid where c.did != 1 "
    "group by n.mid order by cards desc").fetchall()
for r in rows:
    print(f"{models.get(r['mid'], r['mid']):<40} cards={r['cards']:>6}  notes={r['notes']:>6}")

print()
print("=" * 108)
print("F. 当前卡片状态（按分区，来自 DB，非今日队列）")
print("=" * 108)
rows = db.execute("select did, nid, type, count(*) c from cards group by did, nid, type").fetchall()
st = defaultdict(lambda: defaultdict(int))
for r in rows:
    st[branch_of(decks.get(r["did"], "?"), r["nid"])][r["type"]] += r["c"]
print(f"{'分区':<14}{'新卡':>8}{'学习中':>8}{'复习':>8}{'重学':>8}{'合计':>8}")
for label in BRANCHES:
    s = st.get(label)
    if not s:
        continue
    t = sum(s.values())
    print(f"{label:<14}{s[0]:>8}{s[1]:>8}{s[2]:>8}{s[3]:>8}{t:>8}")

print()
print("=" * 108)
print("G. 复习卡的平均间隔（按分区，成熟度）")
print("=" * 108)
rows = db.execute(
    "select did, nid, ivl, count(*) c from cards where type = 2 group by did, nid, ivl").fetchall()
iv = defaultdict(list)
for r in rows:
    iv[branch_of(decks.get(r["did"], "?"), r["nid"])].extend([r["ivl"]] * r["c"])
for label in BRANCHES:
    v = iv.get(label)
    if not v:
        continue
    v.sort()
    print(f"{label:<14}复习卡 {len(v):>5} 张  中位间隔 {v[len(v)//2]:>5} 天  "
          f"平均 {sum(v)/len(v):>6.1f} 天")

print()
print(f"snapshot dir: {TMP}")
