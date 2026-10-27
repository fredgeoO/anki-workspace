# -*- coding: utf-8 -*-
"""回归测试：`today_new_words`（每天挑 N 个生词的纯逻辑）

挡四件事：
1. 排序方向：`JitenAnimeRank` 数字越小越优先（不是越大越优先）。
2. 无排名：空 / 999999 排最后，只在名额没满时补位，不能挤掉有排名的词。
3. 同排名：本段出现次数多的优先；再同则按词形稳定排序。
4. 标签差集：旧集合 → 新集合必须算出「摘除 / 保留 / 新增」，保证总数 ≤ N。

跑法（不碰 Anki、不读 data/）：
  & $PY code\\tests\\test_today_new_words.py
"""
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'tools'))
import textio  # noqa: E402
import today_new_words as TN  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def _e(j):
    return types.SimpleNamespace(jiten=j)


class FakeIndex:
    def __init__(self, mapping):
        self.entries = mapping


def _w(word, occ=1, note=1, card=1):
    return {'word': word, 'occurrences': occ, 'noteId': note, 'cardId': card}


def test_tag_name():
    check('标签就是用户点名的串', TN.TAG == '今天学习生词', TN.TAG)


def test_rank_of():
    idx = FakeIndex({'隙間': [_e(500), _e(120)], '汁': [_e(999999)], '無': []})
    check('同词多卡取最小排名', TN.rank_of('隙間', idx) == 120,
          TN.rank_of('隙間', idx))
    check('999999 视为无排名', TN.rank_of('汁', idx) == TN.UNRANKED,
          TN.rank_of('汁', idx))
    check('没有条目视为无排名', TN.rank_of('無', idx) == TN.UNRANKED,
          TN.rank_of('無', idx))


def test_select_order():
    idx = FakeIndex({})
    words = [_w('低', 1), _w('高', 1), _w('无', 1)]
    idx.entries = {'低': [_e(20)], '高': [_e(900)], '无': [_e(999999)]}
    got = TN.select_words(words, idx, n=3)
    check('数字小 → 排前面', [w['word'] for w in got] == ['低', '高', '无'],
          [w['word'] for w in got])

    got = TN.select_words(words, idx, n=2)
    check('只取前 N 个', [w['word'] for w in got] == ['低', '高'],
          [w['word'] for w in got])
    check('无排名未挤掉有排名', '无' not in [w['word'] for w in got])


def test_unranked_fills_remaining():
    idx = FakeIndex({'无': [_e(999999)]})
    words = [_w('无', 1), _w('有', 1)]
    idx.entries['有'] = [_e(400)]
    got = TN.select_words(words, idx, n=5)
    check('名额没满时无排名补位', [w['word'] for w in got] == ['有', '无'],
          [w['word'] for w in got])
    check('无排名标记保留', got[-1]['jiten'] == TN.UNRANKED, got[-1]['jiten'])


def test_tie_breaks():
    idx = FakeIndex({'甲': [_e(100)], '乙': [_e(100)], '丙': [_e(100)]})
    words = [_w('甲', 2), _w('乙', 9), _w('丙', 2)]
    got = TN.select_words(words, idx, n=3)
    check('同排名按本段次数降序', [w['word'] for w in got] == ['乙', '丙', '甲'],
          [w['word'] for w in got])


def test_diff_ids():
    d = TN.diff_ids([1, 2, 3, 3], [3, 3, 4, 5])
    check('摘除 = 旧 - 新', d['remove'] == [1, 2], d['remove'])
    check('保留 = 交集', d['keep'] == [3], d['keep'])
    check('新增 = 新 - 旧', d['add'] == [4, 5], d['add'])
    check('最终集合去重', d['old'] == [1, 2, 3] and d['new'] == [3, 4, 5], d)

    d = TN.diff_ids([], [])
    check('空集合不炸', d == {'old': [], 'new': [], 'remove': [], 'keep': [],
                              'add': []}, d)


def test_fmt_rank():
    check('无排名显示破折号', TN.fmt_rank(TN.UNRANKED) == '—', TN.fmt_rank(TN.UNRANKED))
    check('有排名原样显示', TN.fmt_rank(120) == '120', TN.fmt_rank(120))


def main():
    for fn in (test_tag_name, test_rank_of, test_select_order,
               test_unranked_fills_remaining, test_tie_breaks,
               test_diff_ids, test_fmt_rank):
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
