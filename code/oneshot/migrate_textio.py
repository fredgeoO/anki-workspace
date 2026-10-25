# -*- coding: utf-8 -*-
"""把「手工编码补丁」一次性换成 ``import textio``（幂等，默认演练）。

2026-10-08 之前，stdio 的 UTF-8 接管在各脚本里被手写了 20+ 遍，写法有四种：

    sys.stdout.reconfigure(encoding='utf-8')                       # 最常见
    if hasattr(sys.stdout, 'reconfigure'):                         # 带护栏的
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    try:                                                           # 套 try 的
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

本脚本把这四种统一改成一行 ``import textio``（唯一实现在 ``code/common/textio.py``，
import 即接管），并给**所有入口脚本**（有 ``if __name__``）补上那一行 —— 没有
``code/common`` 在 sys.path 上的文件会顺带补一个最小的路径引导。

用法::

    & $PY code\\oneshot\\migrate_textio.py             # 演练：只打印将要改什么
    & $PY code\\oneshot\\migrate_textio.py --commit    # 真改（改完自动 py_compile 复核）
    & $PY code\\common\\textio.py audit                # 复核：R1/R2 必须为 0

**不碰**的写法（需要人判断，脚本会列出来）：
``PYTHONIOENCODING='utf-8'``（可能只是文档示例）、以及 reconfigure 混在别的语句里
的块。
"""
from __future__ import annotations

import argparse
import ast
import os
import py_compile
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio as T  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

ROOTS = ('code', os.path.join('.dsh', 'skills'), 'core6000-analysis')
SKIP_DIRS = {'__pycache__', 'pylibs', 'archive', 'node_modules', '.git', '.tmp', 'temp',
             'data', 'output', 'subtitles'}
COMMON = os.path.join(_ROOT, 'code', 'common')

IMPORT_LINE = 'import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）'

HACK_LINE = re.compile(r'^\s*(?:sys\.(?:stdout|stderr)\.reconfigure\('
                       r'|sys\.(?:stdout|stderr)\s*=\s*io\.TextIOWrapper\()')
GUARD_LINE = re.compile(r'^\s*if\s+hasattr\(\s*sys\.(?:stdout|stderr)\s*,\s*[\'"]reconfigure[\'"]')
TRY_LINE = re.compile(r'^\s*try\s*:\s*(#.*)?$')
EXCEPT_LINE = re.compile(r'^\s*except\b[^:]*:\s*(#.*)?$')
#: 这些 import 说明 ``code/common`` 已经在 sys.path 上了（``import textio`` 可以紧跟其后）
COMMON_IMPORT = re.compile(
    r'^\s*(?:import|from)\s+(?:paths|anki_api|_deps|jp_decks|check_cards|check_mine|'
    r'check_ruby|local_llm|textio)\b')
PATH_INSERT = re.compile(r'^\s*sys\.path\.(?:insert|append)\(')
HAS_MAIN = re.compile(r'^if\s+__name__\s*==', re.M)
HAS_TEXTIO = re.compile(r'^\s*(?:import\s+textio\b|from\s+textio\s+import)', re.M)
TOP_IMPORT = re.compile(r'^(?:import|from)\s+\S')


