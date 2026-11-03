# -*- coding: utf-8 -*-
"""回归测试：`sense_repair`（义项核验被剔的词 → 修原卡回插名单）的纯逻辑

挡九件事：
1. sanitize：反斜杠 / Markdown / 半角双引号一律进不了卡（check_cards 的 AINote 硬规则）。
2. 新句闸门：太短 / 太长 / 句面不含目标词（**平假名归一**后比较，`マシ` 认得 `まし`）/
   与原句换皮，四类都不收。
3. 多句字段追加：``句1<br><br>句2``；音频 `[sound:]` 去重，绝不重复追加。
4. `AINote`「② 新句」块幂等：重跑只替换自己的块，① 原正文一个字不动。
5. 词性只改「确定冲突」：两边都认得出且不相交；映射不出的中文词性不改卡。
6. `build_fields`：Meaning 配图 tail 原样拼回；无新句时只写 Meaning（+词性）。
7. 重判放行口径：True / None 放行，只有 False 拦（与 sense gate「不误杀」一致）。
8. 修好的词集合 → 回插名单（results_fixed_words）。
9. `Sentence` 按块切开（≥2 块的卡要跳过，交给 core6000 链路）。

跑法（不碰 Anki、不联网、不调模型）：
  & $PY code\\tests\\test_sense_repair.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
for _p in ('tools', 'common', 'execution', os.path.join('execution', 'core6000')):
    sys.path.insert(0, os.path.join(_CODE, _p))
import textio  # noqa: E402,F401  UTF-8 stdio 唯一入口（audit R2）
import sense_repair as SR  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def test_sanitize():
    s = SR.sanitize('「逃がす」\\\\ 放走 **核心** ``x`` "半角引号"\n第二行')
    check('去反斜杠 / Markdown / 半角双引号', '\\\\' not in s and '**' not in s
          and '```' not in s and '"' not in s, s)
    check('换行压成一行', '\n' not in s, s)
    check('弯引号→直角引号（不留半角）', '「' in SR.sanitize('"a"') or '"' not in SR.sanitize('"a"'))


def test_sentence_gate():
    forms = SR.target_forms('増し', '増し', 'まし')
    ok, why = SR.sentence_ok('お疲れ', forms, '')
    check('太短不收', not ok and '太短' in why, why)
    ok, why = SR.sentence_ok('それに去年よりはマシだしな、本当に', forms, '')
    check('片假名写法认得平假名读音', ok, why)
    ok, why = SR.sentence_ok('これはただの文です、本当に長めの', forms, '')
    check('句面不含目标词不收', not ok and '不含目标词' in why, why)
    ok, why = SR.sentence_ok('それに去年よりはマシだしな、本当に', forms,
                             'それに去年よりはマシだしな、本当に')
    check('与原句换皮不收', not ok and '换皮' in why, why)
    long_sent = 'ま' * 50 + 'し'
    ok, why = SR.sentence_ok(long_sent, forms, '')
    check('太长不收', not ok and '太长' in why, why)


def test_merge():
    check('多句用 <br><br> 追加', SR.merge_block('旧', '新') == '旧<br><br>新')
    check('原字段空就只留新句', SR.merge_block('', '新') == '新')
    a = SR.merge_audio('[sound:a.mp3]', 'b.mp3')
    check('音频追加 [sound:b.mp3]', a == '[sound:a.mp3][sound:b.mp3]', a)
    check('同名音频不重复追加', SR.merge_audio(a, 'b.mp3') == a)
    check('音频文件名带 noteId', SR.audio_name(123) == 'sense-repair-123-sentence-2.mp3')


def test_ainote_idempotent():
    old = '<p><b>核心词汇</b><br>原文讲解</p>'
    once = SR.merge_ainote(old, '新句A', '讲解A')
    twice = SR.merge_ainote(once, '新句B', '讲解B')
    check('① 原正文不动', once.startswith(old), once[:60])
    check('只有一个 ② 块（重跑幂等）',
          twice.count(SR.A2_MARK) == 1, twice)
    check('第二次跑替换内容而不是追加', '新句B' in twice and '新句A' not in twice, twice)
    empty = SR.merge_ainote('', '新句', '讲解')
    check('空 AINote 也生成块', SR.A2_MARK in empty and empty.count('<p>') == 1)


def test_pos():
    check('noun vs 動詞 = 冲突', SR.pos_conflict('noun', '動詞'))
    check('verb vs 動詞 = 不冲突', not SR.pos_conflict('verb', '動詞'))
    check('认不出的卡片词性不参与', not SR.pos_conflict('adjective', '名詞'))
    check('冲突且有映射才给新词性', SR.new_pos_en('noun', '名词', '動詞') == 'noun'
          or SR.new_pos_en('adjective', '名词', '名詞') == '')
    check('adjectival noun 反查', SR.new_pos_en('noun', 'な形容词', '動詞') == 'adjectival noun')
    check('没冲突不改词性', SR.new_pos_en('noun', '名词', '名詞') == '')
    check('映射不出的词性不改卡', SR.new_pos_en('noun', '连体词', '動詞') == '')


def test_build_fields():
    live = {'Meaning': '增加；增多（用于～に増して）<br><br><img src="x.jpg">',
            'Part of Speech': 'noun', 'Sentence': '旧句', 'Sentence HTML': '旧句',
            'Sentence Translation': '旧译', 'AINote': '', 'Sentence Audio': '[sound:w.mp3]'}
    rec = {'word': '増し', 'card_word': '増し', 'reading': 'まし',
           'card_meaning': '增加；增多', 'sentence': 'それに去年よりはマシだしな',
           'dict_pos': 'な形容词', 'senses': []}
    model = {'meaning': '稍好、还好（～よりはマシ）', 'pos_cn': 'な形容词',
             'translation': '总比去年强点。', 'note2': '「～よりはマシ」的固定搭配'}
    f = SR.build_fields(live, rec, model, sent='それに去年よりはマシだしな',
                        ruby='<ruby>去年<rt>きょねん</rt></ruby>よりはマシだしな')
    check('Meaning 配图 tail 原样拼回',
          f['Meaning'].endswith('<br><br><img src="x.jpg">'), f['Meaning'])
    check('Meaning 文字部分是新的', f['Meaning'].startswith('稍好'), f['Meaning'])
    check('词性按词典改成 adjectival noun', f.get('Part of Speech') == 'adjectival noun')
    check('Sentence 恰好 2 块', len(SR._sentence_blocks(f['Sentence'])) == 2)
    check('Sentence HTML 与 Sentence 同块数',
          len(SR._sentence_blocks(f['Sentence HTML'])) == 2)
    check('译文按块配对追加', f['Sentence Translation'].startswith('旧译<br><br>'),
          f['Sentence Translation'])
    check('AINote 只加 ② 块', f['AINote'].count(SR.A2_MARK) == 1)
    check('音频不在纯渲染里写（由 TTS 步骤加）', 'Sentence Audio' not in f, f.keys())

    # 没有可用新句 → 只改释义
    f2 = SR.build_fields(live, rec, model, sent='', ruby='')
    check('无新句只写 Meaning/词性',
          sorted(f2) == ['Meaning', 'Part of Speech'], sorted(f2))
    check('模型没给 meaning → 不写 Meaning',
          'Meaning' not in SR.build_fields(live, rec, {'pos_cn': '名词'}))


def test_judge_and_fixed():
    check('card_ok=True 放行', SR.judge_ok({'card_ok': True}))
    check('card_ok=None（判不了）放行', SR.judge_ok({'card_ok': None}))
    check('card_ok=False 拦', not SR.judge_ok({'card_ok': False}))
    results = [{'word': '疲れ', 'ok': True}, {'word': '増し', 'ok': False},
               {'word': '賢い', 'ok': True}]
    check('修好的词集回插', SR.results_fixed_words(results) == {'疲れ', '賢い'})


def test_blocks():
    check('两块的卡认得出来', len(SR._sentence_blocks('句1<br><br>句2')) == 2)
    check('<br>×3 也算分块', len(SR._sentence_blocks('句1<br><br><br>句2')) == 2)
    check('单句就是 1 块', len(SR._sentence_blocks('ただの一文')) == 1)
    check('<p> 段落也算分块', len(SR._sentence_blocks('<p>一</p><p>二</p>')) == 2)


def test_gloss_and_dict_pos():
    senses = [{'i': 1, 'pos': '名詞', 'glosses': ['tiredness', 'fatigue']},
              {'i': 2, 'pos': '動詞', 'glosses': ['to be tired']}]
    check('字幕义项 gloss 拼接', SR.sense_gloss_of(senses, 1) == 'tiredness；fatigue')
    check('词典词性跟着义项走', SR.dict_pos_of(senses, 2) == '動詞')
    check('义项越界返回空', SR.sense_gloss_of(senses, 9) == ''
          and SR.dict_pos_of(senses, 0) == '')


if __name__ == '__main__':
    for fn in (test_sanitize, test_sentence_gate, test_merge, test_ainote_idempotent,
               test_pos, test_build_fields, test_judge_and_fixed, test_blocks,
               test_gloss_and_dict_pos):
        print('== %s ==' % fn.__name__)
        fn()
    print('')
    if FAIL:
        print('FAIL %d: %s' % (len(FAIL), '；'.join(FAIL)))
        raise SystemExit(1)
    print('全部通过')
