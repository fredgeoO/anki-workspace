# -*- coding: utf-8 -*-
"""文本 I/O 与编码的唯一入口（中文 Windows + GBK + PowerShell 5.1 的现实补丁）。

为什么要有这个模块
==================
本机的现实：**默认代码页 936（GBK）**，而工作区里几乎所有文本都是 **UTF-8**。
这个错配会在四个地方各炸一次，炸法还都不一样：

1. **输出**：stdout/stderr 被重定向（管道、被 DSH 抓走）时，Python 用
   ``locale.getpreferredencoding()`` = ``gbk``：
   ``print('♪')`` → ``UnicodeEncodeError: 'gbk' codec can't encode character '\\u266a'``。
   GBK 编得动的汉字不报错，但消费方（UTF-8）看到的是乱码 —— 这类"静默乱码"
   比崩溃更危险。

2. **输入（管道）**：PowerShell 用 ``$OutputEncoding``（UTF-8）把文本喂给
   ``python``，Python 却按 GBK 解 → 乱码或 ``UnicodeDecodeError``。

3. **读文件**：``open(path)`` 不带 ``encoding`` 时用 GBK（``locale``）；UTF-8 的
   日语/中文变乱码，GBK 收不下的字节直接抛错。

4. **子进程**：``subprocess.run(..., text=True)`` 不带 ``encoding`` 时同样用 GBK
   解子进程的 UTF-8 输出；子 Python 进程也继承不到 UTF-8。

**2026-10-08 的真实事故（本模块要防的那一类）**
------------------------------------------------
在 PowerShell 5.1 里读一个 UTF-8 的产出 JSON::

    Get-Content x.json -Raw | ConvertFrom-Json

5.1 的 ``Get-Content`` 默认 ``-Encoding Default`` = ANSI = **GBK**，于是日文字段名
被解成 ``宸ヤ綔...`` 这类乱码；按日文字段名取的属性一律 ``$null``，判断条件
**全部为真**，结果把 ``output/cmp4`` 里 39 个产出全删了（回归结果丢失、只能重跑）。
所以这套解法有两半，缺一不可：

* **Python 侧**：``import textio`` 一行解决上面 1-4（本模块）。
* **PowerShell 侧**：``code/common/ps-utf8.ps1``（把 Get-Content 等的默认编码钉成 utf8）。
* **铁律**：判断 / 筛选 / 删除前的确认一律交给 Python，PowerShell 只负责启动和显示；
  真要在 PS 里读文件必须 ``-Encoding utf8``，且删之前先打印"将删 N 个"清单。

用法
====
::

    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
    import textio as T          # ← import 这一下就把 stdio 接管成 UTF-8（幂等，失败也不抛）

    print('日本語 ♪')            # 不再 UnicodeEncodeError，也不再乱码
    txt = T.read_text(p)        # UTF-8/BOM/UTF-16/GBK/CP932 自动判；不是 UTF-8 会警告
    obj = T.load_json(p)        # 带 BOM 也读得进（json.load(open(p, 'utf-8')) 读不进）
    T.write_text(out, txt)      # 一律 UTF-8 无 BOM、LF
    T.dump_json(obj, out)       # ensure_ascii=False
    r = T.run([sys.executable, other])   # text + utf-8 + 把 PYTHONIOENCODING 传给子进程

命令行（体检 / 安全读 / 防回退审计）::

    & $PY code\\common\\textio.py check                 # 自检：stdio / 管道 / 各种编码的文件
    & $PY code\\common\\textio.py info                  # 当前 stdio 与环境（排查用）
    & $PY code\\common\\textio.py read data\\x.json --json --keys 振假名,词
    & $PY code\\common\\textio.py decode weird.srt --head 3
    & $PY code\\common\\textio.py audit                 # 退出码 0 = 全仓没有手工编码补丁

边界（本模块**不**做的事）
==========================
* 不猜业务语义：非 UTF-8 文件按"试解码 + 像不像正文"打分判定，并在 stderr 明确
  报告用了哪个编码；要绝对确定就显式传 ``encodings=('gbk',)``。
* 不写 BOM；换行默认 LF（要 CRLF 传 ``newline='\\r\\n'``）。
* 不接管 PowerShell —— PS 侧看 ``code/common/ps-utf8.ps1``。
"""
from __future__ import annotations

import argparse
import ast
import codecs
import io
import json
import locale
import os
import re
import subprocess
import sys
import tokenize

__all__ = [
    'TextEncodingError', 'setup', 'info', 'decode', 'read_bytes', 'read_text',
    'read_text_ex', 'read_stdin', 'load_json', 'loads_json', 'write_text',
    'dump_json', 'child_env', 'text_kwargs', 'run', 'warn',
]

NAME = 'textio'
STDIO_ERRORS = 'replace'          # 编不出来就替换，绝不让脚本因为打印而崩

