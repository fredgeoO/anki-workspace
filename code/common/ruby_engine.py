# -*- coding: utf-8 -*-
"""确定性振假名引擎 —— 结构问题一律用代码解决，语言模型只审「读音盲区」。

为什么要有它
------------
阶段二的失败**几乎全是机械问题**，却被丢回语言模型重试（2026-10-11 实测：
本地模型 17 张里 11 张不合格，原因只有三类 ——
「Sentence HTML 与 Sentence 不一致：誰も vs 誰もが」「有未标 ruby 的汉字」「没返回这张卡」）。
前两类用传统编程方法**可以彻底消除**：

* **字符一致性**：不要「让模型重写句子再校验」，而是**拿原始 Sentence 当骨架**，
  只把模型给的 ruby 贴回去 —— 逐字一致就是构造出来的，不可能不一致。
* **ruby 覆盖**：哪个汉字没标 ruby 是纯文本扫描；缺的读音从**四个确定性来源**补齐。

四个读音来源（优先级从高到低，见 `Lexicon`）
--------------------------------------------
1. **人工例外表** `data/ruby/readings.json`：确定性的正确答案（`殿下=でんか`、
   `格好=かっこう`），一旦写进去永不再问模型。
2. **字幕自带注音**：筛选后的 SRT 里 `漢字(かな)` 是字幕作者给的权威读音
   （`filter_subtitle.py` 的证据目录里就有）。
3. **本 deck 已入库卡的读音**：同一个词在你已有的例句卡里怎么读，是有先例的
   （口径与 `check_ruby.build_lexicon` 完全一致：多字、且读法唯一）。
4. **Sudachi 词典**（`data/pylibs` 里的 SudachiPy + SudachiDict Core）：
   兜底来源，覆盖面最广，但对多音词可能给错（`私→わたくし`、`風→ふう`）。

于是「该问语言模型的东西」被压缩成一个很小的清单：**四个来源都盖不到、
或者互相矛盾的基底**（`blind_spot()` 输出）。其余全归代码。

用法
----
    # 1) 只读体检：结构不合格 + 跨来源读音冲突 + 盲区清单（一次跑完，不写库）
    python code/common/ruby_engine.py check --query "tag:动画::…::第01集"
    python code/common/ruby_engine.py check --gen data/pipeline/gen --srt "<筛选后的 srt>"

    # 2) 修阶段二产出：把 output_NN.json 里的 SentenceHTML 按"原文骨架 + 已给 ruby"重写
    python code/common/ruby_engine.py repair --gen data/pipeline/gen            # 演练
    python code/common/ruby_engine.py repair --gen data/pipeline/gen --write    # 写回 JSON

    # 3) 直接修库里的卡（默认演练）
    python code/common/ruby_engine.py apply --query "tag:动画::…::第01集" --commit

    # 4) 单独渲染/试一条
    python code/common/ruby_engine.py render --sentence "殿下　王城でお控えください。"

退出码：`check` 有结构性不合格时为 1（可当闸门串进流水线）；只有读音冲突/盲区时为 0。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import anki_api as AK      # noqa: E402  唯一的 Anki 访问点
import check_cards as CC   # noqa: E402  结构规则的唯一实现（本模块不再抄一份）
import check_ruby as CR    # noqa: E402  读音词典与字幕注音的现成口径
import paths as WSP        # noqa: E402  工作区路径唯一来源
import textio              # noqa: E402  UTF-8 stdio 唯一入口

KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
KANA = re.compile(r'[\u3041-\u3096\u30a0-\u30ff\u30fc]')
HIRA_ONLY = re.compile(r'^[\u3041-\u3096\u30fc]+$')
KANA_ONLY = re.compile(r'^[\u3041-\u3096\u30a0-\u30ff\u30fc]+$')
RUBY = re.compile(r'<ruby>(.*?)<rt>(.*?)</rt></ruby>', re.S)
TAG = re.compile(r'<[^>]+>')

#: 人工例外表（读音的唯一权威来源）。放 data/ 下，便于手工/脚本追加。
PINNED = os.path.join(WSP.DATA, 'ruby', 'readings.json')
DEFAULT_DECK = 'deck:"0-日本语学习::2-例句"'

#: 读音来源名（按优先级），报告里直接打印这些词
SRC_PINNED, SRC_ANNO, SRC_DECK, SRC_SUDACHI, SRC_GIVEN = (
    'pinned', '字幕注音', '本deck', 'sudachi', '原HTML')


# ============================================================================
# 基础：假名、对齐、拆段
# ============================================================================
def hira(s: str) -> str:
    """片假名 → 平假名（长音符 ー 原样保留）。"""
    return ''.join(chr(ord(c) - 0x60) if '\u30a1' <= c <= '\u30f6' else c for c in (s or ''))


def split_segments(surface: str, reading: str):
    """把 (词形, 读音) 拆成 [(文本, 读音或 None)]：汉字串带读音，送假名裸放。

    送假名必须放在 `<rt>` **之外**（`<ruby>食<rt>た</rt></ruby>べる`），
    敬语接头辞 お/ご 同理（`お<ruby>墓<rt>はか</rt></ruby>`）。
    对齐规则：词形里的假名必须在读音里按顺序出现，用它当锚点切分；
    对不上就整体当一个 ruby（结构仍然合法），由 `validate` 去决定要不要报。

    例：('食べる','たべる') → [('食','た'), ('べる',None)]
        ('お墓','おはか')   → [('お',None), ('墓','はか')]
        ('取り巻き','とりまき') → [('取','と'),('り',None),('巻','ま'),('き',None)]
    """
    surface = surface or ''
    reading = (reading or '').strip()
    if not surface or not KANJI.search(surface):
        return [(surface, None)] if surface else []
    if not reading or not HIRA_ONLY.match(reading):
        return [(surface, None)]          # 没有可用读音 → 原样（validate 会报未标 ruby）

    out = []
    # 敬语接头辞：お/ご 不进 ruby（两侧同时剥）
    if surface[0] in 'おご' and len(surface) > 1 and KANJI.match(surface[1]) \
            and reading[:1] == surface[0]:
        out.append((surface[0], None))
        surface, reading = surface[1:], reading[1:]

    i = j = 0
    n, m = len(surface), len(reading)
    while i < n:
        if KANJI.match(surface[i]):
            k = i
            while k < n and KANJI.match(surface[k]):
                k += 1
            # 汉字串后面紧跟的假名串 = 锚点
            a = k
            while a < n and KANA.match(surface[a]):
                a += 1
            anchor = surface[k:a]
            if anchor:
                pos = reading.find(anchor, j)
                if pos <= j:                       # 锚点对不上 → 整体一个 ruby
                    return [(surface, reading)]
                out.append((surface[i:k], reading[j:pos]))
                out.append((anchor, None))
                j = pos + len(anchor)
                i = a
            else:                                  # 汉字串到词尾
                out.append((surface[i:k], reading[j:]))
                j = m
                i = k
        else:                                      # 词形里的假名：与读音逐字核对
            if j < m and reading[j] == surface[i]:
                j += 1
            else:
                return [(surface, reading)]
            i += 1
            if out and out[-1][1] is None:
                out[-1] = (out[-1][0] + surface[i - 1], None)
            else:
                out.append((surface[i - 1], None))
    if j != m:                                     # 读音没吃完 → 对齐不可信
        return [(surface, reading)]
    return out


def wrap(text: str, reading):
    """按拆分结果包 ruby；纯假名不加 ruby。"""
    if not reading or not KANJI.search(text):
        return text
    return '<ruby>%s<rt>%s</rt></ruby>' % (text, reading)


def pieces(text: str, reading, segs=None):
    return ''.join(wrap(t, r) for t, r in (segs if segs is not None else split_segments(text, reading)))


def strip_text(html: str) -> str:
    """与 check_cards.text_of 同一口径（先去 <rt> 块再去标签）。"""
    return CC.text_of(html or '')


# ============================================================================
# 读音词典（四个来源）
# ============================================================================
class Lexicon:
    """{基底: 读音} + 每个读音的来源，以及字幕注音（按句）与 Sudachi 兜底。"""

    def __init__(self, pinned=None, annos=None, deck=None):
        self.pinned = dict(pinned or {})       # 基底 → 读音（人工权威）
        self.annos = dict(annos or {})         # 整句 → {基底: 读音}（字幕注音）
        self.deck = dict(deck or {})           # 基底 → 读音（本 deck 已入库卡，唯一读法）
        self._tagger = None
        self._tok_cache = {}
        self.hits = {}                         # 统计：来源 → 命中次数

    # ---------------------------------------------------------------- 建表
    @classmethod
    def build(cls, *, query=DEFAULT_DECK, exclude_ids=(), srt=None, plan=None,
              pinned_path=PINNED, use_deck=True):
        pinned = {}
        if pinned_path and os.path.isfile(pinned_path):
            with open(pinned_path, encoding='utf-8') as fh:
                raw = json.load(fh)
            pinned = {k: v for k, v in (raw.get('readings') or raw).items()
                      if isinstance(v, str) and v}
        annos = read_annotations(srt or plan_output(plan)) if (srt or plan) else {}
        deck = {}
        if use_deck:
            try:
                deck = CR.build_lexicon(query, {int(x) for x in exclude_ids})
            except Exception as exc:                     # Anki 没开 / 查询写错
                print('  （本 deck 读音词典跳过：%s）' % exc)
        print('读音来源：人工例外 %d / 字幕注音句 %d / 本 deck 词条 %d'
              % (len(pinned), len(annos), len(deck)))
        return cls(pinned, annos, deck)

    # ---------------------------------------------------------------- Sudachi
    def tagger(self):
        if self._tagger is None:
            pylibs = os.path.join(WSP.DATA, 'pylibs')
            if pylibs not in sys.path:
                sys.path.append(pylibs)
            from sudachipy import Dictionary, SplitMode
            d = Dictionary(dict='core')
            maker = getattr(d, 'tokenizer', None) or d.create
            self._tagger = (maker(), SplitMode.C)
        return self._tagger

    def tokenize(self, text):
        key = text
        if key not in self._tok_cache:
            self._tok_cache[key] = list(self.tagger()[0].tokenize(text, self.tagger()[1]))
        return self._tok_cache[key]

    # ---------------------------------------------------------------- 查读音
    def annos_for(self, sentence):
        """该句的字幕注音 {基底: 读音}（键 = 去掉 <br> 的整句），没有就空。"""
        return self.annos.get(strip_text(sentence).replace('\n', ''), {})

    def lookup(self, surface, sentence=None, given=None, order=None):
        """返回 (读音, 来源)；查不到返回 (None, None)。

        `given` 是原 HTML 里模型已经给过的 ruby（基底→读音）。
        默认顺序：人工例外 → 字幕注音 → 本 deck → Sudachi；
        带 `given` 且 `order` 把它排前面时，等价于「保留模型已给的读法，只补缺的」。
        """
        order = order or (SRC_PINNED, SRC_ANNO, SRC_DECK, SRC_SUDACHI)
        annos = self.annos_for(sentence) if sentence else {}
        for src in order:
            if src == SRC_PINNED and surface in self.pinned:
                return self.pinned[surface], src
            if src == SRC_ANNO and surface in annos:
                return annos[surface], src
            if src == SRC_DECK and surface in self.deck:
                return self.deck[surface], src
            if src == SRC_GIVEN and given and surface in given:
                return given[surface], src
            if src == SRC_SUDACHI and sentence is not None:
                r = self._sudachi_reading(surface, sentence)
                if r:
                    return r, src
        return None, None

    def _sudachi_reading(self, surface, sentence):
        """在该句里找到这个 token，用它的 reading_form。

        Sudachi 常把一个词切成更小的单位（`魔道具` → 魔道+具、`姫様` → 姫+様），
        这时按**分词拼接**给出读音（`ひめ`+`さま` = ひめさま）——这是词典给出的
        逐字读音，可信度低于 deck 先例/字幕注音，但足以把「明显不可能的读法」
        （姫様→ひみま）拎出来。

        **送假名词干**（卡里的基底是长 token 的前缀：`見習` ⊂ `見習い`、`食` ⊂ `食べる`）
        要走另一条路：Sudachi 对**裸词干**给的是别的词条的读音（`見習`→みならい、
        `食`→しょく），拿它当"Sudachi 有意见"会稳定误报 `待复核`，人照它改还会把
        `見習(みなら)い` 改成 `見習(みならい)い`（读成 みならいい）。所以先在句子里
        找「基底 + 纯假名尾巴」的 token，按尾巴长度从读音里切掉尾巴 —— 送假名的读音
        就是它自己，这个切法是构造出来的，不需要词典。
        """
        try:
            for tk in self.tokenize(sentence or ''):
                if tk.surface() == surface:
                    r = hira(tk.reading_form())
                    if HIRA_ONLY.match(r or ''):
                        return r
                elif surface and tk.surface().startswith(surface):
                    rest = hira(tk.surface()[len(surface):])
                    r = hira(tk.reading_form())
                    if (rest and KANA_ONLY.match(rest) and HIRA_ONLY.match(r or '')
                            and len(r) > len(rest) and r.endswith(rest)):
                        return r[:-len(rest)]      # 词干读音 = 整词读音去掉送假名那一段
        except Exception:
            pass
        try:
            toks = self.tokenize(surface)
        except Exception:
            return None
        if not toks or ''.join(t.surface() for t in toks) != surface:
            return None
        parts = []
        for tk in toks:
            if KANJI.search(tk.surface()):
                r = hira(tk.reading_form())
                if not HIRA_ONLY.match(r or ''):
                    return None
                parts.append(r)
            else:
                parts.append(tk.surface())       # 假名/符号照抄
        joined = ''.join(parts)
        return joined if HIRA_ONLY.match(joined) else None

    def note_hit(self, src):
        self.hits[src] = self.hits.get(src, 0) + 1


# ============================================================================
# 渲染 / 修复
# ============================================================================
def read_annotations(path):
    """读筛选后的 SRT → {整句（去 <br>）: {汉字串: 读音}}（口径同 check_ruby 的 ANN）。"""
    if not path or not os.path.isfile(path):
        return {}
    out = {}
    for b in CR.read_srt(path):
        txt = ''.join(CR.deannotate(x) for x in b['lines'])
        found = {}
        for line in b['lines']:
            for m in CR.ANN.finditer(line):
                found[m.group(1)] = m.group(2)
        if found:
            out[txt] = found
    return out


def plan_output(plan_path):
    """filter_subtitle.py 的 plan.json → 它筛出来的 SRT 路径。"""
    if not plan_path:
        return None
    with open(plan_path, encoding='utf-8') as fh:
        return json.load(fh).get('output')


def given_readings(html, sentence):
    """原 HTML 里模型给的 ruby（基底→读音），只收基底确实出现在句子里的。"""
    plain = strip_text(sentence)
    out = {}
    for base, reading in RUBY.findall(html or ''):
        b = TAG.sub('', base)
        if b and b in plain and KANJI.search(b):
            out.setdefault(b, reading)
    return out


def render(sentence, lex: Lexicon, given=None, order=None, stats=None):
    """按原始 Sentence 渲染出 Sentence HTML（**逐字一致是构造出来的**）。

    `<br>` 原位置保留；token 之间的空白/符号/〓 一律照抄原文（用 token 的
    begin/end 切片，不做任何"重新拼接"）。
    """
    given = given or {}
    out = []
    for i, block in enumerate(sentence.split('<br>')):
        if i:
            out.append('<br>')
        out.append(_render_block(block, sentence, lex, given, order, stats))
    return ''.join(out)


def _render_block(block, sentence, lex, given, order, stats):
    if not block:
        return ''
    try:
        toks = lex.tokenize(block)
    except Exception:
        return block
    res, pos = [], 0
    for tk in toks:
        b, e = tk.begin(), tk.end()
        if b > pos:                      # token 之间的空白/符号：照抄
            res.append(block[pos:b])
        surface = block[b:e]
        if KANJI.search(surface):
            reading, src = lex.lookup(surface, sentence=sentence, given=given, order=order)
            if reading:
                lex.note_hit(src)
                if stats is not None:
                    stats.setdefault(surface, (reading, src))
                res.append(pieces(surface, reading))
            else:
                res.append(surface)      # 无来源 → 原样，validate 会报未标 ruby
        else:
            res.append(surface)
        pos = e
    if pos < len(block):
        res.append(block[pos:])
    return ''.join(res)


def validate(sentence, html):
    """结构校验：直接复用 check_cards（唯一一份规则实现）。"""
    hard, soft = CC.check({'sentence': sentence, 'AINote': 'x', 'SentenceHTML': html})
    # check_cards 只在 AINote 非空时才查 HTML；上面用 'x' 绕过它的"未处理"分支
    return [h for h in hard if '缺少段落' not in h and '<p>' not in h], soft


def reading_conflicts(sentence, html, lex: Lexicon):
    """把已给的 ruby 与**独立来源**逐个对照。

    返回两个清单（都是「不自动改、只报告」）：
      * `conflict`：人工例外表 / 字幕注音 / 本 deck 说要读 X，卡里是 Y —— 权威来源，应当改。
      * `review`  ：只有 Sudachi 一家有意见（多音词：私 わたくし/わたし、前世 ぜんせ/ぜんせい）
                    —— 词典不一定对，需要强模型/人裁决，或写进人工例外表。
      * `unknown` ：四个来源都盖不到的基底（真盲区）。
    """
    plain = strip_text(sentence)
    conflict, review, unknown = [], [], []
    for base, reading in RUBY.findall(html or ''):
        b = TAG.sub('', base)
        if len(b) < 2 or not KANJI.search(b) or b not in plain:
            continue
        want, src = lex.lookup(b, sentence=sentence,
                               order=(SRC_PINNED, SRC_ANNO, SRC_DECK, SRC_SUDACHI))
        if not want:
            unknown.append((b, reading))
        elif want != reading:
            (review if src == SRC_SUDACHI else conflict).append((b, reading, want, src))
    return conflict, review, unknown


def intra_conflicts(cards):
    """同一基底在本批里出现两种读法 —— 纯机械可查，错的那个必然在其中。

    实测（本集 116 张）：`姫様` 同时出现 `ひめさま` 与 `ひみま`；
    这类内部矛盾不需要任何语言知识就能发现，是「读音错读」信噪比最高的一条线索。
    """
    seen = {}
    for c in cards:
        for base, reading in RUBY.findall(c.get('SentenceHTML') or ''):
            b = TAG.sub('', base)
            if len(b) < 2 or not KANJI.search(b):
                continue
            seen.setdefault(b, {}).setdefault(reading, []).append(c.get('noteId'))
    return {b: v for b, v in seen.items() if len(v) > 1}


def fix_ainote_readings(ainote, sentence, lex: Lexicon):
    """把 AINote 里**权威来源已判定为错**的 ruby 读法就地换掉（纯字符串替换）。

    `check_cards` 管不到 AINote 的读音，`check_ruby` 只把它算提醒 ——
    于是错读会在讲解里长期存留（实测本集 AINote 里也有 `格好(ぎょうしょう)`）。
    只在「例外表/字幕注音/本 deck」有明确值时才改，Sudachi 一家的意见不动。
    """
    def rep(m):
        base, reading = TAG.sub('', m.group(1)), m.group(2)
        if len(base) < 1 or not KANJI.search(base):
            return m.group(0)
        want, src = lex.lookup(base, sentence=sentence,
                               order=(SRC_PINNED, SRC_ANNO, SRC_DECK))
        if want and src != SRC_SUDACHI and want != reading:
            return '<ruby>%s<rt>%s</rt></ruby>' % (m.group(1), want)
        return m.group(0)

    return RUBY.sub(rep, ainote or '')


def repair(sentence, html, lex: Lexicon, mode='structure'):
    """把一份 HTML 修成结构合格。

    mode='structure'：保留原 HTML 里已给的读法（模型/前任的语义贡献），只补缺的 ruby、
                      并把文本骨架换回原始 Sentence（字符漂移从此不可能发生）。
    mode='fix'      ：连同读音一起以词典/注音为准重渲染（人工例外表优先级最高）。

    返回 (new_html, info)；`info` 里含 changes / unresolved / conflicts。
    """
    problems = validate(sentence, html)[0]
    given = given_readings(html, sentence)
    order = ((SRC_GIVEN, SRC_PINNED, SRC_ANNO, SRC_DECK, SRC_SUDACHI) if mode == 'structure'
             else (SRC_PINNED, SRC_ANNO, SRC_DECK, SRC_GIVEN, SRC_SUDACHI))
    conflict, review, unknown = reading_conflicts(sentence, html, lex)
    if not problems and mode == 'structure':
        # 已经合格的卡**一个字都不动** —— 重渲染只会把 ruby 粒度换来换去（政略結婚 → 政略+結婚），
        # 那是无意义的 churn，也会让「修了多少张」这个数字失去意义。
        new = html
    elif not problems and not conflict:
        # fix 模式但没有权威冲突（例外表/字幕注音/本 deck 都说卡里是对的）→ 同样不动
        new = html
    else:
        new = render(sentence, lex, given=given, order=order)
    left = validate(sentence, new)[0]
    info = {
        'problems_before': problems,
        'problems_after': left,
        'changed': new != (html or ''),
        'conflict': conflict,          # 权威来源（例外表/字幕注音/本 deck）说要改
        'review': review,              # 只有 Sudachi 一家有意见 → 交强模型/人
        'unknown': unknown,            # 四个来源都盖不到
        'bare_kanji': bare_kanji(new),  # 修完仍未标 ruby 的汉字串
    }
    return new, info


def bare_kanji(html):
    """HTML 里仍未标 ruby 的汉字串。"""
    return [''.join(m) for m in
            re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]+', CC.outside_ruby(html or ''))]


# ============================================================================
# 取卡
# ============================================================================
def cards_from_query(query):
    out = []
    for n in AK.notes_info(AK.find_notes(query)):
        f = AK.field_values(n)
        out.append({'noteId': int(n['noteId']),
                    'sentence': f.get('Sentence', ''),
                    'AINote': f.get('AINote', ''),
                    'SentenceHTML': f.get('Sentence HTML', '')})
    return out


def cards_from_gen(gen_dir):
    out = []
    for p in sorted(glob.glob(os.path.join(gen_dir, 'output_*.json'))):
        for c in json.load(open(p, encoding='utf-8')):
            c = dict(c)
            c.setdefault('SentenceHTML', c.get('SentenceHTML') or c.get('Sentence HTML') or '')
            c['_file'] = p
            out.append(c)
    return out


# ============================================================================
# 子命令
# ============================================================================
def _lexicon(a, cards):
    return Lexicon.build(query=getattr(a, 'lexicon', None) or DEFAULT_DECK,
                         exclude_ids=[c.get('noteId') for c in cards if c.get('noteId')],
                         srt=getattr(a, 'srt', None), plan=getattr(a, 'plan', None),
                         pinned_path=getattr(a, 'pinned', None) or PINNED,
                         use_deck=not getattr(a, 'no_deck_lexicon', False))


def cmd_check(a):
    cards = cards_from_query(a.query) if a.query else cards_from_gen(a.gen)
    print('范围：%s   共 %d 张' % (a.query or a.gen, len(cards)))
    lex = _lexicon(a, cards)
    n_bad = n_fixable = 0
    conflict, review, unknown = [], [], []
    for c in cards:
        sent, html = c.get('sentence') or '', c.get('SentenceHTML') or ''
        hard, _soft = validate(sent, html)
        if hard:
            n_bad += 1
            print('  ✗ noteId %s  %s' % (c.get('noteId'), '；'.join(hard)[:150]))
        _new, info = repair(sent, html, lex, mode='structure')
        if info['changed']:
            n_fixable += 1
        for row in info['conflict']:
            conflict.append((c.get('noteId'),) + row)
        for row in info['review']:
            review.append((c.get('noteId'),) + row)
        for row in info['unknown']:
            unknown.append((c.get('noteId'),) + row)
    print()
    print('结构不合格 %d 张（可确定性修复 %d 张）｜ 读音冲突 %d 处 ｜ 待复核 %d 处 ｜ 无来源 %d 处'
          % (n_bad, n_fixable, len(conflict), len(review), len(unknown)))
    intra = intra_conflicts(cards)
    if intra:
        print('  ✗ 本批内部自相矛盾（同一个词两种读法，必有一错）%d 个：' % len(intra))
        for b, readings in sorted(intra.items()):
            print('      %s：%s' % (b, ' ／ '.join(
                '%s（%d 张）' % (r, len(ids)) for r, ids in readings.items())))
    if conflict:
        print('  ✗ 权威来源（人工例外表/字幕注音/本 deck）与卡里不一致 —— 应当改：')
        for nid, b, got, want, src in conflict[:20]:
            print('      noteId %s：%s 卡里 %s，%s %s' % (nid, b, got, src, want))
    if review:
        print('  ⚠ 只有 Sudachi 一家有意见（多音词，词典不一定对）—— 交强模型/人过一次：')
        for nid, b, got, want, _src in review[:40]:
            print('      noteId %s：%s 卡里 %s，sudachi %s' % (nid, b, got, want))
    if unknown:
        print('  ⚠ 四个来源都盖不到（真盲区）：%s'
              % '、'.join('%s→%s' % (b, r) for _n, b, r in unknown[:20]))
    print('来源命中：%s' % ('、'.join('%s %d' % (k, v) for k, v in sorted(lex.hits.items())) or '—'))
    return 1 if n_bad else 0


def cmd_repair(a):
    cards = cards_from_gen(a.gen)
    print('范围：%s   共 %d 张' % (a.gen, len(cards)))
    lex = _lexicon(a, cards)
    by_file, changed, still, conflict, review, unknown = {}, [], [], [], [], []
    for c in cards:
        sent, html = c.get('sentence') or '', c.get('SentenceHTML') or ''
        new, info = repair(sent, html, lex, mode=a.mode)
        c['SentenceHTML'] = new
        by_file.setdefault(c['_file'], []).append({k: v for k, v in c.items() if not k.startswith('_')})
        if info['changed']:
            changed.append(c.get('noteId'))
        if info['problems_after']:
            still.append((c.get('noteId'), info['problems_after']))
        conflict += [(c.get('noteId'),) + t for t in info['conflict']]
        review += [(c.get('noteId'),) + t for t in info['review']]
        unknown += [(c.get('noteId'),) + t for t in info['unknown']]
    print('可确定性修复 %d 张；修后仍不合格 %d 张' % (len(changed), len(still)))
    for nid, probs in still[:10]:
        print('  ✗ noteId %s  %s' % (nid, '；'.join(probs)[:150]))
    print('读音冲突 %d 处；待复核（仅 sudachi）%d 处；无来源 %d 处'
          % (len(conflict), len(review), len(unknown)))
    for nid, b, got, want, src in conflict[:20]:
        print('  ✗ noteId %s：%s 卡里 %s，%s %s' % (nid, b, got, src, want))
    for nid, b, got, want, _s in review[:40]:
        print('  ⚠ noteId %s：%s 卡里 %s，sudachi %s' % (nid, b, got, want))
    if not a.write:
        print('演练：未写回。加 --write 把修复结果写进 output_*.json')
        return 0
    for path, rows in by_file.items():
        json.dump(rows, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('已写回 %d 个产出文件' % len(by_file))
    return 1 if still else 0


def cmd_apply(a):
    cards = cards_from_query(a.query)
    print('范围：%s   共 %d 张' % (a.query, len(cards)))
    lex = _lexicon(a, cards)
    todo = []
    for c in cards:
        sent, html = c.get('sentence') or '', c.get('SentenceHTML') or ''
        new, info = repair(sent, html, lex, mode=a.mode)
        fields = {}
        if info['changed']:
            fields['Sentence HTML'] = new
        if a.fix_ainote:
            fixed_an = fix_ainote_readings(c.get('AINote') or '', sent, lex)
            if fixed_an != (c.get('AINote') or ''):
                fields['AINote'] = fixed_an
        if fields:
            todo.append((c, fields, info))
    print('需要更新 %d 张（其余一个字都不动）' % len(todo))
    for c, fields, info in todo[:20]:
        why = info['problems_before'] or ['读音按权威来源改正']
        print('  · noteId %s  %s  →  %s' % (c['noteId'], '；'.join(why)[:80],
                                             '、'.join(fields)))
    if not todo:
        return 0
    if not a.commit:
        print('演练：未写库。加 --commit 真写（只写上面列出的字段）')
        return 0
    # 写前留回退依据（字段级）
    # ★ 文件名必须唯一到「同一秒内的两次运行也不撞」：2026-10-13 连着修两集的卡时，
    #   两次 apply 落在同一秒 → 第二份 revert 直接覆盖第一份，第一集的回退依据就没了。
    stamp = __import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')
    revert = os.path.join(WSP.DATA, 'ruby', 'revert_%s.json' % stamp)
    seq = 1
    while os.path.exists(revert):
        seq += 1
        revert = os.path.join(WSP.DATA, 'ruby', 'revert_%s-%d.json' % (stamp, seq))
    os.makedirs(os.path.dirname(revert), exist_ok=True)
    with open(revert, 'w', encoding='utf-8') as fh:
        json.dump({'created': stamp, 'query': a.query,
                   'cards': [{'noteId': c['noteId'],
                              'Sentence HTML': c.get('SentenceHTML') or '',
                              'AINote': c.get('AINote') or ''} for c, _f, _i in todo]},
                  fh, ensure_ascii=False, indent=1)
    print('回退依据：%s' % os.path.relpath(revert, WSP.ROOT))
    for c, fields, _info in todo:
        AK.update_note_fields(c['noteId'], fields)
    back = AK.notes_map([c['noteId'] for c, _f, _i in todo])
    bad = []
    for c, fields, _info in todo:
        got = AK.field_values(back[c['noteId']])
        for k, v in fields.items():
            if got.get(k, '') != v:
                bad.append((c['noteId'], k))
    print('已更新 %d 张；回读不一致 %d 处' % (len(todo), len(bad)))
    for nid, k in bad[:10]:
        print('   ✗ noteId %s %s' % (nid, k))
    return 1 if bad else 0


def cmd_render(a):
    lex = Lexicon.build(query=DEFAULT_DECK, use_deck=not a.no_deck_lexicon,
                        pinned_path=a.pinned or PINNED, srt=a.srt, plan=a.plan)
    stats = {}
    out = render(a.sentence, lex, stats=stats)
    print(out)
    print()
    for b, (r, s) in sorted(stats.items()):
        print('  %s = %s   (%s)' % (b, r, s))
    hard, _soft = validate(a.sentence, out)
    print('结构校验：%s' % ('通过 ✅' if not hard else '不合格 → ' + '；'.join(hard)))
    return 1 if hard else 0


def main():
    ap = argparse.ArgumentParser(description='确定性振假名引擎（结构问题不进 LLM）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    common = dict()
    p = sub.add_parser('check', help='只读体检：结构不合格 + 读音冲突 + 盲区清单')
    p.add_argument('--query', help='Anki 查询（与 --gen 二选一）')
    p.add_argument('--gen', default=os.path.join(WSP.DATA_PIPELINE, 'gen'),
                   help='阶段二工作目录（读 output_*.json）')
    p.add_argument('--srt', help='筛选后的 SRT（字幕自带注音，权威读音来源）')
    p.add_argument('--plan', help='filter_subtitle.py 的 plan.json（自动取它的 output）')
    p.add_argument('--lexicon', default=DEFAULT_DECK, help='本 deck 读音词典的查询')
    p.add_argument('--no-deck-lexicon', action='store_true')
    p.add_argument('--pinned', help='人工例外表路径（默认 %s）' % os.path.relpath(PINNED, WSP.ROOT))
    p.set_defaults(func=cmd_check)

    p = sub.add_parser('repair', help='修阶段二产出（原文骨架 + 已给 ruby）')
    p.add_argument('--gen', default=os.path.join(WSP.DATA_PIPELINE, 'gen'))
    p.add_argument('--mode', choices=['structure', 'fix'], default='structure')
    p.add_argument('--write', action='store_true', help='写回 output_*.json（不加则演练）')
    p.add_argument('--srt', help='筛选后的 SRT')
    p.add_argument('--plan', help='filter_subtitle.py 的 plan.json')
    p.add_argument('--lexicon', default=DEFAULT_DECK)
    p.add_argument('--no-deck-lexicon', action='store_true')
    p.add_argument('--pinned')
    p.set_defaults(func=cmd_repair)

    p = sub.add_parser('apply', help='把修复结果写回库里卡的 Sentence HTML（默认演练）')
    p.add_argument('--query', required=True)
    p.add_argument('--mode', choices=['structure', 'fix'], default='structure')
    p.add_argument('--fix-ainote', action='store_true',
                   help='连 AINote 里的错读也一起改（只用权威来源的值，Sudachi 一家的意见不动）')
    p.add_argument('--commit', action='store_true')
    p.add_argument('--srt')
    p.add_argument('--plan')
    p.add_argument('--lexicon', default=DEFAULT_DECK)
    p.add_argument('--no-deck-lexicon', action='store_true')
    p.add_argument('--pinned')
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser('render', help='单独渲染一条（调试用）')
    p.add_argument('--sentence', required=True)
    p.add_argument('--srt'), p.add_argument('--plan'), p.add_argument('--pinned')
    p.add_argument('--no-deck-lexicon', action='store_true')
    p.set_defaults(func=cmd_render)

    a = ap.parse_args()
    with AK.guard():
        return a.func(a)


if __name__ == '__main__':
    raise SystemExit(main())
