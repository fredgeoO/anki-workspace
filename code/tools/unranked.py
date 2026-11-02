# -*- coding: utf-8 -*-
"""「没有 JAR 排名」的待办清单：这些词今天不学，但记着等建卡。

为什么单独记
----------
选词要求词在 Jiten 动漫词频表里有排名：没有排名的词（字段空 / 0 / 999999）
在今天的名单里没有可比位置，直接被挡掉。但它们往往正是「本作里出现、值得学、
只是 Jiten 表里没有」的词——用户之后会为它们建素材生词卡 / 补 JAR。这份清单
就是那个待办池。

**JAR > 30000 不算「没有排名」**（2026-11-01 起）：有排名就进候选，重要性交给
模型精排；所以这类词不在本清单里。

口径
----
* 只记**词库里有卡、但没有 JAR 排名**的词（不是「库里没有的词」）；
* 同一个词重复出现 → 更新统计（次数/集数取最近一次窗口），保留 ``first_seen``；
* 一旦该词有了任何排名（用户补了 / 建卡后被回填）→ 下次运行时自动出清；
* ``doctor`` 读到非空清单就报一条 **提示**（退出码 2，不阻塞）。

只读 Anki：本模块只读写 ``data/daily_new/unranked.json``。
"""
from __future__ import annotations

import datetime as dt
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))

import paths as WSP      # noqa: E402
import textio            # noqa: E402

PATH = os.path.join(WSP.DATA, 'daily_new', 'unranked.json')
MAX_KEEP = 800           # 清单上限，超过按「最近出现 + 次数」裁掉老条目


def load(path=PATH):
    try:
        data = textio.load_json(path)
    except (OSError, ValueError):
        return {'words': {}}
    if not isinstance(data, dict):
        return {'words': {}}
    data.setdefault('words', {})
    if not isinstance(data['words'], dict):
        data['words'] = {}
    return data


def save(data, path=PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data['updated_at'] = dt.datetime.now().isoformat(timespec='seconds')
    textio.dump_json(data, path)


def _row(it, today, source):
    """候选 item（today_new_words 的 dict）→ 清单条目。"""
    return {
        'reading': it.get('reading') or '',
        'jiten': int(it.get('jiten') or 0),
        'occurrences': int(it.get('occurrences') or 0),
        'episodes': int(it.get('episodes') or 0),
        'example': (((it.get('first') or {}).get('text')) or '')[:80],
        'last_seen': today,
        'source': source,
    }


def remember(items, source='', path=PATH, today=None):
    """把一批词登记进清单 → {'added': n, 'updated': n, 'total': n}。"""
    today = today or dt.date.today().isoformat()
    data = load(path)
    words = data['words']
    added = updated = 0
    for it in items:
        w = it.get('word')
        if not w:
            continue
        row = _row(it, today, source)
        old = words.get(w)
        if old:
            row['first_seen'] = old.get('first_seen') or today
            if old.get('source') and old['source'] != source:
                row['also_seen_in'] = (old.get('also_seen_in') or [])[-3:] + [source]
            updated += 1
        else:
            row['first_seen'] = today
            added += 1
        words[w] = row
    if len(words) > MAX_KEEP:
        keep = sorted(words.items(),
                      key=lambda kv: (kv[1].get('last_seen') or '', kv[1].get('occurrences') or 0),
                      reverse=True)[:MAX_KEEP]
        data['words'] = dict(keep)
    save(data, path)
    return {'added': added, 'updated': updated, 'total': len(data['words'])}


def prune(resolved, path=PATH):
    """``resolved`` 里的词（现在已经有 JAR 排名）从清单里出清 → 被删的词列表。"""
    resolved = {w for w in resolved if w}
    if not resolved:
        return []
    data = load(path)
    gone = sorted(w for w in data['words'] if w in resolved)
    if gone:
        for w in gone:
            data['words'].pop(w, None)
        save(data, path)
    return gone


def summary(path=PATH, top=5):
    """→ (总数, 展示用行)。给 doctor 和收工汇报用。"""
    data = load(path)
    words = data['words']
    if not words:
        return 0, []
    rows = sorted(words.items(),
                  key=lambda kv: (-int(kv[1].get('occurrences') or 0),
                                  kv[1].get('last_seen') or '', kv[0]))
    lines = []
    for w, r in rows[:max(1, int(top))]:
        lines.append('%s（%s）｜%d 次/%d 集｜JAR %s｜最近 %s'
                     % (w, r.get('reading') or '—', int(r.get('occurrences') or 0),
                        int(r.get('episodes') or 0),
                        r.get('jiten') or '无', r.get('last_seen') or '—'))
    return len(words), lines


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='JAR 超范围/无排名的待办词清单')
    ap.add_argument('--all', action='store_true', help='列出全部')
    ap.add_argument('--clear', action='store_true', help='清空清单（先确认）')
    a = ap.parse_args(argv)
    data = load()
    words = data['words']
    if a.clear:
        print('清空 %d 个词（%s）' % (len(words), PATH))
        if words:
            save({'words': {}})
        return 0
    n, lines = summary(top=len(words) if a.all else 5)
    print('清单：%d 个词  %s' % (n, PATH))
    for ln in lines:
        print('  ' + ln)
    if n and not a.all:
        print('  …（--all 看全表）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
