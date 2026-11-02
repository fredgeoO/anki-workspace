# -*- coding: utf-8 -*-
"""卡组外新词的「筛选 + 排序」：复用 today-new 那一套既有代码，不新增判断规则。

为什么要有它
------------
覆盖率的 ``oov`` 桶只按 Sudachi 词性粗分（名詞/動詞/形容詞/副詞…），于是
``の`` ``ぞ`` ``すっ`` ``ふい`` 这类切分碎片和语气词会一起漏进「新词」表。
``jp-anki-today-new`` 早就有这道闸（``subtitle_new_words.is_content_token``，
挡单字非汉字、代名詞/数詞、助動詞語干、こそあど），排序也早就有了
（``rank_gate``，一集一次读整集台词精排）。

本模块**不改**两条既有链路，只是把它们的既有能力接到覆盖率这一侧：

* 分词 / 内容词闸：``subtitle_new_words``（Sudachi **C** 粒度，与 today-new 同口径）
* 精排：``rank_gate.ask``（模型名次 + 一句中文理由，缓存与 today-new 共用）
* 词表：``data/vocab_cover/vocab_state.json``（离线，不需要 Anki 开着）

因此「卡组里有没有这个词」仍按覆盖率同一套 ``_norm.norm_word`` 判定，
统计口径与覆盖率报告完全一致，只有「候选粒度」换成 today-new 的 C 粒度。

对外接口::

    res = collect(sentences, vocab)      # -> {'items','proper','dropped','non_jp'}
    picks, meta = rank(res['items'], text, k=30)   # 需要本地模型端点
    print(render(res, picks, meta))
"""
from __future__ import annotations

