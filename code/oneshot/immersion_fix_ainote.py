# -*- coding: utf-8 -*-
"""修 ImmersionKit 卡片生成字段的两个**机械**问题（内容一字不动）。

适用两个牌组（`--deck`）：
* ``example``（默认，``tag:动画::* or tag:日剧::*``，例句卡）：字段 ``AINote``；闸门口径
  ``code/common/check_cards.py``（``a.count('<p>') != a.count('</p>')`` → `'<p> 标签不配对'`；
  ``'"' in a`` → `'AINote 含半角双引号'`）。
* ``mined``（``tag:素材生词``，素材生词卡）：字段同样是 ``AINote``；闸门口径
  ``code/oneshot/immersion_check_mined.py`` 的结构类硬项。

修法（本地模型偶尔写歪，文本本身没问题）：
1. 末尾那个未闭合 ``<p>`` 补 ``</p>``；``</p>`` 多出来 / 中间未闭合等怪结构走第 3 步；
2. 成对半角双引号 → 「」（``pipeline.py`` / ``mine.py`` 提示词里的约定）；
3. 按三个段落标记（中文翻译/核心词汇/语法要点）重建 ``<p>`` 结构，只动结构标签不动正文。

用法：``python code/oneshot/immersion_fix_ainote.py [--deck mined]``（只读打印）
｜ ``--commit`` 真写库。写完逐条回读比对，再重跑一遍闸门确认 0 不合格。
"""
import argparse
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))

import anki_api as AK            # noqa: E402
import check_cards as C          # noqa: E402
import immersion_check_mined as CM   # noqa: E402
import textio                    # noqa: E402  （stdio 一律走 textio，避免 GBK）

SECTIONS = ('中文翻译', '核心词汇', '语法要点')
QUERIES = {'example': 'tag:动画::* or tag:日剧::*', 'mined': 'tag:素材生词'}
FIELD = {'example': 'AINote', 'mined': 'AINote'}


def fix_p(a):
    """补末尾未闭合的 ``</p>``。→ (新值, 说明, 是否已修)"""
    op, cl = a.count('<p>'), a.count('</p>')
    if op == cl:
        return a, '', False
    if cl == 0:
        return a + '</p>' * op, '补 %d 个 </p>' % op, True
    if op == cl + 1 and a.rindex('<p>') > a.rindex('</p>'):
        return a + '</p>', '补末尾 </p>', True
    return a, '<p>/</p> 数量异常（<p> %d / </p> %d）且未闭合者不在末尾' % (op, cl), False


def fix_quotes(a):
    """成对半角双引号 → 「」。→ (新值, 说明, 是否已修)"""
    if '"' not in a:
        return a, '', False
    out, opening, n = [], True, 0
    for ch in a:
        if ch == '"':
            out.append('「' if opening else '」')
            opening = not opening
            n += 1
        else:
            out.append(ch)
    note = '%d 个半角引号 → 「」' % n
    if n % 2 == 1:
        note += '（奇数个，末尾那个按开引号处理，请人工瞄一眼）'
    return ''.join(out), note, True


def rebuild_sections(a):
    """按三个段落标记重排结构：``<p><b>X：</b>内文</p>``（正文一字不动）。

    段落标记缺失或乱序就放弃（返回 False）—— 缺段落是**内容**问题，得重问模型，不能编。
    """
    idx = []
    for k in SECTIONS:
        m = re.search(r'<b>%s：</b>' % k, a)
        idx.append(m.start() if m else -1)
    if any(i < 0 for i in idx) or idx != sorted(idx):
        return a, '段落标记缺失或乱序 → 不重建', False
    out = []
    for n, k in enumerate(SECTIONS):
        start = idx[n] + len('<b>%s：</b>' % k)
        end = idx[n + 1] if n + 1 < len(SECTIONS) else len(a)
        body = a[start:end].replace('<p>', '').replace('</p>', '').strip()
        out.append('<p><b>%s：</b>%s</p>' % (k, body))
    return ''.join(out), '按三段落重建结构', True


def fix_bold(a):
    """补段落头缺的 ``</b>``，并吃掉段尾多出来的孤立 ``</b>``。

    模型偶尔写 ``<p><b>语法要点：<br>…</b></p>`` —— 段落头少了 ``</b>``，闭合标签跑到段尾，
    于是「缺少段落：语法要点」（闸门按 ``<b>X：</b>`` 找段落）而且 `<b>` 不配对。
    """
    n = 0
    for k in SECTIONS:
        pat = '<b>%s：' % k
        i = a.find(pat)
        if i < 0 or a[i + len(pat):i + len(pat) + 4] == '</b>':
            continue
        a = a[:i + len(pat)] + '</b>' + a[i + len(pat):]
        n += 1
        j = a.find('<p>', i + len(pat) + 4)
        end = j if j > 0 else len(a)
        body = a[i + len(pat) + 4:end]
        tail = body.rstrip()
        while tail.endswith('</p>'):
            tail = tail[:-4].rstrip()
        if body.count('</b>') == 1 and '<b>' not in body and tail.endswith('</b>'):
            m = a.rfind('</b>', i, end)
            a = a[:m] + a[m + 4:]
    return a, ('补 %d 个段落头 </b>' % n) if n else '', bool(n)


def load(deck, nids=None):
    """→ [(noteId, 词, AINote, 原始 note 字段 dict)]；nids 给定时只读这些 noteId"""
    out = []
    with AK.guard():
        ids = [int(x) for x in nids] if nids else AK.find_notes(QUERIES[deck])
        for n in AK.notes_info(ids):
            f = AK.field_values(n)
            out.append((n['noteId'], f.get('Word') or f.get('Sentence', '')[:12],
                        f.get(FIELD[deck], ''), f))
    return out


