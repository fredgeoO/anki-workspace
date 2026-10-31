# -*- coding: utf-8 -*-
"""回归测试：episode.stage_retag 走 writeback（不再外挂 oneshot 脚本）。

挡四件事：
1. 编排层再引用一个不存在的脚本（2026-10-31 实测：retag_notes.py 只在 archive/）。
2. 演练模式误写库。
3. 提交后只检查旧标签消失、不检查新标签是否写上（半成品标签也报成功）。
4. 没有 input_tag / 已改过时不该碰库。

纯离线：AK.find_notes 与 WB.write_tags 用假函数替换，不连 Anki。
跑法：& $PY code\\tests\\test_episode_retag.py
"""
import contextlib
import io
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'execution'))
import textio  # noqa: E402  stdio 唯一入口
import episode  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def run_stage(input_tag='待标记', tag='动画::X', commit=False, ids=(11, 12), wb_ok=True):
    """跑一次 stage_retag，返回 (status, rep, 调用记录)。AK/WB 全假。"""
    calls = {'write': []}

    def fake_find(query):
        if query == 'tag:%s' % input_tag:
            return list(ids)
        return []

    def fake_write(nids, add=(), remove=(), commit=False, label=''):
        calls['write'].append({'ids': list(nids), 'add': list(add),
                               'remove': list(remove), 'commit': commit,
                               'label': label})
        return {'ok': wb_ok, 'count': len(nids), 'backup': '/tmp/backup.json',
                'bad': ({} if wb_ok else {list(nids)[0]: ['缺 %s' % tag]})}

    old_find, old_write = episode.AK.find_notes, episode.WB.write_tags
    episode.AK.find_notes, episode.WB.write_tags = fake_find, fake_write
    try:
        a = types.SimpleNamespace(input_tag=input_tag, tag=tag, commit=commit)
        rep = {}
        with contextlib.redirect_stdout(io.StringIO()):
            status = episode.stage_retag(a, rep)
    finally:
        episode.AK.find_notes, episode.WB.write_tags = old_find, old_write
    return status, rep, calls


def test_skip():
    status, _rep, calls = run_stage(input_tag=None)
    check('没有 input_tag → skipped', status == 'skipped', status)
    status, _rep, _calls = run_stage(input_tag='动画::X', tag='动画::X')
    check('与 tag 相同 → skipped', status == 'skipped', status)
    status, _rep, _calls = run_stage(ids=())
    check('查不到卡 → skipped', status == 'skipped', status)
    check('跳过时不写库', calls['write'] == [], calls['write'])


def test_dry_run():
    status, rep, calls = run_stage(commit=False)
    check('演练返回 dry', status == 'dry', status)
    check('演练不调用 write_tags', calls['write'] == [], calls['write'])
    check('演练报告含将改张数', rep.get('retag', {}).get('count') == 2, rep)


def test_commit_ok():
    status, rep, calls = run_stage(commit=True)
    check('提交成功 → done', status == 'done', status)
    check('一次写入、参数正确',
          calls['write'] == [{'ids': [11, 12], 'add': ['动画::X'],
                              'remove': ['待标记'], 'commit': True,
                              'label': 'retag'}], calls['write'])
    check('报告 committed=True', rep.get('retag', {}).get('committed') is True, rep)
    check('报告记下备份路径', rep.get('retag', {}).get('backup') == '/tmp/backup.json', rep)


def test_commit_fail():
    status, rep, _calls = run_stage(commit=True, wb_ok=False)
    check('回读失败 → failed', status == 'failed', status)
    check('报告 committed=False', rep.get('retag', {}).get('committed') is False, rep)


def test_no_external_script():
    src = open(episode.__file__, encoding='utf-8').read()
    check('不再引用 retag_notes.py', 'retag_notes.py' not in src)


def main():
    for fn in (test_skip, test_dry_run, test_commit_ok, test_commit_fail,
               test_no_external_script):
        print(fn.__name__)
        fn()
    print()
    if FAIL:
        print('✗ %d 项失败：%s' % (len(FAIL), FAIL))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
