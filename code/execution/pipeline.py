# -*- coding: utf-8 -*-
"""日语字幕卡流水线（ABS Player 导入 → 清理 → 生成振假名与讲解）

把 2026-09 首次跑通《水星领航员》第 04 集时用到的全部步骤固化成一个可复用脚本。
**代码与作品无关**：换任何动画/剧集，只需要改 --tag 和 --query 两个参数。
下次换一集时，只需要改 --tag 和 --file。

用法总览
--------
# 阶段 0：拉取判据用到的词表/语法表/参照系（结果缓存进 data/pipeline/gen/cache.json，可跨集复用）
#   参照系 = 目标 deck（0-日本语学习::2-例句）本身的全部卡；查重只看 Sentence，不看 AINote
python pipeline.py prepare

# 阶段 1：清理。先出报告（不改库）
python pipeline.py triage --query "tag:待标记"
# 看报告确认后执行：打标签 + suspend
python pipeline.py apply --drop-tag "待标记::弃"

# 阶段 2：生成。切批后由**本地模型**逐批生成 AINote / Sentence HTML（2026-10-11 起，不派子代理）
python pipeline.py split --tag "动画::<作品名>::<季>::第NN集" --batches 12
python pipeline.py gen             # 直连本地模型（Responses API）→ data/pipeline/gen/output_NN.json
#   --per-request 1   每次请求几张卡（默认 1：本地模型一次处理多条容易出错，逐张发；想提速再调大）
#   --retries 1       整批不合格时带着问题重问几轮（默认 1 轮，不做无限返工）
#   --force           已存在的 output_NN.json 也重做（默认跳过，可断点续跑）
#   split --print-prompts   只在本地模型不可用时打印子代理提示词（云端 token 路径，非默认）
#   ⚠ 判断按字段归属分开：AINote 侧不合格（讲解缺失/段落不齐）才算"没做出来"要重问；
#     Sentence HTML 侧的机械问题（文本漂移、漏标 ruby、<br> 数不对）**不重问**，
#     讲解照收，HTML 交给 ruby_engine.py repair 拿原始 Sentence 当骨架重渲染。
python pipeline.py write           # 先校验再入库；校验不通过就不写
#   --skip-check   跳过校验直接写（不推荐）
#   --overwrite    目标字段已有内容时也覆盖
python pipeline.py verify          # 可选：只看校验结果、不入库

# 阶段 4（单独脚本）：素材生词牌组。把例句里出现、但 core6000/考级词汇都没有的词，
#   建成第三个词汇牌组 0-日本语学习::0-词汇::0-素材生词
python mine.py scan                # 只读扫描，出候选
python mine.py split --batches N   # 切批 + 打印子代理提示词（产出 gen_mine/output_NN.json）
python mine.py verify              # 校验（含"是否真的不在已有牌组里"）
python mine.py write --commit      # 入库

依赖：AnkiConnect 在 127.0.0.1:8765；Python 3；校验器 code/common/check_cards.py
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))   # paths.py / check_cards.py
sys.path.insert(0, _HERE)
import anki_api as AK  # noqa: E402  唯一的 Anki 访问点
import check_cards  # noqa: E402
import jp_decks as JD  # noqa: E402  牌组常量 + 标签→级别/频段（考级词汇已扁平化）
import llm_out as OUT  # noqa: E402  模型产出吸收层（类型归一 / 原始回复留证）
import paths as WSP  # noqa: E402  工作区路径的唯一来源（见 code/common/paths.py）
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

WS = WSP.ROOT                                     # 兼容旧引用（提示词里的 {ws} 等）
GEN = os.path.join(WSP.DATA_PIPELINE, 'gen')      # 阶段 0-2 工作目录（原 ./gen）
PLAN = os.path.join(WSP.DATA_PIPELINE, 'plan.json')
DROP_MD = os.path.join(WSP.DATA_PIPELINE, 'drop_candidates.md')
KEEP_MD = os.path.join(WSP.DATA_PIPELINE, 'keep_list.md')

# ============================================================================
# 配置区：换收藏结构时改这里
# ============================================================================
CFG = {
    # 例句卡所在的 deck。本集标签一律由 --tag 传入，**不在这里写死任何作品名**
    'deck': '0-日本语学习::2-例句',

    # 判据①「单词」的来源：考级词汇（按 JLPT 级别 / 频段组织）
    # ⚠ 考级词汇**已扁平化**：原先 11 个按级别/频段切分的子 deck 合并成
    #   「2-考级词汇」一层（10,609 张），级别与频段改由 eggrolls 笔记标签区分
    #   （见 code/common/jp_decks.py）。所以这里是四元组
    #   (级别, deck, 词形字段, 级别标签)；标签为 None 表示整个 deck 一个级别。
    # 注意：不同 deck 的词条字段名不一样，必须逐条指定
    #   - 考级词汇 / eggrolls 系列：VocabKanji
    #   - jp-core（Japanese Vocabulary）：Word
    'vocab_decks': [
        (lv, JD.DECK_KAOKYU, JD.KAOKYU_FIELD, JD.level_tag(lv, band))
        for lv, band in JD.KAOKYU_UNITS
    ],
    # 按词频分段（而非 JLPT 级别）标注的词汇 deck：字段名 + 频段→级别的映射
    'vocab_band_decks': [
        ('jp-core', JD.DECK_CORE6000, 'Word',
         {1: 'N5', 2: 'N5', 3: 'N4', 4: 'N4', 5: 'N3', 6: 'N3'}),
    ],
    # 另有标签形式收录的词汇（拟声拟态词、片假名外来语）
    'vocab_tags': [
        ('オノマトペ', JD.KAOKYU_MODEL + '::オノマトペ'),
        ('カタカナ語', JD.KAOKYU_MODEL + '::カタカナ語'),
    ],
    # 判据②「语法」的来源：语法条目 deck（Card 字段即句型）
    'grammar_decks': [
        '0-日本语学习::1-语法::1-N5::1-N5-解释',
        '0-日本语学习::1-语法::2-N4::1-N4-解释',
        '0-日本语学习::1-语法::3-N3::1-N3-解释',
        '0-日本语学习::1-语法::4-N2::1-N2-解释',
        '0-日本语学习::1-语法::5-N1::1-N1-解释',
    ],
    # 词汇门槛：低于这个级别的词不算「值得学」。由 92 张旧卡的 Word 分布校准而来
    # （旧卡 Word：N5×5 / N4×13 / N3×15 / N2×12 / N1×8 / 不在词表×39）
    'vocab_floor': {'N4', 'N3', 'N2', 'N1', 'オノマトペ', 'カタカナ語'},

    # ── 第三个词汇牌组：素材生词（mine.py 用）──────────────────────────────
    # 入库要求：词形**不存在于上面任何已有词汇牌组**（core6000 + 考级词汇），
    # 词汇来源是 2-例句 里最终保留的字幕例句。见 mine.py。
    'mine_deck': '0-日本语学习::0-词汇::0-素材生词',
    # 「已知词汇」的参照系：已有全部词汇 deck 的**父级前缀**。
    # 用父级前缀（deck:"X" 会连带所有子 deck）而不是逐个列子 deck ——
    # 考级词汇扁平化后它自己就是一层，这样写以后再加子 deck 也自动覆盖到。
    # 顺序 = 收词优先级：先娘家的（考级词汇→core6000）级别更可靠。
    'known_vocab_scopes': [
        # 顺序 = 级别标签来源的优先级（先到先得）
        {'deck': JD.DECK_KAOKYU, 'field': JD.KAOKYU_FIELD, 'lv': '考级'},
        {'deck': JD.DECK_CORE6000, 'field': 'Word', 'lv': 'Core6000'},
    ],
    'mine_model': 'Japanese Vocabulary',   # 与 core6000 同模板，复用其字段
    'mine_tag_prefix': '素材生词',

    'drop_tag': '待标记::弃',
    'pending_tag': '待标记',
}

RANK = ['N5', 'N4', 'N3', 'N2', 'N1']
KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
KATA_ONLY = re.compile(r'^[\u30a1-\u30f6\u30fc]+$')
KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30fc]+$')
KATA_RUN = re.compile(r'[\u30a1-\u30f6\u30fc]{3,}')
PUNCT = re.compile(r'[、。！？!?「」『』（）()\[\]{}…‥・,.:：;；~〜\-－—–\s　]+')
EXTRA_GRAMMAR = [
    'てしまう', 'ちゃう', 'じゃう', 'なきゃ', 'なくちゃ', 'んじゃない', 'んだけど', 'んだ',
    'わけには', 'っけ', 'じゃん', 'だって', 'ってば', 'っぽい', 'なのだ', 'のだよ', 'んです',
    'のかしら', 'ましょうか', 'てもらえ', 'ざるを', 'ずには', 'ところだった', 'どころか',
    'たとえ', 'せっかく', 'おそらく', 'もしも', 'いくら', 'どんなに',
    '仕方がない', 'しょうがない', '間に合', 'おかげで', 'せいで', 'ばかりに', 'ものの',
    'にもかかわらず', 'とはいえ', 'からといって', 'にしては', 'わりに', 'くせに', 'のみならず',
    'だけでなく', 'というより', 'ないことはない', 'ないわけではない', 'ようになる',
    'ようにする', 'ことになる', 'ことにする', 'ばかりだ', 'ところだ', 'はずがない',
    'に違いない', 'かねない', 'ずにはいられない', 'てたまらない', 'てならない',
]
IDIOMS = [
    '気を使', '気を遣', '気が付', '気にする', '気になる', '気に入', '気が済', '気を抜',
    '気が抜', '気が遠く', '手を貸', '手が出', '手に入', '手を出', '手を焼', '目を通',
    '目が届', '目を離', '目に留', '口を出', '口が堅', '顔を出', '顔が広', '足を運',
    '足が出', '胸を張', '胸が痛', '骨が折', '骨を折', '力を貸', '力になる', '役に立',
    '世話になる', '水を差', '水に流', '火が付', '拍車をかけ', '目処が立', '筋が通',
    '話が違', '音を立て', '息を切', '息を吐', '肩を落', '肩の荷', '腰を据', '首をかしげ',
    '首を振', '眉をひそ', '腹を立', '腹が減', '涙を流', '声を上げ', '声をかけ', '声を潜',
    '腕を振る', '腕によりをかけ', '頭ごなし', 'にも程がある', '途方に暮', '折り合いをつけ',
    '気をつけ', 'お世話にな', '当たり前', '思いがけな', '思い切って', '言うまでもな',
    '立場にな', '身につけ', '目を向け', '耳を傾け', '道に迷', '邪魔をす', '迷惑をかけ',
    '面倒を見', '相談に乗', '相手にす', '覚悟を決', '決心をつけ', '心を込め', '心がけ',
]
RENTAI = re.compile(r'[\u4e00-\u9fff][\u3040-\u309f]{1,3}(?:た|てる|ている|ない|れる|られる|いた|てきた)[\u4e00-\u9fff]')


# ============================================================================
# 基础设施
# ============================================================================
# Anki 读写一律走 code/common/anki_api.py（传输/分块/字段拆包/错误语义都在那里）


def strip_html(s):
    import html as _h
    if not isinstance(s, str):
        # 模型/外部数据偶尔给数字、布尔甚至 None（2026-10-12 实测：
        # 本地模型把字符串字段返回成 int，`unescape(5)` 直接崩）—— 一律转成文本。
        s = '' if s is None else str(s)
    s = _h.unescape(s or '')
    return re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', ' ', s, flags=re.I))


def norm(s):
    return PUNCT.sub('', strip_html(s))


def dupkey(s):
    """查重键：只取 Sentence 本身，与 AINote 无关。

    口径：NFKC 统一全角/半角 → 整块删 `<rt>…</rt>`（万一 Sentence 里混进了振假名 HTML）
    → 剥其余标签 → 去掉全部空白（含全角空格 U+3000）。
    **标点保留**：`ありがとう` 与 `ありがとう！` 是两种语气，不算重复（只做全角/半角统一）。
    """
    s = unicodedata.normalize('NFKC', s or '')
    s = re.sub(r'<rt>.*?</rt>', '', s, flags=re.I | re.S)
    return re.sub(r'\s+', '', strip_html(s), flags=re.UNICODE)


def hira2kata(s):
    return ''.join(chr(ord(c) + 0x60) if '\u3041' <= c <= '\u3096' else c for c in s)


def kata2hira(s):
    return ''.join(chr(ord(c) - 0x60) if '\u30a1' <= c <= '\u30f6' else c for c in s)


# ============================================================================
# 阶段 0：prepare —— 拉取词表 / 语法表 / 参照系
# ============================================================================
def vocab_guard(w):
    """长度守卫：纯假名词必须 >=3 字，否则子串匹配会大量误命中
    （2 字的「だめ」「やあ」会在「いやあった」里命中「やあ」）"""
    if KANJI.search(w):
        return len(w) >= 2
    if KATA_ONLY.match(w):
        return len(w) >= 2
    if KANA_ONLY.match(w):
        return len(w) >= 3
    return len(w) >= 2


def build_vocab():
    word_lv = {}

    def better(w, lv):
        old = word_lv.get(w)
        if old is None:
            return True
        if lv in RANK and old in RANK:
            return RANK.index(lv) < RANK.index(old)
        return old not in RANK

    for lv, deck, field, tag in CFG['vocab_decks']:
        for n in AK.notes_info(AK.find_notes(JD.deck_query_tag(deck, tag))):
            w = norm(n['fields'].get(field, {}).get('value', ''))
            if w and vocab_guard(w) and better(w, lv):
                word_lv[w] = lv

    for tag, deck, field, bandmap in CFG.get('vocab_band_decks', []):
        pat = re.compile(re.escape(tag) + r'::(\d)k')
        for n in AK.notes_info(AK.find_notes('deck:"%s"' % deck)):
            band = None
            for t in n['tags']:
                m = pat.match(t)
                if m:
                    band = int(m.group(1))
            lv = bandmap.get(band)
            w = norm(n['fields'].get(field, {}).get('value', ''))
            # 已被 JLPT 级别 deck 收录的词，保留其原始级别（词频排名 ≠ JLPT 级别）
            if w and lv and vocab_guard(w) and better(w, lv):
                word_lv[w] = lv

    for tag, lv in CFG['vocab_tags']:
        for n in AK.notes_info(AK.find_notes('tag:"%s"' % lv)):
            w = norm(n['fields'].get('VocabKanji', {}).get('value', ''))
            if len(w) >= 2 and better(w, lv):
                word_lv[w] = lv
    return word_lv


def build_variants(word_lv):
    conj_tail = 'るうくすつぬぶむぐい'
    out = {}
    for w in word_lv:
        vs = {w}
        # 活用词干只对含汉字的词生成：含汉字时碰撞率低（調べる→調べ、珍しい→珍し）；
        # 纯假名词的 2 字词干极易误命中（かえる→かえ 会命中「おかえりなさい」）
        if len(w) >= 3 and w[-1] in conj_tail and KANJI.search(w):
            vs.add(w[:-1])
        if KANA_ONLY.match(w) or KATA_ONLY.match(w):
            vs.add(hira2kata(w))
            vs.add(kata2hira(w))
        out[w] = [v for v in vs if len(v) >= 2]
    return out


# 五段/一段/サ変/形容詞 的常见活用尾。用途见 conjugation_variants()。
_CONJ_TAILS = ['', 'る', 'た', 'て', 'ます', 'ました', 'ません', 'なかった', 'ない', 'ぬ', 'ず',
               'れる', 'られる', 'せる', 'させる', 'たい', 'そう', 'よう', 'ば', 'たら', 'たり',
               'ながら', 'なさい', 'ろ', 'ずに', 'なくて', 'ちゃう', 'ちゃった', 'てる', 'てた',
               'ている', 'ていた', 'ておく', 'てしまう', 'すぎる', 'やすい', 'にくい', 'たい',
               'い', 'く', 'かった', 'ければ', 'さ', 'み', 'げ', 'め', 'わ', 'おう', 'よう']
# 五十音 5 段（用于生成「未然/連用/仮定」形），行 = 段
_GODAN = {
    'う': 'わいうえお', 'く': 'かきくけこ', 'ぐ': 'がぎぐげご', 'す': 'さしすせそ',
    'つ': 'たちつてと', 'ぬ': 'なにぬねの', 'ぶ': 'ばびぶべぼ', 'む': 'まみむめも',
    'る': 'らりるれろ',
}
_KANA_RANGE = re.compile(r'^[\u3041-\u3096\u30a1-\u30f6]')


def conjugation_variants(w):
    """把词典形展开成常见活用形，用于「这个词是不是已经存在」的判定。

    挖掘（mine.py）是**反向**用途：已知词的变体越多，越不会把
    「漕い」当成 Plan B 的新词收进来（漕ぐ 已在 core6000 里）。
    triage 的参照系判定不用这个函数，以免动到它已固化的回归基线。
    """
    out = {w}
    if len(w) < 2 or KANJI.search(w[-1]):
        return out
    if w.endswith('する') and len(w) > 2:
        # サ変動詞（介抱する・愚弄する・確認する）单独处理并直接返回：
        # 词干是「介抱」而不是「介抱す」，下面那套「尾假名＝词尾」的规则会算出
        # 「介抱すます／介抱すた」这类废变体，而真正要用的「介抱し／介抱した／
        # 介抱して」一个都生成不出来 —— mine.py 定位例句时就会判 notfound
        # （2026-10-12 第 01 集「介抱する」实测：例句是「介抱していただいた」）。
        b = w[:-2]
        out.update({b, b + 'し', b + 'した', b + 'して', b + 'しない', b + 'しなかった',
                    b + 'します', b + 'しました', b + 'しよう', b + 'すれば', b + 'しろ',
                    b + 'される', b + 'させる', b + 'せず', b + 'したい', b + 'しながら',
                    b + 'している', b + 'していた', b + 'しておく', b + 'してしまう'})
        return {v for v in out if len(v) >= 2}
    stem = w[:-1]
    if w[-1] == 'る':                      # 一段 / 五段る
        out.add(stem + 'ます')
        out.add(stem + 'た')
        out.add(stem + 'て')
        out.add(stem + 'ない')
        out.add(stem + 'なかった')
        out.add(stem + 'よう')
        out.add(stem + 'ろ')
        out.add(stem + 'ず')
    row = _GODAN.get(w[-1])
    if row:                                # 五段
        a, i, u, e, o = row
        out.add(stem + a + 'ない')
        out.add(stem + i + 'ます')
        out.add(stem + i + 'たい')
        out.add(stem + i + 'た')
        out.add(stem + i + 'て')
        out.add(stem + i + 'そう')
        out.add(stem + e + 'ば')
        out.add(stem + e + 'る')
        out.add(stem + o + 'う')
    if w[-1] == 'い':                      # イ形容词
        out.add(stem + 'く')
        out.add(stem + 'かった')
        out.add(stem + 'さ')
        out.add(stem + 'ければ')
    for t in _CONJ_TAILS:                  # 通用尾缀
        if t:
            out.add(stem + t)
    return {v for v in out if len(v) >= 2}


def rebuild_known_index(verbose=True):
    """重建「已有词汇牌组」索引 —— 新的素材生词牌组的收录判据就是这个集合。

    返回 (canonical_lv, variant2canonical)：
      - canonical_lv: 词典形 → 级别/来源标签
      - variant2canonical: 一切可识别的写法（活用形、平假名↔片假名、词干）
        → 词典形。判定「某词是否已存在」只需查这个字典。

    覆盖 CFG['known_vocab_scopes'] 里的全部 deck（用父级前缀，连带子 deck）。
    """
    canonical, variant2c = {}, {}
    for sc in CFG.get('known_vocab_scopes', []):
        path = sc['deck']
        field = sc.get('field') or ('VocabKanji' if sc.get('tag') else 'Word')
        lv = sc.get('lv', '')
        ids = AK.find_notes('deck:"%s"' % path)
        if verbose:
            print('  %-46s %6d 张（字段 %s）' % (path.split('::')[-1], len(ids), field))
        for n in AK.notes_info(ids):
            w = norm(n['fields'].get(field, {}).get('value', ''))
            w = w.strip('〜～')
            if not w:
                continue
            label = lv or sc.get('tag') or ''
            if w not in canonical:
                canonical[w] = label
            for v in set(build_variants({w: 1})[w]) | conjugation_variants(w):
                if len(v) >= 2:
                    variant2c.setdefault(v, w)
    return canonical, variant2c


def build_grammar():
    g = {}
    for deck in CFG['grammar_decks']:
        lvl = deck.split('::')[-2].split('-')[1]
        for n in AK.notes_info(AK.find_notes('deck:"%s"' % deck)):
            c = (n['fields'].get('Card', {}).get('value') or '').strip()
            if not c:
                continue
            c = re.sub(r'[（(][^）)]*[）)]', '', c)
            for part in re.split(r'[〜・/～]', c):
                part = part.strip()
                if len(part) < 2 or not KANA.search(part):
                    continue
                if part in ('が', 'を', 'に', 'は', 'へ', 'と', 'も', 'で', 'の', 'や', 'か', 'ね',
                            'よ', 'な', 'さ', 'し', 'て', 'ば', 'げ'):
                    continue
                if part not in g or RANK.index(lvl) < RANK.index(g[part]):
                    g[part] = lvl
    for e in EXTRA_GRAMMAR:
        g.setdefault(e, 'X')
    return g


def cmd_prepare(_a):
    print('拉取词表…')
    word_lv = build_vocab()
    print('  词条 %d' % len(word_lv))
    print('拉取语法条目…')
    grammar = build_grammar()
    print('  句型 %d' % len(grammar))

    # 参照系：本 deck 的全部卡（= 新卡要加进去的那个集合本身），不看 AINote 是否为空
    print('拉取参照系（%s 全 deck 的 Sentence）…' % CFG['deck'])
    ref_notes = AK.notes_info(AK.find_notes('deck:"%s"' % CFG['deck']))
    ref = []
    for n in ref_notes:
        f = n['fields']
        ref.append({'noteId': int(n['noteId']),
                    'sentence': f.get('Sentence', {}).get('value', ''),
                    'word': f.get('Word', {}).get('value', '')})
    print('  参照 %d 张（查重依 Sentence，判定时排除本批自身）' % len(ref))

    cache = {'word_lv': word_lv, 'grammar': grammar, 'reference': ref}
    os.makedirs(GEN, exist_ok=True)
    json.dump(cache, open(os.path.join(GEN, 'cache.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    print('已缓存到 %s' % os.path.join(GEN, 'cache.json'))


def load_cache():
    p = os.path.join(GEN, 'cache.json')
    if not os.path.exists(p):
        raise SystemExit('缺少 %s，先运行：python pipeline.py prepare' % os.path.join(GEN, 'cache.json'))
    return json.load(open(p, encoding='utf-8'))


# ============================================================================
# 阶段 1：triage —— 三维判定
# ============================================================================
def grammar_hits(n, gpat):
    hits = [p for p in gpat if p in n]
    out = []
    for p in sorted(set(hits), key=len, reverse=True):
        if not any(p != q and p in q for q in out):
            out.append(p)
    return out


def classify(cards, cache):
    word_lv = cache['word_lv']
    grammar = cache['grammar']
    reference = cache['reference']

    variants = build_variants(word_lv)
    vocab = sorted(word_lv, key=len, reverse=True)
    kanji_seen = set()
    for w in word_lv:
        kanji_seen |= set(KANJI.findall(w))
    gpat = sorted(grammar, key=len, reverse=True)
    ipat = sorted(set(IDIOMS), key=len, reverse=True)

    # 参照系覆盖。
    # 注意：本批自身的 noteId 必须从参照系里剔除 —— 新卡在 triage 时已经在 deck 里了，
    # 不剔除的话每张卡都会被自己的词/句型"覆盖"，判定会全部误判为 DROP。
    self_ids = {int(c['noteId']) for c in cards}
    reference = [r for r in reference if int(r.get('noteId', 0)) not in self_ids]

    # 查重表：key 只来自 Sentence（不看 AINote）
    ref_dup = {}
    for r in reference:
        k = dupkey(r.get('sentence', ''))
        if k:
            ref_dup.setdefault(k, []).append(int(r.get('noteId', 0)))

    ref_vocab, ref_gram, ref_idiom = set(), set(), set()
    for r in reference:
        rn = norm(r.get('sentence', ''))
        rw = norm(r.get('word', ''))
        if rw:
            ref_vocab.add(rw)
        for vw in vocab:
            if any(v in rn for v in variants[vw]):
                ref_vocab.add(vw)
        ref_gram |= set(grammar_hits(rn, gpat))
        ref_idiom |= {p for p in ipat if p in rn}

    out = []
    seen_batch = {}
    for c in cards:
        n = norm(c['sentence'])
        c2 = strip_html(c['sentence']).strip()
        dk = dupkey(c['sentence'])
        vhits = sorted({w for w in vocab if any(v in n for v in variants[w])}, key=len, reverse=True)
        new_v = [(w, word_lv[w]) for w in vhits if w not in ref_vocab and word_lv[w] in CFG['vocab_floor']]
        low_v = [(w, word_lv[w]) for w in vhits if w not in ref_vocab and word_lv[w] not in CFG['vocab_floor']]
        new_kanji = ''.join(sorted(set(KANJI.findall(n)) - kanji_seen))
        new_g = [g for g in grammar_hits(n, gpat) if g not in ref_gram]
        strong_g = [(g, grammar[g]) for g in new_g
                    if len(g) >= 3 or grammar[g] in ('N3', 'N2', 'N1')]
        weak_g = [(g, grammar[g]) for g in new_g if (g, grammar[g]) not in strong_g]
        idi = [p for p in ipat if p in n and p not in ref_idiom]
        why = []
        if RENTAI.search(n):
            why.append('连体修饰')
        if len(n) >= 26:
            why.append('>26字')

        dims = []
        if new_v:
            dims.append('单词')
        if idi:
            dims.append('惯用')
        if new_kanji:
            dims.append('新汉字')
        if strong_g:
            dims.append('语法')
        if why:
            dims.append('长句')

        # 查重：只比 Sentence。同批内先出现的那张保留，后面重复的判弃。
        if dk and dk in seen_batch:
            dup = '批内重复(=%s)' % seen_batch[dk]
        elif dk and dk in ref_dup:
            dup = '与deck已有卡重复(%s)' % ref_dup[dk][0]
        else:
            dup = ''
            if dk:
                seen_batch[dk] = int(c['noteId'])

        out.append({
            'noteId': int(c['noteId']),
            'sentence': c2,
            'chars': len(n),
            'dup': dup,
            'new_words': ';'.join('%s(%s)' % x for x in new_v[:6]),
            'low_words': ';'.join('%s(%s)' % x for x in low_v[:6]),
            'idioms': ';'.join(idi[:4]),
            'new_kanji': new_kanji,
            'new_grammar': ';'.join('%s(%s)' % x for x in strong_g[:5]),
            'weak_grammar': ';'.join('%s(%s)' % x for x in weak_g[:5]),
            'complex': int(bool(why)),
            'cplx_why': ','.join(why),
            'dims': '+'.join(dims),
            'verdict': 'DROP' if (dup or not dims) else 'KEEP',
        })
    return out


def cmd_triage(a):
    cache = load_cache()
    ids = AK.find_notes(a.query)
    if not ids:
        print('查询无结果：%s' % a.query)
        return
    cards = [{'noteId': n['noteId'], 'sentence': n['fields'].get('Sentence', {}).get('value', '')}
             for n in AK.notes_info(ids)]
    print('待判定：%d 张（查询 %s）' % (len(cards), a.query))
    rows = classify(cards, cache)
    keep = [r for r in rows if r['verdict'] == 'KEEP']
    drop = [r for r in rows if r['verdict'] == 'DROP']
    print('保留 %d / 弃用 %d' % (len(keep), len(drop)))
    from collections import Counter
    print('保留维度分布：', dict(Counter(r['dims'] for r in keep)))
    dups = [r for r in rows if r['dup']]
    if dups:
        print('其中查重命中 %d 张（只比 Sentence，不看 AINote）：' % len(dups))
        for r in dups[:10]:
            print('  %s  `%s`' % (r['dup'], r['sentence']))
        if len(dups) > 10:
            print('  … 其余 %d 张见 drop_candidates.md' % (len(dups) - 10))
    print()

    plan = {
        'keep': [r['noteId'] for r in keep],
        'drop': [r['noteId'] for r in drop],
        'drop_dup_in_batch': [r['noteId'] for r in drop if r['dup'].startswith('批内重复')],
        'drop_dup_vs_existing': [r['noteId'] for r in drop if r['dup'].startswith('与deck')],
        'batch_size': None,
    }
    json.dump(plan, open(PLAN, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    with open(DROP_MD, 'w', encoding='utf-8') as f:
        f.write('# 待弃候选（%d 条）\n\n' % len(drop))
        f.write('> 查重口径：只比 `Sentence` 字段（去标签、去空格后逐字相同即重复），与 `AINote` 是否为空无关。\n\n')
        for r in sorted(drop, key=lambda x: (x['chars'], x['sentence'])):
            f.write('- `%s` — %s%s%s\n' % (r['sentence'], r['noteId'],
                    ('  ' + r['dup']) if r['dup'] else '',
                    ('  低阶词:' + r['low_words']) if r['low_words'] else ''))
    with open(KEEP_MD, 'w', encoding='utf-8') as f:
        f.write('# 保留清单（%d 条）\n\n' % len(keep))
        for dims in sorted(set(r['dims'] for r in keep)):
            sub = [r for r in keep if r['dims'] == dims]
            f.write('## %s（%d 条）\n\n' % (dims, len(sub)))
            for r in sorted(sub, key=lambda x: x['chars']):
                f.write('- `%s` — %s | 词:%s 语法:%s 惯用:%s\n' % (
                    r['sentence'], r['noteId'], r['new_words'] or '-',
                    r['new_grammar'] or '-', r['idioms'] or '-'))
            f.write('\n')
    print('已写出 drop_candidates.md / keep_list.md / plan.json')
    print('确认后执行：python pipeline.py apply')


def cmd_apply(a):
    plan = json.load(open(PLAN, encoding='utf-8'))
    drop = [int(x) for x in plan['drop']]
    if not drop:
        print('plan.json 里没有待弃条目')
        return
    cards = AK.cards_of_notes(drop)
    AK.add_tags(drop, a.drop_tag)
    print('已加标签 %s：%d 张' % (a.drop_tag, len(drop)))
    AK.suspend(cards)
    print('已 suspend：%d 张' % len(cards))
    print('剩余未处理（%s）：%d' % (a.query, AK.count(a.query)))


# ============================================================================
# 阶段 2：split / verify / write
# ============================================================================
SUBAGENT_PROMPT = '''你是精通日语的语言学教授。任务：为一批 Anki 例句卡生成讲解（AINote）与带振假名的例句 HTML（Sentence HTML）。

【第一步】读规范：{doc}

【输入】{gen}\\input_{n:02d}.json
JSON 数组，每项 {{noteId, sentence, word, source}}。sentence 是字幕例句（可能含 <br>）；
word 非空时表示这张卡指定的重点词，核心词汇的第一条必须是它。

【输出】把结果写入 {gen}\\output_{n:02d}.json
JSON 数组，每项 {{noteId, sentence, AINote, SentenceHTML}}，sentence 原样回填。
必须覆盖输入里的每一条，数量与顺序一致。

【禁止】不要调用 AnkiConnect，不要写入 Anki，不要修改输入文件，不要改动 {gen} 目录之外的任何文件。
不要跑 check_cards.py 自检、不要反复重写整批 —— 入库前 write 会统一校验一次，把结果交给它。'''

# 本地模型用的提示词（正本）。**改提示词只改这里**：docs/jp-card-agent-instruction.md 附录 B
# 是它的说明版，SKILL.md 指向本节。特点：自包含（本地模型读不了文件）、一次一批、
# 只输出 JSON、不要自检（校验由 cmd_gen 机械地做一次）。
LOCAL_INSTRUCTION = '''你是精通日语的语言学教授。输入是一批 Anki 例句卡，为每张卡生成讲解（AINote）与带振假名的例句 HTML（SentenceHTML）。

【输入】JSON 数组，每项 {noteId, sentence, word, source}
  sentence：字幕例句原文，可能含 <br>、全角空格、〓 这类字幕噪声——一律原样对待
  word：非空时是这张卡指定的重点词，核心词汇的第一条必须是它
  source：出处，只用来判断语域（动画口语 / 新闻 / 旁白），不要写进结果

【输出】只输出一个 JSON 对象，前后不要任何解释或 markdown 围栏：
{"cards":[{"noteId":123,"AINote":"…","SentenceHTML":"…"}]}
输入里每张卡都要有一条对应输出，noteId 原样照抄，顺序与输入一致。

【AINote】固定三段、每段一个 <p>，第四段按需出现：
<p><b>中文翻译：</b>自然流畅、符合语境的中文翻译。</p>
<p><b>核心词汇：</b><br><ruby>漢字<rt>かな</rt></ruby>：词性。中文释义。（外来语附源词）<br>…</p>
<p><b>语法要点：</b><br>句型：含义 + 接续 + 功能<br>…</p>
<p><b>动词变形解析：</b><br>原形 → 变形（名称） → 变形（名称）＋辅助词<br>…</p>
- 核心词汇只列句中真的出现过的词，2–5 个，不要堆词典；word 非空时它的词条排第一
- 词性用：名词／イ形容词／ナ形容词／自动词／他动词／副词／接续词／惯用句
- 动词变形解析只写句中真实存在的活用（例：戻る（原形）→ 戻っ（连用形·促音便）→ 戻った（た形）＋時に）；
  全句没有活用动词（名词句、形容词句）就整段省略
- 整段 AINote 控制在 400 字以内：这是复习卡，不是词条页

【SentenceHTML】只含例句本身：给日语汉字标 ruby，不加翻译、不加解释、不用 <p> 包裹、
不加句末标点、不改任何空格与标点、<br> 原位置保留单个。

【铁律】
1. 只用 <p> <br> <b> <ruby> <rt> 五个标签；禁止 div/span/style/class 与任何属性
2. 禁止 LaTeX、禁止反斜杠、禁止 $；推导一律用全角箭头 →
3. 禁止 markdown（不要 ``` 围栏、不要 **）；禁止半角双引号 "，需要引号时用「」
4. 送假名放在 <rt> 之外：<ruby>食<rt>た</rt></ruby>べる、<ruby>届<rt>とど</rt></ruby>ける；熟字训整体标：<ruby>今日<rt>きょう</rt></ruby>
5. 敬语接头辞 お/ご 放在 <ruby> 之外：お<ruby>墓<rt>はか</rt></ruby>
6. 纯假名词不标 ruby（不要写 <ruby>と<rt>と</rt></ruby>）；中文汉字绝不标 ruby（中文翻译、中文释义里的字都不标）
7. 读音吃不准的人名、生僻字：不猜，该词不加 ruby，其余照常
8. SentenceHTML 删掉全部 <rt>…</rt> 整块、再剥掉其余标签后，必须与 sentence 逐字相同，<br> 数量也要相同
9. 确实无法给出可靠讲解时（乱码、整句没有可解释的语义单位）：AINote 与 SentenceHTML 都输出空字符串 ""，
   不要编造；其余卡照常生成
10. **值的类型**：noteId 必须是 JSON 数字（照抄输入，别加引号）；AINote / SentenceHTML 的值必须是
   JSON 字符串 —— 不要写数字、true/false、数组或 null（类型不对这张会被打回重做，白跑一趟）
11. 输入里**每张卡都要有一条输出对象**：不确定的卡按第 9 条把两个字段留空，**不要省略整个对象**
12. **振假名以"词"为单位**：读音要覆盖整个汉字词（食わす → くわす），不要只给词的一部分标读音、
   也不要把助词/送假名的读音塞进汉字的 <rt>；同形异读（如 辛い=からい/つらい）拿不准时按第 7 条不加 ruby
13. **核心词汇必须是这句里真出现过的词**：句中是「あの子」，就不要把词条写成「子ども」；
   词典形对活用形（送る → 送った）可以，但必须是同一个词，不许拿上位词/近义词顶替
14. **语法要点要写完整、不自相矛盾**：一句话说完，不要停在「…」「「」这类半截上；
   「一定是～」就写「表示高确信度的推测」，不要写成「觉得一定是～」（既"觉得"又"一定"）

【示例】输入 {"noteId":1,"sentence":"郵便局に戻った時に調べてみるよ","word":"","source":"…"}
输出 {"cards":[{"noteId":1,"AINote":"<p><b>中文翻译：</b>回邮局的时候我查查看。</p><p><b>核心词汇：</b><br><ruby>郵便局<rt>ゆうびんきょく</rt></ruby>：名词。邮局。<br><ruby>戻<rt>もど</rt></ruby>る：自动词（五段）。返回、回到。<br><ruby>調<rt>しら</rt></ruby>べる：他动词（一段）。调查、查询。</p><p><b>语法要点：</b><br>〜た時に：表示「在……的时候」，接在动词た形后，提示后项动作发生的时间点。<br>〜てみる：表示「试着做某事」，接在动词て形后，带有尝试的语感。</p><p><b>动词变形解析：</b><br>戻る（原形）→ 戻っ（连用形·促音便）→ 戻った（た形）＋時に<br>調べる（原形）→ 調べて（て形）＋みる → 調べてみる（〜てみる）</p>","SentenceHTML":"<ruby>郵便局<rt>ゆうびんきょく</rt></ruby>に<ruby>戻<rt>もど</rt></ruby>った<ruby>時<rt>とき</rt></ruby>に<ruby>調<rt>しら</rt></ruby>べてみるよ"}]}

【输出前逐张核对（最常见的三类错误）】
1. SentenceHTML 里**不能有任何 <ruby> 之外的汉字** —— 逐字扫一遍，漏一个就算不合格
2. <br> 的数量与位置和 sentence 完全一致；全角空格、〓 等噪声原样保留
3. 任何半角双引号 " 都换成「」；不要出现 $ 与反斜杠'''

GEN_MAX_TOKENS = 8192        # 单次请求的输出上限（Responses 的 max_output_tokens）


def cmd_split(a):
    tag_query = 'tag:%s AINote:' % a.tag
    ids = AK.find_notes(tag_query)
    if not ids:
        raise SystemExit('没有待生成的卡（查询 %s）' % tag_query)
    cards = [{'noteId': n['noteId'],
              'sentence': n['fields'].get('Sentence', {}).get('value', ''),
              'word': n['fields'].get('Word', {}).get('value', ''),
              'source': n['fields'].get('Source', {}).get('value', '')}
             for n in AK.notes_info(ids)]
    os.makedirs(GEN, exist_ok=True)
    size = (len(cards) + a.batches - 1) // a.batches
    manifest = []
    for b in range(a.batches):
        chunk = cards[b * size:(b + 1) * size]
        if not chunk:
            continue
        name = 'input_%02d.json' % (b + 1)
        json.dump(chunk, open(os.path.join(GEN, name), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        manifest.append({'batch': b + 1, 'input': name,
                         'output': 'output_%02d.json' % (b + 1), 'count': len(chunk)})
    json.dump(manifest, open(os.path.join(GEN, 'manifest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('已切分为 %d 批，共 %d 张（含 Word 重点词 %d 张）'
          % (len(manifest), len(cards), sum(1 for c in cards if c['word'].strip())))
    if not a.print_prompts:
        print('下一步：python pipeline.py gen     # 由本地模型逐批生成（不花云端 token）')
        return
    print()
    print('=' * 76)
    print('本地模型不可用时的备用路径：把下面的提示词发给子代理（会花云端 token）：')
    print('=' * 76)
    for m in manifest:
        print()
        print('---------- 批次 %02d（%d 张）----------' % (m['batch'], m['count']))
        print(SUBAGENT_PROMPT.format(doc=WSP.DOC_JP_CARD, gen=GEN, n=m['batch']))


# ============================================================================
# 阶段 2 · 本地模型生成（gen）
# ============================================================================
def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def group_payload(group):
    """这组卡发给模型的 JSON 正文（分组估算与真实请求**共用同一份**，口径不许漂）。"""
    return json.dumps([{'noteId': int(c['noteId']), 'sentence': c['sentence'],
                        'word': c.get('word', ''), 'source': c.get('source', '')}
                       for c in group], ensure_ascii=False, indent=1)


def group_user(group):
    """一次请求的完整 user 正文（含指令，用于 token 估算）。"""
    return LOCAL_INSTRUCTION + '\n' + group_payload(group)


def fit_groups(items, size, render, cfg, LLM):
    """按 `size` 切块，但**保证每块的 prompt 估算不超本地模型预算**。

    为什么需要它：张数相同、句子长度可以差三倍（长对白 + 生成规范本身就好几千 token）。
    一次塞太多会直接撞 32k 窗口 → `BudgetError` / HTTP 400，**整批白跑**；
    而这类失败最贵的地方在于它出现在"已经跑了几分钟本地算力"之后。
    估算用的是**真实请求正文**（`render` 与 `gen_request` 同一份渲染），宁可多分几次请求。

    单条就超预算的：让它自己一组 —— 调用处的 `try/except` 会把它记成"这组没做出来"
    并落盘留证，下一轮逐张重问，最终进 `failed.json`，不会连累别的卡。
    """
    cap = LLM.budget(cfg)
    out, cur = [], []
    for it in items:
        if cur and (len(cur) >= size or LLM.estimate_tokens(render(cur + [it])) > cap):
            out.append(cur)
            cur = []
        cur.append(it)
    if cur:
        out.append(cur)
    return out


def gen_request(cfg, LLM, group, feedback=None):
    """一次本地模型请求：一组卡 → {noteId: {AINote, SentenceHTML}}。

    feedback 非空时写进用户消息，用于「只重做这批里不合格的那几张」。
    """
    user = group_payload(group)          # 与 fit_groups 的 token 估算共用同一份渲染
    if feedback:
        user += ('\n\n上面这几张卡上一次的输出不合格，问题如下，这次只重做这几张'
                 '（noteId 照抄）：\n' + feedback)
    msgs = [{'role': 'system', 'content': LOCAL_INSTRUCTION},
            {'role': 'user', 'content': user}]
    obj, res, problems = LLM.call_json(cfg, msgs, require='cards', json_mode=True,
                                       enable_thinking=False, quiet=True,
                                       max_tokens=GEN_MAX_TOKENS)
    got = {}
    if isinstance(obj, dict):
        for item in (obj.get('cards') or []):
            if not isinstance(item, dict):
                continue
            nid = OUT.as_int(item.get('noteId'))
            if nid is None:
                continue
            # 本地模型偶尔把这两个字段回成数字/列表 —— 吸收成空串（下面 judge_group 会
            # 按"字段类型不是字符串"判这张卡没做出来），别让 `.strip()` 崩掉整批。
            got[nid] = {'AINote': OUT.as_text(item.get('AINote')),
                        'SentenceHTML': (OUT.as_text(item.get('SentenceHTML'))
                                         or OUT.as_text(item.get('Sentence Html')))}
    if problems:
        print('    ⚠️ 回复形状不合格：%s' % '；'.join(problems)[:160], file=sys.stderr)
    return got, res


def judge_group(group, got):
    """把模型结果拼成卡记录，判一次；返回 (合格的, {noteId: 问题}, {noteId: HTML 机械问题})。

    判断按**字段归属**分开（`check_cards.split_hard`）：

    * **AINote 侧**不合格（讲解缺失、段落不齐、非法字符）→ 这张卡算没做出来，逐张重问。
    * **Sentence HTML 侧**的机械问题（文本漂移、漏标 ruby、`<br>` 数不对）→ **不算失败**：
      讲解照收，HTML 留给 `ruby_engine.py repair` 拿原始 `Sentence` 当骨架重渲染。
      这一类再问一次模型既修不好（它上一轮就是这么标的），还会把合格的讲解一起丢掉
      —— 2026-10-11 七大罪 E01 的 `様子` 就是这么被连坐的。
    """
    ok, bad, mech = {}, {}, {}
    for c in group:
        nid = int(c['noteId'])
        v = got.get(nid)
        if v is None:
            bad[nid] = '模型没有返回这张卡'
            continue
        rec = {'noteId': nid, 'sentence': c['sentence'],
               'AINote': v['AINote'], 'SentenceHTML': v['SentenceHTML']}
        ai_hard, html_hard, _soft = check_cards.split_hard(rec)
        if ai_hard:
            bad[nid] = '；'.join(ai_hard)
            continue
        if html_hard:
            mech[nid] = '；'.join(html_hard)
        ok[nid] = rec
    return ok, bad, mech


FAILED = os.path.join(GEN, 'failed.json')          # 本地模型没做出来的卡（交给强模型收尾）
GEN_RAW = os.path.join(GEN, 'raw')                 # 「这组没做出来」时的模型原始回复


def dump_raw(batch_no, rounds, group, res, why=''):
    """把「这组没做出来」的模型原始回复落盘留证 —— 正常批次不产垃圾。

    以前不留原文：产出出问题时无法回头看成模型到底回了什么，只能靠猜
    （2026-10-12 阶段四的产出被写坏就是这样）。留证失败不影响判定。
    """
    body = ('# 阶段二批次：%s   轮次：%d\n# noteId：%s\n# 问题：%s\n\n'
            % (batch_no, rounds, ','.join(str(c['noteId']) for c in group), why))
    body += OUT.raw_text(res)
    p = OUT.dump_raw(GEN_RAW, 'batch_%02d_r%d' % (batch_no, rounds), body,
                     header='阶段二 gen：这一组没做出来')
    if p:
        print('    模型原始回复已存：%s' % os.path.relpath(p, WSP.ROOT))



def write_output(batch_no, cards, done):
    """写出 output_NN.json：顺序同输入；没做出来的两个字段留空（规范 §8）。"""
    out = []
    for c in cards:
        nid = int(c['noteId'])
        out.append(done.get(nid) or {'noteId': nid, 'sentence': c['sentence'],
                                     'AINote': '', 'SentenceHTML': ''})
    json.dump(out, open(os.path.join(GEN, 'output_%02d.json' % batch_no), 'w',
                        encoding='utf-8'), ensure_ascii=False, indent=1)
    return out


def save_failed(entries):
    """把「本地模型没做出来」的卡写成 failed.json（含失败原因），供强模型收尾。

    条目信息足够让别处独立生成：noteId / sentence / word / source / batch / problems。
    """
    doc = {'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'note': ('这些卡本地模型重试后仍未通过 check_cards；'
                    '用 pipeline.py merge-fix --file <产出> 并回，或人工处理'),
           'cards': entries}
    json.dump(doc, open(FAILED, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return doc


def gen_loop(a, cfg, LLM, cards, batch_no, tag=''):
    """跑一轮「本地模型 + 重问」；返回 (合格, 不合格{noteId: 原因}, token 统计)。

    重问轮**逐张发**（`--per-request` 只管首轮的批量）：小模型在一批里漏标振假名时，
    再把它塞回同一批只会原样再错一次，一张一请求才救得回来。
    Sentence HTML 的机械问题（`judge_group` 的第三个返回值）不在这里重问 —— 交给 repair。
    """
    done, bad, mech = {}, {}, {}
    pending = list(cards)
    rounds, req = 0, 0
    tp = tc = 0
    while pending:
        fb = []
        size = a.per_request if rounds == 0 else 1
        for group in fit_groups(pending, size, group_user, cfg, LLM):
            try:
                got, res = gen_request(cfg, LLM, group,
                                       feedback='\n'.join(fb) if fb else None)
            except Exception as e:
                # **一组出意外只影响这一组**（下一轮逐张重问），绝不带崩整批：
                # 2026-10-12 阶段四就是一条畸形字段把整批 gen 打掉的。
                for c in group:
                    bad[int(c['noteId'])] = '请求/解析异常：%s: %s' % (type(e).__name__, e)
                dump_raw(batch_no, rounds, group, None,
                         '请求异常：%s: %s' % (type(e).__name__, e))
                continue
            req += 1
            tp += res.prompt_tokens
            tc += res.completion_tokens
            try:
                ok, problems, mech_here = judge_group(group, got)
            except Exception as e:
                for c in group:
                    bad[int(c['noteId'])] = '校验异常：%s: %s' % (type(e).__name__, e)
                dump_raw(batch_no, rounds, group, res,
                         '校验异常：%s: %s' % (type(e).__name__, e))
                continue
            done.update(ok)
            bad.update(problems)
            mech.update(mech_here)
            for nid, why in problems.items():
                fb.append('- noteId %d：%s' % (nid, why[:200]))
            if problems:
                dump_raw(batch_no, rounds, group, res,
                         '这组没做出来：%s' % '；'.join(problems.values())[:200])
        if not bad:
            break
        if rounds >= a.retries:
            print('  %s仍有 %d 张没做出来' % (tag, len(bad)))
            break
        rounds += 1
        pending = [c for c in cards if int(c['noteId']) in bad]
        bad = {}
        print('  %s重问第 %d 轮（逐张请求）：%d 张' % (tag, rounds, len(pending)))
    if mech:
        print('  %s%d 张的 Sentence HTML 有机械问题 → 讲解已收下，HTML 交给 ruby_engine.py repair'
              % (tag, len(mech)))
        for nid, why in sorted(mech.items())[:3]:
            print('      noteId %s：%s' % (nid, why[:120]))
    return done, bad, (req, tp, tc)


def output_matches_input(m):
    """这一批的 output_NN.json 是不是**当前 input** 的产出（断点续跑的唯一判据）。

    **只看文件名是不够的。** 同一集跑完一遍之后又导入新卡时，`split` 会原地重写
    `input_NN.json`，而上一趟的 `output_NN.json` 还在、批号也一样 —— 那时它是**另一批卡**
    的产出，照它跳过就等于整批不生成；后面 `stage2_leftovers()` 还会拿这份旧产出验出"合格"，
    `write` 则报"漏卡/多卡"（信息里看不出根因）。2026-10-11 第二次冒烟实测踩到。

    noteId 不是模型产出的一部分，所以这里可以要求**集合相等**。
    """
    ip = os.path.join(GEN, m['input'])
    op = os.path.join(GEN, m['output'])
    if not os.path.exists(op):
        return False
    try:
        want = {int(c['noteId']) for c in json.load(open(ip, encoding='utf-8'))}
        got = {int(c['noteId']) for c in json.load(open(op, encoding='utf-8'))}
    except (ValueError, KeyError, TypeError):
        return False
    return want == got


def cmd_gen(a):
    """直连本地模型生成 output_NN.json。

    默认跳过已存在的批次（可断点续跑，判据见 `output_matches_input`）。
    没做出来的卡汇总进 failed.json，交给强模型（deepseek）用 `merge-fix` 收尾 ——
    本地模型只在**结果可机械校验**的地方顶上，做不出来的不让它硬撑。
    """
    manifest_path = os.path.join(GEN, 'manifest.json')
    if not os.path.exists(manifest_path):
        raise SystemExit('没有 manifest.json，先跑：python pipeline.py split --tag "…"')
    try:
        import local_llm as LLM
    except ImportError as e:
        raise SystemExit('找不到本地模型客户端 code/common/local_llm.py：%s' % e)
    manifest = json.load(open(manifest_path, encoding='utf-8'))
    cfg = LLM.load_config()

    if a.fix_failed:
        return fix_failed(a, cfg, LLM, manifest)

    print('本地模型：%s @ %s（单请求输出上限 %d tokens，每请求 %d 张）'
          % (cfg['model'], cfg['base_url'], GEN_MAX_TOKENS, a.per_request))
    todo = []
    for m in manifest:
        if os.path.exists(os.path.join(GEN, m['output'])) and not a.force:
            if output_matches_input(m):
                print('  批%02d %s 已存在且与输入同源 → 跳过（--force 重做）'
                      % (m['batch'], m['output']))
                continue
            print('  ⚠ 批%02d %s 已存在但与本批输入对不上（同一批号的旧产出）→ 重做'
                  % (m['batch'], m['output']))
        todo.append(m)
    if not todo:
        print('没有要生成的批次。下一步：python pipeline.py write')
        return

    t0 = time.time()
    tot = [0, 0, 0]
    failed = []
    for m in todo:
        cards = json.load(open(os.path.join(GEN, m['input']), encoding='utf-8'))
        done, bad, stat = gen_loop(a, cfg, LLM, cards, m['batch'],
                                   tag='批%02d ' % m['batch'])
        for i in range(3):
            tot[i] += stat[i]
        write_output(m['batch'], cards, done)
        print('  批%02d 写出 %s：%d 张合格 / %d 张待强模型收尾'
              % (m['batch'], m['output'], len(done), len(cards) - len(done)))
        by_id = {int(c['noteId']): c for c in cards}
        for nid, why in sorted(bad.items()):
            c = by_id[nid]
            failed.append({'noteId': nid, 'batch': m['batch'],
                           'sentence': c['sentence'], 'word': c.get('word', ''),
                           'source': c.get('source', ''), 'problems': why})
    print('本地模型结束：%d 次请求，prompt %d + completion %d tokens，耗时 %.0fs'
          % (tot[0], tot[1], tot[2], time.time() - t0))
    if failed:
        save_failed(failed)
        print()
        print('有 %d 张本地模型没做出来 → 已写入 %s' % (len(failed), FAILED))
        print('下一步（交给 deepseek 收尾）：')
        print('  1) 让强模型按 failed.json 生成 data/pipeline/gen/fix_output.json')
        print('     （同样的 JSON 数组格式，只放这些 noteId）')
        print('  2) python pipeline.py merge-fix --file "%s"' % 'fix_output.json')
    else:
        if os.path.exists(FAILED):
            os.remove(FAILED)          # 全部通过就把旧的失败清单清掉，免得强模型去做已经做好的卡
        print('全部一次通过，没有要收尾的。')
    print('下一步：python pipeline.py write')


def fix_failed(a, cfg, LLM, manifest):
    """只重跑 failed.json 里的卡（本地模型逐张再试一遍），修好的直接并回 output_NN.json。"""
    if not os.path.exists(FAILED):
        raise SystemExit('没有 %s（本地模型没有遗留失败项）' % FAILED)
    doc = json.load(open(FAILED, encoding='utf-8'))
    cards = [{'noteId': c['noteId'], 'sentence': c['sentence'],
              'word': c.get('word', ''), 'source': c.get('source', '')}
             for c in doc['cards']]
    if not cards:
        print('failed.json 是空的，没有要重跑的。')
        return
    print('重跑 %d 张（本地模型，逐张请求）' % len(cards))
    done, bad, stat = gen_loop(a, cfg, LLM, cards, 0, tag='收尾 ')
    patch_outputs(done)
    remain = [{'noteId': int(c['noteId']), 'batch': d['batch'],
               'sentence': c['sentence'], 'word': c.get('word', ''),
               'source': c.get('source', ''), 'problems': bad.get(int(c['noteId']), '')}
              for c, d in zip(cards, doc['cards']) if int(c['noteId']) in bad]
    if remain:
        save_failed(remain)
    else:
        # 一张不剩就把 failed.json 删掉：留个空壳会让 episode.py 每次都白跑一轮
        # 「gen --fix-failed」，下一个人还会以为有活没干完。
        if os.path.exists(FAILED):
            os.remove(FAILED)
    print('本轮修好 %d 张，仍剩 %d 张没做出来（%s）'
          % (len(done), len(remain),
             '已更新 failed.json' if remain else 'failed.json 已清空'))
    print('  %d 次请求，prompt %d + completion %d tokens' % stat)
    if remain:
        print('剩下的交给强模型：生成 fix_output.json 后跑 merge-fix')
    else:
        print('下一步：python pipeline.py write')


def patch_outputs(done):
    """把 {noteId: 记录} 并回对应批次的 output_NN.json。返回改动的卡数。"""
    if not done:
        return 0
    manifest = json.load(open(os.path.join(GEN, 'manifest.json'), encoding='utf-8'))
    n = 0
    for m in manifest:
        p = os.path.join(GEN, m['output'])
        if not os.path.exists(p):
            continue
        out = json.load(open(p, encoding='utf-8'))
        changed = False
        for i, rec in enumerate(out):
            v = done.get(int(rec['noteId']))
            if v:
                out[i] = v
                changed = True
                n += 1
        if changed:
            json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return n


def cmd_merge_fix(a):
    """把强模型（deepseek）补做的 fix 产出并回 output_NN.json。

    校验口径与生成时**同一份**（check_cards）—— 不是第二道网，是接收入库产出的唯一一道。
    """
    path = a.file
    if not os.path.isabs(path):
        path = os.path.join(GEN, path)
    if not os.path.exists(path):
        raise SystemExit('找不到 %s' % path)
    merge = json.load(open(path, encoding='utf-8'))
    if isinstance(merge, dict):                       # 容忍 {"cards":[…]}
        merge = merge.get('cards') or merge.get('outputs') or []
    by_id = {}
    for c in merge:
        if not isinstance(c, dict) or c.get('noteId') is None:
            continue
        by_id[int(c['noteId'])] = c
    print('fix 文件 %s：%d 条' % (path, len(by_id)))
    ok, bad, mech = {}, {}, {}
    for nid, c in by_id.items():
        rec = {'noteId': nid, 'sentence': c.get('sentence', ''),
               'AINote': c.get('AINote', ''), 'SentenceHTML': c.get('SentenceHTML', '')}
        ai_hard, html_hard, _soft = check_cards.split_hard(rec)
        if ai_hard:
            bad[nid] = '；'.join(ai_hard)
        else:
            if html_hard:
                mech[nid] = '；'.join(html_hard)
            ok[nid] = rec
    n = patch_outputs(ok)
    print('并入 %d 张（不合格 %d 张）' % (n, len(bad)))
    for nid, why in sorted(bad.items())[:10]:
        print('  ✗ %s %s' % (nid, why[:160]))
    if mech:
        print('  其中 %d 张的 Sentence HTML 有机械问题（讲解照收）→ 跑 '
              'ruby_engine.py repair --gen "%s" --write 重渲染' % (len(mech), GEN))
    if os.path.exists(FAILED):
        doc = json.load(open(FAILED, encoding='utf-8'))
        remain = [c for c in doc['cards'] if int(c['noteId']) not in ok]
        if remain:
            save_failed(remain)
        else:
            os.remove(FAILED)          # 别留空壳（见 fix_failed 的注释）
        print('failed.json 剩余 %d 张' % len(remain))
    print('下一步：python pipeline.py write')


def collect_outputs():
    """读 manifest 与本集各批 output_NN.json。

    返回 (merged, expected_noteIds, 缺失的批次文件)。
    """
    manifest = json.load(open(os.path.join(GEN, 'manifest.json'), encoding='utf-8'))
    merged, expected, missing = [], set(), []
    for m in manifest:
        for c in json.load(open(os.path.join(GEN, m['input']), encoding='utf-8')):
            expected.add(int(c['noteId']))
        p = os.path.join(GEN, m['output'])
        if not os.path.exists(p):
            missing.append(m['output'])
            continue
        merged.extend(json.load(open(p, encoding='utf-8')))
    return merged, expected, missing


def check_outputs(merged, expected):
    """结构规则 + 覆盖率。**全流程只跑这一处**：verify 与 write 共用。

    返回 (不合格, 重复, 漏卡, 多卡)。子代理已经用同一个 check_cards.py 自检过一遍，
    这里跑第二遍只花几十毫秒、不花 token，所以保留「入库前跑一次」这一道，
    但不再在入库后又把全部字段拉回来逐字重比（见 cmd_write 的轻量回读）。
    """
    bad = []
    for c in merged:
        hard, _ = check_cards.check(c)
        if hard:
            bad.append((c['noteId'], hard))
    seen = [int(c['noteId']) for c in merged]
    dup = sorted({x for x in seen if seen.count(x) > 1})
    got = set(seen)
    return bad, dup, sorted(expected - got), sorted(got - expected)


def _html_side(problems):
    """这些硬性问题是不是**只在 Sentence HTML 侧**（机械问题 → repair 能修，不必问模型）。"""
    return any(p.startswith('Sentence HTML') or p.startswith('<br> 数量')
               or p.startswith('AINote 有内容但 Sentence HTML 为空')
               for p in problems)


def report_outputs(merged, expected, checked):
    bad, dup, miss, extra = checked
    print('汇总 %d 条（应覆盖 %d 条）' % (len(merged), len(expected)))
    print('不合格 %d 条' % len(bad))
    for nid, hard in bad:
        print('  %s %s' % (nid, hard))
    n_html = len([1 for _nid, hard in bad if _html_side(hard)])
    if n_html:
        print('  提示：其中 %d 条的问题只在 Sentence HTML 侧（机械问题）→ 先跑 '
              'ruby_engine.py repair --gen "%s" --write 重渲染；不要为它去重问模型。'
              % (n_html, GEN))
    print('漏卡 %d 条 %s' % (len(miss), miss[:10]))
    print('多卡 %d 条 %s' % (len(extra), extra[:10]))
    print('重复 %d 条 %s' % (len(dup), dup[:10]))
    return bool(bad or dup or miss or extra)


def cmd_verify(_a):
    """只校验不入库。**不是必经步骤** —— write 会跑同一份校验，平时直接 write 即可。"""
    merged, expected, missing = collect_outputs()
    if missing:
        raise SystemExit('尚未生成：%s' % ', '.join(missing))
    if report_outputs(merged, expected, check_outputs(merged, expected)):
        raise SystemExit('存在问题，未通过。')
    print('全部通过。执行：python pipeline.py write')


def cmd_write(a):
    merged, expected, missing = collect_outputs()
    if missing:
        raise SystemExit('尚未生成：%s' % ', '.join(missing))
    if not a.skip_check:
        if report_outputs(merged, expected, check_outputs(merged, expected)):
            raise SystemExit('存在问题，未通过（加 --skip-check 可跳过校验直接写库）。')

    by_id = {int(c['noteId']): c for c in merged}
    ids = sorted(by_id)
    if not ids:
        print('没有待写入的卡。')
        return
    info = AK.notes_map(ids)
    notempty = [i for i in ids
                if info[i]['fields']['AINote']['value'] or info[i]['fields']['Sentence HTML']['value']]
    if notempty and not a.overwrite:
        raise SystemExit('以下卡已有内容，拒绝覆盖（加 --overwrite 可强制）：%s' % notempty[:10])
    for i, nid in enumerate(ids, 1):
        c = by_id[nid]
        AK.update_note_fields(nid, {'AINote': c['AINote'],
                                    'Sentence HTML': c['SentenceHTML']})
        if i % 25 == 0:
            print('  已写入 %d/%d' % (i, len(ids)))
    print('写入完成：%d 张' % len(ids))

    # 轻量回读：一次查询统计「AINote 仍为空」的卡（有意跳过的卡本来就该是空的），
    # 再抽 3 张逐字比对兜底。原来是把全部卡的字段拉回来逐字重比一遍 ——
    # 那是把入库前已经跑过的规则又算了一遍，收益低于它的耗时。
    skipped = [i for i in ids if not by_id[i]['AINote']]
    still = AK.find_notes('nid:%s AINote:' % ','.join(str(i) for i in ids))
    unexpected = [i for i in still if i not in skipped]
    sample = ids[:3]
    back = AK.notes_map(sample)
    mism = [i for i in sample
            if i not in back
            or back[i]['fields']['AINote']['value'] != by_id[i]['AINote']
            or back[i]['fields']['Sentence HTML']['value'] != by_id[i]['SentenceHTML']]
    print('回读：抽查 %d 张逐字一致 %d 张；AINote 仍为空 %d 张（有意跳过 %d、异常 %d）'
          % (len(sample), len(sample) - len(mism), len(still), len(skipped), len(unexpected)))
    if mism:
        print('  抽查不一致：%s' % mism)
    if unexpected:
        print('  未写进去：%s' % unexpected[:10])


# ============================================================================
def main():
    ap = argparse.ArgumentParser(description='日语字幕卡流水线')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('prepare', help='拉取词表/语法表/参照系并缓存')

    p = sub.add_parser('triage', help='三维判定，出报告（不改库）')
    p.add_argument('--query', default='tag:%s' % CFG['pending_tag'])

    p = sub.add_parser('apply', help='给 plan.json 的弃用集打标签并 suspend')
    p.add_argument('--drop-tag', default=CFG['drop_tag'])
    p.add_argument('--query', default='tag:%s' % CFG['pending_tag'])

    p = sub.add_parser('split', help='把待生成卡切批（下一步交给 gen）')
    p.add_argument('--tag', required=True, help='本集标签（与作品无关），如 动画::<作品名>::<季>::第NN集')
    p.add_argument('--batches', type=int, default=12)
    p.add_argument('--print-prompts', action='store_true',
                   help='本地模型不可用时，打印子代理提示词（备用路径，会花云端 token）')

    p = sub.add_parser('gen', help='直连本地模型生成 output_NN.json（默认跳过已存在的批次）')
    p.add_argument('--per-request', type=int, default=6, help='首轮每次请求几张卡（默认 6）')
    p.add_argument('--retries', type=int, default=1, help='不合格时带问题重问的轮数（默认 1；重问逐张发）')
    p.add_argument('--force', action='store_true', help='已存在的 output_NN.json 也重做')
    p.add_argument('--fix-failed', action='store_true',
                   help='只重跑 failed.json 里的卡（本地模型再试一遍，修好的并回 output_NN.json）')

    p = sub.add_parser('merge-fix', help='把强模型（deepseek）补做的 fix 产出并回 output_NN.json')
    p.add_argument('--file', default='fix_output.json',
                   help='fix 产出文件（默认 data/pipeline/gen/fix_output.json）')

    sub.add_parser('verify', help='只校验不入库（可选；write 会跑同一份校验）')
    p = sub.add_parser('write', help='校验后写入 Anki')
    p.add_argument('--overwrite', action='store_true', help='目标字段已有内容时也覆盖')
    p.add_argument('--skip-check', action='store_true', help='跳过入库前校验（不推荐）')

    a = ap.parse_args()
    with AK.guard():          # AnkiConnect 出错 → 中文提示，不出 traceback
        {'prepare': cmd_prepare, 'triage': cmd_triage, 'apply': cmd_apply,
         'split': cmd_split, 'gen': cmd_gen, 'merge-fix': cmd_merge_fix,
         'verify': cmd_verify, 'write': cmd_write}[a.cmd](a)


if __name__ == '__main__':
    main()
