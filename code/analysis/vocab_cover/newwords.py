# -*- coding: utf-8 -*-
"""★ 新词清单：把**任意文章 / 字幕**里「我还不认识的词」列成一张可读的表。

和 ``cover_cli.py`` 的分工
--------------------------
``cover_cli.py`` 回答「**覆盖率是多少**」（一份体检报告，新词只印前 N 个预览）；
本工具回答「**新词具体是哪些**」—— 全量列出、带读音/词性/首例句/档位，
并且能直接导出 TSV / CSV / Markdown 去挖词或做讲义。

「新词」的四档口径（与 jp_tok 的 bucket 完全一致，不另立标准）
------------------------------------------------------------
===== ========================================== ==========================
类别   含义                                        默认是否列出
===== ========================================== ==========================
oov    卡组里**没有这张卡**、且是要背的实词           ✅（真正的新词）
untackled 卡组里**有卡但一次都没刷过**                ✅（马上要学的）
proper 卡组外固有名詞（人名/地名/作品名）             ❌（跟着剧情自然学会）
interj 卡组外感動詞（あっ/ん 之类）                   ❌（属听力反应）
numeral 卡组外数詞（一/百五十）                       ❌
compound 整体不在卡组、但能拆成全是已学词的组合词      ❌（其实你懂）
known  卡组内**已学过**的词                           ❌
===== ========================================== ==========================

⚠ 两个已知口径（都是「以卡组为准」带来的，不是 bug）
  1. 超高频功能词（こと / もの / や / みたい…）如果**没做成卡**，也会被判成「真新词」。
     它们往往 Jiten 排名很靠前，``--sort jiten`` 时会浮到最前面。
     → 工具现在会用 ``data/vocab_cover/not_vocab.json`` 把它们标成「功能词」，``--mine-only`` 直接滤掉。
  2. 动词按 Sudachi 的 A 单位切开，所以会看到词干（食べ / 唱え）而不是辞书形 ——
     表里的「原形」列给的就是辞书形（食べる / 唱える），做卡时用那一列。

「跨作品」列：这个词值不值得挖
------------------------------
只看「卡组里有没有」会把两类完全不同的词混在一起：**题材通用词**（殿下・令嬢・公爵・
王位・離宮…换个同题材作品还会遇到，值得做卡）和**作品专有概念/人名**（ユフィリア・
レイニ…换作品就没了，不值得）。判据见 ``crosswork.py``：

===== ================================================ ==================
档     含义                                              默认
===== ================================================ ==================
通用   Jiten 排名 ≤ 5000（表按「出现在多少部作品里」排）  ✅ 挖
题材   命中题材通用词表（宫廷/奇幻/军事/神话/学园・社会）  ✅ 挖
低频通用 Jiten 有排名但很深（宫廷/奇幻词多落在这里）       ✅ 挖
未收录 Jiten 没排名（人名/造语/切分残片）                 ❓ 看情况
作品专有 命中作品专有词表（例：HUNTER×HUNTER 的「念能力」） ❌ 不做卡
功能词/拟声 语法性功能词、拟声与感叹碎片                    ❌ 不做卡
===== ================================================ ==================

* 词表都是可手改的 JSON，在 ``data/vocab_cover/``：``genre_lexicon.json``（题材通用词）、
  ``work_concepts.json``（作品专有）、``not_vocab.json``（语法词/拟声）。
* ``--mine-only`` = 只留「可挖」的（通用 + 题材 + 低频通用，去掉专有/功能词/拟声/疑似人名）。
* 全片假名 + 排名很深（> 20000）或没排名 → 标「疑似人名」，默认不挖（レイニ #134561 就是这种）。

用法::

    # 一集字幕：列出全部新词（卡组外 + 卡组内没学的）
    python newwords.py "subtitles\\転生王女…\\… - 01 (AT-X).srt"

    # 一篇文章 / 一段话 / 管道
    python newwords.py article.txt
    python newwords.py --text "日本語の文章…"
    Get-Content x.txt -Raw | python newwords.py --stdin

    # 整个目录（递归，自动跳过 anki/卡牌用 等子目录）
    python newwords.py "subtitles\\転生王女と天才令嬢の魔法革命"

    # 导出：TSV 挖词 / Markdown 讲义 / JSON 喂流水线
    python newwords.py ep.srt --format tsv  --out data\\vocab_cover\\newwords_ep01.tsv
    python newwords.py ep.srt --format md   --out output\\newwords_ep01.md
    python newwords.py ep.srt --format json --out data\\vocab_cover\\newwords_ep01.json

    # 只看真正没卡的词、至少出现 2 次、按 core6000 序号排
    python newwords.py ep.srt --cat oov --min-count 2 --sort rank

    # ★ 只留「值得挖」的：题材通用（宫廷/奇幻…）+ 跨作品高频 + 低频通用
    python newwords.py ep.srt --sort jiten --mine-only
    python newwords.py ep.srt --mine-only --cross genre        # 只看题材通用词
    python newwords.py ep.srt --cross work,unlisted            # 只看专有/未收录（排除清单）

    # 每集单独成表（默认是全部来源合并统计）
    python newwords.py "subtitles\\転生王女…" --per-file

⚠ Windows 控制台显示日文：本脚本会把 stdout 切到 UTF-8。若仍乱码，
   先执行 ``chcp 65001``（或直接用 ``--out`` 写文件看）。
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _deps import STATE_JSON, WSP, add_pylibs, write_json  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
from _norm import norm_word, to_hiragana  # noqa: E402

add_pylibs()

import analyze  # noqa: E402
import crosswork  # noqa: E402
import jp_tok  # noqa: E402
import srt as srt_mod  # noqa: E402

# 外部词频表（Jiten Anime，3,762 部动画；见 docs/architecture.md §5）——用来给新词排真实优先级
JITEN_CSV = os.path.join(WSP.DATA, 'freq', 'jiten_freq_Anime.csv')

# 目录递归时的跳过规则（与 corpus.py 的 discover() 保持同一套口径）
SKIP_DIRS = {'anki', 'card', 'cards', '_old'}
SKIP_NAME_HINTS = ('（制作', '(制作', '制作anki', 'anki卡牌用')
TEXT_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.txt', '.md')

SRT_EXTS = ('.srt', '.ass', '.ssa', '.vtt')

CATS = ('oov', 'untackled', 'proper', 'interj', 'numeral', 'compound', 'known')
CAT_LABELS = {
    'oov': '卡组外·要背（真新词）',
    'untackled': '卡组内·有卡没学过',
    'proper': '卡组外·专有名词',
    'interj': '卡组外·感动词',
    'numeral': '卡组外·数词',
    'compound': '组合词（可拆成已学词）',
    'known': '卡组内·已学过',
}
CAT_ORDER = {c: i for i, c in enumerate(CATS)}
DEFAULT_CATS = ('oov', 'untackled')

DECK_LABEL = {'core6000': 'core6000', 'jlpt': '考JLPT', 'mined': '素材生词'}
JLPT_ORDER = {'N5': 0, 'N4': 1, 'N3': 2, 'N2': 3, 'N1': 4}
BIG = 10 ** 9


# ------------------------------------------------------------------ 输入收集
def load_jiten_ranks(path: str) -> dict:
    """读 Jiten Anime 词频表 -> {规范键: 排名}。

    表格式是 ``Word,Form,Rank``，汉字形与假名形**两把键都收**（与 freq_external.py
    同一套口径）；同一规范键取更靠前的排名。文件不存在就返回空表（功能自动关闭）。
    """
    ranks = {}
    if not path or not os.path.exists(path):
        return ranks
    with open(path, encoding='utf-8') as fh:
        next(fh, None)                      # 表头
        for line in fh:
            parts = line.rstrip('\n').split(',')
            if len(parts) < 3:
                continue
            try:
                rank = int(parts[2])
            except ValueError:
                continue
            for cand in (parts[0], parts[1]):
                n = norm_word(cand)
                if n and (n not in ranks or rank < ranks[n]):
                    ranks[n] = rank
    return ranks


def is_srt_ext(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SRT_EXTS


def walk_texts(root: str) -> list:
    """递归收集 root 下的文本/字幕文件（跳过 anki、卡牌用等子目录）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not any(h in d for h in SKIP_NAME_HINTS)]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in TEXT_EXTS:
                continue
            if any(h in fn for h in SKIP_NAME_HINTS):
                continue
            out.append(os.path.join(dirpath, fn))
    return sorted(out)


