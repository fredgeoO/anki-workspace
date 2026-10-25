# -*- coding: utf-8 -*-
"""从集合快照按 due 排序，确认激活的卡真的排在新卡队列最前。"""
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

SRC = Path(WSP.ANKI_PROFILE)
TMP = Path(WSP.SNAPSHOTS) / "ankisnap2"
TMP.mkdir(exist_ok=True)
for suf in ("", "-wal", "-shm"):
    s = Path(str(SRC / "collection.anki2") + suf)
    if s.exists():
        shutil.copy2(s, Path(str(TMP / "c.anki2") + suf))

db = sqlite3.connect(str(TMP / "c.anki2"))
db.row_factory = sqlite3.Row
db.create_collation("unicase", lambda a, b: (a > b) - (a < b))
decks = {r["id"]: r["name"].replace("\x1f", "::") for r in db.execute("select id,name from decks")}
by_name = {v: k for k, v in decks.items()}
models = {r["id"]: r["name"] for r in db.execute("select id,name from notetypes")}

# ⚠️ 只认旧版单文件计划（plan_activate.json）；新版每集一份在 data/plans/
plan = json.load(open(os.path.join(WSP.DATA_PLANS, 'plan_activate.json'), encoding='utf-8'))
targets = {t['cardId']: t for t in plan['targets']}

print('按 due 排序的「新卡队列最前 5 张」（快照直读，未经 AnkiConnect 过滤）')
print('=' * 100)
touched_decks = sorted({t['deck'] for t in plan['targets']})
allok = True
for deck in touched_decks:
    did = by_name.get(deck)
    if did is None:
        print('  !! 找不到 deck', deck)
        continue
    rows = db.execute("""select c.id, c.due, n.mid, n.flds from cards c
                         join notes n on n.id=c.nid
                         where c.did=? and c.type=0 order by c.due limit 5""",
                      (did,)).fetchall()
    n_target = sum(1 for t in plan['targets'] if t['deck'] == deck)
    print('\n%s   （本集激活 %d 张）' % (deck, n_target))
    for r in rows:
        f = r['flds'].split('\x1f')
        w = f[1] if len(f) > 1 else '?'
        hit = '✅ 激活' if r['id'] in targets else ''
        print('    due=%-8s %-16s %s' % (r['due'], w, hit))
    # 队列最前的 n_target 张是否全是被激活的
    top = db.execute("""select c.id from cards c where c.did=? and c.type=0
                        order by c.due limit ?""", (did, n_target)).fetchall()
    got = {x['id'] for x in top}
    want = {cid for cid, t in targets.items() if t['deck'] == deck}
    ok = got == want
    allok &= ok
    print('    → 队列最前 %d 张全部是激活卡: %s' % (n_target, '✅' if ok else '❌ 不符'))

print()
print('=' * 100)
print('总结：%s' % ('✅ 所有 deck 的激活卡都排在各自新卡队列最前' if allok
                    else '❌ 有 deck 不符，需要检查'))
print('=' * 100)
