# -*- coding: utf-8 -*-
"""core6000 补例句②的机械闸门 1-5：拿到模型产出就能判的那五道。

从 ``execution/core6000_example.py`` 抽出（2026-11-02，Issue #4「按能力切分超大流程
文件」）。契约文档：docs/core6000-example-design.md §6——这五道判的是**模型刚交回来的
entry**（新句含不含目标词、长度进不进闸门、中文/讲解齐不齐），不吃卡片的写库现场，
所以能和 gen 的流程分开、单独测。

``gate_apply``（闸门 6-9）仍留在巨石里：它拿的是 ``live_values`` 读回来的**写库前**
状态，和 apply 的事务绑在一起，不属于这块能力。

口径一字未改。**调用约定同 ``core6000_jisho``**：跨函数调用走 ``_CE()``（见该模块的
说明），保证测试照旧能对巨石上的别名打补丁。目标词的活用形展开在
``core6000_jisho``（例句源也要用它挑「写出汉字」的那句）。
"""
import os
import re
import sys
import unicodedata

# 系列子目录（issue #12）：单独 import 时自己挂上 code/common 与本系列目录。
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(os.path.dirname(os.path.dirname(_HERE)), 'common'), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from htmltext import strip_tags
from ruby_text import KANJI
from core6000_text2 import (RE_RT, RE_RUBY, RE_WS, SCOPE_MERGE, clean_malformed_ruby,
                            flatten, one_line, plain, ruby_covers)  # noqa: F401
# 闸门 2 的新句长度区间：真值在 core6000_jisho（例句源与这里都要判同一个区间）。
from core6000_jisho import SENT_MAX, SENT_MIN  # noqa: E402


def _CE():
    """跨函数调用一律走这里：巨石 import 本模块后，这些名字的真身在它的全局表里，
    测试 ``CX.jisho_fetch = fake`` 才照样拦得住（拆分前它们本来就同一个命名空间）。

    单独 import 本模块（测试 / 探针）时巨石还没加载，就直接调本模块里的实现。
    """
    return sys.modules.get('core6000_example') or sys.modules[__name__]


# ============================================================================
# 机械闸门 1-5（gen 阶段：拿到模型产出就能判的）
# ============================================================================
def check_sentence_ruby(plain_text, ruby_html, label):
    """契约闸门 3/4：ruby 去 ruby 后等于原句；有汉字就必须有合规 ruby。"""
    problems = []
    if flatten(ruby_html) != flatten(plain_text):
        problems.append('%s：去 ruby 后与正文不一致（ruby=%r）'
                        % (label, one_line(ruby_html, 60)))
    if KANJI.search(plain_text or '') and '<ruby' not in (ruby_html or '').lower():
        problems.append('%s：含汉字但没有 <ruby>' % label)
    elif (ruby_html or '').strip() and not ruby_covers(ruby_html):
        problems.append('%s：振假名不合规（有 ruby 缺 <rt> / 基底只含假名 / 有汉字漏注音）' % label)
    return problems


def check_sentence2_ruby(card, entry):
    """闸门 5b：卡上已有两条例句、第二句缺/坏振假名时，`sentence2_ruby` 必须合规。

    口径与 `sentence1_ruby` 对称（闸门 3/4）：**去 ruby 后必须与卡上第二句逐字一致**
    （`check_sentence_ruby` 的第一条就是干这个的），并且每个 `<ruby>` 都有 `<rt>`、
    基底不得只含假名、ruby 之外不得再有汉字。
    这里**只用模型值**，不回退到 `new_sentence_ruby`：模型一旦改写了那句，
    宁可拒绝这张卡（丢用户的原句比跳过更糟）。
    """
    if card['n_sent'] < 2 or not card['need_ruby2']:
        return []                                   # 不适用：没有第二句 / 第二句振假名本来就合规
    if not entry['sentence2_ruby']:
        return ['闸门5b：need_sentence2_ruby=true 但 sentence2_ruby 是空的']
    return _CE().check_sentence_ruby(card['sentences'][1]['jp'], entry['sentence2_ruby'], 'sentence2_ruby')