#: 全量候选（``decode(encodings=…)`` 显式指定时用；``srt.py`` 这类知道自己可能遇到
#: CP932/EUC-JP 的调用方就用它）。
ENCODINGS = ('utf-8-sig', 'utf-8', 'gb18030', 'cp932', 'shift_jis', 'euc_jp', 'cp1252')
#: 自动判定时的候选。**故意不含 euc_jp**：GB2312 抄了 JIS 的假名行，EUC-JP 的假名在
#: GBK 里解出来还是同一批假名（「日本語の字幕です。」↔「泣塑胳の机穗です。」的
#: 假名/汉字计数一模一样），机器只靠字符分布分不开这两种读法，硬猜会猜错一半。
#: 真需要它（老字幕）就显式 hint：``read_text(p, encodings=srt.ENCODINGS)``。
DEFAULT_ENCODINGS = ('gb18030', 'cp932', 'cp1252')

_BOMS = (
    (codecs.BOM_UTF8, 'utf-8-sig'),
    (codecs.BOM_UTF32_LE, 'utf-32'), (codecs.BOM_UTF32_BE, 'utf-32'),
    (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16'),
)

_KANA = re.compile(r'[\u3041-\u309f\u30a0-\u30ff]')
_HALFKANA = re.compile(r'[\uff61-\uff9f]')
_HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
# 「UTF-8 字节被当 CP932/GBK 读」出来的标志字（srt.py 里那份经验的通用版）
_MOJIBAKE = re.compile(r'[繧縺譁繝縲鈥]')
_REPLACEMENT = '\ufffd'

_MISSING = object()


class TextEncodingError(RuntimeError):
    """严格模式下解码失败 / 有损（strict=True 时才会抛）。"""


# --------------------------------------------------------------------- stdio
def _warn(msg: str) -> None:
    try:
        sys.stderr.write('[%s] %s\n' % (NAME, msg))
    except Exception:                                      # noqa: BLE001
        pass


def warn(msg: str) -> None:
    """统一的 ``[textio] …`` 前缀警告（走 stderr，不会污染 stdout 的数据）。"""
    _warn(msg)


def _reconfig_one(name: str, errors: str):
    stream = getattr(sys, name, None)
    if stream is None:
        return None
    before = getattr(stream, 'encoding', None)
    if hasattr(stream, 'reconfigure'):
        try:
            stream.reconfigure(encoding='utf-8', errors=errors)
            return (before, getattr(stream, 'encoding', None))
        except Exception:                                  # noqa: BLE001
            return (before, before)
    buf = getattr(stream, 'buffer', None)                  # Python < 3.7 兜底
    if buf is not None:
        try:
            setattr(sys, name, io.TextIOWrapper(buf, encoding='utf-8', errors=errors,
                                                line_buffering=True))
            return (before, 'utf-8')
        except Exception:                                  # noqa: BLE001
            return (before, before)
    return (before, before)


def setup(stdin: bool = True, stdout: bool = True, stderr: bool = True,
          errors: str = STDIO_ERRORS) -> dict:
    """把 stdio 钉成 UTF-8（幂等）。返回 ``{流名: (before, after)}``。

    同时在 ``os.environ`` 里种下 ``PYTHONIOENCODING/PYTHONUTF8``，让之后 fork 出去的
    子 Python 进程也默认 UTF-8（``child_env()`` 会显式带上，这里照顾手工 spawn 的）。
    """
    # 管道/重定向时 stdout 用 locale（GBK）——这是两个症状的总开关
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ.setdefault('PYTHONUTF8', '1')
    out = {}
    if stdin:
        out['stdin'] = _reconfig_one('stdin', errors)
    if stdout:
        out['stdout'] = _reconfig_one('stdout', errors)
    if stderr:
        out['stderr'] = _reconfig_one('stderr', errors)
    return out


def info() -> dict:
    """当前 stdio / 环境快照（``check``、``info``、排查脚本都用它）。"""
    def enc(name):
        s = getattr(sys, name, None)
        return None if s is None else getattr(s, 'encoding', None)

    return {
        'python': sys.version.split()[0],
        'executable': sys.executable,
        'stdout': enc('stdout'), 'stderr': enc('stderr'), 'stdin': enc('stdin'),
        'stdout_errors': getattr(sys.stdout, 'errors', None),
        'isatty': bool(getattr(sys.stdout, 'isatty', lambda: False)()),
        'locale_preferred': locale.getpreferredencoding(False),
        'fs_encoding': sys.getfilesystemencoding(),
        'PYTHONIOENCODING': os.environ.get('PYTHONIOENCODING'),
        'PYTHONUTF8': os.environ.get('PYTHONUTF8'),
        'platform': sys.platform,
    }


# --------------------------------------------------------------------- 解码
def _plausibility(text: str) -> float:
    """一段文本"像不像正常中日文正文"的粗略打分（cp932 与 gb18030 都能吃下几乎
    任意字节，所以不能只看"解得出/解不出"，得看解出来像不像话）。

    假名权重最高（日语正文的一半是假名）；汉字次之；UTF-8 乱码标志字、替换字符、
    半角片假名（GBK 中文被当 CP932 读时满地都是）都扣分。
    """
    body = sum(1 for c in text if not c.isspace()) or 1
    kana = len(_KANA.findall(text))
    han = len(_HAN.findall(text))
    bad = len(_MOJIBAKE.findall(text)) + text.count(_REPLACEMENT)
    half = len(_HALFKANA.findall(text))
    return (kana + 0.5 * han) / body - (2.0 * bad + 0.8 * half) / body


def sniff_encoding(data: bytes, encodings=None) -> str:
    """只判编码名（``decode`` 的判定部分，不返回值）。"""
    return decode(data, encodings=encodings)[1]


def decode(data, encodings=None, errors: str = 'replace'):
    """bytes → ``(text, encoding, lossy)``。

    判定顺序：BOM → UTF-8 严格（最强证据，一票采信）→ 带 NUL 时试 UTF-16 →
    其余候选严格试解后按 :func:`_plausibility` 打分取最高（并列时按候选顺序，
    即 gb18030 优先于 cp932）→ 全失败才按 ``errors`` 有损解码。

    显式传了 ``encodings`` 就只按那份清单试（不再先试 UTF-8）。
    """
    if isinstance(data, str):
        return data, 'str', False
    if data is None:
        return '', 'none', False
    if not data:
        return '', 'utf-8', False

    for bom, enc in _BOMS:                                 # 1) BOM 说话最算数
        if data.startswith(bom):
            try:
                return data.decode(enc), enc, False
            except UnicodeDecodeError:
                break

    if encodings is None:
        try:                                               # 2) 无 BOM 的 UTF-8
            return data.decode('utf-8'), 'utf-8', False
        except UnicodeDecodeError:
            pass
        if data.count(b'\x00') > len(data) * 0.2:          # 3) 无 BOM 的 UTF-16
            for enc in ('utf-16-le', 'utf-16-be'):
                try:
                    txt = data.decode(enc)
                except UnicodeDecodeError:
                    continue
                if txt.count('\x00') < len(txt) * 0.05:
                    return txt, enc, False

    cands = []
    for enc in (encodings or DEFAULT_ENCODINGS):
        try:
            txt = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        cands.append((txt, enc))
    if cands:                                              # 4) 打分
        txt, enc = max(cands, key=lambda t: (_plausibility(t[0]),
                                             -ENCODINGS.index(t[1]) if t[1] in ENCODINGS else -99))
        lossy = _REPLACEMENT in txt
        return txt, enc, lossy

    last = (encodings or DEFAULT_ENCODINGS)[0]             # 5) 有损兜底，绝不抛
    return data.decode(last, errors=errors), last + '/replace', True


def read_bytes(path) -> bytes:
    with open(path, 'rb') as fh:
        return fh.read()


def read_text_ex(path, encodings=None, errors: str = 'replace', warn: bool = True):
    """``(text, encoding, lossy)``；不是 UTF-8 或有损时在 stderr 报告（``warn=False`` 闭嘴）。

    静默乱码是 2026-10-08 那次误删的帮凶，所以默认要出声。
    """
    data = read_bytes(path)
    text, enc, lossy = decode(data, encodings=encodings, errors=errors)
    if warn:
        if not str(enc).startswith(('utf-8', 'str')):
            _warn('%s 不是 UTF-8，按 %s 解码；若是 PowerShell 写的，请用 -Encoding utf8'
                  % (_short(path), enc))
        if lossy:
            _warn('⛔ %s 解码有损（%s + %s）：内容可能已被破坏，别拿它做删改判断'
                  % (_short(path), enc, errors))
    return text, enc, lossy


def read_text(path, encodings=None, errors: str = 'replace', warn: bool = True) -> str:
    """读文本，自动判 UTF-8/BOM/UTF-16/GBK/CP932。"""
    return read_text_ex(path, encodings=encodings, errors=errors, warn=warn)[0]


def read_stdin(errors: str = 'replace') -> str:
    """读标准输入（PowerShell 管道）。

    走 ``sys.stdin.buffer`` 自己判编码：PowerShell 5.1 的 ``$OutputEncoding`` 通常是
    UTF-8，但用 ``cmd``/重定向时可能是 GBK，两种都收。内容不裁剪（尾随换行保留）。
    """
    stream = sys.stdin
    buf = getattr(stream, 'buffer', None)
    if buf is None:
        return stream.read()
    return decode(buf.read(), errors=errors)[0]


def load_json(path, default=_MISSING, encodings=None, strict: bool = False,
              warn: bool = True):
    """读 JSON。带 BOM / GBK / UTF-16 都行（``json.load(open(p, encoding='utf-8'))``
    遇到 PowerShell 写的 BOM 会直接抛）。

    ``strict=True``：非 UTF-8 或有损就抛 :class:`TextEncodingError`（做删改判断时用）。
    ``default``：文件不存在 / JSON 坏掉时返回它（给了就不抛）。
    """
    try:
        text, enc, lossy = read_text_ex(path, encodings=encodings,
                                        errors='strict' if strict else 'replace', warn=warn)
    except FileNotFoundError:
        if default is _MISSING:
            raise
        return default
    except UnicodeDecodeError as exc:
        raise TextEncodingError('%s 不是可用的文本（%s）；不要用它做判断' % (path, exc)) from exc
    if strict and (lossy or not str(enc).startswith(('utf-8', 'str'))):
        raise TextEncodingError('%s 不是干净的 UTF-8（判定为 %s，lossy=%s）'
                                % (path, enc, lossy))
    try:
        return loads_json(text)
    except ValueError:
        if default is _MISSING:
            raise
        return default


def loads_json(text: str):
    """``json.loads`` 的 BOM 容忍版（PS 5.1 的 ``-Encoding utf8`` 会带 BOM）。"""
    if isinstance(text, bytes):
        text = decode(text)[0]
    return json.loads(text.lstrip('\ufeff'))


# --------------------------------------------------------------------- 写
def write_text(path, text: str, newline: str = '\n', atomic: bool = False,
               bom: bool = False) -> str:
    """写 UTF-8 文本（默认无 BOM、LF）。``atomic=True`` 先写临时文件再 ``os.replace``。"""
    path = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    body = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    if newline != '\n':
        body = body.replace('\n', newline)
    data = body.encode('utf-8-sig' if bom else 'utf-8')
    if atomic:
        tmp = '%s.tmp%d' % (path, os.getpid())
        with open(tmp, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, path)
    else:
        with open(path, 'wb') as fh:
            fh.write(data)
    return path


def dump_json(obj, path, indent: int = 1, sort_keys: bool = False,
              atomic: bool = False, **kw) -> str:
    """写 JSON：``ensure_ascii=False`` + UTF-8 无 BOM（中文可读、可 diff）。"""
    kw.setdefault('ensure_ascii', False)
    text = json.dumps(obj, indent=indent, sort_keys=sort_keys, **kw)
    return write_text(path, text + '\n', atomic=atomic)


# --------------------------------------------------------------------- 子进程
def child_env(env=None) -> dict:
    """给子进程的环境：显式带上 UTF-8 相关的两个变量（子 Python 也就不用再管 GBK）。"""
    out = dict(os.environ if env is None else env)
    out['PYTHONIOENCODING'] = 'utf-8'
    out['PYTHONUTF8'] = '1'
    return out


def text_kwargs() -> dict:
    """``subprocess`` 的文本模式参数（``text=True`` 且按 UTF-8 解，编不出来替换）。"""
    return {'text': True, 'encoding': 'utf-8', 'errors': 'replace'}


def run(cmd, env=None, check: bool = False, timeout=None, input=None, cwd=None, **kw):
    """``subprocess.run`` 的 UTF-8 文本版（默认抓 stdout/stderr，子进程环境已修好）。"""
    kw.setdefault('stdout', subprocess.PIPE)
    kw.setdefault('stderr', subprocess.PIPE)
    kw.update(text_kwargs())
    return subprocess.run(cmd, env=child_env(env), check=check, timeout=timeout,
                          input=input, cwd=cwd, **kw)


def _short(path) -> str:
    p = os.fspath(path)
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        rel = os.path.relpath(p, here)
        return p if rel.startswith('..') else rel.replace('\\', '/')
    except ValueError:
        return p


# import 即接管（幂等、失败不抛）：脚本只要 ``import textio`` 就够了。
# 必须在 CLI 之前执行，``textio.py check`` 才能把「已经接管」当成前提来断言。
setup()


# ============================================================================
# CLI：体检 / 安全读 / 防回退审计
# ============================================================================
ROOTS = ('code', os.path.join('.dsh', 'skills'), 'core6000-analysis')
SKIP_DIRS = {'__pycache__', 'pylibs', 'archive', 'node_modules', '.git', '.tmp', 'temp',
             'data', 'output', 'subtitles'}

#: R1 —— 手工编码补丁。这些写法散在各脚本里就是「同一件事被抄了 N 遍」，
#: 现在唯一实现是本模块，出现即回退（2026-10-08 之前有 20+ 处）。
HACKS = (
    (r'sys\.(stdout|stderr)\.reconfigure\(', '手工 reconfigure stdio'),
    (r'io\.TextIOWrapper\(\s*sys\.(stdout|stderr)', '手工 TextIOWrapper 包 stdio'),
    (r'sys\.(stdout|stderr)\.encoding\s*=', '手工改 stdio.encoding'),
    (r'PYTHONIOENCODING\s*=\s*["\']', '手工设 PYTHONIOENCODING'),
)
#: R4 —— PowerShell 侧的经典坑（本机 shell 是 5.1，默认 ANSI=GBK）
PS_DANGER = (
    (r'\b(Get-Content|Import-Csv|Select-String)\b(?![^\n]*-Encoding)', '读文件没写 -Encoding utf8'),
    (r'\b(Set-Content|Add-Content|Out-File|Export-Csv)\b(?![^\n]*-Encoding)', '写文件没写 -Encoding utf8'),
    (r'\bConvertFrom-Json\b', 'PS 里解析 JSON（判断请交给 Python）'),
)


def _ws_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _iter_files(root: str, exts):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.lower().endswith(tuple(exts)):
                yield os.path.join(dirpath, fn)


def _lines_of_hits(src: str, pattern: str):
    for m in re.finditer(pattern, src):
        yield src.count('\n', 0, m.start()) + 1


_NONCODE = frozenset(t for t in (
    getattr(tokenize, 'COMMENT', None), getattr(tokenize, 'NL', None),
    getattr(tokenize, 'NEWLINE', None), getattr(tokenize, 'INDENT', None),
    getattr(tokenize, 'DEDENT', None), getattr(tokenize, 'ENDMARKER', None),
    getattr(tokenize, 'ENCODING', None), getattr(tokenize, 'STRING', None)) if t is not None)
_BINARY_MODE = re.compile(r"['\"][rwxabt+]{1,3}['\"]")
_RECEIVER = re.compile(r'([A-Za-z_][\w.]*)\.(read_text|write_text)\(')


def _open_without_encoding(src: str):
    """文本模式 ``open()`` / ``Path(...).read_text()`` 没写 ``encoding`` 的行号。

    只认「读/写文本」的写法：二进制模式（``'wb'``）和自带编码策略的接收者
    （``srt_mod.read_text(p)`` 这种自己的函数）不算。
    """
    hits = []
    for m in re.finditer(r'(?<!def )(?<![\w.])(?:open|io\.open)\(', src):
        seg, closed = _paren_span(src, m.end() - 1)
        if not closed or 'encoding' in seg:
            continue
        if any('b' in mode for mode in _BINARY_MODE.findall(seg)):
            continue
        hits.append(src.count('\n', 0, m.start()) + 1)
    for m in _RECEIVER.finditer(src):
        recv = m.group(1).split('.')[-1]
        if not (recv.startswith('Path') or re.search(r'(?:path|file|_p|_f)$', recv)):
            continue
        seg, closed = _paren_span(src, m.end() - 1)
        if not closed or 'encoding' in seg:
            continue
        hits.append(src.count('\n', 0, m.start()) + 1)
    return hits


def _code_only(src: str) -> str:
    """把"整行都是注释/字符串（含 docstring）"的行清空，行号保持不变。

    审计只看**代码**：文档里为说明问题而引用的旧写法不算回退（写 ``textio-ok``
    的行也一律豁免）。
    """
    lines = src.splitlines()
    keep = [False] * (len(lines) + 1)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in _NONCODE:
                continue
            for ln in range(tok.start[0], min(tok.end[0], len(lines)) + 1):
                if ln >= 1:
                    keep[ln] = True
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return src
    return '\n'.join('' if not keep[i + 1] or 'textio-ok' in ln else ln
                     for i, ln in enumerate(lines))


def _comment_free(src: str) -> str:
    """PowerShell 侧只豁免整行注释（``# …``）。"""
    return '\n'.join('' if ln.lstrip().startswith('#') or 'textio-ok' in ln else ln
                     for ln in src.splitlines())


#: 行里出现这些就说明它**已经**把编码钉住了（或者是在讲怎么钉），不算危险写法
PS_EXEMPT = ('-Encoding', ':Encoding', '[System.IO.File]::ReadAllText',
             'Encoding]::UTF8', 'textio-ok', 'Write-Verbose', 'Write-Host')


def _ps_danger_lines(src: str):
    """PowerShell 里「读工作区文件但没钉编码」的行（``-> [(行号, 原因)]``）。"""
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or any(x in line for x in PS_EXEMPT):
            continue
        for pattern, why in PS_DANGER:
            if re.search(pattern, line):
                out.append((i, why))
    return out


def needs_textio(src: str) -> bool:
    """这个脚本会不会「被直接跑并打印」？会的话就必须 ``import textio``。

    判据（用 ast，不靠猜）：有 ``if __name__`` 门槛，**或在模块层直接 ``print(...)`` /
    ``sys.stdout.write(...)``** —— ``core6000-analysis/`` 与 ``code/analysis/anki_analyze/``
    那批就是没有 `__main__`、跑到顶层就打印的脚本（2026-10-08 第一轮迁移漏了这 44 个，
    实测它们不看 `PYTHONIOENCODING` 时照样打出乱码）。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return bool(re.search(r'^if\s+__name__\s*==', src, re.M)
                    or re.search(r'^\s*print\(', src, re.M))
    for node in tree.body:
        if isinstance(node, ast.If) and '__name__' in ast.dump(node.test):
            return True
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == 'print':
                return True
            if isinstance(func, ast.Attribute) and func.attr == 'write' \
                    and 'stdout' in ast.dump(func.value):
                return True
    return False


def _paren_span(src: str, i: int):
    """``src[i] == '('``：返回括号内文本与是否闭合。"""
    depth, j = 0, i
    while j < len(src):
        c = src[j]
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
            if depth == 0:
                return src[i + 1:j], True
        j += 1
    return src[i + 1:], False


def cmd_audit(args) -> int:
    root = args.root or _ws_root()
    self_path = os.path.abspath(__file__)
    r1, r2, r3, r5 = {}, {}, {}, {}
    r4 = {}
    for base in (args.paths or ROOTS):
        for path in _iter_files(os.path.join(root, base), args.ext):
            if os.path.abspath(path) == self_path:
                continue
            try:
                src = read_text(path, warn=False)
            except OSError:
                continue
            rel = os.path.relpath(path, root).replace('\\', '/')
            if path.endswith('.py'):
                code = _code_only(src)          # 只看代码：docstring 里的旧写法不算回退
                for pattern, why in HACKS:
                    lines = list(_lines_of_hits(code, pattern))
                    if lines:
                        r1.setdefault(rel, []).extend((ln, why) for ln in lines)
                if needs_textio(src) and \
                        not re.search(r'^\s*(import\s+textio\b|from\s+textio\s+import)', code, re.M):
                    r2[rel] = ['会直接跑的脚本没有 import textio（stdio 仍是 GBK）']
                lines = _open_without_encoding(code)
                if lines:
                    r3[rel] = [(ln, '文本模式 open 没写 encoding') for ln in lines]
                if re.search(r'sys\.stdin\.(read|buffer)', code):
                    r5[rel] = [(ln, '直接用 sys.stdin，建议 T.read_stdin()')
                               for ln in _lines_of_hits(code, r'sys\.stdin\.(read|buffer)')]
            else:
                lines = list(_ps_danger_lines(src))
                if not read_bytes(path).startswith(codecs.BOM_UTF8):
                    lines.append((1, '脚本没有 BOM：PS 5.1 按 ANSI 解析，中文注释会毁掉语法'))
                if lines:
                    r4[rel] = lines

    def show(title, hits, fatal, hint=''):
        n = sum(len(v) for v in hits.values())
        mark = '✓' if not n else ('✗' if fatal else '·')
        print('%s %-34s %3d 处 / %2d 个文件 %s' % (mark, title, n, len(hits), hint))
        for rel in sorted(hits)[:(len(hits) if args.all else 5)]:
            for item in sorted(set(hits[rel]), key=repr):   # 有条目带行号，有的不带
                ln, why = item if isinstance(item, tuple) else (0, item)
                print('      %s%s  %s' % (rel, (':%d' % ln) if ln else '', why))

    print('textio audit —— 根目录 %s' % root)
    print()
    show('R1 手工编码补丁（必须为 0）', r1, True, '→ 删掉，改成 import textio')
    show('R2 会直接跑的脚本没 import textio', r2, True, '→ 加一行 import textio')
    show('R3 文本 open 没写 encoding（建议）', r3, False, '→ 加 encoding 或走 textio')
    show('R4 PowerShell 读文件缺 -Encoding（建议）', r4, False, '→ 见 code/common/ps-utf8.ps1')
    show('R5 直接用 sys.stdin（建议）', r5, False, '→ T.read_stdin()')
    print()
    bad = bool(r1 or r2) or (args.strict and (r3 or r4 or r5))
    if not bad:
        print('结论：干净（%s）' % ('--strict 也通过' if args.strict else '加 --strict 连建议项一起卡'))
    else:
        print('结论：需处理（%s）' % ('；'.join(
            t for t, h in (('R1', r1), ('R2', r2), ('R3', r3), ('R4', r4), ('R5', r5))
            if h and (t in ('R1', 'R2') or args.strict))))
    return 1 if bad else 0


def cmd_info(args) -> int:
    for k, v in info().items():
        print('%-20s %s' % (k, v))
    ps = os.path.join(_ws_root(), 'code', 'common', 'ps-utf8.ps1')
    print('%-20s %s' % ('ps-utf8.ps1', ps if os.path.isfile(ps) else '（缺失）'))
    return 0


def cmd_read(args) -> int:
    path = args.path
    text, enc, lossy = read_text_ex(path, encodings=(args.encoding,) if args.encoding else None,
                                    warn=args.warn)
    try:
        obj = loads_json(text)
    except ValueError:
        print('[textio] %s 不是 JSON（判定编码 %s），按文本输出' % (_short(path), enc),
              file=sys.stderr)
        print(text, end='')
        return 0
    if args.count:
        print(len(obj) if isinstance(obj, (list, dict, str)) else 1)
        return 0
    if args.keys:
        missing = []
        for key in [k.strip() for k in args.keys.split(',') if k.strip()]:
            if isinstance(obj, dict) and key in obj:
                val = obj[key]
                print('%s\t%s' % (key, val if isinstance(val, str)
                                  else json.dumps(val, ensure_ascii=False)))
            else:
                missing.append(key)
                print('%s\t<缺失>' % key)
        if missing:
            print('[textio] ⛔ 有 %d 个键在文件里不存在：%s\n'
                  '          若是 PowerShell 读出来的，先怀疑编码（GBK 当 UTF-8 → 键名乱码 → 取到 $null）。\n'
                  '          本命令读的是同一份文件，键名如此才是真的。'
                  % (len(missing), ','.join(missing)), file=sys.stderr)
            return 2
        return 0
    if isinstance(obj, list):
        print('[textio] %s：数组 %d 项%s' % (_short(path), len(obj),
              '，前 %d 项：' % args.limit if args.limit else ''))
        if args.limit:
            print(json.dumps(obj[:args.limit], ensure_ascii=False, indent=1))
            return 0
    print(json.dumps(obj, ensure_ascii=False, indent=1))
    return 0


def cmd_decode(args) -> int:
    data = read_bytes(args.path)
    text, enc, lossy = decode(data, encodings=(args.encoding,) if args.encoding else None)
    strict = []
    for cand in (args.encoding,) if args.encoding else ENCODINGS:
        try:
            data.decode(cand)
            strict.append(cand)
        except (UnicodeDecodeError, LookupError):
            continue
    if args.json:
        print(json.dumps({'path': os.fspath(args.path), 'encoding': enc, 'lossy': lossy,
                          'bytes': len(data), 'chars': len(text),
                          'replacement_chars': text.count(_REPLACEMENT),
                          'strict_ok': strict}, ensure_ascii=False, indent=1))
        return 0
    print('文件      %s' % _short(args.path))
    print('判定编码  %s%s' % (enc, '（有损！）' if lossy else ''))
    print('字节/字符 %d / %d' % (len(data), len(text)))
    print('严格可解  %s' % (', '.join(strict) or '无（任何候选都要替换字符）'))
    print('替换字符  %d' % text.count(_REPLACEMENT))
    if args.head:
        print('--- 前 %d 行 ---' % args.head)
        for line in text.splitlines()[:args.head]:
            print(line)
    return 0


def _scratch() -> str:
    d = os.path.join(_ws_root(), 'temp', 'textio-check')
    os.makedirs(d, exist_ok=True)
    return d


def cmd_check(args) -> int:
    results = []

    def step(name, ok, detail=''):
        results.append((name, ok, detail))
        print('%s %-42s %s' % ('✓' if ok else '✗', name, detail))

    st = info()
    step('stdio 已接管为 UTF-8', str(st['stdout']).lower().startswith('utf8')
         or str(st['stdout']).lower() == 'utf-8',
         'stdout=%s stderr=%s stdin=%s' % (st['stdout'], st['stderr'], st['stdin']))
    sample = '日本語テスト ♪ 工作区「振仮名」— Ａ'
    try:
        print('   print() 样张：%s' % sample)
        step('print() 中日文混排不崩', True)
    except Exception as exc:                               # noqa: BLE001
        step('print() 中日文混排不崩', False, repr(exc))

    # 管道：子进程按 UTF-8 读 stdin、写 stdout（PowerShell 管道走的就是这条路）
    code = ('import sys\n'
            "sys.stdout.reconfigure(encoding='utf-8')\n"
            "sys.stdout.write(sys.stdin.buffer.read().decode('utf-8'))\n")
    try:
        proc = subprocess.run([sys.executable, '-c', code], input=(sample + '\n').encode('utf-8'),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=child_env())          # 不用 T.run：这里要故意不给 encoding
        got = proc.stdout.decode('utf-8', 'replace')
        step('子进程管道往返（UTF-8）', got.strip() == sample, 'child stdout=%r' % got.strip()[:40])
    except Exception as exc:                               # noqa: BLE001
        step('子进程管道往返（UTF-8）', False, '沙箱不给管道：%s: %s' % (type(exc).__name__, exc))

    scratch = _scratch()
    cases = [
        ('utf-8', 'utf-8', '日本語 ♪ 工作区', 'utf-8', None),
        ('utf-8-BOM', 'utf-8-sig', '工作区路径（PS 5.1 -Encoding utf8 的产物）', 'utf-8', None),
        ('utf-16-BOM', 'utf-16', '工作区路径（PS 5.1 Out-File 的产物）', 'utf-16', None),
        ('GBK/ANSI', 'gb18030', '工作区路径的唯一来源', 'gb', None),
        ('CP932', 'cp932', '日本語の字幕です。', 'cp932', None),
        ('EUC-JP（显式 hint）', 'euc_jp', '日本語の字幕です。', 'euc', ('euc_jp',)),
    ]
    for label, enc, text, want, hint in cases:
        path = os.path.join(scratch, 'case_%s.txt' % enc)
        with open(path, 'wb') as fh:
            fh.write(text.encode(enc))
        got, det, lossy = read_text_ex(path, encodings=hint, warn=False)
        ok = got == text and str(det).startswith(want) and not lossy
        step('读文件 %-9s → %-10s' % (label, det), ok,
             'lossy=%s' % lossy if not ok else '')
        if enc == 'euc_jp':
            got2, det2, lossy2 = read_text_ex(path, warn=False)
            step('EUC-JP 无 hint 也不丢字（判定 %s）' % det2,
                 not lossy2 and _REPLACEMENT not in got2,
                 '机器分不开 GB2312/JIS 共用的那段假名行，这是已知边界')

    gbk_path = os.path.join(scratch, 'case_gb18030.txt')
    saved, buf = sys.stderr, io.StringIO()
    try:
        sys.stderr = buf
        read_text(gbk_path)
    finally:
        sys.stderr = saved
    step('非 UTF-8 会出声（不再静默乱码）', '不是 UTF-8' in buf.getvalue(),
         buf.getvalue().strip().splitlines()[0] if buf.getvalue() else '没有警告')

    bom_json = os.path.join(scratch, 'bom.json')
    write_text(bom_json, json.dumps({'振假名': 'ふりがな'}, ensure_ascii=False), bom=True)
    obj = load_json(bom_json, warn=False)
    naive = None
    try:
        with open(bom_json, encoding='utf-8') as fh:
            json.load(fh)
        naive = '没抛（意外）'
    except ValueError as exc:
        naive = type(exc).__name__
    step('load_json 吃得下 BOM', obj.get('振假名') == 'ふりがな',
         'json.load(open(...,%r)) 会 %s' % ('utf-8', naive))

    out = os.path.join(scratch, 'roundtrip.txt')
    write_text(out, '一行\n二行\n')
    raw = read_bytes(out)
    step('write_text = UTF-8 无 BOM / LF', raw == '一行\n二行\n'.encode('utf-8'),
         'bytes=%r' % raw[:6])

    step('child_env 带上 UTF-8 变量',
         child_env().get('PYTHONIOENCODING') == 'utf-8'
         and text_kwargs().get('encoding') == 'utf-8')

    ps_rel = os.path.join('code', 'common', 'ps-utf8.ps1')
    ps = os.path.join(_ws_root(), ps_rel)
    if os.path.isfile(ps):
        step('ps-utf8.ps1 存成 UTF-8 带 BOM', read_bytes(ps).startswith(codecs.BOM_UTF8),
             'PS 5.1 对无 BOM 的脚本按 ANSI 解析，中文注释会毁掉语法')

    print()
    bad = [n for n, ok, _ in results if not ok]
    print('check：%d/%d 通过%s' % (len(results) - len(bad), len(results),
                                 '' if not bad else '，失败：' + '、'.join(bad)))
    print('提示：PowerShell 侧这样加载（CurrentUser 策略是 RemoteSigned，未签名脚本会被拦）：')
    print('      iex ([IO.File]::ReadAllText("$WS\\%s", [Text.Encoding]::UTF8))' % ps_rel)
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog='textio.py',
        description='文本 I/O 与编码的唯一入口：stdio 接管 / 解码 / 安全读 / 防回退审计')
    sub = ap.add_subparsers(dest='cmd')

    p = sub.add_parser('check', help='自检：stdio / 管道 / 各种编码的文件')
    p.set_defaults(func=cmd_check)

    p = sub.add_parser('info', help='当前 stdio 与环境')
    p.set_defaults(func=cmd_info)

    p = sub.add_parser('read', help='安全读 JSON/文本（替代 PS 的 Get-Content|ConvertFrom-Json）')
    p.add_argument('path')
    p.add_argument('--keys', help='只看这些键（逗号分隔）；键不存在会以退出码 2 报警')
    p.add_argument('--count', action='store_true', help='只打印项数')
    p.add_argument('--limit', type=int, default=0, help='数组时只打印前 N 项')
    p.add_argument('--warn', action='store_true', help='打开非 UTF-8/有损警告')
    p.add_argument('--encoding', help='强制按这个编码读')
    p.set_defaults(func=cmd_read)

    p = sub.add_parser('decode', help='报一个文件的编码判定（是否无损）')
    p.add_argument('path')
    p.add_argument('--encoding', help='只试这个编码')
    p.add_argument('--head', type=int, default=0, help='顺带打印前 N 行')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_decode)

    p = sub.add_parser('audit', help='扫全仓手工编码补丁（防回退）')
    p.add_argument('--strict', action='store_true', help='建议项也算失败')
    p.add_argument('--all', action='store_true', help='列出每个文件')
    p.add_argument('--root', help='工作区根（默认自动定位）')
    p.add_argument('--paths', nargs='*', help='只扫这些子目录（默认 code / .dsh/skills / core6000-analysis）')
    p.add_argument('--ext', nargs='*', default=['.py', '.ps1', '.psm1'],
                   help='文件后缀（默认 .py .ps1 .psm1）')
    p.set_defaults(func=cmd_audit)

    args = ap.parse_args(argv)
    if not getattr(args, 'func', None):
        return cmd_check(args)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
