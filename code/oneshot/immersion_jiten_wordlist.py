# -*- coding: utf-8 -*-
"""按 Jiten 动漫词频榜取词，写成 ImmersionKit 的输入词表 ``data/immersion/words.txt``。

口径（用户 2026-10-15 要求）
---------------------------
* 起点：Jiten Anime 词频表 ``data/freq/jiten_freq_Anime.csv``（``Word,Form,Rank``），
  **只取 Rank ≤ --max-rank**（默认 10000，即「JitenAnimeRank 10000 以下」）；
* 用 ``Word`` 列（汉字写法；假名词就是本身）当词形，``Form`` 只当读音备注 ——
  文档 §3 的选词口径用的是 `pipeline.rebuild_known_index()`，它按**词形**建键，
  所以拿 CSV 的 Word 列喂进去才和 core6000/考级 的键同口径；
* 剔除（与 ``immersionkit.cmd_fetch`` 完全同一套判据，不另立口径）：
  1. 已在 core6000 / 考级词汇（``rebuild_known_index()`` 的 canonical + variant）；
  2. 两个目标牌组里已有 ``Word`` 的词；
* 再剔三类**没有学习价值**的噪声（可用 ``--keep-*`` 关掉，回到「严格按字面口径」）：
  1. ``--keep-junk``    ：句片段/带标点/超长（Jiten 表里混着
     ``あっ?もしかして忘れてた?…`` 这种整句，查 ImmersionKit 没有意义）；
  2. ``--keep-function``：整串都是语法胶水（助詞/助動詞/接頭辞/接尾辞）——
     ``の``『は』``に`` 做卡没有意义；
  3. ``--keep-gloss-covered``：**假名写法**的词，其 Sudachi 规范形已在
     core6000/考级 里（``もの``→物、``いう``→言う、``きょう``→今日）——
     同一个词的另一种写法，做出来就是已知词的重复卡。

产物
----
* ``data/immersion/words.txt``    —— 给 ``cli.py immersion fetch`` 吃的词表（按 Rank 升序）；
* ``data/immersion/candidates.tsv``—— 逐条判定（rank / 词 / 读音 / 词性 / 留否 / 原因）；
* ``docs/reports/…md``            —— 人看的口径与计数报告。

只读；不写 Anki、不连网（AnkiConnect 只用来查「目标牌组已有」）。
"""
import argparse
import csv
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'execution'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'analysis', 'vocab_cover'))

import _deps                     # noqa: E402  把 data/pylibs 挂上 sys.path
_deps.add_pylibs()
import anki_api as AK            # noqa: E402
import immersionkit as IK        # noqa: E402  existing_words（与 fetch 同一道闸门）
import paths as WSP              # noqa: E402
import pipeline as P             # noqa: E402  norm / rebuild_known_index
import textio                    # noqa: E402

KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
# Jiten 表里的「整句」噪声：句读/引号/省略号一律视作句片段
JUNK_PUNCT = re.compile(r'[?!！？。、，,…‥・「」『』（）()\[\]【】〈〉《》"\'’“”~〜]')
GLUE_POS = {'助詞', '助動詞', '接頭辞', '接尾辞', '補助記号', '記号', '空白', '接続助詞'}
MAX_WORD_LEN = 12                # 超过这个长度基本是句子/惯用句长串

CSV_DEFAULT = os.path.join(WSP.DATA, 'freq', 'jiten_freq_Anime.csv')
WORDS_DEFAULT = os.path.join(WSP.DATA_IMMERSION, 'words.txt')
TSV_DEFAULT = os.path.join(WSP.DATA_IMMERSION, 'candidates.tsv')


def pos_of(tagger, word):
    """→ (pos 串, 规范形集合)。多词素记 ``短语``；规范形用于查「另一种写法是否已收」。"""
    ms = tagger(word)
    if not ms:
        return '', set()
    pos = [m.part_of_speech() for m in ms]
    forms = set()
    if len(ms) == 1:
        for f in (ms[0].normalized_form(), ms[0].dictionary_form(), ms[0].surface()):
            if f:
                forms.add(P.norm(f))
        p = pos[0]
        return '%s|%s' % (p[0], p[1] if len(p) > 1 else '*'), forms
    # 多词素：整串留作键；每个词素的规范形不参与判定（会不会误伤短语由 --keep-* 决定）
    return '短语', {P.norm(word)}


