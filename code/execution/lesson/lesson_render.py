# -*- coding: utf-8 -*-
"""每日讲义的渲染层：manifest + 模型产出 → 那份给人读的 Markdown。

从 ``execution/today_new.py`` 抽出（2026-11-02，Issue #4「按能力切分超大流程文件」）。
搬过来的是**纯渲染 + 落盘**这一段：给它卡片清单和每卡的 ``teach``，它拼出整份讲义；
不调模型、不查 JMdict、不碰 Anki（词典结果由调用方当 ``dinfo`` 传进来）。

留在 ``today_new`` 的是流程：取卡（AnkiConnect）、切批、直连本地模型、断点续跑。
机械判定在 ``lesson_check``，文本整形在 ``lesson_text``，路径与原子写在 ``lesson_paths``
——后两者是为了让 ``today_new → lesson_render`` 保持单向依赖，不互相 import。

口径一字未改；``today_new`` 仍以同名模块级别名导出这些函数（测试与探针脚本照旧用
``TN.render_lesson``）。
"""
import os
import re
import sys

# 系列子目录（issue #12）：单独 import 时自己挂上 code/common 与本系列目录。
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(os.path.dirname(os.path.dirname(_HERE)), 'common'), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lesson_paths import (LESSON_BACKUP, TAG_TODAY, dated_paths, write_text)
# 机械判定（词形/读音/词性、内容问题、闸门）：实现在 execution/lesson/lesson_check.py。
from lesson_check import (FINAL_PARTICLE_WORDS, INTERJECTION_WORDS, check_coverage,
                          check_render, display_pos, group_vocab, light_card_issues,
                          reading_problem)
# 文本整形与 teach 渲染：execution/lesson/lesson_text.py。
from lesson_text import (clean_structure, grammar_structure, render_teach,
                         structure_looks_garbled)


def clip_sentence(text, limit=160):
    """取第一句/第一行，超长时按**句末标点**截断（绝不截在半个词上）。"""
    line = re.split(r'\n', (text or '').strip())[0]
    line = re.sub(r'\s+', ' ', line).strip()
    if len(line) <= limit:
        return line
    cut = 0
    for m in re.finditer(r'[。！？!?]', line[:limit]):
        cut = m.end()
    if cut < 20:
        cut = line.rfind('、', 0, limit)
        if cut > 20:
            cut += 1
    if cut < 20:
        return line[:limit] + '…（后略）'
    return line[:cut] + '（后略）'


def _sentence_warnings(word, points, jp_ruby):
    """make_card 里用：只拿刚拼好的要点和句子做检查，不必构造整张卡。"""
    return light_card_issues({'word': word,
                              'light': {'points': points, 'jp_ruby': jp_ruby}})


def light_sentences(card):
    """按卡模板序号挑出今天真正会看到的那几句例句。

    这套语法例句模型的模板就是「第 N 句例句」的展示卡（Card 02 = 例句①，…），
    所以 ord=N → Sentence{N}；ord=0 是解释卡（全句都列）。
    """
    sents = card.get('sentences') or []
    ords = sorted({o for o in (card.get('card_ords') or []) if o > 0})
    if not ords:
        return sents
    out = [sents[o - 1] for o in ords if 1 <= o <= len(sents)]
    return out or sents


def cell(text):
    """Markdown 表格单元格：竖线换全角、换行压平，空值显示 —。"""
    t = re.sub(r'\s+', ' ', str(text or '')).strip()
    return t.replace('|', '｜') or '—'


