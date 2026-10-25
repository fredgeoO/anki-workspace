# -*- coding: utf-8 -*-
"""阶段四 · 素材生词牌组（第三个词汇牌组）

牌组：`0-日本语学习::0-词汇::0-素材生词`（与 core6000、考级词汇同级）

收录判据（用户定义）
--------------------
**只收录「不存在于已有两组词汇牌组中的词」**：
  - 判定用 `pipeline.rebuild_known_index()` 建的索引，覆盖
    `0-词汇::2-考级词汇`（10,609 张，字段 VocabKanji）
    + `0-词汇::1-高频日语单词 6000`（6,000 张，字段 Word）
    = 11,728 个词典形 / 229,007 个可识别写法。
  - **词形比对口径**：去掉 `〜`、NFKC 统一全半角、再去掉空白后逐字比对；
    活用形（食べた→食べる）、平假名↔片假名变体、活用词干都算**同一个词**。
    因此 `漕い` 会因 `漕ぐ`（在 jp-core 里）被判为「已存在」。
  - 词汇来源是 `0-日本语学习::2-例句` 里**最终保留**的字幕例句（弃用卡不算）。

五个子命令（与 pipeline.py 的 split/gen/write 同构）
---------------------------------------------------
    # 1. 只读扫描：从例句里挖候选，出报告 + plan_mine.json（不写库）
    python mine.py scan
    python mine.py scan --tag "动画::Aria The Animation::第04集" --limit 200

    # 2. 切批 + 本地模型判定（2026-10-11 起不派子代理；本地模型读不了文件，
    #    规范压进脚本里的 MINE_INSTRUCTION）
    python mine.py split --batches 8
    python mine.py gen                     # 直连本地模型 → data/vocab/gen_mine/output_NN.json

    # 3. 入库（默认演练；--commit 才真写）
    #    产出有变动时 write 会自己先校验一遍（含"是否真的不在已有牌组里"），
    #    校验通过的载荷存成 verified.json；紧接着的 --commit 直接复用，不再校验第二遍。
    #    写入时每条 note 会打：素材生词::<日期>（溯源）+ 素材生词::<来源>（如有）；
    #    2026-10-06 起不再写准入标签（筛选牌组机制已退场）
    python mine.py write
    python mine.py write --commit

    # 4.（可选）只想看校验报告、先不入库时才单独跑：
    python mine.py verify

为什么挖掘要过一道判定（本地模型 / 子代理）
------------------------------------------
纯脚本的「残差法」只能给出**候选**，噪声很大且性质各异：
  - 碎片：`を訪ね`、`は香`、`の激`（已知词没覆盖到的活用形/复合词切片）
  - 专有名词：`山崎`、`藍華`、`河合`、`灯里`（人名，不是生词）
  - 真实生词：`漕ぐ`、`突如`、`沈む`
脚本无法可靠区分「碎片 / 人名 / 生词」，也不该猜词形和释义。
所以脚本负责**确定性的部分**（切词边界、查重、校验、写库），
判定方负责**语义部分**（判定是不是词、给出词典形/读音/词性/释义/翻译）。
默认走本地模型（`mine.py gen`，零云端 token）；本地端点不可用时用
`split --print-prompts` 派子代理。这与 pipeline.py 阶段二的分工一致。

依赖：AnkiConnect 在 127.0.0.1:8765；code/execution/pipeline.py、code/common/check_cards.py
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))   # paths.py / check_cards.py
sys.path.insert(0, _HERE)                                           # pipeline.py
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'analysis', 'vocab_cover'))  # _norm.py
import anki_api as AK      # noqa: E402  唯一的 Anki 访问点
import paths as WSP        # noqa: E402  工作区路径的唯一来源
import pipeline as P       # noqa: E402  复用 CFG / norm / build_variants
import check_mine as CM    # noqa: E402  生词条目的**唯一**规则实现（子代理自检也用它）
import llm_out as OUT      # noqa: E402  模型产出吸收层（类型归一 / 原始回复留证）
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
from _norm import norm_word, primary_form  # noqa: E402  词形归一的唯一实现

GEN = os.path.join(WSP.DATA_VOCAB, 'gen_mine')   # 阶段四工作目录（原 ./gen_mine）
PLAN = os.path.join(WSP.DATA_VOCAB, 'plan_mine.json')
CAND = os.path.join(WSP.DATA_VOCAB, 'mine_candidates.json')
REPORT = os.path.join(WSP.DATA_VOCAB, 'mine_report.md')

# JitenAnimeRank：Jiten 词频排名，也是这个笔记类型的**排序字段**。
# 与 freq_external.py field --all-notes 用同一份词表 + 同一套归一化（_norm）。
# 2026-10-12 前 mine.py 不写这个字段 → 新卡上线后该字段是空的（老卡都有值），
# 用户口径是「排序只认 JitenAnimeRank」，所以入库时就写。
JITEN_WORDS = os.path.join(WSP.DATA, 'vocab_cover', 'study_plan_jiten_anime.json')
JITEN_NO_RANK = '999999'        # 词表里没有的词：文本序排最后

# 历史：2026-10-05 设计曾给生词卡统一打「素材优先」准入标签（筛选牌组用，与
# activate.py 的历史准入标签一致）。筛选牌组机制 2026-10-06 退场后，
# 本脚本不再写该标签（2026-10-10 移除）。新卡全局顺序见 docs/decisions/。

# ── 残差过滤：这些是助词/指示词/形式名词，永远不是「生词」 ──────────────
STOP = set("""
は が を に で と も の や か ね よ な さ し て ば げ へ ぞ ぜ わ い ん っ
から まで より なら しか こそ さえ すら ほど くらい ぐらい まま ところ だけ ばかり
あと まえ なか そと うち むこう こっち あっち どっち どこ いつ だれ なん なに なぜ どう
どれ この その あの こんな そんな あんな どんな こう そう ああ
これ それ あれ ここ そこ あそこ わたし ぼく きみ あなた みんな
です ます でした ました ません ある いる なる する いう いく くる みる おく しまう
から ので のに けど けれど ても でも では には とは って という といった として
""".split())

# 片假名外来语对中文母语者多半不算真生词，排序时压后（但仍然可以收）
KATA_PENALTY = 0.35

# ── 功能词（助词/助动词/补助用言/终助词）────────────────────────────────
# 必须一起参与「最长匹配覆盖」，否则 `が`/`を`/`の` 这种单字助词不被覆盖，
# 残差会变成 `が広がってます` 这样的整段，而不是干净的词。
# 这份表**只用于切词边界**，不参与「是否已存在于已有牌组」的判定。
FUNCTIONAL = """
は が を に で と も の や か ね よ な さ し て ば げ へ ぞ ぜ わ い ん っ り る た だ を
から まで より なら しか こそ さえ すら ほど くらい ぐらい まま ところ だけ ばかり のに ので けど けれど
では には とは って でも ても とも からは からも までは にまで
です ます でした ました ません ましょう でしょう でしょうね ですね ますね ますよ
だ た て で ない なく なかっ なけれ ず ぬ ずに なくて なかった
ある あり いる い いた おる おります なる なり なっ する し した して します しよう すれ される された
いう いっ いわ いえ いうこと という といった として にとって について によって において に関して に対して
れる られる れた られた せる させる せた させた たい たく たかっ たけれ
そう よう らしい みたい っぽい かもしれ かも かしら かな だろう でしょう
ている ています ていた てます てる てた ておく ておい ておき てしまう てしまっ ちゃう ちゃっ じゃう
てくれ てくだ てくださ てもら ていただ てあげ てみる てみ てくる てき てきた ていく ていっ
ながら たり だり つつ れば たら なら と ったら だったら んだったら
こと もの わけ はず つもり ほう ため よう そう らしい べき かどうか
お ご すぎ 過ぎ きる 切る だす 出す こむ 込む あう 合う なおす 直す かける 続ける 始める 終わる 終える 終わる
""".split()
# 功能词的活用尾（动词/形容词词干后常见）
FUNCTIONAL_SUFFIX = """
ます ました ません ませんでした ている ています ていた てます てる てた ておく てしまう
ちゃう ちゃった じゃう てくれ てください てもらう ていただく てあげる てみる てくる ていく
たい たかった たくない たければ そう よう らしい みたい ので のに けど けれど から まで
ば たら なら ても でも ながら たり だり ずに なくて ない なかった ぬ れる られる せる させる
""".split()


def functional_words():
    """功能词表（含活用尾）。"""
    s = set(FUNCTIONAL) | set(FUNCTIONAL_SUFFIX)
    return {w for w in s if w}


def build_head_index(words):
    """词表 → {首字: [词…]}，每个首字下按长度降序（最长匹配用）。"""
    heads = defaultdict(list)
    for w in words:
        if w:
            heads[w[0]].append(w)
    for k in heads:
        heads[k] = sorted(set(heads[k]), key=len, reverse=True)
    return heads


def trim_functional(s):
    """把功能词从残差两端剥掉（`が広がっ` → `広がっ`）。剥不动就原样返回。"""
    func = functional_words()
    words = sorted(func, key=len, reverse=True)
    changed = True
    while changed and s:
        changed = False
        for w in words:
            if len(w) < len(s) and s.startswith(w):
                s = s[len(w):]
                changed = True
                break
            if len(w) < len(s) and s.endswith(w):
                s = s[:-len(w)]
                changed = True
                break
    # 单字助词兜底（`の`/`が` 之类可能被夹在中间）
    while len(s) > 1 and s[0] in 'はがをにでとものやかねよなへ':
        s = s[1:]
    return s


# ============================================================================
# 词表索引与「已存在」判定
# ============================================================================
def build_index():
    """返回 (canonical, variant2c, heads)。

    heads: 首字 → [词…]（按长度降序）。**只含词典形**——
    任何活用形都以其词典形为前缀，所以句内最长匹配用词典形就够，
    不必把 229k 个变体全部塞进来。
    额外并入功能词表，用于切词边界（见 FUNCTIONAL 的说明）。
    """
    print('构建「已有词汇牌组」索引（收录判据的参照系）…')
    t0 = time.time()
    canonical, variant2c = P.rebuild_known_index()
    heads = build_head_index(set(canonical) | functional_words())
    print('  词典形 %d / 可识别写法 %d / 首字数 %d / 功能词 %d  (%.1fs)'
          % (len(canonical), len(variant2c), len(heads),
             len(functional_words()), time.time() - t0))
    return canonical, variant2c, heads


def find_matches(raw, heads, min_len=1):
    """句内最长匹配，返回 [(start, end, 词)]（不重叠）。"""
    out = []
    i, n = 0, len(raw)
    while i < n:
        for w in heads.get(raw[i], ()):        # 已按长度降序
            if len(w) >= min_len and raw.startswith(w, i):
                out.append((i, i + len(w), w))
                i += len(w)
                break
        else:
            i += 1
    return out


def extract_residuals(raw, heads):
    """已知词覆盖之外的连续日文片段。

    用「最长匹配 + 覆盖标记」而不是切分，避免 `いやあった` 里命中 `やあ` 这类误切。
    覆盖块之间的空隙即残差；对残差再跑一次匹配，把嵌在中间却跨块的已知词抠掉
    （残差 `を訪ね` 里的 `を` 会被二次匹配识别并剔除，剩 `訪ね`）。
    """
    covered = [False] * len(raw)
    for s, e, _w in find_matches(raw, heads):
        for j in range(s, e):
            covered[j] = True
    segs, cur = [], []
    for ch, cov in zip(raw, covered):
        if P.KANJI.match(ch) or P.KANA.match(ch):
            if cov:
                if cur:
                    segs.append(''.join(cur))
                    cur = []
            else:
                cur.append(ch)
        else:
            if cur:
                segs.append(''.join(cur))
                cur = []
    if cur:
        segs.append(''.join(cur))

    out = []
    for s in segs:
        inner = find_matches(s, heads)
        if not inner:
            out.append(s)
            continue
        covered2 = [False] * len(s)
        for a, b, _w in inner:
            for j in range(a, b):
                covered2[j] = True
        cur = []
        for ch, cov in zip(s, covered2):
            if cov:
                if cur:
                    out.append(''.join(cur))
                    cur = []
            else:
                cur.append(ch)
        if cur:
            out.append(''.join(cur))
    return [r for r in out if r]


def is_vocab_like(rn, strict=True):
    """残差是否「像一个词」。只做确定性判断，语义判断交给子代理。

    `strict=False` 给例句卡的 `Word` 字段（**人工点名的重点词**）用：不再套残差法的长度下限。
    那把尺子（"含汉字至少 2 字"）是为了滤掉最长匹配吃剩下的单字碎片，而人工点名恰恰可能是
    单字词 —— 2026-10-11 实测：`Word` = `剣`（两个词汇 deck 里都没有卡）被静默丢掉，
    进去判定的反而是一条伪残留 `剣持`，这条例句卡一个生词卡都没产出。
    收不收仍然交给模型判 `include`，这里只决定"要不要送进去判"。
    """
    if not rn or rn in STOP:
        return False
    if not (P.KANJI.search(rn) or P.KANA.search(rn)):
        return False
    if not strict:
        return True
    if P.KATA_ONLY.match(rn):
        return len(rn) >= 3          # 片假名 2 字极易是外来语碎片
    if P.KANA_ONLY.match(rn):
        return len(rn) >= 3          # 纯假名 2 字全是助词/语气词
    return len(rn) >= 2              # 含汉字：至少 2 字


def hit_inflection(cand, canonical, variant2c=None):
    """判定 cand 是否为某个**已知词典形**的活用形。

    两个来源，缺一不可：
      ① 变体表（variant2c）：pipeline.build_variants 已为含汉字的词生成活用词干
         （信じる→信じ、食べる→食べ），直接查表最准。
         ★ 只对**含汉字**的候选查表：变体表对片假名词也做了 kata2hira
         （デモ→でも），拿它去匹配纯假名候选会把「でも」这种高频语法词
         误判成「已存在」。
      ② 反向推活用形：变体表只生成「词干」，词干之外的活用形（作ろう→作る、
         読め→読む、甘く→甘い）要靠这里补。

    命中即说明「这个词已经在 core6000/考级词汇里了」，不该收。
    返回命中的词典形（或词干），或 None。
    """
    if len(cand) < 2:
        return None
    stem, last = cand[:-1], cand[-1]
    hyp = set()

    # 一段动词：去掉尾假名加 る（食べ→食べる、信じ→信じる、見え→見える）。
    # 必须覆盖**全部**い段/え段假名（含浊音 じ/ぢ/び/ぎ），否则会漏掉
    # 上一段动词（信じる・感じる・過ぎる…）——漏掉的后果是把单纯的活用形
    # 当成生词收进牌组（「信じ」不是词，「信じる」才是）。
    if last in 'いきぎしじちぢにひびみりえけげせぜてでねへべめれ':
        hyp.add(stem + 'る')

    # 五段动词：い段 → う段（漕い→漕ぐ、書い→書く）；お段→う段（作ろう→作る）
    for row_u, row_i in (('う', 'い'), ('く', 'き'), ('ぐ', 'ぎ'), ('す', 'し'),
                         ('つ', 'ち'), ('ぬ', 'に'), ('ぶ', 'び'), ('む', 'み'),
                         ('る', 'り')):
        if last == row_i:
            hyp.add(stem + row_u)
    for row_u, row_o in (('う', 'お'), ('く', 'こ'), ('す', 'そ'), ('つ', 'と'),
                         ('ぬ', 'の'), ('ぶ', 'ぼ'), ('む', 'も'), ('る', 'ろ')):
        if last == row_o:
            hyp.add(stem + row_u)

    # イ形容词：甘く→甘い、涼し→涼しい
    if last == 'く':
        hyp.add(stem + 'い')
    if last in 'し':
        hyp.add(stem + 'しい')

    # サ変/カ変的常见残留
    if last == 'し':
        hyp.add(stem + 'する')

    for h in hyp:
        if h in canonical:
            return h
    # ① 变体表（只对含汉字的候选，理由见 docstring）
    if variant2c and P.KANJI.search(cand):
        v = variant2c.get(cand)
        if v:
            return v
    return None


def grammar_patterns():
    """语法条目 deck 的句型 + EXTRA_GRAMMAR，取「可出现的字面形式」。

    用途：把 `〜なくちゃ`、`〜てしまう` 这类**语法点**从生词候选里剔掉。
    `くちゃ` 就是这么漏出来的：`なく` 被功能词表覆盖，剩下 `くちゃ` 看着像个词，
    其实是 `〜なくちゃ`（必须…）的一部分。语法已经在 1-语法 牌组里了，
    不该再占生词卡。
    """
    pat = set()
    for part in P.build_grammar():
        for piece in re.split(r'[〜・/～\s]+', part):
            piece = piece.strip('（）()')
            if len(piece) >= 2 and not re.search(r'[A-Za-z]', piece):
                pat.add(piece)
    return pat


def is_grammar_fragment(rn, gpat):
    """残差是否是某个语法句型的片段（含其本身）。"""
    return any(g in rn or rn in g for g in gpat)


def known_lookups(c, variant2c, canonical):
    """返回 (canonical_hit, variant_hit, inflection_hit)。"""
    key = P.norm(c).strip('〜～')
    return (canonical.get(key), variant2c.get(key),
            hit_inflection(key, canonical, variant2c))


# ============================================================================
# 阶段 4.1：scan —— 只读扫描，产出候选
# ============================================================================
def cmd_scan(a):
    canonical, variant2c, heads = build_index()
    print('拉取语法表 / 熟语表（用于给候选打标签，不参与收录判定）…')
    grammar = P.build_grammar()
    gpat = sorted(grammar, key=len, reverse=True)
    # 语法句型的字面形式：只用来**剔除**语法片段，不参与「已存在」判定
    gexcl = sorted(grammar_patterns(), key=len, reverse=True)

    q = 'deck:"%s"' % P.CFG['deck']
    if a.tag:
        q += ' tag:"%s"' % a.tag
    ids = AK.find_notes(q)
    if not ids:
        raise SystemExit('没有命中例句卡（查询 %s）' % q)
    notes = AK.notes_info(ids)
    print('例句源：%s   命中 %d 张' % (q, len(notes)))

    seen_notes = set()
    by_word = {}
    dup_sentences = 0
    n_infl = n_gram = 0
    for n in notes:
        nid = int(n['noteId'])
        # ★ 存两份，用途完全不同，不能混：
        #   sent_raw  = Sentence 字段原文（保留 <br> 与全角空格）→ 写进生词卡的 Sentence
        #   sent_html = Sentence HTML 字段（带 <ruby>）→ 写进生词卡的 Sentence HTML
        # 生词卡复用例句卡**已经校验过**的振假名，不重新生成。
        # 早期版本误把 strip_html(sent_raw) 当成 sentence_html 存下来，
        # 结果新卡的例句一行到底、且一个振假名都没有 —— 已修。
        sent_raw = n['fields'].get('Sentence', {}).get('value', '') or ''
        sent_html = n['fields'].get('Sentence HTML', {}).get('value', '') or ''
        if not sent_html.strip():
            sent_html = sent_raw
        raw = P.strip_html(sent_raw).replace('\u3000', ' ')
        if not raw.strip():
            continue
        dk = P.dupkey(sent_raw)
        if dk and dk in seen_notes:        # 同一句话在库里有多张卡，只当一次来源
            dup_sentences += 1
            continue
        if dk:
            seen_notes.add(dk)
        src = (n['fields'].get('Source', {}).get('value', '') or '').split('(')[0].strip()
        for r in extract_residuals(raw, heads):
            rn = P.norm(trim_functional(r))
            if not is_vocab_like(rn):
                continue
            # 已是已知词的活用形（食べ←食べる、訪ね←訪ねる）→ 不是生词，直接丢。
            # 剥功能词后会暴露新的已知词，所以再判一轮。
            # 三个口径合并成「是否已存在」：词典形 / 变体表 / 反向活用。
            hit = next((h for h in known_lookups(rn, variant2c, canonical) if h), None)
            if not hit:
                rn2 = P.norm(trim_functional(rn))
                if rn2 != rn and is_vocab_like(rn2):
                    rn = rn2
                    hit = next((h for h in known_lookups(rn, variant2c, canonical) if h), None)
            if hit:
                n_infl += 1
                continue
            # 语法句型的片段（`くちゃ` ← `〜なくちゃ`）→ 语法已在 1-语法 牌组里
            if is_grammar_fragment(rn, gexcl):
                n_gram += 1
                continue
            e = by_word.setdefault(rn, {'word': rn, 'raw': r, 'count': 0,
                                        'occurrences': [], 'scripts': set()})
            e['count'] += 1
            e['scripts'].add('kanji' if P.KANJI.search(rn) else 'kana')
            if len(e['occurrences']) < a.max_examples:
                e['occurrences'].append({'noteId': nid, 'sentence': sent_raw,
                                         'sentence_html': sent_html, 'source': src})

    # ── 例句卡自带的 `Word` 字段（人工指定的重点词）也当候选 ────────────────
    # 残差法有个**结构性盲区**：最长匹配会把多字词吃掉一半 —— `王女`→`王`+`女`、
    # `魔道具`→`魔`+`道具`、`陛下`→`陛`+`下`（`道具`/`下`/`女` 都在已有牌组里），
    # 剩下一两个单字残差被 is_vocab_like 丢掉 → 这类词**永远进不了候选**。
    # 例句卡的 Word 字段正是人工补这个盲区的信号（2026-10-11 实测：53 张里 29 张有 Word，
    # 其中 24 个词残差法一个都没扫出来）。所以直接把它加成候选；
    # 已有牌组里就有的（補充/無駄/様…）在这里先滤掉，不浪费判定。
    n_word = 0
    skip_word = []
    skip_shape = []
    if a.word_field:
        for n in notes:
            w0 = (n['fields'].get('Word', {}).get('value', '') or '').strip()
            if not w0:
                continue
            w = P.norm(w0.replace('〜', '').replace('～', ''))
            if not w or w in by_word:
                continue
            # ★ 人工点名的词不套残差法的长度下限（单字的 `剣` 曾被它丢掉）
            if not is_vocab_like(w, strict=False):
                skip_shape.append(w0)
                continue
            if next((h for h in known_lookups(w, variant2c, canonical) if h), None):
                continue
            sr = n['fields'].get('Sentence', {}).get('value', '') or ''
            # 词必须在例句里找得到 —— 否则入库时定位不到原句（write 会直接判不合格），
            # 与其让它走到那一步，不如在这里就丢掉（记下清单供人复核）。
            plain = P.norm(P.strip_html(sr))
            if w not in plain and (len(w) < 3 or w[:-1] not in plain):
                skip_word.append(w0)
                continue
            sh = n['fields'].get('Sentence HTML', {}).get('value', '') or ''
            if not sh.strip():
                sh = sr
            by_word[w] = {'word': w, 'raw': w0, 'count': 1,
                          'occurrences': [{'noteId': int(n['noteId']), 'sentence': sr,
                                           'sentence_html': sh,
                                           'source': (n['fields'].get('Source', {})
                                                      .get('value', '') or '').split('(')[0].strip()}],
                          'scripts': {'kanji' if P.KANJI.search(w) else 'kana'},
                          'from_word_field': True}
            n_word += 1

    # 语法/熟语命中：只是标签，帮助人工与子代理判断
    ipat = sorted(set(P.IDIOMS), key=len, reverse=True)
    for rn, e in by_word.items():
        tg = []
        if any(p in rn for p in gpat if len(p) >= 2):
            tg.append('语法')
        if any(p in rn for p in ipat):
            tg.append('惯用')
        if rn in STOP:
            tg.append('停用')
        e['tags'] = tg
        e['kana_only'] = bool(P.KANA_ONLY.match(rn) or P.KATA_ONLY.match(rn))
        e['len'] = len(rn)

    # 排序：出现次数 → 长度 → 片假名降权。用户口径是「都收进来」，
    # 这个顺序只用来决定 --limit 截断时先给谁。
    def score(e):
        s = e['count'] * 10 + e['len']
        if e['kana_only'] and not P.KANJI.search(e['word']):
            s *= KATA_PENALTY
        return s

    cands = sorted(by_word.values(), key=lambda e: (-score(e), e['word']))
    for e in cands:
        e['scripts'] = '+'.join(sorted(e['scripts']))
    print('去重后例句 %d 张（跳过多卡重复句 %d 句）' % (len(seen_notes), dup_sentences))
    print('残差候选 %d 个（含汉字 %d / 纯假名 %d）；另丢弃 %d 个已知词活用残片、%d 个语法片段'
          % (len(cands),
             sum(1 for e in cands if P.KANJI.search(e['word'])),
             sum(1 for e in cands if not P.KANJI.search(e['word'])), n_infl, n_gram))
    print('其中来自例句卡 Word 字段（人工重点词）的补充候选 %d 个%s'
          % (n_word, '' if a.word_field else '（已用 --no-word-field 关掉）'))
    if skip_word:
        print('  Word 字段里没进候选的 %d 个（例句里找不到该词形，收进来也定位不到原句）：%s'
              % (len(skip_word), '、'.join(skip_word)))
    if skip_shape:
        print('  Word 字段里按词形规则丢掉的 %d 个（停用词/不含假名汉字）：%s'
              % (len(skip_shape), '、'.join(skip_shape)))
    if a.limit:
        cands = cands[:a.limit]
        print('按 --limit 截断为 %d 个' % len(cands))

    json.dump({'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
               'query': q,
               'candidates': cands},
              open(CAND, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('# 素材生词候选（%d 个）\n\n' % len(cands))
        f.write('> 收录判据：词形不存在于 `2-考级词汇`(10,609) 或 `1-高频日语单词 6000`(6,000) 中。\n')
        f.write('> 判定口径：去 `〜`、NFKC 统一全半角、去空白后逐字比对；活用形与假名/片假名变体算同一个词。\n\n')
        f.write('| # | 候选 | 释义形态 | 出现 | 长度 | 标签 | 例句 |\n|---|---|---|---|---|---|---|\n')
        for i, e in enumerate(cands, 1):
            ex = e['occurrences'][0]['sentence'] if e['occurrences'] else ''
            f.write('| %d | `%s` | %s | %d | %d | %s | %s |\n'
                    % (i, e['word'], e['scripts'], e['count'], e['len'],
                       '/'.join(e['tags']) or '-', ex[:44]))
    print()
    print('候选样例（前 40）：')
    for e in cands[:40]:
        print('  %-12s 出现%-3d %-6s %s' % (e['word'], e['count'], e['scripts'],
                                            (e['occurrences'][0]['sentence'][:40]
                                             if e['occurrences'] else '')))
    print()
    print('已写出：%s' % CAND)
    print('报告：  %s' % REPORT)
    print('下一步：python mine.py split --batches N')


# ============================================================================
# 阶段 4.2：split —— 切批 + 打印子代理提示词
# ============================================================================
SUBAGENT_PROMPT = '''你是精通日语的语言学教授。任务：为一批「候选残差」判定是不是**值得收进生词卡的日语单词**，并给出词条信息。

【第一步】读规范：{doc}

【输入】{gen}\\input_{n:02d}.json
JSON 数组，每项 {{word, count, scripts, len, occurrences:[{{noteId, sentence, sentence_html, source}}]}}。
`word` 是**脚本用已知词表做最长匹配后剩下的残差片段**，不是干净的词：可能是碎片
（`を訪ね`、`は香`）、专有名词（`山崎`、`藍華`）、也可能真的是生词（`漕ぐ`、`突如`）。
`sentence_html` 是已入库的带振假名例句，`sentence` 是纯文本原文。

【输出】把结果写入 {gen}\\output_{n:02d}.json
JSON 数组，每项 {{word, reading, pos, meaning, translation, a_note, include, reason}}
（字段含义与取值见规范）。每一条输入都必须有一条输出，word 与输入逐字一致
（允许 `〜` 与全半角差异），数量与顺序一致。

【禁止】不要调用 AnkiConnect，不要写入 Anki，不要修改输入文件，不要改动 {gen} 目录之外的任何文件。
不要跑 check_mine.py 自检、不要反复重写整批 —— 入库前 write 会统一校验一次，把结果交给它。'''

# 本地模型用的提示词（正本）。**改提示词只改这里**：docs/mine-agent-instruction.md 是它的
# 说明版。与阶段二同理：自包含、一次一批、只输出 JSON、不要自检（校验由 cmd_gen 机械做一次）。
MINE_INSTRUCTION = '''你是精通日语的语言学教授。输入是一批从动画字幕例句里挖出来的「候选残差」，请逐个判定它是不是**值得收进生词卡的日语单词**，并给出词条信息。

【输入】JSON 数组，每项 {word, count, scripts, len, occurrences:[{noteId, sentence, sentence_html, source}]}
  word：脚本用已知词表（core6000 + 考级词汇）做最长匹配后剩下的片段，**不是干净的词**：
    - 碎片：`を訪ね`、`は香`、`の激`、`に出`（已知词没覆盖干净的切片）
    - 专有名词：`山崎`、`藍華`、`河合`（人名/地名/作品设定名，**不收**）
    - 也可能真的是生词：`漕ぐ`、`突如`、`沈む`
  sentence / sentence_html：该词出现的例句（后者带振假名），供你判断语境
  count：出现次数

【输出】只输出一个 JSON 对象，前后不要任何解释或 markdown 围栏：
{"entries":[{"word":"…","reading":"…","pos":"…","meaning":"…","translation":"…","a_note":"…","include":true,"reason":""}]}
每一条输入都要有一条对应输出，顺序与输入一致。

字段：
- word        ：**保留候选本身的写法**，只能**往后接**补全（候选必须是 word 的子串：
                `訪ね`→`訪ねる`、`沈ん`→`沈む`、`満ち溢`→`満ち溢れる`、`ひきこ`→`ひきこもる`）。
                **若候选是活用形/口语缩略形、词典形不含候选**（`食わして`→`食わす`、`〜臭ぇ`→`〜臭い`），
                **word 就原样照抄候选**，把词典形与活用链写进 a_note 的「动词变形解析」。
                判断不了也原样回填。（脚本会机械核对"候选是否为 word 的子串"，对不上这张就打回重做）
- reading     ：该词的平假名读音，**纯假名**，不带任何标签；不确定就留空
- pos         ：中文词性，只能取：名词／イ形容词／ナ形容词／自动词／他动词／副词／接续词／外来语／惯用句
- meaning     ：简洁的中文释义（多个义项用「；」分隔）
- translation ：occurrences[0].sentence 的自然中文翻译（一句）
- a_note      ：该词的讲解（只有 include=true 才需要填），见下
- include     ：true=确实是值得学的日语生词；false=碎片/专有名词/语气词/已知词的活用形/无学习价值
- reason      ：include=false 时必填，一句话说明原因；include=true 时留空字符串

【a_note 规范】四段，每段一个 <p>（第四段只在句中确实出现活用动词时才写）：
<p><b>中文翻译：</b>例句的中文翻译。</p>
<p><b>核心词汇：</b><br><ruby>漢字<rt>かな</rt></ruby>：词性。中文释义。<br>…</p>（第一条就是本词）
<p><b>语法要点：</b><br>句型：含义 + 接续 + 功能<br>…</p>
<p><b>动词变形解析：</b><br>原形 → 变形（名称） → 变形（名称）＋辅助词<br>…</p>

【铁律】
1. a_note 只允许 <p> <br> <b> <ruby> <rt>；禁止 div/span/style/class、禁止 LaTeX、禁止反斜杠、禁止 $、禁止半角双引号（用「」）、禁止 markdown
2. a_note 里的日语汉字必须标 ruby（送假名在 <rt> 外：<ruby>食<rt>た</rt></ruby>べる）；**中文汉字绝不标**
3. word / reading / pos / meaning 四个字段里**不要**放任何 HTML 标签或 ruby
4. 拿不准是不是真词时倾向 include=false（宁可漏收，不要把碎片或人名做成卡）

【输出格式铁律】（脚本逐条机械核对，违反的那条会被打回重做，所以务必照办）
5. 只输出一个 JSON 对象：{"entries": [ … ]}；条目**条数、顺序与输入候选一一对应**，不许漏、不许合并、不许自创
6. `word`/`reading`/`pos`/`meaning`/`translation`/`a_note`/`reason` 的值**必须是 JSON 字符串**
   （不要写数字、true/false、数组、null）；`include` 的值**必须是 JSON 的 true 或 false**（不要写成字符串 "true"）
7. 每条候选都要有对应条目；判不了就 include=false + reason 说明，**不要省略这一条**
8. 字符串字段里不要用半角双引号（JSON 转义容易出错），需要引号时用「」'''

MINE_MAX_TOKENS = 8192        # 单次请求的输出上限


def cmd_split(a):
    data = json.load(open(CAND, encoding='utf-8'))
    cands = data['candidates']
    if not cands:
        raise SystemExit('候选为空，先跑：python mine.py scan')
    os.makedirs(GEN, exist_ok=True)
    size = (len(cands) + a.batches - 1) // a.batches
    manifest = []
    for b in range(a.batches):
        chunk = cands[b * size:(b + 1) * size]
        if not chunk:
            continue
        name = 'input_%02d.json' % (b + 1)
        json.dump(chunk, open(os.path.join(GEN, name), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        manifest.append({'batch': b + 1, 'input': name,
                         'output': 'output_%02d.json' % (b + 1), 'count': len(chunk)})
    json.dump(manifest, open(os.path.join(GEN, 'manifest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('已切分为 %d 批，共 %d 个候选（约 %d 个/批）'
          % (len(manifest), len(cands), size))
    if not a.print_prompts:
        print('下一步：python mine.py gen      # 由本地模型逐批判定（不花云端 token）')
        return
    print()
    print('=' * 76)
    print('本地模型不可用时的备用路径：把下面的提示词发给子代理（会花云端 token）：')
    print('=' * 76)
    for m in manifest:
        print()
        print('---------- 批次 %02d（%d 个）----------' % (m['batch'], m['count']))
        print(SUBAGENT_PROMPT.format(doc=WSP.DOC_MINE_AGENT, gen=GEN, n=m['batch']))


# ============================================================================
# 阶段 4.2b：gen —— 本地模型判定（2026-10-11 起，不派子代理）
# ============================================================================
def mine_payload(group):
    """这组候选发给模型的 JSON 正文（分组 token 估算与真实请求**共用同一份**）。"""
    return json.dumps(
        [{'word': c['word'], 'count': c.get('count', 1),
          'scripts': c.get('scripts', ''), 'len': c.get('len', len(c['word'])),
          'occurrences': [{'noteId': o.get('noteId'), 'sentence': o.get('sentence', ''),
                           'sentence_html': o.get('sentence_html', ''),
                           'source': o.get('source', '')}
                          for o in (c.get('occurrences') or [])[:2]]}
         for c in group], ensure_ascii=False, indent=1)


def mine_user(group, feedback=None):
    """一次请求的完整 user 正文（含规范，用于 token 估算）。"""
    return (MINE_INSTRUCTION + '\n' + mine_payload(group)
            + (('\n\n上面这些候选上一次的输出不合格，问题如下，这次只重做这几条：\n'
                + feedback) if feedback else ''))


def mine_request(cfg, LLM, group, feedback=None):
    """一次本地模型请求：一组候选 → {归一化 word: 条目}。"""
    user = mine_user(group, feedback)
    msgs = [{'role': 'system', 'content': MINE_INSTRUCTION},
            {'role': 'user', 'content': user}]
    obj, res, problems = LLM.call_json(cfg, msgs, require='entries', json_mode=True,
                                       enable_thinking=False, quiet=True,
                                       max_tokens=MINE_MAX_TOKENS)
    got = {}
    if isinstance(obj, dict):
        for item in (obj.get('entries') or []):
            if not isinstance(item, dict):
                continue
            w = P.norm(OUT.as_text(item.get('word')))
            if w:
                got[w] = item
    if problems:
        print('    ⚠️ 回复形状不合格：%s' % '；'.join(problems)[:160], file=sys.stderr)
    return got, res


MINE_RAW_DIR = os.path.join(GEN, 'raw')


def dump_raw(batch, rounds, group, res):
    """「这一组没判出来」时，把模型的原始回复落盘留证。

    以前不留原始回复：2026-10-12 产出被写坏时无法回头看成模型到底回了什么，
    只能靠猜。只在有问题的组写文件，正常批次不产垃圾。
    """
    body = ('# 候选：%s\n# 轮次：%d\n\n' % ('、'.join(c['word'] for c in group), rounds)
            + OUT.raw_text(res))
    p = OUT.dump_raw(MINE_RAW_DIR, 'batch_%s_r%d' % (
        ('%02d' % batch) if isinstance(batch, int) else str(batch), rounds), body,
        header='阶段四 gen：这一组没判出来')
    if p:
        print('    模型原始回复已存：%s' % p)


def origin_possible(residual, cand):
    """`write` 阶段「同源」判定（`same_origin`）的**必要条件**，用于判定阶段提前拦截。

    `build_payload.same_origin` 接受的情形只有三类，**每一类都蕴含"两个词形有一个是
    另一个的子串"**（补成词典形时残差是输出词的前缀）：

        a == b ｜ a in b ｜ b in a ｜（活用命中 且 a in b）

    所以「互不为子串」是**必然会被 write 拒绝**的充分可判条件 —— 在这里拦下来，
    本地模型下一轮就能拿到"必须保留候选作为子串"的具体提示重做，
    而不是等 write 时才整批报 `mismatch`、再退回 failed.json 走强模型。

    典型事故：候选 `食わして`（口语缩略形），模型"好心"补成词典形 `食わす`/`食わせる`
    —— 两者互不为子串 → write 直接判不同源。正确做法是 `word` 原样写 `食わして`，
    把活用链写进 `a_note`。
    """
    a = P.norm(residual).strip('〜～')
    b = P.norm(cand).strip('〜～')
    if not a or not b:
        return False
    return a == b or a in b or b in a


def judge_mine(group, got):
    """把模型结果按候选配回来，跑一次 check_mine；返回 (合格的, {word: 问题})。

    模型常把残差**补成词典形**（`訪ね`→`訪ねる`、`ひきこ`→`ひきこもる`），
    所以精确查不到时按"候选词是返回词的前缀"再找一次 —— 否则会被误判成
    「模型没有返回这条候选」，白丢一条真生词。

    **前缀回退必须排除"本组另一条候选的原词"**（2026-10-12 修）：同组同时出现
    `錆` 与 `錆臭ぇ` 时，返回词 `錆臭ぇ` 是后者的答案，若拿它回退给 `錆`，
    两条候选会拿到同一条目 → 产出里出现两条同词记录。
    """
    ok, bad = {}, {}
    exact = {P.norm(c['word']) for c in group}
    for c in group:
        key = P.norm(c['word'])
        item = got.get(key)
        if item is None:
            longer = sorted((k for k in got if k.startswith(key) and len(k) > len(key)
                             and k not in exact), key=len)
            if longer:
                item = got[longer[-1]]
        if item is None:
            bad[key] = '模型没有返回这条候选'
            continue
        try:
            # 字段**原样**交给校验器（不在这里悄悄纠正类型）：模型把 translation 写成数字时，
            # 要的是「translation 字段类型不是字符串」这条**可执行的重问提示**，
            # 而不是被归一成空串后报一句含糊的"为空"。
            # 只有 word 缺失/为空才回填候选本身（那是模型没给词形，不是给了个坏词形）。
            raw_w = item.get('word')
            entry = {'word': raw_w if raw_w not in (None, '') else c['word'],
                     'reading': item.get('reading'), 'pos': item.get('pos'),
                     'meaning': item.get('meaning'), 'translation': item.get('translation'),
                     'a_note': item.get('a_note'), 'include': CM.as_bool(item.get('include')),
                     'reason': item.get('reason')}
            hard, _soft = CM.check(entry)
        except Exception as e:                      # 判定器/校验器出意外也不许拖垮整批
            bad[key] = '判定异常：%s: %s' % (type(e).__name__, e)
            continue
        if hard:
            bad[key] = '；'.join(hard)
            continue
        if not origin_possible(c['word'], entry['word']):
            # 提前拦下"必被 write 拒绝"的词形（模型换了词/换了活用形），并给出可执行提示
            bad[key] = ('word「%s」与候选「%s」不同源：**必须保留候选本身作为子串**'
                        '（要补词典形就往后接：候选是 word 的前缀，例如 満ち溢 → 満ち溢れる）；'
                        '候选若已是活用形/口语形就原样写进 word，把词典形与活用说明放进 a_note'
                        % (entry['word'], c['word']))
            continue
        ok[key] = entry
    return ok, bad


MINE_FAILED = os.path.join(GEN, 'failed.json')     # 本地模型没判出来的候选（交给强模型收尾）
MINE_PLACEHOLDER_REASON = '模型未能给出合格判定，留待人工'   # gen 判不出来时写进产出占位的固定文案


def is_placeholder(rec):
    """这条产出记录是不是 gen 判定失败留下的**占位条目**。

    占位条目是「这条还没被判定过」的唯一可靠标记：`include=false` + 固定 reason。
    `patch_outputs` 的前缀回退只认它（见那里的注释）。
    """
    return (bool(rec) and not rec.get('include')
            and MINE_PLACEHOLDER_REASON in (rec.get('reason') or ''))


def save_failed(entries):
    doc = {'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'note': ('这些候选本地模型重试后仍未通过 check_mine；'
                    '用 mine.py merge-fix --file <产出> 并回，或人工处理'),
           'candidates': entries}
    json.dump(doc, open(MINE_FAILED, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return doc


def patch_outputs(done):
    """把 {归一化 word: 条目} 并回对应批次的 output_NN.json。返回改动条数。

    匹配只有两条路（2026-10-12 修事故：前缀回退曾把同批另一条真实判定整条覆盖）：

    1. **精确命中**（word 归一化后相等）—— 任何记录都可替换：人工复核过的修正就该覆盖模型判定。
    2. **前缀回退**（判定方把残差补成了词典形：`ひきこ`→`ひきこもる`）—— **只允许落在占位条目上**，
       且回退到的词不能是本批另一条记录的原词。

    事故复盘：fix 只提交了 `錆臭ぇ`，而 `錆` 恰好是它的前缀，于是真实收录的「錆」
    被整条替换成排除条目，产出出现两条 `錆臭ぇ`、`write` 被堵死。
    本批另一条记录的原词（`錆`）本来就不是"残差"，没有理由被前缀回退改写。

    另加一条完整性网：一个 fix 条目只改一条记录，命中第二条就跳过并告警
    （同一批出现两条同词记录本身就是坏数据，不该继续往上盖）；fix 条目一条都没落上也会告警。
    """
    if not done:
        return 0
    manifest = json.load(open(os.path.join(GEN, 'manifest.json'), encoding='utf-8'))
    n = 0
    used = {}                                    # fix 条目 key → 改到了哪条记录
    for m in manifest:
        p = os.path.join(GEN, m['output'])
        if not os.path.exists(p):
            continue
        out = json.load(open(p, encoding='utf-8'))
        exact = {P.norm(r.get('word') or '') for r in out}   # 本批已有记录的原词
        changed = False
        for i, rec in enumerate(out):
            key = P.norm(rec.get('word') or '')
            v, how = done.get(key), '精确'
            if v is None and is_placeholder(rec):
                longer = sorted((k for k in done if k.startswith(key) and len(k) > len(key)
                                 and k not in exact), key=len)
                if longer:
                    v, how = done[longer[-1]], '前缀'
            if not v:
                continue
            vk = P.norm(v.get('word') or '')
            where = '%s 第 %d 条' % (m['output'], i + 1)
            if vk in used:
                print('  ⚠ %s 已改过 %s，又命中 %s → 跳过（一条 fix 只改一条记录）'
                      % (vk, used[vk], where))
                continue
            out[i] = v
            used[vk] = where
            changed = True
            n += 1
            print('  并回 %s ← %s（%s匹配，原词 %r）' % (vk, where, how, rec.get('word')))
        if changed:
            json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    missing = sorted(k for k in done if k not in used)
    if missing:
        print('  ⚠ %d 条 fix 没落到任何记录上（word 与占位条目对不上，产出未改）：%s'
              % (len(missing), '、'.join(missing)))
    return n


def fix_failed(a, cfg, LLM):
    """只重跑 failed.json 里的候选（本地模型逐条再试），修好的并回 output_NN.json。"""
    if not os.path.exists(MINE_FAILED):
        raise SystemExit('没有 %s（本地模型没有遗留失败项）' % MINE_FAILED)
    doc = json.load(open(MINE_FAILED, encoding='utf-8'))
    cands = doc.get('candidates') or []
    if not cands:
        print('failed.json 是空的，没有要重跑的。')
        return
    print('重跑 %d 条（本地模型，逐条请求）' % len(cands))
    done, bad = {}, {}
    pending, rounds = list(cands), 0
    req = tp = tc = 0
    while pending:
        fb = []
        for group in P.fit_groups(pending, a.per_request if rounds == 0 else 1,
                                  mine_user, cfg, LLM):
            res = None
            try:
                got, res = mine_request(cfg, LLM, group,
                                        feedback='\n'.join(fb) if fb else None)
                req += 1
                tp += res.prompt_tokens
                tc += res.completion_tokens
                ok, problems = judge_mine(group, got)
            except Exception as e:              # 同 cmd_gen：一组出意外不拖垮整轮
                req += 1
                print('  ⚠ 一组重问出意外：%s: %s → 这 %d 条按未判定处理'
                      % (type(e).__name__, e, len(group)))
                ok, problems = {}, {P.norm(c['word']): '%s: %s' % (type(e).__name__, e)
                                    for c in group}
            done.update(ok)
            bad.update(problems)
            for k, why in problems.items():
                fb.append('- %s：%s' % (k, why[:200]))
            if problems:
                dump_raw('fix', rounds, group, res)
        if not bad or rounds >= a.retries:
            break
        rounds += 1
        pending = [c for c in cands if P.norm(c['word']) in bad]
        bad = {}
        print('  重问第 %d 轮（逐条请求）：%d 条' % (rounds, len(pending)))
    patch_outputs(done)
    remain = [dict(c, problems=bad.get(P.norm(c['word']), '')) for c in cands
              if P.norm(c['word']) in bad]
    save_failed(remain)
    print('本轮修好 %d 条，仍剩 %d 条（已更新 failed.json）' % (len(done), len(remain)))
    print('  %d 次请求，prompt %d + completion %d tokens' % (req, tp, tc))
    print('剩下的交给强模型：生成 fix_output.json 后跑 merge-fix'
          if remain else '下一步：python mine.py write')


def cmd_merge_fix(a):
    """把强模型（deepseek）补做的 fix 产出并回 output_NN.json（同一份 check_mine 校验）。"""
    path = a.file if os.path.isabs(a.file) else os.path.join(GEN, a.file)
    if not os.path.exists(path):
        raise SystemExit('找不到 %s' % path)
    merge = json.load(open(path, encoding='utf-8'))
    if isinstance(merge, dict):
        merge = merge.get('entries') or merge.get('outputs') or []
    ok, bad = {}, {}
    for item in merge:
        if not isinstance(item, dict):
            continue
        w = P.norm(item.get('word') or '')
        if not w:
            continue
        entry = {'word': item.get('word') or '', 'reading': item.get('reading') or '',
                 'pos': item.get('pos') or '', 'meaning': item.get('meaning') or '',
                 'translation': item.get('translation') or '',
                 'a_note': item.get('a_note') or '', 'include': CM.as_bool(item.get('include')),
                 'reason': item.get('reason') or ''}
        try:
            hard, _soft = CM.check(entry)
        except Exception as e:                  # 校验器出意外也要报成不合格，不中断
            hard = ['校验异常：%s: %s' % (type(e).__name__, e)]
        if hard:
            bad[w] = '；'.join(hard)
        else:
            ok[w] = entry
    n = patch_outputs(ok)
    print('fix 文件 %s：并入 %d 条（不合格 %d 条）' % (path, n, len(bad)))
    for w, why in sorted(bad.items())[:10]:
        print('  ✗ %s %s' % (w, why[:160]))
    if os.path.exists(MINE_FAILED):
        doc = json.load(open(MINE_FAILED, encoding='utf-8'))

        def _fixed(w):
            k = P.norm(w)
            return k in ok or any(x.startswith(k) and len(x) > len(k) for x in ok)

        save_failed([c for c in (doc.get('candidates') or []) if not _fixed(c['word'])])
        print('failed.json 已更新（剩余 %d 条）'
              % len(json.load(open(MINE_FAILED, encoding='utf-8'))['candidates']))
    print('下一步：python mine.py write')


def output_matches_input(m):
    """这一批的 output_NN.json 是不是**当前 input** 的产出（断点续跑的唯一判据）。

    **只看文件名是不够的。** 同一集跑完一遍之后又导入新卡时，`split` 会原地重写
    `input_NN.json`，而上一趟的 `output_NN.json` 还在、批号也一样 —— 那是**另一批候选**
    的产出，照它跳过就等于整批不判定；后面 `episode.mine_leftovers()` 还会拿旧产出跟
    新输入按下标比形状，把差异写成"模型把候选改成了别的形状""条数不一致" →
    误报成 needs_llm（语义问题）。2026-10-11 第二次冒烟实测踩到。

    判据只能用**同源**不能相等：判定的职责恰恰是把残差补成词典形
    （`満ち溢`→`満ち溢れる`），字面本来就会变；口径与 `episode.mine_leftovers` 一致。
    """
    ip = os.path.join(GEN, m['input'])
    op = os.path.join(GEN, m['output'])
    if not os.path.exists(op):
        return False
    try:
        src = json.load(open(ip, encoding='utf-8'))
        got = json.load(open(op, encoding='utf-8'))
    except (ValueError, TypeError):
        return False
    if len(src) != len(got):
        return False
    for a, b in zip(src, got):
        w1, w2 = P.norm(a.get('word') or ''), P.norm(b.get('word') or '')
        if not w2 or not (w1 == w2 or w1 in w2 or w2 in w1):
            return False
    return True


def cmd_gen(a):
    """直连本地模型判定候选。默认跳过已存在的批次（断点续跑，判据见 `output_matches_input`）。"""
    manifest_path = os.path.join(GEN, 'manifest.json')
    if not os.path.exists(manifest_path):
        raise SystemExit('没有 manifest.json，先跑：python mine.py split --batches N')
    try:
        import local_llm as LLM
    except ImportError as e:
        raise SystemExit('找不到本地模型客户端 code/common/local_llm.py：%s' % e)
    manifest = json.load(open(manifest_path, encoding='utf-8'))
    cfg = LLM.load_config()
    if a.fix_failed:
        return fix_failed(a, cfg, LLM)
    print('本地模型：%s @ %s（单请求输出上限 %d tokens，每请求 %d 条候选）'
          % (cfg['model'], cfg['base_url'], MINE_MAX_TOKENS, a.per_request))
    todo = []
    for m in manifest:
        if a.force or not os.path.exists(os.path.join(GEN, m['output'])):
            todo.append(m)
        elif output_matches_input(m):
            print('  批%02d %s 已存在且与输入同源 → 跳过（--force 重做）'
                  % (m['batch'], m['output']))
        else:
            print('  ⚠ 批%02d %s 已存在但与本批输入对不上（同一批号的旧产出）→ 重做'
                  % (m['batch'], m['output']))
            todo.append(m)
    if not todo:
        print('没有要判定的批次。下一步：python mine.py write')
        return

    t0 = time.time()
    tot_p = tot_c = tot_req = 0
    failed = []
    for m in todo:
        cands = json.load(open(os.path.join(GEN, m['input']), encoding='utf-8'))
        done, bad = {}, {}
        pending = list(cands)
        rounds = 0
        while pending:
            fb = []
            size = a.per_request if rounds == 0 else 1     # 重问逐条发
            # fit_groups：张数按 size，但**每组的 prompt 估算必须在本地模型预算内** ——
            # 长对白 + 生成规范很容易在十几条候选时撞 32k 窗口，那会整批白跑几分钟本地算力。
            for group in P.fit_groups(pending, size, mine_user, cfg, LLM):
                res = None
                try:
                    got, res = mine_request(cfg, LLM, group,
                                            feedback='\n'.join(fb) if fb else None)
                    tot_req += 1
                    tot_p += res.prompt_tokens
                    tot_c += res.completion_tokens
                    ok, problems = judge_mine(group, got)
                except Exception as e:
                    # 一组出意外（模型回复形状离谱、校验器 bug、连接抖动）不许拖垮整批：
                    # 这一组按「没判出来」处理，下一轮会逐条重问，最后落到 failed.json。
                    tot_req += 1
                    print('  ⚠ 批%02d 一组判定出意外：%s: %s → 这 %d 条按未判定处理'
                          % (m['batch'], type(e).__name__, e, len(group)))
                    ok, problems = {}, {P.norm(c['word']): '%s: %s' % (type(e).__name__, e)
                                        for c in group}
                done.update(ok)
                bad.update(problems)
                for k, why in problems.items():
                    fb.append('- %s：%s' % (k, why[:200]))
                if problems:
                    # 没判出来时把模型原始回复留一份 —— 以前不留，事故只能靠猜。
                    dump_raw(m['batch'], rounds, group, res)
            if not bad:
                break
            if rounds >= a.retries:
                print('  批%02d 仍有 %d 条没判出来（按"不收"处理，交强模型收尾）'
                      % (m['batch'], len(bad)))
                break
            rounds += 1
            pending = [c for c in cands if P.norm(c['word']) in bad]
            bad = {}
            print('  批%02d 重问第 %d 轮（逐条请求）：%d 条' % (m['batch'], rounds, len(pending)))

        out = []
        for c in cands:
            key = P.norm(c['word'])
            entry = done.get(key) or {'word': c['word'], 'reading': '', 'pos': '',
                                      'meaning': '', 'translation': '', 'a_note': '',
                                      'include': False,
                                      'reason': MINE_PLACEHOLDER_REASON}
            out.append(entry)
        json.dump(out, open(os.path.join(GEN, m['output']), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        n_inc = sum(1 for e in out if e['include'])
        print('  批%02d 写出 %s：收录 %d / 排除 %d'
              % (m['batch'], m['output'], n_inc, len(out) - n_inc))
        for c in cands:
            key = P.norm(c['word'])
            if key in bad:
                item = dict(c)
                item['batch'] = m['batch']
                item['problems'] = bad[key]
                failed.append(item)
    print('判定结束：%d 次请求，prompt %d + completion %d tokens，耗时 %.0fs'
          % (tot_req, tot_p, tot_c, time.time() - t0))
    if failed:
        save_failed(failed)
        print()
        print('有 %d 条本地模型没判出来 → 已写入 %s' % (len(failed), MINE_FAILED))
        print('下一步（交给 deepseek 收尾）：')
        print('  1) 让强模型按 failed.json 生成 data/vocab/gen_mine/fix_output.json')
        print('     （同样的 JSON 数组格式，只放这些 word）')
        print('  2) python mine.py merge-fix --file fix_output.json')
    else:
        if os.path.exists(MINE_FAILED):
            os.remove(MINE_FAILED)     # 全部通过就清掉旧的失败清单
        print('全部一次判定通过。')
    print('下一步：python mine.py write       # 演练（看 dryrun_notes.json 的 word 列）')


# ============================================================================
# 阶段 4.3：verify —— 硬校验子代理产出（write 会自动跑，也可单独跑）
# ============================================================================
def check_entry(c):
    """硬校验单条子代理产出。返回 (hard, soft)，hard 非空即不合格。

    **规则实现只有一份**：`code/common/check_mine.py`（子代理自检用的就是它）。
    原来这里是它的第二份拷贝（再包一层 check_cards），两边口径已经开始漂移，
    等于同一条规则查三遍。
    """
    return CM.check(c)


def build_payload():
    """校验子代理产出 → 待入库载荷，并写出 verified.json。有问题时 raise SystemExit(1)。

    **verify 与 write 共用这一份实现。** 原来 write 会把同样的逐条规则、同样的
    「是否已在已有牌组里」判定再跑一遍（还要重建一次 1.7 万张的索引），
    同一件事查两遍；现在只在这里查一次，write 直接复用 verified.json。
    """
    manifest = json.load(open(os.path.join(GEN, 'manifest.json'), encoding='utf-8'))
    canonical, variant2c, _heads = build_index()

    merged, missing = [], []
    expected = []
    for m in manifest:
        src = json.load(open(os.path.join(GEN, m['input']), encoding='utf-8'))
        expected.extend(src)
        p = os.path.join(GEN, m['output'])
        if not os.path.exists(p):
            missing.append(m['output'])
            continue
        merged.extend(json.load(open(p, encoding='utf-8')))
    if missing:
        raise SystemExit('尚未生成：%s' % ', '.join(missing))

    # ★ 不能拿输出里的 word 去反查输入：子代理的职责就是**把残差补成词典形**
    #   （`満ち溢`→`満ち溢れる`、`食べ終`→`食べ終わる`），补全后字面必然不同。
    #   规范要求输出与输入**同序同量**，所以按下标配对；
    #   并校验"输出词与输入残差同源"（残差是输出词的子串），防止整条跑偏。
    def same_origin(residual, cand):
        a = P.norm(residual).strip('〜～')
        b = P.norm(cand).strip('〜～')
        if a == b or a in b or b in a:
            return True
        return hit_inflection(b, canonical, variant2c) is not None and a in b

    exp = {P.norm(e['word']): e for e in expected}
    bad, known, shallow, notfound, includes = [], [], [], [], []
    noruby = []
    mismatch = []
    seen = set()
    payload = []
    for idx, c in enumerate(merged):
        key = P.norm(c.get('word') or '')
        if key in seen:
            bad.append((c.get('word'), ['输出里重复出现']))
            continue
        seen.add(key)
        # 按下标取对应的输入项，并校验同源
        src = expected[idx] if idx < len(expected) else None
        if src is not None and not same_origin(src['word'], c.get('word') or ''):
            mismatch.append((idx, src['word'], c.get('word')))
            continue
        hard, soft = check_entry(c)
        if not c.get('include'):
            continue
        if hard:
            bad.append((c.get('word'), hard))
            continue
        k = (c['word'] or '').strip('〜～')
        can, var, infl = known_lookups(k, variant2c, canonical)
        if can or var or infl:
            known.append((c['word'], can or var or (infl + '（活用形）')))
            continue
        if src is None:
            notfound.append(c['word'])
            continue
        sentence = ''
        for o in src['occurrences']:
            if P.norm(c['word']) in P.norm(o['sentence']) or c['word'] in o['sentence']:
                sentence = o
                break
        if not sentence:
            for o in src['occurrences']:
                for v in P.conjugation_variants(c['word']):
                    if v in P.norm(o['sentence']):
                        sentence = o
                        break
                if sentence:
                    break
        if not sentence:
            # 促音便等不规则活用（食べ終わる → 食べ終わった）不靠变体表枚举，
            # 直接退一步用**词干**定位：词干能与例句对上就算找到了出处。
            stem = c['word'][:-1]
            for o in src['occurrences']:
                if len(stem) >= 2 and stem in P.norm(o['sentence']):
                    sentence = o
                    break
        if not sentence:
            notfound.append(c['word'])
            continue
        if not (c.get('translation') or '').strip():
            shallow.append(c['word'])
        # 例句必须带上振假名：生词卡的 Sentence HTML 直接复用例句卡的 Sentence HTML。
        # 例句含汉字却没有 <ruby> = 复用错了字段（check_cards.py 管不到这个字段，
        # 所以在这里单独把关）。目标卡没有 ruby 时由 cmd_write 回头向来源卡重取。
        if P.KANJI.search(P.strip_html(sentence['sentence'])) and '<ruby>' not in sentence['sentence_html']:
            noruby.append(c['word'])
        includes.append((c, sentence))
        payload.append({'word': c['word'], 'reading': c['reading'], 'pos': c['pos'],
                        'meaning': c['meaning'], 'translation': c['translation'],
                        'a_note': c['a_note'], 'noteId': sentence['noteId'],
                        'sentence': sentence['sentence'],
                        'sentence_html': sentence['sentence_html'],
                        'source': sentence.get('source', '')})
    n_inc = sum(1 for c in merged if c.get('include'))
    n_exc = len(merged) - n_inc
    print('汇总 %d 条（应覆盖 %d 条）' % (len(merged), len(expected)))
    print('  子代理判定收录 %d / 排除 %d' % (n_inc, n_exc))
    print('  逐条规则不合格 %d' % len(bad))
    for w, hard in bad[:20]:
        print('    ✗ %s  %s' % (w, '; '.join(hard)))
    print('  与输入不同源（补全得离题） %d' % len(mismatch))
    for i, a, b in mismatch[:20]:
        print('    ✗ #%d 输入 %r → 输出 %r' % (i, a, b))
    print('  已在已有牌组里（应剔除） %d' % len(known))
    for w, hit in known[:20]:
        print('    ⊘ %s  ← 已存在于 %s' % (w, hit))
    print('  例句中找不到该词形（无法定位原句） %d  %s' % (len(notfound), notfound[:10]))
    if noruby:
        print('  例句含汉字但 Sentence HTML 没有振假名 %d：%s'
              % (len(noruby), noruby[:10]))
        print('    （write 会回头向来源例句卡重取 Sentence HTML；若仍拿不到会列为提醒）')

    if len(merged) != len(expected):
        print('  ✗ 输出条数 %d ≠ 输入条数 %d' % (len(merged), len(expected)))

    if bad or known or notfound or mismatch or len(merged) != len(expected):
        print()
        print('存在问题，未通过。修掉上面带 ✗/⊘ 的条目后重跑。')
        raise SystemExit(1)

    json.dump(payload, open(os.path.join(GEN, 'verified.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print()
    print('全部通过。待入库 %d 条（已写入 verified.json）。' % len(payload))
    return payload


def verified_fresh():
    """verified.json 是否比全部产出文件都新 —— 是的话 write 直接复用，不再校验一遍。"""
    p = os.path.join(GEN, 'verified.json')
    if not os.path.exists(p):
        return False
    t = os.path.getmtime(p)
    try:
        manifest = json.load(open(os.path.join(GEN, 'manifest.json'), encoding='utf-8'))
    except Exception:
        return False
    files = [os.path.join(GEN, 'manifest.json'), CAND]
    for m in manifest:
        files += [os.path.join(GEN, m['input']), os.path.join(GEN, m['output'])]
    return all(os.path.exists(f) and os.path.getmtime(f) <= t for f in files)


def cmd_verify(_a):
    """校验并写出 verified.json。**不是必经步骤** —— write 在需要时会自己跑一遍。"""
    build_payload()
    print('下一步：python mine.py write            # 演练')
    print('        python mine.py write --commit   # 真写（会复用这次校验结果）')


# ============================================================================
# 阶段 4.4：write —— 入库（默认演练）
# ============================================================================
def slug(s):
    """把出处文件名变成安全、简短的标签片段。

    出处字段是整串文件名，新闻/纪录片那类来源会长到几十字
    （`地震発生3日目は猛暑日に ... TBS NEWS DIG - 日文`），
    直接当标签会产生一个几乎没法看的超长标签，所以按分隔符取头一段并限长。
    """
    s = re.sub(r'\.(srt|ass|vtt|txt)$', '', (s or '').strip(), flags=re.I)
    s = re.split(r'[（(\[【「]| - | _哔哩哔哩_|｜|\|', s)[0]
    s = re.sub(r'[^\w\u3040-\u30ff\u4e00-\u9fff-]+', '_', s).strip('_')
    return s[:24].strip('_')


def existing_words(model=None):
    """库里已有的 Word（用于入闸前的最后一道查重）。"""
    model = model or P.CFG['mine_model']
    ids = AK.find_notes('note:"%s"' % model)
    out = {}
    for n in AK.notes_info(ids):
        w = P.norm(n['fields'].get('Word', {}).get('value', ''))
        if w:
            out.setdefault(w, int(n['noteId']))
    return out


def load_jiten_index(path=None):
    """Jiten 词频表 → {归一化词形: 排名}。

    与 `code/analysis/vocab_cover/freq_external.py field --all-notes` 用**同一份词表、
    同一套归一化**（`_norm.norm_word(primary_form(word))`），两边口径不许漂移。
    文件缺了就返回空表（全写 999999），不阻塞入库。
    """
    path = path or JITEN_WORDS
    if not os.path.exists(path):
        return {}
    return {norm_word(r['word']): r['freq_rank']
            for r in json.load(open(path, encoding='utf-8'))}


def jiten_rank(word, index=None):
    """这条词该写的 `JitenAnimeRank` 字段值（补零 6 位；词表里没有 → 999999）。

    补零是必须的：浏览器按字段排序是**文本序**，补零后文本序才等于数值序
    （`020686` vs `034309`）。用户口径（2026-10-12）：不排卡片位置，排序只认这个字段。
    """
    index = load_jiten_index() if index is None else index
    r = index.get(norm_word(primary_form(word)))
    return ('%06d' % r) if r else JITEN_NO_RANK


def next_index(model=None):
    """新卡的 `Index` 从几开始 —— **不能拿笔记条数当序号**。

    `Index` 是这个笔记类型的**首字段**，而 Anki 自己的查重只看首字段：
    只要历史上删过卡（或序号出现过空洞），`count(model) + 1` 就会撞上仍然存在的
    最大序号，整批 `addNotes` 被「cannot create note because it is a duplicate」
    拒绝 —— 6 条**全新词条**（闸门二已确认新牌组里没有同名卡）一条都进不去，
    而报错信息只会说是 duplicate，看不出重的是首字段。

    2026-10-12 第 01 集实测：count=6099、最大 Index=6100（= 目标 deck 里已有的「剣」）。
    取 **最大序号 + 1** 一定空闲（不存在比它更大的序号）。
    """
    model = model or P.CFG['mine_model']
    mx = 0
    for n in AK.notes_info(AK.find_notes('note:"%s"' % model)):
        v = str((n.get('fields', {}).get('Index', {}) or {}).get('value', '') or '').strip()
        if v.isdigit():
            mx = max(mx, int(v))
    return mx + 1


def cmd_write(a):
    path = os.path.join(GEN, 'verified.json')
    if verified_fresh():
        print('复用 %s（比全部产出文件都新，不再重跑一遍校验）' % path)
    else:
        build_payload()          # 产出有变动（或还没校验过）：在这里一次校验到位
    payload = json.load(open(path, encoding='utf-8'))
    deck = a.deck or P.CFG['mine_deck']
    model = P.CFG['mine_model']

    print('目标 deck ：%s' % deck)
    print('笔记模板 ：%s' % model)
    print('待入库   ：%d 条' % len(payload))
    print('模式     ：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才真写）'))
    print()

    # ---- 闸门一（「是否已存在于 core6000/考级词汇」）**不在这里重跑**：
    #   校验阶段已用同一份索引逐条判过，命中的条目根本没进 verified.json。
    #   再查一遍是同一件事做第二遍，还要重建一次 1.7 万张的索引。
    keep, dupe = list(payload), []

    # ---- 闸门二：新牌组自己的既有卡（幂等，重复跑不会重复建卡）
    have = existing_words(model)
    final = []
    for c in keep:
        w = P.norm(c['word'])
        if w in have:
            dupe.append((c['word'], have[w]))
        else:
            final.append(c)

    print('闸门一：已在已有词汇牌组里的条目在校验阶段已剔除（不重跑）')
    print('闸门二：新牌组里已有同名卡，跳过 %d 条' % len(dupe))
    for w, nid in dupe[:15]:
        print('   = %-12s noteId %s' % (w, nid))
    print()
    print('将要创建 %d 条笔记：' % len(final))
    for c in final:
        print('   %-12s [%s] %s  ← 例句卡 %s'
              % (c['word'], c['pos'], c['meaning'][:24], c['noteId']))
    if not final:
        print('没有可写入的条目。')
        return

    # ---- 闸门三：回头向来源例句卡重取 Sentence / Sentence HTML
    # 候选文件是几小时前 scan 的快照；写库这一刻以**来源卡当前值**为准，
    # 既不丢振假名（<ruby>），也不会用到已被人工修正过的旧句子。
    nids = sorted({int(c['noteId']) for c in final})
    live_src = AK.notes_map(nids) if nids else {}
    no_ruby = []
    for c in final:
        n = live_src.get(int(c['noteId']))
        if not n:
            continue
        s_raw = n['fields'].get('Sentence', {}).get('value', '') or ''
        s_html = n['fields'].get('Sentence HTML', {}).get('value', '') or ''
        if s_raw:
            c['sentence'] = s_raw
        c['sentence_html'] = (s_html or s_raw) or c['sentence_html']
        if P.KANJI.search(P.strip_html(c['sentence'])) and '<ruby>' not in c['sentence_html']:
            no_ruby.append(c['word'])
    if no_ruby:
        print()
        print('⚠ 以下词的例句含汉字但来源卡的 Sentence HTML 没有振假名（会按纯文本写入）：')
        print('   %s' % '、'.join(no_ruby))
        print('   处理：这些例句应当只有假名，或来源卡尚未生成振假名。确认无误可继续。')

    if not a.commit:
        dump = os.path.join(GEN, 'dryrun_notes.json')
        json.dump(final, open(dump, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print()
        print('演练结束，未写任何数据。载荷已存：%s' % dump)
        print('确认无误后加 --commit 重跑。')
        return

    # ---- 建 deck（不存在则建）
    AK.create_deck(deck)
    # Index 是首字段，Anki 的查重看它 —— 必须取「已有最大序号 + 1」，
    # 不能拿 count(model) 当序号（删过卡就会撞，见 next_index 的说明）。
    start = next_index(model)
    jiten = load_jiten_index()
    ranked = sum(1 for c in final if jiten_rank(c['word'], jiten) != JITEN_NO_RANK)
    print('Index 序号：%d…%d（模型内最大序号 + 1 起）' % (start, start + len(final) - 1))
    print('JitenAnimeRank：词表命中 %d / %d（其余写 %s）'
          % (ranked, len(final), JITEN_NO_RANK))
    tag = a.tag or '%s::%s' % (P.CFG['mine_tag_prefix'],
                               dt.datetime.now().strftime('%Y%m%d'))
    notes = []
    for i, c in enumerate(final):
        notes.append(AK.new_note(
            deck, model,
            fields={
                'Index': str(start + i),
                'JitenAnimeRank': jiten_rank(c['word'], jiten),
                'Word': c['word'],
                'Sentence': c['sentence'],
                'Sentence HTML': c['sentence_html'],
                'Transliteration': c['reading'],
                'Meaning': c['meaning'],
                'Part of Speech': c['pos'],
                'AINote': c['a_note'],
                'Sentence Translation': c['translation'],
            },
            tags=[tag]
            + ([P.CFG['mine_tag_prefix'] + '::' + slug(c['source'])]
               if slug(c.get('source')) else []),
            allow_duplicate=False, duplicate_scope='collection'))
    print()
    print('写入中…（一次 addNotes 批量提交 %d 条）' % len(notes))
    t0 = time.time()
    res = AK.add_notes(notes)
    # addNotes 与输入等长：成功的给 noteId，失败的给 null
    ok = [(final[i], int(r)) for i, r in enumerate(res) if r]
    null = [final[i]['word'] for i, r in enumerate(res) if not r]
    print('  addNotes 成功 %d / %d  (%.1fs)' % (len(ok), len(notes), time.time() - t0))
    for w in null[:20]:
        print('    ✗ 被拒（多半是查重）：%s' % w)

    # ---- 回读校验（按 noteId 定位，不靠数组顺序）
    ids = [nid for _c, nid in ok]
    back = AK.notes_map(ids) if ids else {}
    mism = []
    for c, nid in ok:
        n = back.get(nid)
        if n is None:
            mism.append((c['word'], 'noteId %s 查不到' % nid))
            continue
        for f, key in (('AINote', 'a_note'), ('Sentence HTML', 'sentence_html'),
                       ('Meaning', 'meaning'), ('Transliteration', 'reading'),
                       ('Word', 'word'), ('Part of Speech', 'pos'),
                       ('Sentence Translation', 'translation')):
            if n['fields'][f]['value'] != c[key]:
                mism.append((c['word'], f))
        want_rank = jiten_rank(c['word'], jiten)
        if (n['fields'].get('JitenAnimeRank', {}) or {}).get('value', '') != want_rank:
            mism.append((c['word'], 'JitenAnimeRank'))
    bad_words = {w for w, _ in mism}
    print()
    print('回读逐字一致：%d / %d' % (len(ok) - len(bad_words), len(final)))
    for w, f in mism[:20]:
        print('   ✗ %-12s %s' % (w, f))
    print()
    print('已入库 %d 条到 %s' % (len(ok), deck))
    print('回退：Anki 浏览器搜 tag:%s 全选删除即可（新卡尚未学习，删掉无损失）' % tag)


# ============================================================================
def main():
    ap = argparse.ArgumentParser(description='素材生词牌组（第三个词汇牌组）的挖掘与入库')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('scan', help='只读扫描例句，产出候选与报告')
    p.add_argument('--word-field', dest='word_field', action='store_true', default=True,
                   help='把例句卡 Word 字段的词也当候选（默认开：残差法扫不出被最长匹配吃掉的多字词）')
    p.add_argument('--no-word-field', dest='word_field', action='store_false',
                   help='只用残差法（老口径）')
    p.add_argument('--tag', default=None, help='只扫本集例句（默认扫整个 2-例句 deck）')
    p.add_argument('--limit', type=int, default=None, help='只保留排序最靠前的 N 个候选')
    p.add_argument('--max-examples', type=int, default=5, help='每个候选最多记几个例句')
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser('split', help='把候选切批（下一步交给 gen）')
    p.add_argument('--batches', type=int, default=8)
    p.add_argument('--print-prompts', action='store_true',
                   help='本地模型不可用时，打印子代理提示词（备用路径，会花云端 token）')
    p.set_defaults(func=cmd_split)

    p = sub.add_parser('gen', help='直连本地模型判定候选（默认跳过已存在的批次）')
    p.add_argument('--per-request', type=int, default=6, help='首轮每次请求几条候选（默认 6）')
    p.add_argument('--retries', type=int, default=1, help='不合格时带问题重问的轮数（默认 1；重问逐条发）')
    p.add_argument('--force', action='store_true', help='已存在的 output_NN.json 也重做')
    p.add_argument('--fix-failed', action='store_true',
                   help='只重跑 failed.json 里的候选（本地模型再试一遍，修好的并回）')
    p.set_defaults(func=cmd_gen)

    p = sub.add_parser('merge-fix', help='把强模型（deepseek）补做的 fix 产出并回 output_NN.json')
    p.add_argument('--file', default='fix_output.json',
                   help='fix 产出文件（默认 data/vocab/gen_mine/fix_output.json）')
    p.set_defaults(func=cmd_merge_fix)

    sub.add_parser('verify', help='校验 data/vocab/gen_mine/output_*.json').set_defaults(func=cmd_verify)

    p = sub.add_parser('write', help='把校验通过的生词写入新牌组（默认演练）')
    p.add_argument('--commit', action='store_true', help='真写库（不加则只演练）')
    p.add_argument('--deck', default=None, help='覆盖目标 deck')
    p.add_argument('--tag', default=None, help='覆盖本次打的标签')
    p.set_defaults(func=cmd_write)

    a = ap.parse_args()
    with AK.guard():          # AnkiConnect 出错 → 中文提示，不出 traceback
        a.func(a)


if __name__ == '__main__':
    main()
