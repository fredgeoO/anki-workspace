# -*- coding: utf-8 -*-
"""本地模型产出的**吸收层**：让"形状不对的回复"变成可诊断的一条硬错误，而不是崩掉整批。

为什么要有这个模块（2026-10 复盘）
----------------------------------
本地模型（qwen3.8-27b @ NInfer 4090）在阶段二/阶段四出错时，**大多数不是"判得不好"，
而是"回的东西形状不对"**，而脚本原来假设字段一定是字符串：

* `translation` 回成数字 `12` → `(x or '').strip()` 抛 `AttributeError` → **整批 gen 崩掉**
  （写好的那几条也一起丢，重跑要再花几分钟本地算力）
* `include` 回成字符串 `"false"` → 被当真值 → 该排除的词被收录进牌组
* `AINote` 回成数字 → 阶段二 `a.startswith('<p>')` 抛异常 → 一批 12 张全部作废
* 回复不是 JSON、少了外围对象、数组元素不是对象 → 同上一类

三条原则
--------
1. **非字符串一律当"没有这个字段"**（空串）：由校验器报成一条**明确的硬错误**
   （「XX 字段类型不是字符串」），而不是抛异常。
2. **每个判定组各自 try/except**：一组出意外只影响这一组（下一轮逐条重问），
   绝不带崩整批 —— 别让 1 张卡毁掉 12 张的成果。
3. **没判出来的原始回复必须落盘**（`dump_raw`）：不然事后无法回溯模型到底回了什么
   （2026-10-12 产出被写坏时就是因为没留原文，只能靠猜）。

调用方约定
----------
`as_text` / `as_bool` 在 `check_mine.py` 里也有同名再导出（历史调用点与新代码共用同一份实现）。
"""
from __future__ import annotations

import datetime as dt
import json
import os

TRUE_WORDS = ('true', '1', 'yes', 'y', 'on', '是', '真', '对')
FALSE_WORDS = ('false', '0', 'no', 'n', 'off', '否', '假', '错', '')


def as_text(v):
    """模型给的字段值 → 字符串。**非字符串一律当没有这个字段**（空串）。

    数字/列表/字典/布尔都不做隐式转换：模型把 `meaning` 写成 `12` 时，
    想要的是"这条字段不合格"，不是字符串 `'12'`（那会被当成合格释义写进卡里）。
    """
    return v if isinstance(v, str) else ''


def as_bool(v, default=False):
    """模型给的布尔 → `bool`。认识 `"false"`/`0`/`"否"` 这些常见写错法。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in TRUE_WORDS:
            return True
        if s in FALSE_WORDS:
            return False
    return default


def as_int(v, default=None):
    """模型给的数字 → `int`；转不了返回 `default`（不抛）。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def is_boolish(v):
    """这个值是不是**能被可靠解读**的布尔写法（`true`/`false`、`"false"`、`0`/`1`）。

    校验器用它把"模型把 include 写成了 `"收录"` 这种读不出来的东西"报成硬错误，
    而不是悄悄按 False（= 不收录）处理 —— 静默丢词和静默收词一样糟。
    """
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return v in (0, 1)
    if isinstance(v, str):
        return v.strip().lower() in TRUE_WORDS + FALSE_WORDS
    return False


def texts(rec, keys):
    """从一个 dict 里按 keys 取字段，全部按 `as_text` 归一 → 新 dict。"""
    rec = rec if isinstance(rec, dict) else {}
    return {k: as_text(rec.get(k)) for k in keys}


def dump_raw(dirpath, name, body, header=''):
    """把模型的原始回复落盘留证，返回写出的路径（失败返回 `None`，不抛异常）。

    `name` 不含扩展名；同名已存在时自动加 `-2`、`-3` 后缀，不覆盖旧证据。
    留证本身失败**不该反过来影响判定**，所以这里把异常全吃掉。
    """
    try:
        os.makedirs(dirpath, exist_ok=True)
        stem = os.path.join(dirpath, name)
        p, n = stem + '.txt', 2
        while os.path.exists(p):
            p, n = '%s-%d.txt' % (stem, n), n + 1
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write('# %s\n# 落盘时间：%s\n\n'
                     % (header or name,
                        dt.datetime.now().isoformat(timespec='seconds')))
            fh.write(body if isinstance(body, str) else json.dumps(
                body, ensure_ascii=False, indent=1))
        return p
    except Exception:
        return None


def raw_text(res):
    """从模型返回对象里取"原始文本"（不同调用路径字段名不一样）。"""
    if res is None:
        return '(没有拿到模型返回对象)'
    for attr in ('content', 'text', 'raw', 'body'):
        v = getattr(res, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    if isinstance(res, str):
        return res
    return '(返回对象里没有可读文本：%s)' % type(res).__name__
