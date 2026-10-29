# -*- coding: utf-8 -*-
"""义项核验（sense gate）：字幕句里的词义 → JMdict 义项 → 对比卡片释义。

它解决的是什么
------------
词形一样不代表意思一样。`いう` 在 JMdict 里跨「说」「叫做」「据说」好几条义项；
字幕里 `っていうか` 是转折用法，卡片若按「说」讲，今天学的就是错的那层意思。
**机械匹配只能保证「同一个词」，义项一致只能判语义。**

三类判定（每条输入词各一条）
--------------------------
======  =========================================================
字段     含义
======  =========================================================
sense   字幕句用的是义项表里的第几条（用 ``i`` 的值；判不出给 0）
card_ok True 卡片释义对得上 / False 对不上 / None 判不了
why     不超过 30 字的中文理由（对不上时说明差在哪）
======  =========================================================

失败一律**放行**，不误杀
----------------------
* 词典查不到该词 → ``card_ok=None``，当通过；
* 模型输出残缺、重问仍缺条目 → 缺的那条 ``card_ok=None``，当通过；
* 只有模型明确给出 ``False`` 才拦。

缓存
----
``data/daily_new/sense_cache.json``。键 = sha1(词 | 句 | 卡片释义 | 义项表)[:16]，
义项表变了键就变，不会拿旧结论充数。``--no-cache`` 强制重判。

只读：不写 Anki。用法::

    $PY code\\tools\\sense_gate.py "subtitles\\Yani Neko" --n 30
    $PY code\\tools\\sense_gate.py "subtitles\\Yani Neko" --n 30 --no-cache
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, _HERE)

import jmdict_check as JC       # noqa: E402  JMdict 词典层
import paths as WSP             # noqa: E402
import textio                   # noqa: E402

CACHE_PATH = os.path.join(WSP.DATA, 'daily_new', 'sense_cache.json')
REPORT_PATH = os.path.join(WSP.OUTPUT, 'daily', 'sense_gate.md')
BATCH = 8
MAX_SENSES = 12

SYSTEM = (
    '你是日语词典编者，负责核验学习卡片的义项是否与真实语料一致。'
    '只按给出的句子语境判断，不要按词的常见义去猜。'
)

PROMPT = '''下面每条包含：日语句子、句子里的目标词、该词的 JMdict 义项表、卡片上的中文释义。

判断三件事：
1. sense —— 这个句子里的目标词，用的是义项表里的第几条（填该条的 i 值）。判不出填 0。
2. card_ok —— 卡片的中文释义，与这个义项**在意思上**是否对得上：true / false / null（判不了）。
3. why —— 不超过 30 字的中文理由；对不上时说明差在哪一层意思。

判定口径：
- 敬语、谦让、使役、被动、て形/た形只改变语法，不改变义项。
- 卡片释义是「说；讲」这种多义合并时，只要覆盖了该义项就算 true。
- 卡片释义写的是另一个义项（例如句子是「叫做」，卡片写「说」），判 false。
- 句子里的词若是该词的派生用法（复合动词、惯用句），按义项表里最接近的那条判。
- 拿不准时 card_ok 给 null，不要硬判 false。

只输出 JSON，不要任何解释文字：
{"results":[{"id":1,"sense":2,"card_ok":true,"why":"..."}]}

待判条目：
%s
'''


# ============================================================================
# 文本 / 缓存
# ============================================================================
_TAG = re.compile(r'<[^>]{1,200}>|\{[^}]{0,40}\}')


def clean_text(s, limit=120):
    """去 Anki 的 <br>/<img>/{\\an8} 与多余空白，截断。"""
    s = _TAG.sub('', s or '')
    s = re.sub(r'[\s\u3000]+', ' ', s).strip()
    return s[:limit]


def _key(item):
    raw = '\x1f'.join([
        item['word'], item['sentence'], item.get('card_meaning') or '',
        json.dumps(item['senses'], ensure_ascii=False, sort_keys=True),
    ])
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def load_cache(path=CACHE_PATH):
    try:
        data = textio.load_json(path)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(cache, path=CACHE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    textio.dump_json(cache, path)


# ============================================================================
# 义项表
# ============================================================================
def sense_facts(lk, word, card_word=''):
    """→ (senses, note)。senses 是扁平表 [{i, head, pos, glosses, misc}]。"""
    entries = []
    for cand in (word, card_word):
        if not cand:
            continue
        try:
            entries = JC.match_entries(lk.lookup(cand), cand)
        except Exception:  # noqa: BLE001  词典坏了不能挡流程
            entries = []
        if entries:
            break
    if not entries:
        return [], '词典无此词'

    out = []
    for e in entries[:3]:
        head = '、'.join(e['kanji']) or '、'.join(k['text'] for k in e['kana'])
        for s in e['senses'][:8]:
            if len(out) >= MAX_SENSES:
                break
            out.append({
                'i': len(out) + 1,
                'head': head,
                'pos': '、'.join(JC.tag_zh(p) for p in s['pos'][:3]),
                'glosses': s['glosses'][:4],
                'misc': s['misc'][:2],
            })
    return out, ''


# ============================================================================
# 判定
# ============================================================================
def _coerce(res, valid_ids):
    """模型单条结果 → 规范化 dict。"""
    try:
        i = int(res.get('id'))
    except (TypeError, ValueError):
        return None
    if i not in valid_ids:
        return None
    try:
        sense = int(res.get('sense') or 0)
    except (TypeError, ValueError):
        sense = 0
    ok = res.get('card_ok')
    if isinstance(ok, str):
        ok = {'true': True, 'false': False, 'null': None, '': None}.get(ok.strip().lower(),
                                                                        None)
    ok = True if ok is True else (False if ok is False else None)
    return {'id': i, 'sense': max(0, sense), 'card_ok': ok,
            'why': clean_text(str(res.get('why') or ''), 60)}


def _ask(cfg, items, LLM):
    """一批 → {id: 结果}。形状不合格就带反馈重问一次。"""
    payload = json.dumps([{
        'id': n + 1,
        'word': it['word'],
        'reading': it.get('reading') or '',
        'sentence': it['sentence'],
        'card_word': it.get('card_word') or '',
        'card_meaning': it.get('card_meaning') or '',
        'senses': it['senses'],
    } for n, it in items], ensure_ascii=False, indent=1)

    msgs = [{'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': PROMPT % payload}]
    valid = {n + 1 for n, _ in items}
    obj, _res, problems = LLM.call_json(cfg, msgs, require='results')
    got = {}
    if isinstance(obj, dict) and isinstance(obj.get('results'), list):
        for r in obj['results']:
            if not isinstance(r, dict):
                continue
            c = _coerce(r, valid)
            if c:
                got[c['id']] = c
    missing = sorted(valid - set(got))
    if missing and not problems:
        msgs2 = msgs + [
            {'role': 'assistant', 'content': json.dumps(obj, ensure_ascii=False)[:3000]},
            {'role': 'user', 'content': '你漏了 id=%s，只补这些，格式同上。' % missing},
        ]
        obj2, _r2, _p2 = LLM.call_json(cfg, msgs2, require='results')
        if isinstance(obj2, dict) and isinstance(obj2.get('results'), list):
            for r in obj2['results']:
                if isinstance(r, dict):
                    c = _coerce(r, valid)
                    if c and c['id'] not in got:
                        got[c['id']] = c
    return got


def judge(items, cfg=None, use_cache=True, quiet=False):
    """批量判定 → 与 items 等长的结果列表（缺的补 card_ok=None）。"""
    import local_llm as LLM

    cfg = cfg or LLM.load_config()
    cache = load_cache() if use_cache else {}
    todo, results = [], [None] * len(items)
    hits = 0
    for n, it in enumerate(items):
        k = it.get('_key') or _key(it)
        it['_key'] = k
        if use_cache and k in cache:
            results[n] = dict(cache[k], cached=True)
            hits += 1
        else:
            todo.append((n, it))

    if todo:
        if not quiet:
            print('  义项核验：%d 条待判（缓存命中 %d）' % (len(todo), hits),
                  file=sys.stderr)
        for s in range(0, len(todo), BATCH):
            chunk = todo[s:s + BATCH]
            got = _ask(cfg, chunk, LLM)
            for n, it in chunk:
                r = got.get(n + 1) or {'id': n + 1, 'sense': 0, 'card_ok': None,
                                      'why': '模型未返回'}
                r['cached'] = False
                results[n] = r
                if r['card_ok'] is not None:
                    cache[it['_key']] = {k: r[k] for k in ('sense', 'card_ok', 'why')}

    for n, r in enumerate(results):
        if r is None:
            results[n] = {'id': n + 1, 'sense': 0, 'card_ok': None, 'why': '未判定'}

    if todo and use_cache:
        try:
            save_cache(cache)
        except OSError as e:
            print('  ⚠ 缓存写入失败（不影响本次结果）：%s' % e, file=sys.stderr)
    return results


# ============================================================================
# CLI：对今天榜单做一次核验
# ============================================================================
def to_inputs(picked, index, lk=None):
    """选中的词 + 索引 → 判定输入（字幕句、卡片词形/释义、JMdict 义项表）。"""
    import today_new_words as TN

    own = lk is None
    lk = lk or JC.Lookup()
    try:
        out = []
        for it in picked:
            groups = TN.notes_of(it['word'], index)
            ents = [c for nid in it['notes'] for c in groups.get(nid, ())]
            e0 = ents[0] if ents else None
            sentence = clean_text(((it.get('first') or {}).get('text') or ''))
            senses, note = sense_facts(lk, it['word'], (e0.word if e0 else ''))
            out.append({
                'item': it,
                'senses': senses,
                'note': note,
                'input': {
                    'word': it['word'],
                    'reading': (e0.reading if e0 else '') or '',
                    'sentence': sentence,
                    'card_word': (e0.word if e0 else '') or '',
                    'card_meaning': clean_text(e0.meaning if e0 else '', 80),
                    'senses': senses,
                    'occurrences': it['occurrences'],
                    'episodes': it['episodes'],
                    'jiten': it['jiten'],
                    'deck': (e0.deck if e0 else ''),
                },
            })
        return out
    finally:
        if own:
            lk.close()


def collect(source, n, buffer=15):
    """复用 today_new_words 的选词 → [(item, 结果)] 所需的输入。"""
    import anki_api as AK  # noqa: F401  只为 AK.guard 的副作用一致性
    import today_new_words as TN

    index = TN.SW.VocabIndex.load(scopes=TN.SCOPES)
    sources = TN.episode_sources(source)
    stats = TN.collect_stats(sources, index)
    items, _skipped = TN.build_candidates(stats, index, TN.DEFAULT_MAX_JAR,
                                          mu=TN.DEFAULT_MU, lam=TN.DEFAULT_LAM)
    picked, _ranked = TN.plan_pick(items, n + buffer)
    return sources, to_inputs(picked, index)


def _report(source, rows, n):
    lines = ['# 义项核验 · %s' % dt.date.today().isoformat(), '',
             '- 来源：`%s`' % source,
             '- 生成：%s' % dt.datetime.now().isoformat(timespec='seconds'),
             '- 候选：前 %d 名' % len(rows), '']
    bad = [r for r in rows if r['res']['card_ok'] is False]
    unknown = [r for r in rows if r['res']['card_ok'] is None]
    good = [r for r in rows if r['res']['card_ok'] is True]
    lines += ['- 义项一致：%d；**不一致：%d**；判不了：%d'
              % (len(good), len(bad), len(unknown)), '']
    if bad:
        lines += ['## 义项对不上（这些词打 tag 前要处理）', '',
                  '| 词 | 卡片释义 | 字幕句 | 字幕义项 | 理由 |',
                  '|---|---|---|---|---|']
        for r in bad:
            it = r['input']
            sense = r['res']['sense']
            gloss = ''
            if 0 < sense <= len(it['senses']):
                gloss = '；'.join(it['senses'][sense - 1]['glosses'][:3])
            lines.append('| %s | %s | %s | %s | %s |' % (
                it['word'], it['card_meaning'] or '—', it['sentence'][:40],
                gloss or '—', r['res']['why'] or ''))
        lines.append('')
    if unknown:
        lines += ['## 判不了（词典查不到或模型不确定，按通过处理）', '']
        lines += ['- ' + '、'.join(r['input']['word'] for r in unknown), '']
    lines += ['## 全量明细', '',
              '| # | 词 | 次数 | 集数 | JAR | 卡片释义 | 义项 | card_ok | 理由 |',
              '|---|---|---:|---:|---:|---|---:|---|---|']
    for i, r in enumerate(rows, 1):
        it = r['input']
        ok = r['res']['card_ok']
        lines.append('| %d | %s | %d | %d | %d | %s | %s | %s | %s |' % (
            i, it['word'], it['occurrences'], it['episodes'], it['jiten'],
            (it['card_meaning'] or '—')[:20], r['res']['sense'] or 0,
            {True: '✅', False: '❌', None: '—'}[ok], r['res']['why'] or ''))
    lines.append('')
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description='义项核验：字幕句词义 vs 卡片释义')
    ap.add_argument('input', help='字幕文件或作品目录')
    ap.add_argument('--n', type=int, default=30, help='取前 N 名（默认 30）')
    ap.add_argument('--buffer', type=int, default=15, help='多取几名做备份（默认 15）')
    ap.add_argument('--no-cache', action='store_true', help='忽略缓存重判')
    a = ap.parse_args(argv)

    sources, rows = collect(a.input, a.n, a.buffer)
    if not rows:
        print('没有候选词。')
        return 2
    print('窗口：%d 集；核验前 %d 名' % (len(sources), len(rows)))
    results = judge([r['input'] for r in rows], use_cache=not a.no_cache)
    for r, res in zip(rows, results):
        r['res'] = res

    bad = [r for r in rows if r['res']['card_ok'] is False]
    print('')
    print('义项一致 %d / 不一致 %d / 判不了 %d'
          % (sum(1 for r in rows if r['res']['card_ok'] is True), len(bad),
             sum(1 for r in rows if r['res']['card_ok'] is None)))
    if bad:
        print('')
        print('义项对不上：')
        for r in bad:
            it = r['input']
            print('  ❌ %-10s 卡片「%s」｜句子「%s」｜%s'
                  % (it['word'], (it['card_meaning'] or '—')[:16],
                     it['sentence'][:24], r['res']['why']))
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    textio.write_text(REPORT_PATH, _report(a.input, rows, a.n))
    print('')
    print('报告：%s' % REPORT_PATH)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
