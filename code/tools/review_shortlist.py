#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""判弃块「复核短名单」生成器 —— 把本地/弱模型的第一遍筛选变得**可廉价复核**。

问题
----
`filter_subtitle.py` 的 keep/drop 决策是**不可逆**的：被判弃的句子永远不会变成卡，
所以漏掉一条好句子是"看不见的错误"。本集（平家物語 S01E02）的实测：
本地代理判弃 176 块，人工逐条看要花很多 token，而其中绝大多数确实该弃。

做法
----
用 `pipeline.classify()` 的**同一套判据**（单词 / 语法 / 惯用 / 长句 / 新汉字 + 查重）
反向扫一遍判弃块，只把"命中了判据"的挑出来（本集 176 → 39）。再把已知的**机械误报**
自动降级，让真正值得看的那几条排在最前面：

  - 命中只来自说话人标记 / 音效括号（`（祇王）ハッ` 里的「祇」）→ 先去括号再判，直接消失
  - **子串而非词**（`盛ん`←清盛、`苦労`←気苦労）：命中位置紧邻汉字、且"邻字+词"不在词表里
  - 与已保留块重复 / 批内重复
  - 残句（结尾停在 て・のに・けど… 或带省略号）

于是复核面从「309 块」缩到「一屏就能看完的十几条」，强模型只需过这一份。

用法
----
  # 只读，产出短名单（默认写到 data/pipeline/review_shortlist.md）
  python review_shortlist.py --verdict data/evidence/heike_s1e02/verdict.csv
  python review_shortlist.py --verdict ... --out -      # 打到屏幕上

  # 需要先有 pipeline.py prepare 生成的判据缓存
  python review_shortlist.py --verdict ... --cache data/pipeline/gen/cache.json