def read_stdin() -> str:
    """读标准输入。编码判定交给唯一实现 ``textio.read_stdin()``（UTF-8 优先，
    GBK/CP932 也收），不让工具因为管道编码挂掉。"""
    return textio.read_stdin()


def read_sources(args) -> list:
    """-> [(label, text, is_srt)]"""
    items = []
    if args.text:
        items.append(('--text', args.text, False))
    if args.stdin:
        items.append(('stdin', read_stdin(), False))
    for p in args.paths:
        if os.path.isdir(p):
            files = walk_texts(p)
            if not files:
                print(f'[跳过] 目录里没有可分析的文本/字幕：{p}', file=sys.stderr)
            for f in files:
                items.append((os.path.relpath(f, os.getcwd()).replace('\\', '/'),
                              srt_mod.read_text(f), is_srt_ext(f)))
        elif os.path.exists(p):
            items.append((os.path.relpath(p, os.getcwd()).replace('\\', '/'),
                          srt_mod.read_text(p), is_srt_ext(p)))
        else:
            print(f'[跳过] 找不到文件：{p}', file=sys.stderr)
    return items


# ------------------------------------------------------------------ 归类与抽取
def classify(tok) -> str:
    if tok.bucket in jp_tok.DECK_BUCKETS:
        return 'known' if tok.known else 'untackled'
    if tok.bucket == 'oov':
        return 'compound' if tok.compound_of_known else 'oov'
    return tok.bucket


