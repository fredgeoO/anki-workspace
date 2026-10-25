# -*- coding: utf-8 -*-
"""日语分词与「词表匹配」层：把任意日语文本切成可统计的词元，判定每个词元落在
core6000 / 考级词汇 / 素材生词 的哪一档，以及你自己是「已学」「成熟」还是全新。

四个关键设计（都是被数据纠正出来的）
------------------------------------
1. **正规形态素解析**（SudachiPy + SudachiDict Core），不用「拿卡组词表做最长匹配」，
   否则未知词会被贪心合并，覆盖率必然偏乐观。
2. **不建「读音 -> 汉字词」别名表**。实测它制造大量假命中（假名 た 会同时对上 他/田，
   ガス 会同时对上 8 个不相干的词）。假名写法 -> 汉字词交给 Sudachi 的 normalized_form
   （已验证 キレイ->奇麗、やけ->焼け、やっ->遣る）。
3. **先按词性分档，再看词表**：助詞/助動詞/接頭辞/接尾辞 归入 ``grammar``（语法词，
   按「已知」处理 —— 你的语法卡组有 3160 张，且这些不属于要背的词汇），
   这样词汇覆盖率的分母才是真正的「词汇词」。
4. **符号不参与统计**：補助記号/記号/空白 归入 ``symbol``，否则「，」「。」会被算成生词。

对外主接口::

    v = Vocabulary.load()                 # 读 data/vocab_cover/vocab_state.json
    toks = v.tokenize(text)               # -> list[Token]
    s = v.coverage(toks, sentences=...).summary()   # -> 全套统计
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field

from _deps import add_pylibs, load_state
from _norm import (KANA_EXTRA, norm_word, to_hiragana)  # noqa: F401  (re-export)

add_pylibs()

# 符号 / 空白：完全不参与统计
SKIP_POS1 = {'補助記号', '記号', '空白'}
# 语法词：按「已知」处理，不进词汇覆盖率的分母
GRAMMAR_POS1 = {'助詞', '助動詞', '接頭辞', '接尾辞', 'フィラー'}
# 实词/词汇词
VOCAB_POS1 = {'名詞', '動詞', '形容詞', '形状詞', '副詞', '代名詞', '連体詞',
              '接続詞', '感動詞'}

JP_CHAR = re.compile(r'[\u3041-\u3096\u30a1-\u30fa\u4e00-\u9fff\u3400-\u4dbf\u3005\u30fc]')

DECK_BUCKETS = ('core6000', 'jlpt', 'mined')
# 不在卡组里的词汇词，按「要不要背」再分四档：
#   oov     真·要背的实词（名詞/動詞/形容詞/副詞…）
#   proper  固有名詞（人名地名作品名，跟着剧情自然学会，不算词汇量）
#   interj  感動詞（あっ/ん/はっ 之类，属听力反应而非词汇）
#   numeral 数詞（一/百五十，会数数就会）
OOV_BUCKETS = ('oov', 'proper', 'interj', 'numeral')
VOCAB_BUCKETS = DECK_BUCKETS + OOV_BUCKETS
LEARNABLE_BUCKETS = DECK_BUCKETS + ('oov',)


@dataclass
class Token:
    surface: str
    pos1: str
    pos2: str
    normalized: str = ''
    dictionary: str = ''
    reading: str = ''
    key: str = ''                    # 命中的词表规范键（'' = 没命中）
    bucket: str = 'oov'              # core6000/jlpt/mined/oov/grammar/symbol/non_jp
    known: bool = False              # 我刷过至少一次
    mature: bool = False             # 复习卡且间隔 >= 21 天
    deck_hit: bool = False           # 语法词也命中过卡组（只作诊断）
    compound_of_known: bool = False  # 整体不在词表，但可拆成全是已知的实词
    in_deck_untouched: bool = False  # 词表里有卡，但我一次都没刷过

    @property
    def is_symbol(self) -> bool:
        return self.pos1 in SKIP_POS1

    @property
    def is_grammar(self) -> bool:
        return self.bucket == 'grammar'

    @property
    def is_vocab(self) -> bool:
        return self.bucket in VOCAB_BUCKETS

    @property
    def understood(self) -> bool:
        """严格口径：语法词算懂；其余词汇词要求已学（专有名词/感动词算不懂）。"""
        if self.bucket == 'grammar':
            return True
        if self.bucket in ('oov', 'proper', 'interj', 'numeral'):
            return bool(self.compound_of_known)
        return self.known

    @property
    def understood_lenient(self) -> bool:
        """宽口径：把感动词与数词也算懂（听到「あっ」不该算听不懂）。"""
        if self.bucket in ('grammar', 'interj', 'numeral'):
            return True
        if self.bucket in ('oov', 'proper'):
            return bool(self.compound_of_known)
        return self.known

    @property
    def understood_mature(self) -> bool:
        if self.bucket in ('grammar', 'interj', 'numeral'):
            return True
        if self.bucket in ('oov', 'proper'):
            return bool(self.compound_of_known)
        return self.mature


class Vocabulary:
    """卡组词表 + 我的学习状态，以及文本 -> 覆盖率统计。"""

    def __init__(self, state: dict, split_mode: str = 'A'):
        self.state = state
        self.words = state['words']
        self.split_mode = split_mode
        self.mature_days = state.get('mature_days', 21)
        self._tagger = None
        self._tagger_short = None
        self._tok_cache: dict = {}

    @classmethod
    def load(cls, path=None, split_mode: str = 'A') -> 'Vocabulary':
        return cls(load_state(path) if path else load_state(), split_mode=split_mode)

    # ------------------------------------------------------------------ 分词器
    def _make_tagger(self, mode_name: str):
        from sudachipy import Dictionary, SplitMode
        d = Dictionary(dict='core')
        maker = getattr(d, 'tokenizer', None) or d.create
        return maker(), {'A': SplitMode.A, 'B': SplitMode.B, 'C': SplitMode.C}[mode_name]

    @property
    def tagger(self):
        if self._tagger is None:
            self._tagger = self._make_tagger(self.split_mode)
        return self._tagger

    @property
    def short_tagger(self):
        if self._tagger_short is None:
            self._tagger_short = self._make_tagger('A')
        return self._tagger_short

    # ------------------------------------------------------------------ 匹配
    @staticmethod
    def _pos(morpheme) -> tuple:
        p = morpheme.part_of_speech()
        if isinstance(p, (tuple, list)):
            return (p[0], p[1] if len(p) > 1 else '')
        parts = str(p).split(',')
        return (parts[0], parts[1] if len(parts) > 1 else '')

    def lookup_keys(self, morpheme) -> tuple:
        out = []
        for c in (morpheme.normalized_form(), morpheme.dictionary_form(),
                  morpheme.surface()):
            n = norm_word(c)
            if n and n not in out:
                out.append(n)
        return tuple(out)

    def match(self, morpheme) -> tuple:
        """返回 (key, bucket, known, mature)，bucket 为 core6000/jlpt/mined/oov。"""
        for k in self.lookup_keys(morpheme):
            e = self.words.get(k)
            if e is not None:
                b = ('core6000' if e.get('core') else
                     'jlpt' if e.get('jlpt') else
                     'mined' if e.get('mined') else 'oov')
                return k, b, e['known'], e['mature']
        return '', 'oov', False, False

    # ------------------------------------------------------------------ 切词
    def tokenize(self, text: str, decompose_oov: bool = True) -> list:
        ck = (text, decompose_oov)
        hit = self._tok_cache.get(ck)
        if hit is not None:
            return hit
        toks = []
        for m in self.tagger[0].tokenize(text, self.tagger[1]):
            pos1, pos2 = self._pos(m)
            t = Token(surface=m.surface(), pos1=pos1, pos2=pos2,
                      normalized=m.normalized_form(), dictionary=m.dictionary_form(),
                      reading=m.reading_form())
            if t.is_symbol:
                t.bucket = 'symbol'
            elif not JP_CHAR.search(t.surface):
                t.bucket = 'non_jp'
            else:
                key, bucket, known, mature = self.match(m)
                if pos1 in GRAMMAR_POS1:
                    t.bucket = 'grammar'
                    t.deck_hit = bool(key)
                    t.key, t.known, t.mature = key, known, mature
                elif bucket == 'oov':
                    # 不在卡组里：再按「要不要背」细分
                    t.key, t.known, t.mature = key, known, mature
                    if pos1 == '感動詞':
                        t.bucket = 'interj'
                    elif pos2 == '固有名詞':
                        t.bucket = 'proper'
                    elif pos2 == '数詞':
                        t.bucket = 'numeral'
                    else:
                        t.bucket = 'oov'
                    if t.bucket == 'oov' and decompose_oov and len(t.surface) > 1:
                        t.compound_of_known = self._decomposes_into_known(t.surface)
                else:
                    t.key, t.bucket, t.known, t.mature = key, bucket, known, mature
                    if t.bucket in DECK_BUCKETS and not t.known:
                        t.in_deck_untouched = True
            toks.append(t)
        self._tok_cache[ck] = toks
        return toks

    def _decomposes_into_known(self, surface: str) -> bool:
        """整体未命中词表，但按短单位拆开后每个实词子词都已学（如 日本語学習）。"""
        subs = []
        for m in self.short_tagger[0].tokenize(surface):
            pos1, _ = self._pos(m)
            if pos1 in SKIP_POS1 or pos1 in GRAMMAR_POS1:
                continue
            if not JP_CHAR.search(m.surface()):
                continue
            subs.append(m)
        if not subs:
            return False
        for m in subs:
            _k, bucket, known, _mt = self.match(m)
            if bucket == 'oov' or not known:
                return False
        return True

    # ------------------------------------------------------------------ 覆盖率
    def coverage(self, toks: list, sentences: list = None) -> 'Coverage':
        return Coverage(self, toks, sentences)


@dataclass
class Coverage:
    """一份文本（一集字幕 / 一篇文章）的统计。所有口径由 ``summary()`` 一次给出。"""

    vocab: Vocabulary
    toks: list
    sentences: list = None
    _cache: dict = field(default_factory=dict, repr=False)

    # -- 基础分组 -----------------------------------------------------------
    def groups(self) -> dict:
        if 'groups' not in self._cache:
            g = collections.defaultdict(list)
            for t in self.toks:
                if t.bucket in ('symbol', 'non_jp'):
                    continue
                g[t.bucket].append(t)
            self._cache['groups'] = g
        return self._cache['groups']

    def counts(self) -> dict:
        return {k: len(v) for k, v in self.groups().items()}

    def _uniq(self, bucket: str) -> set:
        ck = ('uniq', bucket)
        if ck not in self._cache:
            self._cache[ck] = {t.key or norm_word(t.surface)
                               for t in self.groups().get(bucket, [])}
        return self._cache[ck]

    # -- 覆盖率 -------------------------------------------------------------
    def _cover(self, denom_tokens: int, denom_types: int, buckets) -> dict:
        """覆盖率。``buckets`` = 该口径的分母包含哪些档位。

        分子统一按「这个词算不算懂」逐词元判定（``Token.understood`` /
        ``understood_lenient``），因此语法词只在含语法词口径里计入「懂」，
        不会出现「词汇词口径下理解率 >100%」这种错误。
        """
        buckets = set(buckets)
        g = self.groups()
        cnt = {k: len(v) for k, v in g.items()}
        if not denom_tokens or not denom_types:
            return {}
        toks_in = [t for b in buckets for t in g.get(b, [])]
        deck_tokens = sum(cnt.get(b, 0) for b in DECK_BUCKETS)
        known_tokens = sum(1 for b in DECK_BUCKETS for t in g.get(b, []) if t.known)
        mature_tokens = sum(1 for b in DECK_BUCKETS for t in g.get(b, []) if t.mature)
        understood = sum(1 for t in toks_in if t.understood)
        understood_lenient = sum(1 for t in toks_in if t.understood_lenient)
        understood_mature = sum(1 for t in toks_in if t.understood_mature)

        def uniq(pred=None):
            return {t.key or norm_word(t.surface) for t in toks_in if pred is None or pred(t)}

        deck_types = set().union(*[self._uniq(b) for b in DECK_BUCKETS]) \
            if DECK_BUCKETS else set()
        known_types = {t.key or norm_word(t.surface)
                       for b in DECK_BUCKETS for t in g.get(b, []) if t.known}
        mature_types = {t.key or norm_word(t.surface)
                        for b in DECK_BUCKETS for t in g.get(b, []) if t.mature}
        return {
            'denom_tokens': denom_tokens, 'denom_types': denom_types,
            'core': cnt.get('core6000', 0) / denom_tokens,
            'core_tokens': cnt.get('core6000', 0),
            'jlpt_tokens': cnt.get('jlpt', 0), 'mined_tokens': cnt.get('mined', 0),
            'corejlpt_tokens': cnt.get('core6000', 0) + cnt.get('jlpt', 0),
            'corejlpt': (cnt.get('core6000', 0) + cnt.get('jlpt', 0)) / denom_tokens,
            'oov_tokens': cnt.get('oov', 0),
            'proper_tokens': cnt.get('proper', 0), 'interj_tokens': cnt.get('interj', 0),
            'numeral_tokens': cnt.get('numeral', 0),
            'grammar_tokens': cnt.get('grammar', 0),
            'deck': deck_tokens / denom_tokens,
            'deck_tokens': deck_tokens,
            'known': known_tokens / denom_tokens,
            'mature': mature_tokens / denom_tokens,
            'understood': understood / denom_tokens,
            'understood_lenient': understood_lenient / denom_tokens,
            'understood_mature': understood_mature / denom_tokens,
            'oov': cnt.get('oov', 0) / denom_tokens,
            'grammar': cnt.get('grammar', 0) / denom_tokens,
            'proper': cnt.get('proper', 0) / denom_tokens,
            # 词种口径
            'core_types': len(self._uniq('core6000')) / denom_types,
            'corejlpt_types': (len(self._uniq('core6000')) + len(self._uniq('jlpt')))
            / denom_types,
            'deck_types': len(deck_types) / denom_types,
            'known_types': len(known_types) / denom_types,
            'mature_types': len(mature_types) / denom_types,
            'oov_types': len(self._uniq('oov')) / denom_types,
            'proper_types': len(self._uniq('proper')) / denom_types,
            'interj_types': len(self._uniq('interj')) / denom_types,
            'understood_types': len(uniq(lambda t: t.understood)) / denom_types,
            'understood_lenient_types':
                len(uniq(lambda t: t.understood_lenient)) / denom_types,
            'grammar_types': len(self._uniq('grammar')),
            'compound_tokens': sum(1 for t in self.toks if t.compound_of_known),
            'compound_types': len({t.key or norm_word(t.surface) for t in self.toks
                                   if t.compound_of_known}),
        }

    def summary(self) -> dict:
        if 'summary' in self._cache:
            return self._cache['summary']
        cnt = self.counts()
        n_all = sum(cnt.values())
        n_grammar = cnt.get('grammar', 0)
        n_symbol = sum(1 for t in self.toks if t.bucket == 'symbol')
        n_nonjp = sum(1 for t in self.toks if t.bucket == 'non_jp')
        n_vocab = n_all - n_grammar
        n_learnable = sum(cnt.get(b, 0) for b in LEARNABLE_BUCKETS)
        types_all = sum(len(self._uniq(b)) for b in self.groups())
        types_grammar = len(self._uniq('grammar'))
        types_vocab = types_all - types_grammar
        types_learnable = sum(len(self._uniq(b)) for b in LEARNABLE_BUCKETS)
        res = {
            'tokens': {'all': n_all, 'vocab': n_vocab, 'grammar': n_grammar,
                       'learnable': n_learnable,
                       'symbol': n_symbol, 'non_jp': n_nonjp},
            'buckets': {b: cnt.get(b, 0) for b in VOCAB_BUCKETS + ('grammar',)},
            'types': {'all': types_all, 'grammar': types_grammar,
                      'vocab': types_vocab, 'learnable': types_learnable,
                      'buckets': {b: len(self._uniq(b))
                                  for b in VOCAB_BUCKETS + ('grammar',)}},
            # 分母=全部词元（含语法词）：满足「不排除助词」的要求
            'cover_all': self._cover(n_all, types_all, VOCAB_BUCKETS + ('grammar',)),
            # 分母=词汇词（含专有名词/感动词/数词，去掉语法词与符号）
            'cover_vocab': self._cover(n_vocab, types_vocab, VOCAB_BUCKETS),
            # 分母=需要背的实词（再去掉专有名词/感动词/数词）：最贴近「词汇量」的口径
            'cover_learnable': self._cover(n_learnable, types_learnable, LEARNABLE_BUCKETS),
            'oov': self.oov_words(),
            'proper': self.proper_words(),
            'untackled': self.untackled_deck_words(),
            'sentences': self.sentence_stats(),
        }
        self._cache['summary'] = res
        return res

    # -- 新词 / 待学 ---------------------------------------------------------
    def _word_list(self, bucket: str, min_count: int = 1,
                   exclude_known_compound: bool = True) -> list:
        c = collections.Counter()
        pos = {}
        for t in self.groups().get(bucket, []):
            if exclude_known_compound and t.compound_of_known:
                continue
            w = norm_word(t.surface)
            if not w:
                continue
            c[w] += 1
            pos.setdefault(w, f'{t.pos1}/{t.pos2}')
        return [[w, n, pos[w]] for w, n in c.most_common() if n >= min_count]

    def oov_words(self, min_count: int = 1, exclude_known_compound: bool = True) -> list:
        """完全不在任何卡组里、且**需要背**的实词（按出现次数降序）：[[词, 次数, 词性]]"""
        return self._word_list('oov', min_count, exclude_known_compound)

    def proper_words(self, min_count: int = 1) -> list:
        """卡组外的固有名詞（人名/地名/作品名）：[[词, 次数, 词性]]"""
        return self._word_list('proper', min_count, False)

    def untackled_deck_words(self, min_count: int = 1) -> list:
        """词表里有卡、但我一次都没刷过的词：[[词, 档位, 次数]]"""
        c = collections.Counter()
        for b in DECK_BUCKETS:
            for t in self.groups().get(b, []):
                if not t.known:
                    c[(t.key or norm_word(t.surface), b)] += 1
        return [[k[0], k[1], n] for k, n in c.most_common() if n >= min_count]

    # -- 句子级可懂度 --------------------------------------------------------
    def sentence_stats(self) -> dict:
        """按「一句字幕」统计：整句没有不懂的词 / 只有 1 个不懂的词。

        ``full``/``lenient`` 用严格口径（专有名词、感动词也算不懂）；
        ``*_l`` 是宽口径（感动词/数词算懂）。
        """
        if not self.sentences:
            return {}
        ok0 = ok1 = ok2 = ok0l = ok1l = total = 0
        hist = collections.Counter()
        hist_l = collections.Counter()
        for s in self.sentences:
            content = [t for t in self.vocab.tokenize(s) if t.is_vocab]
            if not content:
                continue
            unk = [t for t in content if not t.understood]
            unk_l = [t for t in content if not t.understood_lenient]
            total += 1
            hist[min(len(unk), 5)] += 1
            hist_l[min(len(unk_l), 5)] += 1
            ok0 += 1 if not unk else 0
            ok1 += 1 if len(unk) <= 1 else 0
            ok2 += 1 if len(unk) <= 2 else 0
            ok0l += 1 if not unk_l else 0
            ok1l += 1 if len(unk_l) <= 1 else 0
        if not total:
            return {}
        return {'sentences': total,
                'full': ok0 / total, 'lenient': ok1 / total, 'lenient2': ok2 / total,
                'full_l': ok0l / total, 'lenient_l': ok1l / total,
                'unknown_hist': dict(sorted(hist.items())),
                'unknown_hist_l': dict(sorted(hist_l.items()))}


# ------------------------------------------------------------------ 理解度映射
# 覆盖率 -> 理解度的经验锚点（词汇覆盖率研究 Laufer / Nation 一系；粗估，不是测量）
COMPREHENSION_ANCHORS = [
    (0.70, 0.10), (0.80, 0.28), (0.90, 0.50), (0.95, 0.70),
    (0.98, 0.80), (0.99, 0.90), (1.00, 0.97),
]

# 无字幕听力需要的覆盖率比阅读更高：没有回看、没有汉字视觉线索
LISTENING_PENALTY = 0.03


def coverage_to_comprehension(cover: float, listening: bool = False) -> float:
    """词汇覆盖率 -> 篇章理解度的粗略估计（分段线性插值）。"""
    pts = COMPREHENSION_ANCHORS
    x = cover - (LISTENING_PENALTY if listening else 0.0)
    if x <= pts[0][0]:
        return max(0.0, x / pts[0][0] * pts[0][1])
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return 0.0
