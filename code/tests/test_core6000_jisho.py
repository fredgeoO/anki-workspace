# -*- coding: utf-8 -*-
"""回归测试：core6000 补例句**新句来自 Jisho** 这几段逻辑（**不连网、不碰 Anki**）。

跑法::

    & $PY code\\tests\\test_core6000_jisho.py

挡的是三类会静默坏掉的地方：

1. `word_written_form`：`思い込む` 的书写骨架是 `思い込`，纯假名词要**关掉**这条偏好；
2. `pick_jisho`：只收「振假名合格 + 含目标词 + 长度进闸门 + 与第一句不像」的候选，
   并且**优先**选写出了目标词汉字的句子（`思い込んでいる` > `思いこんでいた`）；
3. `pin_sentence_source`：模型改写句子时必须被 Jisho 原句覆盖，并留一条
   `sentence_overridden` 警告 —— 否则库里就会出现模型自己编的第 2 句。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
_EXEC = os.path.join(_WS, 'code', 'execution')
for _p in (_EXEC, os.path.join(_EXEC, 'core6000'), os.path.join(_EXEC, 'lesson')):
    sys.path.insert(0, _p)
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))
sys.path.insert(0, os.path.join(_WS, 'code', 'tools'))
sys.path.insert(0, os.path.join(_WS, 'data', 'pylibs'))

import textio                # noqa: E402  UTF-8 stdio（textio audit 要求）
import core6000_example as CX  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def cand(jp, ruby='<ruby>R</ruby>', ok=True, en='', source='Tatoeba'):
    return {'jp': jp, 'en': en, 'source': source, 'url': 'https://jisho.org/x',
            'match': 'exact', 'ruby': ruby, 'ruby_ok': ok, 'ruby_issues': []}


def card(word='思い込む', reading='おもいこむ', first='彼はだまされたと思い込んでいるようです。'):
    return {'id': 1, 'word': word, 'reading': reading,
            'sentences': [{'jp': first, 'cn': '', 'ruby': ''}]}


def with_candidates(cands, why=''):
    """把 jisho_fetch 换成固定候选（不联网）。

    带上 ``apply_max_len=True`` 时，fake 会像真身一样对候选跑一遍
    ``filter_by_max_len``（--jisho-max-len 的过滤发生在 jisho_fetch 内部）：
    这样「过滤后零候选 → (None, why 含 max-len)」这条路径才测得到。
    """
    def fake(card_arg, args):
        out = list(cands)
        if getattr(args, 'apply_max_len', False):
            n_max = getattr(args, 'jisho_max_len', None)
            kept = CX.filter_by_max_len(out, n_max)
            if not kept and out:
                return [], ('Jisho 有 %d 条候选，--jisho-max-len %s 过滤后无候选'
                            % (len(out), n_max))
            return kept, why
        return out, why
    return fake


class Args:
    def __init__(self, **kw):
        self.refresh_jisho = False
        self.jisho_timeout = 30.0
        self.no_dict = False
        self.allow_model_sentence = False
        self.__dict__.update(kw)


def main():
    print('== 1. word_written_form：书写骨架 ==')
    check('思い込む → 思い込', CX.word_written_form('思い込む') == '思い込',
          CX.word_written_form('思い込む'))
    check('適当 → 適当', CX.word_written_form('適当') == '適当', CX.word_written_form('適当'))
    check('逃げ出す → 逃げ出', CX.word_written_form('逃げ出す') == '逃げ出',
          CX.word_written_form('逃げ出す'))
    check('纯假名 あまり → 关掉偏好', CX.word_written_form('あまり') == '',
          CX.word_written_form('あまり'))
    check('空词 → 空', CX.word_written_form('') == '')

    print('== 1b. filter_by_max_len：--jisho-max-len 的运行时视图过滤 ==')
    short = cand('短い文だ。')                       # 5 字（去空白）
    mid = cand('中くらいの長さの文だ。')             # 11 字
    longc = cand('とてもとても長い文で、さらに続く。')   # 17 字
    kept = CX.filter_by_max_len([short, mid, longc], 12)
    check('≤12 字只留短/中两条', [c['jp'] for c in kept] == ['短い文だ。', '中くらいの長さの文だ。'],
          [c['jp'] for c in kept])
    check('全部超长 → 空列表', CX.filter_by_max_len([longc], 5) == [])
    check('None / 0 / 负数 / 布尔 → 原样返回（不启用）',
          all(len(CX.filter_by_max_len([mid], n)) == 1 for n in (None, 0, -3, True)))
    check('非整数（小数/字符串）→ 原样返回',
          len(CX.filter_by_max_len([mid], 10.5)) == 1
          and len(CX.filter_by_max_len([mid], '10')) == 1)
    check('空白不计入字数', len(CX.filter_by_max_len([cand('あ い う え お か き')], 7)) == 1)

    print('== 2. pick_jisho：优先写出目标词汉字的那句 ==')
    orig = CX.jisho_fetch
    try:
        CX.jisho_fetch = with_candidates([
            cand('彼は、彼女が幸せだと思いこんでいた。'),
            cand('彼は自分が病人だと思い込んでいる。'),
        ])
        pick, why = CX.pick_jisho(card(), Args())
        check('选中写出「思い込」的那句',
              pick and pick['jp'] == '彼は自分が病人だと思い込んでいる。', pick)
        check('没理由也返回空 reason', why == '', why)

        print('== 3. pick_jisho：四道闸门 ==')
        CX.jisho_fetch = with_candidates([cand('彼は自分が病人だと思い込んでいる。', ok=False)])
        pick, why = CX.pick_jisho(card(), Args())
        check('ruby_ok=False 不要', pick is None, pick)
        check('理由里写了 ruby', 'ruby' in why, why)

        CX.jisho_fetch = with_candidates([cand('彼はだまされたと思い込んでいるようです。')])
        pick, why = CX.pick_jisho(card(), Args())
        check('与原句相同（相似度超阈值）不要', pick is None, pick)
        check('理由里写了 too-similar', 'too-similar' in why, why)

        CX.jisho_fetch = with_candidates([cand('思い込む。')])
        pick, why = CX.pick_jisho(card(), Args())
        check('太短（<6 字）不要', pick is None, pick)
        check('理由里写了 length', 'length' in why, why)

        CX.jisho_fetch = with_candidates([cand('私は犬が好きだ。')])
        pick, why = CX.pick_jisho(card(), Args())
        check('不含目标词不要', pick is None, pick)
        check('理由里写了 kana-form/no-target',
              'kana-form' in why or 'no-target' in why, why)

        CX.jisho_fetch = with_candidates([], 'Jisho 没有返回例句（0 条或页面结构变了）')
        pick, why = CX.pick_jisho(card(), Args())
        check('零候选 → None + 原样带出原因', pick is None and '0 条' in why, why)

        print('== 4. 快照句也能过：只写假名「こ」的句子在 fallback 里仍可用 ==')
        CX.jisho_fetch = with_candidates([cand('彼は、彼女が幸せだと思いこんでいた。')])
        pick, why = CX.pick_jisho(card(), Args())
        check('没有汉字写法时退而接受假名写法',
              pick and pick['jp'] == '彼は、彼女が幸せだと思いこんでいた。', (pick, why))

        print('== 4b. 纯假名动词：活用形也算「含目标词」 ==')
        forms = CX.kana_conjugations('しゃがむ')
        check('しゃがむ → しゃがんだ（撥音便）', 'しゃがんだ' in forms, sorted(forms))
        check('しゃがむ → しゃがんで', 'しゃがんで' in forms, sorted(forms))
        check('しゃがむ → しゃがみます', 'しゃがみます' in forms, sorted(forms))
        check('かく → かいた（イ音便）', 'かいた' in CX.kana_conjugations('かく'))
        check('たべる → たべた（一段）', 'たべた' in CX.kana_conjugations('たべる'))
        check('あまり → 不展开（避免子串误判）',
              CX.kana_conjugations('あまり') == set(), CX.kana_conjugations('あまり'))
        kana_card = card(word='しゃがむ', reading='しゃがむ',
                         first='お年寄りが道端にしゃがんでいますね。')
        check('target_forms 收进活用形',
              'しゃがんだ' in CX.target_forms(kana_card))
        CX.jisho_fetch = with_candidates([cand('少し離れて見ると、その岩は人がしゃがんだ姿に見える。')])
        pick, why = CX.pick_jisho(kana_card, Args())
        check('写「しゃがんだ」的 Jisho 句能被选中',
              pick is not None and 'しゃがんだ' in pick['jp'], (pick, why))
        CX.jisho_fetch = with_candidates([cand('私は犬が好きだ。')])
        pick, why = CX.pick_jisho(kana_card, Args())
        check('假名卡也挡得住不含目标词的句子', pick is None and 'no-target' in why, (pick, why))

        print('== 5. pin_sentence_source：模型改写的句子留不下来 ==')
        entry = {'new_sentence': '彼は自分が病人だと思っている。',
                 'new_sentence_ruby': '<ruby>彼<rt>かれ</rt></ruby>…'}
        target = {'jp': '彼は自分が病人だと思い込んでいる。',
                  'ruby': '<ruby>彼<rt>かれ</rt></ruby>は…', 'en': '', 'source': 'Tatoeba',
                  'url': '', 'match': 'exact'}
        warn = CX.pin_sentence_source(entry, target)
        check('句子被 Jisho 原句覆盖',
              entry['new_sentence'] == target['jp'], entry['new_sentence'])
        check('振假名被 Jisho 值覆盖',
              entry['new_sentence_ruby'] == target['ruby'], entry['new_sentence_ruby'])
        check('记一条 sentence_overridden 警告',
              len(warn) == 1 and warn[0].startswith('sentence_overridden'), warn)

        entry2 = {'new_sentence': target['jp'], 'new_sentence_ruby': target['ruby']}
        warn2 = CX.pin_sentence_source(entry2, target)
        check('照抄时不报警告', warn2 == [], warn2)
        check('没有 pick 时什么都不做',
              CX.pin_sentence_source({}, None) == [])

        print('== 6. --jisho-pick：手动选择优先，越界/不合格仍明确报错 ==')
        # (a) 命中合格候选 → 返回该条
        CX.jisho_fetch = with_candidates([
            cand('彼は、彼女が幸せだと思いこんでいた。'),
            cand('彼は自分が病人だと思い込んでいる。'),
        ])
        pick, why = CX.pick_jisho(card(), Args(jisho_pick=2))
        check('pick=2 返回第 2 条候选',
              pick and pick['jp'] == '彼は自分が病人だと思い込んでいる。', (pick, why))
        check('pick 命中合格候选时 reason 为空', why == '', why)

        # (b) 越界（N > 候选数）→ (None, 含「超出范围」的 why)，不退回自动挑选
        CX.jisho_fetch = with_candidates([
            cand('彼は、彼女が幸せだと思いこんでいた。'),
            cand('彼は自分が病人だと思い込んでいる。'),
        ])
        pick, why = CX.pick_jisho(card(), Args(jisho_pick=5))
        check('pick=5 越界 → None', pick is None, pick)
        check('越界的 why 里写了「超出范围」', '超出范围' in why, why)

        # (c) 指向的候选不过闸门 → (None, 含「不合格」的 why)，且**不会**退回自动挑选
        # （第 1 条 ruby_ok=False；若退回自动挑选会选中合格的第 2 条 —— 这里必须 None）
        CX.jisho_fetch = with_candidates([
            cand('彼は自分が病人だと思い込んでいる。', ok=False),
            cand('彼は自分が病人だと思い込んでいる。'),
        ])
        pick, why = CX.pick_jisho(card(), Args(jisho_pick=1))
        check('pick=1 指向不合格候选 → None（不退回自动挑选）', pick is None, pick)
        check('不合格的 why 里写了「不合格」', '不合格' in why, why)

        # (d) 手动选择优先：自动挑选会因 too-similar 放弃的句子，用户明确点了就采用
        same = cand('彼はだまされたと思い込んでいるようです。')
        CX.jisho_fetch = with_candidates([same])
        pick, why = CX.pick_jisho(card(), Args())
        check('自动挑选拒绝 too-similar', pick is None and 'too-similar' in why, (pick, why))
        pick, why = CX.pick_jisho(card(), Args(jisho_pick=1))
        check('手动 pick 豁免 too-similar（采用用户的句子）',
              pick is not None and pick['jp'] == same['jp'], (pick, why))
        check('手动 pick 命中时 reason 为空', why == '', why)

        print('== 6b. jisho_pick_matches_existing：已有产出不能压掉手动选句 ==')
        card_one = dict(card(), n_sent=1)
        old_paths = CX.gen_paths
        old_read = CX.read_json
        try:
            CX.gen_paths = lambda nid: {'out': 'memory'}
            CX.read_json = lambda path: {
                'gate': {'ok': True},
                'entries': {'1': {'new_sentence': '彼は自分が病人だと思い込んでいる。'}},
            }
            CX.jisho_fetch = with_candidates([
                cand('彼は、彼女が幸せだと思いこんでいた。'),
                cand('彼は自分が病人だと思い込んでいる。'),
            ])
            entry = {'new_sentence': '彼は自分が病人だと思い込んでいる。'}
            check('没有 pick → 保持原跳过口径',
                  CX.jisho_pick_matches_existing(card_one, Args(), entry) is True)
            check('pick 与旧产出同一条 → 跳过',
                  CX.jisho_pick_matches_existing(card_one, Args(jisho_pick=2), entry) is True)
            check('pick 换了一条 → 必须重生成',
                  CX.jisho_pick_matches_existing(card_one, Args(jisho_pick=1), entry) is False)
            check('pick 越界 → 交给 gen 报明确原因',
                  CX.jisho_pick_matches_existing(card_one, Args(jisho_pick=9), entry) is False)
            check('已有两句的卡不参与 Jisho 选句',
                  CX.jisho_pick_matches_existing(dict(card(), n_sent=2),
                                                 Args(jisho_pick=1), entry) is True)
        finally:
            CX.gen_paths = old_paths
            CX.read_json = old_read

        print('== 6c. sentence_html_problems：句内 <br> 不算第三句 ==')
        card_html = {'n_sent': 1, 'need_ruby2': False,
                     'sentences': [{'ruby': '(ｱﾘｵｰﾆ)<br>ガキ… <ruby>騎士<rt>きし</rt></ruby>を'}]}
        entry_html = {'sentence1_ruby': '',
                      'new_sentence_ruby': '<ruby>貧<rt>まず</rt></ruby>しい<ruby>人<rt>ひと</rt></ruby>を愚弄してはいけない。'}
        ruby1 = card_html['sentences'][0]['ruby']
        ruby2 = entry_html['new_sentence_ruby']
        html = ruby1 + '<br>' + ruby2
        check('原句内部有 <br> 时仍判为正确的两句',
              CX.sentence_html_problems(card_html, entry_html, html) == [],
              CX.sentence_html_problems(card_html, entry_html, html))
        check('两句之间缺 <br> → 不合格',
              CX.sentence_html_problems(card_html, entry_html, ruby1 + ruby2) != [])
        check('第二句被截断 → 不合格',
              CX.sentence_html_problems(card_html, entry_html,
                                        ruby1 + '<br>' + ruby2[:-2]) != [])
        check('重复第二句 → 不合格',
              CX.sentence_html_problems(card_html, entry_html,
                                        ruby1 + '<br>' + ruby2 + '<br>' + ruby2) != [])

        print('== 6d. split_sentence_html：按正文边界把句内换行归回原句 ==')
        s1 = '(ｱﾘｵｰﾆ) ガキ… 騎士を愚弄するとは➡ いい度胸だな｡'
        s2 = '貧しい人を愚弄してはいけない。'
        html_two = ('(ｱﾘｵｰﾆ)<br>ガキ… <ruby>騎士<rt>きし</rt></ruby>を'
                    '<ruby>愚弄<rt>ぐろう</rt></ruby>するとは➡<br>いい'
                    '<ruby>度胸<rt>どきょう</rt></ruby>だな｡<br>'
                    '<ruby>貧<rt>まず</rt></ruby>しい<ruby>人<rt>ひと</rt></ruby>を'
                    '<ruby>愚弄<rt>ぐろう</rt></ruby>してはいけない。')
        blocks = CX.split_sentence_html(html_two, 2, [s1, s2])
        check('原句内部两个 <br> 仍切成 2 块（不是 5 块）',
              blocks is not None and len(blocks) == 2, blocks)
        check('第一块保留原句内部换行',
              blocks is not None and blocks[0].count('<br>') == 2, blocks)
        check('第二块只含新句',
              blocks is not None and CX.flatten(blocks[1]) == CX.flatten(s2), blocks)

        print('== 7. --jisho-max-len：只在短候选里挑（长候选即使合格也不选） ==')
        # 短句 ≤10 字，长句 >10 字但同样合格（含目标词、ruby_ok）。
        short_cand = cand('思い込むのは悪い。')          # 9 字
        long_cand = cand('彼は、彼女が幸せだと思いこんでいた。')  # 18 字
        CX.jisho_fetch = with_candidates([long_cand, short_cand])
        pick, why = CX.pick_jisho(card(), Args(jisho_max_len=12, apply_max_len=True))
        check('max_len=12 时只从短候选里挑（长候选被滤掉）',
              pick and pick['jp'] == '思い込むのは悪い。', (pick, why))
        check('过滤后仍过闸门的 reason 为空', why == '', why)

        # 过滤后零候选 → (None, why 含 max-len 字样)
        CX.jisho_fetch = with_candidates([long_cand])
        pick, why = CX.pick_jisho(card(), Args(jisho_max_len=12, apply_max_len=True))
        check('过滤后零候选 → None', pick is None, pick)
        check('why 里写了 jisho-max-len', 'jisho-max-len' in why, why)

        # 不设 jisho_max_len 时行为不变（回归：长短都在场，自动挑选按原逻辑走）
        CX.jisho_fetch = with_candidates([long_cand, short_cand])
        pick, why = CX.pick_jisho(card(), Args())
        check('不设 max_len 时两条都参与挑选（回归）', pick is not None, (pick, why))
    finally:
        CX.jisho_fetch = orig

    print()
    if FAIL:
        print('❌ %d 项失败：%s' % (len(FAIL), ' / '.join(FAIL)))
        return 1
    print('✅ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
