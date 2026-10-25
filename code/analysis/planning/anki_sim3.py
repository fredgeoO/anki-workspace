"""Forward-simulate the Anki collection to price different new-card ratios.

v3:
  * retention curve p(pass | lastIvl) fitted from the user's own revlog
  * separate pass rate for learning steps (type 0) and relearning (type 2)
  * Anki's 1min/10min learning ladder, lapse -> 1d (lapse new-interval = 0%)
  * per-review seconds measured from revlog by branch x review type
  * two reporting windows: next 90 days (the felt load) and true steady state
"""
from __future__ import annotations

import random
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
import jp_decks as JD  # noqa: E402
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

SNAP = Path(WSP.SNAP_ANKISNAP)
db = sqlite3.connect(str(SNAP))
db.row_factory = sqlite3.Row
db.create_collation("unicase", lambda a, b: (a > b) - (a < b))
decks = {r["id"]: r["name"].replace("\x1f", "::")
         for r in db.execute("select id, name from decks")}

CORE = JD.DECK_CORE6000
# 考级词汇已扁平化：N5/N4/高/中/低 五个分支现在都在「2-考级词汇」这一个 deck 里，
# 只能靠 eggrolls 笔记标签分（见 code/common/jp_decks.py）。旧快照（子 deck 还在）
# 用 deck 名兜底，所以两个时代的快照都能跑。
KAOKYU_LABEL = {"N5": "词汇N5", "N4": "词汇N4",
                "高频": "词汇高", "中频": "词汇中", "低频": "词汇低"}
KAOKYU_NOTE_BRANCH = {}
for _r in db.execute("select id, tags from notes"):
    _tags = (_r["tags"] or "").split()
    _lv = JD.level_from_tags(_tags)
    if _lv:
        KAOKYU_NOTE_BRANCH[_r["id"]] = KAOKYU_LABEL.get(
            JD.band_from_tags(_tags) or _lv, "其他")

BRANCH_PREFIX = [(CORE, "Core6000"), (JD.DECK_EXAMPLE, "对白例句")]
ORDER = ["Core6000", "词汇N5", "词汇N4", "词汇高", "词汇中", "词汇低",
         "语法解释", "语法例句", "对白例句"]


def branch_of(name: str, nid=None) -> str:
    if name.startswith(JD.DECK_GRAMMAR):
        return "语法解释" if name.endswith("-解释") else "语法例句"
    if name == JD.DECK_KAOKYU or name.startswith(JD.DECK_KAOKYU + "::"):
        for band, label in (("高频词汇", "词汇高"), ("中频词汇", "词汇中"),
                            ("低频词汇", "词汇低"), ("1-N5-词汇", "词汇N5"),
                            ("2-N4-词汇", "词汇N4")):
            if band in name:
                return label
        return KAOKYU_NOTE_BRANCH.get(nid, "其他")
    for prefix, label in BRANCH_PREFIX:
        if name == prefix or name.startswith(prefix + "::"):
            return label
    return "其他"


NOW_MS = int(time.time() * 1000)
CUT = NOW_MS - 60 * 86400_000
rev = db.execute(
    "select r.type, r.time, r.ease, r.lastIvl, c.did, c.nid from revlog r "
    "join cards c on c.id = r.cid where r.id > ?", (CUT,)).fetchall()

# ---------- seconds per review, by branch x review type
sec = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
for r in rev:
    s = sec[branch_of(decks.get(r["did"], "?"), r["nid"])][r["type"]]
    s[0] += 1
    s[1] += r["time"]
TIME = {}
for b, d in sec.items():
    avg = sum(v[1] for v in d.values()) / sum(v[0] for v in d.values()) / 1000
    for t in (0, 1, 2):
        n, ms = d.get(t, [0, 0.0])
        TIME[(b, t)] = ms / n / 1000 if n > 40 else avg

