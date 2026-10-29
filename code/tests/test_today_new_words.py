# -*- coding: utf-8 -*-
"""回归测试：`today_new_words`（每天按本作暴露挑 N 个词的纯逻辑）

2026-10-29 起选词从「A/B/D 分池」改成连续打分：

    S = ln(1+occ) + MU*ln(1+eps) + LAM*ln(JAR_MAX/JAR)

挡七件事：
1. 单调性：次数↑、集数↑、JAR↓ 都让分数↑。
2. 换算：`flip_ratio(lam) == 2**(1/lam)`；次数翻倍带来的分数增量 = LAM*ln(倍数)。
3. 取词：按分数降序取 N，不足不硬凑，同分按词形稳定。
4. 名额按「词」算：一个词名下多张未学笔记全部带出，标签数可多于 N。
5. 「学过」按笔记判断：同词一张已学、一张新卡时，新卡仍在候选里。
6. JAR 门槛：只收 1–30000；999999 / >30000 不进候选。
7. 标签差集：旧集合 → 新集合必须算出「摘除 / 保留 / 新增」。

跑法（不碰 Anki、不读 data/）：
  & $PY code\\tests\\test_today_new_words.py
"""
import math
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


def _e(j=500, nid=1, cid=1, typ=0, queue=0, pos='', reading=''):
    return types.SimpleNamespace(jiten=j, note_id=nid, card_id=cid,
                                 type=typ, queue=queue, reading=reading,
                                 pos=pos, deck='', level='')


class FakeIndex:
    def __init__(self, mapping):
        self.entries = mapping


def _stat(occ=1, eps=1, readings=()):
    return {'occ': occ, 'eps': set(range(eps)), 'first': None, 'examples': [],
            'readings': set(readings)}


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


def test_score_monotonic():
    s = TN.score_of
    check('次数越多分越高', s(10, 3, 2000) > s(5, 3, 2000) > s(2, 3, 2000))
    check('集数越多分越高', s(5, 8, 2000) > s(5, 3, 2000) > s(5, 1, 2000))
    check('JAR 越小分越高', s(5, 3, 300) > s(5, 3, 3000) > s(5, 3, 20000))
    check('三项都相同则分数相同', s(5, 3, 2000) == s(5, 3, 2000))
    check('occ=0 也不炸（log1p）', abs(s(0, 0, 30000) - 0.0) < 1e-9,
          s(0, 0, 30000))


def test_score_parts():
    occ, eps, freq = TN.score_parts(4, 2, 6000, mu=0.3, lam=0.3)
    check('次数项 = ln(1+occ)', abs(occ - math.log(5)) < 1e-9, occ)
    check('集数项 = mu*ln(1+eps)', abs(eps - 0.3 * math.log(3)) < 1e-9, eps)
    check('频率项 = lam*ln(JAR_MAX/JAR)',
          abs(freq - 0.3 * math.log(30000 / 6000)) < 1e-9, freq)
    check('分数 = 三项之和',
          abs(TN.score_of(4, 2, 6000, mu=0.3, lam=0.3) - (occ + eps + freq)) < 1e-9)
    check('JAR 超出上限被夹住', TN.score_parts(1, 1, 99999, lam=0.3)[2] == 0.0,
          TN.score_parts(1, 1, 99999, lam=0.3)[2])
    check('JAR=0 不炸（当上限）', TN.score_parts(1, 1, 0, lam=0.3)[2] == 0.0)


def test_flip_ratio():
    check('lam=0.3 → 2**(1/0.3) ≈ 10.08',
          abs(TN.flip_ratio(0.3) - 2 ** (1 / 0.3)) < 1e-9, TN.flip_ratio(0.3))
    check('lam=1 → 翻倍 ≈ 前移 2 倍', abs(TN.flip_ratio(1.0) - 2.0) < 1e-9)
    check('lam=0 → 无穷（不看 JAR）', TN.flip_ratio(0) == float('inf'))

    lam = 0.3
    k = TN.flip_ratio(lam)
    f1 = TN.score_parts(2, 1, 10000, mu=0, lam=lam)[2]
    f2 = TN.score_parts(2, 1, 1000, mu=0, lam=lam)[2]
    check('JAR 缩小 10 倍 = 加 lam*ln10', abs((f2 - f1) - lam * math.log(10)) < 1e-9,
          '%r vs %r' % (f2 - f1, lam * math.log(10)))
    check('flip_ratio 的定义：lam*ln(k) == ln2',
          abs(lam * math.log(k) - math.log(2)) < 1e-12,
          '%r vs %r' % (lam * math.log(k), math.log(2)))
    # 「次数翻倍 ≡ JAR 前移 k 倍」是 log1p 的渐近等式，大数下才严格
    big1 = TN.score_of(1000, 1, 1000, mu=0, lam=lam)
    big2 = TN.score_of(2000, 1, 1000, mu=0, lam=lam)
    check('次数翻倍（大数下）≈ JAR 前移 k 倍',
          abs((big2 - big1) - lam * math.log(k)) < 1e-3,
          '%r vs %r' % (big2 - big1, lam * math.log(k)))


