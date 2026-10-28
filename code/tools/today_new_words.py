# -*- coding: utf-8 -*-
"""每天从一整部作品的字幕里挑 30 个「今天要学」的词，只打一个标签 ``今天学习生词``。

它解决的是什么
------------
「今天学哪 N 个词」每天都要重新决定。2026-10-28 起口径改成**按本作暴露分池**，
不再只看单一 Jiten 排名：

1. **统计窗口 = 整部作品**（同目录所有字幕，含还没看的集）。给一集字幕，脚本会
   把同目录其它集一起扫掉，用来算「出现次数」和「跨了几集」。
2. **候选 = Anki 已有、且至少有一张未学笔记的词**。
   「学过」按**笔记**判断：同一词形下，已学的那张排除，别的未学笔记照选照标。
3. **分池**（硬门槛，纯代码，无模型）：

   ======  ============================================  ==============================
   池       条件                                           排序
   ======  ============================================  ==============================
   A       出现 ≥5 次 **或** 跨集 ≥3 集                    出现×集数 降序 → JAR 升序
   B       JAR ≤4000 **且** 出现 ≥3 次                     同上（A 不足时才取）
   D       JAR ≤6000 **且** 出现 ≥2 次                     同上（A、B 不足时才取）
   E       其余（不取）                                    —
   ======  ============================================  ==============================

4. **取 N 个词**：A 填满 N → A 不足用 B → B 不足用 D → 仍不足就返回少于 N，不取 E。
   名额按**词**算；一个词名下的未学笔记全部打标签，所以标签数可能多于 N。
5. **JAR 门槛**：只处理 ``1 ≤ JAR ≤ 30000`` 的词；无排名（空 / 0 / 999999）与
   JAR >30000 的一律排除（``--max-jar 0`` 可关掉这个门槛）。超范围的不建新卡。
6. **不去重**：复合词各自独立（``魔神`` / ``魔神族`` 都算候选），同词多写法也不合并。
7. **全量替换**：先把全库旧的 ``今天学习生词`` 摘掉，再给今天选中的打上。

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

产物
----
* ``data/daily_new/<日期>/picked.json`` —— 本次入选词 / 池 / 笔记 id（讲义据此排顺序）
* ``output/daily/today_new_words.md`` —— 给人看的稳定路径报告
* ``data/daily_new/state.json`` —— 回退记录（运行前 / 运行后的 noteId 集合）
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
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
SCOPES = (JD.DECK_MINED, JD.DECK_CORE6000, JD.DECK_KAOKYU)   # 三个词汇卡组
SUBTITLE_EXT = ('.srt', '.vtt', '.ass', '.ssa')
POOL_ORDER = ('A', 'B', 'D')        # 取词顺序；E 永远不取
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


def new_note_ids(word, index):
    """该词名下「没学过、也没挂起」的笔记 id（升序）。"""
    return sorted(nid for nid, cards in notes_of(word, index).items()
                  if note_state(cards) == 'new')


def pool_of(occurrences, episodes, jar):
    """硬门槛分池：A / B / D / E（E 不取）。"""
    if occurrences >= 5 or episodes >= 3:
        return 'A'
    if jar <= 4000 and occurrences >= 3:
        return 'B'
    if jar <= 6000 and occurrences >= 2:
        return 'D'
    return 'E'


def pool_key(item):
    """池内排序：出现×集数 降序 → JAR 升序 → 词形（稳定）。"""
    return (-(int(item['occurrences']) * int(item['episodes'])),
            int(item['jiten']), item['word'])


def take_pools(pools, n):
    """A → B → D 依次取，总共不超过 n 个词；不足就少取，不拿 E 硬凑。"""
    out = []
    for name in POOL_ORDER:
        need = n - len(out)
        if need <= 0:
            break
        out.extend(pools.get(name, [])[:need])
    return out


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


def collect_stats(sources, index, include_names=False):
    """逐集统计 → {词形: {occ, eps, first, examples}}（只统计已在词库里的词）。"""
    stats = {}
    for label, path in sources:
        cues = SW.load_cues(path)
        for cue in cues:
            for h in SW.find_hits(cue.text, index, include_names=include_names):
                if not include_names and h.name_like:
                    continue
                rec = stats.setdefault(h.word, {
                    'occ': 0, 'eps': set(), 'first': None, 'examples': [],
                })
                rec['occ'] += 1
                rec['eps'].add(label)
                if rec['first'] is None:
                    rec['first'] = {'episode': label, 'index': cue.index,
                                    'start': cue.start, 'text': cue.text}
                if (len(rec['examples']) < 3
                        and all(e['text'] != cue.text for e in rec['examples'])):
                    rec['examples'].append({'episode': label, 'index': cue.index,
                                            'start': cue.start, 'text': cue.text})
    return stats


def build_candidates(stats, index, max_jar=DEFAULT_MAX_JAR):
    """统计 → 候选词（JAR 在范围内、有未学笔记）→ (items, skipped)。"""
    items, skipped = [], {'jar': [], 'no_notes': []}
    for word, st in stats.items():
        jar = rank_of(word, index)
        if max_jar and int(max_jar) > 0 and jar > int(max_jar):
            skipped['jar'].append(word)
            continue
        groups = notes_of(word, index)
        nids = sorted(nid for nid, cards in groups.items()
                      if note_state(cards) == 'new')
        if not nids:
            skipped['no_notes'].append(word)
            continue
        items.append({
            'word': word,
            'jiten': jar,
            'occurrences': st['occ'],
            'episodes': len(st['eps']),
            'first': st['first'],
            'examples': st['examples'],
            'pool': pool_of(st['occ'], len(st['eps']), jar),
            'notes': nids,
            'note_cards': {nid: sorted(int(c.card_id) for c in groups[nid])
                           for nid in nids},
        })
    return items, skipped


def plan_pools(items, n):
    """候选 → (入选词, 分池排序后的全部池子)。"""
    pools = {'A': [], 'B': [], 'D': [], 'E': []}
    for it in items:
        pools[it['pool']].append(it)
    for name in pools:
        pools[name].sort(key=pool_key)
    return take_pools(pools, n), pools


def describe(item, index):
    """给入选词补展示字段：读音用词典形，牌组/级别取代表笔记。"""
    groups = notes_of(item['word'], index)
    entries = [c for nid in item['notes'] for c in groups.get(nid, ())]
    e0 = entries[0] if entries else None
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
    print('今天要学的词（A > B > D；同池按 出现×集数 降序）：')
    for i, w in enumerate(items, 1):
        first = _first_text(w)
        print('  %2d. %-10s %-12s JAR %-6s ｜%2d 次/%d 集｜%s｜%d 张笔记%s'
              % (i, w['word'], w.get('reading') or '—', fmt_rank(w.get('jiten')),
                 int(w.get('occurrences') or 0), int(w.get('episodes') or 0),
                 w.get('pool'), len(w.get('notes') or []),
                 ('｜「%s」' % first) if first else ''))


def _report_md(source, picked, dropped, plan, n, counts, pool_counts):
    lines = [
        '# 今天学习生词 · %s' % dt.date.today().isoformat(),
        '',
        '- 来源：`%s`' % source,
        '- 生成：%s' % dt.datetime.now().isoformat(timespec='seconds'),
        '- 窗口：%d 集；候选词 %d 个（A %d / B %d / D %d / E %d）'
        % (counts['episodes'], counts['candidates'], pool_counts.get('A', 0),
           pool_counts.get('B', 0), pool_counts.get('D', 0), pool_counts.get('E', 0)),
        '- 入选：%d 个词 / %d 张笔记（上限 %d 个词）'
        % (len(picked), sum(len(w['notes']) for w in picked), n),
        '- 旧标签：%d 个（保留 %d / 摘除 %d）；本次新增 %d'
        % (len(plan['old']), len(plan['keep']), len(plan['remove']), len(plan['add'])),
        '- 规则：A = 出现≥5 或 跨集≥3；B = JAR≤4000 且 出现≥3；'
        'D = JAR≤6000 且 出现≥2；E 不取；JAR 限 1–30000',
        '',
        '## 今天要学',
        '',
        '| # | 词 | 读音 | 池 | JAR | 次数 | 集数 | 笔记 | 首句 |',
        '|---|---|---|---|---:|---:|---:|---:|---|',
    ]
    for i, w in enumerate(picked, 1):
        lines.append('| %d | %s | %s | %s | %s | %d | %d | %d | %s |' % (
            i, w['word'], w.get('reading') or '', w['pool'], fmt_rank(w.get('jiten')),
            int(w['occurrences']), int(w['episodes']), len(w['notes']),
            _first_text(w, 60).replace('|', '\\|')))
    lines.append('')
    if dropped:
        lines += ['## 现场复核被剔除', '']
        for word, nid, why in dropped:
            lines.append('- %s%s：%s' % (word, '' if nid is None else '（note %s）' % nid, why))
        lines += ['']
    if counts.get('skipped_jar'):
        lines += ['> 另有 %d 个词因 JAR 超出 1–30000 未参与选择（不建新卡）。'
                  % counts['skipped_jar'], '']
    if counts.get('skipped_notes'):
        lines += ['> 另有 %d 个词没有未学笔记（已学/已挂起），未参与选择。'
                  % counts['skipped_notes'], '']
    lines += [
        '> 回退：`python code\\tools\\today_new_words.py --revert --commit`',
        '> 清空：`python code\\tools\\today_new_words.py --clear --commit`',
        '',
    ]
    return '\n'.join(lines)


def write_outputs(source, picked, dropped, plan, n, counts, pool_counts):
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
        'pools': pool_counts,
        'plan': {'old': len(plan['old']), 'keep': len(plan['keep']),
                 'remove': len(plan['remove']), 'add': len(plan['add'])},
        'picked': [{
            'word': w['word'], 'reading': w.get('reading') or '',
            'pos': w.get('pos') or '', 'deck': w.get('deck') or '',
            'level': w.get('level') or '', 'pool': w['pool'],
            'occurrences': int(w['occurrences']), 'episodes': int(w['episodes']),
            'jiten': int(w['jiten']),
            # 兼容旧的「一个词一张卡」消费者：noteId = 第一张笔记
            'noteId': int(w['notes'][0]), 'cardId': int(w['note_cards'][w['notes'][0]][0]),
            'notes': [int(x) for x in w['notes']],
            'first': w.get('first'),
        } for w in picked],
        'dropped': [{'word': word, 'noteId': nid, 'reason': why}
                    for word, nid, why in dropped],
    }, json_path)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    textio.write_text(REPORT_PATH, _report_md(source, picked, dropped, plan, n,
                                              counts, pool_counts))
    return json_path, REPORT_PATH


# ============================================================================
# 主流程
# ============================================================================
def do_pick(a):
    index = SW.VocabIndex.load(scopes=SCOPES)
    sources = episode_sources(a.input)
    stats = collect_stats(sources, index, include_names=a.include_names)
    items, skipped = build_candidates(stats, index, a.max_jar)
    picked, pools = plan_pools(items, a.n)

    pool_counts = {k: len(v) for k, v in pools.items()}
    counts = {
        'episodes': len(sources),
        'candidates': len(items),
        'picked': len(picked),
        'notes': sum(len(w['notes']) for w in picked),
        'skipped_jar': len(skipped['jar']),
        'skipped_notes': len(skipped['no_notes']),
    }

    print('来源：%s' % a.input)
    print('窗口：%d 集（同目录整部作品）' % counts['episodes'])
    print('候选：%d 个词（JAR 1–%d、有未学笔记）' % (counts['candidates'], a.max_jar))
    print('  排除：JAR 超范围 %d / 没有未学笔记 %d'
          % (counts['skipped_jar'], counts['skipped_notes']))
    print('分池：A %d / B %d / D %d / E %d（E 不取）'
          % (pool_counts['A'], pool_counts['B'], pool_counts['D'], pool_counts['E']))
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
    print('')
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
                                           counts, pool_counts)
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
