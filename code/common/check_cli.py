# -*- coding: utf-8 -*-
"""check_* 脚本共用的输出骨架：读 JSON 列表 → 逐条 check → ★ 块 → 汇总行 → 退出码。

只抽 check_mine / check_proper 逐字相同的部分；check_cards 的「--anki 取数 + 不同汇总口径」
不走这里。业务判断（check 函数本身）仍留在各自的 check_*.py。
"""
from __future__ import annotations

import json
import sys

import textio  # noqa: F401  import 即接管 stdio 为 UTF-8

from llm_out import as_bool

HR = '=' * 70


def load_json_list(paths, encoding='utf-8'):
    """把若干 JSON 文件读成一个 list。读不了：打印「读不了 <path>：<exc>」并 SystemExit(2)。"""
    cards = []
    for p in paths:
        try:
            with open(p, encoding=encoding) as fh:
                cards.extend(json.load(fh))
        except Exception as exc:
            print('读不了 %s：%s' % (p, exc))
            raise SystemExit(2)
    return cards


def print_bad(bad, quiet=False):
    """bad: [(label, hard, soft)]。quiet=True 时不打印。"""
    if quiet:
        return
    for label, hard, soft in bad:
        print('★ %s' % label)
        for m in hard:
            print('    [不合格] %s' % m)
        for m in soft:
            print('    [提醒]   %s' % m)


def summary_line(total, include_count, bad_count):
    """「总计 N 条（收录 x / 排除 y）—— 合格 a / 不合格 b」。"""
    return ('总计 %d 条（收录 %d / 排除 %d）—— 合格 %d / 不合格 %d'
            % (total, include_count, total - include_count,
               total - bad_count, bad_count))


def run_files(argv, *, usage, check, label_of):
    """check_mine / check_proper 共用的 main。"""
    args = [a for a in argv if a != '--quiet']
    quiet = len(args) != len(argv)
    if not args:
        print(usage)
        raise SystemExit(2)
    cards = load_json_list(args)
    bad = []
    for c in cards:
        hard, soft = check(c)
        if hard:
            bad.append((label_of(c), hard, soft))
    print_bad(bad, quiet)
    print(HR)
    n_inc = sum(1 for c in cards if isinstance(c, dict) and as_bool(c.get('include')))
    print(summary_line(len(cards), n_inc, len(bad)))
    raise SystemExit(1 if bad else 0)