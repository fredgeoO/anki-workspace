# -*- coding: utf-8 -*-
"""选词精排：**一集一次调用**，模型读整集台词 + 本集候选，排出「今天先学哪些」。

它解决的是什么
------------
Sudachi + 词库对齐能保证「不漏词、词形对得上」，但**「这个词值不值得今天学」是语义判断**：
`生徒会` 和 `こと` 在词库里都常见，只有看意思才知道该学哪个。2026-11-01 起这个判断
从公式（次数 × 集数 × JAR）换成模型精排，公式退为同档定序与兜底。

一次一集，不切批
--------------
整集台词（几百句、几千字）+ 本集候选（几百词）在 262k 上下文里绰绰有余，所以
**一集 = 一次调用**：模型看得见完整对白，判「对白里实不实用」有真语境；
切成 25 句一批会让它看不到全局、排序自相矛盾。一季 12 集 = 12 次调用。

排序口径（用户定的优先级，从高到低）
----------------------------------
1. **动漫对白实用度**：在这类番的对白里听到能懂、说出来自然、能迁移到别的番。
   专有名词、语气词、纯功能词（こと/する/ある/いる 这类）排后。
2. **学习/编卡价值**：义项清楚、值得写中文讲解、能配出像样的例句；太抽象、太偏门、
   没有可讲内容的排后。
3. **一般通用度**：前两条打平时才看（出了这部番还用不用得上）。

跨集合并
--------
每集各出一个有序名单，合并时按「归一化名次」取平均：第 1 名 = 1.0，最后一名 → 0。
同一个词在多集都排得高 → 分高（等价于公式里的「跨集」信号）；只在一集出现但排第 1
也能拿满分，不会被集数多的词压死。同分再用公式的 S 定序。

失败一律回退
----------
模型不可用 / 输出残缺 / id 对不上 → 本模块返回 ``[]``，调用方退回公式排序
（``today_new_words.plan_pick``），并在报告里标明「公式兜底」。
**不在本模块里偷偷兜底**，否则线上分不清是模型排的还是公式排的。

只读：不写 Anki。缓存 ``data/daily_new/rank_cache.json``（同一集同一候选集不重复调用）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))
sys.path.insert(0, _HERE)

import paths as WSP          # noqa: E402
import textio                # noqa: E402

CACHE_PATH = os.path.join(WSP.DATA, 'daily_new', 'rank_cache.json')
RUBRIC = 'v2'                # 改提示词必须改这个版本号（缓存键的一部分）
EX_LIMIT = 40                # 每条候选带给模型的例句长度上限
TEXT_LIMIT = 14000           # 单集台词喂给模型的字数上限（约 1 万 token）
# 默认模型/档位：**128K 的 IQ3_S**。理由：本地端点一次只安稳服务一个模型，选一个
# 128K 档位既够装「整集台词 + 全部候选」，又不会因为要 256K 而把端点从别的任务
# 里切出来重载。用 `--model` / `$env:DSH_TODAY_RANK_MODEL` 可临时换。
DEFAULT_MODEL = os.environ.get('DSH_TODAY_RANK_MODEL') or 'qwen3.8-flash-next-iq3_s'
DEFAULT_CTX = int(os.environ.get('DSH_TODAY_RANK_CTX') or 131072)
SYSTEM = (
    '你是日语学习教练，负责给一位看动画学日语的中级学习者挑「今天最该学的词」。'
    '只能从给出的候选表里挑，不要补充候选表以外的词。'
)

PROMPT = '''下面是一集动画的完整台词，和学习者还没学过的**本集候选词**（共 %(total)d 个）。
请按优先级挑出最值得今天学的 **%(k)d 个**，从最值得开始排成有序名单。

判据（从高到低）：
1. 动漫对白实用度：在这类番的对白里听到能懂、说起来自然、能迁移到别的番。
   专有名词、语气词、纯功能词（こと/する/ある/いる 这类）排后。
2. 学习/编卡价值：义项清楚、值得写中文讲解、有例句可配。太抽象、太偏门、没有可讲内容的排后。
3. 一般通用度：前两条打平时才看。

硬规则：
- 只能用候选表里的 id，不许自创、不许合并、不许把两个词写成一个。
- 动词/形容词按候选里的词形原样对应，不要换成别的活用形。
- 每个 id 只出现一次，按「最值得 → 次值得」输出。
- 候选里不够 %(k)d 个值得学的，就给到哪儿算哪儿，不要硬凑。

只输出一个 JSON 对象，前后不要解释或 markdown 围栏：
{"picks":[{"id":1,"why":"对白高频、义项明确"},{"id":2,"why":"..."}]}
why 不超过 18 个汉字，写「为什么值得学」，不要复述词义。

【本集台词】
%(text)s

【本集候选】(id / 词 / 读音 / 词性 / 本集次数 / JAR / 例句)
%(payload)s
'''


# ============================================================================
# 输入 / 缓存
# ============================================================================
def load_cfg(cfg=None):
    """配置 → 精排要用的配置：默认钉在 128K 的 IQ3_S 上。

    钉默认值是刻意的：本地端点一次只安稳服务一个模型，跟着端点当前模型走会让
    「今天用的模型」每天不同、缓存也失效；而 256K 档位要换载模型，会打断别的任务。
    """
    import local_llm as LLM

    cfg = dict(cfg or LLM.load_config())
    if not cfg.get('_model_pinned'):
        cfg['model'] = DEFAULT_MODEL
        cfg['ctx'] = DEFAULT_CTX
        cfg['max_input_tokens'] = DEFAULT_CTX
    cfg['_model_pinned'] = True      # 定过就不许下游再改
    return cfg


def to_inputs(items, limit=EX_LIMIT):
    """候选 → 给模型的紧凑行（不用 JSON 嵌套：省 token，也少一层转义出错）。"""
    rows, valid = [], {}
    for n, it in enumerate(items, 1):
        ex = ((it.get('first') or {}).get('text') or '').replace('\n', ' ')
        if len(ex) > limit:
            ex = ex[:limit] + '…'
        jar = it.get('jiten')
        jar_s = '—' if not jar or int(jar) >= 999999 else str(int(jar))
        rows.append('%d / %s / %s / %s / %d次 / JAR %s / 「%s」' % (
            n, it['word'], it.get('reading') or '—', it.get('pos') or '—',
            int(it.get('ep_occ') or it.get('occurrences') or 0), jar_s, ex))
        valid[n] = it
    return rows, valid


def signature(items, text='', model=''):
    """候选集 + 台词 + **模型** 的指纹（同一集重跑直接吃缓存）。

    模型进指纹是必须的：换模型（256k ↔ 32k、XXS ↔ IQ3_S）就是换判断标准，
    拿旧模型的名单充数会把 A/B 对比变成自欺。
    """
    raw = '\x1f'.join(sorted('%s|%d|%s' % (
        it['word'], int(it.get('occurrences') or 0), it.get('jiten') or 0)
        for it in items))
    key = '%s\x1e%s\x1e%s\x1e%s' % (RUBRIC, model or '', raw, text)
    return hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]


def load_cache(path=CACHE_PATH):
    try:
        data = textio.load_json(path)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(cache, path=CACHE_PATH):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        textio.dump_json(cache, path)
    except OSError as exc:
        print('  ⚠ 精排缓存写入失败（不影响本次结果）：%s' % exc, file=sys.stderr)


# ============================================================================
# 调用与解析
# ============================================================================
def parse_picks(obj, valid):
    """模型输出 → [(item, why)]，保持模型给的顺序；不收自创 id。"""
    out, seen = [], set()
    if not isinstance(obj, dict):
        return out
    for r in (obj.get('picks') or []):
        if not isinstance(r, dict):
            continue
        try:
            i = int(r.get('id'))
        except (TypeError, ValueError):
            continue
        if i not in valid or i in seen:
            continue
        seen.add(i)
        out.append((valid[i], str(r.get('why') or '')[:40]))
    return out


def ask(items, text, cfg, k, quiet=False):
    """一集 → ([(item, why)], meta)。失败给空表，由调用方兜底。"""
    import local_llm as LLM

    rows, valid = to_inputs(items)
    prompt = PROMPT % {'total': len(rows), 'k': int(k),
                       'text': text[:TEXT_LIMIT], 'payload': '\n'.join(rows)}
    msgs = [{'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': prompt}]
    t0 = time.time()
    obj, res, problems = LLM.call_json(cfg, msgs, require='picks')
    secs = time.time() - t0
    picks = parse_picks(obj, valid)
    meta = {
        'calls': 1, 'secs': round(secs, 1), 'candidates': len(rows),
        'returned': len(picks), 'problems': list(problems or [])[:5],
        'model': getattr(res, 'model', '') or cfg.get('model') or '',
        'cached': False,
    }
    if not quiet:
        print('    精排：%d 个候选 → 给回 %d 个（%.1fs）'
              % (len(rows), len(picks), secs), file=sys.stderr)
    return picks, meta


def rank_episode(label, items, text, cfg=None, k=40, use_cache=True, quiet=False):
    """单集精排（供 CLI 与测试调用）→ ([(item, why)], meta)。"""
    import local_llm as LLM

    items = [it for it in items if it.get('notes')]
    if not items:
        return [], {'calls': 0, 'candidates': 0, 'returned': 0, 'episode': label}
    k = max(1, min(int(k), len(items)))
    cfg = load_cfg(cfg)
    key = signature(items, text, cfg.get('model') or '')
    if use_cache:
        row = load_cache().get(key)
        if isinstance(row, dict) and row.get('ids'):
            by_word = {it['word']: it for it in items}
            picks = [(by_word[w], why) for w, why in row['ids'] if w in by_word]
            if picks:
                meta = dict(row.get('meta') or {})
                meta.update({'cached': True, 'calls': 0, 'returned': len(picks),
                             'episode': label})
                if not quiet:
                    print('    精排：命中缓存（%d 个）' % len(picks), file=sys.stderr)
                return picks, meta

    picks, meta = ask(items, text, cfg, k, quiet=quiet)
    meta['episode'] = label
    if picks and use_cache:
        cache = load_cache()
        cache[key] = {
            'episode': label,
            'ids': [[it['word'], why] for it, why in picks],
            'meta': meta,
            'saved_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        if len(cache) > 120:
            for old in sorted(cache, key=lambda x: cache[x].get('saved_at') or '')[:-120]:
                cache.pop(old, None)
        save_cache(cache)
    return picks, meta


def rank_groups(groups, k=40, cfg=None, use_cache=True, quiet=False, workers=None):
    """多集 → (有序 [(item, why, 精排分)], meta)。

    ``groups``: [{'label': 集名, 'text': 整集台词, 'items': [候选…]}, …]

    **各集互不依赖 → 并行**：默认 ``workers = cfg['concurrency']``（端点开几个槽用几个），
    小上下文模型（32k）prefill 短，并行收益最明显；结果按 ``groups`` 顺序合并。

    合并：每个词的单集名次归一化成 ``1 - pos/(n_picks-1)``，多集取平均。
    """
    import local_llm as LLM

    cfg = load_cfg(cfg)
    w = max(1, min(int(workers or cfg.get('concurrency') or 2), len(groups) or 1))

    def _one(g):
        try:
            return rank_episode(g['label'], g.get('items') or [], g.get('text') or '',
                                cfg=cfg, k=k, use_cache=use_cache, quiet=quiet)
        except Exception as exc:        # noqa: BLE001  一集挂了不能拖垮整轮
            return [], {'episode': g.get('label'), 'calls': 0, 'candidates': 0,
                        'returned': 0,
                        'problems': ['%s: %s' % (type(exc).__name__, exc)]}

    if len(groups) > 1 and w > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=w) as ex:
            results = list(ex.map(_one, groups))
    else:
        results = [_one(g) for g in groups]

    picked_scores = {}           # word -> {'sum', 'n', 'why', 'item'}
    metas = []
    for picks, meta in results:
        metas.append(meta)
        m = max(1, len(picks) - 1)
        for pos, (it, why) in enumerate(picks):
            s = 1.0 - pos / float(m)
            rec = picked_scores.setdefault(it['word'],
                                           {'sum': 0.0, 'n': 0, 'why': why, 'item': it})
            rec['sum'] += s
            rec['n'] += 1
            if pos == 0:
                rec['why'] = why
                rec['item'] = it

    ordered = []
    for word, rec in picked_scores.items():
        ordered.append((rec['item'], rec['why'], rec['sum'] / rec['n']))
    ordered.sort(key=lambda x: (-x[2], -float(x[0].get('score') or 0.0), x[0]['word']))
    meta = {
        'episodes': len(groups),
        'workers': w,
        'calls': sum(int(m.get('calls') or 0) for m in metas),
        'cached': all(bool(m.get('cached')) for m in metas) if metas else False,
        'secs': round(sum(float(m.get('secs') or 0) for m in metas), 1),
        'candidates': sum(int(m.get('candidates') or 0) for m in metas),
        'returned': len(ordered),
        'problems': [p for m in metas for p in (m.get('problems') or [])][:5],
        'model': next((m.get('model') for m in metas if m.get('model')), '')
                 or cfg.get('model') or '',
        'per_episode': [{kk: m.get(kk) for kk in
                         ('episode', 'candidates', 'returned', 'secs', 'cached')}
                        for m in metas],
    }
    return ordered, meta


# ============================================================================
# CLI：人工看一眼模型怎么排
# ============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description='对一部作品的每集候选做一次 LLM 精排（只读）')
    ap.add_argument('input', help='字幕文件/作品目录')
    ap.add_argument('--n', type=int, default=30, help='今天要几个词（默认 30）')
    ap.add_argument('--top', type=int, default=40, help='每集让模型给回多少个（默认 40）')
    ap.add_argument('--no-cache', action='store_true')
    ap.add_argument('--season', action='store_true',
                    help='给单集时扩到同目录整季（默认只筛这一集）')
    ap.add_argument('--model', help='临时换模型（如 qwen3.8-flash-next-iq3_s-32k）')
    ap.add_argument('--ctx', type=int, help='上下文档位，配合 --model')
    ap.add_argument('--workers', type=int, help='并行集数（默认取配置的 concurrency）')
    ap.add_argument('--out', help='把有序名单写成 JSON（A/B 对比用）')
    a = ap.parse_args(argv)

    import local_llm as LLM
    import today_new_words as TN
    import subtitle_new_words as SW

    cfg = load_cfg()
    if a.model:
        cfg['model'] = a.model
        cfg['_model_pinned'] = True
        if a.ctx:
            cfg['ctx'] = int(a.ctx)
            cfg['max_input_tokens'] = int(a.ctx)

    index = SW.VocabIndex.load(scopes=TN.SCOPES)
    sources = TN.episode_sources(a.input, season=a.season)
    stats = TN.collect_stats(sources, index, extra_pos=TN.PARTICLE_POS)
    items, skipped = TN.build_candidates(stats, index)
    by_ep = TN.group_by_episode(items, sources, stats)
    ordered, meta = rank_groups(by_ep, k=a.top, cfg=cfg,
                                use_cache=not a.no_cache, workers=a.workers)

    print('')
    print('模型 %s（ctx %s）｜窗口 %d 集｜候选 %d 个｜给回 %d 个｜调用 %d 次 共 %.1fs（%d 路并行）%s'
          % (meta.get('model'), cfg.get('ctx'), len(sources), len(items), len(ordered),
             meta['calls'], meta['secs'], meta.get('workers', 1),
             '（缓存）' if meta.get('cached') else ''))
    print('跳过：JAR 超范围 %d / 已学无新卡 %d / 读音不符 %d'
          % (len(skipped['jar']), len(skipped['no_notes']),
             len(skipped['reading'])))
    if meta.get('problems'):
        print('⚠ 模型输出问题：%s' % meta['problems'])
    print('')
    for i, (it, why, s) in enumerate(ordered[:a.n + 10], 1):
        print('%s%2d. %-10s %-12s JAR %-6s %2d次/%d集｜%.2f｜%s'
              % ('★' if i <= a.n else ' ', i, it['word'], it.get('reading') or '—',
                 TN.fmt_rank(it.get('jiten')), it['occurrences'], it['episodes'],
                 s, why))
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        textio.dump_json({
            'model': meta.get('model'), 'ctx': cfg.get('ctx'),
            'meta': meta, 'source': a.input,
            'picked': [{'word': it['word'], 'reading': it.get('reading') or '',
                        'jiten': it.get('jiten'), 'occ': it['occurrences'],
                        'eps': it['episodes'], 'score': round(s, 4), 'why': why}
                       for it, why, s in ordered],
        }, a.out)
        print('\n写入：%s' % a.out)
    return 0 if ordered else 2


if __name__ == '__main__':
    raise SystemExit(main())
