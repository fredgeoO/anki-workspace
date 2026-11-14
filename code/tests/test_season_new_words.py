# -*- coding: utf-8 -*-
"""回归测试：`season_new_words`（每季生词提取的纯逻辑）

挡六件事：
1. 目录名 → 安全 slug / 默认季标签。
2. 分层判定：Jiten≤12000 → 通用层；12001–24000 且出现≥3 → 作品层；其余池外。
3. 收录规则：通用层先收（本季次数降序 → Jiten 升序），作品层补到上限；
   超过上限截断，**永远不超过 maxWords**。
4. 不足下限时逐级放宽：作品层次数 3→2→1，再放宽 Jiten 上限到 30000；
   放宽过程写进 meta.relaxed。
5. 噪声过滤：只出现 1 次且 Anki 标为惯用句/成句/词的 → 剔；出现≥2 次保留。
6. payload / report 可序列化、两层标题都在。

跑法（不碰 Anki、不读 data/）：
  & $PY code\\tests\\test_season_new_words.py
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'tools'))
import textio  # noqa: E402,F401  UTF-8 stdio（直接跑的脚本必须过 R2）
import season_new_words as SN  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def _it(word, jar, occ, pos='名詞', kind='word', eps=1, notes=(1,)):
    return {
        'word': word, 'kind': kind, 'pos': pos, 'pos0': pos,
        'jiten': jar, 'occurrences': occ, 'episodes': eps,
        'notes': list(notes), 'readings': [], 'score': 0.0,
        'first': {'episode': 'E01', 'index': 1, 'start': '00:01', 'text': word + ' 的例句'},
    }


def test_slug_and_tag():
    check('空格换成下划线', SN.slug_of('subtitles/Sousou no Frieren') == 'Sousou_no_Frieren',
          SN.slug_of('subtitles/Sousou no Frieren'))
    check('默认季标签带前缀',
          SN.default_tag('subtitles/Yuru Camp') == '本季生词::Yuru_Camp',
          SN.default_tag('subtitles/Yuru Camp'))


def test_layer_of():
    it = _it('a', 8000, 1)
    check('Jiten≤12000 → 通用层', SN.layer_of(it, 12000, 12001, 24000, 3) == 'common')
    check('12001–24000 且次数够 → 作品层',
          SN.layer_of(_it('b', 15000, 3), 12000, 12001, 24000, 3) == 'work')
    check('12001–24000 但次数不够 → 池外',
          SN.layer_of(_it('c', 15000, 2), 12000, 12001, 24000, 3) == 'out')
    check('超过 24000 → 池外',
          SN.layer_of(_it('d', 24001, 9), 12000, 12001, 24000, 3) == 'out')


def test_plan_order_and_layers():
    items = [
        _it('w1', 500, 1),
        _it('w2', 8000, 3),
        _it('w3', 11000, 2),
        _it('w4', 13000, 5),
        _it('w5', 20000, 3),
        _it('w6', 22000, 1),
        _it('w7', 30000, 9),
    ]
    picked, meta = SN.plan_season(items, min_words=1, max_words=4)
    words = [x['word'] for x in picked]
    check('通用层按本季次数降序、再 Jiten 升序',
          words == ['w2', 'w3', 'w1', 'w4'], words)
    check('通用层 3 个 / 作品层 1 个（max 截断）',
          meta['common_total'] == 3 and len(picked) == 4, meta)
    check('超过上限不超 max_words', len(picked) <= 4)
    check('layer 标记正确',
          [x['layer'] for x in picked] == ['common', 'common', 'common', 'work'],
          [x['layer'] for x in picked])


def test_plan_relax_count():
    items = [
        _it('c1', 500, 1),
        _it('b1', 15000, 2),
        _it('b2', 18000, 2),
    ]
    picked, meta = SN.plan_season(items, min_words=3, max_words=5)
    words = sorted(x['word'] for x in picked)
    check('次数不足下限时放宽到 ≥2 次补位', words == ['b1', 'b2', 'c1'], words)
    check('放宽记录有次数调整',
          any(str(r.get('to')) == '2' for r in meta['relaxed']), meta['relaxed'])
    check('放宽后仍不超过上限', len(picked) <= 5)


def test_plan_relax_jiten_cap():
    items = [
        _it('c1', 500, 1),
        _it('late1', 28000, 1),
        _it('late2', 29000, 2),
    ]
    picked, meta = SN.plan_season(items, min_words=3, max_words=5,
                                  work_min_count=3)
    words = [x['word'] for x in picked]
    check('次数放到 1 后仍不够 → Jiten 上限放宽到 30000',
          set(words) == {'c1', 'late1', 'late2'}, words)
    check('meta 记录了放宽后的 Jiten 上限', meta['work_jiten_max'] == 30000,
          meta['work_jiten_max'])


def test_plan_no_overfill():
    items = [_it('w%d' % i, 500 + i, 1) for i in range(50)]
    picked, meta = SN.plan_season(items, min_words=10, max_words=7)
    check('候选再多也只取 max_words 个', len(picked) == 7, len(picked))
    check('meta.truncated 标记', meta['truncated'] is True, meta['truncated'])


def test_noise_filter():
    check('出现 1 次的惯用句 → 噪声',
          SN.is_noise(_it('おっ', 315, 1, pos='惯用句')) is True)
    check('出现 2 次的惯用句 → 保留',
          SN.is_noise(_it('ただいま', 659, 6, pos='惯用句')) is False)
    check('普通名词不误杀',
          SN.is_noise(_it('鍋', 5246, 1, pos='名词')) is False)


def test_payload_and_report():
    items = [_it('a', 500, 2), _it('b', 15000, 4)]
    picked, meta = SN.plan_season(items, min_words=1, max_words=10)
    payload = SN.build_payload('subtitles/X', [('E01', 'x.srt')],
                               {'jitenMax': 12000, 'minWords': 1, 'maxWords': 10},
                               meta, {'no_rank': [], 'no_notes': [], 'reading': []},
                               picked, candidates=2, tag='本季生词::X')
    check('payload schema/tool', payload['schema'] == 1 and payload['tool'] == 'season-new')
    check('payload counts 可读',
          payload['counts']['picked'] == 2 and payload['counts']['common'] == 1
          and payload['counts']['work'] == 1, payload['counts'])
    check('payload 可 json.dumps', isinstance(json.dumps(payload, ensure_ascii=False), str))
    md = SN.report_md('subtitles/X', [('E01', 'x.srt')],
                      {'jitenMax': 12000, 'minWords': 1, 'maxWords': 10},
                      meta, picked, tag='本季生词::X')
    check('报告含两层标题', '## 通用层（先学）' in md and '## 作品层（再补）' in md, md[:80])


def main():
    for fn in (test_slug_and_tag, test_layer_of, test_plan_order_and_layers,
               test_plan_relax_count, test_plan_relax_jiten_cap,
               test_plan_no_overfill, test_noise_filter,
               test_payload_and_report):
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
