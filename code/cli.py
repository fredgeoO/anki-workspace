# -*- coding: utf-8 -*-
"""anki-workspace 统一入口（薄分发器）。

**本文件不含任何业务逻辑**：它只做「组 → 脚本」映射 + 参数原样透传，
子进程用同一个 Python 解释器（``sys.executable``），退出码原样回传。
需要改行为就改被调脚本，不要往这里加逻辑。

开工第一件事（强制门禁）::

    python code/cli.py doctor                       # Anki 开着时跑全套
    python code/cli.py doctor --skip-anki           # 离线（跳过需要 Anki 的检查）
    python code/cli.py doctor --tag "动画::<作品名>::<季>::第NN集"   # 并入技能 preflight

日常与每集流水线::

    python code/cli.py episode --tag "动画::<作品名>::<季>::第NN集" --input-tag 待标记
                                    # ★ 每集主线一条命令跑完阶段 2–5（默认演练，--commit 真写）
    python code/cli.py daily stats                  # tag「今天学习生词」今天命中多少
    python code/cli.py daily plan                   # 按 tag 取今天要讲的词
    python code/cli.py daily gen                    # 生成讲义（直连本地模型；没有 tag 就跳过）
    python code/cli.py today-new "字幕.srt" --n 30  # 今日 N 个生词（默认演练，--commit 真写）
    python code/cli.py pipeline prepare             # 阶段 0-2
    python code/cli.py pipeline triage --query "tag:待标记"
    python code/cli.py cards gen --note-id 123      # 单卡/数张：AINote + Sentence HTML（默认演练）
    python code/cli.py cards write --file fix.json --commit
    python code/cli.py activate apply --plan <路径> --commit   # 仅全局重排/历史回退用
    python code/cli.py mine scan --tag "动画::<作品名>::<季>::第NN集"
    python code/cli.py mine write --commit
    python code/cli.py audio plan

词汇分析与按需补例句::

    python code/cli.py vocab cover                  # 覆盖率报告（只暴露 4 个分析入口）
    python code/cli.py vocab newwords
    python code/cli.py vocab report
    python code/cli.py vocab mine_window --k 3
    python code/cli.py vocab reorder-jiten          # 管理 preset：全局词频序重排（默认演练）
    python code/cli.py core6000 gen --words "あまり,义理"
    python code/cli.py ainote enrich --word 分際 --commit   # 加强某张卡的 AINote + 语感
    python code/cli.py jisho --word "徹夜" --reading "てつや"  # 去 jisho 找真实例句（不造句）

ImmersionKit（按词表抓对白例句 + 素材卡，默认全程演练）::

    python code/cli.py immersion fetch  --words-file data\\immersion\\words.txt
    python code/cli.py immersion gen
    python code/cli.py immersion write  --to both --commit
    python code/cli.py immersion verify

弱项（第 5 项：五件套收成一个入口）::

    python code/cli.py weak today --days 3 --plain  # 近三天答得不好的卡的名字
    python code/cli.py weak revlog                  # 自评按钮校准（revlog 原始记录）
    python code/cli.py weak pace                    # 每牌组复习量 / 单卡耗时
    python code/cli.py weak build-list              # 汇总成「单词 —— 简释」清单

其它::

    python code/cli.py temp clean          # 清空一次性文件区 temp/（保留 README.md）
    python code/cli.py temp list           # 先看里面有什么（--dry-run 亦可）
    python code/cli.py backup --dest G:\\...        # 备份（Anki 必须先完全关闭）
    python code/cli.py list                         # 列出全部入口与实际脚本路径
    python code/cli.py <组> <子命令> -- <原样参数>  # ``--`` 之后不再被本文件解析
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, 'common'))          # paths / textio
sys.path.insert(0, os.path.join(_HERE, 'tools'))           # doctor 等工具
import paths as WSP  # noqa: E402  工作区路径的唯一来源
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

# ── 组 → 脚本映射（唯一需要维护的地方）──────────────────────────────────
EXEC = WSP.EXECUTION
AN = WSP.ANALYSIS
VOCAB_DIR = os.path.join(AN, 'vocab_cover')

GROUPS = {
    'episode':   os.path.join(EXEC, 'episode.py'),
    'daily':     os.path.join(EXEC, 'today_new.py'),
    'pipeline':  os.path.join(EXEC, 'pipeline.py'),
    'cards':     os.path.join(EXEC, 'cards.py'),
    'activate':  os.path.join(EXEC, 'activate.py'),
    'mine':      os.path.join(EXEC, 'mine.py'),
    'proper':    os.path.join(EXEC, 'proper.py'),
    'audio':     os.path.join(EXEC, 'mine_audio.py'),
    'core6000':  os.path.join(EXEC, 'core6000_example.py'),
    'meaning':   os.path.join(EXEC, 'core6000_meaning.py'),
    'ainote':    os.path.join(EXEC, 'ainote_enrich.py'),
    'jisho':     os.path.join(WSP.TOOLS, 'jisho_example.py'),
    'immersion': os.path.join(EXEC, 'immersionkit.py'),
    'doctor':    os.path.join(WSP.TOOLS, 'doctor.py'),
    'temp':      os.path.join(WSP.TOOLS, 'temp_clean.py'),
    'backup':    os.path.join(WSP.TOOLS, 'backup_anki.py'),
    'tagfreq':   os.path.join(WSP.TOOLS, 'tag_freq_stop.py'),
    'today-new': os.path.join(WSP.TOOLS, 'today_new_words.py'),
    'r':         os.path.join(AN, 'ankir.py'),
}

# 词汇分析：**只暴露这 4 个入口**，其余 ~20 个脚本仍可直接调用（不从这里走）
VOCAB = {
    'cover':       os.path.join(VOCAB_DIR, 'cover_cli.py'),
    'newwords':    os.path.join(VOCAB_DIR, 'newwords.py'),
    'report':      os.path.join(VOCAB_DIR, 'newword_report.py'),
    'mine_window': os.path.join(VOCAB_DIR, 'mine_window.py'),
}

# 弱项五件套
WEAK = {
    'today':  os.path.join(AN, 'today_weak.py'),
    'revlog': os.path.join(AN, 'analyze_revlog.py'),
    'pace':   os.path.join(AN, 'anki_revlog_analysis.py'),
}
WEAK_CHAIN = {
    # 两步链：先出数据，再汇总成清单
    'build-list': [os.path.join(AN, 'weak_words_2d_live.py'),
                   os.path.join(AN, 'make_weak_list.py')],
}

# ── Jiten 全局词频序重排 preset ────────────────────────────────────────
# 这里包死的三个开关，是 2026-10 实测口径（docs/architecture.md §5 / freq_external.py docstring）：
#   * make_activate_plan 必须 --all-cards + 排除例句卡组，否则计划覆盖不到全部词汇卡
#   * activate apply 必须 --global，跨卡组连续编号才能得到同一个全局顺序
JITEN_MEDIA = 'Anime'
JITEN_TAG = 'jiten'
JITEN_EXCLUDE_DECKS = '0-日本语学习::2-例句'
JITEN_WORDS = os.path.join(WSP.DATA, 'vocab_cover', 'study_plan_jiten_%s.json'
                           % JITEN_MEDIA.lower())
JITEN_PLAN = os.path.join(WSP.DATA_PLANS, 'plan_activate_%s.json' % JITEN_TAG)


def _run(script, args, label=None):
    """跑一个兄弟脚本，stdio 直接继承（进度实时可见、可交互）。

    用 ``textio.run`` 是为了拿到修好的子进程环境（UTF-8），
    显式传 ``stdout=None/stderr=None`` 覆盖它的默认 PIPE，避免把长输出全缓冲起来。
    """
    if not os.path.exists(script):
        print('❌ 找不到脚本：%s' % script)
        return 2
    cmd = [sys.executable, script] + [str(x) for x in args]
    print('→ %s%s' % (label or os.path.relpath(script, WSP.ROOT),
                      (' ' + ' '.join(str(x) for x in args)) if args else ''))
    sys.stdout.flush()      # 输出被重定向/管道时是块缓冲：先冲刷，否则这行会跑到子进程输出后面
    proc = textio.run(cmd, stdout=None, stderr=None)
    return proc.returncode


def _chain(steps, args_per_step):
    """按顺序跑多步，任一步非 0 就停并回传该退出码。"""
    for (script, label), args in zip(steps, args_per_step):
        rc = _run(script, args, label)
        if rc != 0:
            return rc
    return 0


def cmd_vocab(rest):
    if not rest:
        print('vocab 入口（4 个分析入口 + 1 个管理 preset）：')
        for k in VOCAB:
            print('  %-12s %s' % (k, os.path.relpath(VOCAB[k], WSP.ROOT)))
        print('  %-12s %s' % ('reorder-jiten', '全局词频序重排（默认演练，--commit 真写）'))
        return 0
    entry, args = rest[0], rest[1:]
    if entry in VOCAB:
        return _run(VOCAB[entry], args)
    if entry in ('reorder-jiten', 'reorder_jiten'):
        return cmd_jiten(args)
    print('❌ 未知 vocab 入口：%s' % entry)
    print('   可用：%s、reorder-jiten' % '、'.join(VOCAB))
    print('   （其余 vocab_cover 脚本请直接调用：%s）'
          % os.path.relpath(VOCAB_DIR, WSP.ROOT))
    return 2


def cmd_weak(rest):
    if not rest:
        print('weak 入口：')
        for k in WEAK:
            print('  %-12s %s' % (k, os.path.relpath(WEAK[k], WSP.ROOT)))
        for k, scripts in WEAK_CHAIN.items():
            print('  %-12s %s' % (k, ' → '.join(os.path.relpath(s, WSP.ROOT)
                                                for s in scripts)))
        return 0
    mode, args = rest[0], rest[1:]
    if mode in WEAK:
        return _run(WEAK[mode], args)
    if mode in WEAK_CHAIN:
        # 只有第一步吃参数（可选的快照路径）；第二步 make_weak_list.py 不接参数
        scripts = WEAK_CHAIN[mode]
        steps = [(s, os.path.relpath(s, WSP.ROOT)) for s in scripts]
        return _chain(steps, [args] + [[] for _ in scripts[1:]])
    print('❌ 未知 weak 模式：%s' % mode)
    print('   可用：%s、%s' % ('、'.join(WEAK), '、'.join(WEAK_CHAIN)))
    return 2


def _backup_existing_plan():
    """重排前把现有计划文件留一份。

    为什么：``plan_activate_jiten.json`` 是**上一次重排的唯一回退依据**
    （里面存着每张卡的 ``due_before``）。这一跑会把它覆盖掉，所以先另存一份。
    备份放 ``data/plans/_prev/`` 子目录 —— ``activate.py:latest_plan()`` 只 glob
    本层 ``plan_activate*.json``，不会把备份当成"最近那份计划"。
    """
    if not os.path.exists(JITEN_PLAN):
        return None
    import datetime as _dt
    import shutil
    prev_dir = os.path.join(WSP.DATA_PLANS, '_prev')
    os.makedirs(prev_dir, exist_ok=True)
    base = os.path.basename(JITEN_PLAN)
    stamp = _dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    out = os.path.join(prev_dir, '%s.prev-%s' % (os.path.splitext(base)[0], stamp)
                       + os.path.splitext(base)[1])
    shutil.copy2(JITEN_PLAN, out)
    print('已备份上一份计划（回退依据）：%s' % os.path.relpath(out, WSP.ROOT))
    return out


def cmd_jiten(rest):
    """全局词频序重排：build → make_activate_plan → activate apply → field。

    默认**全链演练**（不写库、不写字段）；``--commit`` 才真写。
    第 2 步会覆盖 ``plan_activate_jiten.json``，所以覆盖前先备份到 ``data/plans/_prev/``。
    """
    ap = argparse.ArgumentParser(prog='cli.py vocab reorder-jiten',
                                 description='Jiten 动漫词频序重排 preset（默认演练）')
    ap.add_argument('--commit', action='store_true', help='真写库（位置 + 字段）；不加则只演练')
    ap.add_argument('--skip-build', action='store_true',
                    help='跳过第 1 步（复用现有 %s）' % os.path.relpath(JITEN_WORDS, WSP.ROOT))
    ap.add_argument('--skip-field', action='store_true',
                    help='跳过第 4 步（不写 JitenAnimeRank 字段，只重排位置）')
    a = ap.parse_args(rest)

    print('=' * 88)
    print('Jiten 全局词频序重排 ｜ 模式：%s' % ('★ 真写库' if a.commit else '演练（不写库）'))
    print('  词表：%s' % os.path.relpath(JITEN_WORDS, WSP.ROOT))
    print('  计划：%s' % os.path.relpath(JITEN_PLAN, WSP.ROOT))
    print('  包死的开关：--all-cards、--exclude-decks "%s"、--global' % JITEN_EXCLUDE_DECKS)
    print('=' * 88)

    freq = os.path.join(VOCAB_DIR, 'freq_external.py')
    mkplan = os.path.join(VOCAB_DIR, 'make_activate_plan.py')
    activate = GROUPS['activate']

    n = 0
    if not a.skip_build:
        n += 1
        print('\n[%d/4] 由本地 Jiten CSV 生成词表（只读本地文件，不连网）' % n)
        rc = _run(freq, ['build', '--media', JITEN_MEDIA], 'freq_external.py')
        if rc != 0:
            return rc
    else:
        print('\n[1/4] 已跳过 build（--skip-build）')

    print('\n[2/4] 生成 activate 计划（--all-cards + 排除例句卡组）')
    _backup_existing_plan()
    rc = _run(mkplan, ['--words-file', JITEN_WORDS, '--tag', JITEN_TAG,
                       '--all-cards', '--exclude-decks', JITEN_EXCLUDE_DECKS],
              'make_activate_plan.py')
    if rc != 0:
        return rc

    print('\n[3/4] 按计划重排新卡位置（--global）')
    apply_args = ['apply', '--plan', JITEN_PLAN, '--global']
    if a.commit:
        apply_args.append('--commit')
    rc = _run(activate, apply_args, 'activate.py')
    if rc != 0:
        return rc

    if a.skip_field:
        print('\n[4/4] 已跳过字段写入（--skip-field）')
    else:
        print('\n[4/4] 把 freq_rank 写成笔记字段 JitenAnimeRank（注解用，不参与排序）')
        field_args = ['field', '--plan', JITEN_PLAN]
        if a.commit:
            field_args.append('--commit')
        rc = _run(freq, field_args, 'freq_external.py')
        if rc != 0:
            return rc

    print()
    if a.commit:
        print('完成：位置与字段已真写。回退用 activate.py revert --plan %s --commit' % JITEN_PLAN)
    else:
        print('演练结束，未写任何数据。确认无误后加 --commit 重跑。')
    return 0


def _print_help():
    print('anki-workspace 统一入口 —— python code/cli.py <组> <子命令> [参数...]')
    print()
    print('  doctor    开工体检（强制门禁）      doctor --skip-anki / --tag "动画::…"')
    print('  episode   ★ 每集主线驱动（阶段 2-5） --tag "动画::…" --input-tag 待标记')
    print('  daily     每日讲义（tag 今天学习生词）  stats | models | plan | check | gen | merge | prompt')
    print('  pipeline  阶段 0-2                  prepare | triage | apply | split | verify | write')
    print('  cards     按张生成 AINote+HTML      gen | write（默认演练，--commit 真写）')
    print('  activate  全局重排 / 历史回退      plan | apply | revert')
    print('  mine      阶段 4（素材生词）        scan | split | verify | write')
    print('  proper    专有名词收集（3-专有词汇）model | scan | gen | write | audio | add')
    print('  audio     阶段 5（生词配音）        plan | apply | …')
    print('  core6000  按需补例句②               gen | tts | apply | revert')
    print('  ainote    加强 AINote 讲解（含语感） show | gen | apply | enrich | revert')
    print('  jisho     去 jisho.org 找真实例句     --word <词> [--reading <假名>]')
    print('  immersion ImmersionKit 抓例句       fetch | gen | write | verify')
    print('  vocab     词汇分析 + 词频序重排     %s | reorder-jiten' % ' | '.join(VOCAB))
    print('  weak      弱项五件套                %s | %s'
          % (' | '.join(WEAK), ' | '.join(WEAK_CHAIN)))
    print('  r         ankiR（R 包）分析报告      list | summary | report | health | weak | call | plot')
    print('  temp      一次性文件区（唯一）      list | clean | path')
    print('  tagfreq   按 Jiten 名次打词频分档标签 --stop 12000 --ceiling 24000（默认演练）')
    print('  backup    备份到 G: 盘              --dest <路径>')
    print('  list      列出全部入口与实际脚本路径')
    print()
    print('参数原样透传给被调脚本；``--`` 之后不再被本文件解析。')
    print('子脚本自己的帮助：python code/cli.py <组> --help')


def cmd_list():
    print('组 → 脚本（存在性检查）')
    print('-' * 88)
    rows = list(GROUPS.items()) + [('vocab:' + k, v) for k, v in VOCAB.items()]
    rows += [('weak:' + k, v) for k, v in WEAK.items()]
    for k, v in WEAK_CHAIN.items():
        for s in v:
            rows.append(('weak:' + k, s))
    rows.append(('preset', 'vocab reorder-jiten'))
    for name, script in rows:
        if name == 'preset':
            print('  %-24s %s' % (name, script))
            continue
        mark = 'ok ' if os.path.exists(script) else '❌ '
        print('  %s%-21s %s' % (mark, name, os.path.relpath(script, WSP.ROOT)))
    print()
    print('未纳入统一入口的脚本仍可直接调用（如 %s）'
          % os.path.relpath(VOCAB_DIR, WSP.ROOT))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        _print_help()
        return 0

    group, rest = argv[0], argv[1:]
    if rest and rest[0] == '--':          # 允许显式分隔
        rest = rest[1:]

    if group == 'list':
        return cmd_list()
    if group == 'vocab':
        return cmd_vocab(rest)
    if group == 'weak':
        return cmd_weak(rest)
    if group in ('jiten', 'reorder-jiten'):   # 顶层别名
        return cmd_jiten(rest)
    if group in GROUPS:
        return _run(GROUPS[group], rest)

    print('❌ 未知入口：%s' % group)
    print()
    _print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
