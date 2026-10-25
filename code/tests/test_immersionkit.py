# -*- coding: utf-8 -*-
"""回归测试：ImmersionKit 抓句链路的纯函数（**不连网、不碰 Anki 写接口**）。

跑法（只用工作区的 python）::

    & $PY code\\tests\\test_immersionkit.py

覆盖整条链里最容易「静默出错」的三段：

1. 振假名 ``漢字[よみ]`` → ``Sentence HTML`` 的**对齐**（错位就是错读音，
   ``check_ruby.py`` 会报；给纯假名加 ruby 是软错，有汉字没 ruby 是硬错）；
2. 例句清洗与筛选（bidi 控制符 / ``<br>`` / 类别 / 句长 / 跨词去重 / 命中判定）；
3. 词表过滤与排序（core6000+考级剔除、目标牌组已有、Jiten 排名）。

外加一段**载荷形状**检查（例句卡 8 字段 / 素材卡 14 字段、Index 连续、
``JitenAnimeRank`` 补零 6 位、``AINote`` 与 ``Sentence HTML`` 同空同有）。
"""
import os
import re
import shutil
import sys
from itertools import count

_SEQ = count(1)
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'execution'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'analysis', 'vocab_cover'))

import immersion_api as IM      # noqa: E402
import immersionkit as IK       # noqa: E402
import textio                   # noqa: E402

FAIL = []
RT_BLOCK = re.compile(r'<rt>.*?</rt>', re.S)
TAG = re.compile(r'<[^>]+>')


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def text_of(html):
    """与 code/common/check_cards.py 的 ``text_of`` 同口径：先删 ``<rt>…</rt>`` 再剥标签。"""
    return TAG.sub('', RT_BLOCK.sub('', html or ''))


def case(name, sentence, furigana, want_html=None, want_ok=True):
    html, ok = IM.furigana_to_html(sentence, furigana)
    check('%s ｜ ok=%s' % (name, want_ok), ok is want_ok, '得到 %r' % (ok,))
    if want_ok:
        check('%s ｜ 去标签去 rt 后与原句逐字一致' % name,
              text_of(html) == sentence, '%r vs %r' % (text_of(html), sentence))
    if want_html is not None:
        check('%s ｜ 渲染内容' % name, html == want_html, '得到 %r' % html)
    return html


def ex(i, sentence, translation='译', word_list=(), matched=None, title='clannad',
       category='anime', furigana=None):
    return {'id': '%s_%s_%09d' % (category, title, i),
            'sentence': sentence, 'sentence_with_furigana': furigana or sentence,
            'translation': translation, 'word_list': list(word_list),
            'matched_indexes': list(matched or []), 'title': title,
            'image': 'i.jpg', 'sound': 's.mp3'}


def fake_pick(word='嫌い', sid='anime_clannad_000000000'):
    sentence = 'この町は嫌いだ'
    html, ok = IM.furigana_to_html(sentence, 'この 町[まち]は 嫌[きら]いだ')
    return {'id': sid, 'sentence': sentence, 'translation': 'I hate this town.',
            'title': 'clannad', 'word_list': ['この', '町', 'は', '嫌い', 'だ'],
            'matched_indexes': [{'index': 3, 'length': 1}],
            '_category': 'anime', '_reading': 'きら', '_ruby_ok': ok, '_html': html,
            '_ruby_note': '', '_stem': IK.media_stem(sid),
            '_image_url': 'https://cdn/i.jpg', '_sound_url': 'https://cdn/s.mp3'}


def fake_state(word='嫌い', rank=3081):
    return {'plan': [{'word': word, 'rank': rank, 'picks': [fake_pick()],
                      'gen': 'ok', 'meaning': '讨厌', 'pos': 'ナ形容词',
                      'reading': 'きらい', 'translation_cn': '我讨厌这个镇子。',
                      'a_note': '<p><b>中文翻译：</b>我讨厌这个镇子。</p>'}]}


