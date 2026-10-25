# -*- coding: utf-8 -*-
"""回归测试：jisho_example.py 的解析 / 匹配 / 过滤（**不连网、不碰 Anki**）。

跑法::

    & $PY code\\tests\\test_jisho_example.py

覆盖三处最容易静默出错的地方：

1. Jisho 的 ``furigana + unlinked`` 结构 → 纯日文句子（读音不能混进正文）；
2. Sudachi token 边界匹配：``体中`` 会被切成两个 token，``ヤニ`` 会误命中山
   ``ニヤニヤ`` 的内部子串；
3. Jisho 注音对不齐时的兜底（``お疲れさま`` / ``1時間目`` 交给 Sudachi）。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'tools'))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))
sys.path.insert(0, os.path.join(_WS, 'data', 'pylibs'))

import textio              # noqa: E402  UTF-8 stdio（textio audit 要求）
import jisho_example as J  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


class Tok:
    """Sudachi token 的最小替身。"""

    def __init__(self, surface, reading='', dictionary='', normalized=''):
        self._s = surface
        self._r = reading or surface
        self._d = dictionary or surface
        self._n = normalized or surface

    def surface(self):
        return self._s

    def reading_form(self):
        return self._r

    def dictionary_form(self):
        return self._d

    def normalized_form(self):
        return self._n


class FakeLex:
    pinned = {}

    def __init__(self, mapping):
        self.mapping = mapping

    def tokenize(self, sentence):
        return self.mapping.get(sentence, [])


class FakeLookup:
    """只提供 jmdict_check.match_entries / candidate_readings 需要的字段。"""

    available = True

    def __init__(self, readings):
        self.readings = readings

    def lookup(self, word):
        return [{
            'kanji': [word],
            'kana': [{'text': r, 'common': True} for r in self.readings.get(word, [])],
            'senses': [],
        }]


class Args:
    min_chars = 5
    max_chars = 60
    exact = False
    limit = 8


PAGE = '''<!doctype html><html><body>
<div class="sentences_block"><h4>Sentences<span> — 3 found</span></h4>
<ul class="sentences">
  <li class="entry sentence clearfix">
    <div class="debug">jreibun/1/1</div>
    <div class="sentence_content">
      <ul class="japanese_sentence japanese clearfix" lang="ja">
        猫が<li class="clearfix"><span class="furigana">からだじゅう</span><span class="unlinked">体中</span></li>を
        <li class="clearfix"><span class="furigana">ていねい</span><span class="unlinked">丁寧</span></li>に
        <li class="clearfix"><span class="furigana">な</span><span class="unlinked">舐めて</span></li>いる。
      </ul>
      <div class="english_sentence"><span class="english">The cat is grooming itself.</span>
        <span class="inline_copyright jreibun">— <strong><a href="#">Jreibun</a></strong></span>
      </div>
    </div>
    <a class="light-details_link" href="//jisho.org/sentences/abc">Details ▸</a>
  </li>
  <li class="entry sentence clearfix">
    <div class="debug">tatoeba/2</div>
    <div class="sentence_content">
      <ul class="japanese_sentence japanese clearfix" lang="ja">
        なに<li class="clearfix"><span class="unlinked">ニヤニヤ</span></li>してるんだよ。
      </ul>
      <div class="english_sentence"><span class="english">What are you smirking at?</span>
        <span class="inline_copyright tatoeba">— Tatoeba</span>
      </div>
    </div>
    <a class="light-details_link" href="//jisho.org/sentences/def">Details ▸</a>
  </li>
  <li class="entry sentence clearfix">
    <div class="debug">jreibun/1/1</div>
    <div class="sentence_content">
      <ul class="japanese_sentence japanese clearfix" lang="ja">
        猫が<li class="clearfix"><span class="furigana">からだじゅう</span><span class="unlinked">体中</span></li>を
        <li class="clearfix"><span class="furigana">ていねい</span><span class="unlinked">丁寧</span></li>に
        <li class="clearfix"><span class="furigana">な</span><span class="unlinked">舐めて</span></li>いる。
      </ul>
      <div class="english_sentence"><span class="english">The cat is grooming itself.</span>
        <span class="inline_copyright jreibun">— Jreibun</span>
      </div>
    </div>
  </li>
</ul></div></body></html>'''


def main():
    print('== 1. parse_page：读音不进正文、注解按顺序、出处/URL ==')
    page = J.parse_page(PAGE.encode('utf-8'))
    check('总数 3', page['total'] == 3, page['total'])
    check('抓取 3 条', len(page['entries']) == 3, len(page['entries']))
    e = page['entries'][0]
    check('正文不含 furigana', e['ja'] == '猫が体中を丁寧に舐めている。', e['ja'])
    check('英文翻译', e['en'] == 'The cat is grooming itself.', e['en'])
    check('出处 Jreibun', e['source'] == 'Jreibun', e['source'])
    check('URL 补全协议', e['url'] == 'https://jisho.org/sentences/abc', e['url'])
    check('注解顺序', [x['base'] for x in e['annotations']] == ['体中', '丁寧', '舐めて'],
          e['annotations'])
    check('注解读音', [x['reading'] for x in e['annotations']] ==
          ['からだじゅう', 'ていねい', 'な'], e['annotations'])

    print('== 2. classify_match：token 边界与多 token 词 ==')
    toks = [Tok('猫', 'ネコ', '猫', '猫'), Tok('が', 'ガ', 'が', 'が'),
            Tok('体', 'からだ', '体', '体'), Tok('中', 'ちゅう', '中', '中'),
            Tok('を', 'ヲ', 'を', 'を')]
    sentence = '猫が体中を'
    check('体中（体+中 两个 token）→ exact',
          J.classify_match(sentence, '体中', 'からだじゅう', toks) == 'exact')
    check('猫 → exact', J.classify_match(sentence, '猫', 'ねこ', toks) == 'exact')
    niya = [Tok('なに', 'ナニ', '何', '何'), Tok('ニヤニヤ', 'ニヤニヤ', 'ニヤニヤ', 'ニヤニヤ')]
    check('ヤニ 不误命中 ニヤニヤ 的子串',
          J.classify_match('なにニヤニヤしてる', 'ヤニ', '', niya) == 'none')
    ka = [Tok('飼い猫', 'カイネコ', '飼い猫', '飼い猫')]
    check('猫 在 飼い猫 里 → compound',
          J.classify_match('飼い猫が寝ている', '猫', 'ねこ', ka) == 'compound')
    akuseku = [Tok('あくせく', 'アクセク', 'あくせく', '齷齪')]
    check('齷齪 → exact（normalized_form）',
          J.classify_match('あくせくする', '齷齪', '', akuseku) == 'exact')

    print('== 3. 过滤：去重 / 长度 / 括号 / 无句末标点 / 不匹配 ==')
    lex = FakeLex({
        '猫が体中を丁寧に舐めている。':
            [Tok('猫', 'ネコ', '猫', '猫'), Tok('が'), Tok('体', 'からだ'),
             Tok('中', 'ちゅう'), Tok('を'), Tok('丁寧', 'テイネイ'),
             Tok('に'), Tok('舐め', 'ナメ', '舐める'), Tok('て'), Tok('いる')],
        'なにニヤニヤしてるんだよ。': [Tok('なに'), Tok('ニヤニヤ')],
        'これは長すぎる' + 'あ' * 70 + '。': [Tok('これ')],
        '括弧が閉じていない（テスト。': [Tok('括弧')],
        '句末没有标点': [Tok('句末')],
        '飼い猫が寝ている。': [Tok('飼い猫', 'カイネコ', '飼い猫', '飼い猫'),
                              Tok('が'), Tok('寝て', 'ネテ', '寝る'), Tok('いる')],
    })
    entries = [
        {'ja': '猫が体中を丁寧に舐めている。', 'en': '', 'source': 'Jreibun',
         'sentence_id': '1', 'url': '', 'annotations': []},
        {'ja': 'なにニヤニヤしてるんだよ。', 'en': '', 'source': 'Tatoeba',
         'sentence_id': '2', 'url': '', 'annotations': []},
        {'ja': '猫が体中を丁寧に舐めている。', 'en': '', 'source': 'Jreibun',
         'sentence_id': '1', 'url': '', 'annotations': []},
        {'ja': 'これは長すぎる' + 'あ' * 70 + '。', 'en': '', 'source': 'Tatoeba',
         'sentence_id': '3', 'url': '', 'annotations': []},
        {'ja': '括弧が閉じていない（テスト。', 'en': '', 'source': 'Tatoeba',
         'sentence_id': '4', 'url': '', 'annotations': []},
        {'ja': '句末没有标点', 'en': '', 'source': 'Tatoeba',
         'sentence_id': '5', 'url': '', 'annotations': []},
    ]
    kept, dropped = J.filter_entries(entries, '猫', 'ねこ', lex, Args())
    check('保留 1 条（猫）', len(kept) == 1, [x['ja'] for x in kept])
    check('重复 1 条', dropped['duplicate'] == 1, dict(dropped))
    check('过长 1 条', dropped['length'] == 1, dict(dropped))
    check('括号 1 条', dropped['brackets'] == 1, dict(dropped))
    check('无句末标点 1 条', dropped['no_end_punct'] == 1, dict(dropped))
    check('不匹配 1 条（ニヤニヤ）', dropped['no_match'] == 1, dict(dropped))
    check('match=exact', kept and kept[0]['match'] == 'exact',
          kept[0]['match'] if kept else None)

    exact_args = Args()
    exact_args.exact = True
    kept2, dropped2 = J.filter_entries([
        {'ja': '飼い猫が寝ている。', 'en': '', 'source': 'Tatoeba',
         'sentence_id': '6', 'url': '', 'annotations': []},
    ], '猫', 'ねこ', lex, exact_args)
    check('--exact 丢掉 compound', not kept2 and dropped2['no_match'] == 1, dict(dropped2))

    print('== 4. Jisho 注音对不齐时交给 Sudachi ==')
    plain = FakeLex({})
    check('体中 全汉字 → 接受注解',
          J._annotation_ruby('体中', 'からだじゅう', plain) ==
          '<ruby>体中<rt>からだじゅう</rt></ruby>')
    check('お疲れさま 的截断读音（おつか）→ 拒绝',
          J._annotation_ruby('お疲れさま', 'おつか', plain) is None)
    check('1時間目（数字+汉字）→ 拒绝',
          J._annotation_ruby('1時間目', 'いちじかんめ', plain) is None)
    fake = FakeLookup({'私達': ['わたしたち'], '体中': ['からだじゅう']})
    check('JMdict 否决截断读音（私達 → わたし）',
          J._annotation_ruby('私達', 'わたし', plain, fake) is None)
    check('JMdict 认可的读音保留（体中 → からだじゅう）',
          J._annotation_ruby('体中', 'からだじゅう', plain, fake) ==
          '<ruby>体中<rt>からだじゅう</rt></ruby>')

    print()
    if FAIL:
        print('❌ %d 项失败：%s' % (len(FAIL), ' / '.join(FAIL)))
        return 1
    print('✅ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
