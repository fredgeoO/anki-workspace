# -*- coding: utf-8 -*-
"""回归测试：卡组外新词筛选（`vocab_cover/screen.py` + `is_content_token(drop_aux=)`）

挡四件事：
1. **动了 today-new 的候选集**：``is_content_token`` 默认必须仍然放行
   ``動詞-非自立可能``（おく/つく/なれる）——那样 today-new / subtitle-tag 的行为
   才算「一个字节都没变」，只有显式 ``drop_aux=True`` 才挡。
2. **把卡组里的词当成新词**：``1人``（归一形 一人）、``いう``（归一形 言う）这类
   必须按词典形/归一形/表记三个键都查过，否则新词表会凭空多出一堆基础词。
3. **专名混进新词**：``水之江`` 这类固有名詞 必须单独成组，不进候选。
4. **切分碎片/语气词混进新词**：``の`` ``だ`` ``って`` 必须被内容词闸挡掉。

跑法（不碰 Anki、不写库；用假词表，只依赖工作区自带的 Sudachi）：
  & $PY code\\tests\\test_vocab_screen.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'tools'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'analysis', 'vocab_cover'))

import textio                                                  # noqa: E402
import screen as SCR                                          # noqa: E402
import subtitle_new_words as SW                               # noqa: E402
from _norm import norm_word                                    # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


class FakeVocab:
    """只带 ``words``（norm_word 后的键），够 screen.collect 用。"""

    def __init__(self, words):
        self.words = {norm_word(w): {'core': True} for w in words}


def _tok(word):
    ms = SW.tokenize(word)
    return ms[0] if len(ms) == 1 else None


def test_aux_default_unchanged():
    """today-new 用的默认行为不能变。"""
    t = _tok('おく')
    if t is None or t.pos1 != '非自立可能':
        print('  [SKIP] 词典没把 おく 标成 動詞-非自立可能')
        return
    check('默认放行 非自立可能（today-new 不变）', SW.is_content_token(t) is True)
    check('drop_aux=True 才挡', SW.is_content_token(t, drop_aux=True) is False)
    check('普通动词不受影响',
          SW.is_content_token(_tok('食べる'), drop_aux=True) is True)


def test_collect_deck_and_proper():
    vocab = FakeVocab(['言う', '一人', '食べる'])
    sents = ['いう', '1人で食べる', '水之江さんが来た']
    res = SCR.collect(sents, vocab)
    words = {w['word'] for w in res['items']}
    check('卡组里的词不算新词（いう→言う）', 'いう' not in words and '言う' not in words,
          sorted(words))
    check('卡组里的词不算新词（1人→一人）',
          '1人' not in words and '一人' not in words, sorted(words))
    check('固有名詞单独成组', [w for w, _n in res['proper']] == ['水之江'],
          res['proper'])


def test_collect_drops_fragments():
    vocab = FakeVocab([])
    sents = ['これはパイセンのだ', 'パイセンが来た']
    res = SCR.collect(sents, vocab)
    dropped = {w for w, _n in res['dropped']}
    words = {w['word'] for w in res['items']}
    check('内容词闸挡掉 の/だ/これ/は',
          {'の', 'だ', 'これ', 'は'} <= dropped, sorted(dropped))
    check('挡掉的词不会留在候选里', not (dropped & words), sorted(dropped & words))
    check('真内容词留下', 'パイセン' in words, sorted(words))


def test_occurrence_and_order():
    vocab = FakeVocab([])
    res = SCR.collect(['パイセン', 'パイセン', '内申'], vocab)
    rows = res['items']
    check('按出现次数降序', [r['word'] for r in rows] == ['パイセン', '内申'],
          [r['word'] for r in rows])
    check('次数统计正确', rows[0]['occurrences'] == 2, rows[0])
    check('每条都有首次出现的台词', bool(rows[0]['first']['text']), rows[0]['first'])


def test_json_and_render():
    vocab = FakeVocab([])
    res = SCR.collect(['パイセン', '内申'], vocab)
    blob = SCR.to_json(res)
    check('to_json 有 words', len(blob['words']) == 2, blob.get('words'))
    check('未调模型时 ranked_by=occurrences', blob['ranked_by'] == 'occurrences',
          blob.get('ranked_by'))
    txt = SCR.render(res, top=5)
    check('render 带筛选小标题', '卡组外新词' in txt, txt[:40])
    check('render 不抛异常（空候选）', '没有卡组外的内容词' in SCR.render(
        {'items': [], 'dropped': [], 'proper': [], 'non_jp': []}))


def main():
    for fn in (test_aux_default_unchanged, test_collect_deck_and_proper,
               test_collect_drops_fragments, test_occurrence_and_order,
               test_json_and_render):
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
