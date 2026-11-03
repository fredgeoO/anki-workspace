# -*- coding: utf-8 -*-
"""每日讲义的落盘路径与原子写：`today_new` 与 `lesson_render` **共用**的一层。

从 ``execution/today_new.py`` 抽出（2026-11-02，Issue #4）。抽它不是为了少几行，
而是为了**断掉循环 import**：讲义渲染要用 ``dated_paths`` / ``write_text`` /
``LESSON_BACKUP`` / ``TAG_TODAY``，而 ``today_new`` 又要用渲染——两头直接互引就成了
``today_new`` ↔ ``lesson_render``。把这几个常量与路径函数放到谁都不依赖业务模块的
这一层，依赖就变成单向：

    today_new ──> lesson_render ──┐
       └────────> lesson_paths <──┘

口径一字未改：文件名、目录、原子写（先 ``.tmp`` 再 ``os.replace``）都是原来的。
"""
import json
import os
import sys

# 系列子目录（issue #12）：单独 import 时自己把 code/common 挂上 sys.path。
_COMMON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                       os.path.abspath(__file__)))), 'common')
if _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)

import paths as WSP

OUTDIR = os.path.join(WSP.OUTPUT, 'daily')
LESSON_DIR = os.path.join(OUTDIR, 'lessons')
CARDS_DIR = os.path.join(LESSON_DIR, 'cards')          # 每个请求一个 NN_out.json

# 今天这批词的 tag（由 jp-anki-today-new 从当天字幕选出、全量替换）。
TAG_TODAY = '今天学习生词'

LESSON_BACKUP = True       # 写讲义前把已有讲义改名为 .bak


def dict_path(date):
    return os.path.join(LESSON_DIR, 'dict_%s.json' % date)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1))


def dated_paths(date):
    return {
        'cards': os.path.join(OUTDIR, 'cards_%s.json' % date),
        'cards_latest': os.path.join(OUTDIR, 'cards_latest.json'),
        'lesson_json': os.path.join(LESSON_DIR, 'lesson_%s.json' % date),
        'lesson_md': os.path.join(OUTDIR, 'lesson_%s.md' % date),
        'lesson_latest': os.path.join(OUTDIR, 'lesson_latest.md'),
        'split': os.path.join(LESSON_DIR, 'split_%s.json' % date),
        'metrics': os.path.join(LESSON_DIR, 'metrics_%s.json' % date),
        'dict': dict_path(date),
    }
