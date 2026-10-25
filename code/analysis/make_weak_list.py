# -*- coding: utf-8 -*-
"""把 weak_words_2d.json 汇总成「单词 —— 简释」清单。"""
import json, os, re, sys
from collections import OrderedDict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

P = os.path.join(WSP.DATA_WEAK, "weak_words_2d.json")
data = json.load(open(P, encoding="utf-8"))

FIX = {"長引く": "拖延、拖长（时间）",
       "義理": "义理、人情、道义（社会义务）",
       "ひも": "绳子；鞋带",
       "画面": "屏幕；画面",
       "伸びる": "生长、增长、伸长、长高"}

def short(mean, n=44):
    m = (mean or "").strip()
    m = re.sub(r"\s*/\s*", " / ", m)
    parts = [p.strip() for p in m.split("/") if p.strip()]
    m = parts[0] if parts else m
    m = m.replace(" /", "")
    return m[:n]

vocab, gram = [], []
for x in data:
    (vocab if ("eggrolls" in x["model"] or "Japanese Vocabulary" in x["model"]) else gram).append(x)

# merge duplicate words
merged = OrderedDict()
for x in vocab:
    k = x["word"]
    if k in merged:
        m = merged[k]
        m["again"] += x["again"]; m["hard"] += x["hard"]
        m["read"] = m["read"] or x["read"]
        if len(x["mean"]) > len(m["mean"]):
            m["mean"] = x["mean"]
    else:
        merged[k] = dict(x)

items = sorted(merged.values(), key=lambda x: (-(x["again"] * 2 + x["hard"]), -x["again"], x["word"]))

def line(x):
    rd = f"（{x['read']}）" if x["read"] and x["read"] != x["word"] else ""
    mean = FIX.get(x["word"], short(x["mean"]))
    return f"{x['word']}{rd} —— {mean}"

t1 = [x for x in items if x["again"] >= 2]
t2 = [x for x in items if x["again"] == 1]
t3 = [x for x in items if x["again"] == 0]

out = []
out.append("| 单词 | 简释 |")
out.append("| --- | --- |")
for x in items:
    rd = f"（{x['read']}）" if x["read"] and x["read"] != x["word"] else ""
    out.append(f"| {x['word']}{rd} | {FIX.get(x['word'], short(x['mean']))} |")

print(f"去重后单词数 = {len(items)}  (t1={len(t1)} t2={len(t2)} t3={len(t3)})", file=sys.stderr)
print(f"原始卡片 = {len(data)}  词汇卡 = {len(vocab)}  语法/其他 = {len(gram)}", file=sys.stderr)

lines = []
lines.append(f"# 近两天不熟练的单词（{len(items)} 个）\n")
lines.append("统计范围：2026-09-30 00:00 ～ 2026-10-01 08:15 的复习记录；")
lines.append("筛选条件：这两天里被评过「重来」或「困难」的词汇卡。\n")

for title, grp in (("A. 反复答错（≥2 次「重来」）", t1),
                   ("B. 答错 1 次", t2),
                   ("C. 只标了「困难」", t3)):
    lines.append(f"\n## {title} —— {len(grp)} 个\n")
    for x in grp:
        lines.append("- " + line(x))

gseen = OrderedDict()
for x in gram:
    if "どんなとき" in x["model"]:
        gseen.setdefault(x["word"], x["mean"])
lines.append(f"\n## 附：语法点 —— {len(gseen)} 个\n")
for w, m in gseen.items():
    lines.append(f"- {w} —— {short(m, 40)}")

OUT = os.path.join(WSP.REPORTS, "弱词清单_近两天.md")
open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("wrote " + OUT, file=sys.stderr)
