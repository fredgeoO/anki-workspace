#!/usr/bin/env python
"""挖句前的查词工具。

用法:
    python check_word.py 時差 義理 さっと
    python check_word.py --file words.txt

输出每个词: core 频率排名 / 所在频率档 / JLPT 等级 / 是否已学 / 已在哪些牌组有卡、
以及一条"该不该挖"的建议。
"""
import os
import re
import sys
import sqlite3
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "collection_snapshot.anki2")
SEP = "\x1f"

# 用真实收藏库时改成 Anki 的路径，并把 Anki 关掉（或仍读只读快照）
if not os.path.exists(DB):
    sys.exit("找不到数据库快照，请先运行 introspect.py 生成 collection_snapshot.anki2")

con = sqlite3.connect(DB)
con.create_collation(
    "unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold())
)
cur = con.cursor()

ntname = {r[0]: r[1] for r in cur.execute("SELECT id, name FROM notetypes")}
decks = {r[0]: r[1].replace(SEP, "::") for r in cur.execute("SELECT id, name FROM decks")}

note_word, note_model = {}, {}
note_decks = collections.defaultdict(set)
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    p = flds.split(SEP)
    note_word[nid] = p[1].strip() if len(p) > 1 else ""
    note_model[nid] = ntname[mid]

studied_note = set()
for nid, did, reps in cur.execute("SELECT nid, did, reps FROM cards"):
    note_decks[nid].add(decks.get(did, ""))
    if reps > 0:
        studied_note.add(nid)

# core 排名 & 档位
rank, band = {}, {}
for nid, mid, flds in cur.execute("SELECT id, mid, flds FROM notes"):
    if ntname[mid] != "Japanese Vocabulary":
        continue
    p = flds.split(SEP)
    if len(p) > 1:
        try:
            rank[p[1].strip()] = int(p[0])
        except ValueError:
            pass

for nid, mid, flds, tags in cur.execute("SELECT id, mid, flds, tags FROM notes"):
    p = flds.split(SEP)
    w = p[1].strip() if len(p) > 1 else ""
    for t in tags.split():
        m = re.match(r"jp-core::(\d)k$", t)
        if m:
            band[w] = int(m.group(1))

JLPT_ORDER = {"N5": 1, "N4": 2, "N3高频": 3, "N3中频": 4, "N3低频": 5,
              "N2高频": 6, "N2中频": 7, "N2低频": 8, "N1高频": 9, "N1中频": 10, "N1低频": 11}
jlpt = {}
for nid, mid, flds, tags in cur.execute("SELECT id, mid, flds, tags FROM notes"):
    if ntname[mid] != "eggrolls-JLPT10k-v3.5":
        continue
    p = flds.split(SEP)
    w = p[1].strip() if len(p) > 1 else ""
    for t in tags.split():
        m = re.match(r"eggrolls-JLPT10k-v3\.5::(?:\d-N\d)(?:::(N\d)(高频|中频|低频))?", t)
        if m and m.group(1):
            jlpt[w] = m.group(1) + m.group(2)

word_notes = collections.defaultdict(list)
for nid, w in note_word.items():
    if w:
        word_notes[w].append(nid)


def deinflect(w):
    """尝试还原辞书形"""
    c = set()
    if len(w) < 2:
        return c
    if w.endswith(("く", "かった", "くて")):
        c.add(re.sub(r"(かった|くて|く)$", "", w) + "い")
    m = re.match(r"^(.*?)(って|て|った|た|んで|んだ|いて|いた|いで|いだ|して|した)$", w)
    if m:
        st = m.group(1)
        for last in "うくぐすつぬむぶる":
            c.add(st + last)
        c.add(st + "する")
    for suf in ("ます", "ません", "ました", "ない", "なかった", "れば", "よう", "たい", "ながら", "ず"):
        if w.endswith(suf) and len(w) > len(suf):
            st = w[: -len(suf)]
            for last in "うくぐすつぬむぶる":
                c.add(st + last)
    if w.endswith(("り", "き", "ぎ", "し", "ち", "に", "み", "び")):
        st = w[:-1]
        for last in "うくぐすつぬむぶる":
            c.add(st + last)
    return {x for x in c if len(x) >= 2 and x != w}


def report(w):
    print(f"\n【{w}】")
    # 先看是不是变形
    if w not in rank and w not in jlpt:
        cands = sorted(x for x in deinflect(w) if x in rank or x in jlpt or x in word_notes)
        if cands:
            print(f"  ⚠ 这看起来是变形，不是辞书形。辞书形应为: {'、'.join(cands)}")
            print(f"  → 建议：**改挖辞书形 {cands[0]}**（否则同一个词会变成互不相连的两张卡）")
            w = cands[0]
            print(f"  （以下按 {w} 继续检查）")

    r = rank.get(w)
    if r:
        print(f"  core 6000 排名 : #{r}   (第 {band.get(w,'?')}k 档)")
    else:
        print(f"  core 6000      : 未收录")
    print(f"  JLPT 分组      : {jlpt.get(w, '不在考级表')}")

    nids = word_notes.get(w, [])
    if not nids:
        print(f"  现有卡片       : 无")
        print(f"  → 建议：**可以挖**（通用词表完全没覆盖）")
        return
    for nid in nids:
        st = "已学" if nid in studied_note else "未学"
        ds = " / ".join(sorted(d for d in note_decks[nid] if d))
        print(f"  现有卡片       : [{st}] {ds}")
    any_studied = any(nid in studied_note for nid in nids)
    if any_studied:
        print(f"  → 建议：**不必挖**（已有卡片且已学，会变成重复劳动）")
    else:
        print(f"  → 建议：**不必挖**（已有卡片待学，等它出现即可；若台词特别好可只做整句卡）")


args = sys.argv[1:]
if not args:
    print(__doc__)
    sys.exit(0)
words = []
i = 0
while i < len(args):
    if args[i] == "--file":
        with open(args[i + 1], encoding="utf-8") as f:
            words += [l.strip() for l in f if l.strip()]
        i += 2
    else:
        words.append(args[i])
        i += 1
for w in words:
    report(w)
con.close()
