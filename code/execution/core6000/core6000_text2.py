# -*- coding: utf-8 -*-
"""core6000 补例句②的共享底座：HTML 正则 + JSON / 文本小工具（纯函数）。

从 ``execution/core6000_example.py`` 抽出（2026-11-02，Issue #4「按能力切分超大流程
文件」）。这块是**两个能力的公共地基**：Jisho 例句源（``core6000_jisho``）和字段渲染
（``core6000_render``）用的是同一组去注音 / 数块 / 切块 / 振假名合规口径，必须一字不差。
放在独立模块里也顺手把 import 链拉直：巨石不再需要「先定义小工具、才能搬走 Jisho」。

不碰 Anki、不碰 LLM；只有 ``read_json`` / ``write_text`` / ``write_json`` 这对原子落盘
助手会读写文件。口径一字未改；``core6000_example`` 仍以同名模块级别名导出这些函数
（测试与探针脚本照旧用 ``CE.flatten`` / ``CE.count_blocks`` …）。

``RE_*`` 正则也从巨石里搬到这里，**同一份编译结果**给三个模块共用——同一个「去 ruby
后比对」的口径不该有两份正则。板块解析（``parse_sections``）留在巨石里，它还要用
``RE_SHELL`` / ``RE_MARKER`` 这些，从本模块 import 即可。
"""
import json
import os
import re
import sys

# 系列子目录（issue #12）：单独 import 时自己把 code/common 挂上 sys.path。
_COMMON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                       os.path.abspath(__file__)))), 'common')
if _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)

# 去注音、剥标签与 KANJI 都在 common（issue #5：strip_ruby_readings 正本收进 ruby_text）。
from htmltext import strip_tags                    # noqa: F401
from ruby_text import KANJI, strip_ruby_readings   # noqa: F401

# ============================================================================
# 正则（闸门与渲染共用；从 core6000_example.py 原样搬来，2026-11-02）
# ============================================================================
RE_BR2 = re.compile(r'<br\s*/?>\s*<br\s*/?>', re.I)
RE_BR1 = re.compile(r'<br\s*/?>', re.I)
RE_PBOUND = re.compile(r'</p>\s*<p\b[^>]*>', re.I)
RE_BLOCK = re.compile(r'<br\s*/?>\s*<br\s*/?>|</p>\s*<p\b[^>]*>', re.I)
RE_RUBY = re.compile(r'<ruby\b[^>]*>(.*?)</ruby>', re.S | re.I)
RE_RT = re.compile(r'<rt\b[^>]*>.*?</rt>', re.S | re.I)
RE_BR_ANY = re.compile(r'<br\s*/?>', re.I)
RE_SHELL = re.compile(r'</?(?:p|b|strong|em|i|h1|h2|h3|h4|h5|h6|ul|ol|div|span|font|center|'
                      r'table|thead|tbody|tr|td|th|blockquote)\b[^>]*>', re.I)
RE_MARKER = re.compile(r'<(h3|h4|h5|b|strong)\b[^>]*>(.*?)</\1\s*>', re.S | re.I)
# 裸写在一个 <p> 里的板块名（`<p>1. 中文翻译</p>`，没有 <b>）。
# 注意：标记扫描里**不能**把 `p` 放进 RE_MARKER 的候选里 —— finditer 是不重叠扫描，
# `<p><b>中文翻译</b>：正文</p>` 会被整个 <p> 吃掉，里面的 <b> 就再也扫不到（踩过）。
RE_PBLOCK = re.compile(r'<p\b[^>]*>(.*?)</p>', re.S | re.I)
RE_NUMBER = re.compile(r'^\s*[（(\[]?\s*(?:\d+|[一二三四五六七八九十]+)\s*[.、,，)）\]:：]\s*')
RE_LABEL_TAIL = re.compile(r'\s*[:：]\s*$')
RE_SPACES = re.compile(r'[ \t\u3000]{2,}')
RE_WS = re.compile(r'\s+')
RE_KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30a0-\u30ffー]+$')

# ---- 例句源（Jisho）的口径常量：随这块能力放在这里，巨石与 core6000_jisho 共用一份 ----
JISHO_DIR = ''                         # 按 noteId 缓存的候选目录；真值在巨石里按 WSP 拼，import 后注入
JISHO_MIN_SIMILARITY = 0.72            # 与第一句的相似度**上限**：再像就是换皮，换下一条
JISHO_SOURCE_FIELD = 'sentence_source'  # payload 里给模型看的键名

# not-merged 范围名（闸门 1 判「只在没合并的范围里出现」）：真值在巨石常量区，import 后注入。
SCOPE_MERGE = 'not-merged'

# ============================================================================
# 小工具：JSON / 文本（原 core6000_example.py 的「小工具」板块，2026-11-02 抽出）
# ============================================================================
def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1))


