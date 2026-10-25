# -*- coding: utf-8 -*-
r"""开工体检（doctor）—— 所有动手前的强制门禁。**只读，不改任何东西。**

把三件已有的自审 + 三项这里独有的检查收成一个入口，失败项一次列全::

    python code/cli.py doctor                        # Anki 开着时的全套
    python code/cli.py doctor --skip-anki            # 离线（跳过需要 Anki 的检查）
    python code/cli.py doctor --tag "动画::<作品名>::<季>::第NN集"
    python code/cli.py doctor --quiet                # 更省：只打 fail / warn 标题 + 结论
    python code/cli.py doctor --all                  # 展开全部明细（含第二期待办清单）

默认**只打印有 fail / warn 的节**，全绿时只剩小结与结论；--all 恢复全部明细。

检查来源（**不重复实现已有逻辑**，这是本脚本的设计原则）::

  1. AnkiConnect 健康          → anki_api.py check（--skip-anki 跳过）
  2. Anki 访问点自审           → anki_api.py audit（阻塞项必须为 0；第二期待办是已知例外，只报告）
  3. 编码 / stdio 自审         → textio.py audit --strict（R1-R5 全卡）
  4. 废弃符号残留（doctor 独有）→ 活跃区不许再出现 retire 掉的入口名
                                 （明确标注「已归档/已废弃」的指引行除外；
                                  docs/reports、docs/plans 是史料，不扫）
  5. 快照卫生（doctor 独有）    → data/snapshots 是否有 manifest、是否有 probe 临时目录、
                                 离线快照是否比 live 收藏库旧太多
  6. 文档状态行（doctor 独有）  → docs/**/*.md 头部必须有「状态：」行（reports 除外）
  7. 每集 preflight（并入）     → .dsh/skills/jp-anki-pipeline/scripts/preflight.py

退出码：``0`` = 全绿；``1`` = 有 fail（**必须先修**）；``2`` = 只有 warn（可以继续干活）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))   # paths / textio
import paths as WSP  # noqa: E402  工作区路径的唯一来源
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

ANKI_API = os.path.join(WSP.COMMON, 'anki_api.py')
TEXTIO = os.path.join(WSP.COMMON, 'textio.py')
PREFLIGHT = os.path.join(WSP.ROOT, '.dsh', 'skills', 'jp-anki-pipeline',
                         'scripts', 'preflight.py')
SNAP_MANIFEST = os.path.join(WSP.SNAPSHOTS, 'README.json')
PYLIBS_LOCK = os.path.join(WSP.DATA, 'pylibs.lock.json')

# 活跃区 = 经常跑的链路 + 技能/文档；archive / oneshot / data/evidence 是历史，不在扫描范围
DEPRECATED_PATTERNS = (
    (r'(?<![A-Za-z0-9_])POOL_TAG\b',
     '准入标签常量又出现了（2026-10-06 退场，2026-10-10 已从代码摘除）'),
    (r'gen_i1_prompt',
     'i+1 生成器已归档（archive/experiments/gen_i1_prompt/）'),
    (r'regress_pipeline',
     'regress 脚本已归档（311 条基线不可复现）'),
)
DEPRECATED_SCAN = (
    os.path.join(WSP.CODE, 'execution'),
    os.path.join(WSP.CODE, 'analysis'),
    os.path.join(WSP.CODE, 'tools'),
    os.path.join(WSP.ROOT, '.dsh', 'skills'),
)
DEPRECATED_EXCLUDE = ('__pycache__', 'oneshot', 'anki_analyze')
SKIP_WALK = {'__pycache__', '.git', 'node_modules', '.venv', 'archive',
             'pylibs', 'textio_migration_backup'}
# 只扫「给当前指令」的文件：docs/reports（日期化报告）与 docs/plans（历史立项记录）
# 里提到旧入口是史料，不算残留。允许**明确标注已归档**的指引行（见 _is_archived_note）。
DOC_SCAN_EXCLUDE = ('deprecated', 'reports', 'plans')
_ARCHIVED_NOTE = re.compile(r'archive/|docs/deprecated|已归档|归档于|已废弃|退场')


class Report:
    def __init__(self):
        self.fails = []     # (标题, 明细行)
        self.warns = []
        self.oks = []

    def fail(self, title, lines=()):
        self.fails.append((title, list(lines)))

    def warn(self, title, lines=()):
        self.warns.append((title, list(lines)))

    def ok(self, title):
        self.oks.append(title)


def _rel(p):
    try:
        return os.path.relpath(p, WSP.ROOT).replace('\\', '/')
    except ValueError:
        return p


def _run_py(script, args, timeout=300):
    """跑一个 Python 脚本并抓输出（这里是短输出，抓起来便于汇总）。"""
    cmd = [sys.executable, script] + [str(x) for x in args]
    try:
        proc = textio.run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, '(超时 %ss)' % timeout
    out = (proc.stdout or '') + (proc.stderr or '')
    return proc.returncode, out.rstrip()


def _show(report, out, limit=200, all_of_it=False):
    lines = out.splitlines()
    if not all_of_it and len(lines) > limit:
        lines = lines[:limit] + ['…（还有 %d 行，用 --all 展开）' % (len(lines) - limit)]
    for ln in lines:
        print('      %s' % ln)


# ── 1. AnkiConnect ─────────────────────────────────────────────────────────
def check_anki(report, skip, show_all):
    if skip:
        if show_all:
            print('[1] AnkiConnect 健康检查')
            print('      （--skip-anki：跳过）')
        return
    rc, out = _run_py(ANKI_API, ['check'], timeout=60)
    if rc == 0:
        report.ok('AnkiConnect 可达')
    else:
        report.fail('AnkiConnect 连不上',
                    ['阶段 1-5 全走 AnkiConnect；先打开 Anki（或加 --skip-anki 做离线检查）'])
    if rc != 0 or show_all:
        print('[1] AnkiConnect 健康检查')
        _show(report, out, all_of_it=True)


# ── 2. Anki 访问点自审 ─────────────────────────────────────────────────────
def check_anki_audit(report, show_all):
    rc, out = _run_py(ANKI_API, ['audit'] + (['--all'] if show_all else []), timeout=120)
    # pending（第二期待办：analysis / oneshot）是**已知例外**，这里不卡
    n_pending = 0
    for ln in out.splitlines():
        m = re.search(r'第二期待办.*?：(\d+)', ln)
        if m:
            n_pending = int(m.group(1))
    if rc == 0:
        report.ok('Anki 访问点自审通过')
    else:
        report.fail('Anki 访问点自审有阻塞项', ['看上面的 ✗ / ? 行；新增 Anki 访问必须走 anki_api.py'])
    if n_pending:
        report.warn('有 %d 个文件仍在直接访问 Anki（第二期待办，已知例外）' % n_pending,
                    ['明细：python code/common/anki_api.py audit --all'])
    if rc != 0 or n_pending or show_all:
        print('[2] Anki 访问点自审（anki_api.py audit）')
        _show(report, out, all_of_it=show_all)


# ── 3. 编码 / stdio 自审 ───────────────────────────────────────────────────
def check_textio_audit(report, show_all):
    rc, out = _run_py(TEXTIO, ['audit', '--strict'] + (['--all'] if show_all else []),
                      timeout=120)
    if rc == 0:
        report.ok('textio 自审（--strict）通过')
    else:
        report.fail('textio 自审有命中（R1-R5）',
                    ['R1/R2 必须为 0；--strict 下 R3/R4/R5 也要清零'])
    if rc != 0 or show_all:
        print('[3] 编码 / stdio 自审（textio.py audit --strict）')
        _show(report, out, all_of_it=show_all)


# ── 4. 废弃符号残留 ───────────────────────────────────────────────────────
def _iter_scan_files():
    """给当前指令的文件：活跃代码 + 技能 + README + docs 顶层（跳过 reports/plans/deprecated）。"""
    self_path = os.path.abspath(__file__)
    for base in DEPRECATED_SCAN:
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_WALK and d not in DEPRECATED_EXCLUDE]
            for fn in filenames:
                if fn.endswith(('.py', '.md', '.ps1')):
                    yield os.path.join(dirpath, fn)
    extra = os.path.join(WSP.ROOT, 'README.md')
    if os.path.isfile(extra):
        yield extra
    for path in glob.glob(os.path.join(WSP.DOCS, '**', '*.md'), recursive=True):
        rel = os.path.relpath(path, WSP.DOCS).replace('\\', '/')
        parts = rel.split('/')
        if any(p in DOC_SCAN_EXCLUDE for p in parts[:-1]):
            continue
        if rel == 'deprecated.md':      # 废弃档案本体：它按定义要点名退场的东西
            continue
        yield path


def check_deprecated(report, show_all):
    self_path = os.path.abspath(__file__)
    hits = {}
    for path in _iter_scan_files():
        if os.path.abspath(path) == self_path:      # 本脚本自带这些模式，跳过自己
            continue
        try:
            src = textio.read_text(path, warn=False)
        except OSError:
            continue
        lines = src.splitlines()
        for pat, why in DEPRECATED_PATTERNS:
            for m in re.finditer(pat, src):
                ln = src.count('\n', 0, m.start()) + 1
                text = lines[ln - 1] if 0 < ln <= len(lines) else ''
                if _ARCHIVED_NOTE.search(text):
                    continue        # 明确标注「已归档/已废弃」的指引行是有意保留的
                hits.setdefault(_rel(path), []).append((ln, m.group(0), why))
    if not hits:
        report.ok('废弃符号残留为 0')
        if show_all:
            print('[4] 废弃符号残留（活跃区不该再出现）')
            print('      ✓ 0 处')
        return
    lines = []
    for rel in sorted(hits):
        for ln, what, why in hits[rel]:
            lines.append('%s:%d  %s  ← %s' % (rel, ln, what, why))
    print('[4] 废弃符号残留（活跃区不该再出现）')
    for ln in lines:
        print('      ✗ %s' % ln)
    report.fail('废弃符号残留 %d 处' % len(lines), lines)


# ── 5. 快照卫生 ───────────────────────────────────────────────────────────
def _age_days(path):
    try:
        return (time.time() - os.path.getmtime(path)) / 86400.0
    except OSError:
        return None


def check_snapshots(report, show_all):
    if not os.path.isdir(WSP.SNAPSHOTS):
        report.warn('data/snapshots 不存在', [])
        return
    n0 = len(report.fails) + len(report.warns)
    info = []
    dirs = sorted(d for d in os.listdir(WSP.SNAPSHOTS)
                  if os.path.isdir(os.path.join(WSP.SNAPSHOTS, d)))
    info.append('目录 %d 个' % len(dirs))

    # 5a. manifest 覆盖
    registered = set()
    if os.path.isfile(SNAP_MANIFEST):
        try:
            man = json.load(open(SNAP_MANIFEST, encoding='utf-8'))
            for item in (man.get('snapshots') or []):
                registered.add(item.get('name'))
        except Exception as exc:                              # noqa: BLE001
            report.warn('data/snapshots/README.json 读不了', [str(exc)])
    else:
        report.warn('还没有 data/snapshots/README.json（快照清单）',
                    ['每个快照应有 purpose / created / consumers / 何时可删'])
    if registered:
        missing = [d for d in dirs if d not in registered]
        if missing:
            report.warn('%d 个快照目录没登记在 README.json' % len(missing),
                        ['、'.join(missing)])
        else:
            report.ok('快照目录都已登记')
    elif dirs:
        report.warn('%d 个快照目录都没有清单（README.json 缺失或为空）' % len(dirs))

    # 5b. 疑似临时探测目录
    probe = [d for d in dirs if re.search(r'(probe-|probe_|^live-|^live_probe)', d)]
    if probe:
        report.warn('疑似临时探测目录 %d 个（确认后可删）' % len(probe), ['、'.join(probe)])

    # 5c. 离线快照 vs live 收藏库
    live = WSP.LIVE_COLLECTION
    live_age = _age_days(live)
    if live_age is None:
        info.append('（找不到 live 收藏库 %s：跳过新鲜度对比）' % _rel(live))
    else:
        for label, snap in (('_anki_snap/collection.anki2', WSP.SNAP_ANKI_SNAP),
                            ('anki_snapshot.db', WSP.SNAP_ANKI_SNAPSHOT_DB)):
            age = _age_days(snap)
            if age is None:
                continue
            if live_age < age - 1:
                report.warn('离线快照 %s 比 live 收藏库旧 %.1f 天' % (label, age - live_age),
                            ['离线分析（--source snapshot / weak build-list）会看到旧数据'])
            else:
                info.append('%s：与 live 差距 %.1f 天（可接受）' % (label, age - live_age))

    if show_all or (len(report.fails) + len(report.warns)) > n0:
        print('[5] 快照卫生（data/snapshots）')
        for ln in info:
            print('      %s' % ln)


# ── 6. 文档状态行 ─────────────────────────────────────────────────────────
def check_doc_status(report, show_all):
    missing = []
    checked = 0
    for path in sorted(glob.glob(os.path.join(WSP.DOCS, '**', '*.md'), recursive=True)):
        # docs/reports 是日期化产物（日期在文件名/正文里），不要求状态行
        rel = os.path.relpath(path, WSP.DOCS).replace('\\', '/')
        if rel.startswith('reports/'):
            continue
        checked += 1
        try:
            head = textio.read_text(path, warn=False).splitlines()[:12]
        except OSError:
            continue
        if not any(re.search(r'状态[:：]', ln) for ln in head):
            missing.append(_rel(path))
    root_readme = os.path.join(WSP.ROOT, 'README.md')
    if os.path.isfile(root_readme):
        checked += 1
        try:
            head = textio.read_text(root_readme, warn=False).splitlines()[:12]
            if not any(re.search(r'状态[:：]', ln) for ln in head):
                missing.append('README.md')
        except OSError:
            pass
    if missing:
        report.warn('%d 份文档缺「状态：active/deprecated ｜ 最后核实：YYYY-MM-DD」'
                    % len(missing), missing)
    else:
        report.ok('文档状态行齐全')
    if missing or show_all:
        print('[6] 文档状态行（docs/**/*.md 头部应有「状态：」）')
        print('      检查 %d 份' % checked)
        for rel in missing:
            print('      · %s' % rel)


# ── 7. 技能 preflight（并入）─────────────────────────────────────────────
def check_preflight(report, tag, skip_anki, show_all):
    if not os.path.isfile(PREFLIGHT):
        report.warn('找不到 preflight.py', [_rel(PREFLIGHT)])
        return
    args = []
    if tag:
        args += ['--tag', tag]
    if skip_anki:
        args += ['--offline']
    rc, out = _run_py(PREFLIGHT, args, timeout=180)
    # 只收问题行（[!]/[WARN]/[X]）；不整段 dump preflight 输出，
    # 也不传 --list-tags —— 动画:: 标签全表太长，默认掠过。
    bad = [ln.strip() for ln in out.splitlines()
           if '[!]' in ln or '[WARN]' in ln or '[X]' in ln]
    if rc != 0:
        report.fail('preflight 未通过（AnkiConnect 不可用）', bad)
    elif bad:
        report.warn('preflight 有 %d 条提示' % len(bad), bad)
    else:
        report.ok('preflight 无提示')
    if rc != 0 or bad:
        print('[7] 每集 preflight（jp-anki-pipeline/scripts/preflight.py）')
        for ln in bad:
            print('      %s' % ln)
    elif show_all:
        print('[7] 每集 preflight（jp-anki-pipeline/scripts/preflight.py）')
        _show(report, out, all_of_it=True)


# ── 8. 环境 / 依赖 ────────────────────────────────────────────────────────
def check_env(report, show_all):
    info = []
    py = sys.version.split()[0]
    info.append('Python %s' % py)
    pylibs = os.path.join(WSP.DATA, 'pylibs')
    if os.path.isdir(pylibs):
        n = len(os.listdir(pylibs))
        info.append('data/pylibs：%d 个条目' % n)
    else:
        report.warn('data/pylibs 不存在', ['装库：code/oneshot/install_workspace_wheels.py'])
    if os.path.isfile(PYLIBS_LOCK):
        try:
            lock = json.load(open(PYLIBS_LOCK, encoding='utf-8'))
            pkgs = lock.get('packages') or lock
            info.append('pylibs.lock：%d 个包' % (len(pkgs) if hasattr(pkgs, '__len__') else 0))
        except Exception as exc:                              # noqa: BLE001
            report.warn('data/pylibs.lock.json 读不了', [str(exc)])
    else:
        report.warn('还没有 data/pylibs.lock.json（依赖版本未锁定）',
                    ['重跑 code/oneshot/install_workspace_wheels.py 会生成'])
    report.ok('环境检查完成')
    if show_all:
        print('[8] 环境与依赖')
        for ln in info:
            print('      %s' % ln)


# ── 9. 工作区卫生 ─────────────────────────────────────────────────────────
# 根目录只允许这些条目：一次性文件不许散在工作区里（2026-10-20 立）。
ROOT_ALLOWED = {'README.md', 'AGENTS.md', 'code', 'data', 'docs', 'output', 'subtitles',
                'archive', 'core6000-analysis', 'temp', '.dsh', '.git',
                '.gitignore', '.gitattributes'}


def check_hygiene(report, show_all):
    stray = sorted(n for n in os.listdir(WSP.ROOT) if n not in ROOT_ALLOWED)
    if stray:
        report.warn('根目录有 %d 个计划外条目' % len(stray),
                    ['、'.join(stray),
                     '一次性文件放 temp/（python code/cli.py temp clean），'
                     '成品放 output/ 或 docs/，代码放 code/'])
    else:
        report.ok('根目录干净')

    if not os.path.isdir(WSP.TEMP):
        report.warn('temp/ 不存在', ['建一个空目录 + README.md；code/cli.py temp 不会自己建'])
        return
    n = 0
    size = 0
    for root, _dirs, files in os.walk(WSP.TEMP):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), WSP.TEMP)
            if rel == 'README.md':
                continue
            n += 1
            try:
                size += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    if n:
        report.warn('temp/ 里还有 %d 个一次性文件（%.1f MB）' % (n, size / 1048576.0),
                    ['清空：python code/cli.py temp clean（先看：temp list）'])
    else:
        report.ok('temp/ 是空的')

    if show_all:
        print('[9] 工作区卫生（根目录白名单 + temp/ 待清量）')
        if not stray:
            print('      根目录：只有白名单条目')
        if n == 0:
            print('      temp/：空的')


def main():
    ap = argparse.ArgumentParser(
        prog='doctor',
        description='开工体检（只读）：三件自审 + 废弃符号 + 快照卫生 + 文档状态行 + preflight + 工作区卫生')
    ap.add_argument('--skip-anki', action='store_true',
                    help='离线模式：跳过 AnkiConnect，preflight 也走 --offline')
    ap.add_argument('--tag', help='本集标签，透传给 preflight（如 动画::平家物语::第02集）')
    ap.add_argument('--quiet', action='store_true',
                    help='更省：只打 fail / warn 标题 + 结论（连提示明细也不展开）')
    ap.add_argument('--all', action='store_true',
                    help='展开全部明细（含第二期待办清单；不展开动画:: 标签全表）')
    ap.add_argument('--no-preflight', action='store_true', help='跳过第 7 项')
    a = ap.parse_args()

    report = Report()
    print('=' * 92)
    print('开工体检 doctor ｜ %s ｜ %s'
          % (WSP.ROOT, time.strftime('%Y-%m-%d %H:%M:%S')))
    print('=' * 92)

    check_anki(report, a.skip_anki, a.all)
    check_anki_audit(report, a.all)
    check_textio_audit(report, a.all)
    check_deprecated(report, a.all)
    check_snapshots(report, a.all)
    check_doc_status(report, a.all)
    if not a.no_preflight:
        check_preflight(report, a.tag, a.skip_anki, a.all)
    if not a.quiet:
        check_env(report, a.all)
    check_hygiene(report, a.all)

    print()
    print('=' * 92)
    print('小结')
    print('=' * 92)
    print('  ✓ 通过 %d 项' % len(report.oks))
    if a.all:
        for t in report.oks:
            print('      ✓ %s' % t)
    print('  · 提示 %d 项（可以继续干活）' % len(report.warns))
    for t, lines in report.warns:
        print('      · %s' % t)
        if not a.quiet:
            for ln in lines[:8]:
                print('          %s' % ln)
    print('  ✗ 阻塞 %d 项（必须先修）' % len(report.fails))
    for t, lines in report.fails:
        print('      ✗ %s' % t)
        for ln in lines[:20]:
            print('          %s' % ln)

    print()
    if report.fails:
        print('结论：✗ 有阻塞项 —— 先修完再动手。')
        return 1
    if report.warns:
        print('结论：✓ 可开工（有 %d 条提示，注意上面的内容）。' % len(report.warns))
        return 2
    print('结论：✓ 全绿，可以开工。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
