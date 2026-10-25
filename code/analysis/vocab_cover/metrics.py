# -*- coding: utf-8 -*-
"""把 corpus_tokens.json + vocab_state.json 变成报告用的全部指标，落盘
``data/vocab_cover/metrics.json``（报告与图表都读它，保证图文同源）。

三个分母（同一个覆盖率数字，分母不同差别很大，报告里必须写清）
------------------------------------------------------------
* ``all``       分母 = 全部词元（含语法词）—— 满足「不排除助词」的要求
* ``vocab``     分母 = 词汇词（去掉语法词/符号，含专有名词、感动词、数词）
* ``learnable`` 分母 = 需要背的实词（再去掉专有名词/感动词/数词）

关键指标
--------
* 逐集/逐作品覆盖率
* 语料词频累计曲线：覆盖 95%/98%/99% 各需要多少词汇量（V95/V98/V99）
* 目标差口：达到 X% 还缺多少词，其中多少在这 36 集里会遇到、大概第几集遇到
* 排名分段掌握率：语料最高频的 100/500/1000/2000/3000 词，你已学/已成熟多少
* 跨作品交叉覆盖：学完 A 之后再看 B 能懂多少（实测「换新作品的折损」）
* 学习模拟：按「看一集 -> 把这集不认识的词都学了」推进，覆盖率怎么涨
* Zipf / Heaps 拟合

用法::

    python code/analysis/vocab_cover/metrics.py            # 计算并打印摘要
    python code/analysis/vocab_cover/metrics.py --dump     # 多打印细节
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _deps import CORPUS_JSON, DATA_DIR, STATE_JSON, add_pylibs, write_json  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

METRICS_JSON = os.path.join(DATA_DIR, 'metrics.json')
BUCKETS = {0: 'core6000', 1: 'jlpt', 2: 'mined', 3: 'oov', 4: 'proper',
           5: 'interj', 6: 'numeral'}
DECK_BUCKETS = {'core6000', 'jlpt', 'mined'}
DECK_CODES = {0, 1, 2}
LEARN_CODES = {0, 1, 2, 3}
TARGETS = (0.90, 0.95, 0.98, 0.99)


# ------------------------------------------------------------------ 载入
def load() -> tuple:
    with open(CORPUS_JSON, encoding='utf-8') as fh:
        corpus = json.load(fh)
    with open(STATE_JSON, encoding='utf-8') as fh:
        state = json.load(fh)
    return corpus, state


def merge_word_attrs(episodes) -> tuple:
    """语料级词频 + 每个词的属性（取「最懂」状态）。"""
    freq = collections.Counter()
    attr = {}
    for ep in episodes:
        for w, (n, code, known, mature) in ep['word_counts'].items():
            freq[w] += n
            meta = ep['word_meta'].get(w, ['', '', 0])
            cand = {'bucket': BUCKETS.get(code, 'oov'), 'known': bool(known),
                    'mature': bool(mature), 'pos1': meta[0], 'pos2': meta[1],
                    'compound': bool(meta[2])}
            cur = attr.get(w)
            if cur is None:
                attr[w] = cand
            else:
                cand['known'] = cand['known'] or cur['known']
                cand['mature'] = cand['mature'] or cur['mature']
                cand['compound'] = cand['compound'] or cur['compound']
                attr[w] = cand
    return freq, attr


def tot(episodes) -> dict:
    keys = ('tokens', 'tokens_vocab', 'tokens_learnable', 'tokens_grammar',
            'tokens_symbol', 'chars', 'known_tokens', 'mature_tokens',
            'understood_tokens', 'understood_lenient_tokens',
            'understood_mature_tokens')
    out = {k: sum(e.get(k, 0) for e in episodes) for k in keys}
    for field in ('core_tokens', 'jlpt_tokens', 'mined_tokens', 'oov_tokens',
                  'proper_tokens', 'interj_tokens', 'numeral_tokens', 'deck_tokens'):
        out[field] = sum(e['cover_all'].get(field, 0) for e in episodes)
    out['speech_seconds'] = sum(e.get('speech_seconds', 0) for e in episodes)
    return out


def cover_from_tot(t: dict) -> dict:
    """由 token 汇总数算各种覆盖率（三个分母 × 三档认识程度）。"""
    n_all, n_vocab = t['tokens'], t['tokens_vocab']
    n_learn = t['tokens_learnable']
    known, mature = t['known_tokens'], t['mature_tokens']
    grammar = t['tokens_grammar']
    interj = t['interj_tokens'] + t['numeral_tokens']
    out = {}
    for tag, denom in (('all', n_all), ('vocab', n_vocab), ('learnable', n_learn)):
        out[f'core_{tag}'] = t['core_tokens'] / denom
        out[f'corejlpt_{tag}'] = (t['core_tokens'] + t['jlpt_tokens']) / denom
        out[f'deck_{tag}'] = t['deck_tokens'] / denom
        out[f'oov_{tag}'] = t['oov_tokens'] / denom
    out.update({
        'known_vocab': known / n_vocab, 'mature_vocab': mature / n_vocab,
        'known_learnable': known / n_learn, 'mature_learnable': mature / n_learn,
        'grammar_all': grammar / n_all,
        'proper_vocab': t['proper_tokens'] / n_vocab,
        'interj_vocab': interj / n_vocab,
        # ★ 主推：语法词、感动词、数词都算「能懂」（专有名词仍然算不懂）
        'understood_lenient_all': (known + grammar + interj) / n_all,
        'understood_strict_all': t['understood_tokens'] / n_all,
        'understood_mature_all': t['understood_mature_tokens'] / n_all,
    })
    return out


# ------------------------------------------------------------------ 词频曲线
def freq_curve(freq: collections.Counter, attr: dict) -> dict:
    items = freq.most_common()
    total = sum(freq.values())
    cum, curve = 0, []
    for rank, (w, n) in enumerate(items, 1):
        cum += n
        curve.append({'rank': rank, 'word': w, 'count': n, 'cum': cum,
                      'cover': cum / total, 'bucket': attr[w]['bucket'],
                      'known': attr[w]['known'], 'mature': attr[w]['mature']})
    return {'total_tokens': total, 'types': len(items), 'curve': curve}


def V_for_coverage(fc: dict, target: float) -> int:
    for row in fc['curve']:
        if row['cover'] >= target:
            return row['rank']
    return fc['types']


def coverage_at_V(fc: dict, V: int) -> float:
    if V <= 0:
        return 0.0
    if V >= fc['types']:
        return 1.0
    return fc['curve'][V - 1]['cover']


def rank_band_mastery(fc: dict, attr: dict,
                      bands=(100, 300, 500, 1000, 2000, 3000, 5000)) -> list:
    out, curve = [], fc['curve']
    for b in bands:
        if b > len(curve):
            break
        seg = curve[:b]
        n = len(seg)
        tok_all = sum(r['count'] for r in seg)
        out.append({
            'band': b, 'types': n,
            'known': sum(1 for r in seg if r['known']),
            'known_ratio': sum(1 for r in seg if r['known']) / n,
            'mature': sum(1 for r in seg if r['mature']),
            'mature_ratio': sum(1 for r in seg if r['mature']) / n,
            'oov': sum(1 for r in seg if r['bucket'] == 'oov'),
            'oov_ratio': sum(1 for r in seg if r['bucket'] == 'oov') / n,
            'proper': sum(1 for r in seg if r['bucket'] == 'proper'),
            'not_known': sum(1 for r in seg if not r['known']),
            'band_cover': tok_all / fc['total_tokens'],
            'token_known_ratio': sum(r['count'] for r in seg if r['known']) / tok_all,
        })
    return out


# ------------------------------------------------------------------ 目标差口
def target_gap(fc: dict, attr: dict, first_seen: dict, targets=TARGETS) -> list:
    """达到 X% 覆盖率还缺多少词；这些词在 36 集里大概第几集能遇到。"""
    out = []
    for x in targets:
        V = V_for_coverage(fc, x)
        top = fc['curve'][:V]
        missing = [r['word'] for r in top if not r['known']]
        missing_learnable = [r['word'] for r in top
                             if not r['known'] and r['bucket'] in ('oov',)]
        missing_deck = [r['word'] for r in top
                        if not r['known'] and r['bucket'] in DECK_BUCKETS]
        eps = sorted(first_seen.get(w, 999) for w in missing)
        rec = {
            'target': x, 'V': V,
            'types_in_topV': len(top),
            'known_in_topV': len(top) - len(missing),
            'missing': len(missing),
            'missing_in_deck': len(missing_deck),
            'missing_oov': len(missing_learnable),
            'missing_tokens': sum(r['count'] for r in top if not r['known']),
            'missing_token_share': (sum(r['count'] for r in top if not r['known'])
                                    / fc['total_tokens']),
        }
        if eps:
            rec.update({
                'first_seen_median_episode': eps[len(eps) // 2],
                'first_seen_p90_episode': eps[int(len(eps) * 0.9)],
                'first_seen_max_episode': eps[-1],
            })
        out.append(rec)
    return out


# ------------------------------------------------------------------ 交叉覆盖
def work_coverage_matrix(corpus: dict, state: dict) -> dict:
    """学完 k 部之后看另一部能懂多少（3 部作品实测出来的「新作品折损」）。"""
    episodes = corpus['episodes']
    works = corpus['works']
    known0 = {w for w, e in state['words'].items() if e['known']}
    per_work = {wk: [e for e in episodes if e['work'] == wk] for wk in works}
    work_words = {wk: {w for e in eps for w in e['word_counts']}
                  for wk, eps in per_work.items()}
    learn = {wk: {w for w in work_words[wk] if w not in known0} for wk in works}

    def cov(target: str, learned: set) -> float:
        num = den = 0
        for e in per_work[target]:
            for w, (n, _c, _k, _m) in e['word_counts'].items():
                den += n
                if w in known0 or w in learned:
                    num += n
        return num / den if den else 0.0

    rows = []
    for target in works:
        others = [w for w in works if w != target]
        entry = {'work': target, 'k0': cov(target, set()), 'per_k': {}}
        for k in range(1, len(others) + 1):
            vals = []
            for combo in _combinations(others, k):
                learned = set().union(*[learn[c] for c in combo]) if combo else set()
                vals.append({'learned': list(combo), 'cover': cov(target, learned),
                             'vocab_after': len(known0 | learned)})
            entry['per_k'][k] = {'mean': sum(v['cover'] for v in vals) / len(vals),
                                 'detail': vals}
        rows.append(entry)

    by_k = {}
    for k in range(0, len(works)):
        vals = [r['k0'] if k == 0 else r['per_k'][k]['mean'] for r in rows
                if k == 0 or k in r['per_k']]
        if vals:
            by_k[k] = sum(vals) / len(vals)
    return {'rows': rows, 'by_k': by_k,
            'learn_sizes': {wk: len(learn[wk]) for wk in works},
            'work_types': {wk: len(work_words[wk]) for wk in works},
            'known0': len(known0)}


def _combinations(items, k):
    if k == 0:
        yield ()
        return
    for i in range(len(items)):
        for rest in _combinations(items[i + 1:], k - 1):
            yield (items[i],) + rest


# ------------------------------------------------------------------ 学习模拟
def simulate(corpus: dict, state: dict, order=None, cycles: int = 2) -> dict:
    """「看一集 -> 把这集不认识的词全学了」逐集推进，记录每集看之前的覆盖率。"""
    episodes = corpus['episodes']
    if order is None:
        order = list(range(len(episodes)))
    known0 = {w for w, e in state['words'].items() if e['known']}
    K = set(known0)
    steps = []
    for cyc in range(cycles):
        for i in order:
            ep = episodes[i]
            num = den = 0
            unk = collections.Counter()
            for w, (n, _c, _k, _m) in ep['word_counts'].items():
                den += n
                if w in K:
                    num += n
                else:
                    unk[w] = n
            steps.append({
                'cycle': cyc + 1, 'work': ep['work'], 'episode': ep['episode'],
                'index': i + 1,
                'cover_before': num / den if den else 0,
                'new_words': len(unk), 'new_tokens': sum(unk.values()),
                'vocab_size_before': len(K),
            })
            K |= set(unk)
    return {'steps': steps, 'final_vocab': len(K),
            'final_cover_vocab': _aggregate_cover(episodes, K)}


def _aggregate_cover(episodes, known: set) -> float:
    num = den = 0
    for e in episodes:
        for w, (n, _c, _k, _m) in e['word_counts'].items():
            den += n
            if w in known:
                num += n
    return num / den if den else 0.0


def block_summary(corpus: dict, state: dict) -> dict:
    """按「作品」分块：学完第 k 部之后，第 k+1 部的覆盖率（换新番的实测折损）。"""
    episodes = corpus['episodes']
    works = corpus['works']
    known0 = {w for w, e in state['words'].items() if e['known']}
    K = set(known0)
    blocks = []
    for wk in works:
        idx = [i for i, e in enumerate(episodes) if e['work'] == wk]
        num = den = 0
        unk = set()
        for i in idx:
            for w, (n, _c, _k, _m) in episodes[i]['word_counts'].items():
                den += n
                if w in K:
                    num += n
                else:
                    unk.add(w)
        blocks.append({'work': wk, 'episodes': len(idx),
                       'cover_before_learning': num / den if den else 0,
                       'new_words': len(unk), 'vocab_size_before': len(K),
                       'vocab_size_after': len(K | unk)})
        K |= unk
    gaps = [1 - b['cover_before_learning'] for b in blocks]
    ratios = [gaps[i + 1] / gaps[i] for i in range(len(gaps) - 1) if gaps[i] > 0]
    return {'blocks': blocks, 'gap_shrink_ratios': ratios,
            'mean_gap_shrink': sum(ratios) / len(ratios) if ratios else None}


def deck_reach(corpus: dict, state: dict) -> dict:
    """反向触达：我的卡组里有多少词，在这 36 集里真的出现过。"""
    corpus_words = {w for e in corpus['episodes'] for w in e['word_counts']}
    out = {}
    for logical, key in (('core6000', 'core'), ('jlpt', 'jlpt'), ('mined', 'mined')):
        deck = [w for w, e in state['words'].items() if e.get(key)]
        hit = [w for w in deck if w in corpus_words]
        known = [w for w in hit if state['words'][w]['known']]
        out[logical] = {
            'deck_words': len(deck), 'seen_in_corpus': len(hit),
            'seen_ratio': len(hit) / len(deck) if deck else 0,
            'seen_and_known': len(known),
        }
    return out


def per_episode_new_words(corpus: dict, attr: dict) -> dict:
    """每集新遇到的词种/词元（按「上一集之前没见过」定义），用于估产量。"""
    seen = set()
    rows = []
    for e in corpus['episodes']:
        new_types = [w for w in e['word_counts'] if w not in seen]
        new_learn = [w for w in new_types if attr[w]['bucket'] in ('oov',)]
        new_tokens = sum(e['word_counts'][w][0] for w in new_types)
        rows.append({'work': e['work'], 'episode': e['episode'],
                     'new_types': len(new_types), 'new_learnable': len(new_learn),
                     'new_tokens': new_tokens})
        seen |= set(e['word_counts'])
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0
    return {'rows': rows,
            'median_new_types': med([r['new_types'] for r in rows]),
            'median_new_learnable': med([r['new_learnable'] for r in rows]),
            'total_new_types': sum(r['new_types'] for r in rows)}


def discovery_curve(corpus: dict, order=None) -> list:
    """按集推进，累计「见过」的词种数与占最终语料词表的比例。"""
    episodes = corpus['episodes']
    if order is None:
        order = list(range(len(episodes)))
    seen = set()
    allw = {w for e in episodes for w in e['word_counts']}
    out = []
    for n, i in enumerate(order, 1):
        seen |= set(episodes[i]['word_counts'])
        out.append({'episodes': n, 'seen_types': len(seen),
                    'ratio': len(seen) / len(allw), 'all_types': len(allw)})
    return out


def first_seen_episodes(corpus: dict) -> dict:
    out = {}
    for i, e in enumerate(corpus['episodes'], 1):
        for w in e['word_counts']:
            out.setdefault(w, i)
    return out


# ------------------------------------------------------------------ 拟合
def fit_power(xs, ys) -> dict:
    pts = [(math.log(x), math.log(y)) for x, y in zip(xs, ys) if x > 0 and y > 0]
    if len(pts) < 2:
        return {}
    n = len(pts)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] ** 2 for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return {}
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    yhat = [a + b * p[0] for p in pts]
    ss_res = sum((p[1] - h) ** 2 for p, h in zip(pts, yhat))
    ss_tot = sum((p[1] - sy / n) ** 2 for p in pts)
    return {'a': a, 'b': b, 'r2': 1 - ss_res / ss_tot if ss_tot else 0}


def heaps_fit(corpus: dict) -> dict:
    xs, ys, seen, toks = [], [], set(), 0
    for e in corpus['episodes']:
        seen |= set(e['word_counts'])
        toks += sum(n for n, *_ in e['word_counts'].values())
        xs.append(toks)
        ys.append(len(seen))
    f = fit_power(xs, ys)
    f.update({'tokens': toks, 'types': len(seen)})
    return f


def zipf_fit(fc: dict, upto: int = 3000) -> dict:
    curve = fc['curve'][:upto]
    f = fit_power([r['rank'] for r in curve], [r['count'] for r in curve])
    f['note'] = 'log(freq) = a + b*log(rank)；b≈-1 即标准 Zipf'
    return f


# ------------------------------------------------------------------ 主流程
def learning_rate(snapshot: str = None) -> dict:
    """从收藏快照的 revlog 算：词汇卡每月新学多少张（决定「还缺多少词」要多久）。"""
    import sqlite3
    cands = [snapshot,
             os.path.join(os.path.dirname(DATA_DIR), 'snapshots', 'live', 'collection.anki2'),
             os.path.join(os.path.dirname(DATA_DIR), 'snapshots', 'ankisnap', 'c.anki2'),
             os.path.join(os.path.dirname(DATA_DIR), 'snapshots', 'anki_snapshot.db')]
    path = next((p for p in cands if p and os.path.exists(p)), None)
    if not path:
        return {}
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    con.create_collation('unicase',
                         lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    cur = con.cursor()
    decks = {r[0]: r[1].replace('\x1f', '::') for r in cur.execute('SELECT id, name FROM decks')}
    vocab_dids = {did for did, name in decks.items()
                  if '高频日语单词 6000' in name or '考级词汇' in name
                  or '素材生词' in name or name.endswith('2-例句')}
    card_deck = {cid: did for cid, did in cur.execute('SELECT id, did FROM cards')}
    first = {}
    for cid, ts in cur.execute('SELECT cid, MIN(id) FROM revlog GROUP BY cid'):
        if card_deck.get(cid) in vocab_dids:
            first[cid] = ts
    monthly = collections.Counter()
    for cid, ts in first.items():
        d = _dt.datetime.fromtimestamp(ts / 1000)
        monthly[d.strftime('%Y-%m')] += 1
    months = sorted(monthly)
    recent = months[-6:]
    con.close()
    return {
        'snapshot': os.path.relpath(path, os.path.dirname(DATA_DIR)).replace('\\', '/'),
        'monthly': {k: monthly[k] for k in months},
        'recent_months': recent,
        'recent_total': sum(monthly[k] for k in recent),
        'recent_per_month': (sum(monthly[k] for k in recent) / len(recent)) if recent else 0,
        'total_vocab_cards_studied': len(first),
    }


def compute(dump: bool = False) -> dict:
    corpus, state = load()
    episodes = corpus['episodes']
    works = corpus['works']
    freq, attr = merge_word_attrs(episodes)
    fc = freq_curve(freq, attr)
    fs = first_seen_episodes(corpus)

    t_all = tot(episodes)
    per_work = {}
    for wk in works:
        eps = [e for e in episodes if e['work'] == wk]
        tt = tot(eps)
        per_work[wk] = {
            'episodes': len(eps), 'totals': tt, 'cover': cover_from_tot(tt),
            'minutes': round(tt['speech_seconds'] / 60, 1),
            'types': len({w for e in eps for w in e['word_counts']}),
            'oov_types': len({w for e in eps for w in e['word_counts']
                              if attr[w]['bucket'] == 'oov'}),
            'proper_types': len({w for e in eps for w in e['word_counts']
                                 if attr[w]['bucket'] == 'proper'}),
        }

    deck = state['decks']
    known_words = {w for w, e in state['words'].items() if e['known']}
    mature_words = {w for w, e in state['words'].items() if e['mature']}
    deck_words = {w for w, e in state['words'].items()
                  if e['core'] or e['jlpt'] or e['mined']}

    m = {
        'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
        'corpus_generated_at': corpus['generated_at'],
        'vocab_state_generated_at': corpus.get('vocab_generated_at'),
        'episodes': len(episodes),
        'works': works,
        'totals': t_all,
        'cover': cover_from_tot(t_all),
        'per_work': per_work,
        'per_episode': [{
            'work': e['work'], 'episode': e['episode'], 'title': e['title'],
            'tokens': e['tokens'], 'tokens_vocab': e['tokens_vocab'],
            'minutes': round(e['speech_seconds'] / 60, 1),
            'cover': dict(e['cover_all'], **{f'vocab_{k}': v for k, v in
                                             e['cover_vocab'].items()},
                          **{f'learn_{k}': v for k, v in e['cover_learnable'].items()}),
            'types': e['types_total'], 'oov_types': e['types'].get('oov', 0),
            'proper_types': e['types'].get('proper', 0),
            'untackled_types': sum(1 for _w, (_n, code, k, _mm)
                                   in e['word_counts'].items()
                                   if code in DECK_CODES and not k),
            'sentences': e['sentences'], 'window_15': e['window_15'],
            'oov_top': e['oov_top'][:40],
            'proper_top': e.get('proper_top', [])[:20],
        } for e in episodes],
        'deck': {
            'core6000': deck.get('core6000', {}),
            'jlpt': deck.get('jlpt', {}),
            'mined': deck.get('mined', {}),
            'known_words': len(known_words), 'mature_words': len(mature_words),
            'deck_words': len(deck_words),
            'by_deck': {
                'core6000': sum(1 for e in state['words'].values() if e['core']),
                'jlpt': sum(1 for e in state['words'].values() if e['jlpt']),
                'mined': sum(1 for e in state['words'].values() if e['mined']),
            },
            'known_by_deck': {
                'core6000': sum(1 for e in state['words'].values() if e['core'] and e['known']),
                'jlpt': sum(1 for e in state['words'].values() if e['jlpt'] and e['known']),
                'mined': sum(1 for e in state['words'].values() if e['mined'] and e['known']),
            },
            'mature_by_deck': {
                'core6000': sum(1 for e in state['words'].values() if e['core'] and e['mature']),
                'jlpt': sum(1 for e in state['words'].values() if e['jlpt'] and e['mature']),
                'mined': sum(1 for e in state['words'].values() if e['mined'] and e['mature']),
            },
        },
        'freq_curve': {'total_tokens': fc['total_tokens'], 'types': fc['types'],
                       'V90': V_for_coverage(fc, 0.90), 'V95': V_for_coverage(fc, 0.95),
                       'V98': V_for_coverage(fc, 0.98), 'V99': V_for_coverage(fc, 0.99),
                       'top100_cover': coverage_at_V(fc, 100),
                       'top500_cover': coverage_at_V(fc, 500),
                       'top1000_cover': coverage_at_V(fc, 1000),
                       'top2000_cover': coverage_at_V(fc, 2000),
                       'top3000_cover': coverage_at_V(fc, 3000),
                       'top5000_cover': coverage_at_V(fc, 5000),
                       'curve': fc['curve']},
        'band_mastery': rank_band_mastery(fc, attr),
        'target_gap': target_gap(fc, attr, fs),
        'cross_work': work_coverage_matrix(corpus, state),
        'block_summary': block_summary(corpus, state),
        'deck_reach': deck_reach(corpus, state),
        'per_episode_new': per_episode_new_words(corpus, attr),
        'simulate': simulate(corpus, state),
        'discovery': discovery_curve(corpus),
        'heaps': heaps_fit(corpus),
        'zipf': zipf_fit(fc),
        'learning_rate': learning_rate(),
    }

    curve = fc['curve']
    keep = sorted({1, 10, 50, 100, 200, 300, 500, 750, 1000, 1500, 2000, 3000,
                   4000, 5000, 7500, 10000, len(curve)} |
                  {m['freq_curve'][k] for k in ('V90', 'V95', 'V98', 'V99')})
    m['freq_curve']['sample'] = [curve[r - 1] for r in keep if 0 < r <= len(curve)]
    m['freq_curve']['curve'] = [
        {'rank': r['rank'], 'word': r['word'], 'count': r['count'], 'cover': r['cover'],
         'bucket': r['bucket'], 'known': r['known']} for r in curve]

    m['corpus_vocab_mastery'] = {
        'types': len(freq),
        'known': sum(1 for w in freq if attr[w]['known']),
        'mature': sum(1 for w in freq if attr[w]['mature']),
        'by_bucket_types': dict(collections.Counter(attr[w]['bucket'] for w in freq)),
        'by_bucket_tokens': {b: sum(freq[w] for w in freq if attr[w]['bucket'] == b)
                             for b in set(attr[w]['bucket'] for w in freq)},
    }
    # 三个分母下「这些集一共出现过多少词种 / 词元」
    m['denominators'] = {
        'tokens_all': t_all['tokens'], 'tokens_vocab': t_all['tokens_vocab'],
        'tokens_learnable': t_all['tokens_learnable'],
        'tokens_grammar': t_all['tokens_grammar'],
        'types_all': m['corpus_vocab_mastery']['types'] + 0,   # 词汇词种
        'vocab_types': m['corpus_vocab_mastery']['types'],
        'learnable_types': sum(v for k, v in
                               m['corpus_vocab_mastery']['by_bucket_types'].items()
                               if k in ('core6000', 'jlpt', 'mined', 'oov')),
    }

    if dump:
        print(json.dumps({k: v for k, v in m.items()
                          if k not in ('per_episode', 'freq_curve', 'simulate',
                                       'discovery', 'band_mastery', 'cross_work')},
                         ensure_ascii=False, indent=2))
    write_json(m, METRICS_JSON)
    return m


def summarize(m: dict) -> None:
    c, t, d = m['cover'], m['totals'], m['denominators']
    print(f"语料 {m['episodes']} 集 / {t['tokens']} 词元"
          f"（词汇词 {t['tokens_vocab']} / 需背实词 {t['tokens_learnable']}）"
          f" / 台词时长 {t['speech_seconds']/3600:.1f} 小时")
    for tag, label in (('all', '含语法词'), ('vocab', '词汇词'), ('learnable', '需背实词')):
        print(f"  [{label:<5}] core6000 {c['core_'+tag]*100:>5.1f}%  "
              f"core+考级 {c['corejlpt_'+tag]*100:>5.1f}%  "
              f"全卡组 {c['deck_'+tag]*100:>5.1f}%  新词 {c['oov_'+tag]*100:>5.1f}%")
    print(f"  我实际能懂（宽口径/全部词元）{c['understood_lenient_all']*100:.1f}%  "
          f"严格 {c['understood_strict_all']*100:.1f}%  "
          f"按已成熟 {c['understood_mature_all']*100:.1f}%")
    print(f"  需背实词里：我已学 {c['known_learnable']*100:.1f}%  "
          f"已成熟 {c['mature_learnable']*100:.1f}%")
    print('  反向触达（36 集里真的出现过）：' + '  '.join(
        f"{k} {v['seen_in_corpus']}/{v['deck_words']}={v['seen_ratio']*100:.1f}%"
        for k, v in m['deck_reach'].items()))
    bs = m['block_summary']
    print('  分块实测（学完前几部后看下一部）：' + '  '.join(
        f"{b['work']}={b['cover_before_learning']*100:.1f}%(新词{b['new_words']})"
        for b in bs['blocks']))
    print('    缺口收缩比: ' + '  '.join(f'{r:.2f}' for r in bs['gap_shrink_ratios']))
    pe = m['per_episode_new']
    print(f"  每集新词种：中位 {pe['median_new_types']}（其中需背实词 {pe['median_new_learnable']}）")
    fx = m['freq_curve']
    print(f"  语料词表 {fx['types']} 词种：覆盖 90% 需 {fx['V90']} 词，95% 需 {fx['V95']}，"
          f"98% 需 {fx['V98']}，99% 需 {fx['V99']}")
    for g in m['target_gap']:
        print(f"    目标 {g['target']*100:.0f}%: 还缺 {g['missing']} 词"
              f"（卡组内未学 {g['missing_in_deck']} / 卡组外 {g['missing_oov']}），"
              f"中位第 {g.get('first_seen_median_episode','-')} 集才会遇到")
    dd = m['deck']
    print(f"  卡组资产：core6000 {dd['known_by_deck']['core6000']}/{dd['by_deck']['core6000']}"
          f"，考级 {dd['known_by_deck']['jlpt']}/{dd['by_deck']['jlpt']}"
          f"，合计认识 {dd['known_words']} 词条（成熟 {dd['mature_words']}）")
    print('  每多学一部作品后看下一部的覆盖率：' + '  '.join(
        f"{k}部:{v*100:.1f}%" for k, v in sorted(m['cross_work']['by_k'].items())))
    print('  新作品带来的新词量：' + '  '.join(
        f"{k}:{v}" for k, v in m['cross_work']['learn_sizes'].items()))
    print('  Heaps: V=%.1f*N^%.3f (r2=%.3f)   Zipf: b=%.3f (r2=%.3f)' % (
        math.exp(m['heaps']['a']), m['heaps']['b'], m['heaps']['r2'],
        m['zipf']['b'], m['zipf']['r2']))
    sim = m['simulate']
    first = [s for s in sim['steps'] if s['cycle'] == 1]
    print(f"  学习模拟：第 1 集 {first[0]['cover_before']*100:.1f}% -> "
          f"第 36 集 {first[-1]['cover_before']*100:.1f}%，"
          f"最终词表 {sim['final_vocab']} 词")
    if len(first) >= 24:
        seg = first[12:24]
        print(f"    学完前 12 集后，第 13–24 集平均覆盖 {sum(s['cover_before'] for s in seg)/len(seg)*100:.1f}%")
    lr = m.get('learning_rate') or {}
    if lr:
        print(f"  学卡速度：近 {len(lr['recent_months'])} 个月共新学 {lr['recent_total']} 张词汇卡，"
              f"月均 {lr['recent_per_month']:.0f} 张（快照 {lr['snapshot']}）")


def main() -> int:
    ap = argparse.ArgumentParser(description='计算字幕覆盖率与词汇量指标')
    ap.add_argument('--dump', action='store_true')
    args = ap.parse_args()
    add_pylibs()
    m = compute(dump=args.dump)
    summarize(m)
    print(f'\n写出 {METRICS_JSON}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