def kana_norm(text):
    """读音比对用的归一化：NFKC + 去空白 + 片假名→平假名。"""
    s = unicodedata.normalize('NFKC', text or '')
    s = RE_WS.sub('', s)
    return ''.join(chr(ord(ch) - 0x60) if '\u30a1' <= ch <= '\u30f6' else ch for ch in s)


def word_reading_in_ruby(word, ruby_html):
    """从 `new_sentence_ruby` 里抽出**目标词**的读音；抽不出（判不了）返回 ''。

    只有能**确定**这个词的读音时才返回内容：要么某个 `<ruby>` 的基底正好是目标词，
    要么目标词被一串 `<ruby>` 基底按顺序完整拼出来（逐字标音那种）。
    拼不齐（例如「受付ける」只标了 `受`+`付`）就返回 '' —— 判不了就不警告，宁可漏报。
    """
    h = clean_malformed_ruby(ruby_html or '')
    if not word or not h:
        return ''
    pairs = []
    for inner in RE_RUBY.findall(h):
        m = re.search(r'<rt\b[^>]*>(.*?)</rt>', inner, re.S | re.I)
        if not m:
            continue
        base = strip_tags(RE_RT.sub('', inner)).strip()
        rt = strip_tags(m.group(1)).strip()
        if base:
            pairs.append((base, rt))
    for base, rt in pairs:                 # 一词一 ruby
        if base == word:
            return rt
    joined, rts = '', []                   # 逐字标音：基底按顺序拼成目标词
    for base, rt in pairs:
        if base and word.startswith(joined + base):
            joined += base
            rts.append(rt)
            if joined == word:
                return ''.join(rts)
    return ''


def target_word_warnings(card, entry):
    """目标词读音 / 义项行的**便宜检查**（警告，不是闸门：误报绝不拦卡）。

    1. 新句里出现了目标词，而它在 `new_sentence_ruby` 里被注的读音与卡上 `reading`
       对不上 → 同一张卡里出现了第二种读音。
    2. `new_word_gloss` 里没有目标词那一行 → ② 的义项行只能用卡上的 `Meaning` 兜底，
       看不出新句实际用的是哪个义项（提示词要求模型把实际用的义项写进那一行）。
    """
    out = []
    word, reading = card['word'], card['reading']
    if word and reading and flatten(word) and flatten(word) in flatten(entry['new_sentence']):
        got = _CE().word_reading_in_ruby(word, entry['new_sentence_ruby'])
        if got and _CE().kana_norm(got) != _CE().kana_norm(reading):
            out.append('target_reading_mismatch：新句里「%s」注的是「%s」，卡上 reading 是「%s」'
                       % (word, got, reading))
    if word and not any(g['w'] == word for g in entry['new_word_gloss']):
        out.append('target_gloss_missing：new_word_gloss 里没有目标词「%s」那一行，'
                   '② 的义项行只能用卡上 Meaning 兜底' % word)
    contrast = entry.get('contrast') or ''
    if contrast and not ('①' in contrast and '②' in contrast):
        out.append('contrast_format：contrast 要求写成「①是…，②是…」，'
                   '现在是「%s」' % one_line(contrast, 40))
    return out


