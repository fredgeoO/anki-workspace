#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""字幕前置筛选（制作 Anki 卡牌用）

把「阶段一 triage」的判据提前到**字幕层**执行：只保留值得做成例句卡的片段，
其余（音效/音乐、纯语气词、残句、上下文依赖、无学习点、重复）在入库前就删掉，
这样 ABS Player 导卡与 triage 的人工量都跟着降下来。

保留下来的片段做两件事：
  1) 同一句话被字幕切开的相邻条目**合并**成一条（时间码取首条开始→末条结束），
     这样导出的卡不会拿到半句话；
  2) 块内混进来的**纯语气词行**（别人插的一声「うん」「ハッ」）剔除。

产物：
  - 筛选后的 SRT：编号重排，时间码沿用原值，日文文本逐字保留
  - keep_list.md / drop_candidates.md / verdict.csv：判定证据（命名与阶段一一致）

用法：
  python filter_subtitle.py probe --src "<原始 srt>"
  python filter_subtitle.py apply --plan "<plan.json>"
"""

import argparse
import csv
import json
import os
import re
import sys
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

TIME_RE = re.compile(r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})")

# 丢弃分类
C_SFX = "音效/舞台指示"
C_INTERJ = "语气词/感叹"
C_FRAG = "残句"
C_CTX = "上下文依赖"
C_TRIVIAL = "无学习点"
C_DUP = "重复"


# ---------------------------------------------------------------- 读写

def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    newline = "\r\n" if b"\r\n" in raw else "\n"
    # 编码判定走唯一实现；这里保持原来的严格语义（不是 UTF-8 就报错，不静默替换）
    return textio.decode(raw, encodings=("utf-8",), errors="strict")[0], bom, newline


def parse_srt(text):
    """按空行切块，返回 [{idx, time, lines}]。序号按文件里写的值，不用位置。"""
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = []
    for chunk in re.split(r"\n[ \t]*\n", norm.strip("\n")):
        lines = chunk.split("\n")
        while lines and lines[-1].strip() == "":
            lines.pop()
        if not lines:
            continue
        if len(lines) < 3:
            raise ValueError("块太短，无法解析：%r" % chunk[:60])
        if not re.match(r"^\d+$", lines[0].strip()):
            raise ValueError("块首不是序号：%r" % lines[0])
        if "-->" not in lines[1]:
            raise ValueError("第二行不是时间码：%r" % lines[1])
        blocks.append({
            "idx": int(lines[0].strip()),
            "time": lines[1].strip(),
            "lines": lines[2:],
        })
    return blocks


def split_time(t):
    m = TIME_RE.search(t)
    if not m:
        raise ValueError("时间码解析失败：%r" % t)
    return m.group(1), m.group(2)


# ---------------------------------------------------------------- 分类（仅用于弃用报告）

INTERJ_KANA = re.compile(
    r"^(ん|うん|あっ|あ|ああ|あー|はっ|はあ|はぁ|ふん|ふう|ふぅ|へえ|おお|おー|まあ|あら|えっ|ええ|え|なっ|ぬっ|"
    r"うっ|うう|おっ|おおっ|はは|ふふ|うふ|けけ|わい|よし|こら|これ|ほら|そら|だあ|むん|ぐぬ|んん|フフ|ハハ|ウフ|"
    r"アハ|フハ|フッ|ハッ|ホッ|おや|おと|おとう|んー)+$"
)


def categorize(lines, dup=False):
    """给被丢弃的条目一个粗略归类，供人扫读。"""
    if dup:
        return C_DUP
    joined = " ".join(lines)
    core = re.sub(r"\{[^}]*\}", "", joined)                 # 去 {\an8} 之类
    no_paren = re.sub(r"（[^）]*）", "", core).strip()        # 去（说话人/音效）标记
    # 全是括号内容 → 音效 / 舞台指示
    if no_paren == "" and "（" in core:
        return C_SFX
    if "♪" in core and len(no_paren) <= 2:
        return C_SFX
    # 纯假名且极短 → 语气词
    bare = re.sub(r"[\s…、。！？!?っー～♪・]", "", no_paren)
    if bare and len(bare) <= 5 and not re.search(r"[一-龥]", bare) and INTERJ_KANA.match(bare):
        return C_INTERJ
    if no_paren and len(no_paren) <= 6 and not re.search(r"[一-龥]", no_paren):
        return C_INTERJ
    # 结尾停在接续处 → 残句
    tail = re.sub(r"[\s…。！？!?]", "", no_paren)
    if tail.endswith(("て", "で", "が", "を", "に", "は", "の", "と", "も", "けど", "のに", "って", "から", "ので", "たり", "ながら")):
        return C_FRAG
    if "…" in no_paren:
        return C_FRAG
    if "？" in core or "?" in core:
        return C_CTX
    return C_TRIVIAL


# ---------------------------------------------------------------- 生成

def build_blocks(plan, by_idx):
    drop_lines = {(int(a), int(b)) for a, b in plan.get("drop_lines", [])}
    out = []
    for n, g in enumerate(plan["groups"], 1):
        ents = [int(x) for x in g["entries"]]
        for e in ents:
            if e not in by_idx:
                raise ValueError("计划里的序号 %d 在原字幕里不存在" % e)
        start, _ = split_time(by_idx[ents[0]]["time"])
        _, end = split_time(by_idx[ents[-1]]["time"])
        lines = []
        for e in ents:
            for li, line in enumerate(by_idx[e]["lines"]):
                if (e, li) in drop_lines:
                    continue
                lines.append(line)
        out.append({"n": n, "start": start, "end": end, "lines": lines,
                    "src": ents, "reason": g.get("reason", "")})
    return out, drop_lines


def render_srt(blocks, newline, bom):
    lines = []
    for b in blocks:
        lines.append(str(b["n"]))
        lines.append("%s --> %s" % (b["start"], b["end"]))
        lines.extend(b["lines"])
        lines.append("")                      # 块间空行（SRT 规范）
    while lines and lines[-1] == "":
        lines.pop()
    text = newline.join(lines) + newline
    return ("\ufeff" if bom else "") + text


def write_reports(plan, blocks, blocks_all, drop_lines, outdir, verdict_rows):
    used = set()
    for b in blocks:
        used.update(b["src"])

    os.makedirs(outdir, exist_ok=True)

    # keep_list.md
    kept = ["# 保留清单（%d 条）" % len(blocks), "",
            "判定维度：**历史名词/官职/地名** · **古文（古典语法与古称）** · **生僻/低频字词** · **惯用搭配** · **复杂长句**。",
            "同时要求：句子完整、脱离剧情上下文也能读懂；只有满足任一条才保留。", ""]
    for b in blocks:
        kept.append("- `%s` — %s → %s | %s" % (
            " / ".join(x.strip() for x in b["lines"]).replace("|", "｜"),
            b["start"], b["end"], b["reason"]))
    kept.append("")
    with open(os.path.join(outdir, "keep_list.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(kept))

    # drop_candidates.md
    groups = {}
    for r in verdict_rows:
        if r["verdict"] == "KEEP":
            continue
        groups.setdefault(r["reason"], []).append(r)
    order = [C_SFX, C_INTERJ, C_FRAG, C_CTX, C_TRIVIAL, C_DUP]
    doc = ["# 待弃候选（%d 条）" % sum(len(v) for v in groups.values()), "",
           "按分类列出。若发现判据漏掉的好句子，把它的序号加回 plan.json 的 `groups` 里重跑 `apply` 即可。", ""]
    for cat in order:
        rows = groups.get(cat)
        if not rows:
            continue
        doc.append("## %s（%d 条）" % (cat, len(rows)))
        doc.append("")
        for r in rows:
            doc.append("- `%s` — #%s" % (r["text"].replace("|", "｜"), r["idx"]))
        doc.append("")
    with open(os.path.join(outdir, "drop_candidates.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(doc))

    # verdict.csv
    with open(os.path.join(outdir, "verdict.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["idx", "verdict", "reason", "start", "text"])
        w.writeheader()
        for r in verdict_rows:
            w.writerow(r)


def main():
    # Windows 控制台默认 GBK，日文/♪ 会打印失败；统一走 UTF-8，编码不了就替换
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("probe", help="只读体检：编码/换行/块数")
    p1.add_argument("--src", required=True)

    p2 = sub.add_parser("apply", help="按计划生成筛选后的字幕与判定证据")
    p2.add_argument("--plan", required=True)

    p3 = sub.add_parser("verify", help="回读产物，逐块比对（块数/序号/时间码/逐字文本）")
    p3.add_argument("--plan", required=True)

    args = ap.parse_args()

    if args.cmd == "verify":
        with open(args.plan, "r", encoding="utf-8") as f:
            plan = json.load(f)
        src_text, _, _ = read_text(plan["source"])
        by_idx = {b["idx"]: b for b in parse_srt(src_text)}
        expected, _ = build_blocks(plan, by_idx)
        out_text, _, _ = read_text(plan["output"])
        got = parse_srt(out_text)          # 能解析出来本身就校验了「块间空行 + 序号连续」
        problems = []
        if len(got) != len(expected):
            problems.append("块数 %d ≠ 计划应有 %d" % (len(got), len(expected)))
        for e, g in zip(expected, got):
            if g["idx"] != e["n"]:
                problems.append("块 #%s 的序号应为 %d" % (g["idx"], e["n"]))
            if g["time"] != "%s --> %s" % (e["start"], e["end"]):
                problems.append("块 #%d 时间码不符：%s" % (e["n"], g["time"]))
            if g["lines"] != e["lines"]:
                problems.append("块 #%d 文本不符" % e["n"])
        if problems:
            print("发现 %d 处问题：" % len(problems))
            for p in problems[:20]:
                print("   " + p)
            sys.exit(1)
        print("回读 %d 块：序号、时间码、文本逐字一致 ✅" % len(got))
        return

    if args.cmd == "probe":
        text, bom, newline = read_text(args.src)
        blocks = parse_srt(text)
        print("文件：%s" % args.src)
        print("字节：%d   BOM：%s   换行：%s" % (os.path.getsize(args.src), bom, repr(newline)))
        print("块数：%d   序号范围：%d–%d" % (len(blocks), blocks[0]["idx"], blocks[-1]["idx"]))
        print("首块：%s | %s" % (blocks[0]["time"], " / ".join(blocks[0]["lines"])))
        print("末块：%s | %s" % (blocks[-1]["time"], " / ".join(blocks[-1]["lines"])))
        return

    with open(args.plan, "r", encoding="utf-8") as f:
        plan = json.load(f)

    src = plan["source"]
    text, bom, newline = read_text(src)
    blocks_all = parse_srt(text)
    by_idx = {b["idx"]: b for b in blocks_all}

    blocks, drop_lines = build_blocks(plan, by_idx)
    srt = render_srt(blocks, newline, bom)

    out_srt = plan["output"]
    os.makedirs(os.path.dirname(out_srt), exist_ok=True)
    with open(out_srt, "w", encoding="utf-8", newline="") as f:
        f.write(srt)

    # 判定证据
    used = {}
    for b in blocks:
        for e in b["src"]:
            used[e] = b
    verdict_rows = []
    for b in blocks_all:
        i = b["idx"]
        txt = " / ".join(b["lines"])
        if i in used:
            g = used[i]
            reason = g["reason"]
            # 合并组里与前一条完全同文的（同一句被重复切块）单独标注，避免读报告时误会
            if (len(g["src"]) > 1 and i != g["src"][0]
                    and by_idx[i]["lines"] == by_idx[g["src"][0]]["lines"]):
                reason = "重复（并入 #%d）" % g["n"]
            verdict_rows.append({"idx": i, "verdict": "KEEP",
                                 "reason": reason, "start": g["start"], "text": txt})
        else:
            dup = any(i in grp["src"] and i != grp["src"][0] for grp in blocks
                      if len(grp["src"]) > 1)
            verdict_rows.append({"idx": i, "verdict": "DROP",
                                 "reason": categorize(b["lines"], dup), "start": split_time(b["time"])[0],
                                 "text": txt})
    verdict_rows.sort(key=lambda r: r["idx"])

    outdir = plan.get("evidence_dir", os.path.dirname(args.plan))
    write_reports(plan, blocks, blocks_all, drop_lines, outdir, verdict_rows)

    kept_rows = [r for r in verdict_rows if r["verdict"] == "KEEP"]
    drop_rows = [r for r in verdict_rows if r["verdict"] == "DROP"]
    print("原字幕 %d 块 → 保留 %d 个片段（覆盖原 %d 块），弃用 %d 块"
          % (len(blocks_all), len(blocks), len(kept_rows), len(drop_rows)))
    print("输出字幕：%s" % out_srt)
    print("判定证据：%s" % outdir)
    from collections import Counter
    for cat, n in Counter(r["reason"] for r in drop_rows).most_common():
        print("   弃用·%s：%d" % (cat, n))


if __name__ == "__main__":
    main()
