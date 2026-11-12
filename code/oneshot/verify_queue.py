# -*- coding: utf-8 -*-
"""从集合快照按 due 排序，确认激活的卡真的排在新卡队列最前。

只读探针：经 anki_api.Snapshot（mode=ro）打开 workspace 快照
`data/snapshots/live/collection.anki2`，绝不直连 live 收藏（%APPDATA%\Anki2），
也不再往 data/snapshots/ 复制副本。
"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import paths as WSP  # noqa: E402  路径唯一来源（code/common/paths.py）
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
import anki_api as AK  # noqa: E402  Anki 读写唯一接口（含离线快照 Snapshot）

DB = os.path.join(WSP.SNAPSHOTS, 'live', 'collection.anki2')


def load_plan(path):
    plan = json.load(open(path, encoding='utf-8'))
    # cardId 在计划 JSON 里是字符串，比对前统一成 int
    targets = {int(t['cardId']): t for t in plan['targets']}
    return plan, targets


def main():
    # ⚠️ 只认旧版单文件计划（plan_activate.json）；新版每集一份在 data/plans/
    plan_path = os.path.join(WSP.DATA_PLANS, 'plan_activate.json')
    if not os.path.exists(plan_path):
        print('找不到计划文件：%s' % plan_path)
        print('（旧版单文件计划已不在；新版每集一份的 plan_activate_*.json 本脚本不认）')
        return 1

    plan, targets = load_plan(plan_path)
    snap = AK.Snapshot.open(path=DB)
    try:
        by_name = {v: k for k, v in snap.decks().items()}

        print('按 due 排序的「新卡队列最前 5 张」（快照直读，未经 AnkiConnect 过滤）')
        print('=' * 100)
        touched_decks = sorted({t['deck'] for t in plan['targets']})
        allok = True
        for deck in touched_decks:
            did = by_name.get(deck)
            if did is None:
                print('  !! 找不到 deck', deck)
                continue
            rows = snap.query("""select c.id, c.due, n.mid, n.flds from cards c
                                 join notes n on n.id=c.nid
                                 where c.did=? and c.type=0 order by c.due limit 5""",
                              (did,))
            n_target = sum(1 for t in plan['targets'] if t['deck'] == deck)
            print('\n%s   （本集激活 %d 张）' % (deck, n_target))
            for r in rows:
                f = (r['flds'] or '').split('\x1f')
                w = f[1] if len(f) > 1 else '?'
                hit = '✅ 激活' if int(r['id']) in targets else ''
                print('    due=%-8s %-16s %s' % (r['due'], w, hit))
            # 队列最前的 n_target 张是否全是被激活的
            top = snap.query("""select c.id from cards c where c.did=? and c.type=0
                                order by c.due limit ?""", (did, n_target))
            got = {int(x['id']) for x in top}
            want = {cid for cid, t in targets.items() if t['deck'] == deck}
            ok = got == want
            allok &= ok
            print('    → 队列最前 %d 张全部是激活卡: %s' % (n_target, '✅' if ok else '❌ 不符'))

        print()
        print('=' * 100)
        print('总结：%s' % ('✅ 所有 deck 的激活卡都排在各自新卡队列最前' if allok
                            else '❌ 有 deck 不符，需要检查'))
        print('=' * 100)
    finally:
        snap.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
