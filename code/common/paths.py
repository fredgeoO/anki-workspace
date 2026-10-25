# -*- coding: utf-8 -*-
"""工作区路径的唯一来源 / single source of truth for workspace paths.

目录结构（详见根目录 README.md）::

    code/common      共享库（本模块、check_cards.py、check_mine.py）
    code/execution   执行区：多步流水线（阶段 0-5）与生成任务
    code/tools       工具区：可复用能力（edge-TTS、音频自检、回归测试）
    code/analysis    分析区：学习水平诊断、报告、学习量规划
    code/oneshot     单次执行区：跑一次就拿结果的脚本
    code/analysis/anki_analyze  离线诊断工具岛（自带词表与文本）
    temp/            **唯一**的一次性文件区：临时脚本、dump、日志、实验产出；
                     一件事做完用 ``python code/cli.py temp clean`` 一次清空
    docs/            手册、子代理规范、报告（docs/reports）
    data/            输入与中间产物（快照、缓存、各阶段工作目录）
    output/          生成物（i+1 提示词、合成音频）
    archive/         保留但不再维护的实验脚本

在 ``code/<area>/xxx.py`` 里这样引用::

    import os, sys
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
    import paths as WSP
"""
import os
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

# .../anki-workspace
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CODE = os.path.join(ROOT, 'code')
DOCS = os.path.join(ROOT, 'docs')
DATA = os.path.join(ROOT, 'data')
OUTPUT = os.path.join(ROOT, 'output')
# 唯一的一次性文件区（scratch）：任务做完就 `python code/cli.py temp clean` 清空
TEMP = os.path.join(ROOT, 'temp')

# ---- 代码区 ---------------------------------------------------------------
COMMON = os.path.join(CODE, 'common')
EXECUTION = os.path.join(CODE, 'execution')
TOOLS = os.path.join(CODE, 'tools')
ANALYSIS = os.path.join(CODE, 'analysis')
PLANNING = os.path.join(ANALYSIS, 'planning')
ONESHOT = os.path.join(CODE, 'oneshot')

# ---- 数据区 ---------------------------------------------------------------
SNAPSHOTS = os.path.join(DATA, 'snapshots')
DATA_PIPELINE = os.path.join(DATA, 'pipeline')   # 阶段 0-2 工作目录（原 ./gen）
DATA_VOCAB = os.path.join(DATA, 'vocab')         # 阶段 4 工作目录（原 ./gen_mine）
DATA_PLANS = os.path.join(DATA, 'plans')         # plan_activate_*.json
DATA_I1 = os.path.join(DATA, 'i1')               # gen_i1_cache.json
DATA_WEAK = os.path.join(DATA, 'weak')           # weak_words_2d.json
EVIDENCE = os.path.join(DATA, 'evidence')        # ep04_backup 等判定证据
# Core6000 例句补全（core6000_example.py）：状态、模型产出、token 账本、回退快照
DATA_CORE6000 = os.path.join(DATA, 'core6000')
# ImmersionKit 抓例句（immersionkit.py）：网络缓存 / 计划 / 本地媒体副本
DATA_IMMERSION = os.path.join(DATA, 'immersion')

# ---- 生成物 ---------------------------------------------------------------
OUT_I1 = os.path.join(OUTPUT, 'i1')
OUT_AUDIO = os.path.join(OUTPUT, 'audio')
OUT_AUDIO_CORE6000 = os.path.join(OUT_AUDIO, 'core6000')   # 例句②的 TTS 产物
REPORTS = os.path.join(DOCS, 'reports')

# ---- 共享文件 / 快照 ------------------------------------------------------
CHECK_CARDS = os.path.join(COMMON, 'check_cards.py')
CHECK_MINE = os.path.join(COMMON, 'check_mine.py')
DOC_JP_CARD = os.path.join(DOCS, 'jp-card-agent-instruction.md')
DOC_MINE_AGENT = os.path.join(DOCS, 'mine-agent-instruction.md')

SNAP_ANKISNAP = os.path.join(SNAPSHOTS, 'ankisnap', 'c.anki2')
SNAP_ANKISNAP2 = os.path.join(SNAPSHOTS, 'ankisnap2', 'c.anki2')
SNAP_ANKI_SNAP = os.path.join(SNAPSHOTS, '_anki_snap', 'collection.anki2')
SNAP_ANKI_SNAPSHOT_DB = os.path.join(SNAPSHOTS, 'anki_snapshot.db')
EP04_BACKUP = os.path.join(EVIDENCE, 'ep04_backup')

# 本地 Anki 资料夹（复制快照的来源）；可用环境变量 ANKI_PROFILE 覆盖
ANKI_PROFILE = os.environ.get(
    'ANKI_PROFILE',
    os.path.join(os.environ.get('APPDATA', ''), 'Anki2', '账户 1'))
LIVE_COLLECTION = os.path.join(ANKI_PROFILE, 'collection.anki2')


def ensure(*dirs):
    """Create the given directories (defaults to the writable workdirs)."""
    for d in dirs or (DATA_PIPELINE, DATA_VOCAB, DATA_PLANS, DATA_I1,
                      DATA_WEAK, OUT_I1, OUT_AUDIO, REPORTS,
                      DATA_CORE6000, OUT_AUDIO_CORE6000, DATA_IMMERSION):
        os.makedirs(d, exist_ok=True)
    return dirs


if __name__ == '__main__':
    for k in ('ROOT', 'CODE', 'DOCS', 'DATA', 'OUTPUT', 'SNAPSHOTS',
              'DATA_PIPELINE', 'DATA_VOCAB', 'DATA_PLANS', 'OUT_I1',
              'OUT_AUDIO', 'REPORTS'):
        print('%-16s %s' % (k, globals()[k]))
