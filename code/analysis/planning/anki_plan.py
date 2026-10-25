"""Final planner: price candidate new-card ratios with a vocab pipeline."""
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
VOCAB_PIPE = ["词汇高", "词汇中", "词汇低"]
GROUP = {"Core6000": "core", "词汇N5": "vocab", "词汇N4": "vocab",
         "词汇高": "vocab", "词汇中": "vocab", "词汇低": "vocab",
         "语法解释": "gexp", "语法例句": "gex", "对白例句": "dlg"}


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

tot_n = sum(v[0] for d in sec.values() for v in d.values())
tot_ms = sum(v[1] for d in sec.values() for v in d.values())
print(f"实测全库平均耗时: {tot_ms/tot_n/1000:.1f} 秒/张  (n={tot_n}, 近60天)")
print("实测各卡种秒/张：")
for b in ORDER:
    if b in sec:
        n = sum(v[0] for v in sec[b].values())
        ms = sum(v[1] for v in sec[b].values())
        print(f"   {b:<12}{ms/n/1000:>6.1f} s")

BUCKETS = [(1, 3), (3, 7), (7, 14), (14, 30), (30, 60), (60, 120), (120, 10 ** 9)]
CURVE = []
for lo, hi in BUCKETS:
    sub = [r for r in rev if r["type"] == 1 and lo <= r["lastIvl"] < hi]
    if len(sub) >= 25:
        CURVE.append((lo, hi, sum(1 for r in sub if r["ease"] > 1) / len(sub)))


def p_of(ivl):
    for lo, hi, p in CURVE:
        if lo <= ivl < hi:
            return p
    return CURVE[-1][2]


learn_sub = [r for r in rev if r["type"] == 0]
P_LEARN = sum(1 for r in learn_sub if r["ease"] > 1) / len(learn_sub)
rel_sub = [r for r in rev if r["type"] == 2]
P_RELEARN = sum(1 for r in rel_sub if r["ease"] > 1) / len(rel_sub)

cards = db.execute("select id, did, nid, type, due, ivl, factor from cards").fetchall()
by_branch = defaultdict(list)
for c in cards:
    by_branch[branch_of(decks.get(c["did"], "?"), c["nid"])].append(c)

CRT = db.execute("select crt from col").fetchone()[0]
TODAY = int((time.time() - CRT) // 86400)   # cards.due is days since collection creation
LAPSE_MULT = 0.0   # Anki "new interval" after a lapse (0.0 = deck default)


class Card:
    __slots__ = ("b", "phase", "due", "ivl", "ease")

    def __init__(self, b, phase, due, ivl, ease):
        self.b, self.phase, self.due, self.ivl, self.ease = b, phase, due, ivl, ease


def build_state():
    st = defaultdict(list)
    for b in ORDER:
        for c in by_branch.get(b, []):
            if c["type"] == 0:
                st[b].append(Card(b, "new", None, 0, 2.5))
            elif c["type"] == 2:
                st[b].append(Card(b, "review", c["due"] - TODAY, max(1, c["ivl"]),
                                  max(1.3, c["factor"] / 1000)))
            else:
                st[b].append(Card(b, "learn", 0, max(1, c["ivl"]),
                                  max(1.3, c["factor"] / 1000)))
    return st


def run(plan, horizon, seed=17):
    """plan: {'core':8,'vocab':20,'gexp':2,'gex':9,'dlg':3} new cards per day."""
    rng = random.Random(seed)
    st = build_state()
    daily = [defaultdict(lambda: [0.0, 0.0]) for _ in range(horizon)]

    def pull(b, n, d):
        k = 0
        for c in st[b]:
            if k >= n:
                break
            if c.phase == "new":
                c.phase, c.due, c.ivl = "learn", d, 0
                k += 1
        return n - k

    for d in range(horizon):
        day = daily[d]
        pull("Core6000", plan.get("core", 0), d)
        left = plan.get("vocab", 0)
        for b in VOCAB_PIPE:
            if left <= 0:
                break
            left = pull(b, left, d)
        pull("语法解释", plan.get("gexp", 0), d)
        pull("语法例句", plan.get("gex", 0), d)
        pull("对白例句", plan.get("dlg", 0), d)
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
                        nxt = max(c.ivl + 1, round(c.ivl * c.ease))
                        iv = c.ivl
                        if iv >= 2.5:
                            if iv < 7:
                                f = 1
                            elif iv < 30:
                                f = max(1, round(iv * 0.15))
                            else:
                                f = max(1, round(iv * 0.05))
                            nxt += rng.randint(-f, f)
                        c.ivl = min(36500, max(1, nxt))
                        c.due = d + c.ivl
                    else:
                        old_ivl = c.ivl
                        c.ease = max(1.3, c.ease - 0.2)
                        c.phase, c.ivl, c.due = "relearn", 1, d
                        day[b][0] += 1
                        day[b][1] += TIME.get((b, 2), 15)
                        new_ivl = max(1, round(old_ivl * LAPSE_MULT))
                        if new_ivl > 1:
                            c.phase, c.ivl, c.due = "review", new_ivl, d + new_ivl
    return daily


def win(daily, lo, hi):
    n = hi - lo
    d = daily[lo:hi]
    return (sum(x[0] for day in d for x in day.values()) / n,
            sum(x[1] for day in d for x in day.values()) / n)


def report(title, plan, horizon=730, detail=False):
    daily = run(plan, horizon)
    n = sum(plan.values())
    print(f"\n{'-'*96}")
    print(f"{title}   [新卡 {n}/天: " +
          " ".join(f"{k}={v}" for k, v in plan.items()) + "]")
    print(f"  {'窗口':<14}{'卡片/天':>10}{'分钟/天':>11}{'小时/天':>10}{'秒/张':>8}")
    for name, w in [("前30天", (0, 30)), ("31-90天", (30, 90)),
                    ("91-180天", (90, 180)), ("181-365天", (180, 365)),
                    ("稳态", (horizon - 30, horizon))]:
        c, s = win(daily, *w)
        print(f"  {name:<14}{c:>10.0f}{s/60:>11.0f}{s/3600:>10.2f}{s/max(c,1):>8.1f}")
    if detail:
        print(f"  {'31-90天明细':<14}{'卡片/天':>10}{'分钟/天':>11}{'占比%':>8}")
        tot = sum(day[b][1] for day in daily[30:90] for b in ORDER)
        for b in ORDER:
            c = sum(day[b][0] for day in daily[30:90]) / 60
            s = sum(day[b][1] for day in daily[30:90]) / 60
            if c < 0.5:
                continue
            print(f"  {b:<14}{c:>10.0f}{s/60:>11.1f}{s/tot*100:>8.1f}")
    return daily


if __name__ == "__main__":
    report("[校验] 现状 (Core20+词汇15+解4+例11+白2)",
           dict(core=20, vocab=15, gexp=4, gex=11, dlg=2), detail=True)

    CANDS = {
        "P1 推荐：词汇为主(20) + 听辨(8)": dict(core=8, vocab=20, gexp=2, gex=9, dlg=3),
        "P2 省时：词汇(25) + 听辨(5)": dict(core=5, vocab=25, gexp=2, gex=7, dlg=2),
        "P3 听说并重：词汇(15) + 听辨(12)": dict(core=12, vocab=15, gexp=2, gex=9, dlg=3),
        "P4 上限：全部拉满(55)": dict(core=12, vocab=25, gexp=3, gex=12, dlg=3),
        "P5 全听辨型(现状比例)": dict(core=18, vocab=18, gexp=3, gex=10, dlg=2),
    }
    for k, v in CANDS.items():
        report(k, v, detail=True)