# ---------- retention curve
BUCKETS = [(1, 3), (3, 7), (7, 14), (14, 30), (30, 60), (60, 120),
           (120, 240), (240, 500), (500, 10 ** 9)]
CURVE = []
for lo, hi in BUCKETS:
    sub = [r for r in rev if r["type"] == 1 and lo <= r["lastIvl"] < hi]
    if len(sub) >= 25:
        CURVE.append((lo, hi, sum(1 for r in sub if r["ease"] > 1) / len(sub), len(sub)))
if not CURVE or CURVE[-1][1] < 10 ** 9:
    CURVE.append((CURVE[-1][1], 10 ** 9, CURVE[-1][2], 0))

learn_sub = [r for r in rev if r["type"] == 0]
P_LEARN = sum(1 for r in learn_sub if r["ease"] > 1) / len(learn_sub)
rel_sub = [r for r in rev if r["type"] == 2]
P_RELEARN = sum(1 for r in rel_sub if r["ease"] > 1) / len(rel_sub)

print("=" * 94)
print("实测保留率曲线（近60天，来自你自己的 revlog）")
print("=" * 94)
print(f"  新卡学习步通过率 {P_LEARN*100:.1f}%   重学步通过率 {P_RELEARN*100:.1f}%")
for lo, hi, p, n in CURVE:
    hi_s = "∞" if hi >= 10 ** 9 else str(hi)
    print(f"  上次间隔 {lo:>4}-{hi_s:<5}天  通过率 {p*100:5.1f}%  (n={n:>5})  "
          + "#" * int(p * 45))


def p_of(ivl):
    for lo, hi, p, _ in CURVE:
        if lo <= ivl < hi:
            return p
    return CURVE[-1][2]


# ---------- card states
crt = db.execute("select crt from col").fetchone()[0]
cards = db.execute("select id, did, nid, type, due, ivl, factor from cards").fetchall()
by_branch = defaultdict(list)
for c in cards:
    by_branch[branch_of(decks.get(c["did"], "?"), c["nid"])].append(c)

print()
print("=" * 94)
print("起始状态")
print("=" * 94)
print(f"{'branch':<12}{'新卡':>8}{'复习卡':>9}{'复习卡均间隔':>14}")
for b in ORDER:
    cs = by_branch.get(b, [])
    if not cs:
        continue
    nw = sum(1 for c in cs if c["type"] == 0)
    rv = [c for c in cs if c["type"] == 2]
    mi = sum(c["ivl"] for c in rv) / len(rv) if rv else 0
    print(f"{b:<12}{nw:>8}{len(rv):>9}{mi:>14.1f}")
print(f"{'合计':<12}{sum(1 for c in cards if c['type']==0):>8}"
      f"{sum(1 for c in cards if c['type']==2):>9}")


class Card:
    __slots__ = ("b", "phase", "due", "ivl", "ease", "step")

    def __init__(self, b, phase, due, ivl, ease):
        self.b, self.phase, self.due, self.ivl, self.ease = b, phase, due, ivl, ease


def build_state():
    st = defaultdict(list)
    for b in ORDER:
        for c in by_branch.get(b, []):
            if c["type"] == 0:
                st[b].append(Card(b, "new", None, 0, 2.5))
            elif c["type"] == 2:
                st[b].append(Card(b, "review", c["due"], max(1, c["ivl"]),
                                  max(1.3, c["factor"] / 1000)))
            else:
                st[b].append(Card(b, "learn", 0, max(1, c["ivl"]),
                                  max(1.3, c["factor"] / 1000)))
    return st


