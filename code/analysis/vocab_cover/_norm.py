# -*- coding: utf-8 -*-
"""词形归一的**唯一实现**：抽卡组的脚本（collect_vocab.py）和做覆盖率统计的脚本
（jp_tok.py）必须用同一套规则，否则统计会静默失真，所以规则集中放这里。

规则
----
* NFKC 全角半角统一（！-> !，～-> ~）
* 去空白、去 ・
* 去首尾的 〜 ～（卡组里用 〜さん / 〜やすい 表示接尾辞）
* 去首尾标点装饰
* 片假名 -> 平假名（长音符保留）：这样「卡片写片假名、字幕写平假名」也能对上
* 卡组词条里的 漢字[かんじ] / 漢字（かんじ） 注音写法只取汉字部分
"""
from __future__ import annotations

import re
import unicodedata

KATA_LO, KATA_HI = 0x30A1, 0x30F6
HIRA_LO, HIRA_HI = 0x3041, 0x3096
KANA_EXTRA = '\u30fc\u309d\u309e'          # 长音符、重复符

TRIM = (' \u3000\t・･,、。!?！？「」『』()（）[]［］<>《》〈〉"\'’“”'
        '\u301c\uff5e~\u00b7\u2026\u2027')
BRACKET_SPLIT = re.compile(r'[\[［（(〈＜<【〔]')
DASH_TRIM = ' \u3000-\u2010-\u2015\u2212\u30fc'


def to_hiragana(text: str) -> str:
    return ''.join(chr(ord(c) - 0x60) if KATA_LO <= ord(c) <= KATA_HI else c for c in text)


def primary_form(surface: str) -> str:
    """卡组词条 -> 主词形：``石鹸[けん]`` -> ``石鹸``；``〜さん`` -> ``さん``。"""
    if not surface:
        return ''
    s = unicodedata.normalize('NFKC', surface)
    s = BRACKET_SPLIT.split(s, 1)[0]
    return s.strip()


def norm_word(word: str) -> str:
    """归一化后的查表键。"""
    if not word:
        return ''
    w = unicodedata.normalize('NFKC', word)
    w = re.sub(r'[\s\u3000]', '', w)
    w = w.replace('・', '').replace('･', '')
    w = w.strip(TRIM)
    return to_hiragana(w)


def looks_kana(word: str) -> bool:
    """整词都是假名（含长音符）。"""
    if not word:
        return False
    for c in word:
        o = ord(c)
        if not (HIRA_LO <= o <= HIRA_HI or KATA_LO <= o <= KATA_HI or c in KANA_EXTRA):
            return False
    return True


def kana_only(text: str) -> str:
    keep = []
    for c in text:
        o = ord(c)
        if (HIRA_LO <= o <= HIRA_HI or KATA_LO <= o <= KATA_HI or c in KANA_EXTRA):
            keep.append(c)
    return ''.join(keep)


def reading_keys(reading: str) -> list:
    """读音字段的候选键（原样 + 纯假名）。"""
    out = []
    if not reading:
        return out
    for cand in (unicodedata.normalize('NFKC', reading), kana_only(reading)):
        n = norm_word(cand)
        if n and n not in out:
            out.append(n)
    return out
