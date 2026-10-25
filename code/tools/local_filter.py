#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""字幕筛选 · 本地模型判定（只判灰区，产出 verdict.csv）

配合 `code/tools/prefilter_subtitle.py`：
    规则层   已判掉 NOISE（音效/语气词/应答），KEEP_SAFE（命中强信号且句子完整）默认保留
    本脚本   只判灰区 —— GRAY（命中强信号但句子可疑）/ GRAY_LO（无强信号但不短）/
             GRAY_FRAG（无强信号的短块），必要时也可 --cats keep 抽检 KEEP_SAFE

判据与 `filter_subtitle.py` 一致，额外要求「句子完整、脱离剧情上下文可读」，
并剔除只在本作登场的人名与设定名。

用法
----
  python local_filter.py --ep tensei_oujo_s1e01            # 判本集全部灰区（可重复跑，跳过已判）
  python local_filter.py --ep tensei_oujo_s1e01 --cats GRAY_LO
  python local_filter.py --ep ... --sample-keep 80          # 另抽检 80 条 KEEP_SAFE
  python local_filter.py --ep ... --verdict                # 只打印现有判定分布
"""
import argparse
import csv
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'common'))
sys.path.insert(0, os.path.join(_HERE, '..', 'execution'))
import paths as WSP      # noqa: E402
import textio            # noqa: E402
import local_llm as L    # noqa: E402

SYS = """你是日语学习卡素材的筛选员。用户是中文母语者、日语中级（N3–N2），
正在把动画字幕做成例句卡。你的任务：判断每一条字幕**值不值得做成一张例句卡**。

【保留（keep=1）】满足任一条即可，且句子必须**完整、脱离剧情上下文也能读懂**：
- 生僻或超出 N3 的词汇、四字熟语、惯用搭配
- 复杂长句（含连体修饰、多重从句、书面语结构）
- 值得注意的句型/语法点（不是「ている/こと」这种最基础的）
- 本作的宫廷/贵族语体：お〜になる、〜なさる、〜ですわ/ますわ、〜のじゃ、わたくし、
  貴様、そなた、〜まい、〜ず、〜ぬ 等，以及古语残留

【丢弃（keep=0）】
- 音效/舞台指示（（戦う音）（ため息）♪）、纯语气词/感叹（うん、ハッ、あっ、ふ〜ん）
- 残句：话说一半、被字幕切开的半句（结尾停在 て/が/を/に/けど/って 等，或带省略号…）
- 上下文依赖：只回应上一句（「そうね」「だから言ったろ？」「私も！」

  「はい」「なるほど」「失礼します」）、指名道姓而没有别的信息
- 只在本作登场的人名/设定名，句子本身没有可讲的语言点
- 寒暄套话、日常口水话（おはよう、お疲れっした、頑張って）
- 与同批其它条目几乎重复

【判断要点】
- 「完整」优先于「有生词」：半句即使有生词也判 0。
- 一句话里有**一个**实打实的语言点就判 1；不要因为「感觉简单」就判 0，
  也不要因为「有个别汉字」就判 1。
- 拿不准时判 1（漏掉的句子永远不会变成卡，代价高于多留一句）。

【输出】只输出 JSON 数组，不要解释、不要 markdown 代码块。每个元素：
  {"idx": <整数，原样抄输入>, "keep": 0 或 1, "reason": "<8 字以内的中文理由>"}
