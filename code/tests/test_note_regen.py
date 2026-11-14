# -*- coding: utf-8 -*-
"""`note_regen.py`（卡片修正 · AINote ①② 重写）的离线回归。

跑法：`& $PY code\tests\test_note_regen.py`

**全离线**：不连 Anki、不调模型。验的是三件会写坏卡的事：
1. 句子切分只认「确定是两句」的形态（`<br><br>`，或单个 `<br>` 两侧都有句末标点）；
2. 合成卡把旧 AINote 清空（`sections=[]`）并把 ①/② 两句放进 payload；
3. 提示词里确实有 ① 的四个键；模型产出经 `render_ainote` 后是 `<div>…① …② …</div>`，
   且只写 AINote 一个字段。
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_WS, 'code', 'execution'),
           os.path.join(_WS, 'code', 'common'),
           os.path.join(_WS, 'code', 'execution', 'core6000')):
    sys.path.insert(0, _p)

import textio                 # noqa: E402  （stdio/文件一律 UTF-8）
import note_regen as NR       # noqa: E402
import core6000_example as CE  # noqa: E402

FAILED = []


def ok(cond, label):
    print('  [%s] %s' % ('OK' if cond else '!!', label))
    if not cond:
        FAILED.append(label)


def section(t):
    print('== %s ==' % t)


def fake_note(sentence, trans, html, ainote=''):
    return {
        'noteId': 1,
        'modelName': 'Japanese Vocabulary',
        'fields': {
            'Word': {'value': '放る'},
            'Transliteration': {'value': 'ほうる'},
            'Part of Speech': {'value': '动词'},
            'Meaning': {'value': '扔'},
            'Sentence': {'value': sentence},
            'Sentence HTML': {'value': html},
            'Sentence Translation': {'value': trans},
            'AINote': {'value': ainote},
        },
    }


SENT = 'ボールを空中に放ったの。<br>いい球を放るようになったな、恵一君。'
TRANS = '我把球抛向空中。<br><br>惠一君投球变得很准了。'
HTML = ('ボールを<ruby>空中<rt>くうちゅう</rt></ruby>に<ruby>放<rt>はな</rt></ruby>ったの。'
        '<br>いい<ruby>球<rt>たま</rt></ruby>を<ruby>放<rt>ほう</rt></ruby>るようになったな、'
        '<ruby>恵一<rt>けいいち</rt></ruby><ruby>君<rt>くん</rt></ruby>。')


def test_split():
    section('1. split_sentences')
    ok(NR.split_sentences('一句。<br><br>二句。') == ['一句。', '二句。'], '<br><br> → 两句')
    ok(NR.split_sentences('一句。<br>二句。') == ['一句。', '二句。'],
       '单个 <br> 且两侧都有句末标点 → 两句')
    ok(NR.split_sentences('「一句。」<br>二句。') == ['「一句。」', '二句。'],
       '单个 <br> 且第一句以引号收尾 → 仍认成两句')
    ok(NR.split_sentences('途中で<br>切れた文') == ['途中で<br>切れた文'],
       '单个 <br> 不是句末标点 → 仍算一句（不误切）')
    ok(NR.split_sentences('只有一句。') == ['只有一句。'], '一句原样返回')


def test_card():
    section('2. build_regen_card：清空旧 AINote、两句进 payload')
    card = NR.build_regen_card(fake_note(SENT, TRANS, HTML))
    ok(card['n_sent'] == 2 and card['unmerged'] is True, 'n_sent=2 / unmerged=True')
    ok(card['sections'] == [], 'sections=[]（不拿旧 AINote 当 ①）')
    ok([s['jp'] for s in card['sentences']] == ['ボールを空中に放ったの。',
                                               'いい球を放るようになったな、恵一君。'],
       '①/② 正文按句切分')
    ok([s['cn'] for s in card['sentences']] == ['我把球抛向空中。',
                                               '惠一君投球变得很准了。'],
       '①/② 译文按 <br><br> 对齐')
    ok(card['need_ruby1'] is False and card['need_ruby2'] is False,
       '只重写 AINote：不要求模型补振假名')
    payload = CE.build_payload(card)
    ok(payload.get('sentence2_is_existing') is True, 'payload 标记第二句是卡上既有句')
    ok(payload.get('existing_note') == {}, 'payload 不带旧 AINote')
    ok(payload['existing_sentences'][0]['jp'] == 'ボールを空中に放ったの。',
       'payload 第一句 = ①')

    try:
        NR.build_regen_card(fake_note('只有一句。', '只有一句。', '只有一句。'))
        ok(False, '只有一句 → 明确报错')
    except ValueError as e:
        ok('增加例句' in str(e), '只有一句 → 明确报错并指向增加例句')

    no_word = fake_note(SENT, TRANS, HTML)
    no_word['fields']['Word'] = {'value': ''}
    try:
        NR.build_regen_card(no_word)
        ok(False, '没有 Word 的例句卡 → 明确报错')
    except ValueError as e:
        ok('词汇卡' in str(e), '没有 Word 的例句卡 → 明确报错')


def test_prompt():
    section('3. 提示词：① 四个键在同一份 core6000 正本里')
    prompt = CE.load_system_prompt()
    for key in ('core1', 'grammar1', 'conjugation1', 'context1'):
        ok(key in prompt, '提示词含 %s' % key)
    ok('①' in prompt and '②' in prompt, '提示词讲 ①②')
    ok('cn1' in prompt, '提示词要求 cn1')


def test_generate():
    section('4. generate_one → render_ainote：<div> + ①/②')
    note = fake_note(SENT, TRANS, HTML, ainote='<p><b>中文翻译：</b>旧版式</p>')
    card = NR.build_regen_card(note)
    entry = {
        'new_sentence': card['sentences'][1]['jp'],
        'new_sentence_ruby': '',
        'sentence1_ruby': '',
        'sentence2_ruby': '',
        'cn1': '我把球抛向空中。',
        'cn2': '惠一君投球变得很准了。',
        'new_word_gloss': [
            {'w': '放る', 'r': 'ほうる', 'pos': '动词', 'mean': '投、扔'},
            {'w': '空中', 'r': 'くうちゅう', 'pos': '名词', 'mean': '空中'},
        ],
        'grammar2': '・「～ようになった」：表示能力的变化。',
        'conjugation2': '放る（原形）→ 放るようになった。',
        'context2': '普通体，教练夸奖后辈。',
        'contrast': '①是礼貌体陈述，②是普通体夸奖。',
        'core1': 'ボール（名词）：球。<br><ruby>ボール<rt>ボール</rt></ruby>（名词）：球。'
                 '<br><ruby>空中<rt>くうちゅう</rt></ruby>（名词）：空中。',
        'grammar1': '・「～たの」：句末「の」表示解释说明。',
        'conjugation1': '放る（原形）→ 放った（た形）。',
        'context1': '普通体，同伴描述动作。',
    }

    orig = CE.LC.llm_chat
    calls = {'n': 0}

    def fake_llm(cfg, messages, **kw):
        calls['n'] += 1
        raw = json.dumps({'entries': {str(card['id']): entry}}, ensure_ascii=False)
        return raw, {'prompt_tokens': 1, 'completion_tokens': 1}, {'finish_reason': 'stop'}

    CE.LC.llm_chat = fake_llm
    try:
        args = type('A', (), {'retries': 0, 'no_json_mode': False, 'no_stream': True,
                              'system_prompt': None})()
        got, problems, _warn = NR.generate_one(card, {'model': 'x', 'base_url': 'http://x'}, args)
    finally:
        CE.LC.llm_chat = orig
    ok(problems == [], '闸门通过：%s' % (problems or ''))
    ok(got is not None and got.startswith('<div>') and got.endswith('</div>'),
       'AINote 是 <div> 包裹')
    for canon in ('中文翻译', '核心词汇', '语法要点', '动词变形解析', '语境与表达风格'):
        ok(canon in got, 'AINote 含「%s」' % canon)
    ok('①' in got and '②' in got, 'AINote 含 ① 与 ②')
    ok('两句对比' in got, '语境板块末尾带「两句对比」')
    ok('旧版式' not in got, '旧 AINote 没有被当成 ① 复用')
    ok('<ruby>ボール' not in got and 'ボール（名词）' in got,
       '纯假名 ruby 被确定性剥掉（`<ruby>ボール<rt>ボール</rt></ruby>` → `ボール`）')
    ok('<ruby>空中' in got, '汉字的正常 ruby 保留')
    ok(calls['n'] == 1, '合格后不再重问')

    # 缺 core1 → 闸门拦下（重问 1 次后仍失败），不会拿半份讲解写库
    broken = dict(entry, core1='')
    CE.LC.llm_chat = lambda *a, **k: (
        json.dumps({'entries': {str(card['id']): broken}}, ensure_ascii=False),
        {}, {'finish_reason': 'stop'})
    try:
        args = type('A', (), {'retries': 0, 'no_json_mode': False, 'no_stream': True,
                              'system_prompt': None})()
        got, problems, _warn = NR.generate_one(card, {'model': 'x', 'base_url': 'http://x'}, args)
    finally:
        CE.LC.llm_chat = orig
    ok(got is None and any('core1' in p for p in problems),
       '缺 ① 板块 → 拒绝：%s' % (problems or ''))


def main():
    test_split()
    test_card()
    test_prompt()
    test_generate()
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
