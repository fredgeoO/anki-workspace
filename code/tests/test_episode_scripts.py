# -*- coding: utf-8 -*-
"""回归测试：episode 的编排脚本表（SCRIPTS）必须全部存在。

挡的是 2026-10-31 那类腐化：编排层写死一个路径，脚本被挪走/归档，
直到跑到最后一个阶段才 `❌ 找不到脚本`。现在启动时 `check_scripts()` 就会停。

纯离线：不连 Anki、不读 data/。
跑法：& $PY code\\tests\\test_episode_scripts.py
"""
import contextlib
import io
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
_EXEC = os.path.join(os.path.dirname(_HERE), 'execution')
for _p in (_EXEC, os.path.join(_EXEC, 'core6000'), os.path.join(_EXEC, 'lesson')):
    sys.path.insert(0, _p)
import textio  # noqa: E402  stdio 唯一入口
import episode  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def test_scripts():
    check('SCRIPTS 非空', bool(episode.SCRIPTS), episode.SCRIPTS)
    for name, path in sorted(episode.SCRIPTS.items()):
        check('%s 存在' % name, os.path.exists(path), path)
    check('无缺失脚本', episode.missing_scripts() == [], episode.missing_scripts())
    try:
        episode.check_scripts()
        ok = True
    except SystemExit as exc:
        ok = False
        print('    check_scripts 抛了：%s' % exc)
    check('check_scripts 不抛', ok)


def test_keys():
    want = {'pipeline', 'mine', 'mine_audio', 'ruby_engine'}
    check('脚本表键稳定', set(episode.SCRIPTS) == want, sorted(episode.SCRIPTS))


def test_rank_inprocess():
    captured = {}
    old = episode.FEX.cmd_field

    def fake(ns):
        captured.update(vars(ns))
        return 0

    episode.FEX.cmd_field = fake
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rep = {}
            status = episode.stage_rank(types.SimpleNamespace(commit=False), rep)
    finally:
        episode.FEX.cmd_field = old
    check('rank 演练 → dry', status == 'dry', status)
    check('rank 走 --all-notes', captured.get('all_notes') is True, captured)
    check('rank plan 正确', captured.get('plan') == episode.JITEN_PLAN, captured)
    check('rank 字段名正确', captured.get('field') == 'JitenAnimeRank', captured)


def main():
    for fn in (test_scripts, test_keys, test_rank_inprocess):
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
