# -*- coding: utf-8 -*-
"""写库事务内核 —— 演练 / 备份 / 写 / 回读，只在这一个地方实现。

背景
----
2026-11-01 盘点：30 个文件里出现过 ``--commit``，但只有 7 个调用
``AK.verify_note_fields``。每个脚本自己写一遍“演练→写→回读”，于是
“写后必回读”这条铁律实际上靠自觉。

本模块只暴露两种写：

* :func:`write_fields` —— 写笔记字段（``AINote`` / ``Meaning`` / ...）
* :func:`write_tags`   —— 加/摘标签

**结构上碰不到调度列**：本文件不 import、不调用 ``set_card_due`` /
``set_card_values`` / ``forget_cards``，所以
“due/ivl/factor/type/queue/reps/lapses 不许碰”不需要靠记性。

用法::

    import writeback as WB

    rep = WB.write_fields({123: {'AINote': html}}, commit=a.commit, label='cards')
    rep = WB.write_tags(ids, add=['复习::X'], commit=a.commit, label='tag')
    if not rep['ok']:
        return 1

返回的 ``rep``：

    label / kind / count / commit / backup / bad / ok
    bad = {noteId: ['缺 AINote', 'updateNoteFields 失败', ...]}

行为：演练只打印将写多少与抽样 diff；真写先把旧值备份到
``data/writeback/<时间戳>-<label>.json``，再写、再回读。大批量自动分块
（``chunk``，默认 200）并可块间停顿（``pause``）；``quiet=True`` 时内核不打印，
交给调用方自己的汇报。
"""

from __future__ import annotations

import datetime as dt
import os
import re
import time

import anki_api as AK
import audio_names
import paths as WSP
import textio

MAX_PREVIEW = 3
PREVIEW_CHARS = 72
DEFAULT_SETTLE = 0.5


def _slug(label):
    return audio_names.safe_token(label, fallback='writeback', limit=40)


def _short(value, limit=PREVIEW_CHARS):
    """HTML 去掉标签、压成一行，便于在终端里看 diff。"""
    s = re.sub(r'<[^>]+>', '', str(value or ''))
    s = ' '.join(s.split())
    return s[:limit] + ('…' if len(s) > limit else '')


def _backup_path(label, kind, backup_dir=None):
    root = backup_dir or WSP.DATA_WRITEBACK
    os.makedirs(root, exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3]
    return os.path.join(root, '%s-%s.%s.json' % (stamp, _slug(label), kind))


def _summary(rep, quiet=False):
    if quiet:
        return
    if rep['ok']:
        print('[writeback] %s：%d 张，回读通过' % (rep['label'] or '(未命名)', rep['count']))
        return
    bad = rep['bad']
    head = '、'.join('%s(%s)' % (nid, ','.join(why)) for nid, why in list(bad.items())[:5])
    print('[writeback] %s：%d 张，回读失败 %d 张：%s%s'
          % (rep['label'] or '(未命名)', rep['count'], len(bad), head,
             ' …' if len(bad) > 5 else ''))


def write_fields(expected, *, commit=False, label='', backup=True, verify=True,
                 settle=DEFAULT_SETTLE, chunk=200, pause=0.0, quiet=False,
                 backup_dir=None):
    """写笔记字段。``expected`` = ``{noteId: {字段名: 新值}}``。

    ``commit=False`` 只预览；``commit=True`` 备份旧值 → 分块写 → 回读。
    ``chunk`` 是每批张数（大批量自动分块），``pause`` 是块间停顿秒数。
    ``rep['ok']`` 为 True 表示所有笔记都写成功且回读一致。
    """
    say = (lambda *a, **k: None) if quiet else print
    want = {}
    for nid, fields in (expected or {}).items():
        clean = {str(k): ('' if v is None else str(v)) for k, v in (fields or {}).items()}
        if clean:
            want[int(nid)] = clean
    rep = {'kind': 'fields', 'label': label, 'count': len(want), 'commit': bool(commit),
           'backup': '', 'bad': {}, 'ok': True}
    if not want:
        say('[writeback] %s：没有要写的字段' % (label or '(未命名)'))
        return rep

    ids = sorted(want)
    names = sorted({f for fields in want.values() for f in fields})
    live = AK.note_values(ids, names=names)
    say('[writeback] %s：%d 张 / 字段 %s'
        % (label or '(未命名)', len(want), '、'.join(names)))

    shown = 0
    for nid in ids:
        for f in names:
            after = want[nid].get(f)
            before = live.get(nid, {}).get(f, '')
            if after is None or before == after:
                continue
            say('  · %s %s：%s → %s' % (nid, f, _short(before) or '(空)', _short(after)))
            shown += 1
            if shown >= MAX_PREVIEW:
                break
        if shown >= MAX_PREVIEW:
            break

    if not commit:
        say('[writeback] 演练：未写库（加 --commit 才写）')
        return rep

    before = {nid: {f: live.get(nid, {}).get(f, '') for f in want[nid]} for nid in ids}
    if backup:
        path = _backup_path(label, 'fields', backup_dir)
        textio.dump_json({'at': dt.datetime.now().isoformat(timespec='seconds'),
                          'label': label, 'kind': 'fields',
                          'expected': want, 'before': before}, path)
        rep['backup'] = path
        say('[writeback] 旧值已备份：%s' % path)

    step = max(1, int(chunk or len(ids)))
    written = 0
    for i in range(0, len(ids), step):
        part = [(nid, want[nid]) for nid in ids[i:i + step]]
        for nid, ok in (AK.update_notes(part) or []):
            if not ok:
                rep['bad'].setdefault(nid, []).append('updateNoteFields 失败')
        written += len(part)
        if pause:
            time.sleep(pause)
        if written < len(ids):
            say('  已写 %d/%d' % (written, len(ids)))

    if verify:
        verified = AK.verify_note_fields(want, settle=settle, chunk=chunk) or {}
        for nid, fields in verified.items():
            rep['bad'].setdefault(nid, []).extend('缺 %s' % f for f in fields)

    rep['ok'] = not rep['bad']
    _summary(rep, quiet=quiet)
    return rep