def indent_of(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def block_end(lines, start: int) -> int:
    """从 ``lines[start]``（一个带缩进的块头）起，返回块最后一行的下标（含）。"""
    head_indent = len(indent_of(lines[start]))
    i = start + 1
    last = start
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if len(indent_of(line)) <= head_indent:
            break
        last = i
        i += 1
    return last


def _only_hacks(lines, start: int, end: int) -> bool:
    for line in lines[start:end + 1]:
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        if HACK_LINE.match(line):
            continue
        return False
    return True


def find_hacks(lines):
    """-> [(start, end, kind)]，kind ∈ {'line', 'guard', 'try'}。"""
    out = []
    i = 0
    while i < len(lines):
        if not HACK_LINE.match(lines[i]):
            i += 1
            continue
        start = i
        while i + 1 < len(lines) and HACK_LINE.match(lines[i + 1]):
            i += 1
        end = i
        prev = start - 1
        while prev >= 0 and (not lines[prev].strip() or lines[prev].strip().startswith('#')):
            prev -= 1
        if prev >= 0 and GUARD_LINE.match(lines[prev]):
            bend = block_end(lines, prev)
            if _only_hacks(lines, prev + 1, bend):
                out.append((prev, bend, 'guard'))
                i = bend + 1
                continue
        if prev >= 0 and TRY_LINE.match(lines[prev]):
            bend = block_end(lines, prev)
            body = [ln for ln in lines[prev + 1:bend + 1] if ln.strip()]
            if all(HACK_LINE.match(ln) for ln in body) and bend + 1 < len(lines) \
                    and EXCEPT_LINE.match(lines[bend + 1]):
                eend = block_end(lines, bend + 1)
                ebody = [ln.strip() for ln in lines[bend + 2:eend + 1] if ln.strip()]
                if ebody in ([], ['pass']):
                    out.append((prev, eend, 'try'))
                    i = eend + 1
                    continue
        out.append((start, end, 'line'))
        i = end + 1
    return out


def anchor_after(lines):
    """``import textio`` 该插在哪一行之后（返回值是下标）。找不到返回 None。

    只看**顶格**的 import / sys.path 行：函数体里那份 ``import local_llm``
    （skill 副本的动态加载）不能当锚点，否则会把顶格的 import 塞进函数体。
    """
    idx = None
    for i, line in enumerate(lines):
        if not line[:1].strip():                # 有缩进 → 不算
            continue
        if COMMON_IMPORT.match(line) or (PATH_INSERT.match(line) and 'common' in line):
            idx = i
    if idx is not None:
        return idx + 1
    return None


def top_import_end(lines):
    """顶部 import 块之后的下标（用 ast 定位，不猜）；语法坏了返回 None。"""
    try:
        tree = ast.parse(''.join(lines))
    except SyntaxError:
        return None
    ends = [n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    if ends:
        return max(ends)
    if tree.body and isinstance(tree.body[0], ast.Expr) \
            and isinstance(tree.body[0].value, ast.Constant) \
            and isinstance(tree.body[0].value.value, str):
        return tree.body[0].end_lineno
    head = 0                                   # 别插到 shebang / 编码声明之前
    while head < len(lines) and (not lines[head].strip()
                                 or lines[head].lstrip().startswith('#')):
        head += 1
    return head


def imported_roots(lines):
    """顶层 import 的根模块名（判断 os / sys 有没有现成的）。

    只看 ``tree.body``：函数体里的 ``import sys`` 不算 —— 曾经因为这个用
    ``ast.walk`` 把 ``srt.py`` 的路径引导内联进去却没有顶层 ``import sys``。
    """
    try:
        tree = ast.parse(''.join(lines))
    except SyntaxError:
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split('.')[0])
    return names


def bootstrap_lines(path):
    rel = os.path.relpath(COMMON, os.path.dirname(os.path.abspath(path)))
    parts = [p for p in re.split(r'[\\/]+', rel) if p not in ('', '.')]
    quoted = ', '.join("'%s'" % p for p in parts)
    return [
        '_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))\n',
        "sys.path.insert(0, os.path.join(_TEXTIO_HERE, %s))\n" % quoted,
    ]


def plan_file(path: str):
    """-> (new_lines, notes)；new_lines 为 None 表示无需改/不能自动改。"""
    src = T.read_text(path, warn=False)
    lines = src.splitlines(keepends=True)
    notes = []
    if os.path.abspath(path) == os.path.abspath(__file__):
        return None, ['自己']
    hacks = find_hacks(lines)
    is_main = T.needs_textio(src)         # 入口脚本，或在模块层直接就 print 的脚本
    has_import = bool(HAS_TEXTIO.search(src))
    if not hacks and not is_main:
        return None, []
    if not hacks and has_import:
        return None, []

    new = list(lines)
    if hacks:
        for start, end, kind in reversed(hacks):
            del new[start:end + 1]              # 先只删：插在哪由 anchor 决定
            notes.append('删手工补丁（%s）' % kind)
    if not HAS_TEXTIO.search(''.join(new)):
        at = anchor_after(new)
        if at is None and os.path.dirname(os.path.abspath(path)) == COMMON:
            at = top_import_end(new)            # code/common 自己人：sys.path[0] 已含本目录
            if at is None:
                return None, ['找不到插入点']
            new[at:at] = [IMPORT_LINE + '\n']
            notes.append('在顶部 import 之后插入')
        elif at is None:
            at = top_import_end(new)
            if at is None:
                return None, ['找不到插入点（没有 import 块 / 语法坏了）']
            have = imported_roots(new)
            need = [m + '\n' for m in ('import os', 'import sys')
                    if m.split()[1] not in have]
            new[at:at] = need + bootstrap_lines(path) + [IMPORT_LINE + '\n']
            notes.append('补路径引导%s' % (' + ' + ', '.join(need) if need else ''))
        else:
            new[at:at] = [IMPORT_LINE + '\n']
            notes.append('在 common import 之后插入')
    if ''.join(new) == src:
        return None, []
    try:                                        # 语法闸门：改坏就不落盘
        ast.parse(''.join(new))
    except SyntaxError as exc:
        return None, ['改动后语法不过（%s），跳过' % exc.msg]
    return new, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='migrate_textio.py',
                                 description='把手工编码补丁换成 import textio（默认演练）')
    ap.add_argument('--commit', action='store_true', help='真改（默认只打印）')
    ap.add_argument('--root', default=_ROOT)
    ap.add_argument('--paths', nargs='*', default=list(ROOTS))
    ap.add_argument('--only', nargs='*', help='只处理文件名里含这些串的文件')
    args = ap.parse_args(argv)

    changed, manual, skipped = [], [], 0
    for base in args.paths:
        for dirpath, dirnames, filenames in os.walk(os.path.join(args.root, base)):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if not fn.endswith('.py'):
                    continue
                path = os.path.join(dirpath, fn)
                if args.only and not any(o in path for o in args.only):
                    continue
                rel = os.path.relpath(path, args.root).replace('\\', '/')
                new, notes = plan_file(path)
                if new is None:
                    if notes:
                        manual.append((rel, '；'.join(notes)))
                    else:
                        skipped += 1
                    continue
                changed.append(rel)
                if args.commit:
                    T.write_text(path, ''.join(new))
                    print('改  %-58s %s' % (rel, '；'.join(notes)))
                else:
                    print('将改 %-56s %s' % (rel, '；'.join(notes)))

    print()
    print('%s：%d 个文件%s' % ('已改' if args.commit else '将改', len(changed),
                             '' if args.commit else '（演练，未落盘）'))
    if manual:
        print('需要人工看：%d' % len(manual))
        for rel, why in manual[:20]:
            print('   %-56s %s' % (rel, why))
    if not args.commit:
        print('复核：& $PY code\\common\\textio.py audit --strict')
        return 0

    bad = []
    for rel in changed:
        try:
            py_compile.compile(os.path.join(args.root, rel), doraise=True)
        except py_compile.PyCompileError as exc:
            bad.append((rel, str(exc).splitlines()[0]))
    print('py_compile：%d/%d 通过%s' % (len(changed) - len(bad), len(changed),
                                      '' if not bad else '，失败：'))
    for rel, err in bad:
        print('   %s  %s' % (rel, err))
    print('复核：& $PY code\\common\\textio.py audit --strict')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
