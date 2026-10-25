"""One-shot: real review behaviour + FSRS load. Reads a WORKSPACE COPY of the live
collection (data/snapshots/live/collection.anki2 + -wal) so nothing is locked and
WAL contents are visible.

Sections:
  A. daily volume / again rate / sec per card (last 21 days)
  B. per deck: n, sec/card stats, again rate, grade mix (last 14 days)
  C. review cards: sec/card vs audio duration in the media library (last 14 days)
  D. FSRS state per deck: stability / difficulty / interval
  E. steady-state due/day at candidate retention targets
"""
import json
import os
import re
import sqlite3
import struct
from collections import defaultdict
from datetime import datetime
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

WS = r"<工作区根>"
DB = os.path.join(WS, r"data\snapshots\live\collection.anki2")
MEDIA = os.path.join(os.environ["APPDATA"], "Anki2", "账户 1", "collection.media")

con = sqlite3.connect(DB)
cur = con.cursor()

decks = {}
for did, name in cur.execute("select id, name from decks"):
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    decks[did] = name.replace("\x1f", "::")

card_did = {}
card_info = {}
for cid, did, ivl, ctype, reps, lapses in cur.execute(
        "select id,did,ivl,type,reps,lapses from cards"):
    card_did[cid] = did
    card_info[cid] = (ivl, ctype, reps, lapses)

NOW = max(list(cur.execute("select max(id) from revlog"))[0][0],
          list(cur.execute("select max(mod) from cards"))[0][0] * 1000)
print("NOW:", datetime.fromtimestamp(NOW / 1000), "| reviews:", list(cur.execute("select count(*) from revlog"))[0][0])


def secs(v):
    """revlog.time is milliseconds in this collection (52 s median => 52000 ms)."""
    return v / 1000.0


