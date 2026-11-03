# -*- coding: utf-8 -*-
"""回归测试：`<ruby>` 标签的构造只有一个实现（ruby_engine.wrap）。

挡三件事：
1. 标签格式漂移（`<ruby>x<rt>y</rt></ruby>` 的写法/顺序）；
2. 纯假名或无读音被错误注音；
3. today_new / core6000 两处调用点退回手拼标签。

纯离线：不连 Anki、不读 data/。
跑法：& $PY code\\tests\\test_ruby_wrap.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
_EXEC = os.path.join(os.path.dirname(_HERE), 'execution')
for _p in (_EXEC, os.path.join(_EXEC, 'core6000'), os.path.join(_EXEC, 'lesson')):
    sys.path.insert(0, _p)
import textio  # noqa: E402  stdio 唯一入口
import ruby_engine as RE  # noqa: E402
import ruby_text as RT  # noqa: E402
import htmltext as HT  # noqa: E402
import today_new as TN  # noqa: E402
import core6000_example as CE  # noqa: E402

FAIL = []
TAG = '<ruby>漢字<rt>かんじ</rt></ruby>'


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def test_wrap():
    check('wrap 汉字', RE.wrap('漢字', 'かんじ') == TAG, RE.wrap('漢字', 'かんじ'))
    check('wrap 纯假名不注音', RE.wrap('かな', 'かな') == 'かな', RE.wrap('かな', 'かな'))
    check('wrap 无读音原样', RE.wrap('漢字', '') == '漢字', RE.wrap('漢字', ''))
    check('wrap 空串', RE.wrap('', 'かんじ') == '', RE.wrap('', 'かんじ'))


def test_today_new():
    check('to_ruby 汉字记法', TN.to_ruby('漢字[かんじ]') == TAG, TN.to_ruby('漢字[かんじ]'))
    check('to_ruby 纯假名', TN.to_ruby('かな') == 'かな', TN.to_ruby('かな'))
    kept = '<ruby>漢字<rt>かんじ</rt></ruby>'
    check('to_ruby 已有 ruby 原样保留', TN.to_ruby(kept) == kept, TN.to_ruby(kept))


def test_core6000():
    check('ruby_word 汉字', CE.ruby_word('漢字', 'かんじ') == TAG,
          CE.ruby_word('漢字', 'かんじ'))
    check('ruby_word 纯假名', CE.ruby_word('かな', 'かな') == 'かな',
          CE.ruby_word('かな', 'かな'))
    check('ruby_word 无读音', CE.ruby_word('漢字', '') == '漢字',
          CE.ruby_word('漢字', ''))
    check('ruby_word 去空白', CE.ruby_word(' 漢字 ', ' かんじ ') == TAG,
          CE.ruby_word(' 漢字 ', ' かんじ '))


def test_delegates():
    """两个调用点必须真的走 RE.wrap（而不是又手拼了一遍）。"""
    calls = []
    old = RE.wrap
    RE.wrap = lambda *a, **k: calls.append(a) or old(*a, **k)
    try:
        TN.to_ruby('漢字[かんじ]')
        CE.ruby_word('漢字', 'かんじ')
    finally:
        RE.wrap = old
    check('today_new 走 wrap', ('漢字', 'かんじ') in calls, calls)
    check('core6000 走 wrap', ('漢字', 'かんじ') in calls, calls)


def test_ruby_text():
    check('strip_ruby_base', RT.strip_ruby_base('漢字[かんじ]') == '漢字',
          RT.strip_ruby_base('漢字[かんじ]'))
    check('plain_jp', RT.plain_jp('漢字[かんじ]') == '漢字',
          RT.plain_jp('漢字[かんじ]'))
    check('plain_jp 保留已有 ruby',
          RT.plain_jp('<ruby>漢字<rt>かんじ</rt></ruby>')
          == '<ruby>漢字<rt>かんじ</rt></ruby>',
          RT.plain_jp('<ruby>漢字<rt>かんじ</rt></ruby>'))
    check('strip_tags 换行', HT.strip_tags('<b>x</b><br>y') == 'x\ny',
          HT.strip_tags('<b>x</b><br>y'))
    check('today_new 仍导出 to_ruby', TN.to_ruby is RT.to_ruby, '')
    check('today_new 仍导出 KANJI', TN.KANJI is RT.KANJI, '')


def main():
    for fn in (test_wrap, test_today_new, test_core6000, test_ruby_text,
               test_delegates):
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