def render_light_card(card, A):
    """轻量渲染一条例句卡：句子（带振假名）+ 中文 + 要点一行，内容全部来自卡片本身。"""
    light = card.get('light') or {}
    if card['kind'] == 'sentence':
        A('### %s' % card['word'])
        A('')
        if light.get('jp_ruby'):
            A(light['jp_ruby'])
            A('')
        if light.get('cn'):
            A('中文：%s' % light['cn'])
            A('')
        for p in light.get('points') or []:
            A('- %s' % p)
        # warnings 在 plan 时算过一次；旧 manifest 里没有就现算（merge 老卡片数据也不漏）。
        warns = light.get('warnings')
        if warns is None:
            warns = light_card_issues(card)
        for w in warns or []:
            A('- ⚠️ %s（讲解来自卡片 AINote，建议核对或补全后改卡）' % w)
        if light.get('points') or warns:
            A('')
        if light.get('source'):
            A('*%s*' % light['source'])
            A('')
        return
    # 语法例句卡
    A('### %s　`%s`' % (card['word'], card['level']))
    A('')
    head = '中文 **%s**' % (card['meaning'] or '—')
    struct = clean_structure(card.get('pos') or '')
    if struct and not structure_looks_garbled(struct):
        head += '｜接续 %s' % struct
    A(head)
    A('')
    sents = light_sentences(card)
    if sents:
        A('**今天要看的 %d 句**' % len(sents))
        A('')
        for s in sents:
            A('- %s%s' % (s['ruby'] or s['jp'], ('　—— ' + s['cn']) if s['cn'] else ''))
        A('')
    for p in light.get('points') or []:
        A('**要点**：%s' % p)
        A('')
    warns = light.get('warnings')
    if warns is None:
        warns = light_card_issues(card)
    for w in warns or []:
        A('> ⚠️ %s（要点来自卡片自带讲解，建议核对后改卡）' % w)
        A('')


def dict_card(dinfo, card):
    """取某张卡的词典核验结果（没有就返回空 dict）。"""
    return (dinfo or {}).get(str(card.get('id'))) or {}


def dict_reading_issue(dinfo, card):
    """卡片读音被 JMdict 判成错时返回那条 issue；否则 None。"""
    for iss in dict_card(dinfo, card).get('issues') or []:
        if iss.get('field') == 'reading' and iss.get('level') == 'error':
            return iss
    return None