def run(new_per_day, horizon, seed=11):
    rng = random.Random(seed)
    st = build_state()
    daily = [defaultdict(lambda: [0.0, 0.0]) for _ in range(horizon)]
    for d in range(horizon):
        day = daily[d]
        for b in ORDER:
            n = new_per_day.get(b, 0)
            if n > 0:
                k = 0
                for c in st[b]:
                    if k >= n:
                        break
                    if c.phase == "new":
                        c.phase, c.due, c.ivl = "learn", d, 0
                        k += 1
        for b in ORDER:
            for c in st[b]:
                if c.phase == "new" or c.due is None or c.due > d:
                    continue
                if c.phase == "learn":
                    step, guard = 0, 0
                    while guard < 10:
                        guard += 1
                        day[b][0] += 1
                        day[b][1] += TIME.get((b, 0), 15)
                        step = step + 1 if rng.random() < P_LEARN else 0
                        if step >= 2:
                            break
                    c.phase, c.ivl, c.due = "review", 1, d + 1
                elif c.phase == "relearn":
                    day[b][0] += 1
                    day[b][1] += TIME.get((b, 2), 15)
                    c.phase, c.ivl, c.due = "review", 1, d + 1
                else:
                    day[b][0] += 1
                    day[b][1] += TIME.get((b, 1), 15)
                    if rng.random() < p_of(c.ivl):
                        c.ivl = min(36500, max(c.ivl + 1, round(c.ivl * c.ease)))
                        c.due = d + c.ivl
                    else:
                        c.ease = max(1.3, c.ease - 0.2)
                        c.phase, c.ivl, c.due = "relearn", 1, d
                        day[b][0] += 1
                        day[b][1] += TIME.get((b, 2), 15)
    return daily


def win(daily, lo, hi):
    n = hi - lo
    d = daily[lo:hi]
    return (sum(x[0] for day in d for x in day.values()) / n,
            sum(x[1] for day in d for x in day.values()) / n)


def report(title, plan, horizon=1200, detail=True):
    daily = run(plan, horizon)
    print(f"\n{'-'*94}\n{title}")
    print(f"  新卡/天: {', '.join(f'{k}={v}' for k, v in plan.items() if v)}"
          f"  → 合计 {sum(plan.values())}")
    rows = [("前30天", (0, 30)), ("31-90天", (30, 90)), ("91-180天", (90, 180)),
            ("稳态(末期30天)", (horizon - 30, horizon))]
    print(f"  {'窗口':<16}{'卡片/天':>10}{'分钟/天':>11}{'小时/天':>10}{'秒/张':>8}")
    for name, w in rows:
        c, s = win(daily, *w)
        print(f"  {name:<16}{c:>10.0f}{s/60:>11.0f}{s/3600:>10.2f}{s/max(c,1):>8.1f}")
    if detail:
        print(f"  {'前90天 分区明细':<16}{'卡片/天':>10}{'分钟/天':>11}")
        for b in ORDER:
            c = sum(day[b][0] for day in daily[0:90]) / 90
            s = sum(day[b][1] for day in daily[0:90]) / 90
            if c < 0.5:
                continue
            print(f"  {b:<16}{c:>10.0f}{s/60:>11.1f}")
    return daily


if __name__ == "__main__":
    CURRENT = {"Core6000": 20, "词汇高": 15, "语法解释": 4, "语法例句": 11,
               "对白例句": 2}
    report("[校验] 现状配置", CURRENT)

    PLANS = {
        "A 均衡型": dict(Core6000=10, 词汇高=20, 语法解释=3, 语法例句=10, 对白例句=2),
        "B 词汇优先": dict(Core6000=8, 词汇高=25, 语法解释=2, 语法例句=8, 对白例句=2),
        "C 轻量维持": dict(Core6000=6, 词汇高=12, 语法解释=2, 语法例句=6, 对白例句=2),
        "D 语法强化": dict(Core6000=8, 词汇高=15, 语法解释=4, 语法例句=15, 对白例句=3),
        "E 上限压测": dict(Core6000=14, 词汇高=25, 语法解释=3, 语法例句=12, 对白例句=3),
    }
    for k, v in PLANS.items():
        report(k, v, detail=(k in ("A 均衡型", "B 词汇优先")))
