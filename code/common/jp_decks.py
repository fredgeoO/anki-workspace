# -*- coding: utf-8 -*-
"""日语卡组结构常量 + 「eggrolls 标签 → JLPT 级别 / 频段」解析。

唯一的级别来源
--------------
「考级词汇」已经**扁平化**：原先 `0-日本语学习::0-词汇::2-考级词汇` 下面挂着
11 个按级别/频段切分的子 deck（`1-N5-词汇` … `5-N3-N5-低频词汇::3-N1`），
现在 10,609 张卡全部**直接放在 `2-考级词汇` 这一层**，子 deck 已删除。

级别与频段没有丢 —— eggrolls-JLPT10k-v3.5 的笔记标签一直带着它们：

    eggrolls-JLPT10k-v3.5::1-N5              → N5
    eggrolls-JLPT10k-v3.5::2-N4              → N4
    eggrolls-JLPT10k-v3.5::3-N3::N3高频      → N3 / 高频
    eggrolls-JLPT10k-v3.5::4-N2::N2中频      → N2 / 中频
    eggrolls-JLPT10k-v3.5::5-N1::N1低频      → N1 / 低频

（同一个前缀下还有 `::オノマトペ` / `::カタカナ語` / `::v26.xx.xx` 这些**非级别**
标签，本模块会忽略它们。）

所以：**凡是需要级别或频段的地方都走这个模块**，不要再拼子 deck 路径。
`level_from_tags()` 对「扁平化之前」的旧快照同样成立 —— 旧库里这些标签就有
（实测 data/snapshots/ankisnap/c.anki2：10,609 张考级卡 0 张缺级别标签）。

用法
----
    import jp_decks as JD

    # 1) 查询串（配合 AnkiConnect findNotes / 浏览器搜索框）
    JD.deck_query(JD.DECK_KAOKYU, 'N2', '高频')
    #    -> 'deck:"0-日本语学习::0-词汇::2-考级词汇" tag:eggrolls-JLPT10k-v3.5::4-N2::N2高频'

    # 2) 从笔记标签还原级别（AnkiConnect 的 notesInfo / 快照库的 notes.tags 都行）
    JD.level_from_tags(['eggrolls-JLPT10k-v3.5::4-N2::N2中频'])   # -> 'N2'
    JD.band_from_tags(['eggrolls-JLPT10k-v3.5::4-N2::N2中频'])    # -> '中频'

    # 3) 遍历「旧的 11 个子 deck」对应的 (级别, 频段) 单元
    for level, band in JD.KAOKYU_UNITS:
        ...
"""
import re

# ============================================================================
# 牌组路径
# ============================================================================
DECK_ROOT = '0-日本语学习'
DECK_VOCAB = DECK_ROOT + '::0-词汇'
DECK_MINED = DECK_VOCAB + '::0-素材生词'                 # 素材生词
DECK_CORE6000 = DECK_VOCAB + '::1-高频日语单词 6000'      # core6000
DECK_KAOKYU = DECK_VOCAB + '::2-考级词汇'                 # 考级词汇（扁平化后唯一一层）
DECK_PROPER = DECK_VOCAB + '::3-专有词汇'                 # 专有名词收集（不排学习顺序）
DECK_GRAMMAR = DECK_ROOT + '::1-语法'
DECK_EXAMPLE = DECK_ROOT + '::2-例句'

# ============================================================================
# 考级词汇：级别 / 频段
# ============================================================================
KAOKYU_MODEL = 'eggrolls-JLPT10k-v3.5'
KAOKYU_FIELD = 'VocabKanji'          # 词形字段（其余字段见 today_new.EGGROLL_FIELDS）

LEVELS = ('N5', 'N4', 'N3', 'N2', 'N1')      # 由易到难
RANK = {lv: i for i, lv in enumerate(LEVELS)}
BANDS = ('高频', '中频', '低频')
BAND_ORDER = {b: i for i, b in enumerate(BANDS)}

# 级别标签里那段「号-级别」前缀。N5/N4 只有这一段；N3/N2/N1 后面还挂 ::N{3,2,1}{频段}
_LEVEL_NUM = {'N5': 1, 'N4': 2, 'N3': 3, 'N2': 4, 'N1': 5}
_NUM_LEVEL = {v: k for k, v in _LEVEL_NUM.items()}

# 形如  eggrolls-JLPT10k-v3.5::4-N2      或  eggrolls-JLPT10k-v3.5::4-N2::N2中频
_LEVEL_TAG = re.compile(r'^' + re.escape(KAOKYU_MODEL) + r'::([1-5])-(N[1-5])(?:::([^:]*))?$')
# 极端情况：标签前缀被动过（例如换了模型名），仍然按「::<号>-<级别>」认级别
_LOOSE_LEVEL_TAG = re.compile(r'::[1-5]-(N[1-5])(?:::([^:]*))?$')