def deck_bucket(entry: dict) -> str:
    if entry.get('core'):
        return 'core6000'
    if entry.get('jlpt'):
        return 'jlpt'
    if entry.get('mined'):
        return 'mined'
    return ''


def collect_records(vocab, toks: list, cats) -> dict:
    """词元流 -> {规范键: 词条记录}，次数与词形在词元粒度上累计。"""
    recs = {}
    for t in toks:
        if not t.is_vocab:
            continue
        cat = classify(t)
        if cat not in cats:
            continue
        key = t.key or norm_word(t.surface)
        if not key:
            continue
        r = recs.get(key)
        if r is None:
            entry = vocab.words.get(key)
            r = recs[key] = {
                'key': key,
                'cat': cat,
                'count': 0,
                '_surfaces': collections.Counter(),
                '_lemmas': collections.Counter(),
                '_pos': collections.Counter(),
                '_readings': collections.Counter(),
                'entry': entry or None,
                'examples': [],
            }
        r['count'] += 1
        if t.surface:
            r['_surfaces'][t.surface] += 1
        if t.dictionary:
            r['_lemmas'][t.dictionary] += 1
        if t.pos1:
            r['_pos'][f'{t.pos1}/{t.pos2}' if t.pos2 else t.pos1] += 1
        if t.reading:
            r['_readings'][to_hiragana(t.reading)] += 1
    return recs


def attach_examples(vocab, sentences, recs: dict, want: int) -> None:
    """给每个词挂上最先出现的 want 条例句（按句子粒度分词，只在命中时记录）。"""
    if want <= 0 or not sentences:
        return
    for sent in sentences:
        if all(len(r['examples']) >= want for r in recs.values()):
            break
        for t in vocab.tokenize(sent):
            if not t.is_vocab:
                continue
            key = t.key or norm_word(t.surface)
            r = recs.get(key)
            if r is None or len(r['examples']) >= want:
                continue
            if sent not in r['examples']:
                r['examples'].append(sent)


def build_summary(vocab, toks: list, recs: dict, sentences) -> dict:
    s = vocab.coverage(toks, sentences=sentences).summary()
    ca = s['cover_all']
    type_counts = collections.Counter(r['cat'] for r in recs.values())
    return {
        'tokens': s['tokens']['all'],
        'tokens_vocab': s['tokens']['vocab'],
        'types_vocab': s['types']['vocab'],
        'sentences': len(sentences or []),
        'cover_known': ca.get('known', 0),
        'cover_deck': ca.get('deck', 0),
        'understood_lenient': ca.get('understood_lenient', 0),
        'cat_types': dict(sorted(type_counts.items(), key=lambda kv: CAT_ORDER[kv[0]])),
        'cat_tokens': {c: sum(r['count'] for r in recs.values() if r['cat'] == c)
                       for c in sorted(type_counts, key=lambda c: CAT_ORDER[c])},
    }


