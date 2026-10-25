# -*- coding: utf-8 -*-
"""独立复核子代理产出：数量/顺序/word 对应、非法字符、ruby 配对、以及
规范第 6 条「a_note 里日语汉字必须标 ruby」——check_mine.py 对这最后一条只做软性检查。
不写库。"""
import json
import os
import re
import sys
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))   # paths.py / check_cards.py
import check_cards as C  # noqa: E402
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

GEN = os.path.join(WSP.DATA_VOCAB, 'gen_mine')

KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
CJK_PUNCT = '：；，。、「」『』（）？！…—'

problems = []
for b in range(1, 5):
    inp = json.load(open(os.path.join(GEN, 'input_%02d.json' % b), encoding='utf-8'))
    out = json.load(open(os.path.join(GEN, 'output_%02d.json' % b), encoding='utf-8'))
    print('批次 %02d: 输入 %d / 输出 %d' % (b, len(inp), len(out)))
    if len(inp) != len(out):
        problems.append('批次%d 数量不一致' % b)
    for i, (a, c) in enumerate(zip(inp, out)):
        if unicodedata.normalize('NFKC', a['word']) != unicodedata.normalize('NFKC', c['word']):
            # 允许补全词典形，但必须"同源"：原残差是新词的子串
            if a['word'] not in c['word']:
                problems.append('批次%d #%d word 不对应: 输入 %r -> 输出 %r'
                                % (b, i, a['word'], c['word']))
        for key in ('reading', 'pos', 'meaning', 'word'):
            v = c.get(key) or ''
            if '<' in v or '>' in v:
                problems.append('批次%d %s 的 %s 含标签' % (b, c['word'], key))
        a_note = c.get('a_note') or ''
        if not c.get('include'):
            continue
        # ruby / rt 配对
        if a_note.count('<ruby>') != a_note.count('</ruby>') or a_note.count('<rt>') != a_note.count('</rt>'):
            problems.append('批次%d %s ruby 不配对' % (b, c['word']))
        # 非白名单标签
        for m in re.finditer(r'<\s*/?\s*([a-zA-Z0-9]+)', a_note):
            if m.group(1).lower() not in C.WHITELIST:
                problems.append('批次%d %s 非白名单标签 <%s>' % (b, c['word'], m.group(1)))
        # ★ 关键：<ruby> 之外的汉字，剔除中文字符后应当为空
        outside = C.outside_ruby(a_note)
        # 去掉中文标点与空白后，看还剩什么汉字
        left = [ch for ch in outside if KANJI.match(ch)]
        if left:
            # 中文解释里的汉字是合法的；无法自动区分中日，只能列出供人工看
            print('    [需人工看] %s 的 a_note 在 ruby 外有汉字 %d 个：%s'
                  % (c['word'], len(left), ''.join(left)[:60]))
        # 四段要求
        for sec in ('中文翻译', '核心词汇', '语法要点'):
            if '<b>%s：</b>' % sec not in a_note:
                problems.append('批次%d %s 缺段落 %s' % (b, c['word'], sec))

print()
if problems:
    print('★ 发现 %d 个问题：' % len(problems))
    for p in problems:
        print('   ', p)
else:
    print('★ 结构复核：无问题（数量/顺序/word 对应、标签白名单、ruby 配对、三段齐全）')
