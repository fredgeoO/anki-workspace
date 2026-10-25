# -*- coding: utf-8 -*-
"""字幕覆盖率与词汇量报告：**自动刷新数据链** -> 图表 PNG + Markdown 报告。

一条命令跑完（默认自动发现新字幕、自动重取卡组快照）::

    python code/analysis/vocab_cover/report_build.py

自动刷新（``--refresh auto``，默认）
----------------------------------
* **字幕**：用 ``corpus.discover()`` 扫 ``subtitles/``（跳过 ``anki/`` 等「制作卡牌用」的裁剪版）。
  逐集比「相对路径 + 文件内容 sha1 + 词表 sha1」的缓存键 —— 新加一集、改一集、删一集都会在这里被发现，
  然后只重算变了的那几集（``corpus.build()``）。
* **卡组**：AnkiConnect 可达时重取卡组快照（``collect_vocab.collect()``）。core6000 / 考级词汇是
  **固定词表**（不会增长）；会持续长的只有「素材生词 + 例句」（mined）。快照内容没变就不重写文件，
  以免白白让语料缓存失效。
* **指标**：``metrics.json`` 里记的语料/卡组时间戳与当前对不上就重算（``metrics.compute()``）。

报告正文**不写死任何语料规模**：集数、作品数、小时数、每部集数、卡组词条数、目标档位、
逐集明细、可用脚本清单都由 ``metrics.json`` / ``corpus_tokens.json`` / 目录现场算出 ——
加一部新番、加几集字幕、素材卡涨了，重跑同一条命令即可。

用法::

    python code/analysis/vocab_cover/report_build.py                  # 自动刷新 + 出图 + 出报告
    python code/analysis/vocab_cover/report_build.py --refresh never  # 只用现有 json，不重算
    python code/analysis/vocab_cover/report_build.py --force          # 字幕忽略缓存全量重算
    python code/analysis/vocab_cover/report_build.py --anki never     # 不连 Anki，用现有卡组快照
    python code/analysis/vocab_cover/report_build.py --no-charts       # 只出 Markdown
    python code/analysis/vocab_cover/report_build.py --prune           # 顺带清掉不再需要的语料缓存
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import hashlib
import json
import math
import os
import statistics
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _deps import (CORPUS_JSON, DATA_DIR, OUT_CHARTS, STATE_JSON, WSP,  # noqa: E402
                   add_pylibs, ensure_dirs)
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

add_pylibs()

METRICS = os.path.join(DATA_DIR, 'metrics.json')
REPORT = os.path.join(WSP.REPORTS, '字幕覆盖率与词汇量报告.md')
REL_IMG = os.path.relpath(OUT_CHARTS, WSP.REPORTS).replace('\\', '/')

# ------------------------------------------------------------------ 配色 / 显示名
CORE = '#2b6cb0'
JLPT = '#3182ce'
MINED = '#63b3ed'
OOV = '#e53e3e'
PROPER = '#dd6b20'
KNOWN = '#2f855a'
MATURE = '#276749'
GREY = '#a0aec0'
PALETTE = [CORE, JLPT, MINED, '#805ad5', KNOWN, PROPER, OOV, '#38a169',
           '#d69e2e', '#00a3c4', '#b83280', '#4a5568']

# 逻辑卡组 -> 中文显示名（metrics.json 的 deck 键变了也不用改这里，会用键名兜底）
DECK_LABEL = {'core6000': 'core6000', 'jlpt': '考级词汇', 'mined': '素材生词'}
DECK_COLOR = {'core6000': CORE, 'jlpt': JLPT, 'mined': MINED}
FIXED_DECKS = {'core6000', 'jlpt'}          # 固定词表：不会增长
BUCKET_LABEL = {'core6000': 'core6000 内', 'jlpt': '考级词汇内', 'mined': '素材生词内',
                'oov': '卡组外实词', 'proper': '专有名词', 'interj': '感动词',
                'numeral': '数词'}
BUCKET_ADVICE = {'core6000': '要（你卡组里有）', 'jlpt': '要（你卡组里有）',
                 'mined': '要（已挖出）', 'oov': '**要（卡组没有）**',
                 'proper': '不用背，看剧情自然学会', 'interj': '不用背，属听力反应',
                 'numeral': '不用背'}
BUCKET_ORDER = ['core6000', 'jlpt', 'mined', 'oov', 'proper', 'interj', 'numeral']

# 一次性抽检得到的数字：**不会随语料自动更新**，所以带上抽检日期，免得被当成现值。
BIAS_AUDIT = ('（%s 抽检）实测「读音能对上卡组、只是写法不同」的词元约占需背实词的 1.4%%，'
              '480 个疑似中抽检约一半是真命中。' % '2026-10-07')

_STATE_CACHE = None      # 卡组快照的进程内缓存（刷新后由 refresh_anki_state 覆盖）


# ------------------------------------------------------------------ 小工具
def pct(x, nd=1) -> str:
    return f'{x * 100:.{nd}f}%'


def deck_label(key: str) -> str:
    return DECK_LABEL.get(key, key)


def deck_color(key: str, i: int = 0) -> str:
    return DECK_COLOR.get(key, PALETTE[i % len(PALETTE)])


def color_at(i: int) -> str:
    return PALETTE[i % len(PALETTE)]


def group_blocks(rows: list, key: str = 'work') -> list:
    """-> [(work, [row, ...]), ...]，保持 rows 里第一次出现的作品顺序。"""
    out, index = [], {}
    for r in rows:
        w = r.get(key, '')
        if w not in index:
            index[w] = len(out)
            out.append((w, []))
        out[index[w]][1].append(r)
    return out


def deck_keys(m: dict) -> list:
    """metrics 里出现过的逻辑卡组（保持 by_deck 的顺序，未知键也带上）。"""
    order = [k for k in ('core6000', 'jlpt', 'mined') if k in m['deck'].get('by_deck', {})]
    extra = [k for k in m['deck'].get('by_deck', {}) if k not in order]
    return order + sorted(extra)


def bucket_keys(mb: dict) -> list:
    return ([k for k in BUCKET_ORDER if k in mb]
            + [k for k in sorted(mb) if k not in BUCKET_ORDER])


def vocab_targets(m: dict) -> list:
    """-> [(覆盖率, 指标名, 词数)]，从 freq_curve 的 V90/V95/V98/V99 动态读。"""
    out = []
    for k, v in m['freq_curve'].items():
        if len(k) > 1 and k[0] == 'V' and k[1:].isdigit():
            out.append((int(k[1:]) / 100.0, k, v))
    return sorted(out)


def top_cover_points(m: dict) -> list:
    """-> [(N, 覆盖率)]，从 freq_curve 的 topN_cover 动态读（N 升序）。"""
    fx = m['freq_curve']
    out = []
    for k, v in fx.items():
        if k.startswith('top') and k.endswith('_cover') and k[3:-6].isdigit():
            out.append((int(k[3:-6]), v))
    return sorted(out)


def goal_targets(m: dict, want=(0.95, 0.98)) -> list:
    """挑最接近 0.95 / 0.98 的目标档（metrics 的档位变了也不会 KeyError）。"""
    ts = sorted(g['target'] for g in m.get('target_gap', []))
    out = []
    for w in want:
        if not ts:
            break
        pick = min(ts, key=lambda x: abs(x - w))
        if pick not in out:
            out.append(pick)
    return out


def episodes_per_work(m: dict) -> float:
    """本语料「一部作品多少集」的中位数（估计「还要看几部」时用）。"""
    ns = [p['episodes'] for p in m.get('per_work', {}).values() if p.get('episodes')]
    return float(statistics.median(ns)) if ns else 12.0


def series_estimate(m: dict) -> list:
    """按「还缺多少词 / 每部新番的净产量」估还要看多少部。"""
    learn_sizes = list(m['cross_work']['learn_sizes'].values())
    mc = m['corpus_vocab_mastery']['by_bucket_types']
    total_types = sum(mc.values())
    oov_share = (mc.get('oov', 0) / total_types) if total_types else 0.4
    per_work = (sum(learn_sizes) / len(learn_sizes)) if learn_sizes else 0.0
    per_work_learn = per_work * oov_share
    epw = episodes_per_work(m)
    opts = []
    for g in m['target_gap']:
        missing = g['missing']
        hi = missing / (per_work_learn * 1.2) if per_work_learn else 0.0
        lo = missing / (per_work_learn * 0.6) if per_work_learn else 0.0
        opts.append({
            'target': g['target'], 'missing': missing,
            'missing_in_deck': g['missing_in_deck'], 'missing_oov': g['missing_oov'],
            'per_work_types': per_work, 'per_work_learnable': per_work_learn,
            'episodes_per_work': epw,
            'series_optimistic': hi, 'series_conservative': lo,
            'episodes_optimistic': hi * epw, 'episodes_conservative': lo * epw,
            'median_first_seen_episode': g.get('first_seen_median_episode'),
        })
    return opts


# ------------------------------------------------------------------ 自动刷新
def _anki_call(action: str, timeout: float = 4.0, **params):
    url = os.environ.get('ANKICONNECT_URL', 'http://127.0.0.1:8765')
    payload = json.dumps({'action': action, 'version': 6, 'params': params}).encode('utf-8')
    req = urllib.request.Request(url, data=payload,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        body = json.loads(fh.read().decode('utf-8'))
    if body.get('error'):
        raise RuntimeError(f'AnkiConnect {action}: {body["error"]}')
    return body.get('result')


def anki_reachable(timeout: float = 4.0) -> bool:
    try:
        _anki_call('version', timeout=timeout)
        return True
    except Exception:
        return False


def _state_fingerprint(state: dict) -> str:
    """卡组快照的「内容指纹」：忽略 generated_at，只比真正影响统计的部分。"""
    blob = json.dumps({'decks': state.get('decks'), 'words': state.get('words'),
                       'affixes': state.get('affixes')},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode('utf-8')).hexdigest()


def refresh_anki_state() -> tuple:
    """重取 Anki 卡组快照。-> (是否变化, 说明文字)"""
    global _STATE_CACHE
    import collect_vocab as cv
    state = cv.collect()
    old = textio.load_json(STATE_JSON, default=None)
    if isinstance(old, dict) and old.get('words'):
        if _state_fingerprint(old) == _state_fingerprint(state):
            # 只是 generated_at 变了：不重写文件，语料缓存因此保持有效
            _STATE_CACHE = old
            return False, ('卡组快照无实质变化（沿用 %s）'
                           % old.get('generated_at', '-'))
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_JSON, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False)
    _STATE_CACHE = state
    st = state.get('decks', {})
    detail = '、'.join('%s %d 条' % (deck_label(k), st[k].get('notes', 0))
                       for k in st) if st else '无卡组'
    return True, ('卡组快照已刷新（%s；%s）'
                  % (state.get('generated_at', '-'), detail))


def _load_corpus_json() -> dict:
    return textio.load_json(CORPUS_JSON, default={}) or {}


def _corpus_reason() -> str:
    """语料是否需要重算（空串 = 不需要）。判定与 corpus.py 的缓存键完全一致。"""
    if not os.path.exists(CORPUS_JSON):
        return 'corpus_tokens.json 不存在'
    import corpus as corpus_mod
    corpus = _load_corpus_json()
    if not corpus.get('episodes'):
        return 'corpus_tokens.json 是空的'
    try:
        disc = corpus_mod.discover()
    except OSError as exc:
        return '扫描 subtitles/ 失败：%s' % exc
    have = sorted((e['work'], e['episode']) for e in corpus['episodes'])
    want = sorted((w, n) for w, n, _p in disc)
    if have != want:
        return '字幕集数/集号变了（%d -> %d 集）' % (len(have), len(want))
    if corpus.get('vocab_generated_at') != _state_generated_at():
        return '卡组快照已更新'
    vsig = corpus_mod._vocab_sig()
    for _work, _no, path in disc:
        rel = os.path.relpath(path, WSP.ROOT).replace('\\', '/')
        key = corpus_mod._cache_key(rel, path, vsig)
        if not os.path.exists(os.path.join(corpus_mod.CACHE_DIR, key + '.json')):
            return '有字幕是新内容或改过：%s' % rel
    return ''


def _state_generated_at() -> str:
    return _state_doc().get('generated_at', '')


def _state_doc() -> dict:
    """卡组快照（只读；带进程内缓存，报告里多处要用）。"""
    global _STATE_CACHE
    if _STATE_CACHE is None:
        _STATE_CACHE = textio.load_json(STATE_JSON, default={}) or {}
    return _STATE_CACHE


def _metrics_reason() -> str:
    """指标是否需要重算（空串 = 不需要）。"""
    if not os.path.exists(METRICS):
        return 'metrics.json 不存在'
    old = textio.load_json(METRICS, default=None)
    if not isinstance(old, dict) or 'cover' not in old:
        return 'metrics.json 结构不对'
    corpus = _load_corpus_json()
    if old.get('corpus_generated_at') != corpus.get('generated_at'):
        return '语料已更新'
    if old.get('vocab_state_generated_at') != corpus.get('vocab_generated_at'):
        return '卡组快照已更新'
    return ''


def run_refresh(args) -> tuple:
    """按需刷新 卡组快照 -> 语料 -> 指标。-> (metrics dict, 日志行列表)"""
    log = []
    if args.refresh == 'never':
        if not os.path.exists(METRICS):
            raise SystemExit('--refresh never 但 %s 不存在：先不带该参数跑一次' % METRICS)
        return textio.load_json(METRICS), ['--refresh never：直接使用现有 json']

    # ① 卡组快照（会长的只有「素材生词 + 例句」）
    if args.anki == 'never':
        log.append('--anki never：沿用现有卡组快照（%s）' % (_state_generated_at() or '-'))
    elif anki_reachable():
        try:
            changed, msg = refresh_anki_state()
            log.append(msg)
            if changed:
                log[-1] += ' -> 语料缓存按词表指纹自动全量失效'
        except Exception as exc:                      # Anki 抽风不该毁掉这次出报告
            if args.anki == 'always':
                raise SystemExit('--anki always 但取卡组快照失败：%s' % exc)
            log.append('取卡组快照失败，沿用现有快照（%s）：%s'
                       % (_state_generated_at() or '-', exc))
    elif args.anki == 'always':
        raise SystemExit('--anki always 但 AnkiConnect 不可达（先打开 Anki）')
    else:
        log.append('AnkiConnect 不可达：沿用现有卡组快照（%s）'
                   % (_state_generated_at() or '-'))

    # ② 字幕 -> 语料
    import corpus as corpus_mod
    reason = '强制刷新（--force）' if args.force else (
        _corpus_reason() if args.refresh == 'auto' else '强制刷新（--refresh always）')
    if reason:
        corpus_mod.build(verbose=args.verbose, use_cache=not args.force, prune=args.prune)
        log.append('语料重算：%s' % reason)
    else:
        log.append('语料无变化（复用 corpus_tokens.json）')

    # ③ 语料 -> 指标
    import metrics as metrics_mod
    m_reason = '强制刷新（--refresh always）' if args.refresh == 'always' else _metrics_reason()
    if m_reason or args.force:
        m = metrics_mod.compute()
        log.append('指标重算：%s' % (m_reason or '强制刷新（--force）'))
    else:
        m = textio.load_json(METRICS)
        log.append('指标无变化（复用 metrics.json）')
    return m, log


# ------------------------------------------------------------------ 绘图基建
def setup_mpl():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    for fam in ('Microsoft YaHei', 'Meiryo', 'MS Gothic', 'Yu Gothic',
                'Noto Sans CJK JP', 'Source Han Sans JP', 'SimHei', 'Hiragino Sans'):
        if fam in names:
            plt.rcParams['font.sans-serif'] = [fam, 'Microsoft YaHei', 'Meiryo', 'MS Gothic']
            break
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['figure.dpi'] = 130
    plt.rcParams['savefig.bbox'] = 'tight'
    return plt


def _fig_width(n: int, base: float = 6.0, per: float = 0.24,
               hi: float = 30.0, lo: float = 12.0) -> float:
    """图宽随集数增长（集数越多越宽），并封顶避免出巨图。"""
    return max(lo, min(hi, base + per * n))


def _ep_ticks(ax, eps: list, rotate_after: int = 24, max_labels: int = 90) -> None:
    """逐集 x 轴刻度：集数多时抽稀 + 竖排，避免标签糊成一片。"""
    n = len(eps)
    step = max(1, math.ceil(n / max_labels))
    pos = list(range(0, n, step))
    ax.set_xticks(pos)
    ax.set_xticklabels([str(eps[i]['episode']) for i in pos],
                       fontsize=7 if n <= 40 else 6,
                       rotation=90 if n > rotate_after else 0)


def _work_strip(ax, blocks: list, above: bool = True, fontsize: float = 9) -> None:
    """在坐标轴上标出各作品的分界与集数（贴边放，不压数据）。"""
    start = 0
    total = sum(len(seg) for _w, seg in blocks)
    for wk, seg in blocks:
        if start:
            ax.axvline(start - 0.5, color=GREY, lw=0.8, ls='--')
        mid = start + len(seg) / 2 - 0.5
        label = '%s（%d 集）' % (wk, len(seg)) if total != len(seg) else str(wk)
        xy = (mid, 1.0) if above else (mid, 0.0)
        off = (0, 7) if above else (0, -30)
        ax.annotate(label, xy=xy, xycoords=('data', 'axes fraction'),
                    xytext=off, textcoords='offset points', ha='center',
                    fontsize=fontsize)
        start += len(seg)
    if above and ax.get_title():
        # 作品名贴在轴顶，标题得让位，否则两行字叠在一起
        t = ax.title
        ax.set_title(ax.get_title(), pad=20, fontsize=t.get_fontsize(),
                     fontweight=t.get_fontweight())


# --------------------------------------------------------------------- 图 1
def fig_episode_coverage(m: dict, plt) -> str:
    eps = m['per_episode']
    n = len(eps)
    series = [('core6000', CORE), ('考级词汇', JLPT), ('素材生词', MINED),
              ('卡组外需背新词', OOV)]
    keys = ['core', 'jlpt', 'mined', 'oov']
    fig, ax = plt.subplots(figsize=(_fig_width(n), 5.0))
    x = list(range(n))
    bottoms = [0.0] * n
    for (label, color), key in zip(series, keys):
        vals = [e['cover'].get('learn_' + key, 0.0) * 100 for e in eps]
        ax.bar(x, vals, bottom=bottoms, color=color, width=0.8, label=label)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    known = [e['cover'].get('learn_known', 0.0) * 100 for e in eps]
    ax.plot(x, known, color='black', lw=1.8, marker='o', ms=3,
            label='其中「我已学」的比例')
    ax.set_ylabel('占该集「需背实词」比例 (%)')
    ax.set_title('每集字幕的词汇覆盖率（口径：只统计需要背的实词，'
                 '去掉助词/专有名词/感动词）')
    ax.set_ylim(0, 100)
    _ep_ticks(ax, eps)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.18), ncol=len(series) + 1,
              fontsize=8, framealpha=0.9)
    _work_strip(ax, group_blocks(eps), above=False)
    ax.axhline(m['cover']['core_learnable'] * 100, color=CORE, lw=1, ls=':')
    ax.axhline(m['cover']['deck_learnable'] * 100, color=OOV, lw=1, ls=':')
    ax.annotate('全语料 core6000 上限 %.1f%%' % (m['cover']['core_learnable'] * 100),
                xy=(0.005, m['cover']['core_learnable'] * 100),
                xycoords=('axes fraction', 'data'),
                xytext=(2, 3), textcoords='offset points', fontsize=7, color=CORE)
    ax.annotate('全语料卡组上限 %.1f%%' % (m['cover']['deck_learnable'] * 100),
                xy=(0.005, m['cover']['deck_learnable'] * 100),
                xycoords=('axes fraction', 'data'),
                xytext=(2, 3), textcoords='offset points', fontsize=7, color=OOV)
    out = os.path.join(OUT_CHARTS, 'fig1_每集覆盖率.png')
    fig.savefig(out)
    plt.close(fig)
    return out


# --------------------------------------------------------------------- 图 2
def fig_new_words(m: dict, plt) -> str:
    eps = m['per_episode']
    n = len(eps)
    disc = m['discovery']
    fig, axes = plt.subplots(2, 1, figsize=(_fig_width(n), 7.4), sharex=True,
                             gridspec_kw={'height_ratios': [1.2, 1]})
    ax = axes[0]
    x = list(range(n))
    oov = [e['oov_types'] for e in eps]
    proper = [e['proper_types'] for e in eps]
    ax.bar(x, oov, color=OOV, width=0.8, label='需要背的实词（新词）')
    ax.bar(x, proper, bottom=oov, color=PROPER, width=0.8, label='专有名词（人名地名）')
    ax.set_ylabel('该集新词种数')
    ax.set_title('每集新词产量（「新」= 在前面所有集里都没出现过）')
    ax.legend(fontsize=8)

    ax2 = axes[1]
    if disc:
        ax2.plot([d['episodes'] for d in disc], [d['seen_types'] for d in disc],
                 color=CORE, lw=2,
                 label='累计见过的词种（%d 集词表 %d 词）' % (n, disc[-1]['all_types']))
    ax2.set_xlabel('累计看的集数')
    ax2.set_ylabel('累计词种数')
    ax2.legend(fontsize=8, loc='lower right')
    ax2.grid(alpha=0.3)
    _ep_ticks(ax2, eps)
    _work_strip(ax2, group_blocks(eps), above=False)
    out = os.path.join(OUT_CHARTS, 'fig2_新词产量.png')
    fig.savefig(out)
    plt.close(fig)
    return out


# --------------------------------------------------------------------- 图 3
def fig_vocab_curve(m: dict, plt) -> str:
    curve = m['freq_curve']['curve']
    targets = vocab_targets(m)
    hours = m['totals']['speech_seconds'] / 3600
    ranks = [c['rank'] for c in curve]
    cov = [c['cover'] * 100 for c in curve]
    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    ax.plot(ranks, cov, color=CORE, lw=2.2, label='语料累计覆盖率（按词频从高到低）')
    rows = []           # 左上角小图例：目标线 + 你现在的位置，避免文字压在一起
    for i, (target, name, words) in enumerate(targets):
        color = PALETTE[(i + 4) % len(PALETTE)]
        ax.axvline(words, color=color, ls='--', lw=1)
        rows.append((color, '覆盖 %d%% 需认识 %s 词' % (round(target * 100),
                                                     format(words, ','))))
    now = m['cover']['known_vocab'] * 100
    ax.axhline(now, color=KNOWN, ls='-.', lw=1.4)
    ax.annotate('你现在的实际覆盖 %.1f%%' % now, xy=(1.2, now + 1.5), fontsize=9,
                color=KNOWN)
    v_eff = next((c['rank'] for c in curve if c['cover'] * 100 >= now), None)
    if v_eff:
        ax.axvline(v_eff, color=KNOWN, ls=':', lw=1.2)
        ax.annotate('等效于只认识最高频 %d 词' % v_eff,
                    xy=(v_eff * 1.1, max(2.0, now - 12)), fontsize=8, color=KNOWN)
    known_words = m['deck']['known_words']
    ax.axvline(known_words, color='#805ad5', ls=':', lw=1.2)
    rows.append(('#805ad5', '你卡组里认识的词条 %s 个' % format(known_words, ',')))
    ax.set_xscale('log')
    ax.set_xlabel('词汇量（按语料词频排序，log 轴）')
    ax.set_ylabel('覆盖率 (%)')
    ax.set_ylim(0, 102)
    ax.set_title('「认识多少词」与「能覆盖多少话」的换算曲线'
                 '（%d 集 / %.1f 小时语料实测）' % (m['episodes'], hours))
    ax.grid(alpha=0.3)
    for j, (color, txt) in enumerate(rows):
        ax.text(0.015, 0.965 - 0.052 * j, txt, transform=ax.transAxes, va='top',
                ha='left', fontsize=8, color=color,
                bbox=dict(fc='white', ec='none', alpha=0.8, pad=1.0))
    ax.legend(fontsize=8, loc='lower right')
    out = os.path.join(OUT_CHARTS, 'fig3_词汇量曲线.png')
    fig.savefig(out)
    plt.close(fig)
    return out


# --------------------------------------------------------------------- 图 4
def fig_progress(m: dict, plt) -> str:
    sim = [s for s in m['simulate']['steps'] if s['cycle'] == 1]
    blocks = m['block_summary']['blocks']
    n_sim, n_blk = len(sim), len(blocks)
    fig, axes = plt.subplots(1, 2,
                             figsize=(_fig_width(max(n_sim, n_blk * 6), base=5.0),
                                      5.0),
                             gridspec_kw={'width_ratios': [1.8, 1.0]})
    ax = axes[0]
    ys = [s['cover_before'] * 100 for s in sim]
    ax.plot(list(range(1, n_sim + 1)), ys, color=CORE, lw=2, marker='o', ms=3)
    _work_strip(ax, group_blocks(sim), above=True, fontsize=8)
    ax.set_xlabel('按顺序看的集数（每看完一集就把该集不认识的词全学会）')
    ax.set_ylabel('看这一集时的词汇覆盖率 (%)')
    ax.set_title('覆盖率随「看 + 把生词做成卡」推进的真实模拟', pad=20)
    ax.grid(alpha=0.3)
    if ys:
        ax.set_ylim(max(0.0, min(ys) - 6), 100)
    ax.set_xlim(0, max(2, n_sim + 1))

    ax2 = axes[1]
    labels = ['看第 1 部前\n（只有现有词汇）'] + [
        '看完前 %d 部后\n看第 %d 部' % (i, i + 1) for i in range(1, n_blk)]
    vals = [b['cover_before_learning'] * 100 for b in blocks]
    colors = [GREY] + [color_at(i) for i in range(1, max(1, n_blk))]
    ax2.bar(range(n_blk), vals, color=colors[:n_blk], width=0.62)
    for i, v in enumerate(vals):
        ax2.text(i, v + 1, '%.1f%%' % v, ha='center', fontsize=9)
    ax2.set_xticks(range(n_blk))
    ax2.set_xticklabels(labels, fontsize=8)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel('对新作品的覆盖率 (%)')
    ax2.set_title('换新作品时的残留覆盖率（题材差异越大掉得越狠）', fontsize=10)
    ax2.grid(alpha=0.3, axis='y')
    out = os.path.join(OUT_CHARTS, 'fig4_学习推进.png')
    fig.savefig(out)
    plt.close(fig)
    return out


# --------------------------------------------------------------------- 图 5
def fig_assets(m: dict, plt) -> str:
    d = m['deck']
    keys = deck_keys(m)
    rows = [(deck_label(k), d['by_deck'].get(k, 0), d['known_by_deck'].get(k, 0),
             d['mature_by_deck'].get(k, 0)) for k in keys]
    reach = m['deck_reach']
    fig, axes = plt.subplots(1, 2, figsize=(13, max(4.2, 1.05 * len(rows) + 2.4)),
                             gridspec_kw={'width_ratios': [1.35, 1.0]})
    ax = axes[0]
    for y, (name, total, known, mature) in enumerate(rows):
        ax.barh(y, mature, color=MATURE, label='已成熟（间隔≥21天）' if y == 0 else None)
        ax.barh(y, known - mature, left=mature, color=KNOWN,
                label='学过但未成熟' if y == 0 else None)
        ax.barh(y, total - known, left=known, color='#e2e8f0',
                label='一次都没刷过' if y == 0 else None)
        ax.text(total * 1.02, y, '%d/%d' % (known, total), va='center', fontsize=9)
    ax.set_yticks(list(range(len(rows))))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlabel('词条数')
    ax.set_title('词汇卡资产与掌握程度')
    ax.legend(fontsize=8, loc='lower right')
    ax.set_xlim(0, max([r[1] for r in rows] + [1]) * 1.25)

    ax2 = axes[1]
    names = list(reach)
    ratios = [reach[k]['seen_ratio'] * 100 for k in names]
    ax2.bar(range(len(names)), ratios,
            color=[deck_color(k, i) for i, k in enumerate(names)], width=0.6)
    for i, k in enumerate(names):
        r = reach[k]
        ax2.text(i, ratios[i] + max(ratios + [1]) * 0.03,
                 '%d/%d' % (r['seen_in_corpus'], r['deck_words']),
                 ha='center', fontsize=9)
    ax2.set_xticks(range(len(names)))
    ax2.set_xticklabels([deck_label(k) for k in names], fontsize=8,
                        rotation=20 if len(names) > 4 else 0)
    ax2.set_ylim(0, max(ratios + [1.0]) * 1.35)
    ax2.set_ylabel('在这 %d 集里出现过的比例 (%%)' % m['episodes'])
    ax2.set_title('你的卡组里，有多少词动画里真的会用')
    ax2.grid(alpha=0.3, axis='y')
    out = os.path.join(OUT_CHARTS, 'fig5_词汇资产.png')
    fig.savefig(out)
    plt.close(fig)
    return out


# ------------------------------------------------------------------ 代码清单
def module_summary(path: str, limit: int = 46) -> str:
    """读脚本自己的模块 docstring 第一行 —— 代码清单跟着代码走，不用手工维护。"""
    try:
        src = textio.read_text(path, warn=False)
        doc = ast.get_docstring(ast.parse(src)) or ''
    except Exception:
        return ''
    line = next((ln.strip() for ln in doc.splitlines() if ln.strip()), '')
    line = line.rstrip('：:，,、。;；')
    return (line[:limit] + '…') if len(line) > limit else line


def code_tree(limit: int = 46) -> list:
    names = sorted(f for f in os.listdir(_HERE) if f.endswith('.py'))
    tree = ['code/analysis/vocab_cover/']
    for i, name in enumerate(names):
        branch = '└─' if i == len(names) - 1 else '├─'
        tree.append('%s %-24s %s' % (branch, name, module_summary(os.path.join(_HERE, name),
                                                                  limit)))
    return tree


def _example_subtitle(disc: list) -> str:
    if not disc:
        return '<一集字幕的路径>'
    return os.path.relpath(disc[0][2], WSP.ROOT).replace('\\', '/')


# ------------------------------------------------------------------ 报告正文
def write_report(m: dict, corpus: dict, imgs: dict, disc: list) -> None:
    eps = m['per_episode']
    c, t, d, fx = m['cover'], m['totals'], m['deck'], m['freq_curve']
    mc = m['corpus_vocab_mastery']
    mb, mt = mc['by_bucket_types'], mc['by_bucket_tokens']
    tok_bucket_total = sum(mt.values()) or 1
    gaps = {g['target']: g for g in m['target_gap']}
    est = series_estimate(m)
    est_by = {e['target']: e for e in est}
    goals = goal_targets(m)
    g_lo = gaps.get(goals[0]) if goals else None
    g_hi = gaps.get(goals[-1]) if goals else None
    e_lo = est_by.get(goals[0]) if goals else None
    e_hi = est_by.get(goals[-1]) if goals else None
    lr = m.get('learning_rate') or {}
    keys = deck_keys(m)
    mature_days = (_state_doc().get('mature_days')
                   or m.get('mature_days') or 21)

    n_eps, n_works = m['episodes'], len(m['works'])
    hours = t['speech_seconds'] / 3600
    epw = episodes_per_work(m)
    blocks = group_blocks(eps)
    works_line = '、'.join('%s（%d 集）' % (w, len(seg)) for w, seg in blocks)
    decks_line = ' / '.join('%s %s' % (deck_label(k), format(d['by_deck'].get(k, 0), ','))
                            for k in keys)
    now_cover = c['known_vocab'] * 100
    v_eff = next((x['rank'] for x in fx['curve'] if x['cover'] * 100 >= now_cover), 0)
    deck_ceiling_vocab = c['deck_vocab'] * 100
    deck_ceiling_learn = c['deck_learnable'] * 100
    fixed = [k for k in keys if k in FIXED_DECKS]
    grow = [k for k in keys if k not in FIXED_DECKS]
    fixed_txt = '、'.join(deck_label(k) for k in fixed) or '无'
    grow_txt = '、'.join(deck_label(k) for k in grow) or '无'

    # 句子级指标按句数加权
    n_sent = sum(e['sentences'].get('sentences', 0) for e in eps)
    wsum = lambda field: sum(e['sentences'].get(field, 0) * e['sentences'].get('sentences', 0)
                             for e in eps)
    full = (wsum('full') / n_sent) if n_sent else 0.0
    full_l = (wsum('full_l') / n_sent) if n_sent else 0.0
    len_l = (wsum('lenient_l') / n_sent) if n_sent else 0.0
    win_n = sum(e['window_15']['n'] for e in eps)
    win_full = (sum(e['window_15']['full'] * e['window_15']['n'] for e in eps) / win_n
                if win_n else 0.0)

    # 画面上出现过的 AI 转写字幕（文件名里带标注），说明偏差时按实际列，不写死
    ai_eps = [(e['work'], e['episode'], e.get('file', ''))
              for e in (corpus.get('episodes') or [])
              if 'AI transcribed' in (e.get('file') or '')]
    bs = m['block_summary']
    blocks_mean = (sum(b['cover_before_learning'] for b in bs['blocks'])
                   / len(bs['blocks'])) if bs['blocks'] else 0.0

    L = []
    A = L.append
    A('# 字幕覆盖率与词汇量报告')
    A('')
    A('> 生成时间 %s · 语料 **%d 集 / %d 部作品 / %s 词元 / %.1f 小时台词**（快照 %s）'
      % (_dt.datetime.now().strftime('%Y-%m-%d %H:%M'), n_eps, n_works,
         format(t['tokens'], ','), hours, m.get('corpus_generated_at', '-')))
    A('> 词汇快照 %s · 卡组 %s'
      % (m.get('vocab_state_generated_at', '-'), decks_line))
    A('> 全部数字由 `code/analysis/vocab_cover/` 下的脚本从字幕与 Anki 现场算出，'
      '口径见 §1，可复跑；字幕变多、素材卡变多之后重跑同一条命令即可刷新。')
    A('')
    A('---')
    A('')
    A('## 0. 三句话结论')
    A('')
    first = f'1. **每集覆盖**：一集动画的「需要背的实词」里，' \
            f'**{pct(c["core_learnable"])}** 能在 core6000 里找到，'
    if g_lo:  # 有目标档时补一句「卡组天花板」
        first += (f'**{pct(c["corejlpt_learnable"])}** 能在 core6000+考级词汇里找到；'
                  f'把卡组（core6000+考级）**全部学完**，上限也只有 '
                  f'**{deck_ceiling_learn:.1f}%**（按全部词汇词算是 '
                  f'{deck_ceiling_vocab:.1f}%）。剩下 {pct(c["oov_learnable"])} '
                  f'是卡组里根本没有的词，只能靠看素材挖。')
    A(first)
    A(f'2. **你现在的水平**：Anki 里认识 {d["known_words"]:,} 个词条'
      f'（成熟 {d["mature_words"]:,} 个），落到这 {n_eps} 集字幕上，'
      f'把语法词、感动词、数词也算「懂」的宽口径词汇覆盖率是 '
      f'**{pct(c["understood_lenient_all"])}**，折成经验理解度约 '
      f'**{_comp(c["understood_lenient_all"]*100):.0f}%**；'
      f'实测量级是「平均每句话有 {_avg_unk(m):.1f} 个词不认识，'
      f'{pct(full_l, 0)} 的字幕整句没有生词」。')
    if g_lo and e_lo:
        line = (f'3. **还要看多少部**：把覆盖率推到 {goals[0]*100:.0f}% 还缺 '
                f'**{g_lo["missing"]:,} 个词**')
        if g_hi and g_hi is not g_lo:
            line += (f'，推到 {goals[-1]*100:.0f}% 缺 **{g_hi["missing"]:,} 个词**')
        line += (f'。按每部新番能挖到约 {e_lo["per_work_learnable"]:.0f} 个需背实词估，'
                 f'大约还要 **{e_lo["series_optimistic"]:.0f}–'
                 f'{e_lo["series_conservative"]:.0f} 部**到 {goals[0]*100:.0f}%')
        if e_hi and e_hi is not e_lo:
            line += (f'，**{e_hi["series_optimistic"]:.0f}–'
                     f'{e_hi["series_conservative"]:.0f} 部**到 {goals[-1]*100:.0f}%')
        line += '（前提是每集的生词真的做成卡并复习，光看不学不算）。'
        A(line)
    A('')
    A('---')
    A('')
    A('## 1. 数据与方法')
    A('')
    A('| 项目 | 内容 |')
    A('|---|---|')
    A(f'| 字幕语料 | `subtitles/` 下 {n_works} 部作品共 **{n_eps} 集**：{works_line} |')
    A(f'| 台词量 | {t["tokens"]:,} 个词元，其中词汇词 {t["tokens_vocab"]:,}、'
      f'需背实词 {t["tokens_learnable"]:,}；台词总时长 {hours:.1f} 小时 |')
    A(f'| 词表 | 语料共出现 {mc["types"]:,} 个词汇词种 |')
    A(f'| 词汇卡组 | {decks_line}；去重后合计认识 {d["known_words"]:,}'
      f'（成熟 {d["mature_words"]:,}） |')
    A(f'| 卡组口径 | {fixed_txt}是**固定词表**（不会增长）；会持续增长的只有 '
      f'{grow_txt}（挖生词 + 例句）—— 所以卡组词条数的变化只来自后者 |')
    A('| 分词 | SudachiPy + SudachiDict Core（正规形态素解析，非「拿词表最长匹配」） |')
    A(f'| 掌握判定 | 已学 = 该卡刷卡 ≥1 次；已成熟 = 复习卡且间隔 ≥'
      f'{mature_days} 天（Anki 标准） |')
    A(f'| 数据来源 | AnkiConnect 现场拉取（快照 {m.get("vocab_state_generated_at","-")}）'
      f' + 工作区字幕文件（快照 {m.get("corpus_generated_at","-")}） |')
    A('')
    A('### 1.1 三个分母（同一个覆盖率，分母不同差别很大）')
    A('')
    A('| 口径 | 分母 | 说明 |')
    A('|---|---|---|')
    A(f'| 含语法词 | 全部词元 {t["tokens"]:,} | 按你的要求**不排除助词**。'
      '助词/助动词/接辞属语法，不放进「词汇覆盖率」的分子，'
      '但在理解度里按「你懂」计 |')
    A(f'| 词汇词 | {t["tokens_vocab"]:,} | 去掉助词/助动词/接辞/符号，'
      '保留专有名词、感动词、数词 |')
    A(f'| 需背实词 | {t["tokens_learnable"]:,} | 再去掉专有名词（人名地名）、'
      '感动词（あっ/ん/はっ）、数词 —— **这个口径才是「要背的词汇」** |')
    A('')
    A('### 1.2 已知偏差（都会影响绝对数字，方向已注明）')
    A('')
    A(f'* **写法差异会造出少量假新词**（偏悲观）：卡组收「馬鹿」，台词写「バカ」；'
      f'卡组收「奴」，台词写「ヤツ」。{BIAS_AUDIT}'
      '这条是一次性抽检，不会随语料自动更新。')
    A('* **口语变体与拟声词**（偏悲观）：でっかい、あんた、にゃー 这类要么在卡组外，'
      '要么被 Sudachi 归进别的词。')
    A('* **Anki 口径 ≠ 真实词汇量**（偏悲观）：只在卡组里刷过的算「认识」，'
      '你在别处学会的词不计入。')
    if ai_eps:
        by_work = {}
        for wk, no, _f in ai_eps:
            by_work.setdefault(wk, []).append(no)
        detail = '、'.join('%s 第 %s 集' % (w, '/'.join(str(x) for x in sorted(ns)))
                           for w, ns in by_work.items())
        A(f'* **AI 转写的字幕有噪声**（偏悲观）：{len(ai_eps)} 集标注 AI transcribed'
          f'（{detail}），错字会被算成新词。')
    else:
        A('* **AI 转写的字幕有噪声**（偏悲观）：本期语料没有标注 AI 转写的集。')
    A('* **理解度映射是经验曲线**（粗估）：覆盖率 → 理解度用的是'
      '词汇覆盖率研究（Laufer / Nation 一系）的锚点插值，不是对你本人的测量；'
      '**句子级实测**（§5）不受这条影响。')
    A('')
    A('---')
    A('')
    A('## 2. 每集覆盖了 core6000 / 考级词汇多少')
    A('')
    A('口径：**需背实词**（去掉助词、专有名词、感动词、数词），'
      '这样数字才是「词汇量」的意义。')
    A('')
    A(f'### 2.1 全部 {n_eps} 集合计')
    A('')
    A('| 口径 | core6000 | core6000+考级 | 全部卡组 | 卡组外新词 | 我已学 | 我已成熟 |')
    A('|---|---|---|---|---|---|---|')
    for tag, label in (('all', '含语法词'), ('vocab', '词汇词'), ('learnable', '需背实词')):
        A(f'| {label} | {pct(c["core_" + tag])} | {pct(c["corejlpt_" + tag])} | '
          f'{pct(c["deck_" + tag])} | {pct(c["oov_" + tag])} | — | — |')
    A(f'| 需背实词（认识程度） | — | — | — | — | {pct(c["known_learnable"])} | '
      f'{pct(c["mature_learnable"])} |')
    A('')
    A(f'读法：把 core6000+考级 '
      f'{d["by_deck"].get("core6000", 0) + d["by_deck"].get("jlpt", 0):,} 个词条'
      f'**全部学完**，也只能覆盖「需背实词」的 {deck_ceiling_learn:.1f}%；'
      f'你现在学掉了 {pct(c["known_learnable"])}，'
      f'也就是**离自己卡组的天花板还差 '
      f'{deck_ceiling_learn - c["known_learnable"]*100:.1f} 个百分点**。')
    A('')
    A(f'反过来说：**光靠背完现有卡组，最多也只能听懂 {deck_ceiling_learn:.0f}% 的实词**，'
      f'剩下的 {pct(c["oov_learnable"])} 必须靠素材生词补 —— '
      '这就是为什么「卡组刷完还是听不懂」。')
    A('')
    A('### 2.2 分作品')
    A('')
    A('| 作品 | 集数 | 台词时长 | 词元 | 需背实词 | core6000 | core6000+考级 | 卡组外新词 | 词汇词种 | 其中新词种 |')
    A('|---|---|---|---|---|---|---|---|---|---|')
    for wk in m['works']:
        p = m['per_work'][wk]
        pc = p['cover']
        A(f'| {wk} | {p["episodes"]} | {p["minutes"]:.0f} 分 | {p["totals"]["tokens"]:,} | '
          f'{p["totals"]["tokens_learnable"]:,} | {pct(pc["core_learnable"])} | '
          f'{pct(pc["corejlpt_learnable"])} | {pct(pc["oov_learnable"])} | '
          f'{p["types"]:,} | {p["oov_types"]:,}（专名 {p["proper_types"]:,}） |')
    A('')
    A('### 2.3 逐集明细')
    A('')
    A('| 作品 | 集 | 分钟 | 需背实词 | core6000 | +考级 | 卡组外 | 我已学 | 我已成熟 | 新词种 | 专名 | 整句无生词 | ≤1 个生词 |')
    A('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for e in eps:
        cc, s = e['cover'], e['sentences']
        A(f'| {e["work"]} | {e["episode"]} | {e["minutes"]:.0f} | '
          f'{cc.get("learn_denom_tokens", e["tokens_vocab"]):,} | '
          f'{pct(cc.get("learn_core", 0))} | {pct(cc.get("learn_corejlpt", 0))} | '
          f'{pct(cc.get("learn_oov", 0))} | {pct(cc.get("learn_known", 0))} | '
          f'{pct(cc.get("learn_mature", 0))} | {e["oov_types"]} | {e["proper_types"]} | '
          f'{pct(s.get("full_l", 0), 0)} | {pct(s.get("lenient_l", 0), 0)} |')
    A('')
    A('（「整句无生词 / ≤1 个生词」按**宽口径**：语法词、感动词、数词算懂，'
      '专有名词算不懂 —— 名字不认识确实会卡住听感。）')
    A('')
    if imgs.get('ep'):
        A(f'![每集覆盖率]({REL_IMG}/{os.path.basename(imgs["ep"])})')
        A('')
    A(f'### 2.4 反向触达：一集能碰到卡组里多少词')
    A('')
    A('| 卡组 | 词条数 | %d 集里出现过的 | 比例 |' % n_eps)
    A('|---|---|---|---|')
    for k, v in m['deck_reach'].items():
        A(f'| {deck_label(k)} | {v["deck_words"]:,} | {v["seen_in_corpus"]:,} | '
          f'{pct(v["seen_ratio"])} |')
    A('')
    fixed_reach = [(k, v) for k, v in m['deck_reach'].items() if k in FIXED_DECKS]
    if fixed_reach:
        hi_k, hi_v = max(fixed_reach, key=lambda kv: kv[1]['seen_ratio'])
        lo_k, lo_v = min(fixed_reach, key=lambda kv: kv[1]['seen_ratio'])
        A(f'注意 {deck_label(hi_k)} 有 **{pct(hi_v["seen_ratio"])}** 的词在这 {n_eps} 集'
          f'动画里出现过，{deck_label(lo_k)}只有 {pct(lo_v["seen_ratio"])}。'
          '也就是说：**你的卡组里有一大半词，动画里根本不会用到**，'
          '而动画最常用的口语词反倒有相当一部分不在卡组里 —— 这是「背了卡组却听不懂」的'
          '结构性原因。')
    mined_keys = [k for k in grow if k in m['deck_reach']]
    if mined_keys:
        A('')
        A('（' + '、'.join('%s %s' % (deck_label(k), pct(m['deck_reach'][k]['seen_ratio']))
                          for k in mined_keys)
          + ' 是「为已看/将看的素材挖出来的词」，出现比例天然不高 —— '
            '它补的是卡组外的实词，不是拿来撑卡组覆盖率的。）')
    A('')
    A('---')
    A('')
    A('## 3. 新词产量：一部动画能挖出多少新词')
    A('')
    pe = m['per_episode_new']
    learn_sizes = sorted(m['cross_work']['learn_sizes'].items(),
                         key=lambda kv: kv[1], reverse=True)
    A(f'* 每集**首次出现**的词种中位数：**{pe["median_new_types"]}** 个，'
      f'其中「需要背的实词」中位 **{pe["median_new_learnable"]}** 个')
    A(f'* {n_eps} 集累计新词种 {pe["total_new_types"]:,} 个')
    if learn_sizes:
        A('* 每部作品带来的新词（相对你现有词汇）：'
          + '、'.join(f'{k} {v:,}' for k, v in learn_sizes) + ' 个词种')
    A('')
    A(f'分档看这 {n_eps} 集语料的词元构成（词汇词口径）：')
    A('')
    A('| 档位 | 词种 | 占词种 | 词元 | 占词元 | 是否要背 |')
    A('|---|---|---|---|---|---|')
    for k in bucket_keys(mb):
        A(f'| {BUCKET_LABEL.get(k, k)} | {mb[k]:,} | {pct(mb[k]/mc["types"])} | '
          f'{mt.get(k, 0):,} | {pct(mt.get(k, 0)/tok_bucket_total)} | '
          f'{BUCKET_ADVICE.get(k, "—")} |')
    A('')
    noback = sum(mt.get(k, 0) for k in ('proper', 'interj', 'numeral'))
    A(f'结论：**{pct(noback/tok_bucket_total)} 的词元既不用背也背不了**'
      f'（名字、语气词、数字）；真正要背的是「卡组外实词」'
      f'{pct(mt.get("oov", 0)/tok_bucket_total)} + 卡组内你还没学的部分。')
    A('')
    if imgs.get('nw'):
        A(f'![新词产量]({REL_IMG}/{os.path.basename(imgs["nw"])})')
        A('')
    A('---')
    A('')
    A('## 4. 需要多少词汇量才能听懂：词汇量—覆盖率曲线')
    A('')
    A('| 目标覆盖率 | 需要认识的词种数 |')
    A('|---|---|')
    for target, _name, words in vocab_targets(m):
        A(f'| {target*100:.0f}% | {words:,} |')
    A('')
    A(f'你现在认识 {d["known_words"]:,} 个词条，'
      f'但有效覆盖只有 **{now_cover:.1f}%** —— 等效于「只认识语料最高频的 {v_eff:,} 个词」'
      '的水平。原因不是词少，而是**词的构成偏了**：')
    if 'core6000' in m['deck_reach']:
        A(f'你的 core6000 里只有 {pct(m["deck_reach"]["core6000"]["seen_ratio"])} 的词'
          f'在这 {n_eps} 集动画里出现过'
          + (f'，考级词汇只有 {pct(m["deck_reach"]["jlpt"]["seen_ratio"])}'
             if 'jlpt' in m['deck_reach'] else '')
          + ' —— 卡组里一大半是书面语/考试词，而动画高频的口语词有一批不在卡组里。')
    A('')
    A('同样的词数，如果全部换成语料里最高频的那批词，覆盖率会高得多：')
    A('')
    A('| 若你认识的是最高频的… | 覆盖率 |')
    A('|---|---|')
    for n_words, cover in top_cover_points(m):
        A(f'| {n_words:,} 词 | {pct(cover)} |')
    A('')
    if imgs.get('vc'):
        A(f'![词汇量曲线]({REL_IMG}/{os.path.basename(imgs["vc"])})')
        A('')
    A('---')
    A('')
    A('## 5. 你现在的词汇量与理解度')
    A('')
    A('### 5.1 词汇资产')
    A('')
    A('| 卡组 | 词条 | 已学 | 已成熟 | 未学 |')
    A('|---|---|---|---|---|')
    for k in keys:
        total = d['by_deck'].get(k, 0)
        known = d['known_by_deck'].get(k, 0)
        mature = d['mature_by_deck'].get(k, 0)
        A(f'| {deck_label(k)} | {total:,} | {known:,} | {mature:,} | {total-known:,} |')
    A(f'| **去重合计** | **{d["deck_words"]:,}** | **{d["known_words"]:,}** | '
      f'**{d["mature_words"]:,}** | **{d["deck_words"]-d["known_words"]:,}** |')
    A('')
    A('> 说明：这里按**去重后的词条**统计，所以「已学」比单个卡组的刷卡张数略高 —— '
      '同一个词同时收在 core6000 和考级词汇里时，在任一卡组学过就算「这个词认识」。'
      f'{fixed_txt}是固定词表，词条数不会涨；{grow_txt}会持续增长。')
    A('')
    if lr:
        A(f'按 Anki 复习记录（快照 {lr["snapshot"]}）：'
          f'近 {len(lr["recent_months"])} 个月新学 {lr["recent_total"]:,} 张词汇卡，'
          f'月均 **{lr["recent_per_month"]:.0f} 张**。')
        A('')
    A('### 5.2 落到字幕上的实际水平')
    A('')
    A('| 指标 | 数值 | 含义 |')
    A('|---|---|---|')
    A(f'| 词汇覆盖率（宽口径） | **{pct(c["understood_lenient_all"])}** | '
      '语法词、感动词、数词算懂，专有名词算不懂 |')
    A(f'| 词汇覆盖率（严格口径） | {pct(c["understood_strict_all"])} | '
      '只算「学过的词汇词+语法词」 |')
    A(f'| 按已成熟词算（宽口径） | {pct(c["understood_mature_all"])} | '
      '只有进长期记忆的词汇（+语法词/感动词）才算 |')
    A(f'| 需背实词已学率 | {pct(c["known_learnable"])} | 只算要背的那部分词 |')
    A(f'| 整句无生词（严格 / 宽口径） | {pct(full, 0)} / {pct(full_l, 0)} | '
      f'{n_sent:,} 条字幕里，一个生词都没有的比例 |')
    A(f'| 整句 ≤1 个生词（宽口径） | {pct(len_l, 0)} | 最多只有一个词卡住 |')
    A(f'| 连续 15 个实词都没生词 | {pct(win_full, 0)} | '
      '连续 15 个词一个都不卡的窗口比例（「长时间顺畅听懂」的体验指标，'
      '数值低说明「听得见单词、连不成意思」） |')
    A(f'| 经验理解度 | 宽口径约 {_comp(c["understood_lenient_all"]*100):.0f}% / '
      f'严格口径约 {_comp(c["understood_strict_all"]*100):.0f}% | '
      '覆盖率→理解度的经验映射（Laufer/Nation 一系锚点），仅供量级参考 |')
    A(f'| 平均每句生词数 | {_avg_unk(m):.1f} 个 | 宽口径下每条字幕平均卡住的词数 |')
    A('')
    A(f'**怎么读**：词汇覆盖率 {pct(c["understood_lenient_all"])} 大体相当于'
      '「能抓住话题和大致意思，但每 2–3 句就会被一个词卡住」。'
      '要「看懂剧情细节不费力」通常需要 95%+，要「不用字幕跟上语速」需要 98%+ —— '
      f'你现在离 95% 还差 {95 - c["understood_lenient_all"]*100:.1f} 个百分点，'
      f'离 98% 还差 {98 - c["understood_lenient_all"]*100:.1f} 个百分点。')
    A('')
    if imgs.get('as'):
        A(f'![词汇资产]({REL_IMG}/{os.path.basename(imgs["as"])})')
        A('')
    A('---')
    A('')
    A('## 6. 还要看（并学）多少部动画')
    A('')
    A('### 6.1 实测到的三条规律')
    A('')
    sim = [s for s in m['simulate']['steps'] if s['cycle'] == 1]
    A('**① 同一部剧内部：边看边学，覆盖率涨得很快。**')
    if sim:
        seg_txt = []
        for wk, seg in group_blocks(sim):
            seg_txt.append(f'{wk} 第 {seg[0]["episode"]} 集 {pct(seg[0]["cover_before"], 0)} → '
                           f'第 {seg[-1]["episode"]} 集 {pct(seg[-1]["cover_before"], 0)}')
        A('* ' + '；'.join(seg_txt) + '。')
        A(f'* 全部 {len(sim)} 集按顺序看完并学完生词，最后一集时的覆盖率是 '
          f'{pct(sim[-1]["cover_before"])}。')
    A('')
    A('**② 换新作品会掉一截（题材/人物/专名不同）—— 按实际顺序看：'
      '学完前面几部再进这一部时的覆盖率：**')
    A('')
    A('| 已学完的作品数 | 进这一部时的覆盖率 | 这一部新带来的词种（相对前面已学完的） |')
    A('|---|---|---|')
    for i, b in enumerate(bs['blocks']):
        A(f'| {i} | {pct(b["cover_before_learning"])} | {b["new_words"]:,} |')
    A('')
    if learn_sizes and e_lo:
        A('**③ 每部新番的产量：**'
          + '、'.join(f'{k} {v:,} 词种' for k, v in learn_sizes)
          + f'；折算成「需要背的实词」约 **{e_lo["per_work_learnable"]:.0f} 个/部**。')
    A('')
    A('### 6.2 目标档位下的缺口与部数估计')
    A('')
    A('| 目标覆盖率 | 还需要认识的词 | 其中卡组内未学（现在就能学） | 卡组外（要靠看素材挖） | 估计还要看 |')
    A('|---|---|---|---|---|')
    for e in est:
        A(f'| {e["target"]*100:.0f}% | {e["missing"]:,} | {e["missing_in_deck"]:,} | '
          f'{e["missing_oov"]:,} | **{e["series_optimistic"]:.0f}–'
          f'{e["series_conservative"]:.0f} 部**（{e["episodes_optimistic"]:.0f}–'
          f'{e["episodes_conservative"]:.0f} 集） |')
    A('')
    A('估算假设（都写出来，方便你改）：')
    A('')
    A('* 「还需要认识的词」= 从语料词频高到低累加到目标覆盖率时，你还没学的词数（实测）；')
    if e_lo:
        share = (e_lo['per_work_learnable'] / e_lo['per_work_types'] * 100
                 if e_lo['per_work_types'] else 0)
        A(f'* 「每部产量」= 实测每部新词种 {e_lo["per_work_types"]:,.0f} 个 × '
          f'其中需背实词占比 {share:.0f}%；')
    A('* 乐观情形按产量 ×1.2、保守情形按 ×0.6（越往后词越生僻、越难遇到，产量会衰减）；')
    A(f'* 1 部 = {epw:.0f} 集（本语料 {n_works} 部作品集数的中位数）；'
      f'不含你已经看过的这 {n_works} 部。')
    A('')
    if imgs.get('pg'):
        A(f'![学习推进]({REL_IMG}/{os.path.basename(imgs["pg"])})')
        A('')
    A('### 6.3 更省时间的路径（数据支持的结论）')
    A('')
    if g_lo:
        A(f'1. **先把卡组里没学的补完**：卡组内未学 '
          f'{d["deck_words"]-d["known_words"]:,} 个词条中，'
          f'有 {g_lo["missing_in_deck"]:,} 个直接卡在 {goals[0]*100:.0f}% 目标的路上。'
          f'这部分**不用等碰到**，现在学就涨覆盖率，'
          f'把卡组学满能把覆盖率顶到 {deck_ceiling_learn:.1f}%（需背实词口径）。')
        tail = ''
        if g_hi and g_hi is not g_lo:
            tail = f'（到 {goals[-1]*100:.0f}% 是 {g_hi["missing_oov"]:,} 个）'
        A(f'2. **同时挖卡组外的实词**：这部分（到 {goals[0]*100:.0f}% 目标）是 '
          f'{g_lo["missing_oov"]:,} 个{tail}，'
          '只能从你看的动画里挖 —— 你的 mine 流水线正好干这个。')
    top_pts = top_cover_points(m)
    if top_pts:
        shown = top_pts[:4]
        A('3. **不要平均用力**：语料里' + '，'.join(
            f'最高频 {n:,} 词覆盖 {pct(v)}' for n, v in shown) + '。'
          '先把这 2000–3000 个高频词吃透，收益远大于继续刷低频考级词。')
    if bs['blocks']:
        A(f'4. **换题材要留折损**：看一部新作品时，你的覆盖率平均只有 '
          f'{pct(blocks_mean)}，比你在已学过的作品上的 {pct(c["understood_lenient_all"])} '
          f'低约 {(c["understood_lenient_all"] - blocks_mean) * 100:.0f} 个百分点，'
          '所以「精听一部 + 泛听多部」比只精听一部更快把面铺开。')
    A('')
    A('---')
    A('')
    A('## 7. 限制')
    A('')
    A(f'* 语料只有 {n_works} 部 {n_eps} 集 {hours:.1f} 小时，且各部题材/年代差异大'
      f'（{ "、".join(w for w, _ in blocks) }）。'
      '外推到整个「日语动画」会有偏差，报告里的部数都是**量级估计**。')
    A('* 字幕是**文本**：本报告衡量的是词汇/表达层面，'
      '听力的另外两块（语速适应、音变与省略的辨音）无法从字幕测出。')
    A('* 覆盖率≠理解度：95% 覆盖率仍意味着每 20 个词就有 1 个不认识。')
    A('* 卡组词条数只反映 Anki 里建档的词；`mined` 类卡组（素材生词/例句）会持续增长，'
      '所以历史报告之间这部分不能直接比大小。')
    A('')
    A('---')
    A('')
    A('## 8. 可复用代码')
    A('')
    A('```')
    for line in code_tree():
        A(line)
    A('```')
    A('')
    A('最常用的那条（给你任意一段日语文字或一集字幕，直接出结论）：')
    A('')
    A('```powershell')
    A(f'$WS = "{WSP.ROOT}"')
    A(f'$PY = "{sys.executable}"')
    A('$VC = "$WS\\code\\analysis\\vocab_cover"')
    A('')
    A('# 一集字幕（下面这条就是本次语料里的第一集）')
    A(f'& $PY "$VC\\cover_cli.py" "{_example_subtitle(disc)}"')
    A('# 一篇纯文本 / 一段话')
    A('& $PY "$VC\\cover_cli.py" --text "..."  # 或 --stdin / 文件路径')
    A('# 输出新词表（可喂给你的 mine 流水线）')
    A('& $PY "$VC\\cover_cli.py" --json --oov-out data\\vocab_cover\\oov_ep01.json <file>')
    A('```')
    A('')
    A('数据保鲜：本脚本 `--refresh auto`（默认）已经自动做了「字幕变了重算语料、'
      '语料/卡组变了重算指标、Anki 开着就重取卡组快照」；'
      '想手跑数据链就是 `collect_vocab.py` → `corpus.py` → `metrics.py` → `report_build.py`。')
    A('')
    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L))


def _comp(cover_pct: float) -> float:
    """和 jp_tok.coverage_to_comprehension 同一套锚点，输入输出都是百分数。"""
    import jp_tok
    return jp_tok.coverage_to_comprehension(cover_pct / 100.0) * 100


def _avg_unk(m: dict) -> float:
    tot_u = tot_s = 0
    for e in m['per_episode']:
        s = e['sentences']
        if not s:
            continue
        n = s.get('sentences', 0)
        hist = s.get('unknown_hist_l') or s.get('unknown_hist') or {}
        tot_s += n
        for k, v in hist.items():
            tot_u += int(k) * v
    return tot_u / tot_s if tot_s else 0


def check_metrics(m: dict) -> None:
    """metrics.json 结构自检：旧版/半成品文件直接说清楚，别在生成报告时炸在半路。"""
    need = ('cover', 'totals', 'deck', 'per_episode', 'freq_curve', 'target_gap',
            'per_work', 'works', 'corpus_vocab_mastery', 'block_summary',
            'deck_reach', 'per_episode_new', 'simulate', 'cross_work')
    missing = [k for k in need if k not in m]
    if missing:
        raise SystemExit('metrics.json 缺少字段 %s：请用 --refresh always 重新生成'
                         % '、'.join(missing))


def main() -> int:
    ap = argparse.ArgumentParser(
        description='字幕覆盖率与词汇量报告（自动读取 subtitles/ 的新内容）')
    ap.add_argument('--refresh', choices=('auto', 'always', 'never'), default='auto',
                    help='auto=只重算过期部分（默认）；always=一律重算；never=只用现有 json')
    ap.add_argument('--anki', choices=('auto', 'always', 'never'), default='auto',
                    help='auto=AnkiConnect 可达就重取卡组快照（默认）；always=取不到就报错；'
                         'never=不连 Anki')
    ap.add_argument('--force', action='store_true',
                    help='字幕忽略缓存全量重算（等价于 corpus.py --force，并重算指标）')
    ap.add_argument('--prune', action='store_true', help='顺带清掉不再需要的语料缓存文件')
    ap.add_argument('--no-charts', action='store_true', help='只出 Markdown，不重画图')
    ap.add_argument('--verbose', action='store_true', help='打印逐集重算明细')
    args = ap.parse_args()

    ensure_dirs()
    m, log = run_refresh(args)
    check_metrics(m)
    for line in log:
        print('·', line)

    corpus = _load_corpus_json()
    try:
        import corpus as corpus_mod
        disc = corpus_mod.discover()
    except Exception as exc:
        print('！扫描 subtitles/ 失败（§8 的示例路径会用占位符）：%s' % exc)
        disc = []

    imgs = {}
    if not args.no_charts:
        plt = setup_mpl()
        imgs['ep'] = fig_episode_coverage(m, plt)
        imgs['nw'] = fig_new_words(m, plt)
        imgs['vc'] = fig_vocab_curve(m, plt)
        imgs['pg'] = fig_progress(m, plt)
        imgs['as'] = fig_assets(m, plt)
        for k, v in imgs.items():
            print('图:', os.path.relpath(v, WSP.ROOT))
    write_report(m, corpus, imgs, disc)
    print('语料: %d 集 / %d 部作品 / %.1f 小时'
          % (m['episodes'], len(m['works']), m['totals']['speech_seconds'] / 3600))
    print('报告:', os.path.relpath(REPORT, WSP.ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