必须覆盖输入的每一条 idx，顺序不限。"""


def rows_of(ep):
    p = os.path.join(WSP.EVIDENCE, ep, 'prefilter.csv')
    with open(p, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def verdict_path(ep, tag=''):
    return os.path.join(WSP.EVIDENCE, ep, 'llm_verdict%s.csv' % tag)


def load_done(ep, tag=''):
    p = verdict_path(ep, tag)
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8', newline='') as f:
        return {r['idx']: r for r in csv.DictReader(f)}


def batching(sel, max_items=40, max_chars=3000):
    """按**条数 + 内容字数**双重上限分批。

    实测：一批塞 300+ 条时模型输出会被 max_tokens 截断（只判到一半），
    所以条数是硬约束 —— 40 条/批，输出约 800–1000 tokens，安全。
    中日文按 1 token/字 估，输入侧 3000 字/批。
    """
    out, cur, n = [], [], 0
    for r in sel:
        c = len(r['text']) + 12          # +序号与提示的固定开销
        if cur and (len(cur) >= max_items or n + c > max_chars):
            out.append(cur)
            cur, n = [], 0
        cur.append(r)
        n += c
    if cur:
        out.append(cur)
    return out


def judge(cfg, part, ep, n):
    lines = []
    for r in part:
        hint = ''
        if r['cat'] in ('KEEP_SAFE', 'GRAY') and r.get('why'):
            hint = '   [规则提示：%s]' % r['why']
        lines.append('#%s %s%s' % (r['idx'], r['text'], hint))
    user = ('作品：转生王女与天才令嬢的魔法革命 第%s集（异世界魔法学园/宫廷）\n'
            '以下是第 %d 批共 %d 条字幕：\n\n%s\n\n'
            '按系统提示判定，只输出 JSON 数组。'
            % (ep[-2:], n, len(part), '\n'.join(lines)))
    res = L.chat(cfg, [{'role': 'system', 'content': SYS},
                       {'role': 'user', 'content': user}], quiet=True)
    return res.content


def parse(raw):
    out = {}
    for m in re.finditer(r'\{[^{}]*\}', raw or ''):
        try:
            o = json.loads(m.group(0))
        except Exception:
            continue
        if 'idx' in o and 'keep' in o:
            try:
                out[int(o['idx'])] = (int(o['keep']), str(o.get('reason', ''))[:40])
            except (TypeError, ValueError):
                continue
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--ep', required=True)
    ap.add_argument('--cats', default='GRAY,GRAY_LO,GRAY_FRAG',
                    help='要判的类别，逗号分隔；加 keep 表示 KEEP_SAFE')
    ap.add_argument('--sample-keep', type=int, default=0,
                    help='另从中等长度的 KEEP_SAFE 里抽检 N 条')
    ap.add_argument('--tag', default='', help='判定结果文件后缀（抽检用 _sample）')
    ap.add_argument('--verdict', action='store_true', help='只打印现有判定分布')
    ap.add_argument('--max-batches', type=int, default=0, help='只跑前 N 批（试跑）')
    a = ap.parse_args()

    rows = rows_of(a.ep)
    if a.verdict:
        done = load_done(a.ep, a.tag)
        from collections import Counter
        c = Counter('keep' if v['keep'] == '1' else 'drop' for v in done.values())
        print('%s%s：已判 %d 条 → %s' % (a.ep, a.tag, len(done), dict(c)))
        return

    cats = set(a.cats.split(','))
    sel = [r for r in rows if r['cat'] in cats]
    if a.sample_keep:
        ks = [r for r in rows if r['cat'] == 'KEEP_SAFE']
        ks.sort(key=lambda r: int(r['len']))
        step = max(1, len(ks) // a.sample_keep)
        sel += ks[::step][:a.sample_keep]

    done = load_done(a.ep, a.tag)
    todo = [r for r in sel if r['idx'] not in done]
    parts = batching(todo)
    print('%s：待判 %d 条 / %d 批（已判 %d 条）' % (a.ep, len(todo), len(parts), len(done)))
    if a.max_batches:
        parts = parts[:a.max_batches]

    cfg = L.load_config()
    vp = verdict_path(a.ep, a.tag)
    new = not os.path.exists(vp)
    f = open(vp, 'a', encoding='utf-8', newline='')
    w = csv.writer(f)
    if new:
        w.writerow(['idx', 'keep', 'reason', 'cat', 'text'])
    cats_map = {r['idx']: r for r in rows}
    total = 0
    for i, part in enumerate(parts, 1):
        try:
            raw = judge(cfg, part, a.ep, i)
        except Exception as e:                       # 单批失败不拖垮全局
            print('  批 %d 失败：%s: %s' % (i, type(e).__name__, e))
            continue
        got = parse(raw)
        miss = [r['idx'] for r in part if int(r['idx']) not in got]
        if miss:
            # 输出被截断/漏条：把这一批缩小重试一次（最多 2 轮）
            for attempt in range(2):
                if not miss:
                    break
                retry = [r for r in part if int(r['idx']) in miss]
                print('  批 %d 漏 %d 条 → 拆小重试 %d' % (i, len(miss), attempt + 1))
                for sub in batching(retry, max_items=15, max_chars=1200):
                    try:
                        got.update(parse(judge(cfg, sub, a.ep, i)))
                    except Exception as e:
                        print('    重试失败：%s' % e)
                miss = [r['idx'] for r in part if int(r['idx']) not in got]
        for idx, (keep, reason) in got.items():
            src = cats_map.get(str(idx))
            if src is None:
                continue
            w.writerow([idx, keep, reason, src['cat'], src['text']])
            total += 1
        f.flush()
        print('  批 %d/%d：判 %d/%d 条%s'
              % (i, len(parts), len(got), len(part),
                 ('，漏 %s' % ','.join(map(str, miss[:8]))) if miss else ''))
    f.close()
    print('累计写入 %d 条 → %s' % (total, vp))


if __name__ == '__main__':
    main()
