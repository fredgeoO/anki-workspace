# -*- coding: utf-8 -*-
"""素材驱动激活：把例句卡里遇到、但词汇卡组里**还没学过**的词，提前排进学习队列。

设计约束（不可违背）
--------------------
1. 只碰 type == 0（新卡）。学习中(1)/复习(2)/重学(3) 一律不动——不重置任何已学进度。
2. 只写 cards.due（新卡的位置），绝不写 ivl / factor / type / queue / reps / lapses。
3. plan 阶段只读，不写库。
4. apply 默认演练；必须显式 --commit 才真写。
5. apply 前逐卡从 live Anki 重读状态，已不是新卡的直接跳过并列出。

为什么用 due
------------
Anki 新卡队列按 cards.due（即"位置"）排序取卡，所以把位置调到最前面
= 让这些卡优先进入学习队列。卡的 1分钟/10分钟 学习步、毕业间隔全部保留，
和 Anki 自带的「浏览器 → 重新定位」是同一个动作。

已经被验证过的坑
----------------
AnkiConnect 的 setSpecificValueOfCard 对数值列**必须传整数**。
传字符串（newValues=['13924']）会被静默忽略、不报错——这个坑让第一次验证
误判为"API 不支持重排"。

用法
----
# 1. 报告（只读，不写库）。--tag 传本集例句卡的标签，与具体作品无关
python activate.py plan --tag "动画::<作品名>::<季>::第NN集"

# 2. 演练（读库、算好新位置，但不写）
python activate.py apply --plan plan_activate.json

# 3. 真写
python activate.py apply --plan plan_activate.json --commit

依赖：AnkiConnect 在 127.0.0.1:8765；同目录 pipeline.py（复用其 CFG 与工具函数）
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))   # paths.py
sys.path.insert(0, _HERE)                                           # pipeline.py
import anki_api as AK  # noqa: E402  唯一的 Anki 访问点
import pipeline as P  # noqa: E402  复用 CFG / norm / build_variants 等
import jp_decks as JD  # noqa: E402  牌组常量 + 标签→级别/频段（考级词汇已扁平化）
import paths as WSP   # noqa: E402  工作区路径的唯一来源
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

PLAN_FILE = os.path.join(WSP.DATA_PLANS, 'plan_activate.json')   # 旧路径，仅作兼容
os.makedirs(WSP.DATA_PLANS, exist_ok=True)
TAG_PREFIX = '素材激活::'
# 历史：准入标签「素材优先」曾是筛选牌组的准入口（2026-10-05 设计）。
# 筛选牌组机制 2026-10-06 退场，本脚本自 2026-10-10 起不再写该标签；
# 新卡全局顺序改由 due 位置 + Jiten 词频决定（见 docs/decisions/）。
# LEGACY_POOL_TAG 仅供 revert --unpool 清理 2026-10-06 前的残留。
LEGACY_POOL_TAG = '素材优先'
# 生成激活标签时会被剥掉的前缀（纯装饰，便于标签列表好看）
COSMETIC_PREFIXES = ('动画::',)


def _slug(s):
    """把标签变成安全的文件名片段。保留中日文/字母数字/连字符。"""
    return re.sub(r'[^\w\u3040-\u30ff\u4e00-\u9fff-]+', '_', s).strip('_') or 'plan'


def _strip_cosmetic(tag):
    """剥掉纯装饰前缀（如 动画::）。文件名与激活标签共用同一套规则。"""
    t = (tag or '').strip()
    for p in COSMETIC_PREFIXES:
        if t.startswith(p):
            return t[len(p):]
    return t


def plan_path_for(tag):
    """每个标签一个计划文件 —— 跑新一集不会覆盖旧一集的可回退数据。"""
    return os.path.join(WSP.DATA_PLANS, 'plan_activate_%s.json' % _slug(_strip_cosmetic(tag)))


def latest_plan():
    """没显式给 --plan 时，取最近修改的那个计划文件。"""
    import glob
    fs = glob.glob(os.path.join(WSP.DATA_PLANS, 'plan_activate*.json'))
    return max(fs, key=os.path.getmtime) if fs else None


def make_activation_tag(tag):
    """由本集标签生成激活标签。

    ★ 不硬编码任何作品名。用**完整**标签而不是最后一段，是为了避免不同作品
      的「第05集」撞到同一个激活标签下。例如：
        动画::作品A::第一季::第05集  →  素材激活::作品A::第一季::第05集
        动画::作品B::第05集          →  素材激活::作品B::第05集
    """
    t = _strip_cosmetic(tag).replace(' ', '_')      # Anki 标签不允许空格
    return TAG_PREFIX + t if t else TAG_PREFIX.rstrip(':')


def list_episode_tags():
    """列出 2-例句 deck 里现成的作品/集数标签，供 --tag 出错时提示。"""
    from collections import Counter
    c = Counter()
    for n in AK.notes_info(AK.find_notes('deck:"%s"' % P.CFG['deck'])):
        for t in n.get('tags', []):
            if t.startswith('动画'):
                c[t] += 1
    return c


# ============================================================================
# 词表索引
# ============================================================================
def vocab_sources():
    """产出 (级别, Anki 查询串, 词条字段名, 来源名, 分组用 deck 名)，顺序即优先级。

    考级词汇已扁平化（原先 11 个按级别/频段切分的子 deck 合并成「2-考级词汇」一层），
    级别与频段靠 eggrolls 笔记标签区分，所以每个来源 = deck + 级别标签。
    分组仍然只按 deck（整层现在就是一组，见 cmd_apply 的 by_deck）。
    """
    src = []
    for lv, deck, field, tag in P.CFG['vocab_decks']:
        band = JD.band_from_tags([tag]) if tag else None
        src.append((lv, JD.deck_query_tag(deck, tag), field,
                    lv + band if band else lv, deck))
    for tag, deck, field, _bandmap in P.CFG.get('vocab_band_decks', []):
        src.append(('Core', 'deck:"%s"' % deck, field, deck.split('::')[-1], deck))
    for name, full_tag in P.CFG['vocab_tags']:
        # 这两类是**纯标签**收录（拟声拟态词 / 片假名外来语），不挂在独立 deck 上
        src.append((name, 'tag:"%s"' % full_tag, 'VocabKanji', name, JD.DECK_KAOKYU))
    return src


def activation_variants(w):
    """激活专用的变体生成。刻意与 pipeline.build_variants 不同：

    1. 活用水干（含汉字的动词）：保留 —— 届ける→届け 是正确的
    2. 平假名词 → 片假名写法：保留 —— いたずら→イタズラ 是正确的
    3. **片假名词 → 平假名写法：不做**

    第 3 条是踩出来的。pipeline 的 build_variants 对 KATA_ONLY 也加了 kata2hira，
    于是 デモ↔でも / ナノ↔なの / イカ↔いか 被当成同一个词。但「でも」「なの」「いか」
    是日语里频率最高的语法词，结果每集都会稳定误匹配。
    不对称是有理由的：平假名词被写成片假名是刻意强调（少而可信），
    片假名词"出现在平假名文本里"则撞上的是满篇语法词。

    不改 pipeline.build_variants 是为了不破坏它的回归基线（regression_plan.json
    声称 147/147 复现原判）；triage 那边的后果只是判定偏宽松，无害。
    """
    vs = {w}
    conj_tail = 'るうくすつぬぶむぐい'
    if len(w) >= 3 and w[-1] in conj_tail and P.KANJI.search(w):
        vs.add(w[:-1])
    if P.KANA_ONLY.match(w):
        vs.add(P.hira2kata(w))
    return [v for v in vs if len(v) >= 2]


def build_index():
    """返回 (canonical -> [entry], variant -> canonical, new_cards)

    entry = dict(deck, source, lv, cardId, noteId, type, prior)
    只索引 vocabulary 来源（deck + 级别标签）里的卡；type 来自 live Anki。
    """
    canonical, variant2c, new_cards = {}, {}, set()
    for prior, (lv, query, field, source, deck) in enumerate(vocab_sources()):
        try:
            nids = AK.find_notes(query)
        except AK.AnkiError:
            continue
        for n in AK.notes_info(nids):
            w = P.norm(n['fields'].get(field, {}).get('value', ''))
            if not w or not P.vocab_guard(w):
                continue
            cids = n.get('cards', [])
            if not cids:
                continue
            cid = cids[0]
            e = {'deck': deck, 'source': source, 'lv': lv, 'cardId': cid,
                 'noteId': int(n['noteId']), 'prior': prior}
            canonical.setdefault(w, []).append(e)
            for v in activation_variants(w):
                variant2c.setdefault(v, w)
    # 新卡集合（一次查询，比逐卡 cardsInfo 便宜得多）
    for lv, query, field, _source, _deck in vocab_sources():
        try:
            ids = AK.find_cards(query + ' is:new')
        except AK.AnkiError:
            continue
        new_cards.update(ids)
    return canonical, variant2c, new_cards


def scan_sentence(sentence, variant2c, maxlen):
    """句内最长匹配，返回命中的 canonical 词集合。"""
    s = P.norm(sentence)
    found = set()
    i = 0
    while i < len(s):
        for L in range(min(maxlen, len(s) - i), 1, -1):
            w = variant2c.get(s[i:i + L])
            if w:
                found.add(w)
                i += L
                break
        else:
            i += 1
    return found


def drop_conjugation_stems(words):
    """去掉被更长词覆盖的活用词干（届け 被 届ける 覆盖）。"""
    out = set()
    for w in words:
        if any(v != w and v[:-1] == w for v in words):
            continue
        out.add(w)
    return out


# ============================================================================
# plan
# ============================================================================
def cmd_plan(a):
    print('构建词表索引（%d 个词汇 deck）…' % len(vocab_sources()))
    t0 = time.time()
    canonical, variant2c, new_cards = build_index()
    maxlen = max(len(v) for v in variant2c)
    print('  词形 %d 个 / 变体键 %d 个 / 新卡 %d 张  (%.1fs)'
          % (len(canonical), len(variant2c), len(new_cards), time.time() - t0))

    q = 'deck:"%s" tag:"%s"' % (P.CFG['deck'], a.tag)
    note_ids = AK.find_notes(q)
    print('例句卡：%s' % q)
    print('  命中 %d 条笔记' % len(note_ids))
    if not note_ids:
        print()
        print('没有命中任何例句卡。%s 里现有的作品/集数标签：' % P.CFG['deck'])
        for t, c in sorted(list_episode_tags().items()):
            print('    %-48s %d 张' % (t, c))
        raise SystemExit('检查 --tag 是否与实际标签一致')

    notes = AK.notes_info(note_ids)
    touched, excluded, sentences = {}, {}, {}
    for n in notes:
        sent = n['fields'].get('Sentence', {}).get('value', '')
        word = P.norm(n['fields'].get('Word', {}).get('value', ''))
        hits = scan_sentence(sent, variant2c, maxlen)
        # Word 字段非空时也并入（可能是活用形，扫描未必命中）
        if word:
            for L in range(len(word), 1, -1):
                if word[:L] in variant2c:
                    hits.add(variant2c[word[:L]])
                    break
        for w in drop_conjugation_stems(hits):
            entries = canonical[w]
            fresh = [e for e in entries if e['cardId'] in new_cards]
            if fresh:
                pick = min(fresh, key=lambda e: e['prior'])
                touched.setdefault(w, pick)
            else:
                e = min(entries, key=lambda e: e['prior'])
                excluded.setdefault(w, e)
            sentences.setdefault(w, []).append(P.norm(sent))

    occ = {w: len(v) for w, v in sentences.items()}

    print()
    print('=' * 96)
    print('扫描结果')
    print('=' * 96)
    print('  提及的词汇表词形（已去活用词干）: %d 个' % (len(touched) + len(excluded)))
    print('  ✅ 其中还是新卡，可激活          : %d 个' % len(touched))
    print('  ⛔ 其中已学过（学习中/复习），排除: %d 个' % len(excluded))
    if touched or excluded:
        print('     排除率 %.0f%%'
              % (len(excluded) / (len(touched) + len(excluded)) * 100))

    # 同族词：前 3 字相同的激活目标（多半是同一个学习点的变体，占两个新卡额度）
    fam = {}
    for w in touched:
        fam.setdefault(w[:3], []).append(w)
    dupfam = {k: v for k, v in fam.items() if len(v) > 1}

    print()
    print('  可激活的词（按在素材里出现的次数排序）:')
    print('    %-14s %-5s %-6s %s' % ('词', '级别', '出现次数', '词表来源'))
    for w in sorted(touched, key=lambda x: (-occ.get(x, 0), x)):
        e = touched[w]
        mark = ' ←同族' if any(w in v for v in dupfam.values()) else ''
        print('    %-14s %-5s %-6d %s%s'
              % (w, e['lv'], occ.get(w, 0), e.get('source') or e['deck'].split('::')[-1], mark))
    if dupfam:
        print()
        print('  ⚠ 同族词（建议每个族只留一个，省下新卡额度）:')
        for k, v in sorted(dupfam.items()):
            print('    %s  出现次数: %s'
                  % (' / '.join(sorted(v)),
                     ', '.join('%s=%d' % (x, occ.get(x, 0)) for x in sorted(v))))

    if excluded:
        print()
        print('  被排除的（已学过，绝不触碰）: %s'
              % '、'.join(sorted(excluded)))

    # 取这些卡当前的位置，供 apply 参考
    cids = [e['cardId'] for e in touched.values()]
    cur = {}
    for c in AK.cards_info(cids):
        cur[c['cardId']] = c.get('due')
    plan = {
        'tag': a.tag,
        'activation_tag': make_activation_tag(a.tag),
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'targets': [{'word': w, 'lv': e['lv'], 'deck': e['deck'],
                     'source': e.get('source', ''),
                     'cardId': e['cardId'], 'noteId': e['noteId'],
                     'occurrences': occ.get(w, 0),
                     'due_before': cur.get(e['cardId']),
                     'sentence': (sentences.get(w) or [''])[0]}
                    for w, e in sorted(touched.items(),
                                       key=lambda x: (-occ.get(x[0], 0), x[0]))],
        'excluded': [{'word': w, 'lv': e['lv'], 'deck': e['deck'],
                      'source': e.get('source', ''),
                      'cardId': e['cardId'], 'reason': '已不是新卡'}
                     for w, e in sorted(excluded.items())],
    }
    out = a.out or plan_path_for(a.tag)
    json.dump(plan, open(out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print()
    print('已写出计划：%s  （%d 个激活目标）' % (out, len(plan['targets'])))
    print('激活标签将会是：%s（溯源用；2026-10-06 起不再写准入标签）'
          % plan['activation_tag'])
    print()
    print('下一步：')
    print('  python activate.py apply  --plan "%s"            # 演练' % out)
    print('  python activate.py apply  --plan "%s" --commit   # 真写' % out)
    print('  python activate.py revert --plan "%s" --commit   # 反悔' % out)


# ============================================================================
# apply
# ============================================================================
def cmd_apply(a):
    path = a.plan or latest_plan()
    if not path:
        raise SystemExit('找不到计划文件，先跑：python activate.py plan --tag "…"')
    plan = json.load(open(path, encoding='utf-8'))
    targets = plan['targets']
    commit = a.commit
    print('计划来自 %s  标签 %s  生成于 %s' % (path, plan['tag'], plan['generated_at']))
    print('目标 %d 张' % len(targets))
    print('模式：%s' % ('★ 真写库' if commit else '演练（不写库，加 --commit 才真写）'))
    if not targets:
        return

    # ---- 闸门一：逐卡从 live Anki 重读，已不是新卡的一律剔除
    live = {c['cardId']: c for c in AK.cards_info([t['cardId'] for t in targets])}
    keep, skipped = [], []
    for t in targets:
        c = live.get(t['cardId'])
        if c is None:
            skipped.append((t, '卡不存在'))
        elif c['type'] != 0:
            skipped.append((t, 'type=%d 已不是新卡' % c['type']))
        else:
            t['due_now'] = c['due']
            keep.append(t)

    print()
    print('=' * 96)
    print('闸门一：状态复核')
    print('=' * 96)
    print('  通过（仍是新卡）: %d' % len(keep))
    print('  剔除（已学过/异常）: %d' % len(skipped))
    for t, why in skipped:
        print('    ⛔ %-14s [%s] %s' % (t['word'], t['lv'], why))
    if not keep:
        raise SystemExit('没有可写的目标')

    # ---- 分配新位置
    # 默认「按 deck 分组，各 deck 各从 start 排起」：适合每集激活（每个牌组队首就是这集）。
    # --global：整份计划**全局连续**编号（按计划顺序 = 词表排名）。跨 deck 不再有并列的
    # due，于是筛选牌组（order=DUE）拿到的也是同一个全局顺序；各 deck 内部仍是它的子序列。
    by_deck = {}
    for t in keep:
        by_deck.setdefault(t['deck'], []).append(t)
    start = a.start
    if getattr(a, 'global_order', False):
        for i, t in enumerate(keep):
            t['due_new'] = start + i
    else:
        for deck, items in sorted(by_deck.items()):
            items.sort(key=lambda t: t['lv'] != 'Core')
            for i, t in enumerate(items):
                t['due_new'] = start + i

    print()
    print('=' * 96)
    print('闸门二：将要写入的新位置（只改 due，其他列一律不动）')
    print('=' * 96)
    for deck, items in sorted(by_deck.items()):
        print('  %s  (%d 张)' % (deck, len(items)))
        for t in items:
            print('    %-14s [%-4s] %s → due %s → %s'
                  % (t['word'], t['lv'], t['cardId'], t['due_now'], t['due_new']))

    if not commit:
        print()
        print('演练结束，未写任何数据。确认无误后加 --commit 重跑。')
        return

    # ---- 写
    print()
    print('写入中…')
    okc = 0
    for t in keep:
        # due 必须传 int —— AK.set_card_due 内部已强转，并校验返回值
        if AK.set_card_due(t['cardId'], t['due_new']):
            okc += 1
    tag = plan.get('activation_tag') or make_activation_tag(plan.get('tag', ''))
    AK.add_tags([t['noteId'] for t in keep], tag)
    print('  setSpecificValueOfCard 成功 %d / %d' % (okc, len(keep)))
    print('  已打溯源标签 %s（2026-10-06 起不再写准入标签）' % tag)

    # ---- 回读校验
    time.sleep(0.5)
    after = {c['cardId']: c for c in AK.cards_info([t['cardId'] for t in keep])}
    bad = []
    for t in keep:
        c = after[t['cardId']]
        if c['due'] != t['due_new'] or c['type'] != 0:
            bad.append((t, c))
    print()
    print('=' * 96)
    print('回读校验')
    print('=' * 96)
    print('  位置写入正确且仍是新卡: %d / %d' % (len(keep) - len(bad), len(keep)))
    for t, c in bad:
        print('    ❌ %-14s 期望 due=%s type=0，实得 due=%s type=%s'
              % (t['word'], t['due_new'], c['due'], c['type']))
    print()
    print('回退方法：')
    print('  1) 浏览器搜 tag:%s 全选 → 卡片 → 重新定位（填回原来的起始位置）' % tag)
    print('  2) 或移除该标签：tag:%s → 全选 → 移除标签' % tag)
    print('  注意：位置是排序键，回退只影响先后顺序，不影响任何学习进度。')


def cmd_revert(a):
    """把 plan 里记下的原位置写回去，并移除**本集的**溯源标签。

    2026-10-06 起本脚本不再写准入标签；--unpool 只用于清理 2026-10-06 之前
    残留的「素材优先」标签（默认不动，因为池子是并集，摘错会让别的集掉出池子）。
    """
    path = a.plan or latest_plan()
    if not path:
        raise SystemExit('找不到计划文件')
    plan = json.load(open(path, encoding='utf-8'))
    tag = plan.get('activation_tag') or make_activation_tag(plan.get('tag', ''))
    pool = plan.get('pool_tag') or LEGACY_POOL_TAG
    print('回退 %s 的 %d 个目标，移除溯源标签 %s%s'
          % (path, len(plan['targets']), tag,
             ('，并清理残留准入标签 %s' % pool) if a.unpool
             else '（残留准入标签 %s 保留）' % pool))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练'))

    cids = [t['cardId'] for t in plan['targets']]
    live = {c['cardId']: c for c in AK.cards_info(cids)}
    print()
    print('  %-14s %-10s %-10s %-10s' % ('词', '当前due', '目标due', 'type'))
    todo = []
    for t in plan['targets']:
        c = live.get(t['cardId'])
        if c is None:
            continue
        print('  %-14s %-10s %-10s %-10s'
              % (t['word'], c['due'], t['due_before'], c['type']))
        if c['type'] == 0 and t.get('due_before') is not None:
            todo.append(t)
    if not a.commit:
        print('\n演练结束，未写库。加 --commit 真回退。')
        return

    for t in todo:
        AK.set_card_due(t['cardId'], t['due_before'])
    AK.remove_tags([t['noteId'] for t in plan['targets']], tag)
    if a.unpool:
        AK.remove_tags([t['noteId'] for t in plan['targets']], pool)
    time.sleep(0.5)
    after = {c['cardId']: c for c in AK.cards_info([t['cardId'] for t in todo])}
    bad = [(t, after[t['cardId']]) for t in todo
           if after[t['cardId']]['due'] != t['due_before']]
    print('\n  已还原位置 %d / %d' % (len(todo) - len(bad), len(todo)))
    for t, c in bad:
        print('    ❌ %-14s 期望 %s 实得 %s' % (t['word'], t['due_before'], c['due']))
    print('  已移除溯源标签 %s' % tag)
    print('  残留准入标签 %s：%s' % (pool, '已一并清理' if a.unpool else '保留'))


def main():
    ap = argparse.ArgumentParser(description='素材驱动的词汇卡激活')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('plan', help='只读扫描，产出激活计划')
    p1.add_argument('--tag', required=True,
                    help='本集例句卡的标签（与作品无关），如 动画::<作品名>::<季>::第NN集')
    p1.add_argument('--out', default=None,
                    help='计划文件路径；默认 plan_activate_<标签>.json（每集一份，互不覆盖）')
    p1.set_defaults(func=cmd_plan)

    p2 = sub.add_parser('apply', help='按计划重排新卡位置（默认演练）')
    p2.add_argument('--plan', default=None, help='计划文件；默认取最近修改的那份')
    p2.add_argument('--start', type=int, default=1, help='新位置起始值，默认 1')
    p2.add_argument('--global', dest='global_order', action='store_true',
                    help='整份计划全局连续编号（跨 deck 不并列）——外部词表排序用这个，'
                         '大卡组按位置升序收集新卡时才会拿到同一个全局顺序')
    p2.add_argument('--commit', action='store_true', help='真写库（不加则只演练）')
    p2.set_defaults(func=cmd_apply)

    p3 = sub.add_parser('revert', help='把位置还原、移除溯源标签（默认演练）')
    p3.add_argument('--plan', default=None, help='计划文件；默认取最近修改的那份')
    p3.add_argument('--commit', action='store_true', help='真写库（不加则只演练）')
    p3.add_argument('--unpool', action='store_true',
                    help='同时清理 2026-10-06 前残留的准入标签「%s」（默认不动）'
                         % LEGACY_POOL_TAG)
    p3.set_defaults(func=cmd_revert)

    a = ap.parse_args()
    with AK.guard():          # AnkiConnect 出错 → 中文提示，不出 traceback
        a.func(a)


if __name__ == '__main__':
    main()
