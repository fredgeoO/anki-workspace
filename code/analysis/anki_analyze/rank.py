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

row = []
for nid, mid, flds, tags in cur.execute("SELECT id, mid, flds, tags FROM notes"):
    p = flds.split(SEP)
    row.append((nid, ntname[mid], p, tags))

# --- verify Index == frequency rank, and Index vs jp-core band ---
idx_band = collections.defaultdict(collections.Counter)
for nid, name, p, tags in row:
    if name != "Japanese Vocabulary" or len(p) < 2:
        continue
    try:
        idx = int(p[0])
    except Exception:
        continue
    b = None
    for t in tags.split():
        m = re.match(r"jp-core::(\d)k$", t)
        if m:
            b = int(m.group(1))
    if b:
        idx_band[b][idx // 1000] += 1
print("=== Index 字段是不是频率排名？(行=jp-core档, 列=Index//1000) ===")
for b in sorted(idx_band):
    tot = sum(idx_band[b].values())
    dist = "  ".join(f"{k}k:{idx_band[b][k]}" for k in sorted(idx_band[b]))
    print(f"  core{b}k  n={tot:<5} {dist}")

# --- precise rank per word ---
rank = {}
for nid, name, p, tags in row:
    if name != "Japanese Vocabulary" or len(p) < 2:
        continue
    try:
        rank[p[1].strip()] = int(p[0])
    except Exception:
        pass
if rank:
    print(f"\n  拿到精确排名的词: {len(rank)}  排名范围 {min(rank.values())}–{max(rank.values())}")
    print(f"  排名 1/1000/3000/6000 的词: "
          f"{[w for w,r in rank.items() if r==1]} / "
          f"{[w for w,r in rank.items() if r==1000]} / "
          f"{[w for w,r in rank.items() if r==3000]} / "
          f"{[w for w,r in rank.items() if r==6000]}")

studied = {p[1].strip() for nid, name, p, tags in row if note_studied.get(nid) and len(p) > 1}

# --- JLPT band -> precise core rank ---
jb = {}
order = {"N5": 1, "N4": 2, "N3高频": 3, "N3中频": 4, "N3低频": 5, "N2高频": 6,
         "N2中频": 7, "N2低频": 8, "N1高频": 9, "N1中频": 10, "N1低频": 11}
for nid, name, p, tags in row:
    if name != "eggrolls-JLPT10k-v3.5" or len(p) < 2:
        continue
    w = p[1].strip()
    for t in tags.split():
        m = re.match(r"eggrolls-JLPT10k-v3\.5::(?:\d-N\d)(?:::(N\d)(高频|中频|低频))?", t)
        if m:
            grp = (m.group(1) + m.group(2)) if m.group(1) else None
            if grp:
                jb[w] = order[grp]

print("\n=== JLPT 各组词的精确 core 排名（只有两表都收录的才有排名）===")
print(f"  {'JLPT组':<10}{'有排名词数':>10}{'平均排名':>10}{'中位排名':>10}{'已学平均排名':>14}")
for o in sorted(set(jb.values())):
    ws = [w for w in jb if jb[w] == o and w in rank]
    if not ws:
        continue
    r = [rank[w] for w in ws]
    rl = [rank[w] for w in ws if w in studied]
    nm = {v: k for k, v in order.items()}[o]
    print(f"  {nm:<10}{len(ws):>10}{statistics.mean(r):>10.0f}{statistics.median(r):>10.0f}"
          f"{(statistics.mean(rl) if rl else 0):>14.0f}")

print("\n=== 核心问题：你正在学的 vs 排队中的，精确排名谁靠前 ===")
learn = [w for w in jb if jb[w] == 6 and w in rank and w not in studied]
later = [w for w in jb if jb[w] in (4, 5) and w in rank and w not in studied]
core3_un = [w for w in rank if rank[w] <= 3000 and w not in studied]
for lbl, ws in (("正在学 N2高频(未学)", learn),
                ("排队中 N3中频+低频(未学)", later),
                ("未学的 core 3000 内全部", core3_un)):
    if not ws:
        continue
    r = [rank[w] for w in ws]
    print(f"  {lbl:<26} n={len(ws):>4}  平均排名 {statistics.mean(r):>7.0f}  中位 {statistics.median(r):>6.0f}")

print("\n=== 未学的 core 3000 内词汇，散落在哪些考级分组 ===")
c = collections.Counter(jb.get(w, 0) for w in core3_un)
for o in sorted(c):
    nm = {v: k for k, v in order.items()}.get(o, "不在考级表")
    print(f"     {nm:<12} {c[o]:>4}")
print(f"\n  排名最靠前但还没学的 30 个词：")
for w in sorted(core3_un, key=lambda x: rank[x])[:30]:
    print(f"     #{rank[w]:<5}{w:<12}{'在'+{v:k for k,v in order.items()}.get(jb.get(w,0),'不在考级表')}")
con.close()
