# -*- coding: utf-8 -*-
"""专有名词卡自检器 —— `proper.py` 的硬性规则，与 `check_cards.py` 同一套标签口径。

两个层次，别混：

* `check(entry)`   —— 校验**判定产出**（`gen/output_NN.json` 里的一条）。
  这一层管"卡片内容合不合格"：词形/读音/类别/意思/介绍句/讲解。HTML 只出现在 `a_note`，
  介绍句此时还是**纯文本**（振假名由 `ruby_engine` 之后确定性渲染）。
* `check_card(card)` —— 校验**写入载荷**（`verified.json` 里的一条，字段已按模板拼好）。
  这一层额外管 `Intro`（带 `<ruby>` 的 HTML）、`Categories`（卡面显示用）、`Source`。

用法：
  python check_proper.py data\\vocab\\proper\\<slug>\\gen\\output_01.json
  python check_proper.py <file> --quiet          # 只打印汇总
退出码：0 = 全部合格；1 = 有不合格。
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import check_cards as C  # noqa: E402  ruby / 标签白名单 / 非法字符的唯一实现
import textio  # noqa: E402  UTF-8 stdio 唯一入口
from llm_out import as_bool, as_text, is_boolish  # noqa: E402  模型产出吸收层

KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
#: 读音只收**平假名**（长音符/中点允许）—— 与 check_mine.py 同口径。
#: 片假名不行：泛用读音字段要能直接喂 TTS，且卡面显示的是「怎么读」。
KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30fc\u30fb]+$')
LATIN = re.compile(r'[A-Za-z0-9]')
TAG = re.compile(r'<[^>]+>')
RT_BLOCK = re.compile(r'<rt>.*?</rt>', re.S)

#: 类别枚举 —— 与 code/tools/proper_extract.py 的 CATEGORIES **必须一致**
CATEGORIES = ('人名', '地名', '组织', '概念', '技能', '种族', '称号', '作品名', '其他')

#: `AINote` 的两段（段落名带全角冒号，与卡面 `<b>…：</b>` 一致）
SECTIONS = ('词条', '出处与背景')

TEXT_KEYS = ('word', 'reading', 'meaning', 'intro', 'intro_translation', 'a_note', 'reason')
MAX_INTRO = 160          # 介绍句太长就不像"定义句"了
MAX_MEANING = 80


def sections_hard(html, name='a_note'):
    """段落齐全 + 顺序 + `<p>` 配对（与 check_mine 同一口径，段落名不同）。"""
    hard = []
    if not html:
        return ['%s 为空' % name]
    if not html.strip().startswith('<p>'):
        hard.append('%s 必须以 <p> 开头' % name)
    if html.count('<p>') != html.count('</p>'):
        hard.append('%s 的 <p> 标签不配对' % name)
    pos = []
    for key in SECTIONS:
        marker = '<b>%s：</b>' % key
        if marker not in html:
            hard.append('%s 缺少段落：%s' % (name, key))
        else:
            pos.append(html.find(marker))
    if len(pos) > 1 and pos != sorted(pos):
        hard.append('%s 的段落顺序应为：%s' % (name, ' → '.join(SECTIONS)))
    return hard


def _plain_of(html):
    """可见文本：**先删 `<rt>读音</rt>` 整块**再剥标签。

    只剥标签会把读音留在文本里（`<ruby>姫<rt>ひめ</rt></ruby>屋` → `姫ひめ屋`），
    于是「Intro 里必须出现本词」这类逐字判断会被假报（2026-10-22 实测：13 条汉字词全中）。
    与 `check_cards.text_of` 同一口径。
    """
    return TAG.sub('', RT_BLOCK.sub('', html or ''))


def check(entry):
    """校验一条判定产出。返回 (hard, soft)。"""
    hard, soft = [], []
    if not isinstance(entry, dict):
        return ['条目不是对象：%r' % (entry,)], soft
    for key in TEXT_KEYS:
        v = entry.get(key)
        if v is not None and not isinstance(v, str):
            hard.append('%s 字段类型不是字符串：%s %r' % (key, type(v).__name__, v))
    w = as_text(entry.get('word')).strip()
    if not w:
        return (hard or ['word 为空']), soft
    if not is_boolish(entry.get('include')):
        hard.append('include 不是布尔值：%r' % (entry.get('include'),))
    if LATIN.search(w):
        hard.append('word 含拉丁/数字字符：%r' % w)
    if not (KANJI.search(w) or KANA.search(w)):
        hard.append('word 不含日文字符：%r' % w)
    if '<' in w or '>' in w:
        hard.append('word 含 HTML')
    if not as_bool(entry.get('include')):
        if not as_text(entry.get('reason')).strip():
            hard.append('include=false 但没有 reason')
        return hard, soft

    for key in ('reading', 'meaning', 'intro', 'intro_translation', 'a_note'):
        if not as_text(entry.get(key)).strip():
            hard.append('include=true 但 %s 为空' % key)
    cats = entry.get('categories')
    if not isinstance(cats, (list, tuple)) or not cats:
        hard.append('categories 必须是 1..n 个类别的数组，实际：%r' % (cats,))
        cats = []
    for c in cats:
        if as_text(c) not in CATEGORIES:
            hard.append('category 不在允许集合：%r（允许 %s）' % (c, '/'.join(CATEGORIES)))
    related = entry.get('related')
    if related not in (None, []):
        if not isinstance(related, (list, tuple)):
            hard.append('related 必须是数组：%r' % (related,))
        else:
            for r in related:
                r = as_text(r)
                if not r:
                    continue
                if re.search(r'[<>]', r):
                    hard.append('related 里含 HTML：%r' % r)
                if len(r) > 24:
                    hard.append('related 太长（>24 字）：%r' % r)
    if hard:
        return hard, soft

    if not KANA_ONLY.match(as_text(entry.get('reading'))):
        hard.append('reading 不是纯假名：%r' % entry.get('reading'))

    meaning = as_text(entry.get('meaning'))
    if len(meaning) > MAX_MEANING:
        hard.append('meaning 太长（%d > %d 字）' % (len(meaning), MAX_MEANING))
    for key in ('meaning', 'reading', 'word', 'intro'):
        if re.search(r'[<>]', as_text(entry.get(key))):
            hard.append('%s 里混入了 HTML 标签' % key)

    intro = as_text(entry.get('intro'))
    if w not in intro:
        hard.append('intro 里没有出现本词「%s」（介绍句必须是在介绍它）' % w)
    if len(intro) > MAX_INTRO:
        hard.append('intro 太长（%d > %d 字）' % (len(intro), MAX_INTRO))
    if not intro.endswith(('。', '！', '？')):
        hard.append('intro 应以句末标点结尾：%r' % intro[-12:])

    a = as_text(entry.get('a_note'))
    hard.extend(C.field_hard('a_note', a))
    hard.extend(sections_hard(a))

    # 词条头的 ruby 覆盖（软性）：`<br>` 分段里冒号左边有汉字却没包 ruby
    for seg in re.split(r'<br>', a):
        if '：' not in seg:
            continue
        head = seg.split('：')[0]
        if head.startswith('<p><b>') or head.startswith('<b>'):
            continue
        if KANJI.search(C.outside_ruby(head)):
            soft.append('a_note 词条头可能有未标 ruby 的汉字：%s' % C.outside_ruby(head))
    return hard, soft


def check_card(card):
    """校验一条写入载荷（字段已按模板拼好）。返回 (hard, soft)。"""
    hard, soft = [], []
    if not isinstance(card, dict):
        return ['载荷不是对象：%r' % (card,)], soft
    hard.extend(check(card)[0])

    intro = as_text(card.get('intro_html'))
    if not intro:
        hard.append('Intro（HTML）为空')
    else:
        hard.extend(C.field_hard('Intro', intro))
        plain_intro = _plain_of(intro)
        w = as_text(card.get('word'))
        if w and w not in plain_intro:
            hard.append('Intro 的可见文本里没有「%s」' % w)
        if KANJI.search(plain_intro) and '<ruby>' not in intro:
            hard.append('Intro 含汉字但没有 <ruby>（振假名没渲染上）')
        bare = C.outside_ruby(intro)
        if KANJI.search(bare):
            hard.append('Intro 里有未标 ruby 的汉字：%s' % bare[:24])
        if not plain_intro.rstrip().endswith(('。', '！', '？')):
            hard.append('Intro 应以句末标点结尾：%r' % plain_intro[-12:])
        if intro.count('<p>') != intro.count('</p>'):
            hard.append('Intro 的 <p> 标签不配对')

    cats = card.get('categories') or []
    cat_text = as_text(card.get('categories_text'))
    if not cat_text:
        hard.append('Categories（卡面显示）为空')
    else:
        for c in [x.strip() for x in cat_text.split('/') if x.strip()]:
            if c not in CATEGORIES:
                hard.append('Categories 里有非法类别：%r' % c)
        if [x.strip() for x in cat_text.split('/') if x.strip()] != [as_text(c) for c in cats]:
            hard.append('Categories 文本与 categories 数组不一致：%r vs %r' % (cat_text, cats))

    src = as_text(card.get('source_text'))
    if not src:
        hard.append('Source 为空（至少要有出处）')
    elif not src.startswith('出自'):
        hard.append('Source 应以「出自」开头：%r' % src[:20])
    return hard, soft


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    quiet = '--quiet' in args
    args = [a for a in args if a != '--quiet']
    if not args:
        print('用法：python check_proper.py <gen/output_NN.json> [--quiet]')
        raise SystemExit(2)

    cards, bad_total = [], 0
    for p in args:
        try:
            cards.extend(json.load(open(p, encoding='utf-8')))
        except Exception as exc:
            print('读不了 %s：%s' % (p, exc))
            raise SystemExit(2)

    bad = []
    for c in cards:
        hard, soft = check(c)
        if hard:
            bad.append(((c or {}).get('word') if isinstance(c, dict) else c, hard, soft))
    n_inc = sum(1 for c in cards if isinstance(c, dict) and as_bool(c.get('include')))
    if not quiet:
        for w, hard, soft in bad:
            print('★ %s' % w)
            for m in hard:
                print('    [不合格] %s' % m)
            for m in soft:
                print('    [提醒]   %s' % m)
    print('=' * 70)
    print('总计 %d 条（收录 %d / 排除 %d）—— 合格 %d / 不合格 %d'
          % (len(cards), n_inc, len(cards) - n_inc, len(cards) - len(bad), len(bad)))
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
