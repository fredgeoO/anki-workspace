# -*- coding: utf-8 -*-
"""每日讲义的「口径 + 脏数据兜底」回归测试（today_new.py）。

跑法：`& $PY code\tests\test_lesson_render.py`

挡的是 2026-10-24 复审点出来的**机械可判**的那几类错：
* 词形与读音对不上（`こ` / `あそこ`）→ 必须报出来、显示时隐藏读音
* 词性标错（`ん` / `もん` 标成副词/惯用句，`あっ`/`あー` 标成副词）→ 统一成中文体系并校正
* 同词重复（`うっ` / `ウッ`、`あー` / `アー`）→ 合并成一条，平/片假名列为变体
* 语法接续夹注音（`Ｖる／する 動どう 詞しのＮ`）→ 不许原样进讲义
* 开头的数字与各节实际条目对不上 → 所有计数从同一份分组派生
* 讲解里的机械错（「大约…左右」、拿目标词自比、句子没写完、例句没用上目标词）→ 报出来
* 例句卡要点被截断、核心词不在句子里 → 就地标注
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'execution'))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))

import textio  # noqa: E402  （stdio/文件一律 UTF-8，见 AGENTS.md §3）
import today_new as TN  # noqa: E402

FAILED = []


def ok(cond, label):
    print('  [%s] %s' % ('OK' if cond else '!!', label))
    if not cond:
        FAILED.append(label)


def section(t):
    print('== %s ==' % t)


def vocab(nid, word, reading='', pos='名', meaning='释义', level='N3'):
    return {'id': nid, 'kind': 'vocab', 'level': level, 'deck': '0-词汇::2-考级词汇',
            'deck_short': '0-词汇 / 2-考级词汇', 'model': 'test', 'queue_pos': nid,
            'word': word, 'reading': reading, 'pos': pos, 'meaning': meaning,
            'audio': [], 'sentences': [], 'style': 'full', 'n_cards': 1}


def grammar(nid, word, pos_raw, level='N3'):
    return {'id': nid, 'kind': 'grammar', 'level': level, 'deck': '1-语法::3-N3::1-N3-解释',
            'deck_short': '1-语法 / 3-N3 / 1-N3-解释', 'model': 'test', 'queue_pos': nid,
            'word': word, 'reading': '', 'pos': pos_raw, 'meaning': '随着～',
            'audio': [], 'sentences': [], 'style': 'full', 'n_cards': 1}


def sentence_card(nid, word, points, ruby, cn='中文', n_cards=1):
    return {'id': nid, 'kind': 'sentence', 'level': '', 'deck': '2-例句',
            'deck_short': '2-例句', 'model': 'Basic', 'queue_pos': nid,
            'word': word, 'reading': '', 'pos': '', 'meaning': cn,
            'audio': [], 'sentences': [], 'style': 'light', 'n_cards': n_cards,
            'light': {'jp_ruby': ruby, 'cn': cn, 'points': points, 'source': '某动画 第01集 01:00'}}


def grammar_sentence_card(nid, word, pos_raw, ruby, cn, points):
    sents = [{'jp': 'テスト%d' % i, 'ruby': 'テスト%d' % i, 'cn': '测试%d' % i, 'audio': []}
             for i in range(1, 4)]
    return {'id': nid, 'kind': 'grammar', 'level': 'N3', 'deck': '1-语法::3-N3::2-N3-例句',
            'deck_short': '1-语法 / 3-N3 / 2-N3-例句', 'model': 'test', 'queue_pos': nid,
            'word': word, 'reading': '', 'pos': pos_raw, 'meaning': cn,
            'audio': [], 'sentences': sents, 'style': 'light', 'n_cards': 3,
            'card_ords': [1, 2, 3],
            'light': {'jp_ruby': '', 'cn': cn, 'points': points, 'source': ''}}


def manifest_of(cards, date='2026-10-24'):
    def n(pred):
        return sum(c.get('n_cards') or 1 for c in cards if pred(c))

    return {
        'version': 2, 'date': date, 'generated_at': '2026-10-24T06:00:00',
        'counts': {'total': n(lambda c: True), 'entries': len(cards),
                   'vocab': n(lambda c: c['kind'] == 'vocab'),
                   'grammar': n(lambda c: c['kind'] == 'grammar'),
                   'sentence': n(lambda c: c['kind'] == 'sentence')},
        'decks': [
            {'deck': '0-词汇::2-考级词汇', 'model': 'test', 'kind': 'vocab',
             'taken': n(lambda c: c['kind'] == 'vocab'), 'taken_notes': 3, 'limit': 8,
             'limit_source': 'deckConfig「考级」'},
            {'deck': '1-语法', 'model': 'test', 'kind': 'grammar',
             'taken': n(lambda c: c['kind'] == 'grammar'), 'taken_notes': 2, 'limit': 5,
             'limit_source': 'deckConfig「日语语法」'},
        ],
        'cards': cards,
    }


LESSON = {'date': '2026-10-24', 'entries': {}, 'intro': ''}


def main():
    section('1. reading_problem：只报能证伪的')
    ok(TN.reading_problem('こ', 'あそこ') != '', 'こ / あそこ → 报错（复审第 1 条）')
    ok(TN.reading_problem('カモ', 'かも') == '', 'カモ / かも → 平片假名不算错')
    ok(TN.reading_problem('逃がす', 'にがす') == '', '逃がす / にがす → 送假名对得上')
    ok(TN.reading_problem('お互い', 'おたがい') == '', 'お互い / おたがい → 送假名对得上')
    ok(TN.reading_problem('得る', 'える') == '', '得る / える → 没问题')
    ok(TN.reading_problem('上', 'かみ') == '', '上 / かみ → 脚本判断不了读音对错，不瞎报')
    ok(TN.reading_problem('離す', 'はなす') == '', '離す / はなす → 没问题')

    section('2. 词性：中文体系 + 复审点名的错标')
    ok(TN.pos_label('他動1') == '他动词1类', '他動1 → 他动词1类')
    ok(TN.pos_label('Verbal Noun') == '动词性名词', 'Verbal Noun → 动词性名词')
    ok(TN.pos_label('Noun') == '名词', 'Noun → 名词')
    ok(TN.pos_label('Adverb') == '副词', 'Adverb → 副词（core6000 英文标签别漏）')
    ok(TN.pos_label('接尾・名') == '接尾辞（名词）', '接尾・名 → 接尾辞（名词）')
    ok(TN.display_pos(vocab(1, 'ん', pos='副词')) == ('终助词', True), 'ん（副词）→ 终助词（校正）')
    ok(TN.display_pos(vocab(2, 'もん', pos='惯用句')) == ('终助词', True), 'もん（惯用句）→ 终助词')
    ok(TN.display_pos(vocab(3, 'あっ', pos='副词')) == ('感叹词', True), 'あっ（副词）→ 感叹词')
    ok(TN.display_pos(vocab(4, 'よし', pos='惯用句')) == ('感叹词', True), 'よし（惯用句）→ 感叹词')
    ok(TN.display_pos(vocab(5, '運命', pos='名')) == ('名词', False), '正常词性不被改写')

    section('3. 语法接续：清注音 / 认脏数据')
    garbled = 'Ｖる／する 動どう 詞しのＮ＋につれて'
    ok(TN.structure_looks_garbled(TN.clean_structure(garbled)),
       '汉字/假名之间夹空格 → 判为脏数据（复审第 14 条）')
    ok(TN.clean_structure('动词る形/名词') == '动词辞书形/名词',
       '动词る形/名词 → 动词辞书形/名词')
    ok(TN.clean_structure('Ｎ＋につれて') == '名词＋につれて', 'Ｎ → 名词')
    ok(TN.clean_structure('動[どう]詞[し]のＮ＋につれて') == '动词の名词＋につれて',
       '漢字[かんじ] 记法的注音也去掉')
    st, state = TN.grammar_structure(grammar(9, 'につれて', garbled),
                                     {'structure': '动词る形/名词'})
    ok(st == '动词辞书形/名词' and state == '', '模型整理过的接续优先，且不显示脏字段')
    st2, state2 = TN.grammar_structure(grammar(9, 'につれて', garbled), {})
    ok(st2 == '—' and state2 == 'dirty', '没有模型产出时显示「—」而不是乱码')

    section('4. 同词重复：只并在纯假名条目之间')
    groups = TN.group_vocab([vocab(1, 'うっ'), vocab(2, 'ウッ'), vocab(3, 'あー'),
                             vocab(4, 'アー'), vocab(5, '会う'), vocab(6, '合う')])
    ok(len(groups) == 4, 'うっ/ウッ、あー/アー 各并成一条；会う/合う 不合并（汉字不同）')
    ok([v['word'] for v in groups[0][1]] == ['ウッ'], '变体记在主条目旁边')

    section('5. 讲解里的机械错')
    card = vocab(1, '程度')
    t = {'one_line': '表示程度。', 'core': '比「くらい」正式。',
         'examples': [{'jp': '百円程度の小銭が必要だ。', 'cn': '需要大约一百日元左右的零钱。'}]}
    msgs = TN.teach_issues(card, t)
    ok(any('语义重复' in m for m in msgs), '「大约…左右」→ 报语义重复（复审第 9 条）')
    t2 = {'one_line': '想象。', 'core': '比「想像」更常用。', 'examples': []}
    ok(any('跟它自己比' in m for m in TN.teach_issues(vocab(2, '想像'), t2)),
       '「比『想像』更常用」→ 报自指比较（复审第 4 条）')
    t3 = {'one_line': '时间。', 'core': '口语。',
          'examples': [{'jp': '時間がないから、早くして。', 'cn': '因为没时间，'} ]}
    ok(any('没写完' in m for m in TN.teach_issues(vocab(1, '時間'), t3)), '中文停在「，」→ 报没写完')
    t4 = {'one_line': '拉。', 'core': '口语。', 'examples': [
        {'jp': '重い荷物を車までひいて運んだ。', 'cn': '我把行李拖到车边。'}]}
    ok(not any('没有用上目标词' in m for m in TN.teach_issues(vocab(3, 'ひく'), t4)),
       '假名词的活用形（ひく→ひいて）不算没用上目标词')
    t5 = {'one_line': '拉。', 'core': '口语。', 'examples': [
        {'jp': '彼は毎朝走る。', 'cn': '他每天早上跑步。'}]}
    ok(any('没有用上目标词' in m for m in TN.teach_issues(vocab(4, 'ひく'), t5)),
       '真的没用上目标词 → 报错')

    section('6. 例句卡：核心词 / 截断 / 自相矛盾')
    good = sentence_card(1, 'あの子が届けたかったのは この想い',
                         ['核心词汇：子ども：名词。孩子、小孩。',
                          '语法要点：〜たかったのは〜：把想做的事名词化。'],
                         '<ruby>あの</ruby><ruby>子</ruby>が<ruby>届</ruby>けたかったのは')
    msgs = TN.light_card_issues(good)
    ok(any('核心词汇「子ども」在本句里找不到' in m for m in msgs),
       '句中是「あの子」、核心词写「子ども」→ 报出来（复审第 15 条）')
    cut = sentence_card(2, 'だけどそれは無理だから',
                        ['语法要点：〜だから：接在ナ形容词词干后，句末的「…'],
                        'だけどそれは<ruby>無理</ruby>だから')
    ok(any('没写完' in m for m in TN.light_card_issues(cut)), '要点停在上引号 → 报没写完')
    contra = grammar_sentence_card(3, 'にちがいない', '普通形＋に違いない', '',
                                   '一定是～',
                                   ['要点：意为“觉得一定是～”，表示高确信推测。'])
    ok(any('自相矛盾' in m for m in TN.light_card_issues(contra)),
       '「觉得」+「一定」→ 报自相矛盾（复审第 16 条）')

    section('7. 渲染：计数自洽 / 合并 / 校正在正文里生效')
    cards = [
        vocab(1, 'うっ', pos='副词'), vocab(2, 'ウッ', pos='惯用句'),
        vocab(3, 'こ', reading='あそこ', meaning='那里；远处'),
        grammar(4, 'につれて', garbled),
        grammar_sentence_card(5, 'にちがいない', '普通形＋に違いない', '',
                              '一定是～', ['要点：意为“觉得一定是～”，表示高确信推测。']),
        sentence_card(6, 'あの子が届けたかったのは この想い',
                      ['核心词汇：子ども：名词。孩子、小孩。'],
                      '<ruby>あの</ruby><ruby>子</ruby>が<ruby>届</ruby>けたかったのは'),
    ]
    m = manifest_of(cards)
    lesson = {'date': m['date'], 'intro': '', 'entries': {
        '1': {'teach': {'one_line': '啊。', 'core': '感叹。',
                        'examples': [{'jp': '足を踏まれて、うっと声を上げた。',
                                      'cn': '脚被踩了，忍不住“哎”了一声。'}]}},
        '3': {'teach': {'one_line': '这个。', 'core': '口语。',
                        'examples': [{'jp': 'こっちへ来て。', 'cn': '到这边来。'}]}},
        '4': {'teach': {'one_line': '随着…', 'core': '前后都变化。',
                        'structure': '动词る形/名词',
                        'uses': ['客观规律。'], 'examples': [
                            {'jp': '年齢が上がるにつれて、体力は落ちる。', 'cn': '随着年龄增长体力下降。'}],
                        'contrast': '与「とともに」不同。', 'pitfall': '别用意志句。'}},
        '5': {'teach': {'one_line': '一定是～', 'source': '卡片'}},
        '6': {'teach': {'one_line': '那个孩子想传达的心意。', 'source': '卡片'}},
    }}
    text = TN.render_lesson(m, lesson)
    ok('共 8 张卡（词汇 3 / 语法 4 / 例句 1）' in text, '开头张数按卡算（含同笔记的多张卡）')
    ok('5 条讲解' in text and '例句卡 2 组 / 4 句' in text, '开头与各节都用同一份分组计数')
    ok(text.count('### うっ') == 1, 'うっ / ウッ 只出现一条（复审第 12 条）')
    ok('うっ / ウッ' in text and '感叹词' in text, '合并后的条目显示变体 + 校正后的词性')
    ok('卡片读音字段写「あそこ」' in text and 'こ（あそこ）' not in text,
       '读音对不上时隐藏读音并就地警告（复审第 1 条）')
    ok('动词辞书形/名词' in text and '動どう' not in text, '语法接续不再带注音乱码')
    ok('核心词汇「子ども」在本句里找不到' in text, '例句卡核心词不在句子里 → 就地标注')
    ok('表述自相矛盾' in text, '「觉得一定是」→ 就地标注')
    ok(TN.check_render(text, m) == [], '渲染闸门通过（词形都在）')

    section('8. check_quality：把问题集中报出来')
    lines, n = TN.check_quality(m, lesson)
    ok(n >= 4, '至少报出：读音 / 接续或讲解 / 核心词 / 自相矛盾（实际 %d 条）' % n)
    ok(any('读音' in x for x in lines), '报告里有读音问题')
    ok(any('--restart' in x for x in lines), '报告里给出返工命令')

    section('9. 空节不崩（只有词汇）')
    only_vocab = manifest_of([vocab(1, '程度', reading='ていど')])
    t = TN.render_lesson(only_vocab, {'date': only_vocab['date'], 'entries': {
        '1': {'teach': {'one_line': '程度。', 'core': '书面。', 'examples': [
            {'jp': '百円程度で足りる。', 'cn': '一百日元左右就够了。'}]}}}, 'intro': ''})
    ok('## 词表' in t and '## 语法' not in t and '## 例句卡' not in t, '只有词汇时不渲染空节')
    ok('1 条讲解（词汇 1 · 语法 0 · 例句卡 0 组 / 0 句）' in t, '空节计数显示 0')
    ok(TN.check_render(t, only_vocab) == [], '只有词汇时闸门也通过')

    print()
    if FAILED:
        print('✗ %d 项未通过：%s' % (len(FAILED), '；'.join(FAILED)))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
