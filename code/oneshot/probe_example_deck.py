"""一次性：2-例句（对白例句）卡组的逐卡轨迹，用来看「重复是不是真的在提升速度」。

输出：
  A. 卡组概况 + 每张卡的复习次数分布
  B. 同一张卡第 1 / 2 / 3 / 4+ 次复习的耗时与 Again 率（同一批卡，纵向对比）
  C. 控制音频长度（只取 3–7 秒）后的纵向对比
  D. 句子/音频复用检查：同句是否多卡、同一 mp3 是否被多卡引用、一句挂几个音频
"""
import os
import re
import sqlite3
from collections import defaultdict
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

WS = r"<工作区根>"
DB = os.path.join(WS, r"data\snapshots\live\collection.anki2")
MEDIA = os.path.join(os.environ["APPDATA"], "Anki2", "账户 1", "collection.media")
SND = re.compile(r"\[sound:([^\]]+)\]")
DECK = "0-日本语学习::2-例句"

con = sqlite3.connect(DB)
con.create_collation("unicase", lambda a, b: (a > b) - (a < b))
cur = con.cursor()


def txt(v):
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)


def med(v):
    v = sorted(v)
    return v[len(v) // 2] if v else 0.0


decks = {did: txt(n).replace("\x1f", "::") for did, n in cur.execute("select id,name from decks")}
did = [d for d, n in decks.items() if n == DECK][0]
cards = list(cur.execute(
    "select id, nid, ivl, type, reps, lapses, data from cards where did=?", (did,)))
print("deck:", DECK, "did:", did)
print(f"cards={len(cards)}  new={sum(1 for c in cards if c[3] == 0)}  "
      f"review={sum(1 for c in cards if c[3] == 2)}  "
      f"mature(ivl>=21)={sum(1 for c in cards if c[2] >= 21)}")
fsrs = [c for c in cards if c[6] and '"s"' in c[6]]
if fsrs:
    print("FSRS 参数存在的卡:", len(fsrs))

print("\n=== A. 每张卡的复习次数分布 ===")
h = defaultdict(int)
for c in cards:
    h[min(c[4], 12)] += 1
for k in sorted(h):
    print(f"  {k:2d}{'+' if k == 12 else ' '} 次: {h[k]:4d} 张")

print("\n=== B. 同一张卡第 N 次复习（含学习步与复习）===")
times = defaultdict(list)
agains = defaultdict(int)
tot = defaultdict(int)
for cid, *_ in cards:
    for i, (rid, ease, t) in enumerate(
            cur.execute("select id,ease,time from revlog where cid=? order by id", (cid,)), start=1):
        k = min(i, 5)
        tot[k] += 1
        if t <= 300_000:
            times[k].append(t / 1000.0)
        agains[k] += 1 if ease == 1 else 0
print(f"  {'第N次':>6s} {'n':>5s} {'中位':>7s} {'均值':>7s} {'Again%':>8s}")
for k in sorted(tot):
    v = times[k]
    print(f"  {k:>6d} {tot[k]:5d} {med(v):7.1f} {sum(v)/max(len(v), 1):7.1f} "
          f"{agains[k]/max(tot[k], 1)*100:7.1f}%")

# ---- field ordinals ---------------------------------------------------------
card_nid = {c[0]: c[1] for c in cards}
nids = set(card_nid.values())
mid = list(cur.execute("select mid from notes where id=?", (next(iter(nids)),)))[0][0]
fnames = {o: txt(n) for o, n in cur.execute("select ord,name from fields where ntid=?", (mid,))}
o_sent = next(o for o, n in fnames.items() if n == "Sentence")
o_aud = next(o for o, n in fnames.items() if n == "Sentence Audio")
print(f"\n（笔记类型 {mid}：Sentence=字段{o_sent}, Sentence Audio=字段{o_aud}）")


def dur(f):
    p = os.path.join(MEDIA, f)
    try:
        size = os.path.getsize(p)
        head = open(p, "rb").read(16384)
        off = 0
        if head[:3] == b"ID3":
            off = 10 + (((head[6] & 0x7F) << 21) | ((head[7] & 0x7F) << 14) |
                        ((head[8] & 0x7F) << 7) | (head[9] & 0x7F))
        br = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        for i in range(off, min(len(head) - 4, off + 8192)):
            if head[i] == 0xFF and (head[i + 1] & 0xE0) == 0xE0:
                if ((head[i + 1] >> 1) & 3) == 1 and ((head[i + 2] >> 4) & 0xF) not in (0, 15):
                    return max((size - off) * 8.0 / (br[(head[i + 2] >> 4) & 0xF] * 1000), 0.0)
    except Exception:
        return None
    return None


note_parts = {}
audio_first = {}
multi_audio = 0
for nid, flds in cur.execute("select id, flds from notes"):
    if nid not in nids:
        continue
    parts = (flds or "").split("\x1f")
    note_parts[nid] = parts
    fs = SND.findall(parts[o_aud]) if len(parts) > o_aud else []
    if len(fs) > 1:
        multi_audio += 1
    audio_first[nid] = fs[0] if fs else None
print(f"  一句挂多个音频文件的笔记：{multi_audio} / {len(note_parts)}")

print("\n=== C. 控制音频长度（只取 3–7 秒的卡）后的纵向对比 ===")
bands = defaultdict(list)
for cid, *_ in cards:
    nid = card_nid[cid]
    a = dur(audio_first[nid]) if audio_first.get(nid) else None
    if a is None or not (3 <= a <= 7):
        continue
    for i, (rid, ease, t) in enumerate(
            cur.execute("select id,ease,time from revlog where cid=? order by id", (cid,)), start=1):
        if t > 300_000:
            continue
        k = 1 if i == 1 else (2 if i == 2 else 3)
        bands[k].append((cid, t / 1000.0))
print(f"  {'第N次':>6s} {'卡数':>5s} {'组中位':>8s} {'该组各卡中位的中位':>20s}")
for k in sorted(bands):
    per_card = defaultdict(list)
    for cid, t in bands[k]:
        per_card[cid].append(t)
    print(f"  {k:>6d} {len(per_card):5d} {med([t for _c, t in bands[k]]):8.1f} "
          f"{med([med(v) for v in per_card.values()]):20.1f}")

print("\n=== D. 复用检查 ===")
sent = defaultdict(list)
files = defaultdict(list)
for nid, parts in note_parts.items():
    s = re.sub(r"<[^>]+>", "", parts[o_sent]).strip()
    sent[s].append(nid)
    for f in SND.findall(parts[o_aud]):
        files[f].append(nid)
dup_sent = {k: v for k, v in sent.items() if len(v) > 1}
dup_file = {k: v for k, v in files.items() if len(v) > 1}
print(f"  笔记 {len(note_parts)} 条，唯一句子 {len(sent)} 句，重复句子 {len(dup_sent)} 组")
for k, v in list(dup_sent.items())[:5]:
    print(f"     x{len(v)}: {k[:70]}")
print(f"  唯一音频 {len(files)} 个，被多张卡引用 {len(dup_file)} 个")
for k, v in list(dup_file.items())[:5]:
    print(f"     x{len(v)}: {k}")
con.close()