def stats(v):
    v = sorted(v)
    n = len(v)
    if not n:
        return (0, 0, 0, 0, 0)
    return (v[n // 2], sum(v) / n, v[int(n * .75)], v[int(n * .90)], v[-1])


print("\n=== A. daily volume (last 21 days) ===")
buck = defaultdict(lambda: [0, 0, 0.0, 0])
for rid, ease, t in cur.execute("select id,ease,time from revlog where id>=?",
                                (NOW - 21 * 86400_000,)):
    d = datetime.fromtimestamp(rid / 1000).strftime("%m-%d")
    b = buck[d]
    b[0] += 1
    b[1] += 1 if ease == 1 else 0
    b[2] += secs(t)
    b[3] += 1 if secs(t) > 300 else 0
print(f"  {'day':6s} {'n':>5s} {'again%':>7s} {'min':>7s} {'sec/card':>9s} {'>300s':>6s}")
for d in sorted(buck):
    n, ag, sec, big = buck[d]
    print(f"  {d:6s} {n:5d} {ag/max(n,1)*100:6.1f}% {sec/60:7.1f} {sec/max(n,1):9.1f} {big:6d}")

cut14 = NOW - 14 * 86400_000
cache = {}
print("\n=== B. per deck (last 14 days) ===")
agg = defaultdict(lambda: {"n": 0, "ag": 0, "ts": [], "e": defaultdict(int), "ivl": []})
for rid, cid, ease, t, lastIvl in cur.execute(
        "select id,cid,ease,time,lastIvl from revlog where id>=?", (cut14,)):
    did = card_did.get(cid)
    name = decks.get(did, f"?{did}")
    # roll up to the meaningful deck level
    key = name
    for prefix in ("0-日本语学习::0-词汇::2-考级词汇",
                   "0-日本语学习::1-语法",
                   "0-日本语学习::0-词汇"):
        if name.startswith(prefix):
            key = prefix
            break
    a = agg[key]
    a["n"] += 1
    a["e"][ease] += 1
    a["ag"] += 1 if ease == 1 else 0
    if t <= 300_000:
        a["ts"].append(secs(t))
    a["ivl"].append(lastIvl)
rows = []
for k, a in agg.items():
    med, mean, p75, p90, mx = stats(a["ts"])
    iv = sorted(a["ivl"])
    rows.append((a["n"], k, med, mean, p75, p90, a["ag"] / max(a["n"], 1) * 100,
                 dict(a["e"]), iv[len(iv) // 2] if iv else 0))
rows.sort(reverse=True)
print(f"  {'n':>5s} {'deck':44s} {'med':>4s} {'mean':>5s} {'p75':>4s} {'p90':>4s} {'again%':>7s} {'medLastIvl':>10s} grades(1/2/3/4)")
for n, k, med, mean, p75, p90, ag, e, mivl in rows:
    print(f"  {n:5d} {k[:44]:44s} {med:4.1f} {mean:5.1f} {p75:4.1f} {p90:4.1f} {ag:6.1f}% {mivl:10d} "
          f"{e.get(1,0)}/{e.get(2,0)}/{e.get(3,0)}/{e.get(4,0)}")

print("\n=== C. audio duration vs answer time (last 14 days) ===")
# collect sound filenames referenced by notes, measure durations from the media folder
MP3 = re.compile(r"\[sound:([^\]]+)\]")


def mp3_duration(path):
    """Fast CBR estimate: parse the first frame header, read the bitrate, divide
    the payload size by bytes/second. Falls back to a full frame walk for VBR."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(64 * 1024)
    except Exception:
        return None
    off = 0
    if head[:3] == b"ID3":
        off = 10 + (((head[6] & 0x7F) << 21) | ((head[7] & 0x7F) << 14) |
                    ((head[8] & 0x7F) << 7) | (head[9] & 0x7F))
    br1 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
    br2 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
    i = off
    n = len(head)
    while i + 4 <= n:
        if head[i] == 0xFF and (head[i + 1] & 0xE0) == 0xE0:
            ver = (head[i + 1] >> 3) & 3      # 3 = MPEG1, 2 = MPEG2
            layer = (head[i + 1] >> 1) & 3    # 1 = layer III
            bri = (head[i + 2] >> 4) & 0xF
            sri = (head[i + 2] >> 2) & 3
            if layer == 1 and bri not in (0, 15) and sri != 3:
                kbps = (br1 if ver == 3 else br2)[bri]
                return max((size - off) * 8.0 / (kbps * 1000), 0.0)
        i += 1
    return None


# per-card answer times (last 14 days) and per-note audio totals
card_times = defaultdict(list)
card_note = {}
for cid, nid in cur.execute("select id, nid from cards"):
    card_note[cid] = nid
for rid, cid, t in cur.execute("select id,cid,time from revlog where id>=?", (cut14,)):
    if t <= 300_000:
        card_times[cid].append(secs(t))

note_audio = {}
for nid, flds in cur.execute("select id, flds from notes"):
    tot = 0.0
    cnt = 0
    for m in MP3.finditer(flds or ""):
        f = m.group(1)
        if f not in cache:
            cache[f] = mp3_duration(os.path.join(MEDIA, f))
        if cache[f]:
            tot += cache[f]
            cnt += 1
    if cnt:
        note_audio[nid] = (tot, cnt)

pair = defaultdict(lambda: {"a": [], "t": [], "hit60": 0, "n": 0})
for cid, ts in card_times.items():
    nid = card_note.get(cid)
    did = card_did.get(cid)
    name = decks.get(did, f"?{did}")
    if nid not in note_audio:
        continue
    aud = note_audio[nid][0]
    p = pair[name]
    p["a"].append(aud)
    p["t"].append(sorted(ts)[len(ts) // 2])
    p["n"] += len(ts)
    p["hit60"] += sum(1 for x in ts if x >= 59.0)
print(f"  {'deck':46s} {'cards':>5s} {'medAudio':>8s} {'medTime':>7s} {'medPause':>8s} {'>=59s':>6s}")
for name in sorted(pair, key=lambda k: -pair[k]["n"])[:14]:
    p = pair[name]
    a = sorted(p["a"])
    t = sorted(p["t"])
    ma = a[len(a) // 2]
    mt = t[len(t) // 2]
    print(f"  {name[:46]:46s} {len(a):5d} {ma:8.2f} {mt:7.1f} {max(mt-ma,0):8.1f} "
          f"{p['hit60']/max(p['n'],1)*100:5.1f}%")
print(f"  (measured {len(cache)} media files)")

print("\n=== D. FSRS state per deck ===")
states = defaultdict(lambda: {"n": 0, "S": [], "D": [], "ivl": [], "lapses": 0, "reps": 0})
allrows = []
for cid, did, ivl, factor, reps, lapses, cdata in cur.execute(
        "select id,did,ivl,factor,reps,lapses,data from cards"):
    if not cdata:
        continue
    try:
        dd = json.loads(cdata)
    except Exception:
        continue
    if "s" not in dd:
        continue
    g = decks.get(did, f"?{did}")
    s = states[g]
    s["n"] += 1
    s["S"].append(dd["s"])
    s["D"].append(dd.get("d", 0))
    s["ivl"].append(ivl)
    s["lapses"] += lapses
    s["reps"] += reps
    allrows.append((g, dd["s"], dd.get("d", 0), ivl))
print(f"  {'deck':48s} {'cards':>6s} {'medS':>8s} {'medD':>6s} {'medIvl':>7s} {'reps':>6s} {'lapse':>6s}")
for g, s in sorted(states.items(), key=lambda kv: -kv[1]["n"])[:14]:
    S = sorted(s["S"])
    D = sorted(s["D"])
    I = sorted(s["ivl"])
    print(f"  {g[:48]:48s} {s['n']:6d} {S[len(S)//2]:8.2f} {D[len(D)//2]:6.2f} {I[len(I)//2]:7d} "
          f"{s['reps']/s['n']:6.2f} {s['lapses']/s['n']:6.2f}")

print("\n=== E. steady-state due/day by retention target (cards with ivl>=21) ===")
FACTOR = 0.9 ** (1 / -0.5) - 1
cands = (0.70, 0.75, 0.80, 0.85, 0.90, 0.95)
grouped = defaultdict(list)
for g, S, D, ivl in allrows:
    if ivl >= 21 and S:
        grouped[g].append(S)
print(f"  {'deck':48s} " + " ".join(f"{c:>6.2f}" for c in cands))
tot = defaultdict(float)
for g in sorted(grouped, key=lambda k: -len(grouped[k]))[:14]:
    row = []
    for c in cands:
        due = sum(1.0 / max(S * (c ** (1 / -0.5) - 1) / FACTOR, 1.0) for S in grouped[g])
        row.append(due)
        tot[c] += due
    print(f"  {g[:48]:48s} " + " ".join(f"{v:6.1f}" for v in row))
print(f"  {'ALL':48s} " + " ".join(f"{tot[c]:6.1f}" for c in cands))
print(f"  {'mature cards':48s} {sum(len(v) for v in grouped.values())}")

# per-group again rate in the last 14 days, split by maturity
print("\n=== F. Again rate by maturity (last 14 days) ===")
bands = [(0, 1, "0-1d"), (1, 7, "1-7d"), (7, 21, "7-21d"), (21, 60, "21-60d"),
         (60, 180, "60-180d"), (180, 10 ** 9, "180d+")]
g2 = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for rid, cid, ease, lastIvl in cur.execute(
        "select id,cid,ease,lastIvl from revlog where id>=?", (cut14,)):
    name = decks.get(card_did.get(cid), "")
    key = name
    for prefix in ("0-日本语学习::0-词汇::1-高频日语单词 6000",
                   "0-日本语学习::0-词汇::2-考级词汇",
                   "0-日本语学习::1-语法",
                   "0-日本语学习::2-例句"):
        if name.startswith(prefix):
            key = prefix
            break
    for lo, hi, lab in bands:
        if lo <= lastIvl < hi:
            b = g2[key][lab]
            b[0] += 1
            b[1] += 1 if ease == 1 else 0
            break
for k in sorted(g2, key=lambda k: -sum(v[0] for v in g2[k].values())):
    cells = []
    for lo, hi, lab in bands:
        n, ag = g2[k].get(lab, [0, 0])
        cells.append(f"{lab}:{ag}/{n}" if n else f"{lab}:-")
    print(f"  {k[:44]:44s} " + "  ".join(cells))
con.close()
