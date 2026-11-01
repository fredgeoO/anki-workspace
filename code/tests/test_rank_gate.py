# -*- coding: utf-8 -*-
"""回归测试：`rank_gate`（LLM 精排）+ `today_new_words` 的按序取词接口。

纯离线：不连 Anki、不调模型、不读写 data/。挡这几件事——
1. 模型输出解析：只收表里的 id、去重、保持模型给的顺序、坏形状不炸。
2. 一集一次的口径：编号从 1 开始、用**该集次数**、JAR 缺失显示破折号、例句截断。
3. 缓存指纹：候选或台词一变就要重新问模型（不能拿旧排序充数）。
4. 跨集合并：同一个词在多集排名都好 → 分高；`pick_from_order` 尊重顺序且守名额。
5. 兜底：模型没给出名单时 `rank_groups` 返回空表（由调用方退回公式，不在这里兜）。

跑法（不碰 Anki）：
  & $PY code\\tests\\test_rank_gate.py
"""
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'tools'))
import rank_gate as RG          # noqa: E402
import textio                   # noqa: E402,F401  stdio 统一走 textio（audit R2）
import today_new_words as TN    # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def _item(word, notes=(1,), kind='word', score=0.0, occ=1, eps=1, jar=1000):
    return {'word': word, 'notes': list(notes), 'kind': kind, 'score': score,
            'occurrences': occ, 'episodes': eps, 'jiten': jar, 'reading': 'よみ',
            'pos': '名詞', 'first': {'text': '例文'}}


def test_parse_picks():
    valid = {1: _item('甲'), 2: _item('乙'), 3: _item('丙')}
    obj = {'picks': [{'id': 2, 'why': 'a'}, {'id': 1}, {'id': 2, 'why': 'dup'},
                     {'id': 99, 'why': '自创'}, {'id': 'x'}, 'junk', None]}
    got = RG.parse_picks(obj, valid)
    check('保持模型给的顺序', [it['word'] for it, _ in got] == ['乙', '甲'],
          [it['word'] for it, _ in got])
    check('同一 id 只收一次', len(got) == 2, len(got))
    check('自创 id 丢掉', all(it['word'] in ('甲', '乙') for it, _ in got))
    check('坏输出不炸', RG.parse_picks(None, valid) == []
          and RG.parse_picks({'picks': []}, valid) == []
          and RG.parse_picks({'nope': 1}, valid) == [])


def test_signature():
    a = [_item('甲', occ=2, jar=100)]
    check('同候选集 → 同指纹', RG.signature(a) == RG.signature([_item('甲', occ=2, jar=100)]))
    check('次数变了 → 换指纹', RG.signature(a) != RG.signature([_item('甲', occ=3, jar=100)]))
    check('台词变了 → 换指纹', RG.signature(a, 'あ') != RG.signature(a, 'い'))
    check('排序无关', RG.signature(a + [_item('乙')]) == RG.signature([_item('乙')] + a))


def test_to_inputs():
    it = _item('甲', occ=9, jar=0)
    it['ep_occ'] = 3
    it['first'] = {'text': 'あ' * 80}
    rows, valid = RG.to_inputs([it])
    row = rows[0]
    check('编号从 1 开始', row.startswith('1 / 甲'), row)
    check('优先用该集次数', '3次' in row, row)
    check('无 JAR 显示破折号', 'JAR —' in row, row)
    check('例句被截断', row.endswith('…」') and len(row) < 100, row)
    check('id → item 映射', valid[1] is it)

    rows2, _ = RG.to_inputs([_item('乙', jar=6666)])
    check('有 JAR 原样显示', 'JAR 6666' in rows2[0], rows2[0])

    big = _item('丙', jar=999999)
    rows3, _ = RG.to_inputs([big])
    check('999999 也当无排名', 'JAR —' in rows3[0], rows3[0])


