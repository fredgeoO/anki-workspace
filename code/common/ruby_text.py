# -*- coding: utf-8 -*-
"""把 ``漢字[かんじ]`` 注音记法转成 HTML ``<ruby>``，以及反向取纯文本。

从 ``execution/today_new.py`` 抽出（2026-11-01）：这套解析只依赖正则与
``ruby_engine.wrap``，与 Anki/LLM 无关。``<ruby>`` 标签本身的构造统一走
:func:`ruby_engine.wrap`，这里不再手拼格式。
"""
import re

import ruby_engine as RE
from htmltext import strip_tags

KANJI = re.compile(r'[\u4e00-\u9fff]')
DOUBLE_KANA = re.compile(
    r'([\u3040-\u309f\u30a0-\u30ff])\s+(?=[\u3040-\u309f\u30a0-\u30ff])')


def _kana_or_space(ch):
    return ('\u3040' <= ch <= '\u309f') or ('\u30a0' <= ch <= '\u30ff') or ch in ' \u3000'


def _is_kanji(ch):
    # 汉字 + 々〆ヶ 这类汉字辅助字符（「次々[つぎつぎ]」的 々 要能进基底）
    return bool(KANJI.match(ch)) or ch in '\u3005\u3006\u30f6'


def strip_ruby_readings(text):
    """去注音：整块删掉 <rt>…</rt>（读法），再剥其余标签，<br> 变真换行。

    不能只 strip_tags：那样会留下读法，把「お<ruby>散歩<rt>さんぽ</rt></ruby>」
    变成「お散歩さんぽ」。原先住在 lesson_text，core6000_example 也要用（issue #5）。
    """
    t = re.sub(r'<rt>.*?</rt>', '', text or '', flags=re.S | re.I)
    return strip_tags(t)


def split_ruby(text):
    """把 漢字[かんじ] 记法拆成 [(基底, 读法), ...]，其余文字原样保留。

    基底向左扩展：先吃掉紧邻的汉字串（**允许汉字之间夹空格**，因为
    「どんなときどう使う」系列用空格给长词分词），再在**前导假名段里含空格**时
    多吃那一段（覆盖 彼[かの] 女[じょ] / 大[たい] 切[せつ]）。

    为什么要卡「假名段里必须有空格」：例句里满是「愛あっての結婚生活」这种写法——
    `の` 是词「あっての」的一部分，不是 `愛` 的读音。只有权威数据里
    「彼[かの] 女[じょ]」这种以空格分词的形态才值得向左吃假名，
    否则只吃汉字串（`は勝[か]` 里的 は 就不会被吃进基底）。
    """
    out, i = [], 0
    while i < len(text):
        j = text.find('[', i)
        if j < 0 or ']' not in text[j:]:
            out.append((text[i:], None))
            break
        k = text.find(']', j)
        if j == i:                      # 左边没有基底，当作普通文字
            out.append((text[i:k + 1], None))
            i = k + 1
            continue
        end = j - 1
        while end >= i and text[end] in ' \u3000':
            end -= 1
        if end < i or not _is_kanji(text[end]):
            out.append((text[i:k + 1], None))
            i = k + 1
            continue
        start = end
        while start - 1 >= i and (_is_kanji(text[start - 1]) or text[start - 1] in ' \u3000'):
            start -= 1
        if start - 1 >= i and _kana_or_space(text[start - 1]):
            m = start - 1
            while m - 1 >= i and _kana_or_space(text[m - 1]):
                m -= 1
            lead = text[m:start]
            if ' ' in lead or '\u3000' in lead:
                if m > i and _is_kanji(text[m - 1]):
                    start = m
        out.append((text[i:start], None))
        base = re.sub(r'[\s\u3000]+', '', text[start:end + 1])
        reading = re.sub(r'[\s\u3000]+', '', text[j + 1:k])
        out.append((base, reading))
        i = k + 1
    return out


def _extract_existing_ruby(text, store):
    """把已经带 <ruby> 的片段挖出来占位，返回替换后的文本。

    这类片段本身就是完整注音，必须原样保留——否则会被 strip_tags 连标签一起删掉，
    静默丢掉振假名。
    """
    def keep(m):
        store.append(m.group(0))
        return '\x00RUBY%d\x00' % (len(store) - 1)

    return re.sub(r'<ruby>.*?</ruby>', keep, text or '', flags=re.S | re.I)


def _put_back_ruby(text, store):
    for i, frag in enumerate(store):
        text = text.replace('\x00RUBY%d\x00' % i, frag)
    return text


def strip_ruby_base(text):
    """把 漢字[かんじ] 记法去掉读音，只留汉字原文（例句正文用）。"""
    store = []
    saved = _extract_existing_ruby(text, store)
    saved = strip_tags(saved)
    text = ''.join(base for base, _ in split_ruby(saved))
    text = _put_back_ruby(text, store)
    # 词典数据用空格给长词分词（「勝 ち 負 け」），假名之间的空格要收掉；
    # 词与词之间是真空格（至少一侧是汉字），保留。
    text = DOUBLE_KANA.sub(r'\1', text)
    return re.sub(r'[ \u3000]{2,}', ' ', text).strip()


def to_ruby(text):
    """把 漢字[かんじ] / <b>漢字[かんじ]</b> 记法转成 <ruby>漢字<rt>かんじ</rt></ruby>。

    用于例句正文，让讲义在浏览器/Markdown 预览里直接带假名。
    已经带 ruby 标签的内容原样保留（重复处理是幂等的）。
    """
    store = []
    saved = _extract_existing_ruby(text, store)
    saved = strip_tags(saved)
    pieces = []
    for base, reading in split_ruby(saved):
        pieces.append(RE.wrap(base, reading))
    out = ''.join(pieces)
    out = _put_back_ruby(out, store)
    out = DOUBLE_KANA.sub(r'\1', out)
    out = re.sub(r'</rt></ruby>[ \u3000]+(?=<ruby>)', '</rt></ruby>', out)   # 相邻 ruby 之间不留缝
    out = re.sub(r'\n{2,}', '\n', out)
    return re.sub(r'[ \u3000]{2,}', ' ', out).strip()


def plain_jp(text):
    """讲义里当纯文本用的日语：去标签、去注音、压缩空白、换行变空格。"""
    return re.sub(r'\s+', ' ', strip_ruby_base(text)).strip()
