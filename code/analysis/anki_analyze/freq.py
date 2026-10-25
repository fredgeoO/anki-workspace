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
note_studied = collections.defaultdict(bool)
for nid, reps in cur.execute("SELECT nid, reps FROM cards"):
    if reps > 0:
        note_studied[nid] = True

# word -> core band / jlpt band / studied
core_band, jlpt_band, studied = {}, {}, set()
for nid, mid, flds, tags in cur.execute("SELECT id, mid, flds, tags FROM notes"):
    name = ntname[mid]
    p = flds.split(SEP)
    w = p[1].strip() if len(p) > 1 else ""
    if not w:
        continue
    if note_studied.get(nid):
        studied.add(w)
    for t in tags.split():
        m = re.match(r"jp-core::(\d)k$", t)
        if m:
            core_band[w] = int(m.group(1))
        m = re.match(r"eggrolls-JLPT10k-v3\.5::(?:(\d)-N(\d))(?:::(N\d)(高频|中频|低频))?", t)
        if m:
            grp = m.group(3) + m.group(4) if m.group(3) else "N" + m.group(2)
            order = {"N5": 1, "N4": 2, "N3高频": 3, "N3中频": 4, "N3低频": 5,
                     "N2高频": 6, "N2中频": 7, "N2低频": 8,
                     "N1高频": 9, "N1中频": 10, "N1低频": 11}
            jlpt_band[w] = order.get(grp, 99)

both = [w for w in jlpt_band if w in core_band and w in studied or (w in jlpt_band and w in core_band)]
print("=== 1. JLPT 级别序 vs 真实词频序，两者差多少 ===")
print("  （只看两套表都收录的词；core 数字越小=越常用）\n")
print(f"  {'JLPT 分组':<10}{'词数':>6}{'平均core频段':>14}{'中位':>6}{'落在core1-3k占比':>18}")
order_rev = {}
for w, o in jlpt_band.items():
    order_rev.setdefault(o, []).append(w)
names = {1: "N5", 2: "N4", 3: "N3高频", 4: "N3中频", 5: "N3低频", 6: "N2高频",
         7: "N2中频", 8: "N2低频", 9: "N1高频", 10: "N1中频", 11: "N1低频"}
for o in sorted(order_rev):
    ws = [w for w in order_rev[o] if w in core_band]
    if not ws:
        continue
    bands = [core_band[w] for w in ws]
    in13 = sum(1 for b in bands if b <= 3)
    print(f"  {names.get(o,o):<10}{len(ws):>6}{statistics.mean(bands):>14.2f}{statistics.median(bands):>6.0f}"
          f"{100*in13/len(ws):>17.0f}%")

print("\n=== 2. 关键检验：你正在学的词 vs 排在后面的词，谁更常用？===")
learning = [w for w in jlpt_band if jlpt_band[w] == 6 and w in core_band and w not in studied]
later = [w for w in jlpt_band if jlpt_band[w] in (4, 5) and w in core_band and w not in studied]
print(f"  你正在学（N2高频，未学）: {len(learning)} 词")
if learning:
    b = [core_band[w] for w in learning]
    print(f"     平均 core 频段 {statistics.mean(b):.2f}   中位 {statistics.median(b):.0f}")
    print(f"     落在 core 1-3k 的比例: {100*sum(1 for x in b if x<=3)/len(b):.0f}%")
print(f"  排在后面（N3中频+N3低频，未学）: {len(later)} 词")
if later:
    b = [core_band[w] for w in later]
    print(f"     平均 core 频段 {statistics.mean(b):.2f}   中位 {statistics.median(b):.0f}")
    print(f"     落在 core 1-3k 的比例: {100*sum(1 for x in b if x<=3)/len(b):.0f}%")

print("\n=== 3. 具体证据：还没学、但频率更高（core 3k 内）的词，被排在哪 ===")
unlearned_core3 = sorted([w for w in core_band if core_band[w] == 3 and w not in studied])
print(f"  未学的 core 3k 词共 {len(unlearned_core3)} 个")
c = collections.Counter(jlpt_band.get(w, 0) for w in unlearned_core3)
for o in sorted(c):
    print(f"     在 JLPT 分组 {names.get(o,'不在考级表'):<10} 的有 {c[o]:>4} 个")
print(f"  例（应优先但排在 N3低频/N2高频 之后）: {'、'.join(unlearned_core3[:25])}")

print("\n=== 4. 你已学的 N2高频 词里，有多少其实属于低频区（core 4k 以外）===")
n2_studied = [w for w in jlpt_band if jlpt_band[w] == 6 and w in studied]
b = [core_band.get(w) for w in n2_studied]
c2 = collections.Counter("不在core6000" if x is None else f"{x}k" for x in b)
for k in ["1k", "2k", "3k", "4k", "5k", "6k", "不在core6000"]:
    if c2.get(k):
        print(f"     {k:<12} {c2[k]:>4}  ({100*c2[k]/len(n2_studied):.0f}%)")

print("\n=== 5. 频率优先的边际收益（上一次实测的覆盖率曲线）===")
print("  core 1k        -> 35–53%")
print("  core 1-2k      -> 43–59%")
print("  core 1-3k      -> 58–65%")
print("  core 1-4k      -> 62–68%")
print("  core 1-6k 全部 -> 70–77%")
con.close()
