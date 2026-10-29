# -*- coding: utf-8 -*-
"""每天从一整部作品的字幕里挑 30 个「今天要学」的词，只打一个标签 ``今天学习生词``。

它解决的是什么
------------
「今天学哪 N 个词」每天都要重新决定。2026-10-29 起口径改成**一个连续打分公式**，
不再维护 A/B/D/E 分池表：

1. **统计窗口 = 整部作品**（同目录所有字幕，含还没看的集）。给一集字幕，脚本会
   把同目录其它集一起扫掉，用来算「出现次数」和「跨了几集」。
2. **候选 = Anki 已有、且至少有一张未学笔记的词**。
   「学过」按**笔记**判断：同一词形下，已学的那张排除，别的未学笔记照选照标。
3. **打分**（纯代码，无模型）::

       S = ln(1+occ) + MU*ln(1+eps) + LAM*ln(JAR_MAX/JAR)

   等价乘积形式 ``(1+occ) * (1+eps)^MU * (JAR_MAX/JAR)^LAM``。

   * ``occ`` 本作出现次数，``eps`` 出现集数，``JAR`` JitenAnimeRank（越小越常见）；
   * 三者都取对数：次数与排名都是重尾分布，线性相加会被量纲吃掉；
   * **参数是可换算的**：次数翻倍 = ``ln2``，JAR 前移 k 倍 = ``LAM*ln k``。
     令两者相等得 ``k = 2**(1/LAM)``——默认 ``LAM=0.3`` 即「次数翻一倍 ≈
     JAR 排名前移 10 倍」；
   * JAR 是**次级加分 + 同分排序器**，不是主项：JAR 300 以内多是 おっ / くっ /
     やっぱ 这类填词，LAM 拉到 0.8 会把它们顶到第 1 名；
   * ``MU`` 按集数轻微折价：一集里念 11 遍 ≠ 跨 4 集念 6 遍（后者语境更多）。

4. **取 N 个词**：按分数降序取前 N。名额按**词**算；一个词名下的未学笔记全部
   打标签，所以标签数可能多于 N。候选不足 N 时有几个取几个，**不硬凑**。
5. **JAR 门槛**：只处理 ``1 ≤ JAR ≤ 30000`` 的词；无排名（空 / 0 / 999999）与
   JAR >30000 的一律排除（``--max-jar 0`` 可关掉这个门槛）。
6. **不去重**：复合词各自独立（``魔神`` / ``魔神族`` 都算候选），同词多写法也不合并。
7. **全量替换**：先把全库旧的 ``今天学习生词`` 摘掉，再给今天选中的打上。
8. **词性过滤默认关**：``--drop-phrases`` 才会挡掉 Anki 标为惯用句/成句/词缀/
   代词的词（会连带挡掉 おっ / にゃあ 这类想学的词，所以不默认）。

边界
----
* 只写 ``tags``：**不碰** ``due`` / ``ivl`` / ``factor`` / ``type`` / ``queue`` / ``reps`` / ``lapses``；
* 不改任何字段、不改牌组、不建卡、不配音、不动 ``3-专有词汇``；
* 默认演练，显式 ``--commit`` 才真写。

用法
----
::

    # 演练（默认，不写库）：给一集，自动按同目录整季统计
    $PY code\\tools\\today_new_words.py "字幕.srt"

    # 真写
    $PY code\\tools\\today_new_words.py "字幕.srt" --n 30 --commit

    # 给整个目录
    $PY code\\tools\\today_new_words.py "subtitles\\Yani Neko" --commit

    # 纯文本（不扩展同目录，集数按 1 算）
    $PY code\\tools\\today_new_words.py "note.txt" --commit
    Get-Content draft.txt -Encoding UTF8 | & $PY code\\tools\\today_new_words.py - --commit

    # 只清空 / 撤销
    $PY code\\tools\\today_new_words.py --clear --commit
    $PY code\\tools\\today_new_words.py --revert --commit

    # 调权重：次数权重固定为 1，mu 管集数、lam 管 JAR
    $PY code\\tools\\today_new_words.py "字幕.srt" --lam 0.5      # 更看重高频词
    $PY code\\tools\\today_new_words.py "字幕.srt" --mu 0         # 不看跨集

产物
----
* ``data/daily_new/<日期>/picked.json`` —— 本次入选词 / 分数拆解 / 笔记 id（讲义据此排顺序）
* ``output/daily/today_new_words.md`` —— 给人看的稳定路径报告
* ``data/daily_new/state.json`` —— 回退记录（运行前 / 运行后的 noteId 集合）
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, _HERE)

import anki_api as AK            # noqa: E402  Anki 唯一通道
import jp_decks as JD            # noqa: E402  牌组常量
import paths as WSP              # noqa: E402  工作区路径
import textio                    # noqa: E402  UTF-8 唯一入口
import subtitle_new_words as SW  # noqa: E402  字幕解析 / 分词 / 词表匹配

# ============================================================================
# 配置
# ============================================================================
TAG = '今天学习生词'
UNRANKED = 999999
DEFAULT_N = 30
DEFAULT_MAX_JAR = 30000
JAR_MAX = 30000             # 公式里的 JAR 参照上限（与 DEFAULT_MAX_JAR 同值）
DEFAULT_MU = 0.3            # 集数项权重
DEFAULT_LAM = 0.3           # JAR 项权重：2**(1/0.3) ≈ 10
SCOPES = (JD.DECK_MINED, JD.DECK_CORE6000, JD.DECK_KAOKYU)   # 三个词汇卡组
SUBTITLE_EXT = ('.srt', '.vtt', '.ass', '.ssa')
PARTICLE_POS = ('助詞', '感動詞')      # 放开助词的词性（默认每个这类词单独占名额）
# 这些助词子类是语法胶水，没有可讲的词义，不进候选（が/で/を/は/も/から…）
PARTICLE_SKIP_POS1 = ('格助詞', '係助詞', '接続助詞', '準体助詞', '終助詞-接続')
DEFAULT_PARTICLES = 2                 # 每天最多带出几个助词/感动词（0 = 关闭）
DATA_ROOT = os.path.join(WSP.DATA, 'daily_new')
STATE_PATH = os.path.join(DATA_ROOT, 'state.json')
REPORT_PATH = os.path.join(WSP.OUTPUT, 'daily', 'today_new_words.md')


# ============================================================================
# 纯函数（不碰 Anki，测试直接喂）
# ============================================================================
def rank_of(word, index):
    """该词所有笔记里的最小 JitenAnimeRank；没有（或 999999）→ UNRANKED。"""
    best = UNRANKED
    for e in index.entries.get(word, ()):
        try:
            j = int(e.jiten or UNRANKED)
        except (TypeError, ValueError):
            j = UNRANKED
        if 0 < j < best:
            best = j
    return best


def notes_of(word, index):
    """词形 → {noteId: [这条笔记的卡]}（一个 note 可能有多张卡）。"""
    out = {}
    for e in index.entries.get(word, ()):
        out.setdefault(int(e.note_id), []).append(e)
    return out


def note_state(cards):
    """一条笔记的状态：任一卡已学 → learned；全部卡挂起 → suspended；否则 new。

    「已学」按笔记判断：同词里已学的那张不该拖累还没学的那张。
    """
    if any(int(c.type) != 0 for c in cards):
        return 'learned'
    if all(int(c.queue) == -1 for c in cards):
        return 'suspended'
    return 'new'


def norm_reading(s):
    """读音归一化：片假名→平假名、去空格。比较读音必须走这一条。"""
    return SW.kata2hira((s or '').replace(' ', '').replace('\u3000', ''))


_READ_SPLIT = re.compile(r'[,、;；/／|｜]+')
_PAREN = re.compile(r'[（(][^）)]{0,24}[）)]')
_KANA_ONLY_CHARS = re.compile(r'[^ぁ-ゖァ-ヺー]')


def card_readings(s):
    """卡片读音字段 → 可能的读音集合。

    真实数据很脏：``から,そら``（多读音）、``(オ) bier,びーる``（带英文）、
    ``くちこたえ``（漏浊点）。这里按分隔符拆、去括号、只留假名，
    拆完为空就当「没写读音」，不参与比较。
    """
    out = set()
    for part in _READ_SPLIT.split(s or ''):
        p = _PAREN.sub('', part)
        p = _KANA_ONLY_CHARS.sub('', norm_reading(p))
        if p:
            out.add(p)
    return out


def reading_ok(entry_reading, observed):
    """卡片的读音和字幕里的读音是否对得上。

    ``頭`` 名下挂着两张卡：``あたま``（头）和 ``かしら``（首领）。字幕说
    ``あたま`` 时只能标前者；不看读音就会把「首领」那张一起标上。
    卡片没写读音（或只有英文）时**放行**——判不了，不误杀。
    """
    cands = card_readings(entry_reading)
    if not cands or not observed:
        return True
    return bool(cands & set(observed))


def new_note_ids(word, index, observed=None):
    """该词名下「没学过、也没挂起、读音对得上」的笔记 id（升序）。"""
    out = []
    for nid, cards in notes_of(word, index).items():
        if note_state(cards) != 'new':
            continue
        if observed and not reading_ok(getattr(cards[0], 'reading', ''), observed):
            continue
        out.append(nid)
    return sorted(out)


def dropped_reading_notes(word, index, observed):
    """因读音对不上被排除的 (noteId, 卡片读音)。"""
    out = []
    for nid, cards in notes_of(word, index).items():
        if note_state(cards) != 'new':
            continue
        er = getattr(cards[0], 'reading', '')
        if observed and not reading_ok(er, observed):
            out.append((nid, er))
    return out


def score_parts(occurrences, episodes, jar, mu=DEFAULT_MU, lam=DEFAULT_LAM,
                jar_max=JAR_MAX):
    """分数拆解 → (次数项, 集数项, 频率项)。JAR 被夹在 1..jar_max。"""
    occ = math.log1p(max(0, int(occurrences)))
    eps = float(mu) * math.log1p(max(0, int(episodes)))
    j = int(jar) if jar else jar_max
    j = min(max(j, 1), int(jar_max))
    freq = float(lam) * math.log(float(jar_max) / j)
    return occ, eps, freq


def score_of(occurrences, episodes, jar, mu=DEFAULT_MU, lam=DEFAULT_LAM,
             jar_max=JAR_MAX):
    """S = ln(1+occ) + mu*ln(1+eps) + lam*ln(jar_max/JAR)。"""
    return sum(score_parts(occurrences, episodes, jar, mu, lam, jar_max))


def flip_ratio(lam=DEFAULT_LAM):
    """次数翻一倍 ≈ JAR 排名前移多少倍：k = 2**(1/lam)。"""
    return math.inf if not lam else 2 ** (1.0 / float(lam))


def item_key(item):
    """排序：分数降序 → 词形（同分时稳定，不随字典顺序抖动）。"""
    return (-float(item.get('score') or 0.0), item['word'])


def pick_top(items, n):
    """按分数取前 n 个词；候选不足就少取，不硬凑。"""
    return sorted(items, key=item_key)[:max(0, int(n))]


def diff_ids(old_ids, new_ids):
    """旧标签集合 vs 今天入选集合 → 摘除 / 保留 / 新增。"""
    old, new = set(int(x) for x in old_ids), set(int(x) for x in new_ids)
    return {
        'old': sorted(old),
        'new': sorted(new),
        'remove': sorted(old - new),
        'keep': sorted(old & new),
        'add': sorted(new - old),
    }


def fmt_rank(r):
    return '—' if int(r or UNRANKED) >= UNRANKED else str(int(r))


# ============================================================================
# 候选：整部作品扫一遍
# ============================================================================
def episode_sources(path):
    """输入 → [(标签, 路径)]。

    字幕（.srt/.vtt/.ass/.ssa）**扩展到同目录整季**（统计窗口 = 整部作品）；
    纯文本 / stdin 只算这一份（集数按 1 算）。子目录（如 ``anki/``）不扫，
    避免同一集被数两遍。
    """
    if path == '-':
        return [('-', '-')]

    if os.path.isdir(path):
        files = [os.path.join(path, n) for n in sorted(os.listdir(path))
                 if os.path.splitext(n)[1].lower() in SUBTITLE_EXT
                 and os.path.isfile(os.path.join(path, n))]
    else:
        ext = os.path.splitext(path)[1].lower()
        if ext in SUBTITLE_EXT:
            folder = os.path.dirname(os.path.abspath(path))
            files = [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                     if os.path.splitext(n)[1].lower() in SUBTITLE_EXT
                     and os.path.isfile(os.path.join(folder, n))]
            if os.path.abspath(path) not in {os.path.abspath(f) for f in files}:
                files.insert(0, path)
        else:
            files = [path]

    if not files:
        raise SystemExit('没有找到字幕文件：%s' % path)
    return [(os.path.splitext(os.path.basename(f))[0], f) for f in files]


def collect_stats(sources, index, include_names=False, extra_pos=()):
    """逐集统计 → {词形: {occ, eps, first, examples, readings, pos}}（只统计已在词库里的词）。

    ``readings`` 存的是**词典形读音**（``取り戻した`` → ``とりもどす``），不是活用形读音：
    卡片上的 ``Transliteration`` 写的是词典形，拿活用形去比会整批对不上。
    """
    stats = {}
    lemma_read = {}
    for label, path in sources:
        cues = SW.load_cues(path)
        for cue in cues:
            for h in SW.find_hits(cue.text, index, include_names=include_names,
                                  extra_pos=extra_pos):
                if not include_names and h.name_like:
                    continue
                rec = stats.setdefault(h.word, {
                    'occ': 0, 'eps': set(), 'first': None, 'examples': [],
                    'readings': set(), 'pos': h.pos0, 'pos1': h.pos1,
                })
                rec['occ'] += 1
                rec['eps'].add(label)
                if h.pos0 and not rec.get('pos'):
                    rec['pos'] = h.pos0
                if h.pos1 and not rec.get('pos1'):
                    rec['pos1'] = h.pos1
                if not rec['readings']:
                    if h.word not in lemma_read:
                        lemma_read[h.word] = SW.word_reading(h.word) or h.reading
                    if lemma_read[h.word]:
                        rec['readings'].add(lemma_read[h.word])
                if rec['first'] is None:
                    rec['first'] = {'episode': label, 'index': cue.index,
                                    'start': cue.start, 'text': cue.text}
                if (len(rec['examples']) < 3
                        and all(e['text'] != cue.text for e in rec['examples'])):
                    rec['examples'].append({'episode': label, 'index': cue.index,
                                            'start': cue.start, 'text': cue.text})
    return stats


def build_candidates(stats, index, max_jar=DEFAULT_MAX_JAR, mu=DEFAULT_MU,
                     lam=DEFAULT_LAM, drop_phrases=False):
    """统计 → 候选词（JAR 在范围内、有未学笔记）→ (items, skipped)。"""
    items, skipped = [], {'jar': [], 'no_notes': [], 'phrases': [], 'reading': []}
    for word, st in stats.items():
        jar = rank_of(word, index)
        if max_jar and int(max_jar) > 0 and jar > int(max_jar):
            skipped['jar'].append(word)
            continue
        if drop_phrases:
            ents = index.entries.get(word) or ()
            if ents and all(SW._bad_anki_pos(getattr(e, 'pos', '')) for e in ents):
                skipped['phrases'].append(word)
                continue
        groups = notes_of(word, index)
        observed = {norm_reading(r) for r in (st.get('readings') or ())} - {''}
        is_particle = (st.get('pos') or '') in PARTICLE_POS
        if is_particle and (st.get('pos1') or '') in PARTICLE_SKIP_POS1:
            # 格助词/係助词/接续助词是语法胶水，没有可讲的词义
            skipped.setdefault('glue', []).append(word)
            continue
        nids = sorted(nid for nid, cards in groups.items()
                      if note_state(cards) == 'new'
                      and reading_ok(getattr(cards[0], 'reading', ''), observed))
        pending = False
        if not nids:
            if is_particle:
                # 助词/感动词库里基本没有卡：先带出来，等建卡流程处理
                pending = True
            elif groups and all(note_state(c) != 'new' for c in groups.values()):
                skipped['no_notes'].append(word)
                continue
            else:
                skipped['reading'].append(word)
                continue
        eps = len(st['eps'])
        occ = st['occ']
        items.append({
            'word': word,
            'kind': 'particle' if is_particle else 'word',
            'pending': pending,
            'pos0': st.get('pos') or '',
            'jiten': jar,
            'occurrences': occ,
            'episodes': eps,
            'first': st['first'],
            'examples': st['examples'],
            'score': score_of(occ, eps, jar, mu=mu, lam=lam),
            'notes': nids,
            'readings': sorted(observed),
            'dropped_readings': dropped_reading_notes(word, index, observed),
            'note_cards': {nid: sorted(int(c.card_id) for c in groups[nid])
                           for nid in nids},
        })
    return items, skipped


def plan_pick(items, n, particles=0):
    """候选 → (入选词, 全量排序后的候选)。

    ``particles`` 是助词/感动词单独的名额：它们频次极高（`ね` 一期上百次），
    放进同一个池会把内容词全部挤掉，所以按词性分两路取，再按分数合并显示。
    """
    words = [it for it in items if it.get('kind') != 'particle']
    parts = [it for it in items if it.get('kind') == 'particle']
    words.sort(key=item_key)
    parts.sort(key=item_key)
    picked = words[:max(0, int(n))] + parts[:max(0, int(particles))]
    ranked = sorted(picked + words[max(0, int(n)):] + parts[max(0, int(particles)):],
                    key=item_key)
    return picked, ranked


def describe(item, index):
    """给入选词补展示字段：读音用词典形，牌组/级别取代表笔记。"""
    groups = notes_of(item['word'], index)
    entries = [c for nid in item['notes'] for c in groups.get(nid, ())]
    # 代表作优先取「读音与字幕一致」的那张，避免 `頭` 显示成「かしら」
    observed = {norm_reading(r) for r in (item.get('readings') or ())} - {''}
    e0 = next((c for c in entries
               if not observed or norm_reading(c.reading) in observed),
              entries[0] if entries else None)
    item['reading'] = SW.word_reading(item['word']) or (e0.reading if e0 else '')
    item['pos'] = e0.pos if e0 else ''
    item['deck'] = e0.deck if e0 else ''
    item['level'] = e0.level if e0 else ''
    return item


# ============================================================================
# 现场复核
# ============================================================================
def live_check(picked):
    """按笔记回读：卡还在、全是新卡、没挂起。→ (保留, [(词, noteId, 原因)])。"""
    cids = {nid: c for it in picked for nid, c in it['note_cards'].items()}
    all_cids = [cid for v in cids.values() for cid in v]
    info = {int(c['cardId']): c for c in (AK.cards_info(all_cids) if all_cids else [])}
    kept, dropped = [], []
    for it in picked:
        live = []
        for nid in it['notes']:
            cards = [info.get(int(cid)) for cid in cids.get(nid, [])]
            if not cards or any(c is None for c in cards):
                dropped.append((it['word'], nid, '卡已不存在'))
                continue
            if any(int(c['type']) != 0 for c in cards):
                dropped.append((it['word'], nid, '已不是新卡'))
                continue
            if all(int(c['queue']) == -1 for c in cards):
                dropped.append((it['word'], nid, '已挂起'))
                continue
            live.append(nid)
        if live:
            it['notes'] = live
            kept.append(it)
        else:
            dropped.append((it['word'], None, '没有可用笔记'))
    return kept, dropped


def tagged_note_ids():
    return sorted(int(x) for x in AK.find_notes('tag:"%s"' % TAG))


# ============================================================================
# 输出
# ============================================================================
def _first_text(w, limit=40):
    text = ((w.get('first') or {}).get('text') or '').replace('\n', ' ')
    return text if len(text) <= limit else text[:limit] + '…'


def print_picked(items):
    if not items:
        return
    print('')
    print('今天要学的词（按分数降序；分=次数项+集数项+频率项）：')
    for i, w in enumerate(items, 1):
        first = _first_text(w)
        print('  %2d. %-10s %-12s JAR %-6s ｜%2d 次/%d 集｜分 %.2f｜%d 张笔记%s'
              % (i, w['word'], w.get('reading') or '—', fmt_rank(w.get('jiten')),
                 int(w.get('occurrences') or 0), int(w.get('episodes') or 0),
                 float(w.get('score') or 0), len(w.get('notes') or []),
                 ('｜「%s」' % first) if first else ''))


def _score_rule(mu, lam):
    return ('S = ln(1+次数) + %.2f*ln(1+集数) + %.2f*ln(%d/JAR)'
            '（次数翻一倍 ≈ JAR 前移 %.0f 倍）'
            % (mu, lam, JAR_MAX, flip_ratio(lam)))


def _report_md(source, picked, dropped, plan, n, counts, sense_dropped=None):
    lines = [
        '# 今天学习生词 · %s' % dt.date.today().isoformat(),
        '',
        '- 来源：`%s`' % source,
        '- 生成：%s' % dt.datetime.now().isoformat(timespec='seconds'),
        '- 窗口：%d 集；候选词 %d 个' % (counts['episodes'], counts['candidates']),
        '- 入选：%d 个词 / %d 张笔记（上限 %d 个词）'
        % (len(picked), sum(len(w['notes']) for w in picked), n),
        '- 旧标签：%d 个（保留 %d / 摘除 %d）；本次新增 %d'
        % (len(plan['old']), len(plan['keep']), len(plan['remove']), len(plan['add'])),
        '- 公式：%s' % _score_rule(counts['mu'], counts['lam']),
    ]
    if counts.get('score_top') is not None:
        lines.append('- 分数：入选最高 %.2f / 最低 %.2f%s'
                     % (counts['score_top'], counts['score_min'],
                        ('；第 %d 名 %.2f' % (n + 1, counts['score_next']))
                        if counts.get('score_next') is not None else ''))
    lines += [
        '',
        '## 今天要学',
        '',
        '| # | 词 | 读音 | 分 | JAR | 次数 | 集数 | 笔记 | 首句 |',
        '|---|---|---|---:|---:|---:|---:|---:|---|',
    ]
    for i, w in enumerate(picked, 1):
        lines.append('| %d | %s | %s | %.2f | %s | %d | %d | %d | %s |' % (
            i, w['word'], w.get('reading') or '', float(w.get('score') or 0),
            fmt_rank(w.get('jiten')),
            int(w['occurrences']), int(w['episodes']), len(w['notes']),
            _first_text(w, 60).replace('|', '\\|')))
    lines.append('')
    if sense_dropped:
        lines += ['## 义项核验被剔除', '',
                  '卡片释义与这句字幕里该词的义项对不上，先不打 tag（卡片本身可能需要改）。', '',
                  '| 词 | 卡片释义 | 字幕句 | 字幕义项 | 理由 |',
                  '|---|---|---|---|---|']
        for d in sense_dropped:
            lines.append('| %s | %s | %s | %s | %s |' % (
                d['word'], d['card_meaning'] or '—', (d['sentence'] or '')[:40],
                d['sense_gloss'] or '—', d['why'] or ''))
        lines += ['']
    if dropped:
        lines += ['## 现场复核被剔除', '']
        for word, nid, why in dropped:
            lines.append('- %s%s：%s' % (word, '' if nid is None else '（note %s）' % nid, why))
        lines += ['']
    if counts.get('skipped_jar'):
        lines += ['> 另有 %d 个词因 JAR 超出 1–%d 未参与选择。'
                  % (counts['skipped_jar'], counts.get('max_jar') or JAR_MAX), '']
    if counts.get('skipped_notes'):
        lines += ['> 另有 %d 个词没有未学笔记（已学/已挂起），未参与选择。'
                  % counts['skipped_notes'], '']
    if counts.get('skipped_reading'):
        lines += ['> 另有 %d 个词的笔记读音与字幕读音对不上（例如 `頭` 名下挂着'
                  '「かしら＝首领」那张卡，字幕说的是「あたま」），这些笔记未打 tag。'
                  % counts['skipped_reading'], '']
    if counts.get('skipped_phrases'):
        lines += ['> 另有 %d 个词因词性为惯用句/词缀/代词被 --drop-phrases 过滤。'
                  % counts['skipped_phrases'], '']
    lines += [
        '> 回退：`python code\\tools\\today_new_words.py --revert --commit`',
        '> 清空：`python code\\tools\\today_new_words.py --clear --commit`',
        '',
    ]
    return '\n'.join(lines)


def write_outputs(source, picked, dropped, plan, n, counts, sense_dropped=None):
    today = dt.date.today().isoformat()
    out_dir = os.path.join(DATA_ROOT, today)
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, 'picked.json')
    textio.dump_json({
        'tag': TAG,
        'source': source,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'n': n,
        'counts': counts,
        'formula': {'mu': counts['mu'], 'lam': counts['lam'], 'jar_max': JAR_MAX,
                    'flip_ratio': flip_ratio(counts['lam'])},
        'plan': {'old': len(plan['old']), 'keep': len(plan['keep']),
                 'remove': len(plan['remove']), 'add': len(plan['add'])},
        'picked': [{
            'word': w['word'], 'reading': w.get('reading') or '',
            'pos': w.get('pos') or '', 'deck': w.get('deck') or '',
            'level': w.get('level') or '',
            'score': round(float(w.get('score') or 0), 4),
            'score_parts': [round(x, 4) for x in score_parts(
                w['occurrences'], w['episodes'], w['jiten'], counts['mu'],
                counts['lam'])],
            'sense': int(w.get('sense') or 0),
            'card_ok': w.get('card_ok'),
            'sense_why': w.get('sense_why') or '',
            'occurrences': int(w['occurrences']), 'episodes': int(w['episodes']),
            'jiten': int(w['jiten']),
            # 兼容旧的「一个词一张卡」消费者：noteId = 第一张笔记
            'noteId': int(w['notes'][0]), 'cardId': int(w['note_cards'][w['notes'][0]][0]),
            'notes': [int(x) for x in w['notes']],
            'first': w.get('first'),
        } for w in picked],
        'dropped': [{'word': word, 'noteId': nid, 'reason': why}
                    for word, nid, why in dropped],
        'dropped_sense': sense_dropped,
    }, json_path)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    textio.write_text(REPORT_PATH, _report_md(source, picked, dropped, plan, n,
                                              counts, sense_dropped))
    return json_path, REPORT_PATH


# ============================================================================
# 主流程
# ============================================================================
def sense_filter(picked, ranked, n, index, buffer=15, quiet=False):
    """义项核验：卡片释义和字幕句义项对不上的词剔掉，用后面的词补位。

    只有模型明确判 ``False`` 才剔；词典查不到 / 模型判不了 → 放行（``None``）。
    → (保留的词, 被剔的记录)
    """
    import sense_gate as SG

    pool = ranked[:max(int(n), len(picked)) + int(buffer)]
    rows = SG.to_inputs(pool, index)
    if not rows:
        return picked, []
    results = SG.judge([r['input'] for r in rows], quiet=quiet)

    bad, dropped = {}, []
    for row, res in zip(rows, results):
        it = row['item']
        it['sense'] = res.get('sense') or 0
        it['card_ok'] = res.get('card_ok')
        it['sense_why'] = res.get('why') or ''
        if res.get('card_ok') is False:
            sense = it['sense']
            gloss = ''
            if 0 < sense <= len(row['senses']):
                gloss = '；'.join(row['senses'][sense - 1]['glosses'][:3])
            bad[it['word']] = True
            dropped.append({
                'word': it['word'],
                'card_meaning': row['input']['card_meaning'],
                'sentence': row['input']['sentence'],
                'sense_gloss': gloss,
                'why': it['sense_why'],
            })
    kept = [it for it in pool if it['word'] not in bad][:int(n)]
    return kept, dropped


def do_pick(a):
    index = SW.VocabIndex.load(scopes=SCOPES)
    sources = episode_sources(a.input)
    stats = collect_stats(sources, index, include_names=a.include_names,
                          extra_pos=PARTICLE_POS if a.particles > 0 else ())
    items, skipped = build_candidates(stats, index, a.max_jar, mu=a.mu, lam=a.lam,
                                      drop_phrases=a.drop_phrases)
    picked, ranked = plan_pick(items, a.n, particles=a.particles)
    pending = [w for w in picked if not w.get('notes')]
    picked = [w for w in picked if w.get('notes')]

    sense_dropped = []
    if a.sense_check and picked:
        before = [w['word'] for w in picked]
        picked, sense_dropped = sense_filter(picked, ranked, a.n, index, quiet=False)
        if sense_dropped:
            print('')
            print('义项核验：剔掉 %d 个词（卡片释义与字幕句对不上）'
                  % len(sense_dropped))
            for d in sense_dropped:
                print('  ⛔ %-10s 卡片「%s」｜句子「%s」｜%s'
                      % (d['word'], (d['card_meaning'] or '—')[:14],
                         (d['sentence'] or '')[:20], d['why']))
            after = {w['word'] for w in picked}
            filled = [w['word'] for w in picked if w['word'] not in before]
            if filled:
                print('  补位：%s' % '、'.join(filled))
            elif len(after) < a.n:
                print('  补位不足：最终 %d 个词' % len(after))

    counts = {
        'episodes': len(sources),
        'candidates': len(items),
        'picked': len(picked),
        'notes': sum(len(w['notes']) for w in picked),
        'skipped_jar': len(skipped['jar']),
        'skipped_notes': len(skipped['no_notes']),
        'skipped_phrases': len(skipped['phrases']),
        'skipped_reading': len(skipped['reading']),
        'sense_dropped': len(sense_dropped),
        'particles': len(pending),
        'max_jar': a.max_jar,
        'mu': a.mu,
        'lam': a.lam,
        'occ5': sum(1 for w in items if w['occurrences'] >= 5),
        'eps3': sum(1 for w in items if w['episodes'] >= 3),
        'jar4k': sum(1 for w in items if w['jiten'] <= 4000),
        'score_top': round(max(float(w['score']) for w in picked), 2) if picked else None,
        'score_min': round(min(float(w['score']) for w in picked), 2) if picked else None,
        'score_next': next((round(float(w['score']), 2) for w in ranked
                            if w.get('kind') != 'particle'
                            and w['word'] not in {p['word'] for p in picked}), None),
    }

    print('来源：%s' % a.input)
    print('窗口：%d 集（同目录整部作品）' % counts['episodes'])
    print('候选：%d 个词（JAR 1–%d、有未学笔记）' % (counts['candidates'], a.max_jar))
    print('  排除：JAR 超范围 %d / 没有未学笔记 %d / 读音对不上 %d'
          % (counts['skipped_jar'], counts['skipped_notes'],
             counts['skipped_reading']))
    print('公式：%s' % _score_rule(a.mu, a.lam))
    print('分布：出现≥5 %d 个 / 跨集≥3 %d 个 / JAR≤4000 %d 个'
          % (counts['occ5'], counts['eps3'], counts['jar4k']))
    print('入选：%d 个词 / %d 张笔记（上限 %d 个词）'
          % (len(picked), counts['notes'], a.n))

    if not picked:
        print('')
        print('没有可选的词：本次不改库，旧的「%s」原样保留。' % TAG)
        print('（若确实要清空，显式加 --clear --commit。）')
        return 2

    picked, dropped = live_check(picked)
    if dropped:
        print('')
        print('现场复核剔除：')
        for word, nid, why in dropped[:20]:
            print('  ⛔ %-10s %s%s' % (word, '' if nid is None else '（note %s）' % nid, why))
        if len(dropped) > 20:
            print('  … 共 %d 条' % len(dropped))
    if not picked:
        print('')
        print('现场复核后没有可用的词：本次不改库。')
        return 2

    counts['notes'] = sum(len(w['notes']) for w in picked)
    for w in picked:
        describe(w, index)

    notes = [nid for w in picked for nid in w['notes']]
    plan = diff_ids(tagged_note_ids(), notes)

    print_picked(picked)
    if pending:
        print('')
        print('本作高分助词/感动词（库里没有卡，待建卡；名额 %d）：' % a.particles)
        for w in pending:
            print('  ＊ %-8s ｜%d 次/%d 集｜分 %.2f｜「%s」'
                  % (w['word'], int(w['occurrences']), int(w['episodes']),
                     float(w['score'] or 0),
                     ((w.get('first') or {}).get('text') or '')[:24]))
    print('')
    if counts['score_min'] is not None:
        print('分数：入选最高 %.2f / 最低 %.2f%s'
              % (counts['score_top'], counts['score_min'],
                 ('；第 %d 名 %.2f' % (a.n + 1, counts['score_next']))
                 if counts['score_next'] is not None else ''))
    print('旧标签：%d 个；保留 %d；摘除 %d；新增 %d'
          % (len(plan['old']), len(plan['keep']),
             len(plan['remove']), len(plan['add'])))
    print('')
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    if not a.commit:
        print('演练结束，未写库。')
        return 0

    # 写库前留退路：先记下运行前的标签集合，再动库。
    textio.dump_json({
        'tag': TAG,
        'source': a.input,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'n': a.n,
        'before': plan['old'],
        'after': plan['new'],
        'words': [{'word': w['word'], 'notes': [int(x) for x in w['notes']]}
                  for w in picked],
    }, STATE_PATH)

    if plan['remove']:
        AK.remove_tags(plan['remove'], [TAG])
    if plan['add']:
        AK.add_tags(plan['add'], [TAG])

    after = tagged_note_ids()
    ok = set(after) == set(plan['new'])
    print('')
    print('=' * 88)
    print('写入结果')
    print('=' * 88)
    print('  摘除 %d 个；新增 %d 个；当前「%s」共 %d 个'
          % (len(plan['remove']), len(plan['add']), TAG, len(after)))
    print('  回读校验%s' % ('通过' if ok else '失败'))
    if not ok:
        missing = sorted(set(plan['new']) - set(after))
        extra = sorted(set(after) - set(plan['new']))
        print('  ⚠ 缺失 %d 个：%s' % (len(missing), missing[:10]))
        print('  ⚠ 多出 %d 个：%s' % (len(extra), extra[:10]))
        print('  先跑 --revert --commit 恢复到运行前，再把上面几个 noteId 报给用户。')

    json_path, report_path = write_outputs(a.input, picked, dropped, plan, a.n,
                                           counts, sense_dropped)
    print('')
    print('产物：')
    print('  %s' % json_path)
    print('  %s' % report_path)
    print('')
    print('Anki 浏览器搜索：tag:"%s"' % TAG)
    print('回退：python code\\tools\\today_new_words.py --revert --commit')
    return 0 if ok else 1


def do_clear(a):
    old = tagged_note_ids()
    print('清空标签：%s' % TAG)
    print('当前命中 %d 个笔记' % len(old))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    if not a.commit:
        return 0
    textio.dump_json({
        'tag': TAG,
        'source': '--clear',
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'before': old,
        'after': [],
    }, STATE_PATH)
    if old:
        AK.remove_tags(old, [TAG])
    after = tagged_note_ids()
    print('已摘除 %d 个；当前剩 %d 个%s'
          % (len(old) - len(after), len(after),
             ('：' + str(after[:10])) if after else ''))
    return 0 if not after else 1


def do_revert(a):
    if not os.path.exists(STATE_PATH):
        raise SystemExit('找不到回退记录 %s（先确认确实跑过 --commit）' % STATE_PATH)
    st = textio.load_json(STATE_PATH)
    tag = st.get('tag') or TAG
    before = [int(x) for x in (st.get('before') or [])]
    if tag != TAG:
        raise SystemExit('回退记录的标签是 %s，不是 %s；停手问用户。' % (tag, TAG))
    plan = diff_ids(tagged_note_ids(), before)
    print('回退：恢复到上一次运行前的「%s」集合' % TAG)
    print('当前 %d 个 → 目标 %d 个；摘除 %d；补回 %d'
          % (len(plan['old']), len(before), len(plan['remove']), len(plan['add'])))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    if not a.commit:
        return 0
    if plan['remove']:
        AK.remove_tags(plan['remove'], [TAG])
    if plan['add']:
        # 只补回仍然存在的笔记，避免 AnkiConnect 对已删 note 报错。
        alive = set(AK.notes_map(plan['add']))
        add = [nid for nid in plan['add'] if nid in alive]
        if add:
            AK.add_tags(add, [TAG])
        gone = len(plan['add']) - len(add)
        if gone:
            print('  ⚠ %d 个旧笔记已不存在，未补回' % gone)
    after = tagged_note_ids()
    ok = set(after) == set(before)
    st['reverted_at'] = dt.datetime.now().isoformat(timespec='seconds')
    st['after_actual'] = after
    textio.dump_json(st, STATE_PATH)
    print('回读校验%s；当前 %d 个' % ('通过' if ok else '失败', len(after)))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='每天从整部作品字幕里挑 N 个词，只打标签「%s」' % TAG)
    ap.add_argument('input', nargs='?', default=None,
                    help='字幕（.srt/.vtt/.ass/.txt）、作品目录，或 - 读 stdin；--clear/--revert 时可省')
    ap.add_argument('--n', type=int, default=DEFAULT_N,
                    help='每天选多少个词（默认 %d）；名额按词算' % DEFAULT_N)
    ap.add_argument('--max-jar', type=int, default=DEFAULT_MAX_JAR,
                    help='JAR 上限（默认 %d；0 = 不设上限）' % DEFAULT_MAX_JAR)
    ap.add_argument('--mu', type=float, default=DEFAULT_MU,
                    help='集数项权重（默认 %.2f；0 = 完全不看跨集）' % DEFAULT_MU)
    ap.add_argument('--lam', type=float, default=DEFAULT_LAM,
                    help='JAR 项权重（默认 %.2f；2**(1/lam) = 次数翻倍等价于 JAR 前移的倍数）'
                         % DEFAULT_LAM)
    ap.add_argument('--particles', type=int, default=DEFAULT_PARTICLES,
                    help='助词/感动词单独占几个名额（默认 %d；0 = 不选这类词）'
                         % DEFAULT_PARTICLES)
    ap.add_argument('--drop-phrases', action='store_true',
                    help='挡掉 Anki 标为惯用句/成句/词缀/代词的词（会连带挡掉 おっ/にゃあ 这类词）')
    ap.add_argument('--no-sense-check', dest='sense_check', action='store_false',
                    help='跳过义项核验（默认开：卡片释义与字幕句义项对不上就不打 tag）')
    ap.add_argument('--include-names', action='store_true',
                    help='保留人名/专有名词（默认过滤）')
    ap.add_argument('--clear', action='store_true', help='清空「%s」标签' % TAG)
    ap.add_argument('--revert', action='store_true', help='恢复到上一次运行前的标签集合')
    ap.add_argument('--commit', action='store_true', help='真写库（不加则只演练）')
    a = ap.parse_args(argv)

    if a.clear and a.revert:
        ap.error('--clear 与 --revert 只能选一个')
    if not a.clear and not a.revert:
        if not a.input:
            ap.error('需要输入（字幕/目录/- stdin）；--clear/--revert 才可省略')
        if a.n <= 0:
            ap.error('--n 必须大于 0')

    with AK.guard():
        if a.clear:
            return do_clear(a)
        if a.revert:
            return do_revert(a)
        return do_pick(a)


if __name__ == '__main__':
    raise SystemExit(main())
