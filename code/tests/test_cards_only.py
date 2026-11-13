# -*- coding: utf-8 -*-
"""`cards.py --only {both,ainote,html}` 的回归测试（阶段 2.1）。

跑法：`& $PY code\tests\test_cards_only.py`

**全离线**：不连 Anki、不调模型。monkeypatch `cards.RE.repair`、
`cards.AK.note_values`、`cards.WB.write_fields`，只验字段选择逻辑：
* parser 默认 `--only both`，显式 `html/ainote` 可解析
* `target_fields` / `filled_fields` 只看选中字段
* `finalize(only='html')`：AINote 空、HTML 合法 → ok；`only='ainote'`：AINote 空 → skipped
* `commit`：`only='html'` 只写 `Sentence HTML`，`only='ainote'` 只写 `AINote`；
  覆盖冲突检查也只看选中字段
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'execution'))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))

import textio                 # noqa: E402  （stdio/文件一律 UTF-8，见 AGENTS.md §3）
import cards                  # noqa: E402

FAILED = []


def ok(cond, label):
    print('  [%s] %s' % ('OK' if cond else '!!', label))
    if not cond:
        FAILED.append(label)


def section(t):
    print('== %s ==' % t)


SENT = '郵便局に戻った時に調べてみるよ'
GOOD_HTML = ('<ruby>郵便局<rt>ゆうびんきょく</rt></ruby>に'
             '<ruby>戻<rt>もど</rt></ruby>った'
             '<ruby>時<rt>とき</rt></ruby>に'
             '<ruby>調<rt>しら</rt></ruby>べてみるよ')
GOOD_AINOTE = ('<p><b>中文翻译：</b>去邮局的时候再查查看。</p>'
               '<p><b>核心词汇：</b><br><ruby>郵便局<rt>ゆうびんきょく</rt></ruby>：名词。邮局。</p>'
               '<p><b>语法要点：</b><br>「〜た時」：做某事的时候。</p>')  # noqa: E501  不用半角引号（闸门会拦）


def test_parser():
    section('1. parser：--only')
    ap = cards.build_parser()
    a = ap.parse_args(['gen', '--note-id', '123'])
    ok(a.only == 'both', 'gen 默认 --only both')
    a = ap.parse_args(['write', '--file', 'x.json'])
    ok(a.only == 'both', 'write 默认 --only both')
    for v in ('html', 'ainote', 'both'):
        ok(ap.parse_args(['gen', '--note-id', '123', '--only', v]).only == v,
           'gen 显式 --only %s' % v)
        ok(ap.parse_args(['write', '--file', 'x.json', '--only', v]).only == v,
           'write 显式 --only %s' % v)


def test_fields():
    section('2. target_fields / filled_fields')
    ok(cards.target_fields('both') == (cards.F_NOTE, cards.F_HTML), 'both = 两个字段')
    ok(cards.target_fields('ainote') == (cards.F_NOTE,), 'ainote = 只 AINote')
    ok(cards.target_fields('html') == (cards.F_HTML,), 'html = 只 Sentence HTML')

    both = {'old_ainote': '有', 'old_html': '<ruby>x<rt>エックス</rt></ruby>'}
    only_note = {'old_ainote': '有', 'old_html': ''}
    only_html = {'old_ainote': '', 'old_html': '<b>x</b>'}
    empty = {'old_ainote': '', 'old_html': ''}

    ok(cards.filled_fields(both) == [cards.F_NOTE, cards.F_HTML], 'both 默认：两个都非空')
    ok(cards.filled_fields(only_note, 'html') == [],
       'only=html：AINote 非空不算已填（不跳过）')
    ok(cards.filled_fields(only_html, 'ainote') == [],
       'only=ainote：HTML 非空不算已填（不跳过）')
    ok(cards.filled_fields(both, 'html') == [cards.F_HTML], 'only=html：只看 old_html')
    ok(cards.filled_fields(both, 'ainote') == [cards.F_NOTE], 'only=ainote：只看 old_ainote')
    ok(not cards.filled(empty, 'html') and not cards.filled(only_note, 'html'),
       'filled 也只按选中字段判')


def test_finalize():
    section('3. finalize：按 only 判定')
    # 离线桩：repair 原样返回（HTML 本身已合法，逐字一致由测试数据保证）
    orig_repair = cards.RE.repair

    # 离线桩：真实 repair 会按 Sentence 骨架补全 ruby；这里用确定性替身模拟它的产出——
    # 模型 HTML 为空时按整句标 ruby（即「repair 能确定性修好」的情形），否则原样返回。
    def stub_repair(sent, html, lex, mode='fix'):
        if not (html or '').strip():
            return ('<ruby>郵便局<rt>ゆうびんきょく</rt></ruby>に'
                    '<ruby>戻<rt>もど</rt></ruby>った'
                    '<ruby>時<rt>とき</rt></ruby>に'
                    '<ruby>調<rt>しら</rt></ruby>べてみるよ'), {}
        return html, {}

    cards.RE.repair = stub_repair
    try:
        card = {'noteId': 1, 'sentence': SENT}
        rec, status, problems, _info = cards.finalize(card, '', GOOD_HTML, None, 'html')
        ok(status == 'ok', "only='html'：AINote 空、HTML 合法 → ok（不再按 AINote 判失败）")
        ok(rec['SentenceHTML'] == GOOD_HTML and rec['AINote'] == '',
           "only='html'：记录保留 HTML，AINote 留空")

        # AINote 为空时闸门仍要完整查 HTML（逐字一致 / 漏 ruby / <br> 数），
        # 不能因为「另一个字段空」就提前放行。
        bad_html = GOOD_HTML.replace('郵便局', '郵便')
        _rec, status, problems, _info = cards.finalize(card, '', bad_html, None, 'html')
        ok(status == 'bad' and any('不一致' in p for p in problems),
           "only='html'：AINote 空时 HTML 逐字不一致仍判 bad%s"
           % ('；'.join(problems)[:120] if problems else ''))

        _rec, status, problems, _info = cards.finalize(card, '', GOOD_HTML, None, 'ainote')
        ok(status == 'skipped', "only='ainote'：选中字段（AINote）为空 → skipped")

        _rec, status, problems, _info = cards.finalize(card, '', GOOD_HTML, None)
        ok(status == 'bad' and any('AINote 为空' in p for p in problems),
           "默认 both：AINote 空但 HTML 非空仍判 bad（与现行为一致）")

        rec, status, problems, _i = cards.finalize(card, GOOD_AINOTE, '', None)
        ok(status == 'ok', '默认 both：合法 AINote + repair 补出的 HTML → ok %s'
           % ('；'.join(problems)[:120] if problems else ''))

        # 桩数据：删掉「中文翻译」段（闸门 SECTIONS 要求的核心段落，缺了必报硬错误）
        broken_ainote = GOOD_AINOTE.replace(
            '<p><b>中文翻译：</b>去邮局的时候再查查看。</p>', '')
        _rec, status, problems, _i = cards.finalize(
            card, broken_ainote, GOOD_HTML, None, 'ainote')
        ok(status == 'bad' and any('中文翻译' in p for p in problems),
           "only='ainote'：仍校验 AINote 段落（选中字段照常把关）%s"
           % ('；'.join(problems)[:120] if problems else ''))

        _rec, status, problems, _i = cards.finalize(
            card, broken_ainote, GOOD_HTML, None, 'html')
        ok(status == 'ok',
           "only='html'：AINote 缺段落不算失败（未选中字段不检查）")

        _rec, status, problems, _i = cards.finalize(card, GOOD_AINOTE, '', None, 'html')
        ok(status == 'skipped', "only='html'：HTML 空 → skipped（AINote 有内容也不算）")
    finally:
        cards.RE.repair = orig_repair


def test_commit():
    section('4. commit：只写选中字段')
    rec = {'noteId': 7, 'sentence': SENT, 'AINote': GOOD_AINOTE, 'SentenceHTML': GOOD_HTML}

    orig_nv, orig_wf = cards.AK.note_values, cards.WB.write_fields
    captured = {}

    def fake_nv(ids, names=None, chunk=None):
        captured['names'] = list(names or [])
        return {i: {n: '' for n in (names or [])} for i in ids}   # 全空 → 无冲突

    def fake_wf(want, **kw):
        captured['want'] = want
        return {'bad': {}, 'ok': True, 'count': len(want)}

    cards.AK.note_values = fake_nv
    cards.WB.write_fields = fake_wf
    try:
        ns = lambda only, ow=False: argparse.Namespace(only=only, overwrite=ow)

        bad = cards.commit([rec], ns('html'))
        ok(bad == {}, 'only=html：commit 成功返回')
        ok(set(captured['want'][7]) == {'Sentence HTML'},
           "only='html'：want 只有 'Sentence HTML' 键")

        cards.commit([rec], ns('ainote'))
        ok(set(captured['want'][7]) == {'AINote'},
           "only='ainote'：want 只有 'AINote' 键")

        cards.commit([rec], ns('both'))
        ok(set(captured['want'][7]) == {'AINote', 'Sentence HTML'},
           "默认 both：两个键都写（与现行为逐字一致）")

        # 覆盖冲突检查也只看选中字段：AINote 已有内容、只重做 HTML → 不拦
        def nv_note_filled(ids, names=None, chunk=None):
            captured['names'] = list(names or [])
            return {i: {n: ('旧讲解' if n == cards.F_NOTE else '') for n in (names or [])}
                    for i in ids}

        cards.AK.note_values = nv_note_filled
        try:
            cards.commit([rec], ns('html'))
            ok(True, '冲突检查只看选中字段：AINote 已有内容不拦 only=html')
            blocked = False
            try:
                cards.commit([rec], ns('both'))     # both 时 AINote 非空 → 拒绝覆盖
            except SystemExit:
                blocked = True
            ok(blocked, '默认 both：AINote 已有内容仍拒绝覆盖（不加 --overwrite）')
        finally:
            cards.AK.note_values = fake_nv
    finally:
        cards.AK.note_values, cards.WB.write_fields = orig_nv, orig_wf


def main():
    test_parser()
    test_fields()
    test_finalize()
    test_commit()
    print()
    if FAILED:
        print('FAILED %d 项：' % len(FAILED))
        for f in FAILED:
            print('  ✗ %s' % f)
        return 1
    print('全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