def verify(deck, f, a_new):
    """拿修好的值替进字段，跑该牌组的闸门 → hard 列表（空 = 合格）"""
    f2 = dict(f)
    f2[FIELD[deck]] = a_new
    if deck == 'example':
        c = {'noteId': f.get('noteId'), 'sentence': f2.get('Sentence', ''),
             'AINote': a_new, 'SentenceHTML': f2.get('Sentence HTML', '')}
        return C.check(c)[0]
    return CM.check_note(f2)[0]


def read_nids(path, deck):
    """清单 → noteId 列表。每行 `model<TAB>noteId[<TAB>问题]` 或只有 noteId；
    首列若像 model 名（有字母）则按 deck 过滤。"""
    out = []
    for line in textio.read_text(path).splitlines():
        cols = [c.strip() for c in line.split('\t') if c.strip()]
        if not cols or cols[0].startswith('#'):
            continue
        if len(cols) >= 2 and any(ch.isalpha() for ch in cols[0]):
            if cols[0] != deck:
                continue
            out.append(cols[1])
        else:
            out.append(cols[0])
    return [x for x in out if x.isdigit()]


def main(argv=None):
    ap = argparse.ArgumentParser(description='修卡片 AINote 的 <p> 配对与半角引号')
    ap.add_argument('--deck', choices=('example', 'mined'), default='example')
    ap.add_argument('--commit', action='store_true', help='真写库（默认只打印）')
    ap.add_argument('--show', type=int, default=6, help='打印几条示例')
    ap.add_argument('--nids', help='只修这份清单里的 noteId（每行 model<TAB>noteId 或单列 noteId）')
    ap.add_argument('--allow-partial', action='store_true',
                    help='清单内修不了的卡只报告、仍写其余（配合 --nids）')
    a = ap.parse_args(argv)

    deck = a.deck
    nids = read_nids(a.nids, deck) if a.nids else None
    rows = load(deck, nids)
    src = ('清单 %s（%d 个）' % (os.path.basename(a.nids), len(nids))) if nids else QUERIES[deck]
    print('牌组 %s ｜ %s ｜ %d 张' % (deck, src, len(rows)))
    todo, manual = [], []
    for nid, word, ai, f in rows:
        if not verify(deck, f, ai):          # 本来就合格
            continue
        fixed, why = ai, []
        fixed, m, done = fix_p(fixed)
        if m:
            why.append(m)
        fixed, m2, done2 = fix_quotes(fixed)
        if m2:
            why.append(m2)
        fixed, m3, done3 = fix_bold(fixed)
        if m3:
            why.append(m3)
        if (done or done2 or done3) and not verify(deck, f, fixed):
            todo.append((nid, word, ai, fixed, '； '.join(why)))
            continue
        fixed3, m4, done4 = rebuild_sections(fixed)
        if done4 and not verify(deck, f, fixed3):
            why.append(m4)
            todo.append((nid, word, ai, fixed3, '； '.join(why)))
        else:
            manual.append((nid, word, ai, verify(deck, f, fixed3), '； '.join(why + [m4])))

    for nid, word, _o, _n, why in todo[:a.show]:
        print('  ✓ %s《%s》 %s' % (nid, word, why))
    if len(todo) > a.show:
        print('  … 其余 %d 张同形' % (len(todo) - a.show))
    for nid, word, old, new, why in [t for t in todo if '重建' in t[4] or '</b>' in t[4]][:a.show]:
        print('  ⚙ %s《%s》 %s\n      旧：%s\n      新：%s' % (nid, word, why, old[:240], new[:240]))
    for nid, word, old, hard, m in manual:
        print('  ✗ %s《%s》 修不了：%s ｜ %s' % (nid, word, hard, m))
        print('      原文：%s' % old[:200])
    print('可机械修 %d 张 ｜ 需人工/重问 %d 张' % (len(todo), len(manual)))

    if not a.commit:
        print('（演练；加 --commit 才写库）')
        return 0 if not manual else 1
    if manual and not a.allow_partial:
        print('有修不了的卡 → 本次不写库（避免半修）；按清单修时加 --allow-partial 只写能修的')
        return 1
    if manual:
        print('修不了的 %d 张只报告不写（--allow-partial）' % len(manual))
    pairs = [(nid, {FIELD[deck]: new}) for nid, _w, _o, new, _y in todo]
    with AK.guard():
        for i in range(0, len(pairs), 100):
            AK.update_notes(pairs[i:i + 100])
            print('  写入 %d/%d' % (min(i + 100, len(pairs)), len(pairs)))
        bad = [(nid, '回读不一致') for nid, new in pairs
               if AK.field_values(AK.notes_info([nid])[0]).get(FIELD[deck], '') != new[FIELD[deck]]]
        print('回读逐字段一致：%d/%d' % (len(pairs) - len(bad), len(pairs)))
    rows2 = load(deck, nids)
    left = [(nid, w, verify(deck, f, ai)) for nid, w, ai, f in rows2 if verify(deck, f, ai)]
    print('复查 %s：%d 张 ｜ 不合格 %d 张' % (src, len(rows2), len(left)))
    for nid, w, hard in left[:a.show]:
        print('  ✗ %s《%s》 %s' % (nid, w, hard))
    return 0 if (not bad and not left) else 1


if __name__ == '__main__':
    raise SystemExit(main())