# ------------------------------------------------------------------ 记录成形
def finalize(recs: dict, sort: str, jiten: dict = None,
             cw: 'crosswork.CrossWork' = None, scope: dict = None,
             vocab=None) -> list:
    jiten = jiten or {}
    scope = scope or {}
    words = []
    for r in recs.values():
        entry = r['entry'] or {}
        surface = r['_surfaces'].most_common(1)[0][0] if r['_surfaces'] else r['key']
        lemma = r['_lemmas'].most_common(1)[0][0] if r['_lemmas'] else surface
        reading = ''
        if entry.get('readings'):
            reading = entry['readings'][0]
        elif r['_readings']:
            reading = r['_readings'].most_common(1)[0][0]
        # 读音与词形或原形一致（纯假名词、原形即读音）就不重复显示
        if reading and (norm_word(reading) == norm_word(surface)
                        or norm_word(reading) == norm_word(lemma)):
            reading = ''
        jlpt = list(entry.get('jlpt') or [])
        # 「原形」在卡组/词频表里的情况：用来处理 A 单位切出来的活用形（放っ / 繰り / 語ら…）
        lemma_key = norm_word(lemma) if (lemma and norm_word(lemma) != r['key']) else ''
        lemma_entry = vocab.words.get(lemma_key) if (vocab is not None and lemma_key) else None
        hints = {'lemma_key': lemma_key,
                 'lemma_in_deck': bool(lemma_entry),
                 'lemma_known': bool((lemma_entry or {}).get('known')),
                 'lemma_rank': jiten.get(lemma_key) if lemma_key else None}
        rank = jiten.get(r['key'])
        w = {
            'key': r['key'],
            'word': surface,
            'lemma': lemma if lemma != surface else '',
            'reading': reading,
            'pos': r['_pos'].most_common(1)[0][0] if r['_pos'] else '',
            'count': r['count'],
            'cat': r['cat'],
            'bucket': deck_bucket(entry) if entry else '',
            'core_rank': entry.get('core'),
            'jlpt': jlpt,
            'mined': bool(entry.get('mined')),
            'known': bool(entry.get('known')),
            'mature': bool(entry.get('mature')),
            'reps': entry.get('reps', 0),
            'interval': entry.get('interval', 0),
            'jiten_rank': rank,
            'examples': r['examples'],
        }
        if cw is not None and cw.enabled:
            res = cw.classify(r['key'], surface, lemma, rank, scope, hints)
            w.update(res)
            if res.get('rank_from_lemma'):
                w['jiten_rank'] = hints['lemma_rank']      # 按原形的排名排序/显示
        words.append(w)
    words.sort(key=lambda w: _sort_key(w, sort))
    return words


def _jlpt_min(w) -> int:
    return min((JLPT_ORDER.get(l, 9) for l in w['jlpt']), default=9)


def _sort_key(w, sort: str):
    count = -w['count']
    core = w['core_rank'] if w['core_rank'] else BIG
    if sort == 'jiten':
        return (w['jiten_rank'] or BIG, count, w['key'])
    if sort == 'rank':
        return (core, _jlpt_min(w), count, w['key'])
    if sort == 'jlpt':
        return (_jlpt_min(w), core, count, w['key'])
    if sort == 'kana':
        return (w['reading'] or w['key'], count)
    return (count, core, w['key'])          # freq（默认）


def deck_mark(w) -> str:
    """档位列：core6000 序号 / JLPT 级别 / 素材生词 / —。"""
    bits = []
    if w['core_rank']:
        bits.append(f"core#{w['core_rank']}")
    if w['jlpt']:
        bits.append('/'.join(w['jlpt']))
    if w['mined']:
        bits.append('素材')
    return ' '.join(bits) or ('有卡' if w['known'] or w['cat'] in ('untackled', 'known') else '—')


def truncate(text: str, width: int) -> str:
    text = ' '.join(text.split())
    return text if len(text) <= width else text[:width - 1] + '…'


# ------------------------------------------------------------------ 渲染
def _cat_heading(cat: str, shown: int, total: int) -> str:
    extra = f'（本来源共 {total} 词种）' if total and total != shown else ''
    return f'── {CAT_LABELS[cat]}：{shown} 词种{extra} ──'


