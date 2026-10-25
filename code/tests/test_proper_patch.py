# -*- coding: utf-8 -*-
"""回归测试：专有名词卡片的确定性规则（`proper.py` + `check_proper.py`）

不连本地模型、不碰 Anki（`build_index` 那类会连 Anki 的函数一律不调）：

  python code\\tests\\test_proper_patch.py

覆盖：
  1. 集数识别 / 目录名 / 标签拼装（扁平、可多个、**不含 `::`**）
  2. 出处反解（`Source` → work）与去重键
  3. 残差形态过滤（像名字才进）
  4. 首例句落回（第一条真正包含该词的台词）
  5. `check_proper.check()` 的硬/软规则（含反例）
  6. `check_proper.check_card()` 的卡面字段规则（Intro/HTML、Categories、Source）
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'execution'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'tools'))
import textio  # noqa: E402,F401
import check_proper as CP  # noqa: E402
import proper as PR  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def entry(**kw):
    e = {
        'word': 'メリオダス', 'reading': 'めりおだす',
        'categories': ['人名', '称号'],
        'meaning': '梅利奥达斯（《七大罪》主角，〈憤怒の罪〉）',
        'intro': 'メリオダスは「七つの大罪」の主人公である。',
        'intro_translation': '梅利奥达斯是《七大罪》的主角。',
        'a_note': ('<p><b>词条：</b>《七大罪》的主角，〈憤怒の罪〉を背負う騎士。</p>'
                   '<p><b>出处与背景：</b>名字出自亚瑟王传说中的同名骑士。</p>'),
        'related': ['亚瑟王传说'], 'include': True, 'reason': '',
    }
    e.update(kw)
    return e


def card(**kw):
    e = entry()
    c = dict(e)
    c['intro_html'] = ('<ruby>七<rt>なな</rt></ruby>つの<ruby>大罪<rt>たいざい</rt></ruby>の'
                       '<ruby>主人公<rt>しゅじんこう</rt></ruby>、メリオダス。')
    c['categories_text'] = ' / '.join(e['categories'])
    c['source_text'] = '出自「七大罪」第03集｜原句：憤怒の罪のメリオダス'
    c.update(kw)
    return c


def run():
    print('— 集数 / 目录 —')
    check('S01E05 → 第05集',
          PR.episode_of(r'x\Aria The Animation S01E05 (AI transcribed, some errors).srt') == '第05集',
          PR.episode_of(r'x\Aria The Animation S01E05 (AI transcribed, some errors).srt'))
    check('03.jp → 第03集', PR.episode_of('Aria The Animation 03.jp.srt') == '第03集',
          PR.episode_of('Aria The Animation 03.jp.srt'))
    check('--episode 覆盖文件名', PR.episode_of('随便.srt', '第09集') == '第09集')
    check('--work 里的空格不产生空格标签', ' ' not in PR.tag_safe('ARIA The ANIMATION 01'))

    print('— 标签（类别扁平、出处继承动画两层）—')
    tags = PR.build_tags(['人名', '称号'], '动画::水星领航员')
    check('根标签必有', '专有名词' in tags, tags)
    check('多个类别并列', '人名' in tags and '称号' in tags, tags)
    check('出处标签是动画两层', '动画::水星领航员' in tags, tags)
    check('出处不带季度/集数', not any(t.count('::') > 1 for t in tags), tags)
    check('不写批次/日期标签', not any('批次' in t for t in tags), tags)
    check('只有出处标签带 ::', [t for t in tags if '::' in t] == ['动画::水星领航员'], tags)
    check('非法类别不进标签', '不存在' not in PR.build_tags(['不存在'], '动画::X'))
    check('重复值去重', len(tags) == len(set(tags)), tags)
    check('从标签反解出处',
          PR.work_tag_from_tags(['专有名词', '人名', '动画::水星领航员',
                                 '专有名词-批次-20261022']) == '动画::水星领航员',
          PR.work_tag_from_tags(['专有名词', '人名', '动画::水星领航员',
                                 '专有名词-批次-20261022']))
    check('非动画出处就是裸名',
          PR.work_tag_from_tags(['专有名词', '亚瑟王传说']) == '亚瑟王传说')
    check('去重键 = (词形, 出处标签)，建卡/写库共用一个',
          PR.card_key('藍華', '动画::水星领航员') == ('藍華', '动画::水星领航员'),
          PR.card_key('藍華', '动画::水星领航员'))
    check('同名不同出处 → 不同键',
          PR.card_key('メリオダス', '动画::七大罪') != PR.card_key('メリオダス', '亚瑟王传说'))

    print('— 出处反解 / 去重键 —')
    src = '出自「水星领航员」第01集｜原句：アリシアさん'
    check('Source 反解作品名', PR.work_of_source(src) == '水星领航员', PR.work_of_source(src))
    check('解析不了给空串', PR.work_of_source('随便写的') == '')
    key_a = ('めりおだす', PR.tag_safe('七大罪'))
    key_b = ('めりおだす', PR.tag_safe('亚瑟王传说'))
    check('去重键含出处（同名两作品不是同一张卡）', key_a != key_b, (key_a, key_b))

    print('— 残差形态 —')
    check('片假名 ≥3 算名字', PR.name_like('メリオダス'))
    check('纯汉字 ≥2 算名字', PR.name_like('重盛'))
    check('动词残差不算名字', not PR.name_like('漕ぐ'))
    check('含假名的混合残差不算名字', not PR.name_like('訪ね'))
    check('单字汉字不算名字', not PR.name_like('千'))

    print('— 敬称 / 已知词判据 —')
    check('敬称去掉（1 字词干也去）', PR.strip_honorific('晃さん') == '晃',
          PR.strip_honorific('晃さん'))
    check('ちゃん 也去', PR.strip_honorific('アイちゃん') == 'アイ')
    check('职务不是敬称（保留原样）', PR.strip_honorific('アリア社長') == 'アリア社長')
    check('纯假名名字不被 kata2hira 误杀',
          PR.known_hit('アンナ', {'あんな': 'N4'}, {'アンナ': 'あんな'}) is None)
    check('含汉字的活用形仍算已存在',
          PR.known_hit('食べ', {'食べる': 'N5'}, {'食べ': '食べる'}) == '食べる')

    print('— 首例句落回 —')
    cand = {'occurrences': [
        {'plain': '気持ちを届けるのはシルフさんたちのお仕事', 'episode': '第01集'},
        {'plain': 'これはシングルの実力よ', 'episode': '第02集'},
    ]}
    occ = PR.sentence_for_card(cand, {'word': 'シングル'})
    check('取第一条真正含该词的台词', occ['episode'] == '第02集', occ)
    check('找不到就退回第一条',
          PR.sentence_for_card(cand, {'word': 'アリシア'})['episode'] == '第01集')

    print('— check_proper.check —')
    hard, _ = CP.check(entry())
    check('合格条目无硬问题', not hard, hard)
    hard, _ = CP.check(entry(reading='メリオダス'))
    check('读音不是平假名 → 拦', any('纯假名' in x for x in hard), hard)
    hard, _ = CP.check(entry(categories=['人物']))
    check('非法类别 → 拦', any('category' in x for x in hard), hard)
    hard, _ = CP.check(entry(a_note='<p><b>词条：</b>只有一段</p>'))
    check('缺「出处与背景」段 → 拦', any('出处与背景' in x for x in hard), hard)
    hard, _ = CP.check(entry(a_note=entry()['a_note'].replace('</p>', '') + '"'))
    check('半角双引号 → 拦', any('半角双引号' in x for x in hard), hard)
    hard, _ = CP.check(entry(intro='これは別の騎士の話である。'))
    check('介绍句不含本词 → 拦', any('没有出现本词' in x for x in hard), hard)
    hard, _ = CP.check(entry(intro='メリオダスは主人公'))
    check('介绍句没有句末标点 → 拦', any('句末标点' in x for x in hard), hard)
    hard, _ = CP.check(entry(include=False, reason=''))
    check('include=false 无 reason → 拦', any('reason' in x for x in hard), hard)
    hard, _ = CP.check(entry(include=False, reason='碎片'))
    check('include=false 有 reason → 放行', not hard, hard)

    print('— check_proper.check_card —')
    hard, _ = CP.check_card(card())
    check('合格卡面无硬问题', not hard, hard)
    bad_card = card(intro_html='<ruby>七<rt>なな</rt></ruby>つの大罪の主人公、メリオダス。')
    hard, _ = CP.check_card(bad_card)
    check('Intro 有汉字没 ruby → 拦', any('未标 ruby' in x for x in hard), hard)
    hard, _ = CP.check_card(card(categories_text='人名'))
    check('Categories 文本与数组不一致 → 拦', any('不一致' in x for x in hard), hard)
    hard, _ = CP.check_card(card(source_text='七大罪 第03集'))
    check('Source 不以「出自」开头 → 拦', any('出自' in x for x in hard), hard)

    print()
    if FAIL:
        print('失败 %d 项：%s' % (len(FAIL), '、'.join(FAIL)))
        return 1
    print('全部通过。')
    return 0


if __name__ == '__main__':
    sys.exit(run())
