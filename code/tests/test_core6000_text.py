# -*- coding: utf-8 -*-
"""回归测试：core6000 补例句②的纯渲染（core6000_text.py，**不连网、不碰 Anki**）。

跑法::

    & $PY code\\tests\\test_core6000_text.py

挡四件事：

1. `pos_cn`：卡上 `Part of Speech` 是英文，② 必须按 ① 的中文口径写
   （认不出的原样返回，不许变成空 / 默认值）；
2. `ruby_word`：只给汉字注音，纯假名 / 无读音不加 `<ruby>`；
3. `gloss_lines`：目标词那一行优先用模型给的「新句义项」，模型没给才回退卡上的
   `Meaning` / `Part of Speech`；目标词只出现一次，其余词行格式统一；
4. 这组函数**只在 `core6000_text` 实现一份**，`core6000_example` 只是 import
   （不是又抄了一遍），且模块里不出现 Anki —— 纯渲染不许悄悄长出写库能力。
"""
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'execution'))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))
sys.path.insert(0, os.path.join(_WS, 'code', 'tools'))
sys.path.insert(0, os.path.join(_WS, 'data', 'pylibs'))

import textio                   # noqa: E402  UTF-8 stdio（textio audit 要求）
import core6000_text as CT      # noqa: E402
import core6000_example as CE   # noqa: E402

FAIL = []
TAG = '<ruby>漢字<rt>かんじ</rt></ruby>'


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def gloss(w, r='', pos='', mean=''):
    return {'w': w, 'r': r, 'pos': pos, 'mean': mean}


def test_pos_cn():
    check("noun → 名词", CT.pos_cn('noun') == '名词', CT.pos_cn('noun'))
    check("Adjective 大小写不敏感 → い形容词", CT.pos_cn('Adjective') == 'い形容词',
          CT.pos_cn('Adjective'))
    check("带空白 ' noun ' → 名词", CT.pos_cn(' noun ') == '名词', CT.pos_cn(' noun '))
    check('adjectival noun → な形容词', CT.pos_cn('adjectival noun') == 'な形容词',
          CT.pos_cn('adjectival noun'))
    check('认不出就原样返回', CT.pos_cn('動詞') == '動詞', CT.pos_cn('動詞'))
    check('空串 → 空串（不塞默认值）', CT.pos_cn('') == '', CT.pos_cn(''))
    check('None 不炸', CT.pos_cn(None) == '', CT.pos_cn(None))


def test_ruby_word():
    check('汉字注音', CT.ruby_word('漢字', 'かんじ') == TAG, CT.ruby_word('漢字', 'かんじ'))
    check('纯假名不注音', CT.ruby_word('かな', 'かな') == 'かな', CT.ruby_word('かな', 'かな'))
    check('无读音原样', CT.ruby_word('漢字', '') == '漢字', CT.ruby_word('漢字', ''))
    check('去空白', CT.ruby_word(' 漢字 ', ' かんじ ') == TAG,
          CT.ruby_word(' 漢字 ', ' かんじ '))
    check('空串', CT.ruby_word('', 'かんじ') == '', CT.ruby_word('', 'かんじ'))


def test_gloss_lines():
    lines = CT.gloss_lines('適当', 'てきとう', '适当；随便',
                           [gloss('適当', 'てきとう', 'Adjective', '此处是「随便」的意思')],
                           pos='Adjective')
    check('模型给的义项优先', lines == ['<ruby>適当<rt>てきとう</rt></ruby>'
                                        '（い形容词）：此处是「随便」的意思'], lines)

    lines = CT.gloss_lines('適当', 'てきとう', '适当；随便',
                           [gloss('微妙', 'びみょう', 'Adjective', '微妙')],
                           pos='Adjective')
    check('模型没给目标词 → 回退卡上 Meaning/词性',
          lines[0] == '<ruby>適当<rt>てきとう</rt></ruby>（い形容词）：适当；随便', lines)
    check('其它词单独成行', lines[1] == '<ruby>微妙<rt>びみょう</rt></ruby>（い形容词）：微妙',
          lines)

    lines = CT.gloss_lines('かな', 'かな', '假名', [
        gloss('かな', 'かな', '', ''),
        gloss('漢字', 'かんじ', 'nonexistent-pos', '汉字'),
    ])
    check('目标词是假名 → 不加 ruby、词性未知写 —',
          lines[0] == 'かな（—）：假名', lines)
    check('目标词只出现一次', len(lines) == 2, lines)
    check('未知词性原样写进括号',
          lines[1] == '<ruby>漢字<rt>かんじ</rt></ruby>（nonexistent-pos）：汉字', lines)

    lines = CT.gloss_lines('適当', 'てきとう', '适当', [
        gloss('てきとう', '', 'Adjective', '此处泛指'),
        gloss('適当', 'てきとう', 'Adjective', '重复的同一目标词'),
    ])
    check('读音命中目标词也算目标；重复仍只一行', len(lines) == 1, lines)

    lines = CT.gloss_lines('無', '', '没有', [])
    check('没有 gloss 也要给出目标词行', lines == ['無（—）：没有'], lines)


def test_single_implementation():
    check('core6000_example 的 ruby_word 就是 core6000_text 的',
          CE.ruby_word is CT.ruby_word, '')
    check('core6000_example 的 gloss_lines 就是 core6000_text 的',
          CE.gloss_lines is CT.gloss_lines, '')
    check('core6000_example 的 pos_cn 就是 core6000_text 的',
          CE.pos_cn is CT.pos_cn, '')
    src = inspect.getsource(CE)
    check('core6000_example 从 core6000_text import（不是又抄一遍）',
          'from core6000_text import' in src, '')
    check('core6000_example 不再手拼 <ruby>%s<rt>',
          '<ruby>%s<rt>' not in src, '')
    src = inspect.getsource(CT)
    check('纯渲染模块不 import Anki', 'anki_api' not in src and 'AK.' not in src, '')


def main():
    for fn in (test_pos_cn, test_ruby_word, test_gloss_lines,
               test_single_implementation):
        print(fn.__name__)
        fn()
    print()
    if FAIL:
        print('✗ %d 项失败：%s' % (len(FAIL), FAIL))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