# 旧的 11 个子 deck：级别 / 频段 / 旧子 deck 名（仅用于兼容旧输出与文档）
OLD_SUBDECKS = [
    ('N5', None, '1-N5-词汇'),
    ('N4', None, '2-N4-词汇'),
    ('N3', '高频', '3-N3-N5-高频词汇::1-N3'),
    ('N2', '高频', '3-N3-N5-高频词汇::2-N2'),
    ('N1', '高频', '3-N3-N5-高频词汇::3-N1'),
    ('N3', '中频', '4-N3-N5-中频词汇::1-N3'),
    ('N2', '中频', '4-N3-N5-中频词汇::2-N2'),
    ('N1', '中频', '4-N3-N5-中频词汇::3-N1'),
    ('N3', '低频', '5-N3-N5-低频词汇::1-N3'),
    ('N2', '低频', '5-N3-N5-低频词汇::2-N2'),
    ('N1', '低频', '5-N3-N5-低频词汇::3-N1'),
]
# [(级别, 频段)]，顺序沿用旧子 deck 的编号顺序；N5/N4 的频段是 None
KAOKYU_UNITS = [(lv, band) for lv, band, _ in OLD_SUBDECKS]
_OLD_NAME = {(lv, band): name for lv, band, name in OLD_SUBDECKS}


def level_tag(level, band=None):
    """(级别, 频段) → eggrolls 级别标签名（精确标签，不带通配）。"""
    if level not in _LEVEL_NUM:
        raise ValueError('未知 JLPT 级别: %r' % (level,))
    base = '%s::%d-%s' % (KAOKYU_MODEL, _LEVEL_NUM[level], level)
    if band:
        if band not in BANDS:
            raise ValueError('未知频段: %r' % (band,))
        return '%s::%s%s' % (base, level, band)
    return base


def tag_query(level, band=None):
    """级别标签的 Anki 搜索片段，例如 ``tag:eggrolls-JLPT10k-v3.5::4-N2::N2高频``。"""
    return 'tag:' + level_tag(level, band)


def deck_query(deck, level=None, band=None):
    """牌组 + 级别的完整 Anki 搜索串。level 为 None 时只按牌组查。"""
    return deck_query_tag(deck, level_tag(level, band) if level else None)


def deck_query_tag(deck, tag=None):
    """牌组 + 任意标签的 Anki 搜索串（tag 直接给标签名，不含 tag: 前缀）。"""
    q = 'deck:"%s"' % deck
    return q + (' tag:%s' % tag if tag else '')


def old_subdeck(level, band=None):
    """该 (级别, 频段) 在扁平化之前对应的子 deck 名（旧输出兼容用）。"""
    return _OLD_NAME.get((level, band))


def level_from_tags(tags, loose=True):
    """从笔记标签还原 JLPT 级别；认不出来返回 None。

    tags 可以是任何可迭代的字符串序列（AnkiConnect notesInfo 的 n['tags']，
    或快照库里 notes.tags 用空白切开的列表）。
    """
    for t in tags or ():
        m = _LEVEL_TAG.match(t)
        if m:
            return m.group(2)
    if loose:
        for t in tags or ():
            m = _LOOSE_LEVEL_TAG.search(t)
            if m:
                return m.group(1)
    return None


def band_from_tags(tags, loose=True):
    """从笔记标签还原频段（高频/中频/低频）；N5/N4 或认不出来返回 None。"""
    for t in tags or ():
        m = _LEVEL_TAG.match(t)
        if m and m.group(3):
            for b in BANDS:
                if m.group(3) == m.group(2) + b:
                    return b
    if loose:
        for t in tags or ():
            m = _LOOSE_LEVEL_TAG.search(t)
            if m and m.group(2):
                for b in BANDS:
                    if m.group(2) == m.group(1) + b:
                        return b
    return None


def level_band_from_tags(tags, loose=True):
    """(级别, 频段)，任一认不出来就是 None。"""
    return (level_from_tags(tags, loose=loose), band_from_tags(tags, loose=loose))


def sort_key(level, band=None):
    """(级别, 频段) 的排序键：级别由易到难，同级高频在前。"""
    return (RANK.get(level, len(LEVELS)), BAND_ORDER.get(band, len(BANDS)))


def is_level_tag(tag):
    """这个标签是不是考级词汇的级别标签（用于过滤掉 カタカナ語 / v26.07.13 之类）。"""
    return bool(_LEVEL_TAG.match(tag))
