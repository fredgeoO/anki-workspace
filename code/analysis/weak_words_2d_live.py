# -*- coding: utf-8 -*-
"""近两天（昨天0点起）复习中答错/困难的卡片，输出单词 + 简单解释。

取数走 `AK.Snapshot`（issue #10 B3：不再自己 sqlite3.connect）。窗口 = 昨天 0 点起
（`reviewed_rows(days=2)`），与 today_weak 的「近 N 天」口径一致。**默认读 live 收藏的
只读副本**（`live_copy=True`）；位置参数给显式库路径时读该文件（复现历史用）。
离线快照数据源（`_anki_snap`）已退场。
"""
import os, json, re, html, sys, datetime as dt
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
import anki_api as AK  # noqa: E402  唯一 Anki 访问点（这里用 Snapshot 的 live 只读副本）
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

DB = sys.argv[1] if len(sys.argv) > 1 else None   # None → live 收藏的只读副本

now = dt.datetime.now()
start = now.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=1)

with AK.guard():
    snap = (AK.Snapshot.open(path=DB) if DB
            else AK.Snapshot.open(live_copy=True))   # 默认：live 副本，关时即删

    try:
        rows = snap.reviewed_rows(days=2, ease=(1, 2))   # 昨天0点起，重来+困难

        agg = defaultdict(lambda: {"again": 0, "hard": 0, "nid": 0, "mid": 0,
                                   "deck": "", "last": 0})
        for r in rows:
            a = agg[r["cid"]]
            a["again" if r["ease"] == 1 else "hard"] += 1
            a["nid"] = r["nid"]; a["mid"] = r["mid"]; a["deck"] = r["deck"]
            a["last"] = max(a["last"], r["rid"])

        # ⚠ ids=[] 时 cards()/notes() 是「不加 WHERE」= 全表扫，必须先挡住空窗口
        cids = list(agg.keys())
        state = {c["cardId"]: c for c in snap.cards(ids=cids)} if cids else {}

        nids = sorted({a["nid"] for a in agg.values()})
        notes = {}   # noteId -> (模型名, {字段名: 值（按 ord 序）})
        for ch in AK.chunks(nids, 500):
            for n in snap.notes(ids=ch):
                notes[n["noteId"]] = (n["modelName"], n["fields"])
    finally:
        snap.close()

print(f"窗口: {start:%Y-%m-%d %H:%M} → {now:%Y-%m-%d %H:%M}")
print(f"重来/困难 作答记录数 = {len(rows)}")
byday = defaultdict(int)
for r in rows:
    byday[dt.datetime.fromtimestamp(r["rid"] / 1000).strftime("%Y-%m-%d")] += 1
print("按天:", dict(sorted(byday.items())))

def clean(s):
    s = re.sub(r"\[sound:[^\]]*\]", " ", s or "")
    s = re.sub(r"<br\s*/?>", " / ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def extract(model_name, d):
    if model_name == "Japanese Vocabulary":
        return (model_name, clean(d.get("Word", "")) or clean(d.get("Index", "")),
                clean(d.get("Transliteration", "")), clean(d.get("Meaning", "")),
                clean(d.get("Part of Speech", "")))
    if model_name == "eggrolls-JLPT10k-v3.5":
        return (model_name, clean(d.get("VocabKanji", "")) or clean(d.get("VocabFurigana", "")),
                clean(d.get("VocabFurigana", "")), clean(d.get("VocabDefSC", "")),
                clean(d.get("VocabPoS", "")))
    ne = [(k, clean(v)) for k, v in d.items()]
    ne = [(k, v) for k, v in ne if v]
    return (model_name,
            clean(d.get("Card", "")) or (ne[0][1] if ne else "?"),
            clean(d.get("Bracket", "")),
            clean(d.get("MeaningCN", "")) or clean(d.get("MeaningJP", "")) or
            max((v for k, v in ne[1:]), key=len, default=""),
            "")

out = []
for cid, a in agg.items():
    name, word, read, mean, pos = extract(*notes.get(a["nid"], ("?", {})))
    st = state.get(cid, {})
    out.append(dict(cid=cid, again=a["again"], hard=a["hard"], deck=a["deck"],
                    model=name, word=word, read=read, mean=mean, pos=pos,
                    lapses=st.get("lapses", 0), reps=st.get("reps", 0),
                    ivl=st.get("ivl", 0), type=st.get("type", 0), last=a["last"]))

out.sort(key=lambda x: (-x["again"], -x["hard"], x["word"]))
print(f"\n涉及卡片数 = {len(out)}  重来过 = {sum(1 for o in out if o['again'])}\n")

with open(os.path.join(WSP.DATA_WEAK, "weak_words_2d.json"),
          "w", encoding="utf-8") as fh:
    json.dump([{**o, "last": dt.datetime.fromtimestamp(o["last"] / 1000).strftime("%m-%d %H:%M")}
               for o in out], fh, ensure_ascii=False, indent=1)

for o in out:
    print(json.dumps({
        "last": dt.datetime.fromtimestamp(o["last"] / 1000).strftime("%m-%d %H:%M"),
        "again": o["again"], "hard": o["hard"], "lapses": o["lapses"],
        "type": o["type"], "ivl": o["ivl"], "model": o["model"][:12],
        "deck": o["deck"].replace("\x1f", "::"), "word": o["word"][:50],
        "read": o["read"][:30], "pos": o["pos"][:20], "mean": o["mean"][:130],
    }, ensure_ascii=False))
