# -*- coding: utf-8 -*-
"""单篇文本 / 单集字幕的分析与渲染：CLI 与报告共用这一份实现。

口径
----
* **含语法词口径**（分母 = 全部词元）：满足「不排除助词等语法词」的要求，
  语法词（助詞/助動詞/接頭辞/接尾辞）按「已知」处理 —— 它们不属于要背的词汇，
  且你有 N5–N1 语法卡组 3160 张。
* **词汇词口径**（分母 = 去掉语法词与符号）：真正的词汇量视角。
* **正向覆盖率**：这段文字里的词有多少落在我卡组里 / 我已学 / 我已成熟。
* **反向触达率**：我的卡组里有多少词在这段文字里出现过（学习收益视角）。
* **理解度**：覆盖率经验映射（粗估）+ 句子级实测（整句无生词 / ≤1 个生词）。
"""
from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _deps import add_pylibs  # noqa: E402

add_pylibs()

import jp_tok  # noqa: E402
from jp_tok import Coverage, coverage_to_comprehension  # noqa: E402

SENT_SPLIT = re.compile(r'(?<=[。．.!?！？…‥])')
LINE_SPLIT = re.compile(r'[\r\n]+')


def sentences_of(text: str, is_srt: bool = False):
    """切成句子。SRT 走字幕解析（一条字幕 = 一句），纯文本按行 + 句末标点切。"""
    if is_srt:
        import srt as _srt
        ep = _srt.parse_srt_text(text)
        return ep.sentences(), ' '.join(ep.utterances), ep
    out = []
    for line in LINE_SPLIT.split(text):
        line = line.strip()
        if not line:
            continue
        for piece in SENT_SPLIT.split(line):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out, text, None


def analyze_text(vocab: 'jp_tok.Vocabulary', text: str, sentences=None,
                 decompose_oov: bool = True, label: str = '') -> dict:
    """一段文本的完整分析结果（dict，可直接 json 化）。"""
    toks = vocab.tokenize(text, decompose_oov=decompose_oov)
    cov = Coverage(vocab, toks, sentences=sentences)
    s = cov.summary()

    # 反向触达：卡组里有多少词在这段文字里出现过
    reach = {}
    for bucket, deck_key in (('core6000', 'core'), ('jlpt', 'jlpt')):
        total = sum(1 for e in vocab.words.values() if e.get(deck_key))
        seen = cov._uniq(bucket)
        seen_known = {t.key for t in cov.groups().get(bucket, []) if t.known}
        reach[bucket] = {
            'deck_total': total, 'seen': len(seen),
            'seen_ratio': len(seen) / total if total else 0,
            'seen_known': len(seen_known), 'new_to_me': len(seen - seen_known),
        }
    deck_total = sum(1 for e in vocab.words.values()
                     if e.get('core') or e.get('jlpt') or e.get('mined'))
    seen_all = set().union(*[cov._uniq(b) for b in jp_tok.DECK_BUCKETS])
    reach['deck'] = {'deck_total': deck_total, 'seen': len(seen_all),
                     'seen_ratio': len(seen_all) / deck_total if deck_total else 0}

    ca, cv, cl = s['cover_all'], s['cover_vocab'], s['cover_learnable']
    return {
        'label': label,
        'chars': sum(1 for c in text if not c.isspace()),
        'tokens': s['tokens']['all'],
        'tokens_vocab': s['tokens']['vocab'],
        'tokens_learnable': s['tokens']['learnable'],
        'tokens_grammar': s['tokens']['grammar'],
        'tokens_symbol': s['tokens']['symbol'],
        'types': s['types']['all'],
        'types_vocab': s['types']['vocab'],
        'buckets': s['buckets'],
        'type_buckets': s['types']['buckets'],
        'cover_all': ca,
        'cover_vocab': cv,
        'cover_learnable': cl,
        'reach': reach,
        'oov': s['oov'],
        'untackled': s['untackled'],
        'sentences': s['sentences'],
        'comprehension': {
            # 主推：宽口径（语法词/感动词/数词算懂），分别按「已学」和「已成熟」算
            'by_understood': coverage_to_comprehension(ca.get('understood_lenient', 0)),
            'by_understood_mature': coverage_to_comprehension(ca.get('understood_mature', 0)),
            'by_understood_listening': coverage_to_comprehension(ca.get('understood_lenient', 0),
                                                                 listening=True),
            'by_understood_mature_listening':
                coverage_to_comprehension(ca.get('understood_mature', 0), listening=True),
            # 严格口径：感动词/专有名词也算不懂
            'by_strict': coverage_to_comprehension(ca.get('understood', 0)),
            # 词汇词口径（分母不含语法词）
            'by_vocab_known': coverage_to_comprehension(cv.get('known', 0)),
            'by_vocab_mature': coverage_to_comprehension(cv.get('mature', 0)),
        },
    }


# ------------------------------------------------------------------ 文本渲染
def pct(x, nd=1):
    return f'{x*100:.{nd}f}%'


def _w(text: str) -> int:
    """显示宽度：CJK 全角字符按 2 列算。"""
    return sum(2 if ('\u1100' <= c <= '\u115f' or '\u2e80' <= c <= '\ua4cf'
                     or '\uac00' <= c <= '\ud7a3' or '\uf900' <= c <= '\ufaff'
                     or '\ufe30' <= c <= '\ufe6f' or '\uff00' <= c <= '\uff60'
                     or '\uffe0' <= c <= '\uffe6') else 1 for c in text)


def pad(text: str, width: int, align: str = 'left') -> str:
    space = ' ' * max(0, width - _w(text))
    return text + space if align == 'left' else space + text