def render_table(words: list, top: int, group: bool, with_example: bool,
                 ex_width: int, with_jiten: bool = False,
                 cat_totals: dict = None, with_cross: bool = False) -> list:
    cat_totals = cat_totals or {}
    L = []
    header = ['#', '词', '原形', '读み', '品詞', '次数']
    if with_jiten:
        header.append('Jiten')
    if with_cross:
        header.append('跨作品')
    header.append('档位')
    if with_example:
        header.append('首例句')

    def row(i, w):
        cells = [str(i), w['word'], w['lemma'], w['reading'], w['pos'], str(w['count'])]
        if with_jiten:
            cells.append(str(w['jiten_rank']) if w.get('jiten_rank') else '—')
        if with_cross:
            cells.append(crosswork.CrossWork.label(w))
        cells.append(deck_mark(w))
        if with_example:
            cells.append(truncate(w['examples'][0], ex_width) if w['examples'] else '')
        return cells

    def emit(sub, start=1):
        rows = [row(start + i, w) for i, w in enumerate(sub)]
        widths = [max(analyze._w(header[c]), *(analyze._w(r[c]) for r in rows))
                  for c in range(len(header))]
        L.append('  ' + '  '.join(analyze.pad(header[c], widths[c]) for c in range(len(header))))
        for r in rows:
            L.append('  ' + '  '.join(analyze.pad(r[c], widths[c]) for c in range(len(header))))
        L.append('')

    if group:
        for cat in CATS:
            sub = [w for w in words if w['cat'] == cat]
            if not sub:
                continue
            full = len(sub)
            if top:
                sub = sub[:top]
            L.append(_cat_heading(cat, len(sub), cat_totals.get(cat, full)))
            emit(sub)
    else:
        sub = words[:top] if top else words
        emit(sub)
    return L


def render_md(words: list, top: int, group: bool, with_example: bool,
              ex_width: int, with_jiten: bool = False,
              cat_totals: dict = None, with_cross: bool = False) -> list:
    cat_totals = cat_totals or {}
    L = []
    header = '| # | 词 | 原形 | 读み | 品詞 | 次数 |'
    sep = '|---|---|---|---|---|---|'
    if with_jiten:
        header += ' Jiten |'
        sep += '---|'
    if with_cross:
        header += ' 跨作品 |'
        sep += '---|'
    header += ' 档位 |'
    sep += '---|'
    if with_example:
        header += ' 首例句 |'
        sep += '---|'

    def emit(sub):
        L.append(header)
        L.append(sep)
        for i, w in enumerate(sub, 1):
            ex = truncate(w['examples'][0], ex_width) if w['examples'] else ''
            line = (f"| {i} | {w['word']} | {w['lemma']} | {w['reading']} | {w['pos']} "
                    f"| {w['count']} |")
            if with_jiten:
                line += f" {w['jiten_rank'] if w.get('jiten_rank') else '—'} |"
            if with_cross:
                line += f" {crosswork.CrossWork.label(w)} |"
            line += f" {deck_mark(w)} |"
            if with_example:
                line += f' {ex} |'
            L.append(line)
        L.append('')

    if group:
        for cat in CATS:
            sub = [w for w in words if w['cat'] == cat]
            if not sub:
                continue
            full = len(sub)
            if top:
                sub = sub[:top]
            extra = (f'（本来源共 {cat_totals[cat]} 词种）'
                     if cat_totals.get(cat, full) != len(sub) else '')
            L.append(f'### {CAT_LABELS[cat]}（{len(sub)} 词种{extra}）')
            L.append('')
            emit(sub)
    else:
        emit(words[:top] if top else words)
    return L


TSV_COLS = ('cat', 'word', 'lemma', 'reading', 'pos', 'count', 'jiten_rank',
            'cross', 'cross_note', 'not_vocab', 'suspect_name', 'mine', 'bucket',
            'core_rank', 'jlpt', 'known', 'mature', 'reps', 'interval',
            'key', 'examples')


def render_rows(words: list, top: int) -> list:
    """TSV/CSV 用的平表（顺序 = 排序结果，不分组）。"""
    rows = []
    for w in (words[:top] if top else words):
        row = dict(w)
        row['jlpt'] = '/'.join(w['jlpt'])
        row['core_rank'] = w['core_rank'] if w['core_rank'] else ''
        row['examples'] = ' ⏎ '.join(w['examples'])
        rows.append(row)
    return rows


def summary_line(payload: dict) -> str:
    s = payload['summary']
    cat = s['cat_types']
    bits = [f"{CAT_LABELS[c]} {cat[c]}" for c in CATS if cat.get(c)]
    lines = [f"■ {payload['label']}",
             f"  规模：句子 {s['sentences']} · 词元 {s['tokens']}"
             f"（词汇词 {s['tokens_vocab']}）· 词汇词种 {s['types_vocab']}",
             f"  掌握：卡组覆盖 {s['cover_deck']*100:.1f}% · 已学 {s['cover_known']*100:.1f}%"
             f" · 实际能懂(宽口径) {s['understood_lenient']*100:.1f}%",
             f"  新词：{' · '.join(bits) if bits else '（所选类别里没有词）'}"]
    cc = s.get('cross_counts')
    if cc:
        order = ['通用', '题材', '低频通用', '未收录', '专有', '功能词', '拟声', '疑似人名']
        shown = [f'{k} {cc[k]}' for k in order if cc.get(k)]
        rest = {k: v for k, v in cc.items() if k not in order and k != '可挖'}
        shown += [f'{k} {v}' for k, v in sorted(rest.items())]
        lines.append(f"  跨作品：{' · '.join(shown)}  ⇒ 值得挖 {cc.get('可挖', 0)}")
    return '\n'.join(lines)


