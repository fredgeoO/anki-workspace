# -*- coding: utf-8 -*-
"""core6000 「Meaning」字段重写（按例句 + JMdict 判定直译错误）。

背景
----
`1-高频日语单词 6000` 里大量 Meaning 是**英文释义的逐字直译**（room→房间、
joint→联合的、diet→饮食、recording→记录、newly-wed→新人…），中文看着像词，
实际把学习者带错。本脚本用 JMdict 的义项/词性/读音 + 卡上两条例句做判断，
只重写判为「不准确」的卡，准确的卡一个字不动。

流程
----
    prepare   抽 6000 张卡的字段，拆出 Meaning 的文字部分与配图 tail（只读）
    judge     本地模型分批判定 + 生成新释义（结果落 results.jsonl，可断点续跑）
    report    汇总「旧 → 新」清单、lint 不合格项、按 Index 分段统计
    apply     默认演练；--commit 才写（写前备份旧 Meaning，写后回读）
    revert    按 backup_meaning_*.json 还原

硬约束
------
* **只写 Meaning**：Word / Transliteration / Part of Speech / Sentence / 音频 /
  标签 / due 一律不碰。
* **配图保留**：原 Meaning 里 ``<br><br><img …>`` 之后的整段原样拼回新释义后面，
  图片标识与顺序不变；含 ``<span>`` 等内联标签的卡标记 manual，不自动写。
* **宁可不改，不可改错**：判 ok 的从宽（近义、少列义项都不算错），判 bad 的从严
  （义项错、词性错、直译歧义、与读音不符）。lint 不过的只报告、不写库。
* 写库前把旧 Meaning 备份到 ``data/core6000/meaning/backup_meaning_<ts>.json``。
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_CODE, 'common'))
import anki_api as AK          # noqa: E402
import jmdict_check as JC      # noqa: E402
import paths as WSP            # noqa: E402
import textio                  # noqa: E402  UTF-8 stdio 唯一入口

DECK = '0-日本语学习::0-词汇::1-高频日语单词 6000'
NOTE_MODEL = 'Japanese Vocabulary'
DIR = os.path.join(WSP.DATA_CORE6000, 'meaning')
CARDS = os.path.join(DIR, 'cards.json')
RESULTS = os.path.join(DIR, 'results.jsonl')
VERIFY = os.path.join(DIR, 'verify.jsonl')
MANUAL = os.path.join(DIR, 'manual_fix.json')
FAILED_DIR = os.path.join(DIR, 'failed')
BACKUP_GLOB = os.path.join(DIR, 'backup_meaning_*.json')

# 判定义项的口径。要点：ok 从宽、bad 从严；改写给**常用义项**，不写例句的语境义；
# 保持原卡风格（短释义仍短，解释式仍解释）；字符串里禁止英文双引号（JSON 会碎）。
SYSTEM = """你是日语词典编辑，正在校对 Anki 词汇卡的「释义」字段。
逐条依据「例句」和「词典」判断「现义」。
判 ok（宽）：现义是该词的常用词典义，中文自然；即使不够细、只覆盖部分义项、或与例句里的特定引申义不完全重合，也判 ok。近义词、口语化说法不算错。
判 bad（严）：现义会让学习者理解错——义项选错、词性错、把英文释义逐字直译成错误中文（如 room 译成「房间」、joint 译成「联合的」、diet 译成「饮食」、course 译成「课程」、recording 译成「记录」、near 译成「附近」、blocked 译成「屏蔽」、municipal 译成「市政」、newly-wed 译成「新人」）、与词形或读音明显不符。
改写（只对 bad）：给出该词的常用中文释义，不要只写例句里的语境义；保持原卡风格（现义 8 字以内就给 2 到 10 字，解释式就给 30 字以内）；多义项用「；」分隔；纯中文，不要英文、日文、HTML、括号注释、句号。
字符串里不要出现英文双引号，需要引用时用「」。
只输出 JSON 对象：{"items":[{"i":1,"verdict":"ok","reason":"","meaning":""},...]}，条数一条不少。"""

# 复核口径：**从宽保护旧释义**。初审会误伤「啰嗦但没错」的解释式卡，这一步专门把它们留下来；
# 只有旧释义确实会把学习者带错才 fix。同形异读（おる 居る/折る、空 から/そら）是重点。
VERIFY_SYSTEM = """你是复核员。下面每条是初审认为「旧释义不准」并改写过的卡。请独立核对，标准从宽：
- 旧释义只要是该词的常用义、不会让学习者理解错，即使啰嗦、少列义项、近义、混入一点无关内容，也判 keep_old（不改）。
- 只有旧释义确实错（义项选错、词性错、直译歧义、与读音或词形不符）才判 fix。
- 判 fix 时检查初审新义：正确就沿用；若新义也错（例如选错同形词、丢了常用义、把例句语境义当通用义），给出修正后的释义。
- 修正释义要求：纯中文，2 到 15 字，多义项用「；」分隔，不要英文、日文、HTML、括号注释、句号。
字符串里不要出现英文双引号，需要引用时用「」。
只输出 JSON 对象：{"items":[{"i":1,"verdict":"keep_old 或 fix","meaning":"fix 时给","reason":"不超过30字"},...]}，条数一条不少。"""

TAIL_RE = re.compile(r'(?is)<br\s*/?>\s*(?:<br\s*/?>\s*)*(?=<(?:img|div|table|a)\b)')
INLINE_RE = re.compile(r'(?is)<(?:span|b|i|u|font|strong|em)\b')


# ── 文本/HTML ────────────────────────────────────────────────────────────
def strip_html(text):
    """HTML → 纯文本（<br> 变 /；去标签；解常见实体）。"""
    s = text or ''
    s = re.sub(r'(?is)<br\s*/?>', ' / ', s)
    s = re.sub(r'(?is)<[^>]+>', '', s)
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"')):
        s = s.replace(a, b)
    return re.sub(r'[ \t]+', ' ', s).strip()


def parse_meaning(raw):
    """拆分 Meaning：文字部分 / 配图 tail / 是否含内联标签（manual）。"""
    raw = raw or ''
    m = TAIL_RE.search(raw)
    if m:
        text_raw, tail = raw[:m.start()], raw[m.start():]
    else:
        text_raw, tail = raw, ''
    manual = bool(INLINE_RE.search(text_raw))
    return {
        'text_raw': text_raw,
        'text_plain': strip_html(text_raw),
        'tail': tail,
        'manual': manual,
        'multi_br': bool(re.search(r'(?is)<br', text_raw)),
    }


def render_meaning(card, new_plain):
    """新释义 + 原配图 tail。原卡用 <br> 分条时，把「；」还原成 <br>。"""
    tail = card.get('tail') or ''
    if tail:
        return new_plain + tail
    if card.get('multi_br') and '；' in new_plain:
        return '<br>'.join(x.strip() for x in new_plain.split('；') if x.strip())
    return new_plain


# ── 读取卡片 ──────────────────────────────────────────────────────────────
def load_cards():
    if not os.path.isfile(CARDS):
        raise SystemExit('缺少 %s：先跑 prepare' % CARDS)
    return json.loads(textio.read_text(CARDS))


def cards_by_id():
    return {int(c['id']): c for c in load_cards()}


# ── prepare ──────────────────────────────────────────────────────────────
def cmd_prepare(args):
    ids = AK.find_notes('deck:"%s" note:"%s"' % (DECK, NOTE_MODEL))
    notes = AK.notes_info(ids)
    rows = []
    for n in notes:
        f = n.get('fields') or {}
        g = lambda k: (f.get(k) or {}).get('value', '')
        card = {
            'id': int(n['noteId']),
            'index': g('Index'),
            'word': g('Word'),
            'read': g('Transliteration'),
            'pos': g('Part of Speech'),
            'mean_raw': g('Meaning'),
            'sent': g('Sentence'),
        }
        card.update(parse_meaning(card['mean_raw']))
        rows.append(card)
    rows.sort(key=lambda r: (int(r['index']) if str(r['index']).isdigit() else 10 ** 9))
    textio.dump_json(rows, CARDS, indent=0)
    tail = sum(1 for r in rows if r['tail'])
    manual = sum(1 for r in rows if r['manual'])
    multi = sum(1 for r in rows if r['multi_br'])
    print('prepare：%d 张 → %s' % (len(rows), os.path.relpath(CARDS, WSP.ROOT)))
    print('  配图 tail %d ｜ 内联标签 manual %d ｜ 多行 <br> %d' % (tail, manual, multi))
    if args.verbose:
        for r in rows[:3]:
            print('  sample', r['index'], r['word'], repr(r['text_plain'])[:60], 'tail=%r' % (r['tail'][:30],))
    return 0


# ── judge ────────────────────────────────────────────────────────────────
def facts_text(word, reading, lk):
    """JMdict → 紧凑词典行。"""
    try:
        matched = lk.lookup(word) if lk and lk.available else []
    except Exception:
        matched = []
    if not matched:
        return '未命中（按例句判断）'
    facts = JC.card_facts(matched, word, reading)
    parts = []
    for ent in (facts.get('entries') or [])[:2]:
        for se in ent.get('senses', [])[:4]:
            glosses = '; '.join(se.get('glosses') or [])
            tag = ('〔' + '、'.join(se.get('tags') or []) + '〕') if se.get('tags') else ''
            app = ('（' + se['applies'] + '）') if se.get('applies') else ''
            parts.append('%s %s%s%s' % (se.get('pos', ''), glosses, tag, app))
    return ' ｜ '.join(parts) or '未命中（按例句判断）'


def batch_input(chunk, lk, start_no=1):
    lines = []
    for k, c in enumerate(chunk, start_no):
        sent = (c.get('sent') or '').replace('<br>', ' / ').replace('<br/>', ' / ')
        lines.append('[%d] %s（%s）%s\n现义：%s\n例句：%s\n词典：%s' % (
            k, c['word'], c['read'], c['pos'], (c['text_plain'] or '')[:200],
            sent[:180], facts_text(c['word'], c['read'], lk)))
    return '\n\n'.join(lines)


def parse_json_obj(content):
    t = (content or '').strip()
    t = re.sub(r'^```(?:json)?\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    i, j = t.find('{'), t.rfind('}')
    if i < 0 or j <= i:
        raise ValueError('没有 JSON 对象')
    return json.loads(t[i:j + 1])


def chat_batch(cfg, chunk, lk, effort, retries=1):
    """调本地模型判一批；返回 items（已校验 i 连续）。"""
    import local_llm as L
    n = len(chunk)
    user = '共 %d 条：\n\n%s\n\n只输出 JSON 对象，items 共 %d 条，i 从 1 到 %d。' % (
        n, batch_input(chunk, lk), n, n)
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]
    last_err = None
    for attempt in range(retries + 1):
        res = L.chat(cfg, messages, enable_thinking=True, reasoning_effort=effort,
                     quiet=True, max_tokens=16384, timeout=900)
        try:
            obj = parse_json_obj(res.content)
            items = obj.get('items')
            if not isinstance(items, list) or len(items) != n:
                raise ValueError('items 数量 %s != %d' % (
                    len(items) if isinstance(items, list) else type(items).__name__, n))
            got = sorted(int(x.get('i', 0)) for x in items)
            if got != list(range(1, n + 1)):
                raise ValueError('i 不连续：%s' % got[:10])
            for x in items:
                if x.get('verdict') not in ('ok', 'bad'):
                    raise ValueError('verdict 非法：%r' % x.get('verdict'))
                if x['verdict'] == 'bad' and not str(x.get('meaning') or '').strip():
                    raise ValueError('bad 但 meaning 为空：i=%s' % x.get('i'))
                x['meaning'] = str(x.get('meaning') or '').strip()
                x['reason'] = str(x.get('reason') or '').strip()
            return items, res
        except Exception as e:
            last_err = e
            messages = messages + [
                {'role': 'assistant', 'content': (res.content or '')[:4000]},
                {'role': 'user', 'content': '上一条不是合格 JSON（%s）。请只输出 JSON 对象，'
                                            '字符串内不要出现英文双引号；items 仍为 %d 条。' % (e, n)},
            ]
    raise last_err


def load_results():
    if not os.path.isfile(RESULTS):
        return {}
    out = {}
    for line in textio.read_text(RESULTS).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if 'batch' in obj and 'items' in obj:
            out[int(obj['batch'])] = obj
    return out


def cmd_judge(args):
    import local_llm as L
    cards = load_cards()
    if args.only:
        wanted = set(int(x) for x in re.split(r'[,，\s]+', args.only) if x.strip())
        cards = [c for c in cards if int(c['id']) in wanted or int(c['index']) in wanted]
        print('只判 %d 张' % len(cards))
    bs = max(1, int(args.batch_size))
    batches = [cards[i:i + bs] for i in range(0, len(cards), bs)]
    done = load_results()
    cfg = L.load_config()
    lk = JC.Lookup()
    if not lk.available:
        print('⚠ JMdict 不可用，只能按例句判（质量会降）')
    os.makedirs(FAILED_DIR, exist_ok=True)
    todo = [(b, ch) for b, ch in enumerate(batches) if b not in done]
    if args.start_batch:
        todo = [(b, ch) for b, ch in todo if b >= args.start_batch]
    if args.limit:
        todo = todo[:args.limit]
    print('judge：共 %d 批，已完成 %d，本次跑 %d 批（batch=%d, effort=%s）'
          % (len(batches), len(done), len(todo), bs, args.effort))
    t0 = time.time()
    for n_done, (b, chunk) in enumerate(todo, 1):
        try:
            items, res = chat_batch(cfg, chunk, lk, args.effort)
        except Exception as e:
            raw = getattr(locals().get('res'), 'content', '') or ''
            with open(os.path.join(FAILED_DIR, 'b%04d.txt' % b), 'w', encoding='utf-8') as fh:
                fh.write(raw)
            print('[%d/%d] batch %d 失败：%s（已存 failed/b%04d.txt）'
                  % (n_done, len(todo), b, e, b))
            continue
        out = []
        for x, c in zip(items, chunk):
            out.append({
                'i': x['i'], 'id': c['id'], 'index': c['index'], 'word': c['word'],
                'verdict': x['verdict'], 'meaning': x['meaning'], 'reason': x['reason'],
            })
        row = {'batch': b, 'start': int(chunk[0]['index']), 'end': int(chunk[-1]['index']),
               'items': out, 'usage': getattr(res, 'summary', lambda: '')()}
        if args.dry:
            print(json.dumps(row, ensure_ascii=False)[:4000])
        else:
            with open(RESULTS, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + '\n')
        bad = sum(1 for x in out if x['verdict'] == 'bad')
        el = time.time() - t0
        eta = el / n_done * (len(todo) - n_done) / 60 if n_done else 0
        print('[%d/%d] batch %d（%s–%s）bad=%d ｜ %.0fs ｜ 剩约 %.0f 分'
              % (n_done, len(todo), b, chunk[0]['index'], chunk[-1]['index'], bad, el, eta))
        sys.stdout.flush()
    print('judge 结束')
    return 0


def load_verify():
    """verify.jsonl → {id: item}。"""
    if not os.path.isfile(VERIFY):
        return {}
    out = {}
    for line in textio.read_text(VERIFY).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        for x in obj.get('items') or []:
            if x.get('id') is not None:
                out[int(x['id'])] = x
    return out


def chat_verify_batch(cfg, chunk, lk, retries=1):
    """复核一批初审 bad：keep_old / fix。"""
    import local_llm as L
    n = len(chunk)
    lines = []
    for k, c in enumerate(chunk, 1):
        sent = (c.get('sent') or '').replace('<br>', ' / ')
        lines.append('[%d] %s（%s）%s\n旧义：%s\n初审新义：%s\n例句：%s\n词典：%s' % (
            k, c['word'], c['read'], c['pos'], c['old_plain'][:200], c['new_plain'][:120],
            sent[:180], facts_text(c['word'], c['read'], lk)))
    messages = [
        {'role': 'system', 'content': VERIFY_SYSTEM},
        {'role': 'user', 'content': '共 %d 条：\n\n%s\n\n只输出 JSON 对象，items 共 %d 条，i 从 1 到 %d。'
                                    % (n, '\n\n'.join(lines), n, n)},
    ]
    last_err = None
    for _ in range(retries + 1):
        res = L.chat(cfg, messages, enable_thinking=True, reasoning_effort='medium',
                     quiet=True, max_tokens=16384, timeout=900)
        try:
            obj = parse_json_obj(res.content)
            items = obj.get('items')
            if not isinstance(items, list) or len(items) != n:
                raise ValueError('items 数量不对')
            if sorted(int(x.get('i', 0)) for x in items) != list(range(1, n + 1)):
                raise ValueError('i 不连续')
            for x in items:
                if x.get('verdict') not in ('keep_old', 'fix'):
                    raise ValueError('verdict 非法：%r' % x.get('verdict'))
                if x['verdict'] == 'fix' and not str(x.get('meaning') or '').strip():
                    raise ValueError('fix 但 meaning 为空')
                x['meaning'] = str(x.get('meaning') or '').strip()
                x['reason'] = str(x.get('reason') or '').strip()
            return items, res
        except Exception as e:
            last_err = e
            messages = messages + [
                {'role': 'assistant', 'content': (res.content or '')[:3000]},
                {'role': 'user', 'content': '上一条不是合格 JSON（%s）。请只输出 JSON 对象，'
                                            '字符串内不要出现英文双引号；items 仍为 %d 条。' % (e, n)},
            ]
    raise last_err


def cmd_verify(args):
    import local_llm as L
    changes = collect_changes(use_verify=False)
    bad = [c for c in changes if c['verdict'] == 'bad' and not c['manual']]
    if args.only:
        wanted = set(int(x) for x in re.split(r'[,，\s]+', args.only) if x.strip())
        bad = [c for c in bad if int(c['id']) in wanted or int(c['index']) in wanted]
        print('只复核 %d 张' % len(bad))
    done = load_verify()
    todo = [c for c in bad if int(c['id']) not in done]
    bs = max(1, int(args.batch_size))
    batches = [todo[i:i + bs] for i in range(0, len(todo), bs)]
    cfg = L.load_config()
    lk = JC.Lookup()
    os.makedirs(FAILED_DIR, exist_ok=True)
    print('verify：初审 bad %d，已复核 %d，本次 %d 批' % (len(bad), len(done), len(batches)))
    t0 = time.time()
    for n_done, chunk in enumerate(batches, 1):
        try:
            items, res = chat_verify_batch(cfg, chunk, lk)
        except Exception as e:
            print('[%d/%d] 失败：%s' % (n_done, len(batches), e))
            continue
        out = []
        for x, c in zip(items, chunk):
            out.append({'i': x['i'], 'id': c['id'], 'index': c['index'], 'word': c['word'],
                        'verdict': x['verdict'], 'meaning': x['meaning'], 'reason': x['reason']})
        row = {'batch': n_done - 1, 'items': out}
        with open(VERIFY, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
        keep = sum(1 for x in out if x['verdict'] == 'keep_old')
        print('[%d/%d] keep_old=%d fix=%d ｜ %.0fs'
              % (n_done, len(batches), keep, len(out) - keep, time.time() - t0))
        sys.stdout.flush()
    print('verify 结束')
    return 0


# ── lint / 汇总 ──────────────────────────────────────────────────────────
def is_short_style(old_plain):
    if len(old_plain) <= 10:
        return True
    seps = old_plain.count('；') + old_plain.count('/') + old_plain.count('、')
    return len(old_plain) <= 30 and seps >= 2


def lint_item(new_plain, old_plain):
    """机械闸门；返回不合格原因列表（空 = 可写）。"""
    m = (new_plain or '').strip()
    short = is_short_style(old_plain)
    cap = 18 if short else 60
    bad = []
    if not m:
        bad.append('空')
    if len(m) > cap:
        bad.append('过长%d>%d' % (len(m), cap))
    if re.search(r'[A-Za-z]', m):
        bad.append('含英文')
    if re.search(r'[ぁ-んァ-ヶ]', m):
        bad.append('含日文假名')
    if '<' in m or '>' in m:
        bad.append('含HTML')
    if '。' in m:
        bad.append('含句号')
    if re.search(r'[（(）)]', m):
        bad.append('含括号')
    if m == (old_plain or '').strip():
        bad.append('与旧值相同')
    if '；' in m and any(not s.strip() for s in m.split('；')):
        bad.append('空义项')
    return bad


def load_manual():
    """人工补漏：{index 或 id: {"new": "...", "reason": "..."}}。"""
    if not os.path.isfile(MANUAL):
        return {}
    try:
        return json.loads(textio.read_text(MANUAL)) or {}
    except ValueError:
        return {}


def collect_changes(use_verify=True):
    """读 results（+ verify）→ 每条 bad 的最终处置。

    status: ok / fix（可写）/ keep_old（复核认为旧义可接受）/ unverified（复核没跑到）
    """
    cards = cards_by_id()
    res = load_results()
    verify = load_verify() if use_verify else {}
    out = []
    for b in sorted(res):
        for x in res[b]['items']:
            c = cards.get(int(x['id']))
            if not c:
                continue
            old_plain = c['text_plain']
            first = (x.get('meaning') or '').strip()
            if x['verdict'] == 'ok':
                status, new_plain = 'ok', ''
            else:
                v = verify.get(int(c['id']))
                if v is None:
                    status, new_plain = 'unverified', first
                elif v['verdict'] == 'keep_old':
                    status, new_plain = 'keep_old', ''
                else:
                    status = 'fix'
                    new_plain = (v.get('meaning') or first).strip()
            reasons = lint_item(new_plain, old_plain) if status == 'fix' else []
            out.append({
                'id': c['id'], 'index': c['index'], 'word': c['word'], 'read': c['read'],
                'pos': c.get('pos', ''), 'sent': c.get('sent', ''),
                'verdict': x['verdict'], 'status': status, 'reason': x.get('reason', ''),
                'old_raw': c['mean_raw'], 'old_plain': old_plain,
                'new_plain': new_plain,
                'new_raw': render_meaning(c, new_plain) if status == 'fix' else '',
                'lint': reasons, 'manual': bool(c.get('manual')),
            })
    # 人工补漏：模型判 ok、但抽查确认有错的卡
    manual = load_manual()
    if manual:
        by_index = {str(c['index']): c for c in cards.values()}
        by_id = {str(c['id']): c for c in cards.values()}
        seen = {int(c['id']): c for c in out}
        for key, spec in manual.items():
            c = by_index.get(str(key)) or by_id.get(str(key))
            if not c or not isinstance(spec, dict):
                continue
            new_plain = str(spec.get('new') or '').strip()
            if not new_plain:
                continue
            reasons = lint_item(new_plain, c['text_plain'])
            row = {
                'id': c['id'], 'index': c['index'], 'word': c['word'], 'read': c['read'],
                'pos': c.get('pos', ''), 'sent': c.get('sent', ''),
                'verdict': 'bad', 'status': 'fix', 'reason': '[manual] ' + str(spec.get('reason') or ''),
                'old_raw': c['mean_raw'], 'old_plain': c['text_plain'],
                'new_plain': new_plain,
                'new_raw': render_meaning(c, new_plain),
                'lint': reasons, 'manual': bool(c.get('manual')),
            }
            if int(c['id']) in seen:
                prev = seen[int(c['id'])]
                out.remove(prev)
            out.append(row)
    return out


def cmd_report(args):
    changes = collect_changes()
    judged = len(changes)
    bad = [c for c in changes if c['verdict'] == 'bad']
    ok = [c for c in changes if c['verdict'] == 'ok']
    writable = [c for c in changes if c['status'] == 'fix' and not c['lint'] and not c['manual']]
    manual = [c for c in changes if c['status'] == 'fix' and c['manual']]
    lint_bad = [c for c in changes if c['status'] == 'fix' and c['lint']]
    keep_old = [c for c in changes if c['status'] == 'keep_old']
    unverified = [c for c in changes if c['status'] == 'unverified']
    out = []
    out.append('# core6000 Meaning 重写评审')
    out.append('')
    out.append('- 生成时间：%s' % dt.datetime.now().isoformat(timespec='seconds'))
    out.append('- 已判：%d / 6000 ｜ 初审 ok：%d ｜ 初审 bad：%d' % (judged, len(ok), len(bad)))
    out.append('- 复核保留旧义：%d ｜ 待复核（没跑到）：%d' % (len(keep_old), len(unverified)))
    out.append('- 最终可写：%d ｜ lint 拦下：%d ｜ manual：%d' % (
        len(writable), len(lint_bad), len(manual)))
    out.append('')
    out.append('## 按 Index 分段')
    out.append('')
    out.append('| 段 | 已判 | 初审 bad | 复核保留 | 可写 |')
    out.append('|---|---|---|---|---|')
    for lo in range(1, 6001, 500):
        hi = lo + 499
        seg = [c for c in changes if str(c['index']).isdigit() and lo <= int(c['index']) <= hi]
        seg_bad = [c for c in seg if c['verdict'] == 'bad']
        seg_keep = [c for c in seg if c['status'] == 'keep_old']
        seg_w = [c for c in writable if str(c['index']).isdigit() and lo <= int(c['index']) <= hi]
        out.append('| %d–%d | %d | %d | %d | %d |' % (
            lo, hi, len(seg), len(seg_bad), len(seg_keep), len(seg_w)))
    out.append('')
    out.append('## 将改清单（前 300 条）')
    out.append('')
    out.append('| Index | 词 | 旧释义 | 新释义 | 理由 |')
    out.append('|---|---|---|---|---|')
    for c in writable[:300]:
        esc = lambda s: (s or '').replace('|', '｜').replace('\n', ' ')[:90]
        out.append('| %s | %s | %s | %s | %s |' % (
            c['index'], esc(c['word']), esc(c['old_plain']), esc(c['new_plain']), esc(c['reason'])))
    if len(writable) > 300:
        out.append('')
        out.append('…其余 %d 条见 changes.tsv' % (len(writable) - 300))
    if lint_bad:
        out.append('')
        out.append('## lint 拦下（不写库）')
        out.append('')
        for c in lint_bad[:80]:
            out.append('- %s %s：%s → %s（%s）' % (
                c['index'], c['word'], c['old_plain'], c['new_plain'], '、'.join(c['lint'])))
    if manual:
        out.append('')
        out.append('## manual（含内联标签，不写库）')
        out.append('')
        for c in manual[:40]:
            out.append('- %s %s：%s → %s' % (c['index'], c['word'], c['old_plain'], c['new_plain']))

    md = os.path.join(WSP.OUTPUT, 'core6000_meaning_review_%s.md' % dt.date.today().isoformat())
    textio.write_text(md, '\n'.join(out) + '\n')
    tsv = os.path.join(DIR, 'changes.tsv')
    lines = ['index\tword\tread\told\tnew\tverdict\tstatus\tlint\treason']
    for c in changes:
        lines.append('\t'.join(str(x).replace('\t', ' ').replace('\n', ' ') for x in (
            c['index'], c['word'], c['read'], c['old_plain'], c['new_plain'],
            c['verdict'], c['status'], ','.join(c['lint']), c['reason'])))
    textio.write_text(tsv, '\n'.join(lines) + '\n')
    print('评审报告：%s' % os.path.relpath(md, WSP.ROOT))
    print('全量清单：%s' % os.path.relpath(tsv, WSP.ROOT))
    print('已判 %d ｜ ok %d ｜ bad %d ｜ 可写 %d ｜ lint 拦 %d ｜ manual %d'
          % (judged, len(ok), len(bad), len(writable), len(lint_bad), len(manual)))
    for c in writable[:20]:
        print('  %s %s：%s → %s' % (c['index'], c['word'], c['old_plain'], c['new_plain']))
    return 0


# ── apply / revert ───────────────────────────────────────────────────────
def _live_map(ids):
    return {int(k): v for k, v in AK.notes_map(ids).items()}


def cmd_apply(args):
    changes = collect_changes()
    cand = [c for c in changes if c['status'] == 'fix' and not c['lint'] and not c['manual']]
    if args.only:
        wanted = set(int(x) for x in re.split(r'[,，\s]+', args.only) if x.strip())
        cand = [c for c in cand if int(c['id']) in wanted or int(c['index']) in wanted]
    if not cand:
        print('没有可写的卡（先跑 judge / report）')
        return 0
    live = _live_map([c['id'] for c in cand])
    changed, stale = [], []
    for c in cand:
        got = AK.field(live.get(int(c['id'])), 'Meaning')
        if got != c['old_raw']:
            stale.append(c)
        else:
            changed.append(c)
    if stale:
        print('⚠ 有 %d 张库里的 Meaning 已变（prepare 之后被改过），跳过：%s'
              % (len(stale), ', '.join(str(c['id']) for c in stale[:10])))
    print('将改 %d 项（只写 Meaning；配图 tail 原样保留）' % len(changed))
    by = {}
    for c in changed:
        seg = (int(c['index']) // 500) * 500 + 1
        by[seg] = by.get(seg, 0) + 1
    print('分段：' + ' ｜ '.join('%d–%d:%d' % (k, k + 499, v) for k, v in sorted(by.items())))
    for c in changed[:40]:
        print('  %s %s：%s → %s' % (c['index'], c['word'], c['old_plain'], c['new_plain']))
    if len(changed) > 40:
        print('  …（其余 %d 条见 report/changes.tsv）' % (len(changed) - 40))
    if not args.commit:
        print('演练结束；加 --commit 才写库')
        return 0

    ts = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = os.path.join(DIR, 'backup_meaning_%s.json' % ts)
    backup = {}
    for c in changed:
        backup[str(c['id'])] = {'word': c['word'], 'Meaning': c['old_raw']}
    textio.dump_json(backup, backup_path)
    print('旧 Meaning 已备份：%s（%d 条）' % (os.path.relpath(backup_path, WSP.ROOT), len(backup)))

    pairs = [(int(c['id']), {'Meaning': c['new_raw']}) for c in changed]
    ok_n, fail = 0, []
    for i in range(0, len(pairs), 50):
        for nid, fields in pairs[i:i + 50]:
            try:
                AK.update_note_fields(nid, fields)
                ok_n += 1
            except Exception as e:
                fail.append((nid, str(e)))
        time.sleep(0.2)
    print('写入：成功 %d，失败 %d' % (ok_n, len(fail)))
    if fail:
        for nid, e in fail[:10]:
            print('  ✗ %s %s' % (nid, e))
    expected = {int(c['id']): {'Meaning': c['new_raw']} for c in changed}
    bad = AK.verify_note_fields(expected)
    print('回读：%d 张不一致' % len(bad))
    if bad:
        for nid, fields in list(bad.items())[:10]:
            print('  ✗ %s %s' % (nid, fields))
    applied = os.path.join(DIR, 'applied_%s.json' % ts)
    textio.dump_json({'backup': backup_path, 'count': len(changed),
                      'items': [{'id': c['id'], 'index': c['index'], 'word': c['word'],
                                 'old': c['old_raw'], 'new': c['new_raw']} for c in changed]}, applied)
    print('应用记录：%s' % os.path.relpath(applied, WSP.ROOT))
    print('回退：python code/cli.py meaning revert --backup %s --commit'
          % os.path.relpath(backup_path, WSP.ROOT))
    return 0 if not bad and not fail else 1


def cmd_revert(args):
    path = args.backup
    if not path:
        files = sorted(glob.glob(BACKUP_GLOB))
        if not files:
            raise SystemExit('没有 backup_meaning_*.json')
        path = files[-1]
    data = json.loads(textio.read_text(path))
    pairs = [(int(k), {'Meaning': v['Meaning']}) for k, v in data.items()]
    print('将还原 %d 张（来自 %s）' % (len(pairs), os.path.relpath(path, WSP.ROOT)))
    for nid, f in pairs[:20]:
        print('  %s → %s' % (nid, f['Meaning'][:60]))
    if not args.commit:
        print('演练结束；加 --commit 才写库')
        return 0
    for nid, fields in pairs:
        AK.update_note_fields(nid, fields)
    bad = AK.verify_note_fields({nid: f for nid, f in pairs})
    print('回读：%d 张不一致' % len(bad))
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description='core6000 Meaning 重写（只写 Meaning）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('prepare', help='抽字段 + 拆分配图 tail')
    p.add_argument('--verbose', action='store_true')
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser('judge', help='本地模型分批判定（可断点续跑）')
    p.add_argument('--batch-size', type=int, default=40)
    p.add_argument('--effort', default='medium', choices=['low', 'medium'])
    p.add_argument('--limit', type=int, default=0, help='本次最多跑几批')
    p.add_argument('--start-batch', type=int, default=0)
    p.add_argument('--only', default='', help='只判这些 note id / index（逗号分隔）')
    p.add_argument('--dry', action='store_true', help='只打印，不写 results.jsonl（pilot 用）')
    p.set_defaults(func=cmd_judge)

    p = sub.add_parser('verify', help='复核初审 bad：保留旧义 / 修正新义')
    p.add_argument('--batch-size', type=int, default=40)
    p.add_argument('--only', default='', help='只复核这些 note id / index（逗号分隔）')
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser('report', help='生成评审报告 + changes.tsv')
    p.set_defaults(func=cmd_report)

    p = sub.add_parser('apply', help='写库（默认演练）')
    p.add_argument('--commit', action='store_true')
    p.add_argument('--only', default='', help='只写这些 note id / index（逗号分隔）')
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser('revert', help='按 backup_meaning_*.json 还原')
    p.add_argument('--backup', default='')
    p.add_argument('--commit', action='store_true')
    p.set_defaults(func=cmd_revert)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
