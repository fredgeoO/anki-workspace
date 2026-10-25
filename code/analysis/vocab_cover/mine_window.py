# -*- coding: utf-8 -*-
"""★ 挖掘窗口分析：只挖前 N 集，能覆盖整季多少生词？

回答一个问题：**每季只挖前几集，划不划算？**

口径
----
* 生词 = 卡组外要背 + 有卡没学过（`newwords.py` 的两类），默认只统计「值得挖」
  （`crosswork.py` 判定的 通用 / 题材通用 / 低频通用），`--cat-all` 可改成全部生词。
* **覆盖**：把前 k 集挖到的词做成卡并学会后，整季里这些词**出现过的次数**占全季生词
  总次数的比例 —— 也就是「这一季的生词负担被消掉多少」。按次数算比按词种算更贴近听感。
* **效率** = 覆盖占比 ÷ 挖的词种占比。> 1 说明这个窗口的「词」比后面几集的更值钱；
  **边际效率** = 本集新增词种占比带来的覆盖增量，跌破 1.0 就说明这一集开始不划算了。

用法::

    python mine_window.py                       # 全部作品（subtitles/）
    python mine_window.py "subtitles\\<作品目录>"
    python mine_window.py <作品> --k 3           # 高亮「前 3 集」这个窗口
    python mine_window.py --cat-all --max-k 6
    python mine_window.py --md-out docs\\reports\\挖掘窗口分析.md --json-out data\\vocab_cover\\mine_window.json

产物（可选）：Markdown 分析报告 + JSON 曲线数据（含「窗口外的高价值词」清单，
即前 k 集没挖到、但后面集数里出现且 Jiten 排名靠前的词 —— 挖完窗口后按这个补）。
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

from _deps import STATE_JSON, WSP, add_pylibs  # noqa: E402
from _norm import norm_word  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

add_pylibs()

import analyze  # noqa: E402
import corpus  # noqa: E402
import crosswork  # noqa: E402
import jp_tok  # noqa: E402
import newwords as nw  # noqa: E402
import srt as srt_mod  # noqa: E402

VC_DATA = os.path.join(WSP.DATA, 'vocab_cover')


def _table(headers, rows):
    L = ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join(['---'] * len(headers)) + '|']
    L += ['| ' + ' | '.join('' if c is None else str(c) for c in row) + ' |' for row in rows]
    return L


def episodes_of(paths: list) -> 'collections.OrderedDict':
    """路径（作品目录/单集文件）-> {作品: [(集号, 路径)]}；不给就用 subtitles/ 全部作品。

    发现规则与 `corpus.discover()` 完全一致（跳过 anki/卡牌用 等目录）。
    """
    works = collections.OrderedDict()
    for work, ep, path in corpus.discover(os.path.join(WSP.ROOT, 'subtitles')):
        works.setdefault(work, []).append((ep, path))
    want = [os.path.abspath(p) for p in paths]
    if not want:
        return collections.OrderedDict((w, sorted(e)) for w, e in works.items())

    def hit(path: str) -> bool:
        ap = os.path.abspath(path)
        return any(ap == w or ap.startswith(w + os.sep) for w in want)

    out = collections.OrderedDict()
    for work, eps in works.items():
        keep = [(ep, path) for ep, path in eps if hit(path)]
        if keep:
            out[work] = sorted(keep)
    return out or collections.OrderedDict((w, sorted(e)) for w, e in works.items())


def analyze_work(vocab, jiten, cw, work: str, eps: list, cat_all: bool) -> dict:
    cats = ('oov', 'untackled')
    per_ep = []
    for ep, path in sorted(eps):
        text = srt_mod.read_text(path)
        _sent, clean, _ = analyze.sentences_of(text, is_srt=True)
        toks = vocab.tokenize(clean)
        recs = nw.collect_records(vocab, toks, cats)
        words = nw.finalize(recs, 'jiten', jiten, cw, cw.scope_for(path), vocab)
        keep = {w['key']: w for w in words if cat_all or w.get('mine')}
        per_ep.append((ep, keep))

    total_types = len({k for _, d in per_ep for k in d})
    total_tokens = sum(w['count'] for _, d in per_ep for w in d.values())

    curve, seen = [], set()
    prev_types = prev_cover = 0
    for ep, d in per_ep:
        new = [k for k in d if k not in seen]
        seen |= set(d)
        cover = sum(w['count'] for _, dd in per_ep for k, w in dd.items() if k in seen)
        dt_pct = (len(seen) - prev_types) / total_types if total_types else 0
        dc = cover / total_tokens - prev_cover if total_tokens else 0
        curve.append({
            'episode': ep,
            'new_types': len(new),
            'ep_tokens': sum(w['count'] for w in d.values()),
            'cum_types': len(seen),
            'cum_types_pct': len(seen) / total_types if total_types else 0,
            'cum_cover_pct': cover / total_tokens if total_tokens else 0,
            'marginal_types_pct': dt_pct,
            'marginal_cover_pt': dc,
            'marginal_eff': (dc / dt_pct) if dt_pct else 0.0,
        })
        prev_types, prev_cover = len(seen), cover / total_tokens if total_tokens else 0

    # 窗口外的高价值词：前 k 集没挖到、后面出现的词（按 Jiten 排）
    return {'work': work, 'episodes': len(per_ep), 'total_types': total_types,
            'total_tokens': total_tokens, 'curve': curve, 'per_ep': per_ep}


def missed_words(per_ep: list, k: int, top: int) -> list:
    """前 k 集没挖到、后面出现的词 —— 按「原形」合并（なくなる 的各活用形算一个词）。"""
    head = {key for _, d in per_ep[:k] for key in d}
    later = collections.defaultdict(int)
    meta = {}
    for _ep, d in per_ep[k:]:
        for key, w in d.items():
            if key in head:
                continue
            later[key] += w['count']
            meta.setdefault(key, w)
    grouped = {}
    for key, count in later.items():
        w = meta[key]
        gkey = norm_word(w.get('lemma') or w['word'])
        g = grouped.get(gkey)
        if g is None:
            g = grouped[gkey] = dict(w, later_count=0, forms=[])
        g['later_count'] += count
        if w['word'] not in g['forms']:
            g['forms'].append(w['word'])
    out = list(grouped.values())
    out.sort(key=lambda w: (w.get('jiten_rank') or nw.BIG, -w['later_count']))
    return out[:top]


def _missed_cell(w) -> str:
    """窗口外清单按原形显示（活用形在 JSON 的 forms 里）。"""
    return w.get('lemma') or w['word']


def _cell(w):
    lemma = w.get('lemma') or ''
    return f"{w['word']}（{lemma}）" if lemma else w['word']


def render_md(results: list, k: int, missed_top: int, cat_all: bool) -> str:
    L = ['# 挖掘窗口分析：每季只挖前 N 集值不值', '']
    L.append(f"> 生成：{_dt.datetime.now().isoformat(timespec='seconds')} ｜ "
             f"口径：{'全部生词' if cat_all else '值得挖的生词'}"
             f"（通用/题材通用/低频通用）｜ 高亮窗口 k = {k}")
    L.append('')
    L.append('「覆盖」= 前 k 集挖到的词在**整季**里出现过的次数 ÷ 全季生词总次数；'
             '「效率」= 覆盖占比 ÷ 挖的词种占比（>1 表示这个窗口的单位词更值钱）。')
    L.append('')
    L.append(f'## 汇总（前 {k} 集 vs 整季）')
    L.append('')
    rows = []
    for r in results:
        c = r['curve'][min(k, len(r['curve'])) - 1]
        eff = c['cum_cover_pct'] / c['cum_types_pct'] if c['cum_types_pct'] else 0
        rows.append([r['work'], r['episodes'], r['total_types'],
                     c['cum_types'], f"{c['cum_types_pct']*100:.1f}%",
                     f"{c['cum_cover_pct']*100:.1f}%", f'{eff:.2f}×'])
    L.extend(_table(['作品', '集数', '全季词种', f'前{k}集词种', '占全季词种',
                     f'覆盖整季生词次数', '效率'], rows))
    L.append('')
    for r in results:
        L.append(f"### {r['work']}（{r['episodes']} 集 · 值得挖 {r['total_types']} 词种 · "
                 f"{r['total_tokens']} 次）")
        L.append('')
        rows = []
        for c in r['curve'][:max(k + 3, 6)]:
            rows.append([f"第 {c['episode']:02d} 集", c['new_types'], c['cum_types'],
                         f"{c['cum_types_pct']*100:.1f}%",
                         f"{c['cum_cover_pct']*100:.1f}%",
                         f"{c['marginal_eff']:.2f}×"])
        L.extend(_table(['集', '本集新增词种', '累计词种', '累计占全季', '累计覆盖',
                         '本集边际效率'], rows))
        L.append('')
        ms = r.get('missed') or []
        if ms:
            L.append(f"**窗口外的高价值词**（前 {k} 集没挖到、后面出现，按动画词频排前 "
                     f"{min(missed_top, len(ms))} 个）：")
            L.append('')
            rows = [[i, _missed_cell(w), w.get('reading') or '', (w.get('pos') or '').split('/')[0],
                     w['later_count'], w.get('jiten_rank') or '—',
                     '/'.join(w.get('forms') or [])]
                    for i, w in enumerate(ms[:missed_top], 1)]
            L.extend(_table(['#', '词（原形）', '读音', '品詞', '窗口外次数', 'Jiten', '出现形态'],
                            rows))
            L.append('')
    L.append('## 怎么用')
    L.append('')
    L.append(f'* 效率 > 1 的集数区间就是「挖了最划算」的窗口；本表里 {k} 集是当前设置，'
             '`--k` 可以改。')
    L.append('* 边际效率**跌破 1.0** 的那一集起，新增词多为一次性设定词，性价比开始低于平均值。')
    L.append('* 「窗口外的高价值词」按 Jiten 排名补挖即可 —— 不用整季重挖。')
    return '\n'.join(L).rstrip() + '\n'


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:                                      # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(
        description='只挖前 N 集能覆盖整季多少生词（窗口分析）',
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('paths', nargs='*', help='作品目录（默认 subtitles/ 下全部作品）')
    ap.add_argument('--k', type=int, default=3, help='高亮的前 N 集窗口（默认 3）')
    ap.add_argument('--cat-all', action='store_true',
                    help='把全部生词算进来（含专有名词/拟声等），默认只算「值得挖」')
    ap.add_argument('--missed-top', type=int, default=20, help='窗口外高价值词列几个（默认 20）')
    ap.add_argument('--md-out', help='Markdown 报告输出路径')
    ap.add_argument('--json-out', help='JSON 数据输出路径')
    ap.add_argument('--quiet', action='store_true', help='只写文件')
    ap.add_argument('--state', default=STATE_JSON, help='词汇快照 JSON')
    ap.add_argument('--jiten', default=nw.JITEN_CSV, help='Jiten 动画词频表 CSV')
    ap.add_argument('--no-jiten', action='store_true', help='不读词频表')
    args = ap.parse_args()

    if not os.path.exists(args.state):
        print(f'[错误] 找不到词汇快照：{args.state}（先跑 collect_vocab.py）', file=sys.stderr)
        return 2
    vocab = jp_tok.Vocabulary.load(args.state, split_mode='A')
    jiten = {} if args.no_jiten else nw.load_jiten_ranks(args.jiten)
    cw = crosswork.CrossWork()
    works = episodes_of(args.paths)
    if not works:
        print('没有找到字幕集。', file=sys.stderr)
        return 2

    results = []
    for work, eps in works.items():
        r = analyze_work(vocab, jiten, cw, work, eps, args.cat_all)
        r['missed'] = missed_words(r.pop('per_ep'), args.k, args.missed_top)
        results.append(r)
        if not args.quiet:
            c = r['curve'][min(args.k, len(r['curve'])) - 1]
            eff = c['cum_cover_pct'] / c['cum_types_pct'] if c['cum_types_pct'] else 0
            print(f"■ {work}（{r['episodes']} 集 · 值得挖 {r['total_types']} 词种）")
            print(f"  前 {args.k} 集：{c['cum_types']} 词种（占 {c['cum_types_pct']*100:.1f}%）"
                  f" → 覆盖整季生词的 {c['cum_cover_pct']*100:.1f}%（效率 {eff:.2f}×）")
            below = [x for x in r['curve'] if x['marginal_eff'] and x['marginal_eff'] < 1]
            if below:
                print(f"  边际效率跌破 1.0 从第 {below[0]['episode']:02d} 集开始"
                      f"（{below[0]['marginal_eff']:.2f}×）")
    md = render_md(results, args.k, args.missed_top, args.cat_all)
    if args.md_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.md_out)), exist_ok=True)
        with open(args.md_out, 'w', encoding='utf-8', newline='') as fh:
            fh.write(md)
        if not args.quiet:
            print(f'报告 {os.path.relpath(args.md_out, WSP.ROOT)}')
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        payload = {'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
                   'k': args.k, 'cat_all': args.cat_all,
                   'snapshot': os.path.relpath(args.state, WSP.ROOT).replace('\\', '/'),
                   'works': results}
        with open(args.json_out, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        if not args.quiet:
            print(f'数据 {os.path.relpath(args.json_out, WSP.ROOT)}')
    if not args.md_out and not args.json_out and not args.quiet:
        sys.stdout.write('\n' + md)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
