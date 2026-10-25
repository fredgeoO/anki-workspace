# -*- coding: utf-8 -*-
"""vocab_cover 子包的公共入口：路径、词表快照加载、第三方依赖引导。

第三方依赖（SudachiPy + SudachiDict、matplotlib）装在**工作区内**的
``data/pylibs``，不进系统环境。任何脚本 import 本模块即可获得 sys.path 修正。
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)), 'common'))
import paths as WSP  # noqa: E402

PYLIBS = os.path.join(WSP.DATA, 'pylibs')
DATA_DIR = os.path.join(WSP.DATA, 'vocab_cover')
STATE_JSON = os.path.join(DATA_DIR, 'vocab_state.json')
CORPUS_JSON = os.path.join(DATA_DIR, 'corpus_tokens.json')
OUT_CHARTS = os.path.join(WSP.OUTPUT, 'vocab_cover')


def add_pylibs() -> None:
    if PYLIBS not in sys.path:
        sys.path.append(PYLIBS)


def load_state(path: str = STATE_JSON) -> dict:
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def ensure_dirs() -> None:
    for d in (DATA_DIR, OUT_CHARTS, WSP.REPORTS):
        os.makedirs(d, exist_ok=True)


def write_json(obj, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False)
