#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""跨作品词汇覆盖实验 —— 「N 部作品各挖前 3 集」vs「1 部作品挖满 12 集」

问题
----
每部作品只挖前 3 集，其余集数靠泛听，能不能比「同一部作品挖满 12 集」
覆盖到更多**库里没有的词**？

口径
----
只看字幕里出现、而库里（考级词汇 10,609 + core6000）没有的词形。
用两种口径各算一遍，结论应一致：
  loose  句中连续汉字串 ≥2 或假名串 ≥3，未收录即算候选（会把长复合词拆开，偏多）
  strict 同上，但再用**跨集频次**洗一遍：跨作品出现 ≥3 次的判为通用词/机械碎片，剔除
         （剩下的多为作品特有词与低频词）

覆盖度用「不同词形数」计，同一词无论在几集里出现只算一次。

用法
----
  python cross_show_curve.py --show "ARIA The ANIMATION" --show "Heike Monogatari" ...
  python cross_show_curve.py --k 3 --out data/evidence/cross_show_curve.csv
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'common'))
sys.path.insert(0, os.path.join(_HERE, '..', 'execution'))
import paths as WSP      # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

KAN = re.compile(r'[\u4e00-\u9fff\u3005]{2,}')
KANA = re.compile(r'[\u3041-\u309f\u30a0-\u30ff\u30fc]{3,}')
PARENS = re.compile(r'[（(][^）)]*[）)]')
BRACE = re.compile(r'\{[^}]*\}')
TIME = re.compile(r'^\d+$')


def parse_srt(path):
    with open(path, 'rb') as f:
        raw = f.read()
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    text = raw.decode('utf-8', errors='replace')
    for chunk in re.split(r'\n[ \t]*\n', text.replace('\r\n', '\n').strip('\n')):
        lines = chunk.split('\n')
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
        yield ' / '.join(lines[2:])


def cand_words(text, known):
    """句中所有「连续汉字串 ≥2」与「连续假名串 ≥3」的词形。

    注意**不能**预先剔掉词表里已有的词：词表收录的是词典形，字幕里会以活用形/
    复合词出现，而不同作品的切片不同（`王女殿下` 在一部里被切成 `王女`+`殿下`、
    在另一部里只切出 `殿下`），预先剔除会让跨作品重叠率虚高到 100%。
    统一取全词形，再用「出现在几部作品里」在中性口径下剔除通用词。
    """
    t = PARENS.sub('', BRACE.sub('', text))
    out = set()
    for rx in (KAN, KANA):
        for m in rx.finditer(t):
            out.add(m.group(0))
    return out


def load_known():
    p = os.path.join(WSP.DATA, 'evidence', 'subtitle_index.json')
    with open(p, encoding='utf-8') as f:
        d = json.load(f)
    return set(d['canonical']) | set(d['variant2c'])


def eps_of(show):
    d = os.path.join(WSP.ROOT, 'subtitles', show)
    fs = sorted(f for f in os.listdir(d) if f.lower().endswith('.srt'))
    # 挡住 OP/ED/预告之类的非正片字幕：文件名里带 OP/ED/NC/Menu 的不要
    skip = re.compile(r'(?i)\b(nc)?(op|ed|pv|menu|preview)\b')
    return [os.path.join(d, f) for f in fs if not skip.search(os.path.splitext(f)[0])]


