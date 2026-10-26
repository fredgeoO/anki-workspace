# -*- coding: utf-8 -*-
"""极简 HTML 树（标准库 ``html.parser``），顶替环境里缺失的 lxml。

为什么有这个模块
----------------
``code/tools/jisho_example.py`` 解析 Jisho 的例句页只需要 lxml 的一小撮能力：
``fromstring`` / ``tostring`` / ``text_content()`` / ``iterchildren()`` /
``getparent().remove()``，以及**本工作区用到的几种 xpath**。但 ``data/pylibs`` 里没有
lxml（也不许 pip install），于是给它一个只实现这一小撮能力的替身：装的库没有、
行为对不上时报错要显式，不静默降级。

支持的选择器（就是 jisho_example 用到的那几种，别的会抛 ``NotImplementedError``）::

    //div[contains(@class,"x")]//h4
    //li[contains(@class,"a") and contains(@class,"b")]
    .//a[contains(@class,"x")]/@href
    .//span[contains(@class,"a") or contains(@class,"b")]
    .//span[contains(@class,"furigana")]

节点结构与 lxml 一致：``node.text`` 是首个子元素之前的文本，``node.tail`` 是元素结束
之后的文本，``node.children`` 只放元素节点。
"""
from __future__ import annotations

import html as html_mod
import os
import re
import sys
from html.parser import HTMLParser

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio  # noqa: E402,F401  UTF-8 stdio 唯一入口（textio audit 要求）

VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'area', 'base', 'col',
        'embed', 'source', 'track', 'wbr'}


class Node(object):
    __slots__ = ('tag', 'attrs', 'parent', 'children', 'text', 'tail')

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.parent = parent
        self.children = []          # 只放 Node
        self.text = None
        self.tail = None

    # ---- lxml 兼容的最小接口 ------------------------------------------------
    def getparent(self):
        return self.parent

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    @property
    def classes(self):
        return (self.attrs.get('class') or '').split()

    def iterchildren(self):
        for ch in self.children:
            yield ch

    def remove(self, child):
        self.children = [c for c in self.children if c is not child]
        child.parent = None

    def text_content(self):
        parts = [self.text or '']

        def walk(node):
            for ch in node.children:
                parts.append(ch.text or '')
                walk(ch)
                parts.append(ch.tail or '')

        walk(self)
        return ''.join(parts)

    def descendants(self, tag=None):
        out = []
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            if tag is None or node.tag == tag:
                out.append(node)
            stack.extend(reversed(node.children))
        return out

    def xpath(self, expr):
        scope = self
        rest = expr.strip()
        if rest.startswith('.//'):
            rest = rest[1:]                      # .//x 与 //x 在本文档里同义（禁止查 self）
        if not rest.startswith('//'):
            raise NotImplementedError(expr)
        rest = rest[2:]
        attr = ''
        m_attr = re.search(r'/(@[\w:-]+)$', rest)
        if m_attr:
            attr = m_attr.group(1)[1:]
            rest = rest[:m_attr.start()]
        steps = rest.split('//')
        found = [scope]
        last = None
        for step in steps:
            m = re.match(r'^(\w+)(\[.*\])?$', step)
            if not m:
                raise NotImplementedError(expr)
            tag, pred = m.group(1), m.group(2) or ''
            classes, need_all, need_any = _parse_pred(pred, expr)
            nxt = []
            for node in found:
                for cand in node.descendants(tag):
                    if _class_ok(cand, classes, need_all, need_any):
                        nxt.append(cand)
            found, last = nxt, nxt
        if attr:
            return [n.attrs[attr] for n in last if attr in n.attrs]
        return last


def _parse_pred(pred, expr):
    """``[contains(@class,"a") and contains(@class,"b")]`` → (类名列表, all?, any?)。"""
    if not pred:
        return [], False, False
    body = pred[1:-1]
    classes = re.findall(r'contains\(@class\s*,\s*"([^"]+)"\)', body)
    if not classes:
        raise NotImplementedError(expr)
    if ' and ' in body:
        return classes, True, False
    if ' or ' in body:
        return classes, False, True
    return classes, False, False


def _class_ok(node, classes, need_all, need_any):
    if not classes:
        return True
    raw = node.attrs.get('class') or ''
    got = raw.split()
    if need_all:
        return all(c in got for c in classes)
    if need_any:
        return any(c in got for c in classes)
    return classes[0] in got


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('#document')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, attrs, parent=self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not data:
            return
        top = self.stack[-1]
        if top.children:
            last = top.children[-1]
            last.tail = (last.tail or '') + data
        else:
            top.text = (top.text or '') + data


def fromstring(content):
    """HTML 文本/字节 → 根节点（与 lxml 一样，单个顶层元素时返回那个元素）。"""
    if isinstance(content, (bytes, bytearray)):
        content = bytes(content).decode('utf-8', 'replace')
    builder = _Builder()
    builder.feed(content)
    builder.close()
    top = builder.root.children
    if len(top) == 1:
        return top[0]
    return builder.root


def tostring(node, encoding='unicode'):
    """节点 → HTML 字符串（属性不还原，只保留 jisho_example 需要的结构）。"""
    buf = []

    def emit(n):
        buf.append('<' + n.tag)
        for key, value in n.attrs.items():
            buf.append(' %s="%s"' % (key, html_mod.escape(value or '', quote=True)))
        buf.append('>')
        if n.text:
            buf.append(html_mod.escape(n.text))
        for ch in n.children:
            emit(ch)
        buf.append('</%s>' % n.tag)
        if n.tail:
            buf.append(html_mod.escape(n.tail))

    emit(node)
    return ''.join(buf)


if __name__ == '__main__':
    doc = fromstring('<ul class="japanese_sentence"><li><span class="unlinked">私</span></li>。<br></ul>')
    print(doc.text_content().strip())
    print(tostring(doc)[:80])
