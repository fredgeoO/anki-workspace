# -*- coding: utf-8 -*-
r"""三个词汇卡组的 JitenAnimeRank 分布与学习配比。

分析对象（``0-日本语学习::0-词汇`` 下三组）：
    0-素材生词 / 1-高频日语单词 6000 / 2-考级词汇

要回答的问题
------------
1. 三组**剩余新卡**的 JitenAnimeRank 分布差多少？已学部分又偏到哪里？
2. 以「看懂动画」为目标，每学一张卡的边际收益（动漫词元覆盖）是多少？
   各组单卡成本（实测秒/次）不同，按「收益/分钟」比较才公平。
3. 给定每天的新卡预算，三组各分几张，比例是多少？

数据来源
--------
* Anki live 收藏的只读副本（``AK.Snapshot.open(live_copy=True)``）：卡状态、字段、revlog
* ``data/vocab_cover/corpus_tokens.json``：96 集字幕的词元计数
* ``data/freq/jiten_freq_Anime.csv``：Jiten Anime 名次

产物
----
``data/vocab_cover/deck_ratio.json``
``docs/reports/词汇三卡组配比.md``（由 ``--report`` 生成）
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import json
import math
import os
import statistics
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_VC = os.path.join(_HERE, 'vocab_cover')
sys.path.insert(0, _VC)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))

from _norm import norm_word  # noqa: E402
import anki_api as AK  # noqa: E402
import textio as T  # noqa: E402

DECKS = collections.OrderedDict([
    ('mined', '0-日本语学习::0-词汇::0-素材生词'),
    ('core6000', '0-日本语学习::0-词汇::1-高频日语单词 6000'),
    ('jlpt', '0-日本语学习::0-词汇::2-考级词汇'),
])
SHORT = {'mined': '素材生词', 'core6000': 'Core6000', 'jlpt': '考级词汇'}

# 1k 一档到 20k，之后按更粗的档
BANDS = [
    (1, 1000, '1-1k'),
    (1001, 2000, '1k-2k'),
    (2001, 3000, '2k-3k'),
    (3001, 4000, '3k-4k'),
    (4001, 5000, '4k-5k'),
    (5001, 6000, '5k-6k'),
    (6001, 8000, '6k-8k'),
    (8001, 10000, '8k-10k'),
    (10001, 15000, '10k-15k'),
    (15001, 20000, '15k-20k'),
    (20001, 30000, '20k-30k'),
    (30001, 50000, '30k-50k'),
    (50001, 10 ** 9, '50k+'),
    (None, None, '无名次'),
]
BAND_LABELS = [b[2] for b in BANDS]


def band_of(rank):
    if rank is None:
        return '无名次'
    for lo, hi, label in BANDS:
        if lo is not None and lo <= rank <= hi:
            return label
    return '无名次'


def parse_rank(value):
    try:
        r = int(str(value or '').strip())
    except ValueError:
        return None
    if r <= 0 or r >= 999999:
        return None
    return r


def word_of(deck, f):
    if deck == 'jlpt':
        return (f.get('VocabKanji') or '').strip() or (f.get('VocabFurigana') or '').strip()
    return (f.get('Word') or '').strip()


def reading_of(deck, f):
    if deck == 'jlpt':
        return (f.get('VocabFurigana') or '').strip()
    return (f.get('Transliteration') or '').strip()


def pct(n, d):
    return round(100.0 * n / d, 2) if d else 0.0


def quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def load_corpus_counts(path):
    """字幕词元计数（全部 96 集合并），键已归一化。"""
    doc = json.load(open(path, encoding='utf-8'))
    counts = collections.Counter()
    episodes = 0
    for ep in doc.get('episodes') or []:
        episodes += 1
        for w, rec in (ep.get('word_counts') or {}).items():
            counts[norm_word(w)] += int(rec[0])
    return counts, episodes


def load_jiten(path):
    """Jiten 名次：归一化词 -> 最小 Rank。"""
    best = {}
    with open(path, encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            try:
                rank = int((row.get('Rank') or '').strip())
            except ValueError:
                continue
            if rank < 1:
                continue
            for col in ('Word', 'Form'):
                k = norm_word(row.get(col) or '')
                if k and (k not in best or rank < best[k]):
                    best[k] = rank
    return best


def collect(snap):
    """读三组笔记 + 卡状态，返回 {deck: [record]}。"""
    out = {}
    for key, name in DECKS.items():
        notes = snap.notes(deck=name)
        cards = {c['noteId']: c for c in snap.cards(deck=name)}
        rows = []
        for n in notes:
            c = cards.get(n['noteId'])
            if c is None:
                continue
            f = n['fields']
            word = word_of(key, f)
            rows.append({
                'nid': n['noteId'],
                'cid': c['cardId'],
                'word': word,
                'key': norm_word(word),
                'reading': norm_word(reading_of(key, f)),
                'rank': parse_rank(f.get('JitenAnimeRank')),
                'reps': c['reps'],
                'lapses': c['lapses'],
                'ivl': c['ivl'],
                'type': c['type'],
                'queue': c['queue'],
                'factor': c['factor'],
                'due': c['due'],
                'tags': n['tags'],
            })
        out[key] = rows
    return out


def deck_summary(rows):
    total = len(rows)
    learned = [r for r in rows if r['reps'] > 0]
    mature = [r for r in learned if r['type'] == 2 and r['ivl'] >= 21]
    new = [r for r in rows if r['reps'] == 0]
    return total, learned, mature, new


def band_table(rows):
    c = collections.Counter(band_of(r['rank']) for r in rows)
    n = len(rows)
    return {label: {'n': c.get(label, 0), 'pct': pct(c.get(label, 0), n)}
            for label in BAND_LABELS}


def rank_stats(rows):
    ranks = sorted(r['rank'] for r in rows if r['rank'] is not None)
    if not ranks:
        return {'n': 0}
    return {
        'n': len(ranks),
        'median': statistics.median(ranks),
        'p25': quantile(ranks, 0.25),
        'p75': quantile(ranks, 0.75),
        'p90': quantile(ranks, 0.90),
        'share_le_6000': pct(sum(1 for x in ranks if x <= 6000), len(rows)),
        'share_le_10000': pct(sum(1 for x in ranks if x <= 10000), len(rows)),
        'share_gt_20000': pct(sum(1 for x in ranks if x > 20000), len(rows)),
    }


def revlog_stats(snap):
    """近 90 天各组的复习次数、秒/次、通过率；近 30 天新卡引入量。

    另外算「首月成本」：45-75 天前第一次出现的卡，从第一次复习起 30 天内的
    总用时 / 卡数，包含学习步与首月复习，单位分钟。
    """
    now_ms = int(time.time() * 1000)
    cut90 = now_ms - 90 * 86400 * 1000
    cut30 = now_ms - 30 * 86400 * 1000
    cut45 = now_ms - 45 * 86400 * 1000
    cut75 = now_ms - 75 * 86400 * 1000

    deck_of = {}
    for key, name in DECKS.items():
        for c in snap.cards(deck=name):
            deck_of[c['cardId']] = key

    by = {k: {'reviews': 0, 'review_ms': [], 'pass': 0, 'again': 0,
              'review_type2': 0, 'again_type2': 0,
              'new_cards_30d': 0} for k in DECKS}
    # 逐卡：[(id, timeMs, type)]，只保留三组卡
    per_card = collections.defaultdict(list)

    rl = snap.revlog(since_ms=cut90)
    first_seen = {}
    for r in rl:
        key = deck_of.get(r['cardId'])
        if key is None:
            continue
        d = by[key]
        d['reviews'] += 1
        if 0 < r['timeMs'] < 120000:
            d['review_ms'].append(r['timeMs'])
        if r['ease'] > 1:
            d['pass'] += 1
        if r['ease'] == 1:
            d['again'] += 1
        if r['type'] == 2:
            d['review_type2'] += 1
            if r['ease'] == 1:
                d['again_type2'] += 1
        per_card[r['cardId']].append((r['revlogId'], r['timeMs'], r['type']))
        f = first_seen.get(r['cardId'])
        if f is None or r['revlogId'] < f:
            first_seen[r['cardId']] = r['revlogId']

    for cid, rid in first_seen.items():
        if rid >= cut30 and cid in deck_of:
            by[deck_of[cid]]['new_cards_30d'] += 1

    # 45-75 天前首见的卡：首月成本；近 30 天首见的卡：首日成本（不删失）
    cohort = {k: {'cards': 0, 'total_ms': 0, 'first_day_ms': 0} for k in DECKS}
    recent_first_day = {k: {'cards': 0, 'first_day_ms': 0} for k in DECKS}
    for cid, rid in first_seen.items():
        if cid not in deck_of:
            continue
        key = deck_of[cid]
        events = sorted(per_card[cid])
        if not events:
            continue
        first_id = events[0][0]
        first_day = first_id // 86400000
        day_ms = sum(tms for eid, tms, _typ in events if eid // 86400000 == first_day)
        if cut75 <= rid <= cut45:
            cohort[key]['cards'] += 1
            for eid, tms, _typ in events:
                if eid <= first_id + 30 * 86400 * 1000:
                    cohort[key]['total_ms'] += tms
                if eid // 86400000 == first_day:
                    cohort[key]['first_day_ms'] += tms
        if rid >= cut30:
            recent_first_day[key]['cards'] += 1
            recent_first_day[key]['first_day_ms'] += day_ms

    out = {}
    for key, d in by.items():
        times = sorted(d['review_ms'])
        ch = cohort[key]
        out[key] = {
            'reviews_90d': d['reviews'],
            'sec_per_review_mean': round(statistics.mean(times) / 1000, 2) if times else None,
            'sec_per_review_median': round(statistics.median(times) / 1000, 2) if times else None,
            'pass_rate': pct(d['pass'], d['reviews']),
            'again_rate': pct(d['again'], d['reviews']),
            'review_pass_rate': pct(d['review_type2'] - d['again_type2'], d['review_type2']),
            'reviews_per_day_30d': round(d['reviews'] / 30.0, 1),
            'new_cards_30d': d['new_cards_30d'],
            'new_cards_per_day_30d': round(d['new_cards_30d'] / 30.0, 1),
            'cohort_cards': ch['cards'],
            'first_month_min_per_card': round(ch['total_ms'] / ch['cards'] / 60000, 2)
            if ch['cards'] else None,
            'first_day_min_per_card': round(ch['first_day_ms'] / ch['cards'] / 60000, 2)
            if ch['cards'] else None,
            'recent_cards_30d': recent_first_day[key]['cards'],
            'recent_first_day_min_per_card': round(
                recent_first_day[key]['first_day_ms'] / recent_first_day[key]['cards'] / 60000, 2)
            if recent_first_day[key]['cards'] else None,
        }
    return out


def band_prior(corpus_counts, jiten):
    """按 Jiten 名次分档，估「学一个该档随机词」在 96 集里能覆盖多少词元。

    返回 {band_label: {'words': n, 'tokens': t, 'per_word': t/n}}
    """
    band_words = collections.Counter()
    for r in jiten.values():
        band_words[band_of(r)] += 1
    band_tokens = collections.Counter()
    for w, n in corpus_counts.items():
        r = jiten.get(w)
        if r is None:
            band_tokens['无名次'] += n
        else:
            band_tokens[band_of(r)] += n
    total_tokens = sum(corpus_counts.values())
    out = {}
    for label in BAND_LABELS:
        words = band_words.get(label, 0)
        tokens = band_tokens.get(label, 0)
        out[label] = {
            'jiten_words': words,
            'corpus_tokens': tokens,
            'token_share': round(tokens / total_tokens, 6) if total_tokens else 0,
            'per_word': (tokens / words) if words else 0.0,
            'per_1000_words': (tokens / words * 1000) if words else 0.0,
        }
    return out


def main():
    ap = argparse.ArgumentParser(description='三词汇卡组 JitenAnimeRank 配比分析')
    ap.add_argument('--out', default=os.path.join(
        AK.WSP.DATA, 'vocab_cover', 'deck_ratio.json'))
    ap.add_argument('--corpus', default=os.path.join(
        AK.WSP.DATA, 'vocab_cover', 'corpus_tokens.json'))
    ap.add_argument('--jiten', default=os.path.join(
        AK.WSP.DATA, 'freq', 'jiten_freq_Anime.csv'))
    args = ap.parse_args()

    corpus_counts, episodes = load_corpus_counts(args.corpus)
    jiten = load_jiten(args.jiten)
    print('语料：%d 集，词元 %d，词种 %d；Jiten 表 %d 词' %
          (episodes, sum(corpus_counts.values()), len(corpus_counts), len(jiten)))

    with AK.Snapshot.open(live_copy=True) as snap:
        decks = collect(snap)
        rl = revlog_stats(snap)

    prior = band_prior(corpus_counts, jiten)

    # 词 -> 出现在哪些组；全库已学/成熟集合
    key_decks = collections.defaultdict(set)
    learned_any = set()
    mature_any = set()
    for key, rows in decks.items():
        for r in rows:
            if r['key']:
                key_decks[r['key']].add(key)
            if r['reps'] > 0:
                learned_any.add(r['key'])
                if r['type'] == 2 and r['ivl'] >= 21:
                    mature_any.add(r['key'])

    report = {
        'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
        'corpus': {'episodes': episodes,
                   'tokens': sum(corpus_counts.values()),
                   'types': len(corpus_counts)},
        'band_prior': prior,
        'decks': {},
        'overlap': {},
        'allocation': {},
    }

    # 每组的词条 / 已学 / 新卡明细
    for key, rows in decks.items():
        total, learned, mature, new = deck_summary(rows)
        # 加语料计数
        for r in rows:
            n = corpus_counts.get(r['key'], 0)
            if n == 0 and r['reading']:
                n = corpus_counts.get(r['reading'], 0)
            r['corpus'] = n
            r['value'] = float(n) if n else prior[band_of(r['rank'])]['per_word']
            r['learned_anywhere'] = r['key'] in learned_any
            r['new_anywhere'] = any(
                x['key'] == r['key'] and x['reps'] == 0 for x in rows)
        new_unique = [r for r in new if not r['learned_anywhere']]
        seen = set()
        deduped = []
        for r in new_unique:
            if r['key'] in seen:
                continue
            seen.add(r['key'])
            deduped.append(r)
        new_unique = deduped
        new_excl = [r for r in new_unique if key_decks[r['key']] == {key}]
        learned_tail = [r for r in learned if r['rank'] and r['rank'] > 20000]
        learned_mid = [r for r in learned if r['rank'] and 10000 < r['rank'] <= 20000]
        learned_le3k = [r for r in learned if r['rank'] and r['rank'] <= 3000]
        new_tail = [r for r in new if r['rank'] and r['rank'] > 20000]
        new_gt10k = [r for r in new if r['rank'] and r['rank'] > 10000]
        new_mid = [r for r in new if r['rank'] and 10000 < r['rank'] <= 20000]
        report['progress'] = report.get('progress', {})
        report['progress'][key] = {
            'learned': len(learned),
            'learned_le_3000': len(learned_le3k),
            'learned_10k_20k': len(learned_mid),
            'learned_10k_20k_corpus_tokens': sum(r['corpus'] for r in learned_mid),
            'learned_gt_20000': len(learned_tail),
            'learned_gt_20000_corpus_tokens': sum(r['corpus'] for r in learned_tail),
            'new_gt_10000': len(new_gt10k),
            'new_gt_20000': len(new_tail),
            'new_gt_10000_pct': pct(len(new_gt10k), len(new)),
            'new_gt_20000_pct': pct(len(new_tail), len(new)),
            'new_10k_20k_corpus_tokens': sum(r['corpus'] for r in new_mid),
            'new_gt_20000_corpus_tokens': sum(r['corpus'] for r in new_tail),
        }

        dup_new = [r for r in new if r['learned_anywhere']]
        dup_other_new = [r for r in new_unique if len(key_decks[r['key']]) > 1]

        def cov(rs):
            return sum(r['corpus'] for r in rs)
        band_detail = {}
        for label in BAND_LABELS:
            rs = [r for r in new_unique if band_of(r['rank']) == label]
            hits = [r for r in rs if r['corpus'] > 0]
            band_detail[label] = {
                'n': len(rs),
                'hit': len(hits),
                'hit_pct': pct(len(hits), len(rs)),
                'tokens': cov(rs),
                'tokens_per_card': round(cov(rs) / len(rs), 2) if rs else 0,
                'mean_hit_tokens': round(sum(r['corpus'] for r in hits) / len(hits), 2)
                if hits else 0,
            }
        report['decks'][key] = {
            'name': DECKS[key],
            'total': total,
            'learned': len(learned),
            'mature': len(mature),
            'new': len(new),
            'learned_pct': pct(len(learned), total),
            'mature_pct': pct(len(mature), total),
            'bands_all': band_table(rows),
            'bands_learned': band_table(learned),
            'bands_new': band_table(new),
            'bands_new_unique': band_table(new_unique),
            'rank_all': rank_stats(rows),
            'rank_learned': rank_stats(learned),
            'rank_new': rank_stats(new),
            'rank_new_unique': rank_stats(new_unique),
            'revlog': rl[key],
            'new_already_learned_elsewhere': len(dup_new),
            'new_unique': len(new_unique),
            'new_unique_exclusive': len(new_excl),
            'new_shared_with_other_new': len(dup_other_new),
            'new_corpus_hits': sum(1 for r in new if r['corpus'] > 0),
            'new_corpus_hit_pct': pct(sum(1 for r in new if r['corpus'] > 0), len(new)),
            'new_unique_corpus_tokens': cov(new_unique),
            'new_exclusive_corpus_tokens': cov(new_excl),
            'band_detail_new_unique': band_detail,
            'top_new_words': [
                {'word': r['word'], 'rank': r['rank'], 'corpus': r['corpus']}
                for r in sorted(
                    [x for x in new_unique if x['rank'] and x['rank'] <= 6000],
                    key=lambda x: -x['corpus'])[:15]],
        }
        print('\n== %s (%s) 总 %d / 已学 %d / 成熟 %d / 新 %d' %
              (SHORT[key], key, total, len(learned), len(mature), len(new)))
        print('  新卡名次：', report['decks'][key]['rank_new'])
        print('  新卡分档：', {k: v['pct'] for k, v in report['decks'][key]['bands_new'].items()})
        print('  已学分档：', {k: v['pct'] for k, v in report['decks'][key]['bands_learned'].items()})
        print('  新卡去重后 %d（独有 %d，与别组新卡重复 %d，已被别组学过 %d）' %
              (len(new_unique), len(new_excl), len(dup_other_new), len(dup_new)))
        print('  覆盖命中 %d/%d=%.1f%%；去重新词覆盖词元 %d / 独有 %d' %
              (sum(1 for r in new if r['corpus'] > 0), len(new),
               pct(sum(1 for r in new if r['corpus'] > 0), len(new)),
               cov(new_unique), cov(new_excl)))
        print('  %-9s %5s %7s %8s %8s' % ('档', '新词', '命中%', '词元', '词元/卡'))
        for label in BAND_LABELS:
            bd = band_detail[label]
            if bd['n']:
                print('  %-9s %5d %6.1f%% %8d %8.2f' %
                      (label, bd['n'], bd['hit_pct'], bd['tokens'], bd['tokens_per_card']))
        pg = report['progress'][key]
        print('  已学 %d：≤3k %d / 10-20k %d / >20k %d（这些 >20k 卡覆盖词元 %d）；'
              '新卡 >10k %d (%.1f%%) / >20k %d (%.1f%%)' %
              (pg['learned'], pg['learned_le_3000'], pg['learned_10k_20k'],
               pg['learned_gt_20000'], pg['learned_gt_20000_corpus_tokens'],
               pg['new_gt_10000'], pg['new_gt_10000_pct'],
               pg['new_gt_20000'], pg['new_gt_20000_pct']))

    # 两两重叠（按词键）
    print('\n== 重叠')
    keys = list(DECKS)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            sa = {r['key'] for r in decks[a] if r['key']}
            sb = {r['key'] for r in decks[b] if r['key']}
            inter = sa & sb
            la = {r['key'] for r in decks[a] if r['reps'] > 0}
            lb = {r['key'] for r in decks[b] if r['reps'] > 0}
            report['overlap']['%s|%s' % (a, b)] = {
                'shared_words': len(inter),
                'pct_of_%s' % a: pct(len(inter), len(sa)),
                'pct_of_%s' % b: pct(len(inter), len(sb)),
                'shared_new': sum(1 for k in inter
                                  if any(r['key'] == k and r['reps'] == 0 for r in decks[a])
                                  and any(r['key'] == k and r['reps'] == 0 for r in decks[b])),
                'learned_in_%s_new_in_%s' % (a, b): len(la & {r['key'] for r in decks[b] if r['reps'] == 0}),
                'learned_in_%s_new_in_%s' % (b, a): len(lb & {r['key'] for r in decks[a] if r['reps'] == 0}),
            }
            print('  %s x %s: 共享词 %d (%.1f%% / %.1f%%)，双方都未学 %d，%s已学→%s未学 %d' %
                  (SHORT[a], SHORT[b], len(inter),
                   pct(len(inter), len(sa)), pct(len(inter), len(sb)),
                   report['overlap']['%s|%s' % (a, b)]['shared_new'],
                   SHORT[a], SHORT[b],
                   report['overlap']['%s|%s' % (a, b)]['learned_in_%s_new_in_%s' % (a, b)]))

    # ------------------------------------------------------------------
    # 全库去重后的「可学新词」供给：每个词按最低名次归一次
    # ------------------------------------------------------------------
    best_new = {}   # key -> (rank, corpus, set(decks))
    for key, rows in decks.items():
        for r in rows:
            if r['reps'] > 0 or r['learned_anywhere'] or not r['key']:
                continue
            cur = best_new.get(r['key'])
            cand_rank = r['rank'] if r['rank'] is not None else 10 ** 9
            if cur is None:
                best_new[r['key']] = [cand_rank, r['corpus'], {key}]
            else:
                cur[2].add(key)
                if cand_rank < cur[0]:
                    cur[0], cur[1] = cand_rank, r['corpus']
    union = collections.Counter()
    union_tokens = collections.Counter()
    for k, (rank, corpus, _dks) in best_new.items():
        b = band_of(None if rank >= 10 ** 9 else rank)
        union[b] += 1
        union_tokens[b] += corpus
    report['union_new'] = {
        'total_words': len(best_new),
        'total_corpus_tokens': sum(union_tokens.values()),
        'bands': {label: {'words': union.get(label, 0),
                          'tokens': union_tokens.get(label, 0)}
                  for label in BAND_LABELS},
    }
    print('\n== 全库去重后可学新词 %d 个，覆盖词元 %d' %
          (len(best_new), sum(union_tokens.values())))
    cum_w = cum_t = 0
    for label in BAND_LABELS:
        cum_w += union.get(label, 0)
        cum_t += union_tokens.get(label, 0)
        print('  %-9s 新词 %5d  词元 %6d  累计词 %5d  累计词元 %6d' %
              (label, union.get(label, 0), union_tokens.get(label, 0), cum_w, cum_t))

    # 分配规则：素材优先；≤10k 的 core/jlpt 重复词给 Core（有例句音频）；
    # >10k 的重复词给便宜的考级。得到一张「按名次档的学习方案」。
    def assign_deck(dks, rank):
        if 'mined' in dks:
            return 'mined'
        if rank is not None and rank <= 10000 and 'core6000' in dks:
            return 'core6000'
        if 'jlpt' in dks:
            return 'jlpt'
        return next(iter(dks))

    plan = {label: collections.Counter() for label in BAND_LABELS}
    plan_tokens = {label: collections.Counter() for label in BAND_LABELS}
    for k, (rank, corpus, dks) in best_new.items():
        lab = band_of(None if rank >= 10 ** 9 else rank)
        dk = assign_deck(dks, None if rank >= 10 ** 9 else rank)
        plan[lab][dk] += 1
        plan_tokens[lab][dk] += corpus
    report['supply_plan'] = {
        label: {dk: {'cards': plan[label][dk], 'tokens': plan_tokens[label][dk]}
                for dk in DECKS} for label in BAND_LABELS}
    print('\n== 按「素材优先 / ≤10k 重复词给 Core / >10k 给考级」分配后的供给')
    print('  %-9s %8s %8s %8s' % ('档', '素材', 'Core', '考级'))
    for label in BAND_LABELS:
        if sum(plan[label].values()):
            print('  %-9s %8d %8d %8d' %
                  (label, plan[label]['mined'], plan[label]['core6000'], plan[label]['jlpt']))
    for thresh, name in ((6000, '≤6k'), (10000, '≤10k'), (20000, '≤20k')):
        c = collections.Counter()
        for label in BAND_LABELS:
            for lo, hi, lab in BANDS:
                if lab == label and lo is not None and lo <= thresh:
                    c.update(plan[label])
        tot = sum(c.values())
        print('  %s: %s 比例 %s' % (name, dict(c),
                                   {k: round(100.0 * c[k] / tot, 1) for k in DECKS}))

    # 每组在每档的「独有 / 与别组共享」新词数
    print('\n== 各组新词供给（独有 = 只有这组有；共享 = 别组也有同样的词）')
    supply = {}
    for key, rows in decks.items():
        d = {}
        for label in BAND_LABELS:
            rs = [r for r in rows if r['reps'] == 0 and not r['learned_anywhere']
                  and band_of(r['rank']) == label]
            excl = sum(1 for r in rs if key_decks[r['key']] == {key})
            d[label] = {'all': len(rs), 'exclusive': excl, 'shared': len(rs) - excl}
        supply[key] = d
        tot = {x: sum(d[l][x] for l in BAND_LABELS) for x in ('all', 'exclusive', 'shared')}
        print(' ', SHORT[key], tot)
    report['supply_by_band'] = supply

    # 复习负担按档：用到期间隔估每天复习量
    print('\n== 复习负担（按当前间隔估）')
    burden = {}
    for key, rows in decks.items():
        b = collections.Counter()
        for r in rows:
            if r['reps'] > 0 and r['ivl'] > 0:
                b[band_of(r['rank'])] += 1.0 / r['ivl']
        burden[key] = {label: round(b[label], 2) for label in BAND_LABELS}
        print(' ', SHORT[key], {k: v for k, v in burden[key].items() if v})
    report['review_burden_per_day'] = burden

    # ------------------------------------------------------------------
    # 配比模拟：按「每张新卡的边际收益 / 首月成本」做贪心
    # ------------------------------------------------------------------
    def cost_of(key):
        r = rl[key]
        if r.get('first_month_min_per_card'):
            return r['first_month_min_per_card']
        fd = r.get('recent_first_day_min_per_card')
        return round(fd * 2.2, 2) if fd else 2.0

    costs = {k: cost_of(k) for k in DECKS}
    print('\n== 首月单卡成本（分钟）', costs)

    def sim(value_fn, per_day, days, caps=None, quality=None):
        caps = caps or {}
        quality = quality or {}
        q = {}
        for key, rows in decks.items():
            cap = caps.get(key)
            q[key] = sorted(
                [r for r in rows if r['reps'] == 0 and r['key'] not in learned_any
                 and (cap is None or (r['rank'] is not None and r['rank'] <= cap))],
                key=lambda r: (r['rank'] is None, r['rank'] or 10 ** 9, -r['corpus']))
        selected = set(learned_any)
        counts = collections.Counter()
        picked = []
        coverage = 0
        steps = per_day * days
        for _ in range(steps):
            best_key, best_score = None, -1.0
            for key in DECKS:
                while q[key] and q[key][0]['key'] in selected:
                    q[key].pop(0)
                if not q[key]:
                    continue
                r = q[key][0]
                score = value_fn(r) * quality.get(key, 1.0) / costs[key]
                if score > best_score:
                    best_key, best_score = key, score
            if best_key is None:
                break
            r = q[best_key].pop(0)
            selected.add(r['key'])
            counts[best_key] += 1
            coverage += r['corpus']
            picked.append(r)
        total = sum(counts.values())
        band_mix = collections.Counter(band_of(r['rank']) for r in picked)
        return {
            'per_day': per_day, 'days': days, 'total': total,
            'counts': {k: counts[k] for k in DECKS},
            'ratio': {k: round(100.0 * counts[k] / total, 1) if total else 0 for k in DECKS},
            'time_min_total': round(sum(counts[k] * costs[k] for k in DECKS), 1),
            'coverage_tokens': coverage,
            'coverage_per_min': round(coverage / max(1e-9, sum(counts[k] * costs[k] for k in DECKS)), 2),
            'band_mix': {label: band_mix.get(label, 0) for label in BAND_LABELS},
            'le_6000_pct': pct(sum(1 for r in picked if r['rank'] and r['rank'] <= 6000), len(picked)),
            'le_10000_pct': pct(sum(1 for r in picked if r['rank'] and r['rank'] <= 10000), len(picked)),
        }

    scenarios = {
        'general': lambda r: prior[band_of(r['rank'])]['per_word'],
        'corpus': lambda r: r['corpus'] + 0.05 * prior[band_of(r['rank'])]['per_word'],
        'blend': lambda r: 0.5 * prior[band_of(r['rank'])]['per_word'] + 0.5 * r['corpus'],
    }
    for name, fn in scenarios.items():
        print('\n-- 情景 %s' % name)
        report['allocation'][name] = []
        for days in (90, 180, 365):
            s = sim(fn, 30, days)
            report['allocation'][name].append(s)
            print('  %3d 天×30: %s | 比例 %s | %.0f 分钟 | 覆盖 %d 词元 | %.2f 词元/分钟 | ≤6k %.0f%%' %
                  (days, s['counts'], s['ratio'], s['time_min_total'],
                   s['coverage_tokens'], s['coverage_per_min'], s['le_6000_pct']))

    # 加上名次闸门：素材 ≤20k，Core/考级 ≤10k（只学对动漫有用的部分）
    caps = {'mined': 20000, 'core6000': 10000, 'jlpt': 10000}
    print('\n-- 加名次闸门（素材≤20k / Core、考级≤10k），180 天×30，按例句卡价值倍数 q')
    report['allocation']['capped'] = []
    for qv in (1.0, 1.5, 2.0):
        s = sim(scenarios['blend'], 30, 180, caps=caps,
                quality={'mined': qv, 'core6000': qv, 'jlpt': 1.0})
        s['quality_multiplier'] = qv
        report['allocation']['capped'].append(s)
        print('  q=%.1f: %s | 比例 %s | 覆盖 %d 词元 | %.2f 词元/分钟 | ≤6k %.0f%%' %
              (qv, s['counts'], s['ratio'], s['coverage_tokens'],
               s['coverage_per_min'], s['le_6000_pct']))

    # 当前配比（近 30 天实测）作为对照
    def sim_fixed(per_day_map, days, caps=None):
        caps = caps or {}
        q = {}
        for key, rows in decks.items():
            cap = caps.get(key)
            q[key] = sorted(
                [r for r in rows if r['reps'] == 0 and r['key'] not in learned_any
                 and (cap is None or (r['rank'] is not None and r['rank'] <= cap))],
                key=lambda r: (r['rank'] is None, r['rank'] or 10 ** 9, -r['corpus']))
        selected = set(learned_any)
        counts = collections.Counter()
        picked = []
        coverage = 0
        for _ in range(days):
            for key, n in per_day_map.items():
                for _ in range(int(round(n))):
                    while q[key] and q[key][0]['key'] in selected:
                        q[key].pop(0)
                    if not q[key]:
                        break
                    r = q[key].pop(0)
                    selected.add(r['key'])
                    counts[key] += 1
                    coverage += r['corpus']
                    picked.append(r)
        total = sum(counts.values())
        return {
            'per_day': per_day_map, 'days': days, 'total': total,
            'counts': {k: counts[k] for k in DECKS},
            'ratio': {k: round(100.0 * counts[k] / total, 1) if total else 0 for k in DECKS},
            'coverage_tokens': coverage,
            'time_min_total': round(sum(counts[k] * costs[k] for k in DECKS), 1),
            'coverage_per_min': round(coverage / max(1e-9, sum(counts[k] * costs[k] for k in DECKS)), 2),
            'le_6000_pct': pct(sum(1 for r in picked if r['rank'] and r['rank'] <= 6000), len(picked)),
            'le_10000_pct': pct(sum(1 for r in picked if r['rank'] and r['rank'] <= 10000), len(picked)),
        }

    cur_mix = {k: rl[k]['new_cards_per_day_30d'] for k in DECKS}
    print('\n-- 对照：维持近 30 天实测配比 %s，180 天' % cur_mix)
    cur = sim_fixed(cur_mix, 180)
    report['allocation']['current_mix_180d'] = cur
    print('  %s | 比例 %s | 覆盖 %d 词元 | %.2f 词元/分钟 | ≤6k %.0f%%' %
          (cur['counts'], cur['ratio'], cur['coverage_tokens'],
           cur['coverage_per_min'], cur['le_6000_pct']))
    cur_cap = sim_fixed(cur_mix, 180, caps={'mined': 20000, 'core6000': 10000, 'jlpt': 10000})
    report['allocation']['current_mix_capped_180d'] = cur_cap
    print('  同名次闸门后 %s | 比例 %s | 覆盖 %d 词元 | %.2f 词元/分钟 | ≤6k %.0f%%' %
          (cur_cap['counts'], cur_cap['ratio'], cur_cap['coverage_tokens'],
           cur_cap['coverage_per_min'], cur_cap['le_6000_pct']))

    T.dump_json(report, args.out)
    print('\n写出', os.path.relpath(args.out, AK.WSP.ROOT))

    # 存一份 band prior 供报告用
    prior_path = os.path.join(AK.WSP.DATA, 'vocab_cover', 'deck_ratio_prior.json')
    T.dump_json(prior, prior_path)


if __name__ == '__main__':
    raise SystemExit(main())
