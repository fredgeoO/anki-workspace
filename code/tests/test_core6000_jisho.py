# -*- coding: utf-8 -*-
"""回归测试：core6000 补例句**新句来自 Jisho** 这几段逻辑（**不连网、不碰 Anki**）。

跑法::

    & $PY code\\tests\\test_core6000_jisho.py

挡的是三类会静默坏掉的地方：

1. `word_written_form`：`思い込む` 的书写骨架是 `思い込`，纯假名词要**关掉**这条偏好；
2. `pick_jisho`：只收「振假名合格 + 含目标词 + 长度进闸门 + 与第一句不像」的候选，
   并且**优先**选写出了目标词汉字的句子（`思い込んでいる` > `思いこんでいた`）；
3. `pin_sentence_source`：模型改写句子时必须被 Jisho 原句覆盖，并留一条
   `sentence_overridden` 警告 —— 否则库里就会出现模型自己编的第 2 句。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'execution'))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))
sys.path.insert(0, os.path.join(_WS, 'code', 'tools'))
sys.path.insert(0, os.path.join(_WS, 'data', 'pylibs'))

import textio                # noqa: E402  UTF-8 stdio（textio audit 要求）
import core6000_example as CX  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def cand(jp, ruby='<ruby>R</ruby>', ok=True, en='', source='Tatoeba'):
    return {'jp': jp, 'en': en, 'source': source, 'url': 'https://jisho.org/x',
            'match': 'exact', 'ruby': ruby, 'ruby_ok': ok, 'ruby_issues': []}


def card(word='思い込む', reading='おもいこむ', first='彼はだまされたと思い込んでいるようです。'):
    return {'id': 1, 'word': word, 'reading': reading,
            'sentences': [{'jp': first, 'cn': '', 'ruby': ''}]}


def with_candidates(cands, why=''):
    """把 jisho_fetch 换成固定候选（不联网）。"""
    def fake(card_arg, args):
        return list(cands), why
    return fake


class Args:
    def __init__(self, **kw):
        self.refresh_jisho = False
        self.jisho_timeout = 30.0
        self.no_dict = False
        self.allow_model_sentence = False
        self.__dict__.update(kw)


def main():
    print('== 1. word_written_form：书写骨架 ==')
    check('思い込む → 思い込', CX.word_written_form('思い込む') == '思い込',
          CX.word_written_form('思い込む'))
    check('適当 → 適当', CX.word_written_form('適当') == '適当', CX.word_written_form('適当'))
    check('逃げ出す → 逃げ出', CX.word_written_form('逃げ出す') == '逃げ出',
          CX.word_written_form('逃げ出す'))
    check('纯假名 あまり → 关掉偏好', CX.word_written_form('あまり') == '',
          CX.word_written_form('あまり'))
    check('空词 → 空', CX.word_written_form('') == '')

    print('== 2. pick_jisho：优先写出目标词汉字的那句 ==')
    orig = CX.jisho_fetch
    try:
        CX.jisho_fetch = with_candidates([
            cand('彼は、彼女が幸せだと思いこんでいた。'),
            cand('彼は自分が病人だと思い込んでいる。'),
        ])
        pick, why = CX.pick_jisho(card(), Args())
        check('选中写出「思い込」的那句',
              pick and pick['jp'] == '彼は自分が病人だと思い込んでいる。', pick)
        check('没理由也返回空 reason', why == '', why)

        print('== 3. pick_jisho：四道闸门 ==')
        CX.jisho_fetch = with_candidates([cand('彼は自分が病人だと思い込んでいる。', ok=False)])
        pick, why = CX.pick_jisho(card(), Args())
        check('ruby_ok=False 不要', pick is None, pick)
        check('理由里写了 ruby', 'ruby' in why, why)

        CX.jisho_fetch = with_candidates([cand('彼はだまされたと思い込んでいるようです。')])
        pick, why = CX.pick_jisho(card(), Args())
        check('与原句相同（相似度超阈值）不要', pick is None, pick)
        check('理由里写了 too-similar', 'too-similar' in why, why)

        CX.jisho_fetch = with_candidates([cand('思い込む。')])
        pick, why = CX.pick_jisho(card(), Args())
        check('太短（<6 字）不要', pick is None, pick)
        check('理由里写了 length', 'length' in why, why)

        CX.jisho_fetch = with_candidates([cand('私は犬が好きだ。')])
        pick, why = CX.pick_jisho(card(), Args())
        check('不含目标词不要', pick is None, pick)
        check('理由里写了 kana-form/no-target',
              'kana-form' in why or 'no-target' in why, why)

        CX.jisho_fetch = with_candidates([], 'Jisho 没有返回例句（0 条或页面结构变了）')
        pick, why = CX.pick_jisho(card(), Args())
        check('零候选 → None + 原样带出原因', pick is None and '0 条' in why, why)

        print('== 4. 快照句也能过：只写假名「こ」的句子在 fallback 里仍可用 ==')
        CX.jisho_fetch = with_candidates([cand('彼は、彼女が幸せだと思いこんでいた。')])
        pick, why = CX.pick_jisho(card(), Args())
        check('没有汉字写法时退而接受假名写法',
              pick and pick['jp'] == '彼は、彼女が幸せだと思いこんでいた。', (pick, why))

        print('== 5. pin_sentence_source：模型改写的句子留不下来 ==')
        entry = {'new_sentence': '彼は自分が病人だと思っている。',
                 'new_sentence_ruby': '<ruby>彼<rt>かれ</rt></ruby>…'}
        target = {'jp': '彼は自分が病人だと思い込んでいる。',
                  'ruby': '<ruby>彼<rt>かれ</rt></ruby>は…', 'en': '', 'source': 'Tatoeba',
                  'url': '', 'match': 'exact'}
        warn = CX.pin_sentence_source(entry, target)
        check('句子被 Jisho 原句覆盖',
              entry['new_sentence'] == target['jp'], entry['new_sentence'])
        check('振假名被 Jisho 值覆盖',
              entry['new_sentence_ruby'] == target['ruby'], entry['new_sentence_ruby'])
        check('记一条 sentence_overridden 警告',
              len(warn) == 1 and warn[0].startswith('sentence_overridden'), warn)

        entry2 = {'new_sentence': target['jp'], 'new_sentence_ruby': target['ruby']}
        warn2 = CX.pin_sentence_source(entry2, target)
        check('照抄时不报警告', warn2 == [], warn2)
        check('没有 pick 时什么都不做',
              CX.pin_sentence_source({}, None) == [])
    finally:
        CX.jisho_fetch = orig

    print()
    if FAIL:
        print('❌ %d 项失败：%s' % (len(FAIL), ' / '.join(FAIL)))
        return 1
    print('✅ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
