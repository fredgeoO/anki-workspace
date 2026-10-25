import os, re, sqlite3, collections, statistics, json
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect(os.path.join(HERE, "collection_snapshot.anki2"))
con.create_collation("unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
cur = con.cursor()
SEP = "\x1f"
decks = {r[0]: r[1].replace(SEP, "::") for r in cur.execute("SELECT id, name FROM decks")}
ntname = {r[0]: r[1] for r in cur.execute("SELECT id, name FROM notetypes")}
card_deck = dict(cur.execute("SELECT id, did FROM cards"))


def grp(name):
    if not name:
        return "?"
    if "高频日语单词 6000" in name:
        return "core6000(听辨)"
    if "考级词汇" in name:
        return "考级词汇"
    if "-解释" in name:
        return "语法-解释"
    if "例句" in name and "语法" in name:
        return "语法-例句"
    if name.endswith("例句"):
        return "挖句"
    return "其他"


# ---- 1. 挖句卡的模板方向 ----
print("=== 1. 挖句卡到底在测哪个方向？===")
basic_ids = [k for k, v in ntname.items() if v == "Basic"]
for ntid in basic_ids:
    for ord_, name, cfg in cur.execute("SELECT ord, name, config FROM templates WHERE ntid=?", (ntid,)):
        try:
            js = json.loads(cfg)
        except Exception:
            continue
        q = js.get("qfmt", "")
        a = js.get("afmt", "")
        print(f"  模板「{name}」")
        print(f"    正面: {re.sub(chr(10),' ',q)[:190]}")
        print(f"    背面: {re.sub(chr(10),' ',a)[:190]}")

# ---- 2. 反应速度随复习次数的变化 ----
print("\n=== 2. 反应速度有没有随复习次数下降（这才是熟练度指标）===")
rows = list(cur.execute("SELECT id, cid, ease, time, type FROM revlog ORDER BY id"))
per_card = collections.defaultdict(list)
for ts, cid, ease, time_, type_ in rows:
    per_card[cid].append((ts, ease, time_, type_))

series = collections.defaultdict(lambda: collections.defaultdict(list))
for cid, lst in per_card.items():
    d = grp(decks.get(card_deck.get(cid, 0), ""))
    for i, (ts, ease, time_, type_) in enumerate(lst, 1):
        b = "1" if i == 1 else ("2" if i == 2 else ("3" if i == 3 else
             ("4-5" if i <= 5 else ("6-10" if i <= 10 else "11-20" if i <= 20 else ">20"))))
        series[d][b].append(time_ / 1000)

order = ["1", "2", "3", "4-5", "6-10", "11-20", ">20"]
print(f"  {'牌组':<16}" + "".join(f"{b+'次':>9}" for b in order))
for d in ("core6000(听辨)", "考级词汇", "语法-例句", "挖句", "语法-解释"):
    if d not in series:
        continue
    line = f"  {d:<16}"
    for b in order:
        v = series[d].get(b)
        line += f"{(statistics.mean(v) if v else 0):>8.1f}s"
    print(line)

# ---- 3. 反应速度分布：多少是“自动化”的 ----
print("\n=== 3. 成熟卡（≥11 次复习）的反应速度分布 ===")
print("   参考：日语语速约每秒 7-8 拍。超过 3 秒的提取，实时听力里来不及。")
for d in ("core6000(听辨)", "考级词汇", "语法-例句", "挖句"):
    if d not in series:
        continue
    v = series[d].get("11-20", []) + series[d].get(">20", [])
    if not v:
        continue
    fast = sum(1 for x in v if x <= 2)
    mid = sum(1 for x in v if 2 < x <= 5)
    slow = sum(1 for x in v if 5 < x <= 15)
    vslow = sum(1 for x in v if x > 15)
    n = len(v)
    print(f"  {d:<16} n={n:>5}  ≤2s {100*fast/n:>4.0f}%   2-5s {100*mid/n:>4.0f}%   "
          f"5-15s {100*slow/n:>4.0f}%   >15s {100*vslow/n:>4.0f}%   中位 {statistics.median(v):>5.1f}s")

# ---- 4. 听辨 vs 见词回忆：同一批词的速度差 ----
print("\n=== 4. 同一个词的两个方向，反应速度差多少 ===")
note_word = {}
for nid, flds in cur.execute("SELECT id, flds FROM notes"):
    p = flds.split(SEP)
    note_word[nid] = p[1].strip() if len(p) > 1 else ""
card_note = dict(cur.execute("SELECT id, nid FROM cards"))
spd = collections.defaultdict(list)
for cid, lst in per_card.items():
    d = grp(decks.get(card_deck.get(cid, 0), ""))
    if d in ("core6000(听辨)", "考级词汇"):
        for ts, ease, time_, type_ in lst:
            spd[d].append(time_ / 1000)
for d in ("考级词汇", "core6000(听辨)"):
    v = spd.get(d, [])
    if v:
        print(f"  {d:<16} 平均 {statistics.mean(v):>5.1f}s  中位 {statistics.median(v):>5.1f}s")
con.close()
