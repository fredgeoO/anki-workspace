# -*- coding: utf-8 -*-
"""JitenAnimeRank 分档覆盖率：0-1万 / 1万-2万 / 2万+ 各占文本多少。

口径
----
把工作区 ``subtitles/`` 全部语料按 Sudachi 分词，每个词元映射到 Jiten Anime
名次（``data/freq/jiten_freq_Anime.csv``，Word/Form 双写法都收），再按名次档位
汇总**词元占比**与**词种占比**。

名次映射优先用 token 的**原文 surface**（文本里是 おまえ 就是 おまえ 的名次，
而不是 Sudachi 归一后的 御前），找不到再退回 normalized / dictionary / reading。
这样避免「汉字写法」把高频词误判成高频榜外（無い=4566 → ない=43）。

两种分母
--------
* ``all``    = 全部词元（含语法词/助词，去符号、非日语）
* ``vocab``  = 词汇词元（去语法词/符号）

Jiten 官方 stats 页的「典型动漫标题」覆盖率是**含语法词**的口径，看 ``all`` 列
对得上；``vocab`` 列是工作区一直用的词汇口径。

用法::
    python code/analysis/vocab_cover/jiten_rank_bands.py             # 用 corpus_tokens.json 的 word_counts
    python code/analysis/vocab_cover/jiten_rank_bands.py --retokenize  # 重新分词（surface 优先映射，最准）

产物::
    data/vocab_cover/jiten_rank_band_cover.json
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
from _deps import CORPUS_JSON, DATA_DIR, WSP, add_pylibs  # noqa: E402
from _norm import norm_word  # noqa: E402

BANDS = ((1, 10000), (10001, 20000), (20001, 10 ** 9))
CHECKPOINTS = (1000, 2000, 3000, 6000, 10000, 14000, 20000, 25100, 31800)


def load_jiten_ranks(csv_path: str) -> dict:
    """归一化词键 -> 最靠前 Jiten 名次。Word 与 Form 两种写法都收。"""
    best = {}
    with open(csv_path, encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            try:
                rank = int((row.get('Rank') or '').strip())
            except ValueError:
                continue
            if rank < 1:
                continue
            for col in ('Word', 'Form'):
                k = norm_word(row.get(col) or '')
                if not k:
                    continue
                cur = best.get(k)
                if cur is None or rank < cur:
                    best[k] = rank
    return best


def band_of(rank):
    if rank is None:
        return 'norank'
    for lo, hi in BANDS:
        if lo <= rank <= hi:
            return '%d-%s' % (lo, '20k+' if hi > 10 ** 8 else hi)
    return 'norank'


def token_rank(t, ranks):
    """token -> Jiten 名次：surface 优先，退回 normalized/dictionary/reading。"""
    for key in (norm_word(t.surface), norm_word(t.normalized),
                norm_word(t.dictionary), norm_word(t.reading)):
        if key and key in ranks:
            return ranks[key]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description='JitenAnimeRank 分档文本覆盖率')
    ap.add_argument('--csv', default=os.path.join(WSP.DATA, 'freq', 'jiten_freq_Anime.csv'))
    ap.add_argument('--corpus', default=CORPUS_JSON)
    ap.add_argument('--retokenize', action='store_true',
                    help='重新分词，按 surface 优先映射名次（更准，约 20 秒）')
    ap.add_argument('--json', default=os.path.join(DATA_DIR, 'jiten_rank_band_cover.json'))
    args = ap.parse_args()

    ranks = load_jiten_ranks(args.csv)

    tok_all = collections.Counter()      # band -> tokens（含语法词）
    tok_vocab = collections.Counter()    # band -> tokens（词汇词）
    typ_sets = collections.defaultdict(set)   # band -> 词汇词种集合

    if args.retokenize:
        add_pylibs()
        sys.path.insert(0, os.path.join(WSP.ROOT, 'code', 'common'))
        import corpus  # noqa: E402
        import jp_tok  # noqa: E402
        import srt  # noqa: E402
        vocab = jp_tok.Vocabulary.load()
        eps = corpus.discover()
        print('重新分词：%d 集' % len(eps))
        for work, no, path in eps:
            ep = srt.load_episode(path, work=work)
            for u in ep.utterances:
                for t in vocab.tokenize(u):
                    if t.is_symbol or t.bucket == 'non_jp':
                        continue
                    b = band_of(token_rank(t, ranks))
                    tok_all[b] += 1
                    if t.is_vocab:
                        tok_vocab[b] += 1
                        typ_sets[b].add(norm_word(t.surface) or norm_word(t.normalized))
    else:
        with open(args.corpus, encoding='utf-8') as fh:
            corpus_doc = json.load(fh)
        for ep in corpus_doc.get('episodes') or []:
            for w, rec in (ep.get('word_counts') or {}).items():
                n = rec[0]
                b = band_of(ranks.get(w))
                tok_all[b] += n
                tok_vocab[b] += n
                typ_sets[b].add(w)

    total_all = sum(tok_all.values()) or 1
    total_vocab = sum(tok_vocab.values()) or 1
    total_types = sum(len(s) for s in typ_sets.values()) or 1

    report = {
        'episodes': len(eps) if args.retokenize else None,
        'tokens_all': total_all,
        'tokens_vocab': total_vocab,
        'types_vocab': total_types,
        'bands': {},
        'cumulative': [],
    }
    print('词元（含语法词）%d / 词汇词元 %d / 词汇词种 %d' %
          (total_all, total_vocab, total_types))
    print('%-14s %10s %9s %12s %9s %10s %9s' %
          ('Jiten 名次档', '词元(全)', '占比(全)', '词元(词汇)', '占比(词汇)',
           '词种(词汇)', '词种占比'))
    order = ['1-10000', '10001-20000', '20001-20k+', 'norank']
    for b in order:
        report['bands'][b] = {
            'tokens_all': tok_all[b], 'share_all': round(tok_all[b] / total_all, 4),
            'tokens_vocab': tok_vocab[b], 'share_vocab': round(tok_vocab[b] / total_vocab, 4),
            'types_vocab': len(typ_sets[b]),
            'type_share': round(len(typ_sets[b]) / total_types, 4),
        }
        print('%-14s %10d %8.2f%% %12d %8.2f%% %10d %8.2f%%' %
              (b, tok_all[b], tok_all[b] / total_all * 100, tok_vocab[b],
               tok_vocab[b] / total_vocab * 100, len(typ_sets[b]),
               len(typ_sets[b]) / total_types * 100))
    print('写出', os.path.relpath(args.json, WSP.ROOT))
    with open(args.json, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
