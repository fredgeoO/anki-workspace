#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""字幕筛选 · 汇总判定并生成 filter_subtitle.py 的 plan.json

输入
----
  data/evidence/<集>/prefilter.csv     规则层（prefilter_subtitle.py scan）
  data/evidence/<集>/llm_verdict.csv   本地模型判定（local_filter.py），可缺

判定合成（宁可放过、不可错杀）
----
  规则层的职责只有一件事：判掉**确定性噪声**（NOISE：音效/语气词/应答）。
  其余所有块一律听本地模型。唯独一种情况**推翻模型**：
      「模型说丢，但规则给出了强词汇/语法信号（sig 含 W/G/I），且句子不短（≥12 字）」
  —— 这类记进 `conflicts.md` 供人过目，默认保留（漏掉的句子永远不会变成卡）。
  模型缺判定的块 → 保守保留，并在报告里列出。

用法
----
  python assemble_filter.py --ep tensei_oujo_s1e01 --output "<筛选后 srt 路径>"
  python assemble_filter.py --ep tensei_oujo_s1e01 --src "<原始 srt>" ...   # 自动生成 plan.json
"""
import argparse
import csv
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'common'))
import paths as WSP      # noqa: E402
import textio            # noqa: E402

# 本作专属人名/设定名（这些词单独出现不构成学习点；句子里另有语言点则无所谓，
# 所以这里只用于**报告提示**，不参与自动判弃）
NAME_HINT = ('ユフィリア', 'アニスフィア', 'オルファンス', 'グランツ', 'イルシア',
             'ティルティ', 'アルガルド', 'マゼンタ', 'レイニ', 'マローダー')


def read_csv(p):
    if not os.path.exists(p):
        return []
    with open(p, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


TIME = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')


def _secs(t):
    m = TIME.search(t or '')
    if not m:
        return None
    h, mi, s, ms = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000.0


def _gap(prev_time, cur_time):
    """前块结束 → 后块开始 的间隔秒数（负数=重叠）。解析不出来返回 None。"""
    a = _secs(prev_time.split('-->')[-1]) if prev_time else None
    b = _secs((cur_time or '').split('-->')[0]) if cur_time else None
    if a is None or b is None:
        return None
    return b - a


def _txt(r):
    return r['text']


def _unused():
    return None


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--ep', required=True)
    ap.add_argument('--src', help='原始 srt（写进 plan.json）')
    ap.add_argument('--output', required=True, help='筛选后 srt 的路径')
    ap.add_argument('--title', default='')
    ap.add_argument('--no-merge', action='store_true',
                    help='不做「同句切开」的相邻块合并')
    a = ap.parse_args()

    ev = os.path.join(WSP.EVIDENCE, a.ep)
    rows = read_csv(os.path.join(ev, 'prefilter.csv'))
    if not rows:
        raise SystemExit('缺少 %s/prefilter.csv' % ev)
    llm = {r['idx']: r for r in read_csv(os.path.join(ev, 'llm_verdict.csv'))}

    verdict, reason = {}, {}
    conflicts = []
    for r in rows:
        i, cat = r['idx'], r['cat']
        if cat == 'NOISE':
            verdict[i], reason[i] = 'DROP', r['why'] or '音效/语气词'
            continue
        v = llm.get(i)
        if v is None:
            verdict[i] = 'KEEP'
            reason[i] = '模型未判（保守保留）'
            continue
        if v['keep'] == '1':
            verdict[i] = 'KEEP'
            reason[i] = '模型:%s%s' % (v['reason'] or '', ('｜' + r['sig']) if r['sig'] else '')
        else:
            strong = (r['sig'] or '').replace('/', '')
            frag = '残句' in (r['why'] or '') or r['text'].rstrip().endswith(('〓', '…', '‥'))
            if not frag and len(r['text']) >= 12 and any(c in strong for c in 'WGI'):
                # 模型要丢，但规则层看到实打实的词/语法，而且**句子是完整的**
                # —— 保守保留，列进人工清单。残句不在此列（半句话本来就不该做卡）。
                verdict[i] = 'KEEP'
                reason[i] = '规则推翻模型:%s' % (v['reason'] or '')
                conflicts.append(r)
            else:
                verdict[i] = 'DROP'
                reason[i] = '模型:%s' % (v['reason'] or '')

    if conflicts:
        p = os.path.join(ev, 'conflicts.md')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('# 模型判弃、规则层有强信号 → 默认保留（%d 条）\n\n' % len(conflicts))
            f.write('> 这些句子模型认为不值得做卡，但规则层检出了未收录词/句型/惯用。\n'
                    '> 默认按**保留**处理；若你认为该丢掉，把序号从 `plan.json` 的 `groups` 里删掉后\n'
                    '> 重跑 `filter_subtitle.py apply` 即可。\n\n')
            for r in conflicts:
                f.write('- `#%s` %s\n    - 规则信号 `%s`：%s\n    - 模型理由：%s\n'
                        % (r['idx'], r['text'].replace('\n', ' '), r['sig'],
                           (r['why'] or '').split('｜')[0], reason[r['idx']]))
        print('模型与规则冲突 %d 条 → %s' % (len(conflicts), p))

    # 补回被 〓 切掉的「下半句」：
    # 字幕里长句常被切成两块，前块以 〓 结尾、后块才是句子的宾语/谓语。
    # 若前块保留、后块被判弃，而两块**相邻**、后块很短且不是新起的人名/语气词，
    # 就把后块并回来 —— 否则留下的就是半句话（正是判据要避免的）。
    by_idx = {r['idx']: r for r in rows}
    merged_into = {}
    if not a.no_merge:
        for r in rows:
            i = r['idx']
            if verdict[i] != 'KEEP' or not r['text'].rstrip().endswith('〓'):
                continue
            nxt = by_idx.get(str(int(i) + 1))
            if nxt is None or verdict[nxt['idx']] != 'DROP' or len(nxt['text']) > 30:
                continue
            tail = re.sub(r'^[（(][^）)]*[）)]', '', nxt['text']).strip()
            if not tail or len(tail) < 2 or re.match(r'^[♪〓]', tail) or tail[0] in ' 　':
                continue
            verdict[nxt['idx']] = 'KEEP'
            reason[nxt['idx']] = '补回被〓切掉的下半句(#%s)' % i
            merged_into[nxt['idx']] = i
        if merged_into:
            print('补回被〓切掉的下半句：%d 块' % len(merged_into))

    # 合成 groups：把「同一句被字幕切开的相邻块」并回一条。
    # 合并条件（保守，避免把两句不相干的话拼一起）：
    #   ① 原字幕里两块**相邻**（序号差 1）
    #   ② 时间上**首尾相接**（后块开始 ≤ 前块结束 + 0.3s）—— 真正的切句就是这样
    #   ③ 合并后文本不超过 80 字
    #   ④ 前块不以句末标点/感叹号收尾（否则它本身就是完整句）
    # 被合并的块在证据里标成「并入 #N」，与 filter_subtitle.py 的口径一致。
    END_P = '。！？!?♪」』'
    groups = []
    cur = []
    for r in rows:
        i = r['idx']
        if verdict[i] != 'KEEP':
            if cur:
                groups.append(cur)
                cur = []
            continue
        if cur:
            prev = by_idx[cur[-1]]
            gap = _gap(prev['time'], r['time'])
            ptxt = prev['text'].rstrip(' 　')
            if (not a.no_merge and int(i) - int(cur[-1]) == 1 and gap is not None
                    and gap <= 0.3 and not ptxt.endswith(tuple(END_P))
                    and len(''.join(by_idx[x]['text'] for x in cur)) + len(r['text']) <= 80):
                merged_into[i] = cur[0]
                cur.append(i)
                continue
            groups.append(cur)
        cur = [i]
    if cur:
        groups.append(cur)

    plan = {
        'title': a.title or a.ep,
        'source': a.src or '',
        'output': a.output,
        'evidence_dir': ev.replace('\\', '/'),
        'note': ('判据：历史/宫廷名词、古语与敬语语体、生僻或低频字词、惯用搭配、复杂长句 ⇒ 保留；'
                 '额外要求句子完整、脱离剧情上下文可读；剔除只在本作登场的人名与设定名。'
                 'entries 为原字幕块序号，多个序号=同句被字幕切开，合并为一条。'
                 '本 plan 由 code/tools/assemble_filter.py 从 prefilter.csv + llm_verdict.csv 合成。'),
        'groups': [{'entries': g, 'reason': reason[g[0]]} for g in groups],
        'drop_lines': [],
        'merged_into': merged_into,
    }
    out = os.path.join(ev, 'plan.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)

    # 保住自己的判定表：filter_subtitle.py apply 会用 categorize() 覆盖 verdict.csv
    mine = os.path.join(ev, 'verdict_mine.csv')
    with open(mine, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['idx', 'verdict', 'reason', 'cat', 'text'])
        for r in rows:
            i = r['idx']
            w.writerow([i, verdict[i], reason[i], r['cat'], r['text']])

    nk = sum(1 for r in rows if verdict[r['idx']] == 'KEEP')
    from collections import Counter
    rc = Counter(reason[r['idx']].split(':')[0].split('·')[0] for r in rows
                 if verdict[r['idx']] == 'DROP')
    print('%s：原 %d 块 → 保留 %d 块 / %d 个片段，弃用 %d 块'
          % (a.ep, len(rows), nk, len(groups), len(rows) - nk))
    for k, n in rc.most_common():
        print('   弃用·%s：%d' % (k, n))
    print('→ %s' % out)
    print('下一步：filter_subtitle.py apply --plan "%s"' % out)


if __name__ == '__main__':
    main()
