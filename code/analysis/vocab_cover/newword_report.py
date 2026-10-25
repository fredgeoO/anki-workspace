# -*- coding: utf-8 -*-
"""★ 生词报告生成器：一条命令出「学习用」生词报告（Markdown + JSON）。

面向日语学习，**不写工具细节**（判定规则、复现命令、跨剧对比都不进报告）。
章节固定为：

  一句话结论 → 规模与掌握 → 生词分档 → 题材通用词 → 值得挖的生词 → 不用记的生词（附原因）
  （整部作品再加「分集速览」）

用法::

    # 单集 / 单篇文章
    python newword_report.py "subtitles\\<作品>\\... - 01 (AT-X).srt"
    python newword_report.py article.txt

    # 整个作品目录（递归）：汇总 + 分集速览
    python newword_report.py "subtitles\\<作品目录>"

    # 整个 subtitles/（多部作品）：每部各出一份报告
    python newword_report.py subtitles

    # 常用开关
    ... --top 40                 # 值得挖清单最多列几个（默认 40，0 = 全部）
    ... --ep-top 15              # 分集速览每集列几个（默认 15）
    ... --no-example             # 表格里不要「首例句」列
    ... --out docs\\reports\\x.md --json-out data\\vocab_cover\\x.json

产物（默认路径）::

    docs/reports/<slug>_生词报告.md            # 报告
    data/vocab_cover/<slug>_生词.json          # 结构化数据（含 cross/mine 字段，可接挖词链路）
    data/vocab_cover/pending_<slug>.json       # 待判定清单（只在有「未收录」词时写）

代理只参与「未收录 + 词表没覆盖」的词
--------------------------------------
代码已经做完所有能自动做的判断（`crosswork.py` 的三份词表 + Jiten 排名）：
通用 / 题材通用 / 低频通用 → 值得挖；作品专有 / 功能词 / 拟声 → 不挖。
剩下**判不了的**（Jiten 没排名、三份词表也都没覆盖）会攒成待判定清单，每个词带
原形・品詞・次数・集号・例句・提示（是否片假名、是否活用形、是否含汉字）。
需要时才派**一个**代理（或本地模型，见 local-llm 技能）判一遍，把结论填进
``decisions`` 字段后回写词表::

    python newword_report.py --apply-decisions data\\vocab_cover\\pending_<slug>.json

``decisions`` 形状（kind 四选一）::

    "decisions": {
      "髪色":   {"kind": "genre", "category": "学园・社会"},       # 跨作品通用词 → 值得挖
      "ユフィリア": {"kind": "work",  "reason": "人名（女主角）"},   # 作品专有 → 不挖
      "ニュッ":  {"kind": "not_vocab", "group": "onomatopoeia"},   # 功能词/拟声 → 不挖
      "思春":   {"kind": "ignore", "reason": "切分残片"}            # 判过但不挖 → 写进 not_vocab 的 ignored 组
    }

四种结论都会**落盘**，所以同一个词不会被反复问第二遍：回写后重跑报告，待判定数应该归零，
同类词以后全自动。
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _deps import STATE_JSON, WSP, add_pylibs  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
from _norm import norm_word  # noqa: E402

add_pylibs()

import analyze  # noqa: E402
import corpus  # noqa: E402
import crosswork  # noqa: E402
import jp_tok  # noqa: E402
import newwords as nw  # noqa: E402

VC_DATA = os.path.join(WSP.DATA, 'vocab_cover')
REPORT_DIR = os.path.join(WSP.ROOT, 'docs', 'reports')
CATS = ('oov', 'untackled')          # 报告只关心「卡组外要背」+「有卡没学过」
KANJI_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')

TIER_ROWS = [
    ('通用', '通用（跨作品高频）', '✅ 值得挖'),
    ('题材', '题材通用（宫廷/奇幻/军事/神话/学园・社会）', '✅ 值得挖'),
    ('低频通用', '低频通用（有排名但冷门）', '✅ 值得挖'),
    ('专有', '作品专有（人名/独有概念）', '❌ 不做卡'),
    ('疑似人名', '疑似人名/造语（片假名 + 排名很深或没有排名）', '❌ 不做卡'),
    ('inflection', '活用形碎片（原形已有卡）', '❌ 不做卡'),
    ('function', '语法性功能词', '❌ 不做卡'),
    ('拟声', '拟声 / 感叹', '❌ 不做卡'),
    ('ignored', '已判·不挖（人工/代理确认过）', '❌ 不做卡'),
    ('未收录', '未收录（两表都没有）', '❓ 看情况'),
]

TEXT_LABELS = {'--text': '一段文字', 'stdin': '标准输入（管道）'}


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec='seconds')


def _pct(x: float) -> str:
    return f'{x * 100:.1f}%'


def _table(headers: list, rows: list) -> list:
    L = ['| ' + ' | '.join(headers) + ' |',
         '|' + '|'.join(['---'] * len(headers)) + '|']
    for r in rows:
        L.append('| ' + ' | '.join('' if c is None else str(c) for c in r) + ' |')
    return L


def _inline(words: list, with_lemma: bool = True) -> str:
    def cell(w):
        return _word_cell(w) if with_lemma else w['word']
    return ' · '.join(f'{cell(w)}({w["count"]})' if w['count'] > 1 else cell(w)
                      for w in sorted(words, key=lambda w: -w['count']))


def _word_cell(w: dict) -> str:
    """词形；是活用形时补上原形（做卡用原形），例如 放っ（放つ）。"""
    lemma = w.get('lemma') or ''
    return f"{w['word']}（{lemma}）" if lemma else w['word']


def _rel(path: str) -> str:
    if not path:
        return ''
    try:
        rel = os.path.relpath(path, WSP.ROOT)
    except ValueError:
        return path
    return path if rel.startswith('..') else rel.replace('\\', '/')


def _cell(text: str, width: int) -> str:
    text = ' '.join((text or '').split())
    return text if len(text) <= width else text[:width - 1] + '…'


# ------------------------------------------------------------------ 输入收集
def slugify(text: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', '_', (text or '').strip())
    return re.sub(r'_+', '_', s).strip('_') or 'report'


def work_key_of(label: str) -> str:
    """相对路径 -> 作品键（只有 subtitles/<作品>/… 才算作品，其它按单篇文章处理）。"""
    parts = [p for p in label.replace('\\', '/').split('/') if p]
    if parts and parts[0] == 'subtitles' and len(parts) > 2:
        return parts[1]
    return ''


def collect_sources(args) -> list:
    """-> [{label, text, is_srt, work_key, episode, file}]（复用 newwords 的读法）"""
    items = []
    for label, text, is_srt in nw.read_sources(args):
        base = os.path.basename(label)
        item = {'label': label, 'text': text, 'is_srt': is_srt,
                'work_key': work_key_of(label), 'file': label,
                'episode': corpus.episode_no(base) if is_srt else None}
        items.append(item)
    return items


def group_by_work(items: list) -> 'collections.OrderedDict':
    groups = collections.OrderedDict()
    for it in items:
        groups.setdefault(it['work_key'], []).append(it)
    for key in groups:
        groups[key].sort(key=lambda it: (it['episode'] is None, it['episode'] or 0,
                                         it['label']))
    return groups


def group_title(key: str, items: list) -> str:
    if not key and items[0]['label'] in TEXT_LABELS:
        return TEXT_LABELS[items[0]['label']]
    stem = os.path.splitext(os.path.basename(items[0]['file']))[0]
    label = (corpus.WORK_LABELS.get(key, key) if key else '') or stem
    eps = sorted({it['episode'] for it in items if it['episode'] is not None})
    if len(items) == 1 and eps:
        return f'{label} 第 {eps[0]:02d} 集'
    if len(items) == 1:
        return label
    if eps:
        return f'{label}（{len(items)} 集）'
    return label


def group_slug(key: str, items: list, title: str) -> str:
    if not key and items[0]['label'] in TEXT_LABELS:
        return 'text' if items[0]['label'] == '--text' else 'stdin'
    stem = os.path.splitext(os.path.basename(items[0]['file']))[0]
    label = (corpus.WORK_LABELS.get(key, key) if key else '') or stem
    eps = sorted({it['episode'] for it in items if it['episode'] is not None})
    if len(items) == 1 and eps:
        return f'{label}_E{eps[0]:02d}'
    if len(items) == 1:
        return stem
    return label or slugify(title)


# ------------------------------------------------------------------ 分析
def analyze_source(vocab, jiten, cw, item: dict, examples: int) -> dict:
    sentences, clean, _ep = analyze.sentences_of(item['text'], is_srt=item['is_srt'])
    toks = vocab.tokenize(clean)
    recs = nw.collect_records(vocab, toks, CATS)
    nw.attach_examples(vocab, sentences, recs, examples)
    words = nw.finalize(recs, 'jiten', jiten, cw, cw.scope_for(item['label']), vocab)
    summary = nw.build_summary(vocab, toks, recs, sentences)
    summary['cover_core6000'] = (vocab.coverage(toks).summary().get('cover_all')
                                 or {}).get('core', 0.0)
    summary['cross_counts'] = cw.counts(words)
    return {'label': item['label'], 'file': item['file'], 'episode': item['episode'],
            'summary': summary, 'words': words}


def snapshot_info(state_path: str) -> dict:
    info = {'path': os.path.relpath(state_path, WSP.ROOT).replace('\\', '/')}
    try:
        with open(state_path, encoding='utf-8') as fh:
            data = json.load(fh)
        decks = data.get('decks') or {}
        info['generated_at'] = data.get('generated_at')
        info['source'] = data.get('source')
        info['core6000_studied'] = (decks.get('core6000') or {}).get('studied')
        info['core6000_mature'] = (decks.get('core6000') or {}).get('mature')
        info['core6000_notes'] = (decks.get('core6000') or {}).get('notes')
    except Exception:                                          # noqa: BLE001
        pass
    return info


def episodes_of_key(sources: list) -> dict:
    """词键 -> 出现过的集号列表（分集归属用）。"""
    out = collections.defaultdict(list)
    for src in sources:
        ep = src['episode']
        for w in src['words']:
            if ep is not None and ep not in out[w['key']]:
                out[w['key']].append(ep)
    return {k: sorted(v) for k, v in out.items()}


def sort_words(words: list, sort: str = 'jiten') -> list:
    return sorted(words, key=lambda w: nw._sort_key(w, sort))


# ------------------------------------------------------------------ 渲染
def _bits(pairs: list) -> str:
    """('跨作品通用', 89) … -> 「跨作品通用 89 · 低频通用 119」（跳过 0）。"""
    return ' · '.join(f'{k} {v}' for k, v in pairs if v)


def render_headline(title: str, summary: dict, words: list, cc: dict,
                    n_sources: int) -> list:
    unknown = len(words)
    tokens = sum(w['count'] for w in words)
    mine = cc.get('可挖', 0)
    genre = sum(v for k, v in cc.items() if k.startswith('题材:'))
    genres = {k.split(':', 1)[1]: v for k, v in cc.items() if k.startswith('题材:')}
    scope = f'这 {n_sources} 集里' if n_sources > 1 else '这里'
    L = ['## 一句话结论', '']
    L.append(f'**{scope}还不认识的词：{unknown} 个词种**'
             f'（占 {summary["types_vocab"]} 个词汇词种的 {_pct(unknown / summary["types_vocab"])}）；'
             f'共出现 {tokens} 次（占 {summary["tokens_vocab"]} 个词汇词元的 '
             f'{_pct(tokens / summary["tokens_vocab"])}）。')
    L.append('')
    L.append(f'其中 **值得挖 {mine} 个** —— ' + _bits([
        ('跨作品通用', cc.get('通用', 0)), ('题材通用', genre),
        ('低频通用', cc.get('低频通用', 0))]) + '；')
    L.append(f'**不用记 {unknown - mine} 个** —— ' + _bits([
        ('作品专有人名/概念', cc.get('专有', 0)), ('疑似人名', cc.get('疑似人名', 0)),
        ('活用形碎片', cc.get('活用形', 0)), ('功能词', cc.get('功能词', 0)),
        ('拟声', cc.get('拟声', 0)), ('已判不挖', cc.get('已判不挖', 0)),
        ('未收录', cc.get('未收录', 0))]))
    if genres:
        L.append('')
        L.append('题材看点：' + ' · '.join(f'{k} {v} 个'
                                          for k, v in sorted(genres.items(), key=lambda kv: -kv[1])))
    L.append('')
    L.append('> 建议：优先把「值得挖」里 Jiten 排名靠前的那几十个做卡（第 4 节已按动画出现广度排好）；'
             '题材词（宫廷/奇幻…）跟着剧情过一遍就能记住大半；人名和拟声不用做卡。')
    return L


def render_scale(summary: dict, snap: dict, n_sources: int) -> list:
    cc = summary.get('cross_counts') or {}
    L = ['## 1. 规模与掌握', '']
    L.extend(_table(['指标', '数值'], [
        ['句子', summary['sentences']],
        ['词汇词元 / 词汇词种', f"{summary['tokens_vocab']} / {summary['types_vocab']}"],
        ['core6000 覆盖', _pct(summary.get('cover_core6000', 0.0))],
        ['卡组覆盖（core6000 + JLPT + 素材生词）', _pct(summary['cover_deck'])],
        ['已学（严格口径）', _pct(summary['cover_known'])],
        ['**实际能懂（宽口径）**', f"**{_pct(summary['understood_lenient'])}**"],
        ['生词：卡组外要背 / 有卡没学过',
         f"{summary['cat_types'].get('oov', 0)} / {summary['cat_types'].get('untackled', 0)}"],
    ]))
    L.append('')
    snap_bits = []
    if snap.get('generated_at'):
        snap_bits.append(f"词汇快照 {str(snap['generated_at'])[:16].replace('T', ' ')}")
    if snap.get('core6000_studied') is not None:
        snap_bits.append(f"core6000 已学 {snap['core6000_studied']} / 成熟 {snap.get('core6000_mature')}")
    if snap_bits:
        L.append('> ' + ' ｜ '.join(snap_bits))
        L.append('')
    return L


def render_tiers(cc: dict) -> list:
    L = ['## 2. 生词分档', '']
    rows = []
    for key, name, action in TIER_ROWS:
        if key == '题材':
            n = sum(v for k, v in cc.items() if k.startswith('题材:'))
        else:
            n = cc.get(key, 0)
        if n or key in ('通用', '题材', '低频通用'):
            rows.append([name, n, action])
    rows.append(['**合计**', sum(r[1] for r in rows), ''])
    L.extend(_table(['档', '词种', '怎么处理'], rows))
    L.append('')
    L.append('> 「通用 / 题材通用 / 低频通用」= 换个作品还会碰到的词，值得做卡；'
             '「作品专有」= 只在**这一部**里成立的概念或人名，跟着剧情记住就行。')
    return L


def render_genre(words: list, with_example: bool, ex_width: int) -> list:
    genre = [w for w in words if w.get('cross') == 'genre']
    if not genre:
        return []
    L = ['## 3. 题材通用词', '']
    L.append('> 同一题材的作品里反复出现，值得做卡；它们同时是这部作品的世界观骨架。')
    L.append('')
    by_cat = collections.defaultdict(list)
    for w in genre:
        by_cat[w.get('cross_note') or '其他'].append(w)
    for cat, ws in sorted(by_cat.items(), key=lambda kv: -sum(w['count'] for w in kv[1])):
        ws = sorted(ws, key=lambda w: -(w['count'] or 0))
        L.append(f'**{cat}（{len(ws)} 个 / {sum(w["count"] for w in ws)} 次）**')
        L.append('')
        headers = ['词', '读音', '品詞', '次数', 'Jiten']
        rows = [[_word_cell(w), w['reading'] or '', (w['pos'] or '').split('/')[0],
                 w['count'], w['jiten_rank'] or '—'] for w in ws]
        if with_example:
            headers.append('首例句')
            for row, w in zip(rows, ws):
                row.append(_cell((w['examples'] or [''])[0], ex_width))
        L.extend(_table(headers, rows))
        L.append('')
    return L


def render_mine(words: list, top: int, with_example: bool, ex_width: int,
                json_out: str = '') -> list:
    mine = sort_words([w for w in words if w.get('mine')])
    if not mine:
        return []
    shown = mine[:top] if top else mine
    L = ['## 4. 值得挖的生词', '']
    L.append(f'共 **{len(mine)} 个**，按动画出现广度排序（Jiten 越靠前 = 在越多部动画里出现过）'
             + (f'，下表列前 {len(shown)} 个。' if len(shown) < len(mine) else '。'))
    L.append('')
    L.append('> 词形后面带括号的是活用形（例如 `放っ（放つ）`），**做卡用括号里的原形**。')
    L.append('')
    headers = ['#', '词', '读音', '品詞', '次数', 'Jiten', '档']
    if with_example:
        headers.append('首例句')
    rows = []
    for i, w in enumerate(shown, 1):
        row = [i, _word_cell(w), w['reading'] or '', (w['pos'] or '').split('/')[0],
               w['count'], w['jiten_rank'] or '—', crosswork.CrossWork.label(w)]
        if with_example:
            row.append(_cell((w['examples'] or [''])[0], ex_width))
        rows.append(row)
    L.extend(_table(headers, rows))
    if len(shown) < len(mine):
        L.append('')
        L.append(f'> 其余 {len(mine) - len(shown)} 个的完整清单见 `{_rel(json_out)}`。'
                 if json_out else f'> 其余 {len(mine) - len(shown)} 个见完整数据。')
    return L


def render_skip(words: list, pending_path: str = '') -> list:
    skip = [w for w in words if not w.get('mine')]
    if not skip:
        return []
    L = ['## 5. 不用记的生词', '']
    groups = {
        'work': [w for w in skip if w.get('cross') == 'work'],
        'name': [w for w in skip if w.get('suspect_name')],
        'inflection': [w for w in skip if w.get('cross') == 'inflection'],
        'function': [w for w in skip if w.get('not_vocab')],
        'unlisted': [w for w in skip if not w.get('not_vocab')
                     and not w.get('suspect_name') and w.get('cross') == 'unlisted'],
    }
    if groups['work']:
        L.append(f"### 作品专有人名 / 概念（{len(groups['work'])} 个）")
        L.append('')
        L.append('跨作品没有通用性，跟着剧情记住即可。')
        L.append('')
        L.extend(_table(['词', '次数', '说明'],
                        [[w['word'], w['count'], w.get('cross_note') or '']
                         for w in sorted(groups['work'], key=lambda w: -w['count'])]))
        L.append('')
    if groups['name']:
        L.append(f"### 疑似人名 / 造语（{len(groups['name'])} 个）")
        L.append('')
        L.append('片假名而且词频表里排名很深或根本没有 —— 多半是角色名/自造词：'
                 + _inline(groups['name'], with_lemma=False))
        L.append('')
    if groups['inflection']:
        L.append(f"### 活用形碎片（{len(groups['inflection'])} 个）")
        L.append('')
        L.append('分词器把动词切成了活用形，原形你卡组里已经有一张卡了，不用另做：'
                 + _inline(groups['inflection']))
        L.append('')
    if groups['function']:
        gram = [w for w in groups['function'] if w.get('not_vocab') == 'grammar']
        ono = [w for w in groups['function'] if w.get('not_vocab') == 'onomatopoeia']
        L.append(f"### 功能词 / 拟声（{len(groups['function'])} 个）")
        L.append('')
        if gram:
            L.append(f'语法性功能词 {len(gram)} 个（不是词汇量问题）：'
                     f'{_inline(gram, with_lemma=False)}')
            L.append('')
        if ono:
            L.append(f'拟声 / 感叹 {len(ono)} 个（属听力反应）：'
                     f'{_inline(ono, with_lemma=False)}')
            L.append('')
    if groups['unlisted']:
        L.append(f"### 未收录（{len(groups['unlisted'])} 个）")
        L.append('')
        L.append(f'词频表和卡组都没有：{_inline(groups["unlisted"])}')
        L.append('')
        L.append('多为词典漏收的合成词或生造词；确实想学的把它加进'
                 ' `data/vocab_cover/genre_lexicon.json` 就会转成「值得挖」。')
        if pending_path:
            L.append('')
            L.append(f'> 待判定清单：`{_rel(pending_path)}`（把这些词判成 通用词 / 作品专有 / 拟声 /'
                     f'不挖 后 `--apply-decisions` 回写词表，之后同类词全自动）')
    return L


def render_episodes(sources: list, ep_top: int, with_example: bool,
                    ex_width: int) -> list:
    if len(sources) < 2:
        return []
    L = ['## 6. 分集速览', '']
    rows = []
    for src in sources:
        s = src['summary']
        cc = s.get('cross_counts') or {}
        ep = f"第 {src['episode']:02d} 集" if src['episode'] is not None else src['file']
        unknown = sum(s['cat_types'].get(c, 0) for c in CATS)
        rows.append([ep, s['tokens_vocab'], s['types_vocab'], unknown,
                     cc.get('可挖', 0), _pct(s['understood_lenient'])])
    L.extend(_table(['集', '词汇词元', '词汇词种', '生词（词种）', '值得挖', '宽口径能懂'], rows))
    L.append('')
    for src in sources:
        s = src['summary']
        cc = s.get('cross_counts') or {}
        ep = f"第 {src['episode']:02d} 集" if src['episode'] is not None else src['file']
        unknown = sum(s['cat_types'].get(c, 0) for c in CATS)
        L.append(f'### {ep}')
        L.append('')
        L.append(f"卡组覆盖 {_pct(s['cover_deck'])} · 宽口径能懂 {_pct(s['understood_lenient'])}"
                 f" ｜ 生词 {unknown} 个词种（值得挖 {cc.get('可挖', 0)}）")
        L.append('')
        mine = sort_words([w for w in src['words'] if w.get('mine')])
        if not mine:
            L.append('（这一集没有值得挖的生词）')
            L.append('')
            continue
        shown = mine[:ep_top] if ep_top else mine
        headers = ['#', '词', '读音', '品詞', '次数', 'Jiten', '档']
        if with_example:
            headers.append('首例句')
        rows = []
        for i, w in enumerate(shown, 1):
            row = [i, _word_cell(w), w['reading'] or '', (w['pos'] or '').split('/')[0],
                   w['count'], w['jiten_rank'] or '—', crosswork.CrossWork.label(w)]
            if with_example:
                row.append(_cell((w['examples'] or [''])[0], ex_width))
            rows.append(row)
        L.extend(_table(headers, rows))
        if len(shown) < len(mine):
            L.append('')
            L.append(f'> 这一集还有 {len(mine) - len(shown)} 个，见数据文件的 sources 段。')
        L.append('')
    return L


# ------------------------------------------------------------------ 待判定清单
def pending_words(words: list, ep_map: dict) -> list:
    out = []
    for w in words:
        if w.get('not_vocab') or w.get('cross') != 'unlisted':
            continue
        forms = [w['word']] + ([w['lemma']] if w.get('lemma') else [])
        out.append({
            'word': w['word'], 'lemma': w.get('lemma') or '', 'reading': w.get('reading') or '',
            'pos': w.get('pos') or '', 'count': w['count'],
            'episodes': [f'{e:02d}' for e in ep_map.get(w['key'], [])],
            'examples': (w.get('examples') or [])[:2],
            'hints': {
                'katakana_only': all(crosswork.KATAKANA_RE.match(f) for f in forms),
                'sudachi_inflected': bool(w.get('lemma') and w['lemma'] != w['word']),
                'has_kanji': bool(KANJI_RE.search(w['word'])),
                'jiten_rank': w.get('jiten_rank'),
            },
        })
    return sorted(out, key=lambda d: (-d['count'], d['word']))


def apply_decisions(path: str, genre_path: str = '', work_path: str = '',
                    not_vocab_path: str = '') -> int:
    """把代理（或人）填好的 decisions 回写到三份词表。"""
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    work_key = data.get('work_key') or ''
    decisions = data.get('decisions') or {}
    if not decisions:
        print(f'[跳过] {path} 里没有 decisions。', file=sys.stderr)
        return 1

    def load(p):
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)

    genre_path = genre_path or crosswork.GENRE_JSON
    work_path = work_path or crosswork.WORK_JSON
    not_vocab_path = not_vocab_path or crosswork.NOT_VOCAB_JSON
    genre = load(genre_path)
    work = load(work_path)
    notv = load(not_vocab_path)
    cats = genre.setdefault('categories', {})
    works = work.setdefault('works', {})
    done = collections.Counter()

    for word, spec in decisions.items():
        spec = spec or {}
        kind = (spec.get('kind') or '').strip()
        word = word.strip()
        if not word or kind == '':
            done['skip'] += 1
            continue
        if kind == 'genre':
            cat = spec.get('category') or '学园・社会'
            entry = cats.setdefault(cat, {'kanji': [], 'words': []})
            entry.setdefault('words', [])
            if word not in entry['words']:
                entry['words'].append(word)
            done['genre'] += 1
        elif kind == 'work':
            if not work_key:
                print(f'[警告] 作品专有词 {word} 没有 work_key，跳过。', file=sys.stderr)
                continue
            works.setdefault(work_key, {})[word] = spec.get('reason') or '作品专有'
            done['work'] += 1
        elif kind in ('not_vocab', 'ignore'):
            group = spec.get('group') if spec.get('group') in ('grammar', 'onomatopoeia') \
                else ('ignored' if kind == 'ignore' else 'onomatopoeia')
            notv.setdefault(group, [])
            if word not in notv[group]:
                notv[group].append(word)
            done[group] += 1
        else:
            print(f'[警告] 未知 kind={kind!r}（{word}），跳过。', file=sys.stderr)

    for path_, obj in ((genre_path, genre), (work_path, work), (not_vocab_path, notv)):
        with open(path_, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.write('\n')
    print(f"回写完成：题材词 {done['genre']} · 作品专有 {done['work']} · "
          f"功能词 {done['grammar']} · 拟声 {done['onomatopoeia']} · "
          f"已判不挖 {done['ignored']} · 跳过 {done['skip']}")
    print('  改的是 ' + ' / '.join(_rel(p) for p in (genre_path, work_path, not_vocab_path))
          + '，重跑报告即可生效。')
    return 0


# ------------------------------------------------------------------ CLI
def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='生成「学习用」生词报告（Markdown + JSON）',
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('paths', nargs='*', help='文件或目录（.srt 按字幕解析，目录递归）')
    ap.add_argument('--text', help='直接给一段文字')
    ap.add_argument('--stdin', action='store_true', help='从标准输入读')
    ap.add_argument('--top', type=int, default=40, help='值得挖清单最多列几个（默认 40，0 = 全部）')
    ap.add_argument('--first-k', type=int, default=0, metavar='N',
                    help='只取每个作品的前 N 集（挖前几集的窗口，见 mine_window.py；0 = 全部）')
    ap.add_argument('--ep-top', type=int, default=15, help='分集速览每集最多列几个（默认 15）')
    ap.add_argument('--example-width', type=int, default=34, help='例句截断宽度（默认 34）')
    ap.add_argument('--no-example', action='store_true', help='表格里不要「首例句」列')
    ap.add_argument('--min-count', type=int, default=1, help='至少出现几次（默认 1）')
    ap.add_argument('--out', help='Markdown 输出路径（默认 docs/reports/<slug>_生词报告.md）')
    ap.add_argument('--json-out', help='JSON 输出路径（默认 data/vocab_cover/<slug>_生词.json）')
    ap.add_argument('--pending-out', help='待判定清单路径（默认 data/vocab_cover/pending_<slug>.json）')
    ap.add_argument('--no-files', action='store_true', help='只在控制台打印，不写文件')
    ap.add_argument('--stdout', action='store_true', help='把 Markdown 打到标准输出')
    ap.add_argument('--jiten', default=nw.JITEN_CSV, help='Jiten 动画词频表 CSV')
    ap.add_argument('--no-jiten', action='store_true', help='不读词频表（档位退化成「未收录」居多）')
    ap.add_argument('--common-max', type=int, default=5000, help='Jiten ≤ 该值算「通用」（默认 5000）')
    ap.add_argument('--name-rank', type=int, default=20000, help='片假名 + 排名 > 该值算疑似人名')
    ap.add_argument('--genre-lexicon', default=crosswork.GENRE_JSON, help='题材通用词表 JSON')
    ap.add_argument('--work-concepts', default=crosswork.WORK_JSON, help='作品专有词表 JSON')
    ap.add_argument('--not-vocab', default=crosswork.NOT_VOCAB_JSON, help='语法词/拟声表 JSON')
    ap.add_argument('--split-mode', default='A', choices=['A', 'B', 'C'], help='Sudachi 切分粒度')
    ap.add_argument('--state', default=STATE_JSON, help='换一份词汇快照 JSON')
    ap.add_argument('--apply-decisions', metavar='JSON',
                    help='把待判定清单里填好的 decisions 回写词表，然后退出')
    ap.add_argument('--quiet', action='store_true', help='不打印进度')
    return ap


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)


def _dump(path: str, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:                                      # noqa: BLE001
            pass
    args = build_argparser().parse_args()
    if args.apply_decisions:
        return apply_decisions(args.apply_decisions, args.genre_lexicon,
                               args.work_concepts, args.not_vocab)

    items = collect_sources(args)
    if not items:
        print('没有输入。用 paths / --text / --stdin 指定内容。', file=sys.stderr)
        return 2
    if not os.path.exists(args.state):
        print(f'[错误] 找不到词汇快照：{args.state}\n'
              f'        先跑 collect_vocab.py 生成（需要 Anki 开着）：\n'
              f'        python code/analysis/vocab_cover/collect_vocab.py', file=sys.stderr)
        return 2

    vocab = jp_tok.Vocabulary.load(args.state, split_mode=args.split_mode)
    jiten = {} if args.no_jiten else nw.load_jiten_ranks(args.jiten)
    cw = crosswork.CrossWork(genre_path=args.genre_lexicon, work_path=args.work_concepts,
                             not_vocab_path=args.not_vocab, common_max=args.common_max,
                             name_rank=args.name_rank)
    with_example = not args.no_example
    snap = snapshot_info(args.state)

    groups = group_by_work(items)
    if args.first_k:
        for key, group in list(groups.items()):
            keep = [it for it in group
                    if it['episode'] is None or it['episode'] <= args.first_k]
            if keep:
                groups[key] = keep
            else:
                del groups[key]
    single = len(groups) == 1
    for key, group in groups.items():
        title = group_title(key, group)
        slug = group_slug(key, group, title)
        sources = []
        for it in group:
            src = analyze_source(vocab, jiten, cw, it, 2 if with_example else 0)
            if args.min_count > 1:
                src['words'] = [w for w in src['words'] if w['count'] >= args.min_count]
            src['summary']['cross_counts'] = cw.counts(src['words'])
            sources.append(src)
        merged = nw._merge(sources)
        words = merged['words']
        cc = merged['summary'].get('cross_counts') or {}
        # 合并后的 core6000 覆盖率（newwords._merge 只合并了三项，这里按词元数加权补上）
        tot = sum(s['summary']['tokens'] for s in sources) or 1
        merged['summary']['cover_core6000'] = sum(
            s['summary'].get('cover_core6000', 0.0) * s['summary']['tokens']
            for s in sources) / tot
        ep_map = episodes_of_key(sources)
        pending = pending_words(words, ep_map)

        out_md = (args.out if args.out and single
                  else os.path.join(REPORT_DIR, f'{slug}_生词报告.md'))
        out_json = (args.json_out if args.json_out and single
                    else os.path.join(VC_DATA, f'{slug}_生词.json'))
        out_pending = (args.pending_out if args.pending_out and single
                       else os.path.join(VC_DATA, f'pending_{slug}.json'))
        if args.no_files:
            out_md = out_json = out_pending = ''

        L = [f'# {title} · 生词报告', '']
        eps = [s['episode'] for s in sources if s['episode'] is not None]
        unit = f'{len(eps)} 集' if eps else f'{len(group)} 个文件'
        L.append(f"> 素材：{unit} · {merged['summary']['sentences']} 句 · "
                 f"{merged['summary']['tokens_vocab']} 个词汇词元 · "
                 f"{merged['summary']['types_vocab']} 个词汇词种")
        if snap.get('generated_at'):
            L.append(f"> 词汇快照：{str(snap['generated_at'])[:16].replace('T', ' ')}"
                     f"（core6000 已学 {snap.get('core6000_studied')} / "
                     f"成熟 {snap.get('core6000_mature')}）")
        L.append('')
        L.extend(render_headline(title, merged['summary'], words, cc, len(group)))
        L.append('')
        L.extend(render_scale(merged['summary'], snap, len(group)))
        L.append('')
        L.extend(render_tiers(cc))
        L.append('')
        L.extend(render_genre(words, with_example, args.example_width))
        L.extend(render_mine(words, args.top, with_example, args.example_width, out_json))
        L.append('')
        L.extend(render_skip(words, out_pending if pending else ''))
        L.append('')
        L.extend(render_episodes(sources, args.ep_top, with_example, args.example_width))
        md = re.sub(r'\n{3,}', '\n\n', '\n'.join(L).rstrip()) + '\n'

        data = {
            'generated_at': _now(), 'title': title, 'slug': slug, 'work_key': key,
            'snapshot': snap, 'counts': cc, 'pending_count': len(pending),
            'sources': sources, 'merged': merged,
        }
        if out_md:
            _write(out_md, md)
        if out_json:
            data['outputs'] = {'markdown': out_md, 'json': out_json,
                               'pending': out_pending if pending else ''}
            _dump(out_json, data)
        if pending and out_pending:
            _dump(out_pending, {
                'work_key': key, 'title': title, 'generated_at': _now(),
                'count': len(pending),
                'howto': '把每个词的结论填进 decisions（kind: genre/work/not_vocab/ignore），'
                         '再跑 newword_report.py --apply-decisions <本文件>',
                'decisions': {}, 'words': pending,
            })
        if args.stdout:
            sys.stdout.write(md)
        if not args.quiet:
            unknown = len(words)
            print(f'■ {title}')
            print(f"  还不认识 {unknown} 个词种 · 值得挖 {cc.get('可挖', 0)} · "
                  f"不用记 {unknown - cc.get('可挖', 0)} · 待判定 {len(pending)}")
            if out_md:
                print(f'  报告 {os.path.relpath(out_md, WSP.ROOT)}')
            if out_json:
                print(f'  数据 {os.path.relpath(out_json, WSP.ROOT)}')
            if pending and out_pending:
                print(f'  待判定 {os.path.relpath(out_pending, WSP.ROOT)}'
                      f'（{len(pending)} 个词；需要时派一个代理判定后 --apply-decisions）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
