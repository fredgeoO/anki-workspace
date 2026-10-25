# -*- coding: utf-8 -*-
"""一次性迁移：把现有的素材卡补上统一准入标签 ``素材优先``。

> ⚠ **历史脚本（2026-10-10 注）**：本文描述的「素材优先准入标签 + 筛选牌组」机制已于
> 2026-10-06 **退场**（标签已清零、筛选牌组已删），`activate.py` / `mine.py` 也自
> 2026-10-10 起不再写该标签。本脚本保留作历史参考与「万一要回退」的凭据 ——
> 全记录与恢复路径见 docs/deprecated.md §2。

背景（2026-10-05 的设计统一）
---------------------------
以前有三个并行的命名空间：``素材激活::<集>``、``素材生词::<来源>``、``动画::<集>``。
现在统一成「一个准入标签 + 溯源标签仍在」：

* **准入**：``素材优先`` —— 筛选牌组「素材优先」只搜 ``is:new tag:素材优先``，
  于是全库只有一个新卡入口（大卡组 new/day=0，只做复习）。
* **溯源**：``素材激活::<集>`` / ``素材生词::<来源>`` 全部保留，回退与追查都还靠它们。

两个范围（``--scope``）
----------------------
* ``material``（默认，2026-10-05 原本的行为）：给「已经带 素材激活* 或 素材生词* 但还没
  有 素材优先」的笔记补标签。**只覆盖素材卡**。
* ``vocab-new``（2026-10-06 新增）：给**三个词汇卡组里所有还不带 素材优先 的新卡笔记**补标签。
  为什么需要：core6000/考级的存量新卡从来没走过素材路径，所以一条素材标签都没有 ——
  实测 11,990 张新卡里只有 405 张带标签，筛选牌组根本搜不到其余 1 万多张，
  于是「按外部词表排序的单一队列」落不了地。补完之后筛选牌组（order=DUE）才是
  唯一的新卡入口，取卡顺序 = ``cards.due`` = 词表排名（见 docs/architecture.md §5）。

幂等（重复跑不会重复加），并且可以按范围一键回退。

用法::

    python code/oneshot/migrate_pool_tag.py                          # 演练（素材卡范围）
    python code/oneshot/migrate_pool_tag.py --commit                 # 真写
    python code/oneshot/migrate_pool_tag.py --scope vocab-new                    # 演练（存量新卡）
    python code/oneshot/migrate_pool_tag.py --scope vocab-new --commit           # 真写
    python code/oneshot/migrate_pool_tag.py --scope vocab-new --revert --commit  # 只撤销这一范围
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

AC_URL = 'http://127.0.0.1:8765'
POOL_TAG = '素材优先'
SOURCE_PREFIXES = ('素材激活::', '素材生词::')
BATCH = 200
_DATA_VC = os.path.join(WSP.DATA, 'vocab_cover')

# 三个词汇卡组（与 vocab_cover/make_activate_plan.py 的 DECK_GROUPS 同一批）；
# deck: 搜索包含子卡组，所以写父卡组即可覆盖考级那些 ::N1/::N2 子牌组。
VOCAB_ROOTS = (
    '0-日本语学习::0-词汇::1-高频日语单词 6000',
    '0-日本语学习::0-词汇::2-考级词汇',
    '0-日本语学习::0-词汇::0-素材生词',
)

SCOPES = {
    'material': {
        'label': '带 素材激活*/素材生词* 的笔记（素材卡）',
        'query': ('(' + ' or '.join('tag:%s*' % p for p in SOURCE_PREFIXES) + ')'
                  + ' -tag:' + POOL_TAG),
        'state': os.path.join(_DATA_VC, 'pool_tag_migration.json'),
    },
    'vocab-new': {
        'label': '三个词汇卡组里的存量新卡笔记',
        'query': ('is:new (' + ' or '.join('deck:"%s"' % d for d in VOCAB_ROOTS) + ')'
                  + ' -tag:' + POOL_TAG),
        'state': os.path.join(_DATA_VC, 'pool_tag_migration_vocab_new.json'),
    },
}


def ac(action, **params):
    body = json.dumps({'action': action, 'version': 6, 'params': params},
                      ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(AC_URL, body, {'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=300).read().decode('utf-8'))
    if r.get('error'):
        raise SystemExit('AnkiConnect [%s]: %s' % (action, r['error']))
    return r['result']


def batched(seq, n=BATCH):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def collect_targets(scope: dict) -> list:
    """-> 需要补标签的 noteId 列表。"""
    return ac('findNotes', query=scope['query'])


def describe(nids: list) -> collections.Counter:
    """按已有的素材前缀统计，便于确认范围。"""
    c = collections.Counter()
    for b in batched(nids):
        for n in ac('notesInfo', notes=b) or []:
            tags = [t for t in n.get('tags', []) if t.startswith(SOURCE_PREFIXES)]
            c[tags[0].split('::')[0] if tags else '(无素材前缀)'] += 1
    return c


def describe_decks(nids: list, sample: int = 1000) -> collections.Counter:
    """按卡组统计（看范围对不对）。只抽样 cardsInfo，避免上万次往返。"""
    c = collections.Counter()
    cids = []
    for b in batched(nids[:sample]):
        cids.extend(ac('findCards', query='nid:' + ','.join(str(x) for x in b)) or [])
    for b in batched(cids):
        for card in ac('cardsInfo', cards=b) or []:
            c[card['deckName']] += 1
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description='给现有素材卡补/撤统一准入标签 素材优先')
    ap.add_argument('--scope', choices=sorted(SCOPES), default='material',
                    help='material=素材卡（默认）；vocab-new=三个词汇卡组的存量新卡')
    ap.add_argument('--commit', action='store_true', help='真写库（不加则只演练）')
    ap.add_argument('--revert', action='store_true', help='撤销：从这些笔记上摘掉 素材优先')
    args = ap.parse_args()
    scope = SCOPES[args.scope]
    STATE = scope['state']

    pool_n = len(ac('findNotes', query='tag:%s' % POOL_TAG))
    print('范围：%s（--scope %s）' % (scope['label'], args.scope))
    print('当前带 %s 的笔记：%d 个' % (POOL_TAG, pool_n))
    print('模式：%s' % ('★ 真写库' if args.commit else '演练（不写库）'))
    print()

    if args.revert:
        if not os.path.exists(STATE):
            raise SystemExit('找不到迁移记录 %s，无法安全回退。' % STATE)
        nids = json.load(open(STATE, encoding='utf-8'))['note_ids']
        print('回退：将从这个脚本当初加过标签的 %d 个笔记上摘掉 %s' % (len(nids), POOL_TAG))
        if not args.commit:
            print('演练结束，未写库。加 --commit 真回退。')
            return 0
        for b in batched(nids):
            ac('removeTags', notes=b, tags=POOL_TAG)
        print('已摘除。现在带 %s 的笔记：%d 个'
              % (POOL_TAG, len(ac('findNotes', query='tag:%s' % POOL_TAG))))
        return 0

    nids = collect_targets(scope)
    print('需要补 %s 的笔记：%d 个' % (POOL_TAG, len(nids)))
    if nids:
        print('  来源构成：', dict(describe(nids)))
        deckc = describe_decks(nids)
        print('  卡组构成（抽样最多 1000 张卡）：')
        for d, n in deckc.most_common(12):
            print('    %6d  %s' % (n, d))
        for b in list(batched(nids))[:1]:
            for n in (ac('notesInfo', notes=b[:5]) or []):
                w = next((v['value'] for k, v in n['fields'].items()
                          if k in ('Word', 'VocabKanji', 'Front') and v['value']), '')
                print('    %-14s tags=%s' % (w[:14], [t for t in n['tags']
                                                      if t.startswith(SOURCE_PREFIXES)]))
    if not nids:
        print('无需变更。')
        return 0

    if not args.commit:
        print('\n演练结束，未写库。确认无误后加 --commit。')
        print('（回退记录会写到 %s）' % STATE)
        return 0

    for b in batched(nids):
        ac('addTags', notes=b, tags=POOL_TAG)
    after = len(ac('findNotes', query='tag:%s' % POOL_TAG))
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({'pool_tag': POOL_TAG, 'scope': args.scope, 'query': scope['query'],
               'note_ids': nids, 'count': len(nids)},
              open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n已打标签 %d 个笔记；现在带 %s 的笔记：%d 个' % (len(nids), POOL_TAG, after))
    print('回退记录：%s' % STATE)
    print('回退命令：python code/oneshot/migrate_pool_tag.py --scope %s --revert --commit'
          % args.scope)
    print('\n下一步：把筛选牌组的搜索改成  is:new tag:%s' % POOL_TAG)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