def main():
    print('== 1. 振假名对齐：常规 / 空读音 / 符号基 ==')
    case('单个汉字+送假名', '私 あの子 嫌いよ', '私[わたし] あの 子[こ] 嫌[きら]いよ',
         '<ruby>私<rt>わたし</rt></ruby> あの<ruby>子<rt>こ</rt></ruby> '
         '<ruby>嫌<rt>きら</rt></ruby>いよ')
    case('空读音（实测 痛[]い）不加 ruby', 'でも痛いの 嫌いじゃないし',
         'でも 痛[]いの　 嫌[きら]いじゃないし')
    case('符号基（～[から]）丢掉读音', 'カラオケ 嫌いなんで 帰りま～す',
         'カラオケ  嫌[きら]いなんで  帰[かえ]りま ～[から]す')
    case('括号与空格不算进基', '(千)を泣かしたら (バーバ)　嫌いになっちゃうからね。',
         '( 千[せん])を 泣[な]かしたら(バーバ)　 嫌[きら]いになっちゃうからね。')

    print('== 2. 振假名对齐：混合读音 span（汉字+假名同一个 [读音]）==')
    case('お金[おかね]：读音含前导假名 → 并进基', 'お金がない', 'お金[おかね]がない',
         '<ruby>お金<rt>おかね</rt></ruby>がない')
    case('この町[まち]：读音不含前导假名 → 前导留纯文本', 'この町は 嫌いだ',
         'この町[まち]は 嫌[きら]いだ',
         'この<ruby>町<rt>まち</rt></ruby>は <ruby>嫌<rt>きら</rt></ruby>いだ')
    case('食べ物[たべもの]：中间假名逐字对上', '食べ物の好き嫌い', '食[た]べ 物[もの]の 好[す]き 嫌[きら]い')
    case('心の底[こころのそこ]：整词读音', '心の底から嫌いだ', '心の底[こころのそこ]から 嫌[きら]いだ')
    case('私は学生[がくせい]：长基对不上就缩短（这正是 check_ruby 要防的错位）',
         '私は学生です', '私は学生[がくせい]です',
         '私は<ruby>学生<rt>がくせい</rt></ruby>です')
    case('大っ嫌いです：与写法有空格差异仍能对齐', '大っ嫌いです', '大[だい]っ 嫌[きら]いです')

    print('== 3. 振假名对齐：对不上必须留空（宁缺勿错）==')
    check('整句对不上 → ("", False)', IM.furigana_to_html('全然違う文', '別[べつ]の 文[ぶん]') == ('', False))
    check('缺右括号 → ("", False)', IM.furigana_to_html('嫌い', '嫌[きら') == ('', False))
    check('空输入 → ("", False)', IM.furigana_to_html('', '') == ('', False))
    html, ok = IM.furigana_to_html('嫌いだ', '嫌[きら]いだ')
    check('不注音汉字能被查出来（write 用它当闸门）',
          IK.unrubied_kanji('<ruby>嫌<rt>きら</rt></ruby>いだ') == ''
          and IK.unrubied_kanji('嫌いだ') == '嫌', IK.unrubied_kanji('嫌いだ'))

    print('== 4. 目标词读音 ==')
    check('从 furigana 取目标词读音', IM.word_reading(
        ex(1, '', word_list=['嫌い'], furigana='私[わたし]　嫌[きら]いよ'), '嫌い') == 'きら')
    check('取不到就空串', IM.word_reading(ex(1, '', word_list=['猫']), '猫') == '')

    print('== 5. 文本清洗 ==')
    dirty = '\u202a“嫌いですか？”\u202c'
    check('去掉 bidi 控制符', IM.clean_text(dirty) == '“嫌いですか？”', repr(IM.clean_text(dirty)))
    check('全角空格保留、连续半角空格折叠',
          IM.clean_text('(メリル )私  あの子　嫌いよ') == '(メリル )私 あの子　嫌いよ',
          repr(IM.clean_text('(メリル )私  あの子　嫌いよ')))
    check('NBSP 变普通空格', IM.clean_text('a\u00a0b') == 'a b')
    check('<br> 检出（多说话人拼接的判据）', IM.has_br('a<br>b') and not IM.has_br('a b'))
    check('括号占比：说话人标记', abs(IM.paren_ratio('(メリル) 私 嫌いよ') - 5 / 11) < 0.01,
          IM.paren_ratio('(メリル) 私 嫌いよ'))

    print('== 6. 命中的三重判定（drama 的 matched_indexes 常为空）==')
    check('matched_indexes 精确切片', IM.hits_word(
        ex(1, 'あ', word_list=['この', '嫌い'], matched=[{'index': 1, 'length': 1}]), '嫌い'))
    check('matched_indexes 为空但 word_list 有整词', IM.hits_word(
        ex(1, 'あ', word_list=['あ', '嫌い', 'だ']), '嫌い'))
    check('被拆成多个 token 也能命中', IM.hits_word(
        ex(1, 'あ', word_list=['嫌', 'い', 'だ']), '嫌い'))
    check('完全不在 → 不命中', not IM.hits_word(ex(1, '猫が好き', word_list=['猫', '好き']), '嫌い'))

    print('== 7. 选句：类别 / 句长 / <br> / 去重 / n ==')
    pool = [
        ex(1, '嫌いだね', 'hate it', ['嫌い', 'だ', 'ね']),
        ex(2, '猫が嫌いです', 'hate cats', ['猫', '嫌い'], title='clannad', category='games'),
        ex(3, 'a<br>嫌い', 'x', ['嫌い']),
        ex(4, '嫌い' * 30, 'long', ['嫌い']),
        ex(5, 'あ' * 40 + '嫌い', 'long', ['嫌い']),
        ex(6, 'この町は嫌いだ', 'I hate this town', ['この', '町', 'は', '嫌い', 'だ'],
           matched=[{'index': 3, 'length': 1}]),
        ex(7, '猫は嫌いだ', 'I hate cats', ['猫', 'は', '嫌い', 'だ']),
    ]
    picks = IM.select_sentences(pool, '嫌い', n=3, categories=['anime'], max_len=20)
    check('类别过滤掉 games', all(p['_category'] == 'anime' for p in picks), str([p['id'] for p in picks]))
    check('含 <br> 的被丢掉', all('<br>' not in p['sentence'] for p in picks))
    check('超长句被丢掉', all(IM.text_len(p['sentence']) <= 20 for p in picks))
    check('短句优先（服务端序即短优先，这里保序）', picks[0]['sentence'] == '嫌いだね',
          picks[0]['sentence'])
    check('n 生效', len(picks) == 3, str(len(picks)))
    check('附带的 _category / _reading 都在（_html 由 fetch 阶段填）',
          all(p['_category'] and '_reading' in p for p in picks))
    used = set()
    first = IM.select_sentences(pool, '嫌い', n=2, categories=['anime'], max_len=20, used_ids=used)
    second = IM.select_sentences(pool, '嫌い', n=2, categories=['anime'], max_len=20, used_ids=used)
    check('used_ids 跨词去重（同一句不会被两个词各写一张卡）',
          not ({p['id'] for p in first} & {p['id'] for p in second}),
          '%s / %s' % ([p['id'] for p in first], [p['id'] for p in second]))
    check('句长下限也生效', IM.select_sentences([ex(9, '嫌い', 'x', ['嫌い'])], '嫌い',
                                            min_len=4) == [])
    check('译文为空/含 <br> 的丢掉',
          IM.select_sentences([ex(9, '嫌い', '', ['嫌い']),
                               ex(10, '嫌い', 'a<br>b', ['嫌い'])], '嫌い') == [])

    print('== 8. 词表过滤 + Jiten 排序 ==')
    words = [('嫌い', None), ('猫', 2), ('ゴンドラ', None), ('食う', None)]
    todo, skipped = IM.filter_words(
        words, canonical={'猫': '考级', '食う': 'Core6000'},
        variants={'くらい': '嫌い'}, have={'ゴンドラ'},
        rank_of=lambda w: {'嫌い': 3081, 'ゴンドラ': 999999, '食う': 500}[w],
        norm=lambda w: w)
    check('已在 core6000/考级 → 剔除', [w for w, _r in skipped] == ['猫', 'ゴンドラ', '食う'],
          str(skipped))
    check('目标牌组已有 → 剔除', any(w == 'ゴンドラ' for w, _r in skipped), str(skipped))
    check('剩下的只有嫌い', [r['word'] for r in todo] == ['嫌い'], str(todo))
    todo2, _s = IM.filter_words([('a', None), ('b', None), ('c', None)],
                                rank_of=lambda w: {'a': 99, 'b': 1, 'c': 999999}[w])
    check('按 Jiten 排名升序（999999 排最后）',
          [r['word'] for r in todo2] == ['b', 'a', 'c'], str(todo2))
    todo3, _s = IM.filter_words([('x', None)], variants={'x': 'y'}, canonical={'y': '考级'})
    check('写法归一命中也能剔除', todo3 == [] and '归一' in _s[0][1], str(_s))

    print('== 9. 词表文件解析（# 注释 / 词<TAB>条数 / 去重）==')
    base = IK.WSP.TEMP
    tmp = os.path.join(base, 'immersion_test_%d' % next(_SEQ))
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        wf = os.path.join(tmp, 'words.txt')
        textio.write_text(wf, '# 注释行\n嫌い\n猫\t2\n嫌い\n\n ゴンドラ \n')
        got = IM.read_words_file(wf)
        check('解析出 3 个词、保序去重', got == [('嫌い', None), ('猫', 2), ('ゴンドラ', None)],
              str(got))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('== 10. 载荷形状：例句卡 Basic 8 字段 / 素材卡 Japanese Vocabulary 14 字段 ==')
    items = IK.build_payloads(fake_state(), 'both', False, 6001)
    check('一个词 → 例句卡 1 张 + 素材卡 1 张', len(items) == 2, str(len(items)))
    deck_e, model_e, fields_e, tags_e = items[0][:4]
    deck_m, model_m, fields_m, tags_m = items[1][:4]
    check('例句卡落在 ::2-例句 + Basic 模型',
          deck_e == IK.DECK_EXAMPLE and model_e == 'Basic', '%s / %s' % (deck_e, model_e))
    check('例句卡字段齐全（8）', set(fields_e) == set(IK.BASIC_FIELDS),
          str(sorted(set(IK.BASIC_FIELDS) ^ set(fields_e))))
    check('例句卡有剧照与原声',
          fields_e['Image'].startswith('<img src="ik_anime_clannad_000000000.jpg"')
          and fields_e['Sentence Audio'] == '[sound:ik_anime_clannad_000000000.mp3]',
          '%s / %s' % (fields_e['Image'], fields_e['Sentence Audio']))
    check('例句卡 Sentence HTML 去 rt 后与原句一致',
          text_of(fields_e['Sentence HTML']) == fields_e['Sentence'])
    check('例句卡标签＝动画::中文名（命中 slug_map.yaml）', tags_e == ['动画::CLANNAD'], str(tags_e))
    check('例句卡标签：映射表里没有的作品退回英文 slug',
          IK.example_tag('anime', 'zzz_unknown') == '动画::zzz_unknown'
          and IK.example_tag('drama', 'zzz_unknown') == '日剧::zzz_unknown',
          '%s / %s' % (IK.example_tag('anime', 'zzz_unknown'),
                       IK.example_tag('drama', 'zzz_unknown')))
    check('素材卡落在 ::0-素材生词 + Japanese Vocabulary',
          deck_m == IK.DECK_MINED and model_m == 'Japanese Vocabulary',
          '%s / %s' % (deck_m, model_m))
    check('素材卡字段齐全（14）', set(fields_m) == set(IK.JVOCAB_FIELDS),
          str(sorted(set(IK.JVOCAB_FIELDS) ^ set(fields_m))))
    check('Index 用传入的起点', fields_m['Index'] == '6001', fields_m['Index'])
    check('JitenAnimeRank 补零 6 位', fields_m['JitenAnimeRank'] == '003081',
          fields_m['JitenAnimeRank'])
    check('素材卡只挂裸 素材生词（2026-10-17 收敛口径，不再有子标签）',
          tags_m == ['素材生词'], str(tags_m))
    check('配图进 Meaning（沿用现有素材卡先例）',
          '<img src="ik_anime_clannad_000000000.jpg"' in fields_m['Meaning'],
          fields_m['Meaning'][:80])
    check('Word Audio / Pitch Accent 留空',
          fields_m['Word Audio'] == '' and fields_m['Pitch Accent'] == '')

    items_no = IK.build_payloads(fake_state(), 'both', True, 6001)
    check('--no-ainote：AINote 与 Sentence HTML 一起留空',
          all(it[2]['AINote'] == '' and it[2]['Sentence HTML'] == '' for it in items_no))
    items_rankless = IK.build_payloads(fake_state(rank=None), 'mined', False, 1)
    check('词表外写 999999', items_rankless[0][2]['JitenAnimeRank'] == '999999',
          items_rankless[0][2]['JitenAnimeRank'])
    two = fake_state()
    two['plan'][0]['picks'] = [fake_pick(sid='anime_clannad_000000000'),
                               fake_pick(sid='anime_clannad_000000001')]
    items_two = IK.build_payloads(two, 'both', False, 10)
    check('--to both：n 条例句 = n 张例句卡 + 1 张素材卡（按词分组，素材卡跟在首句后）',
          [it[1] for it in items_two] == ['Basic', 'Japanese Vocabulary', 'Basic'],
          str([it[1] for it in items_two]))
    idx = [it[2]['Index'] for it in items_two if it[1] == 'Japanese Vocabulary']
    check('素材卡只取第一条（Index 连续）', idx == ['10'], str(idx))
    check('媒体文件名来自 example id', IK.media_stem('anime_k_on__000003060') == 'ik_anime_k_on__000003060',
          IK.media_stem('anime_k_on__000003060'))

    print()
    if FAIL:
        print('✗ %d 项不合格：%s' % (len(FAIL), '、'.join(FAIL)))
        raise SystemExit(1)
    print('✓ 全部通过')


if __name__ == '__main__':
    main()
