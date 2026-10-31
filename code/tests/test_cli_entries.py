# -*- coding: utf-8 -*-
"""回归测试：cli 入口表（GROUPS / VOCAB / WEAK）里的脚本必须都存在。

`cli.py list` 一直会标 ❌，但退出码是 0；2026-11-01 加了 `list --check`
（缺失则退出 1），这里把它钉住。

纯离线：只查路径与返回值，不跑被调脚本。
跑法：& $PY code\\tests\\test_cli_entries.py
"""
import contextlib
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))              # code/（cli.py）
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio  # noqa: E402  stdio 唯一入口
import cli  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def entries():
    rows = list(cli.GROUPS.items())
    rows += [('vocab:' + k, v) for k, v in cli.VOCAB.items()]
    rows += [('weak:' + k, v) for k, v in cli.WEAK.items()]
    for k, v in cli.WEAK_CHAIN.items():
        rows += [('weak:' + k, s) for s in v]
    return rows


def test_entries():
    missing = [name for name, path in entries() if not os.path.exists(path)]
    check('入口脚本都存在', not missing, missing)
    check('list --check 返回 0', quiet(cli.cmd_list, check=True) == 0, '')


def test_list_output():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(['list'])
    text = buf.getvalue()
    check('list 返回 0', rc == 0, rc)
    check('list 打印 ok 标记', 'ok ' in text, text[:120])
    check('list 含全部组', 'weak:today' in text and 'vocab:cover' in text, '')


def test_unknown():
    check('未知入口返回 2', quiet(cli.main, ['no-such-group']) == 2, '')
    check('空参数返回 0（打印帮助）', quiet(cli.main, []) == 0, '')


def test_resolve():
    e, rest = cli.resolve(['episode', '--tag', 'X'])
    check('顶层组 → script', e and e[0] == 'script' and e[1].endswith('episode.py')
          and rest == ['--tag', 'X'], (e, rest))
    e, rest = cli.resolve(['vocab', 'cover', 'a.srt'])
    check('vocab 子命令 → script', e and e[0] == 'script'
          and e[1].endswith('cover_cli.py') and rest == ['a.srt'], (e, rest))
    e, rest = cli.resolve(['vocab', 'reorder-jiten', '--commit'])
    check('reorder-jiten → preset', e and e[0] == 'preset' and rest == ['--commit'],
          (e, rest))
    e, rest = cli.resolve(['jiten'])
    check('jiten 别名 → preset', e and e[0] == 'preset', e)
    e, rest = cli.resolve(['weak', 'build-list'])
    check('build-list → chain', e and e[0] == 'chain' and len(e[1]) == 2, e)
    e, rest = cli.resolve(['vocab'])
    check('vocab 无子命令 → group', e == ('group', 'vocab'), e)
    e, rest = cli.resolve(['nope'])
    check('未知 → None', e is None, e)


def main():
    for fn in (test_entries, test_list_output, test_unknown, test_resolve):
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