def render(res: dict, top: int = 25, show_lists: bool = True) -> str:
    ca, cv = res['cover_all'], res['cover_vocab']
    cl = res.get('cover_learnable', {})
    r = res['reach']
    L = []
    L.append(f'■ {res["label"] or "（未命名文本）"}')
    L.append(f'  规模：{res["chars"]} 字 · 词元 {res["tokens"]}'
             f'（词汇词 {res["tokens_vocab"]} + 语法词 {res["tokens_grammar"]}；'
             f'另有符号 {res["tokens_symbol"]} 个不计）'
             f' · 词种 {res["types"]}（词汇词 {res["types_vocab"]}）')
    L.append('  词元构成：' + '  '.join(
        f'{k}={res["buckets"].get(k, 0)}' for k in
        ('core6000', 'jlpt', 'mined', 'oov', 'proper', 'interj', 'numeral', 'grammar')))
    L.append('')
    L.append('  ── 正向覆盖率 ──')
    L.append('  ' + pad('口径', 22) + pad('含语法词', 11, 'right')
             + pad('词汇词', 11, 'right') + pad('需背实词', 11, 'right'))
    rows = [
        ('core6000 命中', ca.get('core', 0), cv.get('core', 0), cl.get('core', 0)),
        ('core6000+考级', ca.get('corejlpt', 0), cv.get('corejlpt', 0),
         cl.get('corejlpt', 0)),
        ('我的全部卡组', ca.get('deck', 0), cv.get('deck', 0), cl.get('deck', 0)),
        ('我已学（刷卡≥1）', ca.get('known', 0), cv.get('known', 0), cl.get('known', 0)),
        ('我已成熟（≥21天）', ca.get('mature', 0), cv.get('mature', 0), cl.get('mature', 0)),
        ('★我实际能懂（宽口径）', ca.get('understood_lenient', 0),
         cv.get('understood_lenient', 0), cl.get('understood_lenient', 0)),
        ('★严格口径能懂', ca.get('understood', 0), cv.get('understood', 0),
         cl.get('understood', 0)),
        ('完全在卡组之外（新词）', ca.get('oov', 0), cv.get('oov', 0), cl.get('oov', 0)),
        ('专有名词（卡组外）', ca.get('proper', 0), cv.get('proper', 0),
         cl.get('proper', 0)),
        ('语法词（助词/助动词等）', ca.get('grammar', 0), 0.0, 0.0),
    ]
    for name, a, b, c in rows:
        L.append('  ' + pad(name, 22) + pad(pct(a), 11, 'right')
                 + pad(pct(b), 11, 'right') + pad(pct(c), 11, 'right'))
    L.append('')
    L.append('  ── 反向触达率：看这段内容能碰到卡组里多少词 ──')
    for key, name in (('core6000', 'core6000'), ('jlpt', '考级词汇'), ('deck', '全部词汇卡')):
        d = r.get(key)
        if not d:
            continue
        if key == 'deck':
            L.append(f'  {name:<10} 卡组 {d["deck_total"]:>5} 词，本段出现 {d["seen"]:>4}'
                     f'（{pct(d["seen_ratio"])}）')
        else:
            L.append(f'  {name:<10} 卡组 {d["deck_total"]:>5} 词，本段出现 {d["seen"]:>4}'
                     f'（{pct(d["seen_ratio"])}），其中我还没学 {d["new_to_me"]:>4}')
    L.append('')
    L.append('  ── 新词与待学 ──')
    L.append(f'  完全不在卡组里的新词：{len(res["oov"])} 个词种'
             f'（占词汇词种 {pct(res["type_buckets"].get("oov", 0)/max(1,res["types_vocab"]))}）')
    L.append(f'  卡组里有卡但我没刷过：{len(res["untackled"])} 个词种')
    L.append('')
    L.append('  ── 理解度估计 ──')
    s = res['sentences']
    if s:
        L.append(f'  句子级实测（{s["sentences"]} 句）：整句无生词 {pct(s["full"], 0)}'
                 f'（宽口径 {pct(s["full_l"], 0)}）· ≤1 个生词 {pct(s["lenient_l"], 0)}')
    c = res['comprehension']
    L.append(f'  覆盖率经验映射（宽口径）：按已学 {pct(c["by_understood"])}'
             f' · 按已成熟 {pct(c["by_understood_mature"])}'
             f' · 严格口径 {pct(c["by_strict"])}')
    L.append(f'  换成无字幕听力（覆盖率折算 −3pt）：'
             f'按已学 {pct(c["by_understood_listening"])}'
             f' · 按已成熟 {pct(c["by_understood_mature_listening"])}')
    L.append(f'  最保守口径（只看词汇词、只算已成熟）：{pct(c["by_vocab_mature"])}')
    if show_lists and res['oov']:
        L.append('')
        L.append(f'  ── 新词（不在任何卡组，前 {min(top, len(res["oov"]))} 个，按出现次数）──')
        for i in range(0, min(top, len(res['oov'])), 6):
            L.append('  ' + '  '.join(f'{w}×{n}' for w, n, _p in res['oov'][i:i + 6]))
    if show_lists and res['untackled']:
        L.append('')
        L.append(f'  ── 卡组里有卡但没刷过（前 {min(top, len(res["untackled"]))} 个）──')
        for i in range(0, min(top, len(res['untackled'])), 6):
            L.append('  ' + '  '.join(f'{w}[{b[:4]}]×{n}'
                                      for w, b, n in res['untackled'][i:i + 6]))
    return '\n'.join(L)