配合 `check_ruby.py` 一起用，就是「本地模型跑量 + 机械闸门 + 强模型只审短名单」的分工。
"""
import argparse
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'execution'))
import paths as WSP      # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
import pipeline as P     # noqa: E402  判据的唯一来源

PARENS = re.compile(r'[（(][^）)]*[）)]')
ANN = re.compile(r'([\u4e00-\u9fff\u3005]+)[（(][\u3041-\u3096\u30a0-\u30ff\u30fc]+[）)]')
KANJI = re.compile(r'[\u4e00-\u9fff]')
FRAG_TAIL = ('て', 'で', 'が', 'を', 'に', 'は', 'の', 'と', 'も', 'けど', 'のに', 'って',
             'から', 'ので', 'たり', 'ながら', 'れば', 'し')


def clean(text):
    """去掉字幕注音与括号内容 —— 让判据只看"句子本体"。"""
    s = ANN.sub(r'\1', text)
    s = PARENS.sub('', s)
    return s.strip()


def substring_suspect(word, text, vocab):
    """命中位置紧邻汉字、且「邻字+词」不在词表里 → 很可能是更长词的一部分。"""
    for m in re.finditer(re.escape(word), text):
        i, j = m.start(), m.end()
        before = text[i - 1] if i > 0 else ''
        after = text[j] if j < len(text) else ''
        if before and KANJI.match(before) and (before + word) not in vocab:
            return before + word
        if after and KANJI.match(after) and (word + after) not in vocab:
            return word + after
    return ''


def is_fragment(text):
    t = re.sub(r'[\s…。！？!?、]', '', text)
    return '…' in text or t.endswith(FRAG_TAIL)


def main():
    ap = argparse.ArgumentParser(description='判弃块复核短名单生成器')
    ap.add_argument('--verdict', required=True, help='filter_subtitle.py 产出的 verdict.csv')
    ap.add_argument('--cache', default=os.path.join(WSP.DATA_PIPELINE, 'gen', 'cache.json'),
                    help='pipeline.py prepare 的判据缓存')
    ap.add_argument('--out', default=os.path.join(WSP.DATA_PIPELINE, 'review_shortlist.md'),
                    help='输出 markdown（- 表示打到屏幕）')
    a = ap.parse_args()

    cache = json.load(open(a.cache, encoding='utf-8'))
    vocab = set(cache['word_lv'])
    rows = list(csv.DictReader(open(a.verdict, encoding='utf-8')))
    drops = [r for r in rows if r['verdict'] == 'DROP']
    if not drops:
        raise SystemExit('%s 里没有 DROP 行' % a.verdict)

    cards = [{'noteId': -(i + 1), 'sentence': clean(r['text'])} for i, r in enumerate(drops)]
    res = P.classify(cards, cache)
    variants = P.build_variants(cache['word_lv'])

    # 维度权重：单词/惯用最值钱，新汉字最弱（专有名词里也会冒出「新汉字」）
    WEIGHT = {'单词': 4, '惯用': 4, '语法': 3, '长句': 1, '新汉字': 1}

    def weight(dims):
        return sum(WEIGHT.get(d, 1) for d in dims.split('+') if d)

    real, noise = [], []
    for r, row in zip(res, drops):
        if not r['dims']:
            continue                      # 判据都不命中 → 与本工具无关
        body = clean(row['text'])
        why, notes = [], []
        if r['dup']:
            why.append(r['dup'])
        # 命中的是词干/活用形而不是词典形时，标出来 —— 这类最容易是误匹配
        for w in [x.split('(')[0] for x in re.split(r';', r['new_words']) if x]:
            if w in body:
                continue              # 词典形本身就在句子里，不必提示
            for v in sorted(variants.get(w, []), key=len, reverse=True):
                if v != w and v in body:
                    notes.append('命中的是「%s」，词典形是「%s」——请确认句中确实是这个词' % (v, w))
                    break
        sub = ''
        for w in [x.split('(')[0] for x in re.split(r';', r['new_words']) if x]:
            if w:
                s = substring_suspect(w, body, vocab)
                if s:
                    sub = s
                    break
        if sub:
            why.append('疑似子串：`%s` 是更长词的一部分' % sub)
        if is_fragment(body):
            why.append('残句')
        if r['dims'] == '新汉字' and notes == [] and not why:
            notes.append('命中只来自「汉字没在词表里」——人名/地名/专有名词也会这样，句子本身可能没有学习点')
        item = {'idx': row['idx'], 'text': row['text'], 'dims': r['dims'],
                'words': r['new_words'], 'grammar': r['new_grammar'],
                'idioms': r['idioms'], 'kanji': r['new_kanji'],
                'noise': why, 'notes': notes}
        (noise if why else real).append(item)

    real.sort(key=lambda x: (-weight(x['dims']), -len(x['text'])))
    noise.sort(key=lambda x: (-weight(x['dims']), -len(x['text'])))

    L = []
    L.append('# 判弃块复核短名单（%d 条命中判据 / 共 %d 条判弃）\n' % (len(real) + len(noise), len(drops)))
    L.append('> 由 `code/tools/review_shortlist.py` 用 `pipeline.classify` 的同一套判据反向扫出。')
    L.append('> **先看「值得复核」，看完就可以停**；「已自动降级」那一节是已知的机械误报模式，扫一眼即可。\n')
    L.append('## 值得复核（%d 条）\n' % len(real))
    for x in real:
        L.append('- `#%s` %s' % (x['idx'], x['text'].replace('\n', ' ')))
        det = []
        if x['words']:
            det.append('词：' + x['words'])
        if x['grammar']:
            det.append('语法：' + x['grammar'])
        if x['idioms']:
            det.append('惯用：' + x['idioms'])
        if x['kanji']:
            det.append('新汉字：' + x['kanji'])
        L.append('  - [%s] %s' % (x['dims'], '　'.join(det)))
        for n in x['notes']:
            L.append('  - ⚑ %s' % n)
    L.append('')
    L.append('## 已自动降级（%d 条，机械误报模式）\n' % len(noise))
    for x in noise:
        L.append('- `#%s` %s 　→ %s' % (x['idx'], x['text'].replace('\n', ' '), '；'.join(x['noise'])))
    text = '\n'.join(L) + '\n'

    if a.out == '-':
        print(text)
    else:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        open(a.out, 'w', encoding='utf-8').write(text)
        print('判弃 %d 条 → 命中判据 %d 条（值得复核 %d / 已降级 %d）'
              % (len(drops), len(real) + len(noise), len(real), len(noise)))
        print('已写出：%s' % a.out)


if __name__ == '__main__':
    main()
