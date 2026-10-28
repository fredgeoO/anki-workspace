# -*- coding: utf-8 -*-
"""回归测试：`today_new_words`（每天按本作暴露挑 N 个词的纯逻辑）

挡六件事：
1. 分池门槛：A = 出现≥5 或 跨集≥3；B = JAR≤4000 且 出现≥3；
   D = JAR≤6000 且 出现≥2；其余 E（不取）。
2. 取词顺序：A 填满 → B 补 → D 补，总数不超过 N，**不拿 E 硬凑**。
3. 名额按「词」算：一个词名下多张未学笔记全部带出，标签数可多于 N。
4. 「学过」按笔记判断：同词一张已学、一张新卡时，新卡仍在候选里。
5. JAR 门槛：只收 1–30000；999999 / >30000 不进候选。
6. 标签差集：旧集合 → 新集合必须算出「摘除 / 保留 / 新增」。

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


def _e(j=500, nid=1, cid=1, typ=0, queue=0):
    return types.SimpleNamespace(jiten=j, note_id=nid, card_id=cid,
                                 type=typ, queue=queue, reading='',
                                 pos='', deck='', level='')


class FakeIndex:
    def __init__(self, mapping):
        self.entries = mapping


def _stat(occ=1, eps=1):
    return {'occ': occ, 'eps': set(range(eps)), 'first': None, 'examples': []}


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


def test_note_state():
    check('全为新卡 → new', TN.note_state([_e(typ=0)]) == 'new')
    check('任一卡已学 → learned', TN.note_state([_e(typ=0), _e(typ=2)]) == 'learned',
          TN.note_state([_e(typ=0), _e(typ=2)]))
    check('全部挂起 → suspended', TN.note_state([_e(queue=-1), _e(queue=-1)]) == 'suspended')
    check('埋藏仍算 new', TN.note_state([_e(queue=-3)]) == 'new')


def test_new_note_ids_per_note():
    """同词：一张已学、两张新卡 → 只返回两张新笔记。"""
    idx = FakeIndex({'抱く': [
        _e(nid=10, cid=100, typ=2),
        _e(nid=11, cid=110, typ=0),
        _e(nid=12, cid=120, typ=0),
    ]})
    check('已学笔记被排除、新笔记保留', TN.new_note_ids('抱く', idx) == [11, 12],
          TN.new_note_ids('抱く', idx))


def test_pool_of():
    check('出现≥5 → A', TN.pool_of(5, 1, 30000) == 'A')
    check('跨集≥3 → A', TN.pool_of(1, 3, 30000) == 'A')
    check('JAR≤4000 且 出现≥3 → B', TN.pool_of(3, 2, 4000) == 'B')
    check('JAR>4000 不进 B，落到 D', TN.pool_of(3, 2, 4001) == 'D',
          TN.pool_of(3, 2, 4001))
    check('JAR>6000 且 出现 3 → E', TN.pool_of(3, 2, 6001) == 'E',
          TN.pool_of(3, 2, 6001))
    check('JAR≤6000 且 出现≥2 → D', TN.pool_of(2, 2, 6000) == 'D')
    check('出现 1 次 → E', TN.pool_of(1, 1, 100) == 'E')


def test_jar_gate():
    idx = FakeIndex({'贵': [_e(30001)], '界': [_e(30000)], '无': [_e(999999)],
                     '常': [_e(1000)]})
    stats = {w: _stat(3, 2) for w in ('贵', '界', '无', '常')}
    items, skipped = TN.build_candidates(stats, idx, max_jar=30000)
    words = {it['word'] for it in items}
    check('JAR 30001 排除', '贵' not in words, words)
    check('无排名排除', '无' not in words, words)
    check('JAR 30000 保留', '界' in words, words)
    check('排除清单有计数', set(skipped['jar']) == {'贵', '无'}, skipped['jar'])

    items2, _ = TN.build_candidates(stats, idx, max_jar=0)
    check('max_jar=0 时全收', {it['word'] for it in items2} == {'贵', '界', '无', '常'},
          {it['word'] for it in items2})


def test_candidates_skip_learned_only():
    """整词都学过的词没有未学笔记 → 不进候选。"""
    idx = FakeIndex({'甲': [_e(nid=1, typ=2)], '乙': [_e(nid=2, typ=2), _e(nid=3, typ=0)]})
    stats = {w: _stat(3, 2) for w in ('甲', '乙')}
    items, skipped = TN.build_candidates(stats, idx, max_jar=30000)
    check('全学过的词被排除', [it['word'] for it in items] == ['乙'],
          [it['word'] for it in items])
    check('排除原因记为没有未学笔记', skipped['no_notes'] == ['甲'], skipped['no_notes'])


def test_plan_pools_quota():
    idx = FakeIndex({})
    stats = {'a%d' % i: _stat(6, 4) for i in range(2)}      # A
    stats.update({'b%d' % i: _stat(3, 2) for i in range(2)})  # B
    stats.update({'d%d' % i: _stat(2, 2) for i in range(2)})  # D
    idx.entries = {w: [_e(2000)] for w in stats}
    items, _ = TN.build_candidates(stats, idx, max_jar=30000)
    picked, pools = TN.plan_pools(items, 3)
    check('A 先填满', [w['word'] for w in picked] == ['a0', 'a1', 'b0'],
          [w['word'] for w in picked])
    check('B 池有余量未取', len(pools['B']) == 2, len(pools['B']))


def test_plan_pools_no_e():
    idx = FakeIndex({'e1': [_e(5000)]})
    items, _ = TN.build_candidates({'e1': _stat(1, 1)}, idx, max_jar=30000)
    picked, _ = TN.plan_pools(items, 30)
    check('E 池不凑数', picked == [], picked)


def test_word_quota_notes_more_than_n():
    """N 按词算：词 3 个、笔记 5 张，最终笔记数 > N。"""
    idx = FakeIndex({'甲': [_e(nid=1), _e(nid=2)], '乙': [_e(nid=3)],
                     '丙': [_e(nid=4), _e(nid=5)]})
    stats = {w: _stat(6, 3) for w in ('甲', '乙', '丙')}
    items, _ = TN.build_candidates(stats, idx, max_jar=30000)
    picked, _ = TN.plan_pools(items, 2)
    check('取 2 个词', len(picked) == 2, len(picked))
    check('笔记总数可超过 2', sum(len(w['notes']) for w in picked) > 2,
          sum(len(w['notes']) for w in picked))


def test_pool_key():
    items = [
        {'word': '甲', 'occurrences': 5, 'episodes': 2, 'jiten': 100},   # 10
        {'word': '乙', 'occurrences': 20, 'episodes': 1, 'jiten': 100},  # 20
        {'word': '丙', 'occurrences': 20, 'episodes': 1, 'jiten': 50},   # 20, JAR 小
    ]
    got = sorted(items, key=TN.pool_key)
    check('出现×集数 降序、JAR 升序', [w['word'] for w in got] == ['丙', '乙', '甲'],
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
    for fn in (test_tag_name, test_rank_of, test_note_state,
               test_new_note_ids_per_note, test_pool_of, test_jar_gate,
               test_candidates_skip_learned_only, test_plan_pools_quota,
               test_plan_pools_no_e, test_word_quota_notes_more_than_n,
               test_pool_key, test_diff_ids, test_fmt_rank):
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
