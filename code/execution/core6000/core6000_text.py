# -*- coding: utf-8 -*-
"""core6000 补例句②的纯渲染：词性 / 注音 / 词表，只拼字符串。

从 ``execution/core6000_example.py`` 抽出（2026-11-01，阶段 4 第一刀）。
这组函数不碰 Anki、不碰 LLM、不读 manifest，依赖只有 ``ruby_engine.wrap``，
所以能脱离 3k 行巨石单独测试；口径一字未改。

**没有迁走的**：``render_sentence_html`` / ``render_ainote`` /
``section_body_html`` 仍在 ``core6000_example`` —— 它们吃卡片结构体
（``sections`` / ``layout`` / ``n_sent``）并依赖板块解析，属于「渲染 + 卡片模型」，
要等卡片模型先独立。``scan`` / ``gen`` / ``apply`` 的写库路径一个字没动。

系列子目录（issue #12）：本模块在 ``code/execution/core6000/`` 下，单独 import 时
自己把 ``code/common`` 挂上 sys.path；被巨石 import 时那条路本来就在。
"""
import os as _os
import sys as _sys
_COMMON = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(
                       _os.path.abspath(__file__)))), 'common')
if _COMMON not in _sys.path:
    _sys.path.insert(0, _COMMON)

import ruby_engine as RE

POS_CN = {                       # 卡上 `Part of Speech` 是英文：② 的（词性）按 ① 的中文口径写
    'noun': '名词', 'verb': '动词', 'adjective': 'い形容词',
    'adjectival noun': 'な形容词', 'adverb': '副词', 'verbal noun': '名词/サ変動詞',
    'interrogative': '疑问词', 'pronoun': '代词', 'conjunction': '接续词',
    'particle': '助词', 'counter': '量词', 'numeral': '数词',
    'expression': '惯用语', 'prefix': '接头辞', 'suffix': '接尾辞',
}


def pos_cn(pos):
    """词性英文 → 中文（认不出就原样返回，不丢信息）。"""
    p = (pos or '').strip()
    return POS_CN.get(p.lower(), p)


def ruby_word(w, r):
    """`<ruby>漢字<rt>かな</rt></ruby>`；没有读音或词里没汉字就原样返回。

    口径与 ① 一致：只给汉字注音（假名词不注音 —— 闸门 4 也禁止基底只含假名）。
    标签构造统一走 ruby_engine.wrap（纯假名/无读音不加 ruby 的判断也只在那一处）。
    """
    return RE.wrap((w or '').strip(), (r or '').strip())


def gloss_lines(word, reading, meaning, glosses, pos=''):
    """② 的词表：目标词一行 + 新句里其它值得讲的词（最多 4 个）。

    行文与 ① 的「核心词汇」对齐：`<ruby>漢字<rt>かな</rt></ruby>（词性）：释义`，
    这样 ①② 看起来是同一套版式（契约 §5.2）。① 用的是**卡里原有的正文**
    （`core6000_example.section_body_html` 的 `orig`），不经过这里 —— 改这里一个字都不会动 ①。

    目标词那一行优先用模型在 `new_word_gloss` 里给的那条（`mean` 要写明新句**实际用的义项**，
    「此处是「…」的意思」就写在这里）；模型没给就回退到卡上的 `Meaning`。
    """
    lines, used, target_line = [], set(), None
    for g in glosses:
        if g['w'] == word or (reading and g['w'] == reading):
            target_line = g
            used.add(g['w'])
    if target_line:
        head_word = target_line['w']
        head_r = target_line['r'] or reading
        head_pos = target_line['pos'] or pos          # 模型没给词性就用卡上的 Part of Speech
        head_mean = target_line['mean'] or meaning
    else:
        head_word, head_r, head_pos, head_mean = word, reading, pos, meaning
    head = ruby_word(head_word, head_r)
    if head:
        head += '（%s）：%s' % (pos_cn(head_pos) or '—', head_mean or '—')
    lines.append(head)
    for g in glosses:
        if g['w'] in used:
            continue
        lines.append('%s（%s）：%s' % (ruby_word(g['w'], g['r']),
                                     pos_cn(g['pos']) or '—', g['mean'] or '—'))
    return lines
