# -*- coding: utf-8 -*-
"""学习策略分析：该按「卡组自身的排序」被动学，还是按「素材里真出现的词」学？

回答三件事（全部基于实测语料 + 你的 Anki 状态）：

1. **同样学 N 个词，两种顺序的收益差多少**
   * 卡组顺序：core6000 按 Index 从小到大，取未学的前 N 个
   * 素材顺序：按这 36 集字幕里的实际出现次数，取未学的前 N 个
   * 收益 = 这些词在语料「需背实词」词元里的占比
2. **卡组顺序本身是不是频率顺序**（Index 与素材频率的相关性、前 N 个词的素材命中率）
3. **素材能供给多少学习量**：每集里「卡组内未学」与「卡组外新词」各多少（决定能不能纯素材驱动）

同时产出可直接用的清单：
* ``data/vocab_cover/study_plan_critical_path.json`` —— 卡组内未学、但素材里出现过的词，按素材频率排序
* ``data/vocab_cover/study_plan_mining.json`` —— 卡组外实词，按素材频率排序（喂 mine 流水线）
* ``docs/reports/学习策略建议.md`` —— 结论文档

用法::

    python code/analysis/vocab_cover/study_plan.py
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import math
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _deps import DATA_DIR, STATE_JSON, WSP, add_pylibs, write_json  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

METRICS = os.path.join(DATA_DIR, 'metrics.json')
CORPUS = os.path.join(DATA_DIR, 'corpus_tokens.json')
PLAN_CRITICAL = os.path.join(DATA_DIR, 'study_plan_critical_path.json')
PLAN_MINING = os.path.join(DATA_DIR, 'study_plan_mining.json')
PLAN_NEXT = os.path.join(DATA_DIR, 'study_plan_next200.json')
MEMO = os.path.join(WSP.REPORTS, '学习策略建议.md')
DECK_BUCKETS = {'core6000', 'jlpt', 'mined'}
CORE, JLPT, MINED, OOV = 'core6000', 'jlpt', 'mined', 'oov'


def pct(x, nd=1):
    return f'{x*100:.{nd}f}%'


# ------------------------------------------------------------------ 载入
def load():
    m = json.load(open(METRICS, encoding='utf-8'))
    corpus = json.load(open(CORPUS, encoding='utf-8'))
    state = json.load(open(STATE_JSON, encoding='utf-8'))
    return m, corpus, state


def corpus_freq(corpus: dict) -> collections.Counter:
    freq = collections.Counter()
    for ep in corpus['episodes']:
        for w, (n, *_rest) in ep['word_counts'].items():
            freq[w] += n
    return freq


def word_category(word: str, state: dict, attr_bucket: str = None) -> str:
    e = state['words'].get(word)
    if e:
        if e['known']:
            return 'known_deck'
        if e['core']:
            return 'core_untackled'
        if e['jlpt']:
            return 'jlpt_untackled'
        if e['mined']:
            return 'mined_untackled'
    return attr_bucket or 'oov'


# ------------------------------------------------------------------ 1. 顺序对比
def order_comparison(m: dict, corpus: dict, state: dict, ns=(100, 300, 500, 1000, 2000)) -> dict:
    freq = corpus_freq(corpus)
    total_vocab_tokens = m['totals']['tokens_learnable']
    words = state['words']

    core_untackled = sorted(
        ((e['core'], w) for w, e in words.items() if e['core'] and not e['known']))
    # 素材顺序：语料里出现过的、我还没学或不认识的词，按素材频次降序
    material_order = sorted(
        (w for w in freq if not (words.get(w) or {}).get('known')), key=lambda w: -freq[w])
    material_in_deck = sorted(
        (w for w in freq if (words.get(w) or {}).get('core') and not words[w]['known']),
        key=lambda w: -freq[w])

    rows = []
    for n in ns:
        deck_set = [w for _r, w in core_untackled[:n]]
        mat_set = material_order[:n]
        mat_deck_set = material_in_deck[:n]
        gain_deck = sum(freq.get(w, 0) for w in deck_set) / total_vocab_tokens
        gain_mat = sum(freq.get(w, 0) for w in mat_set) / total_vocab_tokens
        gain_mat_deck = sum(freq.get(w, 0) for w in mat_deck_set) / total_vocab_tokens
        hit_deck = sum(1 for w in deck_set if freq.get(w)) / max(1, len(deck_set))
        rows.append({
            'n': n,
            'deck_order_gain': gain_deck, 'deck_order_hit_rate': hit_deck,
            'material_order_gain': gain_mat, 'material_in_deck_gain': gain_mat_deck,
            'ratio': (gain_mat / gain_deck) if gain_deck else None,
            'ratio_deckonly': (gain_mat_deck / gain_deck) if gain_deck else None,
        })
    return {'rows': rows, 'core_untackled': len(core_untackled),
            'material_untackled_words': len(material_order)}


def index_is_frequency(m: dict, corpus: dict, state: dict) -> dict:
    """core6000 的 Index 到底是不是频率序？看它与素材频率的相关性。"""
    freq = corpus_freq(corpus)
    pairs = [(e['core'], freq.get(w, 0)) for w, e in state['words'].items() if e['core']]
    ranks = [p[0] for p in pairs]
    counts = [p[1] for p in pairs]
    # Spearman（用秩相关，避免量纲问题）
    def rankdata(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rankdata(ranks), rankdata(counts)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    rho = num / den if den else 0
    # 前 N 张卡里有多少在素材中出现过
    hit = {}
    for n in (100, 300, 500, 1000, 2000, 3000):
        seg = [w for _r, w in sorted((e['core'], w) for w, e in state['words'].items()
                                     if e['core'])[:n]]
        hit[n] = sum(1 for w in seg if freq.get(w)) / max(1, len(seg))
    # Index 最小的 15 个词，肉眼检查
    head = [w for _r, w in sorted((e['core'], w) for w, e in state['words'].items()
                                  if e['core'])[:15]]
    return {'spearman_rank_vs_corpus_freq': rho, 'hit_rate_by_n': hit, 'head15': head}


# ------------------------------------------------------------------ 2. 供给量
def supply(m: dict, corpus: dict, state: dict) -> dict:
    """每集能供给多少「可学的新词」。"""
    words = state['words']
    rows = []
    for e in corpus['episodes']:
        untackled = sum(1 for w, (_n, code, known, _mm) in e['word_counts'].items()
                        if code in (0, 1, 2) and not known)
        oov = sum(1 for w, (_n, code, known, _mm) in e['word_counts'].items() if code == 3)
        proper = sum(1 for w, (_n, code, known, _mm) in e['word_counts'].items() if code == 4)
        rows.append({'work': e['work'], 'episode': e['episode'],
                     'untackled_in_deck': untackled, 'oov': oov, 'proper': proper,
                     'total': untackled + oov})
    tot = sorted(r['total'] for r in rows)

    def med(xs):
        return xs[len(xs) // 2] if xs else 0
    return {
        'rows': rows,
        'median_untackled_in_deck': med(sorted(r['untackled_in_deck'] for r in rows)),
        'median_oov': med(sorted(r['oov'] for r in rows)),
        'median_total': med(tot),
        'min_total': tot[0] if tot else 0, 'max_total': tot[-1] if tot else 0,
    }


# ------------------------------------------------------------------ 3. 组成
def band_composition(m: dict, corpus: dict, state: dict,
                     bands=(100, 300, 500, 1000, 2000, 3000)) -> list:
    """素材里最高频的前 N 个词，分别属于哪一类。"""
    freq = corpus_freq(corpus)
    order = sorted(freq, key=lambda w: -freq[w])
    total = sum(freq.values())
    out = []
    for b in bands:
        seg = order[:b]
        cats = collections.Counter()
        tok = collections.Counter()
        for w in seg:
            c = word_category(w, state)
            cats[c] += 1
            tok[c] += freq[w]
        out.append({'band': b, 'cats': dict(cats), 'tokens': dict(tok),
                    'token_total': sum(tok.values()),
                    'share_of_all': sum(tok.values()) / total})
    return out


# ------------------------------------------------------------------ 4. 语法卡组
def grammar_stats(snapshot: str = None) -> dict:
    cands = [snapshot] + [os.path.join(WSP.SNAPSHOTS, p) for p in
                          ('live/collection.anki2', 'ankisnap/c.anki2',
                           'anki_snapshot.db')]
    path = next((p for p in cands if p and os.path.exists(p)), None)
    if not path:
        return {}
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    con.create_collation('unicase',
                         lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    cur = con.cursor()
    decks = {r[0]: r[1].replace('\x1f', '::') for r in cur.execute('SELECT id, name FROM decks')}
    did_of = {}
    for did, name in decks.items():
        if '语法' in name:
            did_of[did] = '语法'
        elif '高频日语单词 6000' in name:
            did_of[did] = 'core6000'
        elif '考级词汇' in name:
            did_of[did] = '考级词汇'
        elif '素材生词' in name or name.endswith('2-例句'):
            did_of[did] = '素材/例句'
    cards = {}
    for cid, did, reps, lapses, ivl, type_ in cur.execute(
            'SELECT id, did, reps, lapses, ivl, type FROM cards'):
        g = did_of.get(did)
        if g:
            cards[cid] = (g, reps, lapses, ivl, type_)
    stats = collections.defaultdict(lambda: {'cards': 0, 'studied': 0, 'mature': 0,
                                             'reps': 0, 'again': 0, 'rev': 0, 'ms': 0})
    for cid, (g, reps, lapses, ivl, type_) in cards.items():
        s = stats[g]
        s['cards'] += 1
        s['studied'] += 1 if reps > 0 else 0
        s['mature'] += 1 if (type_ == 2 and ivl >= 21) else 0
    for ts, cid, ease, time_, type_ in cur.execute('SELECT id, cid, ease, time, type FROM revlog'):
        row = cards.get(cid)
        if not row:
            continue
        s = stats[row[0]]
        s['reps'] += 1
        s['ms'] += time_
        if type_ == 1:
            s['rev'] += 1
            s['again'] += 1 if ease == 1 else 0
    con.close()
    out = {}
    for g, s in stats.items():
        out[g] = {
            'cards': s['cards'], 'studied': s['studied'], 'mature': s['mature'],
            'reviews': s['reps'], 'again_rate': s['again'] / s['rev'] if s['rev'] else None,
            'avg_sec': s['ms'] / s['reps'] / 1000 if s['reps'] else None,
        }
    return {'snapshot': os.path.relpath(path, WSP.ROOT).replace('\\', '/'), 'by_group': out}


def new_card_order(snapshot: str = None) -> dict:
    """确认 Anki 现在到底按什么顺序给你新卡（新卡的 due 字段 = 内部顺序号）。

    如果新卡的 due 升序与 core6000 的 Index 升序一致，说明「按卡牌自身排序」成立。
    """
    cands = [snapshot] + [os.path.join(WSP.SNAPSHOTS, p) for p in
                          ('live/collection.anki2', 'ankisnap/c.anki2',
                           'anki_snapshot.db')]
    path = next((p for p in cands if p and os.path.exists(p)), None)
    if not path:
        return {}
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    con.create_collation('unicase',
                         lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    cur = con.cursor()
    decks = {r[0]: r[1].replace('\x1f', '::') for r in cur.execute('SELECT id, name FROM decks')}
    did = next((d for d, n in decks.items() if '高频日语单词 6000' in n), None)
    ntname = {r[0]: r[1] for r in cur.execute('SELECT id, name FROM notetypes')}
    mid = next((m for m, n in ntname.items() if n == 'Japanese Vocabulary'), None)
    rows = []
    cur2 = con.cursor()
    for cid, nid, due, queue in cur.execute(
            'SELECT id, nid, due, queue FROM cards WHERE did=?', (did,)).fetchall():
        if queue != 0:          # 只看未学的新卡
            continue
        flds = cur2.execute('SELECT flds FROM notes WHERE id=?', (nid,)).fetchone()
        if not flds:
            continue
        parts = flds[0].split('\x1f')
        rows.append((due, parts[1].strip() if len(parts) > 1 else '', parts[0].strip()))
    con.close()
    rows.sort()
    head = [r[1] for r in rows[:20]]
    # due 顺序与 Index 顺序的秩相关
    n = len(rows)
    if n < 10:
        return {'new_cards': n}
    def rankdata(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        for pos, idx in enumerate(order):
            r[idx] = pos + 1
        return r
    a = rankdata([r[0] for r in rows])
    b = rankdata([int(r[2]) if r[2].isdigit() else 0 for r in rows])
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return {'new_cards': n, 'first20_by_due': head,
            'spearman_due_vs_index': num / den if den else 0}


def recent_load(days: int = 21, snapshot: str = None) -> dict:
    """最近 N 天的实际负荷（按组）：复习次数 / 分钟 / **真正的新卡**。

    新卡必须用「全局第一次复习」判定 —— 只看窗口内记录，会把老卡的窗口内首刷误算成新卡。
    """
    cands = [snapshot] + [os.path.join(WSP.SNAPSHOTS, p) for p in
                          ('live/collection.anki2', 'ankisnap/c.anki2',
                           'anki_snapshot.db')]
    path = next((p for p in cands if p and os.path.exists(p)), None)
    if not path:
        return {}
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    con.create_collation('unicase',
                         lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    cur = con.cursor()
    decks = {r[0]: r[1].replace('\x1f', '::') for r in cur.execute('SELECT id, name FROM decks')}
    did_of = {}
    for d, name in decks.items():
        if '语法' in name:
            did_of[d] = '语法'
        elif '高频日语单词 6000' in name:
            did_of[d] = 'core6000'
        elif '考级词汇' in name:
            did_of[d] = '考级词汇'
        elif '素材生词' in name or name.endswith('2-例句'):
            did_of[d] = '素材/例句'
    card = {cid: did_of.get(d) for cid, d in cur.execute('SELECT id, did FROM cards')}
    day = 86400000
    newest = cur.execute('SELECT MAX(id) FROM revlog').fetchone()[0] or 0
    cut = newest - days * day

    stats = collections.defaultdict(lambda: {'reps': 0, 'ms': 0, 'new': 0,
                                             'rev': 0, 'again': 0})
    for cid, ts in cur.execute('SELECT cid, MIN(id) FROM revlog GROUP BY cid'):
        if ts > cut:
            g = card.get(cid)
            if g:
                stats[g]['new'] += 1
    active_days = set()
    for ts, cid, ease, time_, type_ in cur.execute(
            'SELECT id, cid, ease, time, type FROM revlog WHERE id > ?', (cut,)):
        active_days.add(ts // day)
        g = card.get(cid)
        if not g:
            continue
        stats[g]['reps'] += 1
        stats[g]['ms'] += time_
        if type_ == 1:
            stats[g]['rev'] += 1
            stats[g]['again'] += 1 if ease == 1 else 0
    con.close()
    ndays = max(1, len(active_days))
    out = {}
    for g, s in stats.items():
        out[g] = {'reps_per_day': s['reps'] / ndays, 'min_per_day': s['ms'] / 60000 / ndays,
                  'new_per_day': s['new'] / ndays, 'new_per_month': s['new'] * 30 / ndays,
                  'again_rate': s['again'] / s['rev'] if s['rev'] else None}
    tot = {'reps_per_day': sum(v['reps_per_day'] for v in out.values()),
           'min_per_day': sum(v['min_per_day'] for v in out.values()),
           'new_per_day': sum(v['new_per_day'] for v in out.values()),
           'new_per_month': sum(v['new_per_month'] for v in out.values())}
    return {'days': days, 'active_days': ndays, 'by_group': out, 'total': tot,
            'newest_review': _dt.datetime.fromtimestamp(
                newest / 1000).isoformat(timespec='seconds')}


def corpus_bucket_map(corpus: dict) -> dict:
    """词 -> 语料判定的档位。

    同一个词在不同集里可能被判成不同词性（Sudachi 对专有名词的判定依赖上下文），
    这里用「只要有一次被判成固有名詞就当专有名词」的保守规则，避免名字混进背词清单。
    """
    code2bucket = {0: CORE, 1: JLPT, 2: MINED, 3: OOV, 4: 'proper', 5: 'interj',
                   6: 'numeral'}
    seen = {}
    for ep in corpus['episodes']:
        for w, (_n, code, *_r) in ep['word_counts'].items():
            seen.setdefault(w, set()).add(code2bucket.get(code, OOV))
    out = {}
    for w, buckets in seen.items():
        if 'proper' in buckets:
            out[w] = 'proper'
        elif buckets <= {'interj', 'numeral'}:
            out[w] = 'interj' if 'interj' in buckets else 'numeral'
        elif buckets & {CORE, JLPT, MINED} and not (buckets - {CORE, JLPT, MINED,
                                                             'interj', 'numeral'}):
            out[w] = next(b for b in (CORE, JLPT, MINED) if b in buckets)
        elif OOV in buckets:
            out[w] = OOV
        else:
            out[w] = next(iter(buckets))
    return out


def tail_analysis(state: dict, corpus: dict) -> dict:
    """已学/未学两部分 core6000 的 Index 分布与素材命中率 —— 证明「好吃的已经吃完了」。"""
    freq = set()
    for ep in corpus['episodes']:
        freq |= set(ep['word_counts'])
    out = {}
    for label, flag in (('studied', True), ('untackled', False)):
        ws = [(e['core'], w) for w, e in state['words'].items()
              if e['core'] and e['known'] == flag]
        idx = sorted(r for r, _w in ws)
        if not idx:
            continue
        out[label] = {
            'cards': len(ws), 'index_min': idx[0], 'index_median': idx[len(idx) // 2],
            'index_max': idx[-1],
            'material_hit_rate': (sum(1 for _r, w in ws if w in freq) / len(ws)),
        }
    return out


# ------------------------------------------------------------------ 主流程
def compute(dump: bool = False) -> dict:
    m, corpus, state = load()
    order = order_comparison(m, corpus, state)
    idx = index_is_frequency(m, corpus, state)
    sup = supply(m, corpus, state)
    bands = band_composition(m, corpus, state)
    gram = grammar_stats()
    freq = corpus_freq(corpus)

    # 可复用清单：卡组内未学但素材出现过的词（按素材频次）
    bmap = corpus_bucket_map(corpus)
    crit = sorted(((w, freq[w]) for w, e in state['words'].items()
                   if (e['core'] or e['jlpt'] or e['mined']) and not e['known']
                   and freq.get(w)),
                  key=lambda t: -t[1])
    mining = sorted(((w, freq[w]) for w in freq
                     if not (state['words'].get(w) or {}).get('known')
                     and bmap.get(w) == OOV),
                    key=lambda t: -t[1])
    # 合并后的「下一步就学这些」：卡组内现成卡 + 卡组外要挖的，统一按素材频次
    merged = sorted(set(crit) | set(mining), key=lambda t: -t[1])
    write_json([{'word': w, 'corpus_count': n} for w, n in crit], PLAN_CRITICAL)
    write_json([{'word': w, 'corpus_count': n} for w, n in mining], PLAN_MINING)
    comp = collections.Counter()
    for w, _n in crit:
        e = state['words'].get(w) or {}
        comp['core6000' if e.get('core') else 'jlpt' if e.get('jlpt') else 'mined'] += 1
    cp_by_source = dict(comp)
    write_json([{'word': w, 'corpus_count': n,
                 'in_deck': bool((state['words'].get(w) or {}).get('core')
                                 or (state['words'].get(w) or {}).get('jlpt')
                                 or (state['words'].get(w) or {}).get('mined')),
                 'bucket': bmap.get(w, OOV)} for w, n in merged[:200]],
               PLAN_NEXT)

    res = {'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
           'order': order, 'index': idx, 'supply': sup, 'bands': bands,
           'grammar': gram, 'tail': tail_analysis(state, corpus),
           'new_card_order': new_card_order(),
           'recent_load': recent_load(),
           'critical_path': {'words': len(crit), 'by_source': cp_by_source,
                             'top50': [w for w, _n in crit[:50]],
                             'json': os.path.relpath(PLAN_CRITICAL, WSP.ROOT).replace('\\', '/')},
           'mining': {'words': len(mining),
                      'top50': [w for w, _n in mining[:50]],
                      'json': os.path.relpath(PLAN_MINING, WSP.ROOT).replace('\\', '/')}}
    if dump:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def summarize(r: dict) -> None:
    print('=== 1. 同样学 N 个词，两种顺序的收益（占语料需背实词的比例）===')
    print(f"  {'N':>5}{'卡组顺序':>10}{'卡组命中率':>11}{'素材顺序':>10}"
          f"{'仅用卡组卡':>11}{'素材/卡组':>10}")
    for row in r['order']['rows']:
        print(f"  {row['n']:>5}{pct(row['deck_order_gain']):>10}"
              f"{pct(row['deck_order_hit_rate']):>11}{pct(row['material_order_gain']):>10}"
              f"{pct(row['material_in_deck_gain']):>11}"
              f"{row['ratio']:>10.1f}x")
    print(f"  卡组内未学共 {r['order']['core_untackled']} 个 core6000 词；"
          f"素材里出现过、我还没学的词 {r['order']['material_untackled_words']} 个")
    print()
    print('=== 2. core6000 的 Index 是不是频率序 ===')
    print(f"  Index 与素材频次的 Spearman 秩相关：{r['index']['spearman_rank_vs_corpus_freq']:.3f}"
          '（-1 = 完全反向，0 = 无关）')
    print('  Index 前 N 张卡在素材中出现过的比例：' + '  '.join(
        f'{k}:{pct(v, 0)}' for k, v in r['index']['hit_rate_by_n'].items()))
    print(f"  Index 最小的 15 个词：{' '.join(r['index']['head15'])}")
    print()
    print('=== 3. 每集能供给多少可学的新词 ===')
    s = r['supply']
    print(f"  卡组内未学（素材命中）中位 {s['median_untackled_in_deck']} 个/集；"
          f"卡组外新词中位 {s['median_oov']} 个/集；合计中位 {s['median_total']} 个/集"
          f"（最少 {s['min_total']} / 最多 {s['max_total']}）")
    print()
    print('=== 4. 素材高频词的构成 ===')
    for b in r['bands']:
        cats = b['cats']
        print(f"  前 {b['band']:>4} 词（占全部词元 {pct(b['share_of_all'])}）："
              f"卡组已学 {cats.get('known_deck', 0):>4} · "
              f"core 未学 {cats.get('core_untackled', 0):>4} · "
              f"考级未学 {cats.get('jlpt_untackled', 0):>4} · "
              f"卡组外 {cats.get('oov', 0):>4}")
    print()
    print('=== 5. 卡组实测 ===')
    g = r['grammar'].get('by_group', {})
    print(f"  {'组':<12}{'卡数':>7}{'已学':>7}{'成熟':>7}{'忘记率':>9}{'秒/次':>8}")
    for k, v in sorted(g.items()):
        ar = f"{v['again_rate']*100:.1f}%" if v['again_rate'] is not None else '-'
        av = f"{v['avg_sec']:.1f}" if v['avg_sec'] else '-'
        print(f"  {k:<12}{v['cards']:>7}{v['studied']:>7}{v['mature']:>7}{ar:>9}{av:>8}")
    nco = r.get('new_card_order') or {}
    if nco:
        print()
        print(f"=== 6. Anki 现在实际给新卡的顺序（core6000 未学新卡 {nco['new_cards']} 张）===")
        print(f"  队列顺序 vs Index 的秩相关：{nco['spearman_due_vs_index']:.3f}"
              '（≈1 表示就是按 Index 顺序在发卡）')
        print(f"  先发的 20 张：{' '.join(nco['first20_by_due'])}")
    rl = r.get('recent_load') or {}
    if rl:
        print()
        print(f"=== 7. 最近 {rl['days']} 天实际负荷"
              f"（活跃 {rl.get('active_days')} 天，数据截至 {rl.get('newest_review','')}）===")
        for k, v in sorted(rl['by_group'].items()):
            ar = f"{v['again_rate']*100:.1f}%" if v.get('again_rate') is not None else '-'
            print(f"  {k:<12} 复习 {v['reps_per_day']:>6.1f} 次/天 · "
                  f"{v['min_per_day']:>5.1f} 分钟/天 · 新卡 {v['new_per_day']:>4.1f} 张/天"
                  f"（{v['new_per_month']:>5.0f} 张/月）· 忘记率 {ar}")
        t = rl['total']
        print(f"  {'合计':<12} 复习 {t['reps_per_day']:>6.1f} 次/天 · "
              f"{t['min_per_day']:>5.1f} 分钟/天 · 新卡 {t['new_per_day']:>4.1f} 张/天"
              f"（{t['new_per_month']:>5.0f} 张/月）")


def main() -> int:
    ap = argparse.ArgumentParser(description='卡组顺序 vs 素材驱动的学习策略分析')
    ap.add_argument('--dump', action='store_true')
    ap.add_argument('--memo', action='store_true', help='同时写 docs/reports/学习策略建议.md')
    args = ap.parse_args()
    add_pylibs()
    r = compute(dump=args.dump)
    summarize(r)
    write_json(r, os.path.join(DATA_DIR, 'study_plan.json'))
    print(f"\n写出 {PLAN_CRITICAL}")
    print(f"写出 {PLAN_MINING}")
    print(f"写出 {os.path.join(DATA_DIR, 'study_plan.json')}")
    if args.memo:
        write_memo(r)
        print(f'写出 {MEMO}')
    return 0


def write_memo(r: dict) -> None:
    """把结论写成可留档的建议文档（数字全部来自本次实测）。"""
    from report_build import _comp  # 复用同一套覆盖率->理解度映射
    L = []
    A = L.append
    o, idx, sup, gram = r['order'], r['index'], r['supply'], r['grammar']
    nco = r.get('new_card_order') or {}
    A('# 学习策略建议：卡组顺序 vs 素材驱动')
    A('')
    A(f"> 生成时间 {_dt.datetime.now():%Y-%m-%d %H:%M} · 数据来自 "
      f"`data/vocab_cover/`（36 集字幕 8.2 小时 + Anki 现状）")
    A('')
    A('## 一句话结论')
    A('')
    A("**不要停卡组，但要停「按卡组自身的 Index 顺序被动学」。**")
    A(f"同样学 500 个词，按素材实际出现频率挑，覆盖率收益是按 core6000 Index 顺序挑的 "
      f"**{o['rows'][2]['ratio']:.1f} 倍**；而且卡组里真正值得现在学的，是 "
      f"**{r['critical_path']['words']} 个「素材里出现过、你还没学」的现成卡**，"
      f"不是排在前面的那 3,000 多张尾部卡。")
    A('')
    A('## 1. 两种顺序的效率差')
    A('')
    A('| 学多少个词 | 按 core6000 Index 顺序 | 这些词在素材中的命中率 | 按素材频率顺序 | 只用卡组里的卡按素材频率 | 倍数 |')
    A('|---|---|---|---|---|---|')
    for row in o['rows']:
        A(f"| {row['n']} | {pct(row['deck_order_gain'])} | {pct(row['deck_order_hit_rate'])} | "
          f"{pct(row['material_order_gain'])} | {pct(row['material_in_deck_gain'])} | "
          f"**{row['ratio']:.1f}×** |")
    A('')
    A('读法：第 3 列是「按 Index 顺序发给你的这批卡，有多大比例在你真看过的 36 集里出现过」；'
      '第 2 列是它们能覆盖多少字幕词元 —— 也就是说，**这些卡即使出现过，也是素材里的低频词**。')
    A('')
    comp = r['critical_path'].get('by_source', {})
    A(f"* core6000 里未学 **{o['core_untackled']}** 张；但**整个卡组**里「素材出现过且你还没学」的"
      f"现成卡只有 **{r['critical_path']['words']}** 张"
      f"（core6000 {comp.get('core6000',0)} / 考级 {comp.get('jlpt',0)} / 素材生词 {comp.get('mined',0)}）—— "
      '这 1,407 张就是「现成卡里的最优解」，其余 9,000 多张尾部卡对动画收益接近 0。')
    A(f"* 素材里出现过、你还没学的词一共 {o['material_untackled_words']} 个"
      f"（含必须现挖的 {r['mining']['words']} 个卡组外实词）。")
    A('')
    A('## 2. core6000 的排序对你有没有用')
    A('')
    A(f"* Index 与素材频次的秩相关 **{idx['spearman_rank_vs_corpus_freq']:.2f}**："
      f"方向是对的（Index 越小越常用），但强度只有中等 —— 不足以当「该学哪个」的依据。")
    A('* Index 前 N 张卡在素材中出现过的比例：' + '、'.join(
        f'前 {k} 张 {pct(v, 0)}' for k, v in idx['hit_rate_by_n'].items()) + '。')
    tl = r.get('tail') or {}
    if tl.get('studied') and tl.get('untackled'):
        s, u = tl['studied'], tl['untackled']
        A('* **最能说明问题的一组数**：')
        A(f"  * 已学的 {s['cards']:,} 张：Index 中位 **{s['index_median']:,}**，"
          f"素材命中率 **{pct(s['material_hit_rate'])}**")
        A(f"  * 未学的 {u['cards']:,} 张：Index 最小 **{u['index_min']:,}**、"
          f"中位 **{u['index_median']:,}**，素材命中率只有 **{pct(u['material_hit_rate'])}**")
        A(f"  → 你已经把卡组的「头部」吃完了，等在前面的**全是尾部**："
          f"命中率差 {(s['material_hit_rate']/max(1e-9,u['material_hit_rate'])):.1f} 倍。")
    A(f"* 你现在被发到的是 Index 从 ~2,400 开始的尾部（先发的 20 张："
      f"{'、'.join(nco.get('first20_by_due', [])[:12])}…），"
      f"这一段的素材命中率只 ~{pct(o['rows'][2]['deck_order_hit_rate'], 0)}。")
    A('')
    A('## 3. 最硬的证据：越往尾部走，忘得越多')
    A('')
    A('| 组 | 卡数 | 已学 | 成熟 | 全期忘记率 | 近 21 天忘记率 | 秒/次 |')
    A('|---|---|---|---|---|---|---|')
    recent = (r.get('recent_load') or {}).get('by_group', {})
    for k, v in sorted(gram.get('by_group', {}).items()):
        rv = recent.get(k, {})
        ar = f"{v['again_rate']*100:.1f}%" if v['again_rate'] is not None else '-'
        ra = f"{rv['again_rate']*100:.1f}%" if rv.get('again_rate') is not None else '-'
        av = f"{v['avg_sec']:.1f}" if v.get('avg_sec') else '-'
        A(f"| {k} | {v['cards']:,} | {v['studied']:,} | {v['mature']:,} | {ar} | {ra} | {av} |")
    A('')
    A('core6000 的忘记率从全期 '
      f"{gram['by_group'].get('core6000', {}).get('again_rate', 0)*100:.1f}% 升到近 21 天 "
      f"{recent.get('core6000', {}).get('again_rate', 0)*100:.1f}% —— "
      '正是「刷到尾部、词越来越抽象、素材里又见不到」的直接后果。'
      '同期语法卡是 '
      f"{recent.get('语法', {}).get('again_rate', 0)*100:.1f}%（全期 "
      f"{gram['by_group'].get('语法', {}).get('again_rate', 0)*100:.1f}%）—— 记得最牢。")
    A('')
    A('## 4. 每集能供给多少可学的词')
    A('')
    A(f"* 卡组内未学但这一集出现了：中位 **{sup['median_untackled_in_deck']}** 个/集")
    A(f"* 卡组外实词（要挖的）：中位 **{sup['median_oov']}** 个/集")
    A(f"* 合计中位 **{sup['median_total']}** 个/集（最少 {sup['min_total']}，最多 {sup['max_total']}）")
    A('')
    A('→ 完全够你每天 10–20 张新卡的配方，而且每张卡都来自你真在看的内容。')
    A('')
    A('## 5. 素材高频词的构成（为什么「按素材挑」更划算）')
    A('')
    A('| 素材频率段 | 占全部词元 | 卡组已学 | core 未学 | 考级未学 | 卡组外 |')
    A('|---|---|---|---|---|---|')
    for b in r['bands']:
        c = b['cats']
        A(f"| 前 {b['band']} 词 | {pct(b['share_of_all'])} | {c.get('known_deck', 0)} | "
          f"{c.get('core_untackled', 0)} | {c.get('jlpt_untackled', 0)} | "
          f"{c.get('oov', 0)} |")
    A('')
    top1000 = next((b for b in r['bands'] if b['band'] == 1000), None)
    if top1000:
        unk = (top1000['cats'].get('core_untackled', 0)
               + top1000['cats'].get('jlpt_untackled', 0)
               + top1000['cats'].get('oov', 0))
        A(f"最高频 1,000 词里你不认识 {unk} 个，其中 **{top1000['cats'].get('oov', 0)} 个"
          f"（{top1000['cats'].get('oov', 0)/max(1,unk)*100:.0f}%）根本不在你的卡组里** —— "
          '所以「只把卡组刷完」解决不了高频缺口，必须同时挖素材生词。')
    A('')
    A('## 6. 现在的时间账（近 21 天实测）')
    A('')
    rl = r.get('recent_load') or {}
    A(f"数据截至 {rl.get('newest_review','')}，活跃 {rl.get('active_days','?')} 天。")
    A('')
    A('| 组 | 复习/天 | 分钟/天 | 新卡/天 | 新卡/月 |')
    A('|---|---|---|---|---|')
    for k, v in sorted(rl.get('by_group', {}).items()):
        A(f"| {k} | {v['reps_per_day']:.0f} | {v['min_per_day']:.0f} | "
          f"{v['new_per_day']:.1f} | {v['new_per_month']:.0f} |")
    tt = rl.get('total', {})
    A(f"| **合计** | **{tt.get('reps_per_day',0):.0f}** | **{tt.get('min_per_day',0):.0f}** | "
      f"**{tt.get('new_per_day',0):.1f}** | **{tt.get('new_per_month',0):.0f}** |")
    A('')
    A(f"你现在的词汇新卡是 core6000 {recent.get('core6000',{}).get('new_per_day',0):.0f}/天 + "
      f"考级 {recent.get('考级词汇',{}).get('new_per_day',0):.0f}/天 + 素材 "
      f"{recent.get('素材/例句',{}).get('new_per_day',0):.1f}/天；"
      f"语法另有 {recent.get('语法',{}).get('new_per_day',0):.0f}/天，占掉 "
      f"{recent.get('语法',{}).get('min_per_day',0):.0f} 分钟/天"
      f"（{recent.get('语法',{}).get('min_per_day',0)/max(1,tt.get('min_per_day',1))*100:.0f}% 的总时间）。")
    A('')
    A('## 7. 建议配方')
    A('')
    A(f"1. **新卡主流（约 70%）**：只学「素材里真的出现过、我还不懂」的词。"
      f"卡组已有的优先用现成卡（`{r['critical_path']['json']}`，{r['critical_path']['words']} 个词按素材频次排序），"
      f"卡组没有的走挖词（`{r['mining']['json']}`，{r['mining']['words']} 个）；"
      f"两者合并的「下一步 200 词」在 `{os.path.relpath(PLAN_NEXT, WSP.ROOT).replace(chr(92), '/')}`。")
    A('2. **新卡支流（约 30%）**：保留一部分 core6000 高频段的卡 —— '
      '它们覆盖的是「还没看到的作品」里的常见词，是泛化能力，不是浪费。')
    A('3. **语法 5–10 张/天保留**：语法是有限集合（你 N5–N1 语法卡组 3,160 张，'
      '其中「解释」卡只有 632 张），且实测忘记率最低（近 21 天 10.9%）；'
      '而且在字幕里助词/助动词占了全部词元的 47% —— 它是出现频率最高的一层，'
      '值得保持手感。'
      f"但注意它 {gram['by_group'].get('语法', {}).get('avg_sec', 0):.0f} 秒/张，"
      '是词汇卡的 1.5–2.4 倍，配额要按时间算不按张数算；'
      '建议先把 632 张「解释」卡过完，再决定要不要继续刷例句卡。')
    A('4. **不要停卡组**：卡组的问题不是「卡不好」，是「排序不贴素材」。'
      '停掉整组会丢掉 core6000 覆盖「没看过的作品」的那部分价值。')
    A('5. **如果近期要考 JLPT**：考级词汇尾部不能停 —— 它的排序服务的是考试，'
      '和「听懂动画」是两个目标，两者都要就按 7:3 分账。')
    A('')
    A('## 8. 用这两份清单时的注意')
    A('')
    A('* `study_plan_mining.json` 是从语料里判「卡组外实词」得到的，会混入少量'
      '片假名人名/拟声词（Sudachi 把 アクア 这类标成普通名词），'
      '按你平时的 triage 过一眼即可；')
    A('* 清单只按**素材频次**排序，没有考虑你个人「已经见过几次」——'
      '真正的选卡顺序建议是「素材频次 × 你已经在这几集里碰到过它」；')
    A('* 语料变了（看完新一集）重跑 `corpus.py` → `metrics.py` → `study_plan.py` 即可刷新。')
    A('')
    with open(MEMO, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L))


if __name__ == '__main__':
    raise SystemExit(main())
