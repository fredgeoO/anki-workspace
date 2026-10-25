# -*- coding: utf-8 -*-
"""把「素材优先词表」转成 ``code/execution/activate.py`` 能直接吃的激活计划。

为什么这样做（而不是搬卡组）
--------------------------
* Anki 新卡队列按 ``cards.due``（即"位置"）取卡，把位置排到最前 = 优先学；
  这和 Anki 自带的「浏览器 → 重新定位」是同一个动作，**不影响任何学习进度**。
* ``activate.py`` 已经把这套写库路径验证过：只碰 type==0、只写 due、
  plan 只读、apply 默认演练、revert 可回退。
* 搬卡组（changeDeck）会让 core6000/考级 的「已学 X/6000」统计失真，
  也会让 ``code/analysis/vocab_cover/collect_vocab.py`` 按卡组名认不出这些词，
  覆盖率报告会跳变 —— 所以不搬。

本脚本只做两件事：
1. 从 live Anki 读出「这些词现在还是新卡的」cardId/noteId/due_before（只读）；
2. 按素材频次顺序写一份 activate.py 兼容的 plan（写到 data/plans/，不碰 Anki）。

用法::

    python code/analysis/vocab_cover/make_activate_plan.py                # 用 critical_path 清单
    python code/analysis/vocab_cover/make_activate_plan.py --top 300      # 只取前 300 个词
    python code/analysis/vocab_cover/make_activate_plan.py --words-file X.json --tag 素材优先

之后（走 activate.py 的既有闸门）::

    python code/execution/activate.py apply  --plan data/plans/plan_activate_素材优先.json            # 演练
    python code/execution/activate.py apply  --plan data/plans/plan_activate_素材优先.json --commit   # 真写
    python code/execution/activate.py revert --plan data/plans/plan_activate_素材优先.json --commit   # 回退
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import re
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _deps import DATA_DIR, WSP, add_pylibs, write_json  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
from _norm import norm_word, primary_form  # noqa: E402

CRITICAL = os.path.join(DATA_DIR, 'study_plan_critical_path.json')
PLAN_DIR = os.path.join(WSP.DATA, 'plans')
AC_URL = os.environ.get('ANKICONNECT_URL', 'http://127.0.0.1:8765')
TAG_PREFIX = '素材激活::'
BATCH = 200

DECK_GROUPS = {
    'core6000': ['0-日本语学习::0-词汇::1-高频日语单词 6000'],
    'jlpt': ['0-日本语学习::0-词汇::2-考级词汇'],
    'mined': ['0-日本语学习::0-词汇::0-素材生词', '0-日本语学习::2-例句'],
}
WORD_FIELDS = ('Word', 'VocabKanji', 'Expression', 'Front', 'Vocabulary', '単語')
PREFER = {'core6000': 0, 'jlpt': 1, 'mined': 2}


def ac(action: str, **params):
    body = json.dumps({'action': action, 'version': 6, 'params': params},
                      ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(AC_URL, body, {'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=300).read().decode('utf-8'))
    if r.get('error'):
        raise SystemExit('AnkiConnect 错误 [%s]: %s' % (action, r['error']))
    return r['result']


def batched(seq, n=BATCH):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def clean_field(v: str) -> str:
    v = re.sub(r'\[sound:[^\]]*\]', '', v or '')
    v = re.sub(r'<[^>]+>', '', v)
    return re.sub(r'\s+', ' ', v).strip()


def group_of(deck: str) -> str:
    for g, prefixes in DECK_GROUPS.items():
        for p in prefixes:
            if deck == p or deck.startswith(p + '::'):
                return g
    return ''


def level_of(deck: str) -> str:
    g = group_of(deck)
    if g == 'core6000':
        return 'Core'
    if g == 'mined':
        return 'Mine'
    m = re.search(r'(N[1-5])', deck)
    return m.group(1) if m else 'JLPT'


def collect_new_cards(exclude_prefixes=()) -> dict:
    """-> {归一化词: [(cardId, noteId, deck, due_before, surface), ...]}，只含仍是新卡的。

    ``exclude_prefixes`` 里的卡组（含其子卡组）不参与 —— 例如 ``0-日本语学习::2-例句``
    是例句卡，有它自己的激活路径，不该混进词汇词频队列。
    """
    deck_names = ac('deckNames')
    targets = [d for d in deck_names if group_of(d)
               and not any(d == p or d.startswith(p + '::') for p in exclude_prefixes)]
    query = 'is:new (' + ' or '.join('deck:"%s"' % d for d in targets) + ')'
    cids = ac('findCards', query=query)
    cards = []
    for b in batched(cids):
        cards.extend(ac('cardsInfo', cards=b))
    cards = [c for c in cards if c.get('type') == 0]
    nids = sorted({c['note'] for c in cards})
    notes = {}
    for b in batched(nids):
        for n in ac('notesInfo', notes=b) or []:
            fields = {k: clean_field(v.get('value', '')) for k, v in n['fields'].items()}
            word = ''
            for f in WORD_FIELDS:
                if fields.get(f):
                    word = fields[f]
                    break
            if not word:
                word = next((v for v in fields.values() if v), '')
            notes[n['noteId']] = word
    index = collections.defaultdict(list)
    for c in cards:
        word = notes.get(c['note'])
        if not word:
            continue
        key = norm_word(primary_form(word)) or norm_word(word)
        if key:
            index[key].append((c['cardId'], c['note'], c['deckName'], c.get('due'), word))
    return index


def main() -> int:
    ap = argparse.ArgumentParser(description='生成素材优先的 activate.py 计划')
    ap.add_argument('--words-file', default=CRITICAL, help='词表 JSON（默认 study_plan_critical_path.json）')
    ap.add_argument('--tag', default='素材优先',
                    help='溯源标签后缀（最终标签 = 素材激活::<tag>）；'
                         '注意这不是 2026-10-06 退场的准入标签')
    ap.add_argument('--top', type=int, default=0, help='只取前 N 个词（0=全部）')
    ap.add_argument('--min-count', type=int, default=1, help='素材出现次数下限')
    ap.add_argument('--exclude-decks', default='',
                    help='逗号分隔的卡组前缀，这些卡组（含子卡组）不参与。'
                         '外部词表排序时用 "0-日本语学习::2-例句" 把例句卡排除，'
                         '这样计划只覆盖需要排的词汇卡')
    ap.add_argument('--all-cards', action='store_true',
                    help='同一个词的**每张**新卡都排（默认只取 Core>JLPT>Mine 一张）。'
                         '外部词表要覆盖全部未学新卡时必须加这个，否则剩下的同类卡会'
                         '带着原来的随机位置插到队首前面去')
    ap.add_argument('--out', default=None, help='计划输出路径')
    args = ap.parse_args()

    add_pylibs()
    rows = json.load(open(args.words_file, encoding='utf-8'))
    rows = [r for r in rows if r['corpus_count'] >= args.min_count]
    if args.top:
        rows = rows[:args.top]
    print(f'候选词 {len(rows)} 个（来自 {os.path.relpath(args.words_file, WSP.ROOT)}）')

    exclude = tuple(p.strip() for p in args.exclude_decks.split(',') if p.strip())
    index = collect_new_cards(exclude)
    if exclude:
        print(f'已排除卡组：{"、".join(exclude)}')
    print(f'live Anki 里仍是新卡的词：{len(index)} 个')

    targets, missing, multi = [], [], 0
    matched_keys = set()
    for i, r in enumerate(rows):
        key = norm_word(r['word'])
        cands = index.get(key)
        if not cands:
            missing.append(r['word'])
            continue
        matched_keys.add(key)
        cands = sorted(cands, key=lambda c: (PREFER.get(group_of(c[2]), 9), c[2]))
        if len(cands) > 1:
            multi += 1
        # --all-cards：同一个词的每张新卡都排上（Core>JLPT>Mine 顺序相邻）。
        # 为什么需要：只排一张的话，**同一个词的其余新卡会保留原来的位置**，而那些位置是
        # Anki「新卡随机插队」（new_card_insert_order=RANDOM）给的散乱小整数（1、3、4…），
        # 于是它们会插到排好的词频队列**前面**去，全局顺序就废了。实测有 2,326 张这种卡。
        for cid, nid, deck, due, _surface in (cands if args.all_cards else cands[:1]):
            targets.append({
                'word': r['word'], 'lv': level_of(deck), 'deck': deck,
                'cardId': cid, 'noteId': nid,
                'occurrences': r['corpus_count'], 'due_before': due, 'sentence': '',
                # 外部词表（freq_external.py）的行带 freq_rank：那才是真排名，
                # occurrences 对它是 10**6//rank 的合成值。本地语料清单没有这个字段。
                'freq_rank': r.get('freq_rank'),
                'alt_decks': [c[2] for c in cands if c[0] != cid],
            })

    # 词表里查不到的新卡（实测 101 张：自然に/必死に 这类带助词的词条、剝げる 这类异体字、
    # 以及 Jiten 动画表里确实没有的词）统一排到**队尾**。不排它们的话，它们会带着原来的
    # 随机位置（2641、2713…）插进排好的队列中间，同样是破坏全局顺序。
    unmatched_cards = 0
    if args.all_cards:
        for key in sorted(k for k in index if k not in matched_keys):
            for cid, nid, deck, due, surface in index[key]:
                unmatched_cards += 1
                targets.append({
                    'word': surface, 'lv': level_of(deck), 'deck': deck,
                    'cardId': cid, 'noteId': nid,
                    'occurrences': 0, 'due_before': due, 'sentence': '',
                    'freq_rank': None, 'alt_decks': [],
                })

    activation_tag = TAG_PREFIX + args.tag.replace(' ', '_')
    plan = {
        'tag': args.tag,
        'activation_tag': activation_tag,
        'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
        'source': os.path.relpath(args.words_file, WSP.ROOT).replace('\\', '/'),
        'note': '由 vocab_cover/make_activate_plan.py 生成：按素材频次把新卡排到各卡组最前',
        'targets': targets,
        'excluded': [],
    }
    out = args.out or os.path.join(PLAN_DIR, 'plan_activate_%s.json' % args.tag)
    os.makedirs(PLAN_DIR, exist_ok=True)
    write_json(plan, out)

    by_deck = collections.Counter(t['deck'] for t in targets)
    print()
    print(f'计划已写出：{os.path.relpath(out, WSP.ROOT)}')
    print(f'  激活目标 {len(targets)} 张（全部是 live 里的新卡）')
    print(f'  同一个词有多张新卡的词：{multi} 个'
          + ('（--all-cards：每张都排上了）' if args.all_cards
             else '（只取了 Core>JLPT>Mine 的一张；其余同类卡位置不变，'
                  '外部词表排序时要加 --all-cards）'))
    if args.all_cards:
        print(f'  词表里查不到、排到队尾的新卡：{unmatched_cards} 张')
    print(f'  词表里有、但已不是新卡（已学过，脚本不会碰）的：{len(missing)} 个')
    if missing[:10]:
        print('    例如：' + '、'.join(missing[:10]))
    print('  按卡组分布：')
    for d, n in sorted(by_deck.items(), key=lambda kv: -kv[1]):
        print(f'    {n:>5}  {d}')
    print()
    print('下一步（activate.py 自带闸门：默认演练，--commit 才写库）：')
    print(f'  python code/execution/activate.py apply  --plan "{out}"')
    print(f'  python code/execution/activate.py apply  --plan "{out}" --commit')
    print(f'  python code/execution/activate.py revert --plan "{out}" --commit')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