def read_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print('警告：读不出 %s（%s）' % (path, e), file=sys.stderr)
        return default


def flatten(text):
    """闸门用口径：整块删掉 <rt>…</rt>（读音），再剥标签，再去掉所有空白。"""
    return RE_WS.sub('', strip_ruby_readings(text or ''))


def plain(text):
    """人看的纯文本：去 ruby 读音、去标签、空白压成一个空格。"""
    return RE_WS.sub(' ', strip_ruby_readings(text or '')).strip()


def one_line(text, limit=120):
    t = plain(text)
    return t if len(t) <= limit else t[:limit] + '…'


def clean_malformed_ruby(html):
    """`<ruby><br>…風<rt>かぜ</rt></ruby>` 这类畸形注音：清掉基底里的 <br>。

    口径同 today_new.py::sentence_html_line（那里还会把 <br> 换成 ' / '，
    这里是字段重建，只清 ruby 内部的换行）。
    """
    def drop_br(m):
        return RE_BR_ANY.sub('', m.group(0))

    return RE_RUBY.sub(drop_br, html or '')


def strip_outer_wrappers(html):
    """剥掉最外层唯一的 <div …> / <p …> 外壳（只剥一层壳，不拆里面的块）。"""
    s = (html or '').strip()
    for _ in range(4):
        if (re.match(r'^<div\b', s, re.I) and re.search(r'</div>\s*$', s, re.I)
                and len(re.findall(r'<div\b', s, re.I)) == 1):
            s = re.sub(r'</div>\s*$', '', re.sub(r'^<div\b[^>]*>', '', s, count=1, flags=re.I),
                       flags=re.I).strip()
            continue
        if (re.match(r'^<p\b', s, re.I) and re.search(r'</p>\s*$', s, re.I)
                and len(re.findall(r'<p\b', s, re.I)) == 1):
            s = re.sub(r'</p>\s*$', '', re.sub(r'^<p\b[^>]*>', '', s, count=1, flags=re.I),
                       flags=re.I).strip()
            continue
        break
    return s


def count_blocks(text, rx=None):
    """按主分隔数块；先剥外壳、清畸形 ruby。

    `rx` 默认 `<br><br>` / `</p><p>`（`Sentence`、`Sentence Translation`）；
    `Sentence HTML` 传 `RE_BR1`——多句用**单个** `<br>` 分隔（2026-10-30 口径）。
    """
    core = strip_outer_wrappers(clean_malformed_ruby(text or ''))
    return len([x for x in (rx or RE_BLOCK).split(core) if flatten(x)])


def ruby_covers(html):
    """这块 HTML 是否给**所有汉字**都配了合规振假名（契约闸门 4 的口径）。

    * 每个 `<ruby>` 都必须有 `<rt>`；
    * ruby 基底不得只含假名（お/ご 这类敬语接头辞不能单独进基底）；
    * ruby 之外不能再有汉字（否则有汉字没注音）。
    """
    h = clean_malformed_ruby(html or '')
    if not h.strip():
        return False
    for inner in RE_RUBY.findall(h):
        if not re.search(r'<rt\b[^>]*>.*?</rt>', inner, re.S | re.I):
            return False
        base = strip_tags(RE_RT.sub('', inner)).strip()
        if not base or not KANJI.search(base):
            return False
        if RE_BR_ANY.search(base):
            return False
    return not KANJI.search(strip_tags(RE_RUBY.sub('', h)))


def block_needs_ruby(block):
    """去掉读音后仍有汉字 = 这块需要振假名。"""
    return bool(KANJI.search(strip_tags(RE_RT.sub('', block or ''))))


def block_ruby_ok(block):
    return (not block_needs_ruby(block)) or ruby_covers(block)


def split_sentence_html(html, n):
    """把 `Sentence HTML` 切成 n 块（逐块去外壳，返回内层 HTML）。

    依次试 `<br><br>` / `</p><p>` / 单个 `<br>`，取块数正好等于 n 的那一种；
    都不等 → None（= 不可用，走模型值）。
    """
    s = clean_malformed_ruby(html or '')
    if not flatten(s):
        return None
    core = strip_outer_wrappers(s)
    for rx in (RE_BR2, RE_PBOUND, RE_BR1):
        parts = [strip_outer_wrappers(x) for x in rx.split(core)]
        parts = [x for x in parts if flatten(x)]
        if len(parts) == n:
            return parts
    return None


def split_blocks(text):
    """按 `<br><br>` 切块（`Sentence` / `Sentence Translation` 用）。"""
    return [x.strip() for x in RE_BR2.split(text or '') if flatten(x)]


def join_blocks(text):
    """把字段里的多个块用标准 `<br><br>` 重新拼起来（内容是原来的）。"""
    return '<br><br>'.join(split_blocks(text))


def dedupe(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out