def write_tags(ids, *, add=(), remove=(), commit=False, label='', backup=True,
               verify=True, settle=DEFAULT_SETTLE, chunk=200, pause=0.0,
               quiet=False, backup_dir=None):
    """加/摘标签。``add`` / ``remove`` 是标签列表；分块后先摘后加。

    回读规则：``add`` 里的每个标签都要在笔记上，``remove`` 里的都不能残留。
    """
    say = (lambda *a, **k: None) if quiet else print
    nids = sorted({int(x) for x in (ids or [])})
    adds = [str(t).strip() for t in (add or []) if str(t).strip()]
    rems = [str(t).strip() for t in (remove or []) if str(t).strip()]
    rep = {'kind': 'tags', 'label': label, 'count': len(nids), 'commit': bool(commit),
           'add': adds, 'remove': rems, 'backup': '', 'bad': {}, 'ok': True}
    if not nids or not (adds or rems):
        say('[writeback] %s：没有要改的标签' % (label or '(未命名)'))
        return rep

    live = AK.notes_map(nids, chunk=chunk)
    say('[writeback] %s：%d 张 / %s%s%s'
        % (label or '(未命名)', len(nids),
           ('加 ' + '、'.join(adds)) if adds else '',
           '；' if adds and rems else '',
           ('摘 ' + '、'.join(rems)) if rems else ''))
    missing = [nid for nid in nids if nid not in live]
    if missing:
        say('[writeback] ⚠ 有 %d 张笔记已不存在：%s' % (len(missing), missing[:5]))

    if not commit:
        say('[writeback] 演练：未写库（加 --commit 才写）')
        return rep

    if backup:
        path = _backup_path(label, 'tags', backup_dir)
        textio.dump_json({'at': dt.datetime.now().isoformat(timespec='seconds'),
                          'label': label, 'kind': 'tags', 'add': adds, 'remove': rems,
                          'before': {nid: (live.get(nid) or {}).get('tags') or []
                                     for nid in nids}}, path)
        rep['backup'] = path
        say('[writeback] 旧标签已备份：%s' % path)

    step = max(1, int(chunk or len(nids)))
    done = 0
    for i in range(0, len(nids), step):
        part = nids[i:i + step]
        if rems:
            AK.remove_tags(part, rems)
        if adds:
            AK.add_tags(part, adds)
        done += len(part)
        if pause:
            time.sleep(pause)
        if done < len(nids):
            say('  已写 %d/%d' % (done, len(nids)))

    if verify:
        if settle:
            time.sleep(settle)
        now = AK.notes_map(nids, chunk=chunk)
        for nid in nids:
            note = now.get(nid)
            if note is None:
                rep['bad'][nid] = ['笔记不存在']
                continue
            tags = set(note.get('tags') or [])
            why = ['缺 %s' % t for t in adds if t not in tags]
            why += ['残留 %s' % t for t in rems if t in tags]
            if why:
                rep['bad'][nid] = why

    rep['ok'] = not rep['bad']
    _summary(rep, quiet=quiet)
    return rep
