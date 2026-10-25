# -*- coding: utf-8 -*-
"""一次性文件区 ``temp/`` 的查看与清空（唯一入口）。

工作区约定（2026-10-20 起）：所有「做完就该消失」的东西 —— 临时脚本、排查 dump、
跑批日志、实验中间产出 —— **只放** ``<workspace>/temp/``，不许落在工作区别的地方。
一件事做完，一条命令收摊：

    python code/cli.py temp list            # 现在里面有什么（默认动作）
    python code/cli.py temp clean           # 真删（保留 README.md）
    python code/cli.py temp clean --dry-run # 只看将删什么，不动手
    python code/cli.py temp path            # 打印绝对路径

删除前一律先打印「将删 N 个文件 / X MB」的清单，数字不对就停
（docs/architecture.md §6.2）。``temp/README.md`` 是这块地界的说明书，永远保留。

为什么要有这个入口：以前一次性产物散在 ``.tmp/``、``data/tmp/``、``output/cmp*/``、
工作区根目录，收拾一次要逐个确认；现在只有一个地方，也只有一个删除动作。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

# 这块地界的说明书，任何清理动作都不许碰
KEEP = ('README.md',)


def _check_dir():
    """确认 TEMP 就是工作区下的 temp/，防手滑删错地方。"""
    real = os.path.realpath(WSP.TEMP)
    root = os.path.realpath(WSP.ROOT)
    if os.path.basename(real) != 'temp' or os.path.dirname(real) != root:
        print('❌ 拒绝执行：%s 不是 %s 下的 temp/'
              % (real, root))
        return False
    return True


def _entries():
    """返回 [(相对路径, 字节数)]，已排除要保留的 README.md。"""
    out = []
    if not os.path.isdir(WSP.TEMP):
        return out
    for root, _dirs, files in os.walk(WSP.TEMP):
        for name in files:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, WSP.TEMP).replace('\\', '/')
            if rel in KEEP:
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            out.append((rel, size))
    return sorted(out)


def _fmt(nbytes):
    if nbytes >= 1024 * 1024:
        return '%.1f MB' % (nbytes / 1048576.0)
    if nbytes >= 1024:
        return '%.0f KB' % (nbytes / 1024.0)
    return '%d B' % nbytes


def _top_level(entries):
    """按顶层条目汇总，免得刷出上千行。"""
    agg = {}
    for rel, size in entries:
        head = rel.split('/')[0]
        n, b = agg.get(head, (0, 0))
        agg[head] = (n + 1, b + size)
    return sorted(agg.items())


def _print_manifest(entries, verbose=False):
    total = sum(size for _rel, size in entries)
    print('temp/ = %s' % WSP.TEMP)
    if not entries:
        print('（现在是空的）')
        return total
    print('共 %d 个文件，%s' % (len(entries), _fmt(total)))
    print('-' * 72)
    if verbose:
        for rel, size in entries:
            print('  %10s  %s' % (_fmt(size), rel))
    else:
        for head, (n, size) in _top_level(entries):
            print('  %10s  %-40s %d 个文件' % (_fmt(size), head, n))
        print('（要看逐个文件加 --verbose）')
    return total


def cmd_list(a):
    entries = _entries()
    _print_manifest(entries, verbose=a.verbose)
    if entries:
        print()
        print('清空：python code/cli.py temp clean')
    return 0


def cmd_path(a):
    print(WSP.TEMP)
    return 0


def cmd_clean(a):
    if not _check_dir():
        return 2
    entries = _entries()
    total = _print_manifest(entries, verbose=a.verbose)
    if not entries:
        return 0
    if a.dry_run:
        print()
        print('演练结束：没有删任何东西。确认无误后去掉 --dry-run 再跑。')
        return 0
    removed = 0
    for head, _n in _top_level(entries):
        path = os.path.join(WSP.TEMP, head.replace('/', os.sep))
        if head in KEEP:
            continue
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            try:
                os.remove(path)
            except OSError as exc:                            # noqa: BLE001
                print('  ⚠ 删不掉：%s（%s）' % (head, exc))
                continue
        removed += 1
    left = _entries()
    print()
    print('已清空 temp/：删掉 %d 个顶层条目、%d 个文件、%s。'
          % (removed, len(entries), _fmt(total)))
    if left:
        print('⚠ 还剩 %d 个文件没删掉（可能被占用）：' % len(left))
        for rel, _size in left[:10]:
            print('  %s' % rel)
        return 1
    print('下次的一次性文件也放这里：%s' % WSP.TEMP)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='temp',
        description='一次性文件区 temp/：查看 / 打印路径 / 一键清空（保留 README.md）')
    ap.add_argument('action', nargs='?', default='list',
                    choices=('list', 'ls', 'path', 'clean'),
                    help='list（默认）| path | clean')
    ap.add_argument('--dry-run', action='store_true', help='clean 时只打印，不真删')
    ap.add_argument('--verbose', '-v', action='store_true', help='逐个文件列出')
    a = ap.parse_args(argv)

    if a.action in ('list', 'ls'):
        return cmd_list(a)
    if a.action == 'path':
        return cmd_path(a)
    return cmd_clean(a)


if __name__ == '__main__':
    sys.exit(main())