def gate_gen(card, entry, scopes=None):
    """闸门 1-5（契约 §6）。返回 (问题列表, 警告列表)。

    注意闸门 1/2 只对**模型造的新句**有意义：原卡已有两条例句时，`new_sentence` 只是
    把卡上第二句原样重复（用来对齐振假名与 ② 讲解），那一句是卡里的既有数据
    （可能本来就不含目标词，如「する」的第二句「…サッカーをしている」），
    拿闸门 1 去卡它属于误伤。

    `scopes` = 本次 `--only` 选定的范围。`core1/grammar1/conjugation1/context1` 这四个键
    是**契约 §5.3 的 not-merged 扩展**（那个范围里 ① 也要模型产出，且默认不参与）：
    只有真的在跑 not-merged 时才是硬要求。默认范围里处理一张 `unmerged` 的卡时，
    渲染的 ① 用的是**卡里原有的板块正文**（`section_body_html` 的 `orig`），这四个键
    根本不参与渲染 —— 所以这里按范围判，而不是按卡判（`scopes=None` = 不知道范围，从严）。
    """
    p, warn = [], []
    jp = plain(entry['new_sentence'])
    ruby = entry['new_sentence_ruby']
    n_chars = RE_WS.sub('', jp)
    if card['n_sent'] == 1:
        # 1 目标词必须出现
        if not any(f in jp for f in _CE().target_forms(card)):
            p.append('闸门1：新句里没有目标词「%s」' % card['word'])
        # 2 长度 + 与原句不同
        if not (SENT_MIN <= len(n_chars) <= SENT_MAX):
            p.append('闸门2：新句长度 %d 字（要求 %d–%d）' % (len(n_chars), SENT_MIN, SENT_MAX))
        if card['sentences'] and flatten(jp) == flatten(card['sentences'][0]['jp']):
            p.append('闸门2：新句与第一句完全相同')
    else:
        # 已有两条例句：new_sentence 必须原样用卡上第二句（缺它的振假名时是硬要求）
        want = card['sentences'][1]['jp']
        if flatten(jp) != flatten(want):
            if card['need_ruby2']:
                p.append('闸门2：原卡已有两条例句且第二句没有可用振假名，new_sentence 必须原样用'
                         '第二句「%s」，实际是「%s」' % (one_line(want, 40), one_line(jp, 40)))
            else:
                warn.append('sentence2_mismatch：② 讲的和卡上第二句不是同一句'
                            '（卡上第二句「%s」）' % one_line(want, 40))
    # 3/4 ruby 一致性
    if not ruby:
        p.append('闸门3：new_sentence_ruby 是空的')
    else:
        p.extend(_CE().check_sentence_ruby(jp, ruby, 'new_sentence_ruby'))
    # 5 句①振假名（需要时）
    if card['need_ruby1'] and card['sentences']:
        s1 = card['sentences'][0]['jp']
        if not entry['sentence1_ruby']:
            p.append('闸门5：need_sentence1_ruby=true 但 sentence1_ruby 是空的')
        else:
            p.extend(_CE().check_sentence_ruby(s1, entry['sentence1_ruby'], 'sentence1_ruby'))
    # 5b 句②振假名（已有两条例句、且第二句缺/坏振假名时）
    if card['n_sent'] >= 2 and card['need_ruby2']:
        p.extend(_CE().check_sentence2_ruby(card, entry))
    # ② 讲解必须齐（否则渲染出来的 ② 是空的）
    for key, name in (('cn2', '新句中文 cn2'), ('grammar2', '语法要点 grammar2'),
                      ('conjugation2', '动词变形解析 conjugation2'),
                      ('context2', '语境与表达风格 context2'), ('contrast', '两句对比 contrast')):
        if not entry[key]:
            p.append('%s 是空的' % name)
    if card['unmerged'] and (scopes is None or SCOPE_MERGE in scopes):
        for key in ('core1', 'grammar1', 'conjugation1', 'context1'):
            if not entry[key]:
                p.append('not-merged 范围缺 %s' % key)
    if not card['sentences'][0]['cn'] and not entry['cn1']:
        p.append('cn1 是空的（原卡没有中文翻译时必须给）')
    # 便宜检查（警告，不拦卡）：目标词读音是否和 reading 一致 / ② 有没有给义项行
    warn.extend(_CE().target_word_warnings(card, entry))
    return p, warn