import collections
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.join(os.path.dirname(os.path.dirname(_HERE)), 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from _norm import norm_word  # noqa: E402  与覆盖率同一套归一化

import subtitle_new_words as SW  # noqa: E402  分词 + 内容词闸（本模块不重写规则）

_JP = re.compile(r'[\u3041-\u3096\u30a1-\u30fa\u4e00-\u9fff\u3400-\u4dbf]')


def collect(sentences, vocab, drop_aux=True):
    """逐句分词 → 卡组外、过内容词闸的候选词。

    :param sentences: 句子列表（``analyze.sentences_of`` 的产物）
    :param vocab: ``jp_tok.Vocabulary``（用 ``.words`` 判断在不在卡组里）
    :param drop_aux: 挡掉 ``動詞-非自立可能``（おく/つく/なれる 这类补助动词）。
                     默认 True **只在本模块生效**，today-new 的候选集不受影响。
    """
    deck = vocab.words
    items = {}
    proper = collections.Counter()
    dropped = collections.Counter()
    non_jp = collections.Counter()
    first_seen = {}

    for sentence in sentences:
        for t in SW.tokenize(sentence):
            base = SW.norm(t.base)
            if not base:
                continue
            # 与 jp_tok.match 同口径：词典形 / 归一形 / 表记 三个键都查一次，
            # 否则 `1人`(归一形=一人)、`いう`(归一形=言う) 会被误判成卡组外。
            keys = (base, SW.norm(t.norm_form), SW.norm(t.surface))
            if any(k and norm_word(k) in deck for k in keys):
                continue                      # 卡组里有 → 不是新词（口径同覆盖率）
            if not _JP.search(base):
                non_jp[base] += 1             # 纯拉丁/数字（画面水印文字）
                continue
            if t.pos1 == '固有名詞':
                proper[base] += 1
                continue
            if not SW.is_content_token(t, drop_aux=drop_aux):
                dropped[base] += 1
                continue
            rec = items.get(base)
            if rec is None:
                rec = items[base] = {
                    'word': base,
                    'reading': SW.word_reading(base) or t.reading,
                    'pos': ('%s-%s' % (t.pos0, t.pos1) if t.pos1 else t.pos0),
                    'occurrences': 0,
                    'jiten': None,
                    'first': None,
                }
            rec['occurrences'] += 1
            if rec['first'] is None:
                rec['first'] = {'text': sentence}
                first_seen[base] = sentence

    rows = sorted(items.values(), key=lambda r: (-r['occurrences'], r['word']))
    return {
        'items': rows,
        'proper': proper.most_common(),
        'dropped': dropped.most_common(),
        'non_jp': non_jp.most_common(),
    }


def rank(items, text, k=30, cfg=None, quiet=True):
    """整集精排（复用 ``rank_gate``）。模型不可用时返回空表，由调用方按次数兜底。"""
    if not items:
        return [], {'calls': 0, 'candidates': 0, 'returned': 0}
    try:
        import rank_gate as RG
    except Exception as exc:                                  # pragma: no cover
        return [], {'calls': 0, 'problems': ['rank_gate 不可用：%s' % exc]}
    cfg = RG.load_cfg(cfg)
    picks, meta = RG.ask(items, text, cfg, k=min(int(k), len(items)), quiet=quiet)
    return picks, meta


def ordered(items, picks):
    """模型名次在前，未入选的按出现次数跟在后面。"""
    by_word = {it['word']: it for it in items}
    out, seen = [], set()
    for it, why in picks:
        out.append((by_word.get(it['word'], it), why))
        seen.add(it['word'])
    for it in items:
        if it['word'] not in seen:
            out.append((it, ''))
    return out


def render(res, picks=None, meta=None, top=25):
    """人读的报告段。"""
    items = res['items']
    lines = []
    lines.append('  ── 卡组外新词（内容词闸 + 整集精排）──')
    lines.append('  候选 %d 个内容词 ｜ 被内容词闸挡掉 %d 种 ｜ 专名 %d 种 ｜ 非日语 %d 种'
                 % (len(items), len(res['dropped']), len(res['proper']),
                    len(res['non_jp'])))
    if not items:
        lines.append('  （没有卡组外的内容词）')
        return '\n'.join(lines)

    meta = meta or {}
    rows = ordered(items, picks or [])
    if picks:
        lines.append('  排序：LLM 精排（%d 候选 → 给回 %d，模型 %s，%.1fs）'
                     % (meta.get('candidates', 0), len(picks),
                        meta.get('model', '') or '?', meta.get('secs', 0) or 0))
    else:
        lines.append('  排序：按出现次数（未调模型 / 模型无结果）')
        for p in (meta.get('problems') or [])[:3]:
            lines.append('    problems: %s' % p)

    lines.append('  名次  词 / 读音 / 词性 / 次数 / 模型理由')
    for n, (it, why) in enumerate(rows[:top], 1):
        lines.append('  %3d  %s / %s / %s / %d次%s'
                     % (n, it['word'], it['reading'] or '—', it['pos'],
                        it['occurrences'], (' ｜ ' + why) if why else ''))
    rest = len(rows) - top
    if rest > 0:
        lines.append('  ……另有 %d 个未列出（--top 调大 / --screen-out 导全表）' % rest)
    if res['dropped']:
        lines.append('  闸挡掉（前 12）：%s'
                     % ' '.join('%s×%d' % (w, n) for w, n in res['dropped'][:12]))
    if res['proper']:
        lines.append('  专名（前 12）：%s'
                     % ' '.join('%s×%d' % (w, n) for w, n in res['proper'][:12]))
    return '\n'.join(lines)


def to_json(res, picks=None, meta=None, ex_limit=120):
    """机器可读产物（``--screen-out``）。"""
    meta = meta or {}
    rows = ordered(res['items'], picks or [])
    return {
        'candidates': len(res['items']),
        'ranked_by': ('llm' if picks else 'occurrences'),
        'model': meta.get('model', ''),
        'secs': meta.get('secs', 0),
        'words': [{'word': it['word'], 'reading': it['reading'], 'pos': it['pos'],
                   'occurrences': it['occurrences'],
                   'why': why,
                   'first': ((it.get('first') or {}).get('text') or '')[:ex_limit]}
                  for it, why in rows],
        'dropped_nontent': res['dropped'],
        'proper': res['proper'],
        'non_jp': res['non_jp'],
    }
