import os, sqlite3, sys, collections, datetime, statistics

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
card_deck = {r[0]: r[1] for r in cur.execute("SELECT id, did FROM cards")}
card_note = {r[0]: r[1] for r in cur.execute("SELECT id, nid FROM cards")}
note_tags = {r[0]: (r[1] or "") for r in cur.execute("SELECT id, tags FROM notes")}


def deck_branch(name, nid=None):
    """牌组名 → 分区名。考级词汇已扁平化：级别/频段只能从笔记标签拿。"""
    if name == JD.DECK_KAOKYU or name.startswith(JD.DECK_KAOKYU + "::"):
        for band in JD.BANDS:
            if band in name:              # 旧快照：子 deck 名里带频段
                return "考级词汇-%s" % band
        tags = note_tags.get(nid, "").split()
        lv = JD.level_from_tags(tags)
        if lv:
            return "考级词汇-%s" % (JD.band_from_tags(tags) or lv)
        return "考级词汇"
    return name

rows = list(cur.execute("SELECT id, cid, ease, time, type FROM revlog ORDER BY id"))
first_seen = {}
for ts, cid, ease, time_, type_ in rows:
    first_seen.setdefault(cid, ts)

cut = datetime.datetime(2026, 9, 23).timestamp() * 1000
print("=== 最近 7 天新卡落在哪个分区 ===")
print("   （考级词汇已扁平化：全部落在同一个 deck，级别/频段按笔记标签拆开）")
c = collections.Counter()
for cid, ts in first_seen.items():
    if ts >= cut:
        c[deck_branch(decks.get(card_deck.get(cid, 0), "?"), card_note.get(cid))] += 1
for k, v in c.most_common():
    print(f"  {v:>4}  {k}")

print("\n=== 各牌组下 20 张待学词（看接下来的内容）===")
for did in sorted(decks, key=lambda d: decks[d]):
    name = decks[did]
    if not any(x in name for x in ("高频日语单词 6000", JD.DECK_KAOKYU, "1-N3-解释",
                                   "2-N3-例句", "2-例句")):
        continue
    ws = []
    for nid, flds in cur.execute(
        "SELECT n.id, n.flds FROM notes n JOIN cards c ON c.nid=n.id "
        "WHERE c.did=? AND c.queue=0 ORDER BY n.sfld LIMIT 22", (did,)
    ):
        p = flds.split(SEP)
        ws.append(p[1] if len(p) > 1 else "?")
    print(f"  {name[-42:]:<44} {' '.join(ws[:20])}")

print("\n=== 语法解释卡耗时分布（是否有 60s 封顶）===")
grp = collections.defaultdict(list)
for ts, cid, ease, time_, type_ in rows:
    grp[decks.get(card_deck.get(cid, 0), "")].append(time_ / 1000)
for name in sorted(grp):
    if "-解释" not in name:
        continue
    v = grp[name]
    caps = sum(1 for x in v if x >= 59.5)
    print(f"  {name[-24:]:<26} n={len(v):>5} 均值={statistics.mean(v):>5.1f}s "
          f"中位={statistics.median(v):>5.1f}s 封顶占比={100*caps/len(v):>5.1f}%")

print("\n=== 现有卡池的“到期引擎” ===")
for label, where in (("全部复习中卡片", "queue=2 AND ivl>0"),
                     ("成熟卡(ivl>=21)", "queue=2 AND ivl>=21")):
    s = cur.execute(f"SELECT SUM(1.0/ivl), COUNT(*) FROM cards WHERE {where}").fetchone()
    print(f"  {label:<18} 共 {s[1]:>5} 张 -> 理论到期量 {s[0]:.0f} 张/天")
# learning-type load
n_learn = cur.execute("SELECT COUNT(*) FROM cards WHERE queue IN (1,3)").fetchone()[0]
print(f"  学习中/重学卡片: {n_learn}")

print("\n=== 剩余新卡构成 ===")
comp = collections.Counter()
for did, name in decks.items():
    n = cur.execute("SELECT COUNT(*) FROM cards WHERE did=? AND queue=0", (did,)).fetchone()[0]
    if n:
        comp[name] = n
tot = 0
for k in sorted(comp, key=lambda k: -comp[k]):
    print(f"  {comp[k]:>5}  {k[-52:]}")
    tot += comp[k]
print(f"  {tot:>5}  合计")
con.close()