# ------------------------------------------------------------------ CLI
def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='把文章/字幕里的新词列成一张表（读音·词性·次数·首例句·档位）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument('paths', nargs='*', help='文件或目录（.srt 按字幕解析，目录递归）')
    ap.add_argument('--text', help='直接给一段文字')
    ap.add_argument('--stdin', action='store_true', help='从标准输入读')
    ap.add_argument('--cat', default=','.join(DEFAULT_CATS),
                    help=f'要列出的类别，逗号分隔。可选：{",".join(CATS)}'
                         f'（默认 {",".join(DEFAULT_CATS)}；all=全部）')
    ap.add_argument('--with-proper', action='store_true', help='附带专有名词')
    ap.add_argument('--with-known', action='store_true', help='附带已学过的词')
    ap.add_argument('--min-count', type=int, default=1, help='至少出现几次（默认 1）')
    ap.add_argument('--top', type=int, default=0, help='每类最多列几个（默认 0 = 全部）')
    ap.add_argument('--sort', default='freq',
                    choices=['freq', 'rank', 'jlpt', 'kana', 'jiten'],
                    help='排序：freq 出现次数（默认）/ rank core6000 序号 / jlpt 级别'
                         ' / kana 读音 / jiten 动画真实词频（最细，推荐挖词用）')
    ap.add_argument('--jiten', default=JITEN_CSV,
                    help=f'Jiten 动画词频表 CSV（默认 {os.path.relpath(JITEN_CSV, WSP.ROOT)}）')
    ap.add_argument('--no-jiten', action='store_true', help='不读词频表（不显示 Jiten 列）')
    ap.add_argument('--cross', default='',
                    help=f'只列这些跨作品档，逗号分隔。可选：{",".join(crosswork.CROSS_ORDER)}'
                         '（common 通用 / genre 题材通用 / rare 低频通用 / unlisted 未收录'
                         ' / function 功能词+拟声 / work 作品专有）。默认不过滤')
    ap.add_argument('--mine-only', action='store_true',
                    help='★ 只列「值得挖」的词：通用+题材+低频通用，去掉作品专有/'
                         '语法性功能词/拟声/疑似人名')
    ap.add_argument('--common-max', type=int, default=5000,
                    help='Jiten 排名 ≤ 这个数算「通用」（默认 5000）')
    ap.add_argument('--name-rank', type=int, default=20000,
                    help='全片假名且排名 > 这个数算「疑似人名」（默认 20000）')
    ap.add_argument('--no-cross', action='store_true', help='不做跨作品判定（不出跨作品列）')
    ap.add_argument('--genre-lexicon', default=crosswork.GENRE_JSON,
                    help='题材通用词表 JSON（默认 data/vocab_cover/genre_lexicon.json）')
    ap.add_argument('--work-concepts', default=crosswork.WORK_JSON,
                    help='作品专有词表 JSON（默认 data/vocab_cover/work_concepts.json）')
    ap.add_argument('--not-vocab', default=crosswork.NOT_VOCAB_JSON,
                    help='语法词/拟声表 JSON（默认 data/vocab_cover/not_vocab.json）')
    ap.add_argument('--format', default='table',
                    choices=['table', 'md', 'tsv', 'csv', 'json'], help='输出格式')
    ap.add_argument('--out', help='写到文件（tsv/csv 带 BOM，方便 Excel 打开）')
    ap.add_argument('--per-file', action='store_true', help='每个来源单独成表（默认合并统计）')
    ap.add_argument('--examples', type=int, default=1, help='每个词附几条例句（默认 1，0 = 不要）')
    ap.add_argument('--example-width', type=int, default=30, help='表格里例句截断宽度')
    ap.add_argument('--no-example', action='store_true', help='表格里不显示例句列')
    ap.add_argument('--flat', action='store_true', help='不按类别分组，只出一张排序总表')
    ap.add_argument('--split-mode', default='A', choices=['A', 'B', 'C'],
                    help='Sudachi 切分粒度，默认 A（与其它统计口径一致）')
    ap.add_argument('--state', default=STATE_JSON, help='换一份词汇快照 JSON')
    ap.add_argument('--quiet', action='store_true', help='只写文件，不打印表格')
    return ap


