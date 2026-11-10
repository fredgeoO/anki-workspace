# -*- coding: utf-8 -*-
"""共享格式化工具：百分比等常用渲染函数。"""


def pct(x, nd=1):
    return f'{x * 100:.{nd}f}%'