def render_lesson(manifest, lesson, dinfo=None):
    """渲染讲义。

    `dinfo` = {卡片 id: jmdict_check.check_card() 结果}；给了就用词典校正
    词性、隐藏读音错误并就地标注；不给则退回纯卡片字段（旧行为）。
    """
    cards = manifest['cards']
    counts = manifest['counts']
    vocab = [c for c in cards if c['kind'] == 'vocab']
    grammar = [c for c in cards if c['kind'] == 'grammar' and c.get('style') != 'light']
    light = [c for c in cards if c['kind'] == 'sentence' or
             (c.get('style') == 'light' and c['kind'] != 'sentence')]
    entries = (lesson or {}).get('entries', {}) or {}
    date = manifest['date']

    # 口径：先按「讲义条目」分组，所有计数都从这里派生 —— 开头的数字、表格行数、
    # 来源表的合计必须是同一份数据算出来的（复审点名的「5 / 5 / 7 组」对不上就出在这）。
    vgroups = group_vocab(vocab)
    video = [c for c in light if c['kind'] == 'sentence']
    gram_ex = [c for c in light if c['kind'] != 'sentence']
    n_v, n_g = len(vgroups), len(grammar)
    n_v_cards = sum(1 + len(v) for _, v in vgroups)
    n_merged = sum(len(v) for _, v in vgroups)
    n_sent = sum(len(light_sentences(c)) for c in gram_ex) + len(video)
    n_entries = n_v + n_g + len(light)
    n_notes = sum(st.get('taken_notes', st['taken']) for st in manifest['decks'])
    pos_fixed, pos_fixed_dict, dirty_struct, bad_reading = [], [], [], []
    parts = []
    A = parts.append

    A('# 今日讲义 · %s' % date)
    A('')
    if manifest.get('mode') == 'tag':
        A('> 今天的 %d 个词来自 tag `%s`（由 `jp-anki-today-new` 从当天字幕选出、'
          '全量替换；没有这个 tag 的日子不生成讲义）。' % (len(vocab), TAG_TODAY))
        A('')
    if grammar or light:
        A('共 %d 张卡（词汇 %d / 语法 %d / 例句 %d）｜%d 条讲解'
          '（词汇 %d · 语法 %d · 例句卡 %d 组 / %d 句）｜生成于 %s'
          % (counts['total'], counts['vocab'], counts['grammar'], counts.get('sentence', 0),
             n_entries, n_v, n_g, len(light), n_sent, manifest['generated_at']))
    else:
        A('共 %d 张卡｜%d 条讲解（词汇 %d 条）｜生成于 %s'
          % (counts['total'], n_entries, n_v, manifest['generated_at']))
    A('')
    if lesson and lesson.get('intro'):
        A(lesson['intro'])
        A('')

    # ---- 导航：先扫一遍 ----
    A('## 今日一览')
    A('')
    if vgroups:
        A('**词汇 %d 条 / %d 张卡**' % (n_v, n_v_cards))
        A('')
        A('| # | 词形 | 读音 | 词性 | 释义 | 级别 |')
        A('|---|---|---|---|---|---|')
        for i, (c, variants) in enumerate(vgroups, 1):
            names = []
            for item in [c] + variants:
                if item['word'] not in names:
                    names.append(item['word'])
            rp = reading_problem(c['word'], c.get('reading') or '')
            drp = dict_reading_issue(dinfo, c)
            pos, _fixed = display_pos(c, dict_card(dinfo, c))
            A('| %d | %s | %s | %s | %s | %s |'
              % (i, cell(' / '.join(names)),
                 cell('—' if (rp or drp) else (c.get('reading') or '')),
                 cell(pos), cell(c.get('meaning') or ''), cell(c.get('level') or '')))
        A('')
    if grammar:
        A('**语法点 %d 条 / %d 张卡**（语法单元的例句卡在「例句卡」一节展开）' % (n_g, len(grammar)))
        A('')
        A('| # | 句型 | 中文 | 接续 | 级别 |')
        A('|---|---|---|---|---|')
        for i, c in enumerate(grammar, 1):
            teach = (entries.get(str(c['id'])) or {}).get('teach') or {}
            struct, _st = grammar_structure(c, teach)
            A('| %d | %s | %s | %s | %s |'
              % (i, cell(c['word']), cell(c.get('meaning') or ''),
                 cell(struct), cell(c.get('level') or '')))
        A('')
    if light:
        A('**例句卡 %d 组 / %d 句**（视频例句 %d 组 · 语法例句卡 %d 组）'
          % (len(light), n_sent, len(video), len(gram_ex)))
        A('')
        A('| # | 例句卡 | 中文 | 卡数 |')
        A('|---|---|---|---|')
        for i, c in enumerate(light, 1):
            A('| %d | %s | %s | %s |'
              % (i, cell(c['word']), cell(c.get('meaning') or ''), cell(c.get('n_cards') or 1)))
        A('')
    A('> 口径：「张卡」按卡数；「条讲解」按讲义条目'
      '（同词形的平/片假名条目已合并）。以上各节小标题加起来 = 开头的「%d 条讲解」。' % n_entries)
    A('')

    # ---- 正文：词表 ----
    if vgroups:
        A('## 词表')
        A('')
        for primary, variants in vgroups:
            teach = (entries.get(str(primary['id'])) or {}).get('teach') or {}
            if not teach:
                for v in variants:
                    alt = (entries.get(str(v['id'])) or {}).get('teach') or {}
                    if alt:
                        teach = alt
                        break
            names = []
            for item in [primary] + variants:
                if item['word'] not in names:
                    names.append(item['word'])
            raw_reading = primary.get('reading') or ''
            dcard = dict_card(dinfo, primary)
            rp = reading_problem(primary['word'], raw_reading)
            drp = dict_reading_issue(dinfo, primary)
            if rp:
                bad_reading.append((primary['word'], raw_reading, rp))
            A('### %s%s　`%s`' % (' / '.join(names),
                                 '（%s）' % raw_reading if raw_reading and not (rp or drp) else '',
                                 primary['level']))
            A('')
            pos, fixed = display_pos(primary, dcard)
            if fixed:
                pos_fixed.append(primary['word'])
                if dcard.get('pos_fix'):
                    pos_fixed_dict.append((primary['word'], pos))
            A('%s｜**%s**' % (pos or '—', primary.get('meaning') or '—'))
            A('')
            if rp or drp:
                bits = []
                if rp:
                    bits.append('卡片读音字段写「%s」，与词形「%s」对不上：%s'
                                % (raw_reading, primary['word'], rp))
                if drp:
                    bits.append('JMdict 判定：%s' % drp['message'])
                A('> ⚠️ %s。已隐藏读音；这张卡可能挖错了，'
                  '建议回 Anki 把词形／读音／释义三者对一遍。' % '；'.join(bits))
                A('')
            if variants:
                same = [v['word'] for v in variants if v['word'] != primary['word']]
                if same:
                    A('> 表记变体：%s（同一个词；Anki 里是多张卡，讲义合并为一条）'
                      % '、'.join(same))
                else:
                    A('> 重复卡：Anki 里同一词形有 %d 张（讲义合并为一条）' % (1 + len(variants)))
                A('')
            lines = render_teach(primary, teach)
            if lines:
                A('\n'.join(lines))
            else:
                A('> ⚠️ 本次没有为这张卡生成讲解。')
                A('')
        if pos_fixed:
            hard = [w for w in pos_fixed if w not in {x for x, _p in pos_fixed_dict}]
            note = '> 词性说明：%s 的词性已按语言事实校正' % '、'.join(pos_fixed)
            # 只列今天这批卡里实际走了硬编码兜底表的词；
            # 别把 INTERJECTION_WORDS 全表（如「よし」）抄进脚注——卡里没有它，列出来就是误导
            interj = sorted({w for w in hard if w in INTERJECTION_WORDS})
            finp = sorted({w for w in hard if w in FINAL_PARTICLE_WORDS})
            bits = []
            if finp:
                bits.append('`%s`＝终助词' % '／'.join(finp))
            if interj:
                bits.append('`%s`＝感叹词' % '／'.join(interj))
            if bits:
                note += '（%s）' % '，'.join(bits)
            if pos_fixed_dict:
                note += '；其中 %s 由 JMdict 判定（词典词性：%s）' % (
                    '、'.join(w for w, _p in pos_fixed_dict),
                    '／'.join(sorted({p for _w, p in pos_fixed_dict})))
            note += '；Anki 词性字段里写的是「%s」，建议回改卡片。' % (
                '／'.join(sorted({(c.get('pos') or '空') for c in vocab
                                  if c['word'] in pos_fixed})) or '空')
            A(note)
            A('')

    # ---- 正文：语法 ----
    if grammar:
        A('## 语法')
        A('')
        for c in grammar:
            teach = (entries.get(str(c['id'])) or {}).get('teach') or {}
            struct, st = grammar_structure(c, teach)
            if st == 'dirty':
                dirty_struct.append(c['word'])
            A('### %s　`%s`' % (c['word'], c['level']))
            A('')
            A('中文 **%s**%s｜来自 `%s`'
              % (c.get('meaning') or '—',
                 '｜接续 %s' % struct if struct else '',
                 c['deck_short']))
            A('')
            if st == 'dirty':
                A('> ⚠️ 这张卡的接续字段是脏数据（汉字夹着注音），已显示为「—」；'
                  '补跑 `gen --only-words "%s" --restart` 让模型重新整理。' % c['word'])
                A('')
            lines = render_teach(c, teach)
            if lines:
                A('\n'.join(lines))
            else:
                A('> ⚠️ 本次没有为这张卡生成讲解。')
                A('')
            A('**Anki 自带例句**')
            A('')
            if c['sentences']:
                for s in c['sentences']:
                    A('- %s' % (s['ruby'] or s['jp']))
                    if s['cn']:
                        A('  - %s' % s['cn'])
            else:
                A('- （这张卡没有配例句）')
            A('')

    if light:
        A('## 例句卡')
        A('')
        A('**共 %d 组 / %d 句**：视频例句 %d 组 · 语法例句卡 %d 组 %d 句'
          % (len(light), n_sent, len(video), len(gram_ex), n_sent - len(video)))
        A('')
        A('> 这些卡自带讲解（视频例句的 AINote / 语法例句的结论），这里只列今天要看的内容，'
          '不另写讲解。')
        A('')
        for c in light:
            render_light_card(c, A)

    A('## 今日自测')
    A('')
    A('1. 合上讲义，把上面每个词/句型的中文意思默写一遍。')
    A('2. 每个词自己想一个句子，再对照讲义的「例句」。')
    A('3. 打开 Anki 学这批卡时，注意哪些是刚才没记住的，记下来明天回看。')
    A('')
    A('## 本讲义的卡片来源')
    A('')
    tag_mode = manifest.get('mode') == 'tag'
    if tag_mode:
        A('| 卡型 | 词汇卡组（deck） | 模型 | 今日取词（张） | 笔记（条） | 来源 |')
        A('|---|---|---|---|---|---|')
    else:
        A('| 卡型 | 学习单元（deck） | 模型 | 今日取卡（张） | 笔记（条） | 上限 | 上限来源 |')
        A('|---|---|---|---|---|---|---|')
    for st in manifest['decks']:
        if tag_mode:
            A('| %s | %s | %s | %d | %d | tag:「%s」 |'
              % ({'vocab': '词汇', 'grammar': '语法', 'sentence': '例句'}.get(st['kind'],
                                                                              st['kind']),
                 cell(st['deck'].replace('0-日本语学习::', '')), cell(st.get('model') or ''),
                 st['taken'], st.get('taken_notes', st['taken']), TAG_TODAY))
        else:
            A('| %s | %s | %s | %d | %d | %s | %s |'
              % ({'vocab': '词汇', 'grammar': '语法', 'sentence': '例句'}.get(st['kind'],
                                                                              st['kind']),
                 cell(st['deck'].replace('0-日本语学习::', '')), cell(st.get('model') or ''),
                 st['taken'], st.get('taken_notes', st['taken']), st.get('limit', '—'),
                 cell(st.get('limit_source', ''))))
    if tag_mode:
        A('| 合计 | — | — | %d | %d | — |' % (counts['total'], n_notes))
    else:
        A('| 合计 | — | — | %d | %d | — | — |' % (counts['total'], n_notes))
    A('')
    if tag_mode:
        A('> 本讲义 %d 条讲解 = 词汇 %d 条（%d 张卡，同词形合并 %d 条）。'
          % (n_entries, n_v, n_v_cards, n_merged))
        A('> 取词口径 = 全库 tag:「%s」——词由 `jp-anki-today-new` 从当天字幕选出并全量替换；'
          '没有这个 tag 的日子不生成讲义。' % TAG_TODAY)
    else:
        A('> 本讲义 %d 条讲解 = 词汇 %d 条（%d 张卡，同词形合并 %d 条）＋ 语法 %d 条 ＋ 例句卡 %d 组。'
          % (n_entries, n_v, n_v_cards, n_merged, n_g, len(light)))
        A('> 取卡口径 = 旧版「Anki 今日新卡队列」（按 deck 日上限；2026-10-28 起不再使用）。')
    A('> 退路：讲义只是文本，删掉重跑即可；本脚本从不写 Anki。')
    A('')
    return '\n'.join(parts)


def merge_and_render(manifest, lesson, tag='merge', dinfo=None):
    """闸门 + 渲染 + 落盘。缺卡就报错，不写讲义。"""
    p = dated_paths(manifest['date'])
    problems = check_coverage(manifest, lesson)
    text = render_lesson(manifest, lesson, dinfo)
    problems.extend(check_render(text, manifest))
    if problems:
        print('%s 未通过闸门，没有写讲义：' % tag, file=sys.stderr)
        for t in problems:
            print('  - ' + t, file=sys.stderr)
        return 1, None
    if LESSON_BACKUP and os.path.exists(p['lesson_md']):
        os.replace(p['lesson_md'], p['lesson_md'] + '.bak')
    write_text(p['lesson_md'], text)
    write_text(p['lesson_latest'], text)
    print('%s：讲义已生成 → %s' % (tag, p['lesson_md']))
    cnt = manifest['counts']
    print('  %d 张卡 / %d 条笔记全部覆盖（词汇 %d / 语法 %d / 例句 %d），共 %d 字'
          % (cnt['total'], cnt.get('entries', len(manifest['cards'])), cnt['vocab'],
             cnt['grammar'], cnt.get('sentence', 0), len(text)))
    return 0, p['lesson_md']