def resolve_cats(args) -> set:
    raw = args.cat.strip()
    if raw == 'all':
        cats = set(CATS)
    else:
        cats = {c.strip() for c in raw.split(',') if c.strip()}
    bad = cats - set(CATS)
    if bad:
        raise SystemExit(f'未知类别：{", ".join(sorted(bad))}（可选：{", ".join(CATS)} 或 all）')
    if args.with_proper:
        cats.add('proper')
    if args.with_known:
        cats.add('known')
    return cats or set(DEFAULT_CATS)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:
            pass
    args = build_argparser().parse_args()
    cats = resolve_cats(args)
    items = read_sources(args)
    if not items:
        print('没有输入。用 paths / --text / --stdin 指定内容。', file=sys.stderr)
        return 2
    if not os.path.exists(args.state):
        print(f'[错误] 找不到词汇快照：{args.state}\n'
              f'        先跑 collect_vocab.py 生成（需要 Anki 开着）：\n'
              f'        python code/analysis/vocab_cover/collect_vocab.py', file=sys.stderr)
        return 2

    vocab = jp_tok.Vocabulary.load(args.state, split_mode=args.split_mode)
    jiten = {} if args.no_jiten else load_jiten_ranks(args.jiten)
    if not args.no_jiten and not jiten:
        print(f'[提示] 没有词频表（{args.jiten}），跳过 Jiten 列与 jiten 排序。', file=sys.stderr)
    cw = crosswork.CrossWork(genre_path=args.genre_lexicon, work_path=args.work_concepts,
                             not_vocab_path=args.not_vocab, common_max=args.common_max,
                             name_rank=args.name_rank, enabled=not args.no_cross)
    want_cross = {c.strip() for c in (args.cross or '').split(',') if c.strip()}
    bad_cross = want_cross - set(crosswork.CROSS_ORDER)
    if bad_cross:
        raise SystemExit(f'未知跨作品档：{", ".join(sorted(bad_cross))}'
                         f'（可选：{", ".join(crosswork.CROSS_ORDER)}）')
    payloads = []
    for label, text, is_srt in items:
        sentences, clean, _ep = analyze.sentences_of(text, is_srt=is_srt)
        toks = vocab.tokenize(clean)
        recs = collect_records(vocab, toks, cats)
        attach_examples(vocab, sentences, recs, args.examples)
        scope = cw.scope_for(label) if cw.enabled else {}
        words = finalize(recs, args.sort, jiten, cw, scope, vocab)
        words = [w for w in words if w['count'] >= args.min_count]
        if want_cross:
            words = [w for w in words if w.get('cross') in want_cross]
        if args.mine_only:
            words = [w for w in words if w.get('mine')]
        summary = build_summary(vocab, toks, recs, sentences)
        if cw.enabled:
            summary['cross_counts'] = cw.counts(words)
        payloads.append({'label': label, 'summary': summary, 'words': words})

    with_example = not args.no_example and args.examples > 0
    with_jiten = bool(jiten)
    with_cross = cw.enabled
    if args.per_file:
        payload = {'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
                   'split_mode': args.split_mode, 'cats': sorted(cats),
                   'min_count': args.min_count, 'sources': payloads}
    else:
        merged = _merge(payloads)
        payload = {'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
                   'split_mode': args.split_mode, 'cats': sorted(cats),
                   'min_count': args.min_count, 'sources': payloads, 'merged': merged}

    out = render_output(payload, args, cats, with_example, with_jiten, with_cross)
    if args.out:
        _write_text(args.out, out, args.format)
        print(f'写出 {args.out}（{_count(payload, args.per_file)} 词种）')
    if not args.quiet:
        if args.out and args.format in ('tsv', 'csv'):
            head = render_human(payload, args, cats, with_example, with_jiten, with_cross)
            sys.stdout.write(head)
        elif not args.out:
            sys.stdout.write(out)
    return 0


def _count(payload, per_file: bool) -> int:
    if per_file:
        return sum(len(s['words']) for s in payload['sources'])
    return len(payload['merged']['words'])