def is_glue(pos):
    if not pos or pos == '短语':
        return False
    return pos.split('|')[0] in GLUE_POS


def load_rows(path, max_rank, min_rank):
    rows = []
    for r in csv.DictReader(textio.read_text(path).splitlines()):
        try:
            rank = int((r.get('Rank') or '').strip())
        except ValueError:
            continue
        if not (min_rank <= rank <= max_rank):
            continue
        word = (r.get('Word') or '').strip()
        form = (r.get('Form') or '').strip()
        if word:
            rows.append((rank, word, form))
    rows.sort(key=lambda x: (x[0], x[1]))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description='Jiten 榜 → ImmersionKit 词表')
    ap.add_argument('--csv', default=CSV_DEFAULT, help='Jiten 词频表 CSV')
    ap.add_argument('--max-rank', type=int, default=10000, help='只取 Rank ≤ 这个数')
    ap.add_argument('--min-rank', type=int, default=1)
    ap.add_argument('--out', default=WORDS_DEFAULT, help='写出的词表')
    ap.add_argument('--tsv', default=TSV_DEFAULT, help='逐条判定明细')
    ap.add_argument('--report', default='', help='人看的报告（默认 docs/reports/…）')
    ap.add_argument('--limit', type=int, default=0, help='只取前 N 个（试跑）')
    ap.add_argument('--known-only', action='store_true',
                    help='反过来：只留 core6000/考级**已有**的词（给例句牌组补对白例句用）')
    ap.add_argument('--words-only', action='store_true',
                    help='只留单词（剔掉多词素短语：ように/として/具合が悪い 这类）')
    ap.add_argument('--keep-junk', action='store_true', help='不剔句片段/带标点/超长')
    ap.add_argument('--keep-function', action='store_true', help='不剔纯语法胶水')
    ap.add_argument('--keep-gloss-covered', action='store_true',
                    help='不剔「假名写法、规范形已收」的词')
    ap.add_argument('--no-anki', action='store_true', help='不查目标牌组已有（离线）')
    a = ap.parse_args(argv)

    rows = load_rows(a.csv, a.max_rank, a.min_rank)
    print('Jiten 表 %s：Rank ≤ %d 的条目 %d 条'
          % (os.path.relpath(a.csv, WSP.ROOT), a.max_rank, len(rows)))

    print('拉取 core6000/考级 索引…')
    canon, variant = P.rebuild_known_index()
    have = set() if a.no_anki else IK.existing_words()
    print('  已知词形 %d · 变体 %d · 目标牌组已有 %d'
          % (len(canon), len(variant), len(have)))

    from sudachipy import Dictionary, SplitMode
    _d = Dictionary(dict='core')
    _tok = (getattr(_d, 'tokenizer', None) or _d.create)()

    def tagger(word):                                  # C 单位（整词优先）
        return _tok.tokenize(word, SplitMode.C)

    keep, dropped, seen = [], [], {}
    for rank, word, form in rows:
        pos, keys = pos_of(tagger, word)
        decision, reason = 'keep', ''
        if not a.keep_junk and (JUNK_PUNCT.search(word) or len(word) > MAX_WORD_LEN):
            decision, reason = 'drop', '句片段/带标点/超长'
        elif not a.keep_function and is_glue(pos):
            decision, reason = 'drop', '纯语法胶水（%s）' % pos
        elif a.words_only and pos == '短语':
            decision, reason = 'drop', '多词素短语（--words-only）'
        else:
            own = P.norm(word)
            own_hit = own in canon or own in variant
            hit = ''
            for k in keys:
                if k and (k in canon or k in variant):
                    hit = k
                    break
            if a.known_only:
                # 反过来的口径：只留 core6000/考级里**已有**的词。
                # 这些词的例句卡只进例句牌组（练对白听力），不建素材生词卡。
                if not hit:
                    decision, reason = 'drop', '不在 core6000/考级'
                elif not own_hit:
                    decision, reason = 'drop', '假名写法（正字 %s 已在）' % hit
                elif own in have:
                    decision, reason = 'drop', '目标牌组已有'
            elif hit:
                where = ((canon.get(hit) or 'core6000/考级') if hit in canon
                         else '%s（归一为 %s）' % (canon.get(variant[hit], 'core6000/考级'),
                                              variant[hit]))
                decision, reason = 'drop', '已在 %s' % where
            elif own in have:
                decision, reason = 'drop', '目标牌组已有'
        if decision == 'keep' and P.norm(word) in seen:
            decision, reason = 'drop', '重复条目（同名更靠前 %s）' % seen[P.norm(word)]
        if decision == 'keep':
            seen.setdefault(P.norm(word), rank)
            keep.append((rank, word, form, pos))
        else:
            dropped.append((rank, word, form, pos, decision, reason))

    if a.limit:
        keep = keep[:a.limit]

    report = a.report or os.path.join(
        WSP.REPORTS, 'ImmersionKit词表-Jiten%d%s%s.md'
        % (a.max_rank, '-考级已有' if a.known_only else '',
           '-单词' if a.words_only else ''))

    lines = ['# ImmersionKit 词表：Jiten Rank ≤ %d%s%s' % (
                 a.max_rank, '（core6000/考级已有 → 只补例句卡）' if a.known_only else '',
                 '（只做单词，剔多词素短语）' if a.words_only else ''), '',
             '> 生成时间 %s · 源 `%s` · 口径见 `code/oneshot/immersion_jiten_wordlist.py`'
             % (__import__('datetime').datetime.now().isoformat(timespec='seconds'),
                os.path.relpath(a.csv, WSP.ROOT)), '',
             '| 项 | 数量 |', '| --- | --- |',
             '| Jiten 表 Rank ≤ %d 的条目 | %d |' % (a.max_rank, len(rows)),
             '| 入选（写进 `%s`） | **%d** |' % (os.path.relpath(a.out, WSP.ROOT), len(keep)),
             '| 剔除合计 | %d |' % len(dropped), '']
    by_reason = {}
    for r in dropped:
        key = r[5].split('（')[0].split('|')[0]
        by_reason[key] = by_reason.get(key, 0) + 1
    lines += ['## 剔除原因', '', '| 原因 | 数量 |', '| --- | --- |']
    for k, v in sorted(by_reason.items(), key=lambda x: -x[1]):
        lines.append('| %s | %d |' % (k, v))

    by_pos = {}
    for r in keep:
        by_pos[r[3]] = by_pos.get(r[3], 0) + 1
    lines += ['', '## 入选词性分布', '', '| 词性 | 数量 |', '| --- | --- |']
    for k, v in sorted(by_pos.items(), key=lambda x: -x[1]):
        lines.append('| %s | %d |' % (k or '(空)', v))

    lines += ['', '## 入选（按 Rank 升序，前 200）', '',
              '| Rank | 词 | 读音 | 词性 |', '| --- | --- | --- | --- |']
    for rank, word, form, pos in keep[:200]:
        lines.append('| %d | %s | %s | %s |' % (rank, word, form, pos))
    if len(keep) > 200:
        lines.append('')
        lines.append('（其余 %d 条见 `%s`）' % (len(keep) - 200,
                                          os.path.relpath(a.tsv, WSP.ROOT)))
    textio.write_text(report, '\n'.join(lines) + '\n')

    head = ['# ImmersionKit 抓例句用的词表（Jiten Rank ≤ %d，按 Rank 升序）' % a.max_rank,
            '# 由 code/oneshot/immersion_jiten_wordlist.py 生成；'
            '已在 core6000/考级 与目标牌组里的词已剔除',
            '# 一行一个词；# 开头是注释；可以写「词<TAB>条数」覆盖 --n']
    textio.write_text(a.out, '\n'.join(head + [w for _r, w, _f, _p in keep]) + '\n')

    tsv = ['rank\tword\tform\tpos\tkeep\treason']
    for rank, word, form, pos in keep:
        tsv.append('%d\t%s\t%s\t%s\t1\t' % (rank, word, form, pos))
    for rank, word, form, pos, _d, reason in dropped:
        tsv.append('%d\t%s\t%s\t%s\t0\t%s' % (rank, word, form, pos, reason))
    textio.write_text(a.tsv, '\n'.join(tsv) + '\n')

    print('')
    print('入选 %d 个词 → %s' % (len(keep), os.path.relpath(a.out, WSP.ROOT)))
    print('剔除 %d 条 → 明细 %s' % (len(dropped), os.path.relpath(a.tsv, WSP.ROOT)))
    print('报告 %s' % os.path.relpath(report, WSP.ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
