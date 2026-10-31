# -*- coding: utf-8 -*-
"""回归测试：writeback 写库内核（演练 / 备份 / 写 / 回读）。

挡五件事：
1. 演练模式偷偷写库；
2. 真写前不备份旧值；
3. 写完不回读（坏卡当成功）；
4. 回读失败不报告（ok 恒 True）；
5. 内核里出现调度接口调用（due/ivl 那条铁律的结构保证）。

纯离线：AK 全部用假函数替换；备份写到 temp/test_writeback，不碰 data/。
跑法：& $PY code\\tests\\test_writeback.py
"""
import contextlib
import io
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio  # noqa: E402  stdio 唯一入口
import paths as WSP  # noqa: E402
import writeback as WB  # noqa: E402

BD = os.path.join(WSP.TEMP, 'test_writeback')
FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


@contextlib.contextmanager
def patched(**fns):
    old = {k: getattr(WB.AK, k) for k in fns}
    for k, v in fns.items():
        setattr(WB.AK, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(WB.AK, k, v)


def reset_bd():
    if os.path.isdir(BD):
        shutil.rmtree(BD)
    os.makedirs(BD)


def backups():
    return sorted(os.listdir(BD)) if os.path.isdir(BD) else []


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def test_dry_fields():
    calls = {'update': 0, 'verify': 0}

    def fake_values(ids, names=None, chunk=None):
        return {nid: {n: 'old' for n in (names or [])} for nid in ids}

    def fake_update(pairs):
        calls['update'] += 1
        return [(nid, True) for nid, _ in pairs]

    def fake_verify(want, settle=0.5, chunk=None):
        calls['verify'] += 1
        return {}

    with patched(note_values=fake_values, update_notes=fake_update,
                 verify_note_fields=fake_verify):
        rep = quiet(WB.write_fields, {1: {'AINote': 'x'}, 2: {'AINote': 'y'}})
    check('演练：报告 2 张', rep['count'] == 2, rep)
    check('演练：不写库', calls['update'] == 0, calls)
    check('演练：不回读', calls['verify'] == 0, calls)
    check('演练：不备份', backups() == [], backups())


def test_commit_fields():
    calls = {'pairs': [], 'verify': None}

    def fake_values(ids, names=None, chunk=None):
        return {nid: {n: 'old-' + n for n in (names or [])} for nid in ids}

    def fake_update(pairs):
        calls['pairs'] = list(pairs)
        return [(nid, True) for nid, _ in pairs]

    def fake_verify(want, settle=0.5, chunk=None):
        calls['verify'] = want
        return {}

    reset_bd()
    with patched(note_values=fake_values, update_notes=fake_update,
                 verify_note_fields=fake_verify):
        rep = quiet(WB.write_fields, {1: {'AINote': 'x'}, 2: {'AINote': 'y'}},
                    commit=True, label='t', settle=0, backup_dir=BD)
    check('真写：ok', rep['ok'] is True, rep)
    check('真写：写了两张', len(calls['pairs']) == 2, calls['pairs'])
    check('真写：回读的是期望值', calls['verify'] == {1: {'AINote': 'x'},
                                                      2: {'AINote': 'y'}}, calls['verify'])
    check('真写：留下备份', len(backups()) == 1, backups())
    if backups():
        import json
        with open(os.path.join(BD, backups()[0]), encoding='utf-8') as fh:
            saved = json.load(fh)
        check('备份含旧值', saved['before']['1']['AINote'] == 'old-AINote', saved)


def test_commit_fields_verify_bad():
    def fake_values(ids, names=None, chunk=None):
        return {nid: {n: 'old' for n in (names or [])} for nid in ids}

    def fake_update(pairs):
        return [(nid, True) for nid, _ in pairs]

    def fake_verify(want, settle=0.5, chunk=None):
        return {2: ['AINote']}

    reset_bd()
    with patched(note_values=fake_values, update_notes=fake_update,
                 verify_note_fields=fake_verify):
        rep = quiet(WB.write_fields, {1: {'AINote': 'x'}, 2: {'AINote': 'y'}},
                    commit=True, label='t', settle=0, backup_dir=BD)
    check('回读失败：ok=False', rep['ok'] is False, rep)
    check('回读失败：列出坏卡', 2 in rep['bad'], rep['bad'])


def test_commit_fields_update_fail():
    def fake_values(ids, names=None, chunk=None):
        return {nid: {} for nid in ids}

    def fake_update(pairs):
        return [(nid, nid != 2) for nid, _ in pairs]

    def fake_verify(want, settle=0.5, chunk=None):
        return {}

    reset_bd()
    with patched(note_values=fake_values, update_notes=fake_update,
                 verify_note_fields=fake_verify):
        rep = quiet(WB.write_fields, {1: {'AINote': 'x'}, 2: {'AINote': 'y'}},
                    commit=True, label='t', settle=0, backup_dir=BD)
    check('写失败：ok=False', rep['ok'] is False, rep)
    check('写失败：点名 2', 2 in rep['bad'], rep['bad'])


def test_tags_add():
    state = {1: [], 2: []}
    calls = {'add': [], 'remove': []}

    def fake_map(ids, chunk=None):
        return {nid: {'noteId': nid, 'tags': list(state[nid])} for nid in ids}

    def fake_add(ids, tags):
        calls['add'].append((list(ids), list(tags)))
        for nid in ids:
            state[nid].extend(tags)

    def fake_remove(ids, tags):
        calls['remove'].append((list(ids), list(tags)))
        for nid in ids:
            state[nid] = [t for t in state[nid] if t not in tags]

    reset_bd()
    with patched(notes_map=fake_map, add_tags=fake_add, remove_tags=fake_remove):
        rep = quiet(WB.write_tags, [1, 2], add=['复习::X'], commit=True,
                    label='tag', settle=0, backup_dir=BD)
    check('加标签：ok', rep['ok'] is True, rep)
    check('加标签：调用一次', calls['add'] == [([1, 2], ['复习::X'])], calls)
    check('加标签：回读命中', state[1] == ['复习::X'], state)
    check('加标签：留下备份', len(backups()) == 1, backups())


def test_tags_remove():
    state = {1: ['复习::X', '别的'], 2: ['复习::X']}

    def fake_map(ids, chunk=None):
        return {nid: {'noteId': nid, 'tags': list(state[nid])} for nid in ids}

    def fake_remove(ids, tags):
        for nid in ids:
            state[nid] = [t for t in state[nid] if t not in tags]

    reset_bd()
    with patched(notes_map=fake_map, add_tags=lambda *a: None, remove_tags=fake_remove):
        rep = quiet(WB.write_tags, [1, 2], remove=['复习::X'], commit=True,
                    label='tag', settle=0, backup_dir=BD)
    check('摘标签：ok', rep['ok'] is True, rep)
    check('摘标签：只摘目标', state[1] == ['别的'], state)
    check('摘标签：全清', state[2] == [], state)


def test_tags_verify_bad():
    state = {1: []}

    def fake_map(ids, chunk=None):
        return {nid: {'noteId': nid, 'tags': list(state[nid])} for nid in ids}

    reset_bd()
    with patched(notes_map=fake_map, add_tags=lambda *a: None,
                 remove_tags=lambda *a: None):
        rep = quiet(WB.write_tags, [1], add=['复习::X'], commit=True,
                    label='tag', settle=0, backup_dir=BD)
    check('标签没写上：ok=False', rep['ok'] is False, rep)
    check('标签没写上：给原因', '缺 复习::X' in rep['bad'].get(1, []), rep['bad'])


def test_chunked_fields():
    calls = {'parts': [], 'verify': []}

    def fake_values(ids, names=None, chunk=None):
        return {nid: {n: 'old' for n in (names or [])} for nid in ids}

    def fake_update(pairs):
        calls['parts'].append(len(pairs))
        return [(nid, True) for nid, _ in pairs]

    def fake_verify(want, settle=0.5, chunk=None):
        calls['verify'].append(chunk)
        return {}

    reset_bd()
    want = {i: {'AINote': 'v%d' % i} for i in range(1, 6)}
    with patched(note_values=fake_values, update_notes=fake_update,
                 verify_note_fields=fake_verify):
        rep = quiet(WB.write_fields, want, commit=True, label='t', settle=0,
                    chunk=2, backup_dir=BD)
    check('分块写：2/2/1', calls['parts'] == [2, 2, 1], calls['parts'])
    check('分块回读：chunk 透传', calls['verify'] == [2], calls['verify'])
    check('分块写：ok', rep['ok'] is True, rep)


def test_chunked_tags():
    state = {i: [] for i in range(1, 6)}
    sizes = []

    def fake_map(ids, chunk=None):
        return {nid: {'noteId': nid, 'tags': list(state[nid])} for nid in ids}

    def fake_add(ids, tags):
        sizes.append(len(ids))
        for nid in ids:
            state[nid].extend(tags)

    reset_bd()
    with patched(notes_map=fake_map, add_tags=fake_add, remove_tags=lambda *a: None):
        rep = quiet(WB.write_tags, list(state), add=['T'], commit=True, label='t',
                    settle=0, chunk=2, backup_dir=BD)
    check('分块打标：2/2/1', sizes == [2, 2, 1], sizes)
    check('分块打标：ok', rep['ok'] is True, rep)


def test_quiet():
    def fake_values(ids, names=None, chunk=None):
        return {nid: {n: 'old' for n in (names or [])} for nid in ids}

    reset_bd()
    buf = io.StringIO()
    with patched(note_values=fake_values, update_notes=lambda p: [],
                 verify_note_fields=lambda w, settle=0.5, chunk=None: {}):
        with contextlib.redirect_stdout(buf):
            WB.write_fields({1: {'AINote': 'x'}}, commit=False, quiet=True)
    check('quiet：内核不打印', buf.getvalue() == '', buf.getvalue())


def test_no_scheduling_calls():
    src = open(WB.__file__, encoding='utf-8').read()
    bad = [name for name in ('set_card_due', 'set_card_values', 'forget_cards',
                             'suspend(', 'unsuspend(')
           if ('.' + name) in src or ('AK.' + name) in src]
    check('内核不调用调度接口', not bad, bad)


def main():
    reset_bd()
    for fn in (test_dry_fields, test_commit_fields, test_commit_fields_verify_bad,
               test_commit_fields_update_fail, test_tags_add, test_tags_remove,
               test_tags_verify_bad, test_chunked_fields, test_chunked_tags,
               test_quiet, test_no_scheduling_calls):
        print(fn.__name__)
        fn()
        reset_bd()
    print()
    if FAIL:
        print('✗ %d 项失败：%s' % (len(FAIL), FAIL))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