def _merge(payloads: list) -> dict:
    """多来源合并：次数相加、例句按顺序补齐、类别取并集。"""
    if len(payloads) == 1:
        m = dict(payloads[0])
        m['merged_from'] = [payloads[0]['label']]
        return m
    recs = {}
    for p in payloads:
        for w in p['words']:
            r = recs.get(w['key'])
            if r is None:
                r = recs[w['key']] = dict(w, examples=list(w['examples']))
                continue
            r['count'] += w['count']
            for ex in w['examples']:
                if len(r['examples']) < 3 and ex not in r['examples']:
                    r['examples'].append(ex)
    order = {c: i for i, c in enumerate(CATS)}
    words = sorted(recs.values(), key=lambda w: _sort_key(w, 'freq'))
    tok_total = sum(p['summary']['tokens'] for p in payloads)
    deck_tok = sum(p['summary']['cover_deck'] * p['summary']['tokens'] for p in payloads)
    known_tok = sum(p['summary']['cover_known'] * p['summary']['tokens'] for p in payloads)
    und_tok = sum(p['summary']['understood_lenient'] * p['summary']['tokens']
                  for p in payloads)
    cat_types = collections.Counter(w['cat'] for w in words)
    summary = {
        'tokens': tok_total,
        'tokens_vocab': sum(p['summary']['tokens_vocab'] for p in payloads),
        'types_vocab': sum(p['summary']['types_vocab'] for p in payloads),
        'sentences': sum(p['summary']['sentences'] for p in payloads),
        'cover_deck': deck_tok / tok_total if tok_total else 0,
        'cover_known': known_tok / tok_total if tok_total else 0,
        'understood_lenient': und_tok / tok_total if tok_total else 0,
        'cat_types': dict(sorted(cat_types.items(), key=lambda kv: order[kv[0]])),
    }
    if any('cross' in w for w in words):
        cc = collections.Counter(crosswork.CrossWork.label(w) for w in words)
        cc['可挖'] = sum(1 for w in words if w.get('mine'))
        summary['cross_counts'] = dict(cc)
    return {
        'label': f"合并 {len(payloads)} 个来源",
        'merged_from': [p['label'] for p in payloads],
        'summary': summary,
        'words': words,
    }


def render_human(payload: dict, args, cats, with_example: bool,
                 with_jiten: bool = False, with_cross: bool = False) -> str:
    """人类可读部分：每来源的概况 + 词表（table/md）。"""
    L = []
    groups = payload['sources'] if args.per_file else [payload['merged']]
    merged = payload.get('merged')
    for g in groups:
        L.append(summary_line(g) if 'summary' in g else '')
        words = g['words']
        if merged is not None and g is merged and len(payload['sources']) > 1:
            L.append(f"  （合并自：{len(payload['sources'])} 个来源）")
        L.append('')
        totals = (g.get('summary') or {}).get('cat_types', {})
        if args.format == 'md':
            L.extend(render_md(words, args.top, not args.flat, with_example,
                               args.example_width, with_jiten, totals, with_cross))
        else:
            L.extend(render_table(words, args.top, not args.flat, with_example,
                                  args.example_width, with_jiten, totals, with_cross))
    return '\n'.join(L).rstrip() + '\n'


def render_output(payload: dict, args, cats, with_example: bool,
                  with_jiten: bool = False, with_cross: bool = False) -> str:
    if args.format == 'json':
        if args.per_file:
            return json.dumps(payload, ensure_ascii=False, indent=2)
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if args.format in ('tsv', 'csv'):
        sep = '\t' if args.format == 'tsv' else ','
        groups = payload['sources'] if args.per_file else [payload['merged']]
        L = []
        head = list(TSV_COLS) + (['source'] if args.per_file else [])
        L.append(sep.join(head))
        for g in groups:
            src = g['label']
            for row in render_rows(g['words'], args.top):
                cells = [_csv_cell(row.get(c, ''), sep) for c in TSV_COLS]
                if args.per_file:
                    cells.append(_csv_cell(src, sep))
                L.append(sep.join(cells))
        return '\n'.join(L) + '\n'
    return render_human(payload, args, cats, with_example, with_jiten, with_cross)


def _csv_cell(value, sep: str) -> str:
    s = '' if value is None else str(value)
    if sep == ',' and any(ch in s for ch in ',"\n'):
        return '"' + s.replace('"', '""') + '"'
    if sep == '\t':
        return s.replace('\t', ' ').replace('\n', ' ')
    return s


def _write_text(path: str, text: str, fmt: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    enc = 'utf-8-sig' if fmt in ('tsv', 'csv') else 'utf-8'
    with open(path, 'w', encoding=enc, newline='') as fh:
        fh.write(text)


if __name__ == '__main__':
    raise SystemExit(main())