def main():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--show', action='append', required=True)
    ap.add_argument('--k', type=int, default=3, help='每部挖前 K 集')
    ap.add_argument('--common-min', type=int, default=3, help='跨作品出现≥N次判为通用词')
    ap.add_argument('--min-shows', type=int, default=3,
                    help='出现在 ≥N 部作品里的词形算通用词，从分析中剔除（N=作品数则全留）')
    ap.add_argument('--out')
    a = ap.parse_args()

    known = load_known()
    per_show = {}       # show -> [每个字幕文件的词形集合]
    for s in a.show:
        files = eps_of(s)
        # 每个字幕文件 = 一集：把该文件所有块的词形并成一个集合
        per_show[s] = [set().union(*[cand_words(t, known) for t in parse_srt(p)]) or set()
                       for p in files]
        print('%-46s %2d 集' % (s, len(per_show[s])))

    # 通用词剔除：跨作品都出现的词形（剧本语域不同、但这些词在哪都有 → 不是作品特有词汇）
    shows_of = Counter()
    for s, eps in per_show.items():
        for w in set().union(*eps) if eps else set():
            shows_of[w] += 1
    generic = {w for w, n in shows_of.items() if n >= a.min_shows}
    print('出现在 ≥%d 部作品里的通用词形 %d 个 → 从曲线中剔除'
          % (a.min_shows, len(generic)))
    if generic:
        per_show = {s: [e - generic for e in eps] for s, eps in per_show.items()}

    def coverage(pick):
        ws = set()
        for s, i in pick:
            ws |= per_show[s][i]
        return ws

    def report(title, pick):
        ws = coverage(pick)
        print('  %-50s %5d 词' % (title, len(ws)))
        return ws

    print('\n=== 各方案覆盖的词形数（已剔通用词）')
    results = {}
    # 方案 A：同一部作品挖满全部集数
    A = {s: report('A 单作品挖满 %d 集：%s' % (len(per_show[s]), _short(s)),
                   [(s, i) for i in range(len(per_show[s]))]) for s in a.show}
    # 方案 B：每部作品只挖前 K 集
    B = {s: report('B 每部挖前 %d 集：%s' % (a.k, _short(s)),
                   [(s, i) for i in range(min(a.k, len(per_show[s])))]) for s in a.show}
    # 方案 C：全部作品的前 K 集并集
    C = report('C 全部 %d 部作品的前 %d 集（并集）' % (len(a.show), a.k),
               [(s, i) for s in a.show for i in range(min(a.k, len(per_show[s])))])
    results = {'A': A, 'B': B, 'C': C}

    # 关键对比：按「读过多少集」对齐的累计覆盖曲线
    print('\n=== 同样读过 N 集时的累计覆盖')
    order_single = sorted(a.show, key=lambda s: -len(per_show[s]))[0]

    def curve(pick):
        ws, out = set(), []
        for s, i in pick:
            ws |= per_show[s][i]
            out.append(len(ws))
        return out

    cs = curve([(order_single, i) for i in range(len(per_show[order_single]))])
    rr = [(s, i) for i in range(max(len(v) for v in per_show.values())) for s in a.show
          if i < len(per_show[s])]
    cr = curve(rr)
    print('  单作品《%s》顺序挖  vs  跨 %d 部轮流挖（每部第 i 集）'
          % (_short(order_single), len(a.show)))
    print('  %-8s %-16s %-16s %s' % ('读过集数', '单作品累计', '跨作品累计', '跨作品增益'))
    for n in (3, 6, 9, 12, 18, 24, 36, 52):
        if n > len(cr):
            break
        b = cs[n - 1] if n <= len(cs) else cs[-1]
        print('  %-10d %-18d %-18d %+.0f%%'
              % (n, b, cr[n - 1], 100 * (cr[n - 1] - b) / max(1, b)))

    print('\n=== 各作品前 %d 集各自的独有贡献' % a.k)
    for s in a.show:
        b = B[s]
        print('  %-38s %4d 词，其中 %4d 词(%2.0f%%) 是别的作品前 %d 集**没有**的'
              % (_short(s), len(b), len(b - (C - b)),
                 100 * len(b - (C - b)) / max(1, len(b)), a.k))
    print('  并集 %d 词' % len(C))

    if a.out:
        with open(a.out, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(['方案', '对象', '覆盖词数'])
            for s, ws in A.items():
                w.writerow(['A 单作品挖满', s, len(ws)])
            for s, ws in B.items():
                w.writerow(['B 每部前 %d 集' % a.k, s, len(ws)])
            w.writerow(['C 全部作品前 %d 集（并集）' % a.k, '并集', len(C)])
            for n in (3, 6, 9, 12, 18, 24, 36, 52):
                if n <= len(cr):
                    w.writerow(['曲线·单作品', '读过%d集' % n, cs[n - 1] if n <= len(cs) else cs[-1]])
                    w.writerow(['曲线·跨作品', '读过%d集' % n, cr[n - 1]])
        print('\n→ %s' % a.out)


def _short(s):
    return s if len(s) <= 34 else s[:31] + '…'


def _common_words(per_show, min_shows):
    """跨作品都出现、且次数够多的词 → 通用词/机械碎片。"""
    c = Counter()
    for s, eps in per_show.items():
        for w in set().union(*eps) if eps else set():
            c[w] += 1
    return {w for w, n in c.items() if n >= min_shows}


if __name__ == '__main__':
    main()
