# -*- coding: utf-8 -*-
"""卡组 × JitenAnimeRank 贴合度：我这些词条，能盖住「动漫通用词频榜」的哪一段？

和 `metrics.py` 的 `deck_reach`（我的卡组里有多少词在你那 72 集里出现过）刚好相反，
这里问的是**榜单方向**：

1. **榜 → 卡组**：JitenAnimeRank 前 N 个最常用的动漫词里，有多少 % 已经在卡组里
   （core6000 / 考级词汇 / 素材生词，去重）；
2. **卡组 → 榜**：卡组里的词在榜上的名次分布（中位数、四分位）——名次越靠后，
   说明这套卡组越不贴合「动漫常用词」；
3. **缺口成分**：没覆盖到的词里，多少是语法词/感动词/专有名词/数词（本来就不用背），
   多少是真的该补的实词（`oov`）；并按「有没有在你那 72 集字幕里出现过」标注优先级；
4. **该补清单**：缺口里的实词按榜上名次排序落成 TSV，可以直接喂给挖词流程
   （`code/execution/mine.py` 的默认词表就是这张榜）。

用法
----
    python code\\analysis\\vocab_cover\\jiten_fit.py                      # 前 12093 名（默认=卡组规模）
    python code\\analysis\\vocab_cover\\jiten_fit.py --top 20000
    python code\\analysis\\vocab_cover\\jiten_fit.py --max-rank 50000      # 分类更多缺口（Sudachi 慢一点）
    python code\\analysis\\vocab_cover\\jiten_fit.py --report docs\\reports\\Jiten动漫词库贴合度.md

产物
----
    data/vocab_cover/jiten_fit.json      指标数字（可被别的脚本读）
    data/vocab_cover/jiten_gap.tsv       缺口实词清单（名次 / 词 / 是否在 72 集语料里出现过）
    docs/reports/Jiten动漫词库贴合度.md   人看的报告（--report 时）
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _deps                                    # noqa: E402

_deps.add_pylibs()

import textio                                   # noqa: E402
from _norm import norm_word                     # noqa: E402
from _deps import DATA_DIR, STATE_JSON, CORPUS_JSON, write_json  # noqa: E402

JITEN_JSON = os.path.join(DATA_DIR, 'study_plan_jiten_anime.json')
FIT_JSON = os.path.join(DATA_DIR, 'jiten_fit.json')
GAP_TSV = os.path.join(DATA_DIR, 'jiten_gap.tsv')

# 榜上覆盖率的检查点（名次位置）
CHECKPOINTS = (1000, 2000, 3000, 6000, 9000, 12093, 15000, 20000, 30000, 50000)
CAT_LABEL = {
    'deck_by_reading': '卡组里已有（假名/汉字写法不同，读音对得上）',
    'deck_other_form': '卡组里已有（词形归一后命中）',
    'deck_compound': '卡组里已有（复合词，构成它的实词都收着）',
    'oov': '卡组外实词',
    'grammar': '语法词（助词/助动词/接辞）',
    'grammar_pos': '语法词（接续词等）',
    'proper': '专有名词（人名地名）',
    'pronoun': '代名词（これ/きみ 这一类）',
    'interj': '感动词（语气词）',
    'numeral': '数词',
    'symbol': '符号',
    'non_jp': '非日语（拉丁字母等）',
}


# --------------------------------------------------------------------- 载入
def load_ranks(path: str = JITEN_JSON) -> list:
    """Jiten 榜 -> 按名次排好的 [(position, freq_rank, word, key)]。

    position 是「榜上第几个词」（1 起），freq_rank 是 Jiten CSV 里的 Rank 原始值
    （一个 rank 值可能对应多个词条，所以两者不相等）。
    """
    rows = textio.load_json(path, default=None)
    if not rows:
        raise SystemExit('缺 %s：先跑 freq_external.py build --media Anime' % path)
    rows = sorted(rows, key=lambda r: (r.get('freq_rank') or 0, r.get('word') or ''))
    out, seen = [], set()
    for r in rows:
        w = (r.get('word') or '').strip()
        k = norm_word(w)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append((len(out) + 1, r.get('freq_rank') or 0, w, k))
    return out


def deck_sets(state: dict) -> dict:
    """卡组 -> 几组查找键（每组都有「严 / 宽」两份）。

    * 严（如 `all`）：归一化后的**词形键**；
    * 宽（如 `all_loose`）：再加上卡组词条的**读音** —— 榜上是假名写法（はなす / こわい），
      卡组收的是汉字写法（話す / 恐い）时，只有读音能对上。Sudachi 不会把假名还原成
      汉字，所以少了这一步会严重低估「其实我有这张卡」。宽松口径会带进少量同音异义词。
    """
    words = state['words']
    base = {
        'all': set(words),
        'core6000': {k for k, v in words.items() if v.get('core')},
        'jlpt': {k for k, v in words.items() if v.get('jlpt')},
        'mined': {k for k, v in words.items() if v.get('mined')},
        'known': {k for k, v in words.items() if v.get('known')},
        'mature': {k for k, v in words.items() if v.get('mature')},
    }
    base['fixed'] = base['core6000'] | base['jlpt']
    read_of = {}
    for k, v in words.items():
        rk = {norm_word(r) for r in (v.get('readings') or [])}
        rk = {r for r in rk if r and r != k}
        if rk:
            read_of[k] = rk
    out = dict(base)
    for name, keys in base.items():
        extra = set()
        for k in keys:
            extra |= read_of.get(k, set())
        out[name + '_loose'] = keys | extra
    out['by_reading'] = out['all_loose'] - out['all']
    return out


# --------------------------------------------------------------------- 命中判定
def read_owner(state: dict) -> dict:
    """读音键 -> 拥有它的卡组词条键（同音取先出现的那个）。"""
    out = {}
    for k, v in state['words'].items():
        for r in (v.get('readings') or []):
            rk = norm_word(r)
            if rk and rk != k:
                out.setdefault(rk, k)
    return out


def pos_category(toks, no_need_pos) -> str:
    """没命中卡组时，按词性判断「要不要背」。"""
    if not toks:
        return 'non_jp'
    if any(t.bucket == 'proper' for t in toks):
        return 'proper'
    if any(t.bucket == 'numeral' for t in toks):
        return 'numeral'
    if any(t.bucket == 'interj' for t in toks):
        return 'interj'
    if any(t.bucket == 'symbol' for t in toks):
        return 'symbol'
    if any(t.bucket == 'non_jp' for t in toks):
        return 'non_jp'
    if any(t.bucket == 'grammar' for t in toks):
        return 'grammar'
    if all((t.pos1 == '代名詞' or t.pos2 == '代名詞') for t in toks):
        return 'pronoun'
    if all(t.pos1 in no_need_pos for t in toks):
        return 'grammar_pos'          # 单独查「が」这类会被标成接続詞
    if any(t.bucket == 'oov' for t in toks):
        return 'oov'
    return 'grammar_pos'


def match_form(t, deck: dict) -> str:
    """词形路径：归一化 / 词典形 / 原形 有一个在卡组键里就算命中。"""
    for cand in (t.normalized, t.dictionary, t.surface):
        ck = norm_word(cand)
        if ck and ck in deck['all']:
            return ck
    return ''


def match_reading(t, deck: dict) -> str:
    """读音路径（只用于分词兜底）：读音键**本身就是卡组的词条**。

    典型场景：卡组收假名「できる」，榜上是汉字「出来る」。这里故意不去查
    「某词条的读音」，因为那会撞上大量同音异义词（榜「魔」↔ 卡「間」都是 ま）。
    """
    ck = norm_word(t.reading)
    if ck and ck in deck['all']:
        return ck
    return ''


def scan(ranks: list, deck: dict, owner: dict, limit: int, verbose=False) -> list:
    """逐词判定「卡组里到底有没有这张卡」—— 曲线和缺口分类共用这一遍。

    命中级别
    --------
    strict         词形键直接相等
    by_reading     榜上词的键 = 卡组某词条的**读音**（榜「はなす」↔ 卡「話す」）
    token_form     分词后归一化词形命中（榜「出来る」↔ 卡「できる」这类写法差异）
    token_reading  分词后读音命中
    token_all      复合词：构成它的实词卡组里都有（榜「何者」= 何 + 者）
    none           没有 —— 这时 `cat` 记录它的词性类别（要不要背）
    """
    from jp_tok import Vocabulary, GRAMMAR_POS1
    vocab = Vocabulary.load()
    no_need_pos = set(GRAMMAR_POS1) | {'接続詞', '記号', '補助記号', '空白'}
    recs = []
    for pos, rk, word, key in ranks:
        if pos > limit:
            break
        rec = {'pos': pos, 'freq_rank': rk, 'word': word, 'key': key,
               'level': 'none', 'hit_key': '', 'cat': ''}
        if key in deck['all']:
            rec.update(level='strict', hit_key=key)
        elif key in owner:
            rec.update(level='by_reading', hit_key=owner[key])
        else:
            toks = vocab.tokenize(word)
            content = [t for t in toks
                       if t.pos1 not in no_need_pos and t.bucket not in ('symbol',
                                                                        'non_jp')]
            forms = [(t, match_form(t, deck)) for t in content]
            reads = [(t, match_reading(t, deck)) for t in content]
            if content and all(h for _t, h in forms):
                # 单个词条：词形归一命中；多个词条：构成它的实词全都在卡组里
                rec.update(level='token_form' if len(toks) == 1 else 'token_all',
                           hit_key=forms[0][1])
            elif content and all(h for _t, h in reads):
                rec.update(level='token_reading', hit_key=reads[0][1])
            else:
                rec['cat'] = pos_category(toks, no_need_pos)
        recs.append(rec)
        if verbose and pos % 10000 == 0:
            print('  ..已判定 %s 个榜上词' % format(pos, ','), flush=True)
    return recs


def curve_from(recs: list, state: dict, checkpoints=CHECKPOINTS) -> dict:
    """前 N 个榜上词里，各卡组命中多少（按命中级别归到对应卡组）。"""
    words = state['words']
    want = sorted(set(int(c) for c in checkpoints if c > 0))
    names = ('all', 'all_loose', 'fixed_loose', 'core6000_loose', 'jlpt_loose',
             'mined_loose', 'known_loose', 'mature_loose')
    hits = {n: 0 for n in names}
    points, wi = [], 0
    for rec in recs:
        lv, hk = rec['level'], rec['hit_key']
        e = words.get(hk) or {}
        if lv == 'strict':
            hits['all'] += 1
        if lv != 'none':
            hits['all_loose'] += 1
            if e.get('core'):
                hits['core6000_loose'] += 1
            if e.get('jlpt'):
                hits['jlpt_loose'] += 1
            if e.get('core') or e.get('jlpt'):
                hits['fixed_loose'] += 1
            if e.get('mined'):
                hits['mined_loose'] += 1
            if e.get('known'):
                hits['known_loose'] += 1
            if e.get('mature'):
                hits['mature_loose'] += 1
        while wi < len(want) and rec['pos'] == want[wi]:
            points.append({'top': rec['pos'],
                           **{n: {'n': hits[n], 'ratio': hits[n] / rec['pos']}
                              for n in names}})
            wi += 1
    return {'points': points}


def deck_side(ranks: list, deck: dict) -> dict:
    """卡组 → 榜：我的词在榜上的名次分布。"""
    pos_of = {k: pos for pos, _rk, _w, k in ranks}
    res = {}
    for name in ('all', 'core6000', 'jlpt', 'mined'):
        keys = deck[name]
        in_table = [pos_of[k] for k in keys if k in pos_of]
        if not in_table:
            continue
        in_table.sort()
        n = len(in_table)

        def q(p):
            return in_table[min(n - 1, int(n * p))]
        res[name] = {
            'deck_words': len(keys),
            'in_table': n,
            'not_in_table': len(keys) - n,
            'median_pos': q(0.5), 'p25_pos': q(0.25), 'p75_pos': q(0.75),
            'p90_pos': q(0.90),
            'within_top_12093': sum(1 for p in in_table if p <= 12093),
            'within_top_12093_ratio': (sum(1 for p in in_table if p <= 12093) / n),
        }
    return res


# --------------------------------------------------------------------- 缺口成分
def gaps_from(recs: list, corpus_keys: set, max_rank: int) -> dict:
    """缺口成分 + 该补清单。

    「词形键没命中」里有两类其实卡组已经有：读音对得上、分词的词形对得上，
    它们分别记成 `deck_by_reading` / `deck_other_form`，不算缺口。
    """
    COVERED = {'by_reading': 'deck_by_reading', 'token_reading': 'deck_by_reading',
               'token_form': 'deck_other_form', 'token_all': 'deck_compound'}
    rows, counts = [], {}
    for rec in recs:
        if rec['pos'] > max_rank:
            break
        if rec['level'] == 'strict':
            continue                      # 词形键直接命中，不算缺口
        cat = COVERED.get(rec['level']) or rec['cat'] or 'oov'
        counts[cat] = counts.get(cat, 0) + 1
        if cat == 'oov':
            rows.append({'pos': rec['pos'], 'freq_rank': rec['freq_rank'],
                         'word': rec['word'],
                         'in_corpus72': rec['key'] in corpus_keys})
    extra = (counts.get('deck_other_form', 0) + counts.get('deck_by_reading', 0)
             + counts.get('deck_compound', 0))
    return {'counts': counts, 'gap_total': sum(counts.values()),
            'need_rows': rows, 'max_rank': max_rank,
            'need_total': len(rows), 'also_covered': extra,
            'need_in_corpus': sum(1 for r in rows if r['in_corpus72'])}


def corpus_keys() -> set:
    """72 集语料里出现过的全部词汇词键（没有语料文件就返回空集）。"""
    c = textio.load_json(CORPUS_JSON, default=None)
    if not c or not c.get('episodes'):
        return set()
    keys = set()
    for ep in c['episodes']:
        keys.update(ep.get('word_counts', {}))
    return keys


# --------------------------------------------------------------------- 渲染
def pct(x, digits=1):
    return ('%.' + str(digits) + 'f%%') % (100.0 * x)


def render_md(m: dict) -> str:
    L = []
    A = L.append
    top = m['top']
    d, curve, side = m['deck'], m['curve'], m['deck_side']
    first = curve['main']
    A('# 卡组 × JitenAnimeRank 贴合度')
    A('')
    A('> 生成时间 %s · 榜 `study_plan_jiten_anime.json`（%s 个词条，Jiten Anime 词频）'
      % (m['generated_at'], format(m['table_size'], ',')))
    A('> 卡组快照 %s · 去重词条 %s 个（core6000 %s / 考级词汇 %s / 素材生词 %s）'
      % (m['state_generated_at'], format(len(d['all']), ','),
         format(len(d['core6000']), ','), format(len(d['jlpt']), ','),
         format(len(d['mined']), ',')))
    A('')
    A('## 0. 一句话结论')
    A('')
    A('* 榜上**前 %s 个**最常用的动漫词里，你的卡组已经有 **%s**（%s 个）—— 按含读音的宽口径；'
      '只按词形严格算是 %s（%s 个），差额是假名↔汉字、分词写法差异。'
      % (format(top, ','), pct(first['all_loose']['ratio']),
         format(first['all_loose']['n'], ','), pct(first['all']['ratio']),
         format(first['all']['n'], ',')))
    A('* 其中**已学** %s、**已成熟** %s（都是宽口径）；只算两块固定词表'
      '（core6000 + 考级词汇）是 %s。'
      % (pct(first['known_loose']['ratio']), pct(first['mature_loose']['ratio']),
         pct(first['fixed_loose']['ratio'])))
    gap = m['gaps']
    A('* 前 %s 个里词形键没命中的 %s 个词条中，%s 个其实是「卡组里已经有这张卡」'
      '（假名↔汉字、或分词归一后命中）；真正缺的实词 **%s 个**，'
      '其中 %s 个在你那 72 集字幕里出现过 —— 这就是「core6000/考级词汇都不收、'
      '但动漫里很常用」的那批。'
      % (format(m['max_rank'], ','), format(gap['gap_total'], ','),
         format(gap['also_covered'], ','), format(gap['need_total'], ','),
         format(gap['need_in_corpus'], ',')))
    A('')
    A('## 1. 榜 → 卡组：前 N 个动漫词里我收了多少')
    A('')
    A('| 榜上前 N 个词 | 卡组已有（严：词形） | 卡组已有（宽：含读音） | core6000 | 考级词汇 | 素材生词 | 已学 | 已成熟 |')
    A('|---|---|---|---|---|---|---|---|')
    for p in curve['points']:
        A('| %s | %s | **%s** | %s | %s | %s | %s | %s |'
          % (format(p['top'], ','), pct(p['all']['ratio']), pct(p['all_loose']['ratio']),
             pct(p['core6000_loose']['ratio']),
             pct(p['jlpt_loose']['ratio']), pct(p['mined_loose']['ratio']),
             pct(p['known_loose']['ratio']), pct(p['mature_loose']['ratio'])))
    A('')
    A('> 除「严」这一列外，其余都是**宽口径**（词形键 ∪ 读音键）：榜上「はなす」对上卡组'
      '「話す」的读音就算命中。宽口径会带进少量同音异义词，偏乐观，真实值在严/宽之间。')
    A('> 「前 N 个词」= 按榜上名次顺序取的 N 个词条；Jiten CSV 的 Rank 原始值有并列，'
      '所以名次值 ≤ N 的词条数会多于 N（本榜 %s 个词条分布在 1..%s 名次值上）。'
      % (format(m['table_size'], ','), format(m['max_freq_rank'], ',')))
    A('')
    A('## 2. 卡组 → 榜：我的词在榜上排多靠前')
    A('')
    A('| 卡组 | 词条 | 在榜上 | 名次中位数 | 前 25% 名次 | 前 75% 名次 | 落在前 12093 名内 |')
    A('|---|---|---|---|---|---|---|')
    label = {'all': '去重合计', 'core6000': 'core6000', 'jlpt': '考级词汇',
             'mined': '素材生词'}
    for name in ('all', 'core6000', 'jlpt', 'mined'):
        s = side.get(name)
        if not s:
            continue
        A('| %s | %s | %s（%s） | %s | %s | %s | %s（%s） |'
          % (label[name], format(s['deck_words'], ','), format(s['in_table'], ','),
             pct(s['in_table'] / s['deck_words']), format(s['median_pos'], ','),
             format(s['p25_pos'], ','), format(s['p75_pos'], ','),
             format(s['within_top_12093'], ','), pct(s['within_top_12093_ratio'])))
    A('')
    A('> 「在榜上」= 这张榜里找得到该词条（找不到的多是专有名词、活用形或写法差异）。'
      '名次中位数越小越贴合动漫常用词。')
    A('')
    A('## 3. 缺口成分（前 %s 个榜上词）' % format(m['max_rank'], ','))
    A('')
    A('| 类型 | 词条 | 占比 | 要不要背 |')
    A('|---|---|---|---|')
    for b, n in sorted(gap['counts'].items(), key=lambda kv: -kv[1]):
        A('| %s | %s | %s | %s |'
          % (CAT_LABEL.get(b, b), format(n, ','), pct(n / max(1, gap['gap_total'])),
             '要（补卡组）' if b == 'oov' else
             ('不用（卡里已有）' if b == 'deck_other_form' else '不用')))
    A('')
    A('## 4. 该补清单（前 40 个，完整清单见 `data/vocab_cover/jiten_gap.tsv`）')
    A('')
    A('| 榜上位置 | Jiten 名次 | 词 | 72 集语料里出现过 |')
    A('|---|---|---|---|')
    for r in m.get('_need_rows', [])[:40]:
        A('| %s | %s | %s | %s |'
          % (format(r['pos'], ','), format(r['freq_rank'], ','), r['word'],
             '是' if r['in_corpus72'] else '否'))
    A('')
    A('> 排序 = 榜上名次，越靠前越常用。`in_corpus72=true` 的说明你看的字幕里已经出现过，'
      '挖词/做卡时优先。')
    A('')
    return '\n'.join(L) + '\n'


# --------------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description='卡组 × JitenAnimeRank 贴合度分析')
    ap.add_argument('--top', type=int, default=0,
                    help='主口径 N（默认 = 卡组去重词条数，即 12093 这种）')
    ap.add_argument('--max-rank', type=int, default=0,
                    help='缺口分类分析到第 N 个榜上词（默认 = 与 --top 相同）')
    ap.add_argument('--jiten', default=JITEN_JSON, help='Jiten 榜 json')
    ap.add_argument('--report', default='', help='额外写一份 Markdown 到该路径')
    ap.add_argument('--gap-out', default=GAP_TSV, help='缺口 TSV 输出路径')
    ap.add_argument('--top-gaps', type=int, default=0, help='只写前 K 个缺口（0=全部）')
    ap.add_argument('--verbose', action='store_true', help='打印扫描进度')
    args = ap.parse_args()

    ranks = load_ranks(args.jiten)
    state = _deps.load_state()
    deck = deck_sets(state)
    owner = read_owner(state)
    top = args.top or len(deck['all'])
    max_rank = args.max_rank or top

    limit = max([top, max_rank] + list(CHECKPOINTS))
    recs = scan(ranks, deck, owner, limit, verbose=args.verbose)
    curve = curve_from(recs, state, checkpoints=sorted(set(CHECKPOINTS + (top,))))
    points = {p['top']: p for p in curve['points']}
    curve['main'] = points.get(top) or (curve['points'][-1] if curve['points'] else None)
    side = deck_side(ranks, deck)
    gaps = gaps_from(recs, corpus_keys(), max_rank)

    m = {
        'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'state_generated_at': state.get('generated_at', ''),
        'table_size': len(ranks),
        'max_freq_rank': max(rk for _p, rk, _w, _k in ranks),
        'top': top,
        'max_rank': max_rank,
        'deck': {k: sorted(v) for k, v in deck.items() if not k.endswith('_loose')},
        'curve': curve,
        'deck_side': side,
        'gaps': {k: v for k, v in gaps.items() if k != 'need_rows'},
    }
    write_json(m, FIT_JSON)
    m['_need_rows'] = gaps['need_rows']       # 只给渲染用，不落盘

    rows = gaps['need_rows']
    if args.top_gaps:
        rows = rows[:args.top_gaps]
    with open(args.gap_out, 'w', encoding='utf-8') as fh:
        fh.write('pos\tfreq_rank\tword\tin_corpus72\n')
        for r in rows:
            fh.write('%d\t%d\t%s\t%s\n' % (r['pos'], r['freq_rank'], r['word'],
                                           'true' if r['in_corpus72'] else 'false'))

    first = curve['main']
    print('榜：%s 个词条（名次值 1..%s）' % (format(len(ranks), ','),
                                            format(m['max_freq_rank'], ',')))
    print('卡组：去重 %s 个（core6000 %s / 考级 %s / 素材生词 %s）'
          % (format(len(deck['all']), ','), format(len(deck['core6000']), ','),
             format(len(deck['jlpt']), ','), format(len(deck['mined']), ',')))
    print('前 %s 个动漫词：卡组覆盖 严 %s（%s 个）/ 宽 %s（含读音，%s 个）｜固定词表 %s｜已学 %s｜已成熟 %s'
          % (format(top, ','), pct(first['all']['ratio']), format(first['all']['n'], ','),
             pct(first['all_loose']['ratio']), format(first['all_loose']['n'], ','),
             pct(first['fixed_loose']['ratio']), pct(first['known_loose']['ratio']),
             pct(first['mature_loose']['ratio'])))
    g = gaps
    print('前 %s 名缺口：%s 个词条 -> 实词 %s 个（%s 个在 72 集语料里出现过）、'
          '其中「卡里其实已有」%s 个、其余 %s 个不用背'
          % (format(max_rank, ','), format(g['gap_total'], ','),
             format(g['need_total'], ','), format(g['need_in_corpus'], ','),
             format(g['also_covered'], ','),
             format(g['gap_total'] - g['need_total'] - g['also_covered'], ',')))
    print('落盘：%s' % FIT_JSON)
    print('落盘：%s（%s 行）' % (args.gap_out, format(len(rows), ',')))
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, 'w', encoding='utf-8') as fh:
            fh.write(render_md(m))
        print('报告：%s' % args.report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
