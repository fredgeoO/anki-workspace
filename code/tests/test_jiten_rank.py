# -*- coding: utf-8 -*-
"""回归测试：`freq_external.lookup_rank`（按 tag 回填 JitenAnimeRank 的查表核心）

挡两件事：
1. 2026-10-21 修的 bug：`index.get()` 返回 `(rank, 原词形)` 元组，`--tag` 路径拿它去
   `'%06d' %` 会 TypeError（这条路以前一次都没跑通过）。
2. 旧字体回退：Jiten 词表只收新字体，`剝げる` 必须落到 `剥げる` 的 52906，而不是查不到。

跑法（不碰 Anki、不读 data/）：
  & $PY code\tests\test_jiten_rank.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'analysis', 'vocab_cover'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio  # noqa: E402
import freq_external as FE  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


# 和 load_index 同形的索引：归一化键 -> (rank, 原始词形)（键由 norm_word 归一化）
_RAW = {
    'なす': (3476, 'なす'),
    '宿': (4471, '宿'),
    '剥げる': (52906, '剥げる'),
    'はげる': (45767, 'はげる'),
    '禿げる': (82686, '禿げる'),
    '妙': (1181, '妙'),
    'パーマ': (26863, 'パーマ'),
}
INDEX = {FE.norm_word(k): v for k, v in _RAW.items()}


def test_lookup():
    check('普通汉字词查得到', FE.lookup_rank(INDEX, '宿') == 4471, FE.lookup_rank(INDEX, '宿'))
    check('假名词查得到', FE.lookup_rank(INDEX, 'なす') == 3476)
    check('片假名按平假名键命中', FE.lookup_rank(INDEX, 'パーマ') == 26863)
    check('查不到返回 0', FE.lookup_rank(INDEX, '存在しない語') == 0)
    check('空串返回 0', FE.lookup_rank(INDEX, '') == 0)


def test_kyujitai():
    check('旧字体 剝げる -> 剥げる(52906)', FE.lookup_rank(INDEX, '剝げる') == 52906,
          FE.lookup_rank(INDEX, '剝げる'))
    check('不打旧字体补丁的词不受影响',
          FE.lookup_rank(INDEX, '禿げる') == 82686)


def test_format():
    # 这是 --tag 路径的历史 bug：取到元组直接 %06d 会 TypeError
    val = '%06d' % FE.lookup_rank(INDEX, '妙')
    check('补零 6 位: 1181 -> 001181', val == '001181', val)
    check('补零后文本序 == 数值序',
          '%06d' % 1181 < '%06d' % 3476 < '%06d' % 52906,
          ['%06d' % 1181, '%06d' % 3476, '%06d' % 52906])


def test_primary_form():
    check('卡组注音写法取汉字部分', FE.primary_form('石鹸[けん]') == '石鹸',
          FE.primary_form('石鹸[けん]'))
    check('接尾辞去装饰', FE.norm_word('〜さん') == 'さん', FE.norm_word('〜さん'))


def test_derive_field_values():
    """--tag / --models 共用的推导：词字段按类型取、补零、查不到写 no_rank。"""
    notes = [
        {'noteId': 1, 'modelName': 'Japanese Vocabulary',
         'fields': {'Word': {'value': '宿'}}},
        {'noteId': 2, 'modelName': 'eggrolls-JLPT10k-v3.5',
         'fields': {'VocabKanji': {'value': 'なす'}}},
        {'noteId': 3, 'modelName': 'Japanese Vocabulary',
         'fields': {'Word': {'value': '存在しない語'}}},
        {'noteId': 4, 'modelName': 'Japanese Vocabulary',
         'fields': {'Word': {'value': ''}, 'Sentence': {'value': '宿'}}},
        {'noteId': 5, 'modelName': 'Other',
         'fields': {'Sentence': {'value': 'x'}, 'Expression': {'value': '妙'}}},
    ]
    want, words, skipped = FE.derive_field_values(notes, INDEX, '999999')
    check('词字段按笔记类型取（Word / VocabKanji）',
          want.get(1) == '004471' and want.get(2) == '003476', want)
    check('未知类型按 WORD_FIELDS 顺序回退（Expression）', want.get(5) == '001181', want)
    check('词表查不到写 no_rank', want.get(3) == '999999', want)
    check('无词字段的笔记被跳过', 4 not in want and skipped == 1, (want, skipped))
    check('words 只记查到词的笔记', set(words) == {1, 2, 3, 5}, words)
    check('no_rank 可改', FE.derive_field_values(notes[:3], INDEX, '000000')[0][3] == '000000')


def test_expand_models():
    check('vocab 展开成两个词汇笔记类型',
          FE._expand_models(['vocab']) == list(FE.VOCAB_MODELS),
          FE._expand_models(['vocab']))
    check('显式类型名原样保留', FE._expand_models(['Basic']) == ['Basic'])
    check('去空去重', FE._expand_models(['Basic', '', 'Basic', ' vocab '])
          == ['Basic', 'Japanese Vocabulary', 'eggrolls-JLPT10k-v3.5'],
          FE._expand_models(['Basic', '', 'Basic', ' vocab ']))


def main():
    for fn in (test_lookup, test_kyujitai, test_format, test_primary_form,
               test_derive_field_values, test_expand_models):
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