def test_lam_zero_ignores_jar():
    a = TN.score_of(3, 1, 500, mu=0, lam=0)
    b = TN.score_of(3, 1, 25000, mu=0, lam=0)
    check('lam=0 时 JAR 不影响分数', abs(a - b) < 1e-9, (a, b))


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


def test_drop_phrases_off_by_default():
    """默认不过滤惯用句（おっ / にゃあ 这类词用户要学）。"""
    idx = FakeIndex({'おっ': [_e(pos='惯用句')], '村': [_e(pos='名词')]})
    stats = {w: _stat(3, 2) for w in ('おっ', '村')}
    items, _ = TN.build_candidates(stats, idx)
    check('默认保留惯用句', {it['word'] for it in items} == {'おっ', '村'},
          {it['word'] for it in items})
    items2, skipped2 = TN.build_candidates(stats, idx, drop_phrases=True)
    check('--drop-phrases 才挡掉惯用句', {it['word'] for it in items2} == {'村'},
          {it['word'] for it in items2})
    check('被挡的词有计数', skipped2['phrases'] == ['おっ'], skipped2['phrases'])


def test_candidates_skip_learned_only():
    """整词都学过的词没有未学笔记 → 不进候选。"""
    idx = FakeIndex({'甲': [_e(nid=1, typ=2)], '乙': [_e(nid=2, typ=2), _e(nid=3, typ=0)]})
    stats = {w: _stat(3, 2) for w in ('甲', '乙')}
    items, skipped = TN.build_candidates(stats, idx, max_jar=30000)
    check('全学过的词被排除', [it['word'] for it in items] == ['乙'],
          [it['word'] for it in items])
    check('排除原因记为没有未学笔记', skipped['no_notes'] == ['甲'], skipped['no_notes'])


def test_plan_pick_order():
    idx = FakeIndex({})
    # 次数高但 JAR 很差 vs 次数低但 JAR 极好
    stats = {'多': _stat(8, 1), '准': _stat(2, 2), '中': _stat(4, 2)}
    idx.entries = {'多': [_e(20000)], '准': [_e(300)], '中': [_e(2000)]}
    items, _ = TN.build_candidates(stats, idx, max_jar=30000)
    picked, ranked = TN.plan_pick(items, 3)
    got = [w['word'] for w in picked]
    check('按分数降序', got == [w['word'] for w in ranked], got)
    check('分数最高的排第一', picked[0]['word'] == ranked[0]['word'], picked[0]['word'])
    check('每个候选都带 score', all('score' in it for it in items))


def test_plan_pick_quota():
    idx = FakeIndex({})
    stats = {'a%d' % i: _stat(6, 4) for i in range(2)}
    stats.update({'b%d' % i: _stat(3, 2) for i in range(2)})
    stats.update({'d%d' % i: _stat(2, 2) for i in range(2)})
    idx.entries = {w: [_e(2000)] for w in stats}
    items, _ = TN.build_candidates(stats, idx, max_jar=30000)
    picked, _ = TN.plan_pick(items, 3)
    check('只取 N 个', len(picked) == 3, len(picked))

    picked2, _ = TN.plan_pick(items, 99)
    check('候选不足就少取', len(picked2) == len(items), (len(picked2), len(items)))


def test_pick_top_tie_stable():
    items = [{'word': '丙', 'score': 2.0}, {'word': '甲', 'score': 2.0},
             {'word': '乙', 'score': 3.0}]
    got = [w['word'] for w in TN.pick_top(items, 3)]
    check('同分按词形稳定', got == ['乙', '丙', '甲'], got)
    check('n=0 返回空', TN.pick_top(items, 0) == [])
    check('负数 n 返回空', TN.pick_top(items, -5) == [])


def test_word_quota_notes_more_than_n():
    """N 按词算：词 3 个、笔记 5 张，最终笔记数 > N。"""
    idx = FakeIndex({'甲': [_e(nid=1), _e(nid=2)], '乙': [_e(nid=3)],
                     '丙': [_e(nid=4), _e(nid=5)]})
    stats = {w: _stat(6, 3) for w in ('甲', '乙', '丙')}
    items, _ = TN.build_candidates(stats, idx, max_jar=30000)
    picked, _ = TN.plan_pick(items, 2)
    check('取 2 个词', len(picked) == 2, len(picked))
    check('笔记总数可超过 2', sum(len(w['notes']) for w in picked) > 2,
          sum(len(w['notes']) for w in picked))