def test_rank_groups_merge():
    """两集各出名单：同一词两集都靠前 → 合并分更高。"""
    a, b, c = _item('甲'), _item('乙'), _item('丙')

    def fake(label, items, text, cfg=None, k=40, use_cache=True, quiet=False):
        by = {it['word']: it for it in items}
        picks = ([by['甲'], by['乙']] if label == 'E1' else [by['甲'], by['丙']])
        return [(it, 'w') for it in picks], {'calls': 1, 'candidates': len(items),
                                             'returned': len(picks), 'secs': 0.1,
                                             'cached': False, 'episode': label}

    orig = RG.rank_episode
    RG.rank_episode = fake
    try:
        groups = [{'label': 'E1', 'text': 't1', 'items': [a, b]},
                  {'label': 'E2', 'text': 't2', 'items': [a, c]}]
        ordered, meta = RG.rank_groups(groups, k=2, use_cache=False)
        words = [it['word'] for it, _w, _s in ordered]
        check('两集都排第一的词合并后最前', words[0] == '甲', words)
        check('只出现一集的词也保留', set(words) == {'甲', '乙', '丙'}, words)
        check('合并计数', meta['episodes'] == 2 and meta['calls'] == 2, meta)
        check('每集明细都在', len(meta['per_episode']) == 2, meta['per_episode'])
        scores = {it['word']: s for it, _w, s in ordered}
        check('多集稳定靠前 → 分更高', scores['甲'] >= scores['乙'], scores)
    finally:
        RG.rank_episode = orig


def test_rank_groups_empty():
    check('没有候选 → 空表不炸', RG.rank_groups([])[0] == [] and
          RG.rank_groups([{'label': 'E1', 'text': '', 'items': []}], use_cache=False)[0] == [])


def test_pick_from_order():
    order = [_item('ん', kind='particle', notes=(1,)),
             _item('甲', notes=(2,)),
             _item('あっ', kind='particle', notes=(3,)),
             _item('乙', notes=(4,)),
             _item('丙', notes=(5,)),
             _item('ほら', kind='particle', notes=())]
    got = TN.pick_from_order(order, 2, particles=1)
    check('按传入顺序取，不重排', [it['word'] for it in got] == ['甲', '乙', 'ん'], 
          [it['word'] for it in got])
    check('语气词只占 particles 个名额', sum(1 for it in got if it['kind'] == 'particle') == 1)
    check('没笔记的词不占名额', 'ほら' not in [it['word'] for it in got])

    none = TN.pick_from_order(order, 3, particles=0)
    check('particles=0 时不取语气词', [it['word'] for it in none] == ['甲', '乙', '丙'],
          [it['word'] for it in none])
    check('候选不足就少取', len(TN.pick_from_order(order[:2], 10, particles=0)) == 1)


def test_group_by_episode():
    items = [_item('甲'), _item('乙')]
    stats = {'甲': {'eps': {'E1', 'E2'}, 'per_ep': {'E1': 3, 'E2': 1}},
             '乙': {'eps': {'E1'}, 'per_ep': {'E1': 2}}}
    orig = TN.SW.load_cues
    TN.SW.load_cues = lambda p: [types.SimpleNamespace(text='あ', index=1, start='0'),
                                 types.SimpleNamespace(text='い', index=2, start='1')]
    try:
        groups = TN.group_by_episode(items, [('E1', 'x.srt'), ('E2', 'y.srt')], stats)
    finally:
        TN.SW.load_cues = orig
    check('每集一组', [g['label'] for g in groups] == ['E1', 'E2'],
          [g['label'] for g in groups])
    e1 = {it['word']: it for it in groups[0]['items']}
    check('只放本集出现过的词', set(e1) == {'甲', '乙'}, set(e1))
    check('次数换成该集次数', e1['甲']['ep_occ'] == 3, e1['甲']['ep_occ'])
    check('整集台词带上', groups[0]['text'] == 'あ\nい', groups[0]['text'])
    check('第二集只带本集候选', [it['word'] for it in groups[1]['items']] == ['甲'],
          [it['word'] for it in groups[1]['items']])
    check('不改动原 item', items[0].get('ep_occ') is None)


def test_report_md_marks_fallback():
    counts = {'episodes': 1, 'candidates': 2, 'ranked_by': 'formula', 'mu': 0.3,
              'lam': 0.3, 'score_top': 3.0, 'score_min': 2.0, 'score_next': None}
    plan = {'old': [], 'keep': [], 'remove': [], 'add': []}
    md = TN._report_md('src', [_item('甲')], [], plan, 1, counts)
    check('公式兜底时报告写明', '公式兜底' in md, md[:120])
    counts2 = dict(counts, ranked_by='llm', rank_calls=3, rank_secs=12.5)
    md2 = TN._report_md('src', [_item('甲')], [], plan, 1, counts2, why_of={'甲': '高频'})
    check('LLM 定序时报告写明', 'LLM 精排' in md2, md2[:120])
    check('模型理由进表', '高频' in md2)


def main():
    for fn in (test_parse_picks, test_signature, test_to_inputs,
               test_rank_groups_merge, test_rank_groups_empty, test_pick_from_order,
               test_group_by_episode, test_report_md_marks_fallback):
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
