# -*- coding: utf-8 -*-
"""HTML 文本清洗的最小公共实现：去标签、``<br>`` 转换行。

从 ``execution/today_new.py`` 抽出的第一块（2026-11-01）：这段逻辑被讲义/卡片
多处复用，且不依赖 Anki、LLM 或路径，适合放进 ``common/``。
"""
import re

TAG = re.compile(r'<[^>]+>')
BR = re.compile(r'<br\s*/?>', re.I)


def strip_tags(text):
    """去 HTML 标签，``<br>`` 变成真换行，保留其余文字。"""
    text = text or ''
    text = BR.sub('\n', text)
    text = TAG.sub('', text)
    return text
