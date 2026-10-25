"""Workaround installer（仅本工作区用）.

两个沙箱交互问题：
1. pip 的临时目录由 ``tempfile.mkdtemp`` 建成 0o700，在 DSH 工作区沙箱下对受限令牌不可写
   -> 把 ``os.mkdir`` 的 mode 统一改成 0o777（``os.makedirs`` 的默认值，可写）。
2. pip 要用 PEP 517 子进程构建 sdist（unidic-lite / ipadic 都没有 wheel），子进程没有本补丁，
   会在管道通信上失败或挂住 -> 一律 ``--only-binary :all:``，只用预编译 wheel。

装到工作区内的 ``data/pylibs``（不进系统环境，卸载直接删目录）。

版本锁（2026-10-10 新增）
-------------------------
``data/pylibs.lock.json`` 记录已装包的**确切版本**（从 dist-info 实读，不是手敲）。

* 装之前先比对：锁里的包都还在、版本也对 → 直接跳过 pip（**幂等**，不会白跑一次联网）。
* 装完之后按实装结果**重写锁**。
* ``--check-only``：只比对并打印，绝不调用 pip（想确认环境状态时用这个）。
* ``--force``：忽略锁，照旧跑 pip。

用法::

    python code/oneshot/install_workspace_wheels.py --check-only   # 只看状态
    python code/oneshot/install_workspace_wheels.py                # 缺什么装什么（幂等）
    python code/oneshot/install_workspace_wheels.py --force        # 强制重装
    python code/oneshot/install_workspace_wheels.py <pkg> …        # 只装指定的包
"""
import json
import os
import re
import sys

WS = r"<工作区根>"
TARGET = os.path.join(WS, "data", "pylibs")
LOCK = os.path.join(WS, "data", "pylibs.lock.json")
DEFAULT_PKGS = ["sudachipy", "sudachidict_core", "matplotlib"]

sys.path.insert(0, os.path.join(WS, "code", "common"))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（import 时即 setup()）

argv = [a for a in sys.argv[1:] if not a.startswith('--')]
FLAGS = {a for a in sys.argv[1:] if a.startswith('--')}
UNKNOWN = FLAGS - {'--check-only', '--force'}
if UNKNOWN:
    raise SystemExit('未知参数：%s（可用 --check-only / --force）' % ' '.join(sorted(UNKNOWN)))
PKGS = argv or DEFAULT_PKGS


def canon(name):
    """包名规范化（PyPI 规则）：``SudachiPy`` / ``sudachipy`` / ``sudachi_py`` 视为同一个。"""
    return re.sub(r'[-_.]+', '-', name or '').lower()


def installed(pylibs=TARGET):
    """实读目录里的 dist-info → {规范化包名: 版本}。"""
    import importlib.metadata as md
    out = {}
    if not os.path.isdir(pylibs):
        return out
    for d in md.distributions(path=[pylibs]):
        nm = d.metadata['Name']
        if nm:
            out[canon(nm)] = d.version
    return out


def read_lock():
    if not os.path.isfile(LOCK):
        return {}
    try:
        got = json.load(open(LOCK, encoding='utf-8'))
        return got if isinstance(got, dict) else {}
    except Exception as exc:                                   # noqa: BLE001
        print('[lock] 读不了 %s：%s（忽略，继续）' % (LOCK, exc))
        return {}


def write_lock(requested):
    import datetime as _dt
    pkgs = installed()
    data = {
        '_readme': 'data/pylibs 的版本锁（工作区本地第三方库）。重装/升级后由 '
                   'code/oneshot/install_workspace_wheels.py 回写。删除 data/pylibs 即卸载。',
        'generated_at': _dt.date.today().isoformat(),
        'python': sys.version.split()[0],
        'target': 'data/pylibs',
        'requested': list(requested),
        'packages': dict(sorted(pkgs.items(), key=lambda kv: kv[0].lower())),
    }
    with open(LOCK, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    print('[lock] 已回写 %s（%d 个包）' % (os.path.relpath(LOCK, WS), len(pkgs)))


def lock_state():
    """→ (是否全部就绪, 缺失/版本不符的清单)。"""
    have = installed()
    locked = (read_lock().get('packages') or {})
    bad = []
    for name in PKGS:
        want = locked.get(canon(name)) or next(
            (v for k, v in locked.items() if canon(k) == canon(name)), None)
        got = have.get(canon(name)) or next(
            (v for k, v in have.items() if canon(k) == canon(name)), None)
        if got is None:
            bad.append('%s（未安装）' % name)
        elif want and got != want:
            bad.append('%s（锁 %s，实装 %s）' % (name, want, got))
    return (not bad), bad


if __name__ == '__main__':
    ready, bad = lock_state()
    print('目标目录 %s' % TARGET)
    print('请求安装 %s' % '、'.join(PKGS))
    if ready:
        have = installed()
        print('已就绪（%d 个包，与 data/pylibs.lock.json 一致）：' % len(have))
        for k in sorted(have, key=str.lower):
            print('  %-28s %s' % (k, have[k]))
        if '--check-only' in FLAGS:
            print('结论：--check-only，不调用 pip。')
            sys.exit(0)
        if '--force' not in FLAGS:
            print('结论：无需安装（要强制重装加 --force）。')
            sys.exit(0)
    else:
        print('缺 / 版本不符：')
        for b in bad:
            print('  · %s' % b)
        if '--check-only' in FLAGS:
            print('结论：--check-only，不调用 pip。')
            sys.exit(1)
    print('将调用 pip 安装 %d 个包到 %s' % (len(PKGS), TARGET))

    os.environ["TMP"] = os.path.join(WS, "data", "piptmp")
    os.environ["TEMP"] = os.environ["TMP"]
    os.environ["TMPDIR"] = os.environ["TMP"]
    for d in (os.environ["TMP"], TARGET):
        os.makedirs(d, exist_ok=True)

    _orig_mkdir = os.mkdir

    def _mkdir(path, mode=0o777, *a, **k):
        return _orig_mkdir(path, 0o777, *a, **k)

    os.mkdir = _mkdir

    sys.argv = [
        "pip", "install",
        "--no-input", "--disable-pip-version-check", "--no-cache-dir",
        "--only-binary", ":all:",
        "--target", TARGET,
    ] + PKGS
    from pip._internal.cli.main import main  # noqa: E402

    rc = main(sys.argv[1:])
    if rc == 0:
        write_lock(PKGS)
    sys.exit(rc)