def test_reading_gate():
    """`頭` 名下挂着两张卡：あたま（头）/ かしら（首领）。只标读音对得上的那张。"""
    idx = FakeIndex({'頭': [
        _e(nid=1, cid=1, reading='あたま'),
        _e(nid=2, cid=2, reading='かしら'),
    ]})
    stats = {'頭': _stat(5, 3, readings=['あたま'])}
    items, skipped = TN.build_candidates(stats, idx)
    check('只带出读音一致的笔记', items and items[0]['notes'] == [1],
          items[0]['notes'] if items else 'no item')
    check('记录被排掉的读音', items and items[0]['dropped_readings'] == [(2, 'かしら')],
          items[0]['dropped_readings'] if items else '')
    check('字幕读音是 かしら 时反过来', TN.new_note_ids('頭', idx, {'かしら'}) == [2],
          TN.new_note_ids('頭', idx, {'かしら'}))

    stats2 = {'頭': _stat(5, 3, readings=['かしら'])}
    items2, _ = TN.build_candidates(stats2, idx)
    check('换读音换卡', items2 and items2[0]['notes'] == [2], items2 and items2[0]['notes'])

    check('卡片没写读音时放行', TN.reading_ok('', {'あたま'}) is True)
    check('字幕没读音时放行', TN.reading_ok('かしら', set()) is True)
    check('读音相等才放行', TN.reading_ok('アタマ', {'あたま'}) is True,
          TN.reading_ok('アタマ', {'あたま'}))
    check('读音不同不放行', TN.reading_ok('かしら', {'あたま'}) is False)

    idx3 = FakeIndex({'頭': [_e(nid=9, cid=9, reading='かしら')]})
    items3, skipped3 = TN.build_candidates({'頭': _stat(5, 3, readings=['あたま'])}, idx3)
    check('全部笔记读音都不对 → 不进候选', items3 == [], items3)
    check('记为读音对不上而非已学', skipped3['reading'] == ['頭'], skipped3)


def test_pick_with_quota_particles():
    """语气词单独占名额：高分感动词不许把内容词挤掉（2026-10-30 修义项补位的回归）。

    用户口径：语气词每天只学 2 个，其余名额留给内容词。感动词频次极高
    （`ん` 一期 400 次），一旦和内容词同池按分数切，30 个名额全是 `あっ`/`うっ`。
    """
    items = [
        {'word': 'ん', 'score': 9.0, 'kind': 'particle', 'notes': [1]},
        {'word': 'あっ', 'score': 8.0, 'kind': 'particle', 'notes': [2]},
        {'word': 'え', 'score': 7.0, 'kind': 'particle', 'notes': [3]},
        {'word': '村', 'score': 3.5, 'kind': 'word', 'notes': [4]},
        {'word': '反応', 'score': 3.4, 'kind': 'word', 'notes': [5]},
    ]
    picked = TN.pick_with_quota(items, 3, particles=2)
    got = [it['word'] for it in picked]
    check('感动词只占 particles 个名额', got == ['村', '反応', 'ん', 'あっ'], got)
    check('总名额 = n + particles', len(picked) == 4, len(picked))

    none = TN.pick_with_quota(items, 3, particles=0)
    check('particles=0 时一个感动词都不选',
          [it['word'] for it in none] == ['村', '反応'], [it['word'] for it in none])

    with_no_note = [{'word': 'ほら', 'score': 99.0, 'kind': 'particle', 'notes': []}] + items
    req = TN.pick_with_quota(with_no_note, 1, particles=1, require_notes=True)
    check('require_notes 时没笔记的词不占名额',
          [it['word'] for it in req] == ['村', 'ん'], [it['word'] for it in req])
    keep_pending = TN.pick_with_quota(with_no_note, 1, particles=1)
    check('默认保留没笔记的词（待建卡要能显示）',
          [it['word'] for it in keep_pending] == ['村', 'ほら'],
          [it['word'] for it in keep_pending])


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
               test_new_note_ids_per_note, test_score_monotonic, test_score_parts,
               test_flip_ratio, test_lam_zero_ignores_jar, test_jar_gate,
               test_drop_phrases_off_by_default, test_candidates_skip_learned_only,
               test_plan_pick_order, test_plan_pick_quota, test_pick_top_tie_stable,
               test_word_quota_notes_more_than_n, test_reading_gate,
               test_pick_with_quota_particles, test_diff_ids,
               test_fmt_rank):
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
