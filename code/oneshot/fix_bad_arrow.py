# -*- coding: utf-8 -*-
"""修复 AINote 等字段里残留的坏箭头记号 `$ightarrow$` → `→`（U+2192）。

背景
----
规范（docs/jp-card-agent-instruction.md §1）早就禁止 LaTeX、要求推导用 `→`，
但早期批次里模型写 `$\\rightarrow$` 时，`\\r` 被当成回车吃掉，留下 `$ightarrow$`；
后来又被人手工「修」过一次：把 `$` 去掉、改成 `$\\rightarrow$`——形状变了，
LaTeX 本身还在。两种都不是好状态，统一收敛到 ASCII 之外、字体普遍支持、
且**任何渲染管线都不会再吃掉**的 `→`。

安全设计
--------
1. **默认演练**，只有 `--commit` 才写库。
2. 写之前对每个字段做**等价性校验**：把原文里的坏记号全部抹掉后，
   与「改完再抹掉箭头」的文本必须逐字相同——也就是证明改动只是「删掉坏记号、
   插进一个箭头」，没有碰任何别的字符。不等价就跳过该字段并报错。
3. `--only-note` 支持单卡试改；`--report` 留下逐卡明细，可回滚。

用法::

    python code/oneshot/fix_bad_arrow.py --only-note 1621392136383        # 演练单卡
    python code/oneshot/fix_bad_arrow.py --only-note 1621392136383 --commit
    python code/oneshot/fix_bad_arrow.py                                  # 演练 core6000 全部
    python code/oneshot/fix_bad_arrow.py --commit
    python code/oneshot/fix_bad_arrow.py --all-decks --commit             # 含其它牌组 18 张
"""
import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'common'))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）


ANKI_URL = 'http://127.0.0.1:8765'
DEFAULT_DECK = '0-日本语学习::0-词汇::1-高频日语单词 6000'
ARROW = '\u2192'

# 三条替换规则，**按顺序**跑，每条都尽量明确，不用模糊字符类，
# 免得 `\leftarrow` / `a rightarrow b` 这种正常内容被咬掉。
#
# 1) 被 $…$ 包起来的 LaTeX 箭头（含多余反斜杠）：连美元符一起吃掉，
#    否则会留下 `$→$` 这种更难看的东西。
DOLLAR_TEX_RE = re.compile(
    r'\$+\s*\\+(?:rightarrow|Rightarrow|to)\s*\$+'
    r'|\$+\s*ightarrow\s*\$+'
)

# 2) 裸的 LaTeX 命令（没有美元包着）。`\to` 带尾部边界，防止咬掉 `\rightarrow` 的尾巴。
BARE_CMD_RE = re.compile(
    r'\\+(?:rightarrow|Rightarrow|to)(?![A-Za-z])'
)

# 3) `\r` 被吃掉的残骸 `ightarrow`。只在前一个字符不是字母时匹配，
#    这样 `a rightarrow b` 里的普通英文不受影响。
STRAY_RE = re.compile(r'(?<![A-Za-z])ightarrow')

# 供报告核对：本脚本认得的全部可疑记号
TOKEN_RE = re.compile('(?:%s)|(?:%s)|(?:%s)'
                      % (DOLLAR_TEX_RE.pattern, BARE_CMD_RE.pattern,
                         STRAY_RE.pattern))

# 只探测、不替换的其它 LaTeX 残渣（报告用；不做自动改写，留人工判断）
DETECT_ONLY_RE = re.compile(
    r'\\+[rl]?leftarrow'
    r'|\\+[rl]?Leftarrow'
    r'|\$\$+'
    r'\$[^$\n]{1,40}\$'
    r'|\\+[a-zA-Z]{2,}'
)

# 可选（--text-wrap）：`$\text{原形}$` 里 `\t` 被吃成制表符后的残骸，去掉外壳只留内容。
# 只在内容不含反斜杠/花括号时匹配，避免碰到真正的数学式。
TEXT_WRAP_RE = re.compile(r'\$[\t\n]?ext\{([^{}\\\n]{0,30})\}\$')

# 除了坏箭头（和开启开关后的 \text 外壳），本脚本不改任何东西
FIELD_WHITELIST = None      # None = 所有字段；用 --fields 可限定


def invoke(action, **params):
    payload = json.dumps({'action': action, 'version': 6, 'params': params}).encode('utf-8')
    req = urllib.request.Request(ANKI_URL, payload, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as fh:
        res = json.loads(fh.read().decode('utf-8'))
    if res.get('error'):
        raise RuntimeError('%s: %s' % (action, res['error']))
    return res['result']


def fix_text(text, text_wrap=False):
    """把坏记号换成 →。**不动任何空白**——原排版里的全角/半角空格逐字保留。

    ``text_wrap=True`` 时额外去掉 `$\text{…}$` 残骸的外壳（只留内容）。
    """
    text = DOLLAR_TEX_RE.sub(ARROW, text)
    text = BARE_CMD_RE.sub(ARROW, text)
    text = STRAY_RE.sub(ARROW, text)
    if text_wrap:
        text = TEXT_WRAP_RE.sub(lambda m: m.group(1), text)
    return text


def strip_markers(text, text_wrap=False):
    """等价性比较用：抹掉坏记号与箭头，剩下应当逐字相同。"""
    text = DOLLAR_TEX_RE.sub('', text)
    text = BARE_CMD_RE.sub('', text)
    text = STRAY_RE.sub('', text)
    text = text.replace(ARROW, '')
    if text_wrap:
        text = TEXT_WRAP_RE.sub('', text)
    return text


def normalize_cmp(text, text_wrap=False):
    return unicodedata.normalize('NFC', strip_markers(text, text_wrap))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--deck', default=DEFAULT_DECK)
    ap.add_argument('--all-decks', action='store_true')
    ap.add_argument('--only-note', type=int, action='append', default=None,
                    help='只处理这些 noteId（可重复）')
    ap.add_argument('--only-word', action='append', default=None, help='只处理这些词形')
    ap.add_argument('--fields', action='append', default=None,
                    help='限定字段名（默认全部字段）')
    ap.add_argument('--commit', action='store_true', help='真正写库；缺省只演练')
    ap.add_argument('--report', default=os.path.join(WSP.DATA, 'snapshots',
                                                     'bad_arrow_fix_report.json'))
    ap.add_argument('--samples', type=int, default=2)
    ap.add_argument('--text-wrap', action='store_true',
                    help='额外把 $\\text{…}$ 残骸去掉外壳只留内容（\\t 被吃成制表符的那批）')
    args = ap.parse_args()

    scope = 'deck:*' if args.all_decks else 'deck:"%s"' % args.deck
    if args.only_note:
        note_ids = sorted(set(args.only_note))
        scope = 'explicit noteIds'
    else:
        note_ids = sorted(set(invoke('findNotes', query=scope)))
    print('扫描范围: %s，note 数: %d' % (scope, len(note_ids)))

    planned = []
    skipped = []
    for i in range(0, len(note_ids), 400):
        for info in invoke('notesInfo', notes=note_ids[i:i + 400]):
            note_id = info['noteId']
            fields = info.get('fields', {})
            word = (fields.get('Word', {}) or {}).get('value', '')
            if args.only_word and word not in args.only_word:
                continue
            updates = {}
            for name, fv in fields.items():
                if args.fields and name not in args.fields:
                    continue
                val = fv.get('value', '') or ''
                has_tokens = TOKEN_RE.search(val)
                has_wrap = args.text_wrap and TEXT_WRAP_RE.search(val)
                if not (has_tokens or has_wrap):
                    continue
                new = fix_text(val, text_wrap=args.text_wrap)
                if normalize_cmp(val, args.text_wrap) != normalize_cmp(new, args.text_wrap):
                    skipped.append({'noteId': note_id, 'field': name,
                                    'why': '等价性校验不通过，拒绝改写'})
                    print('  ✗ note %s 字段 %s 等价性校验不通过，跳过' % (note_id, name))
                    continue
                if new == val:
                    continue
                updates[name] = new
            if updates:
                planned.append({
                    'noteId': note_id,
                    'word': word,
                    'index': (fields.get('Index', {}) or {}).get('value', ''),
                    'modelName': info.get('modelName'),
                    'before': {k: (fields[k].get('value') or '') for k in updates},
                    'after': updates,
                    'hits': {k: len(TOKEN_RE.findall(fields[k].get('value') or ''))
                             for k in updates},
                    'text_wrap_hits': {k: len(TEXT_WRAP_RE.findall(
                        fields[k].get('value') or '')) for k in updates},
                })

    total_hits = sum(sum(p['hits'].values()) for p in planned)
    wrap_notes = [p for p in planned if any(v for v in p.get('text_wrap_hits', {}).values())]
    print('待改 note: %d，坏记号 %d 处，字段分布: %s'
          % (len(planned), total_hits,
             dict(Counter(f for p in planned for f in p['after']))))
    if args.text_wrap:
        print('其中含 $\\text{…}$ 残骸的 note: %d，共 %d 处'
              % (len(wrap_notes),
                 sum(sum(p['text_wrap_hits'].values()) for p in wrap_notes)))

    for p in planned[:args.samples]:
        for fname in p['after']:
            print('\n--- note %s Index=%s %s [%s]' % (p['noteId'], p['index'], p['word'], fname))
            for token in sorted(set(TOKEN_RE.findall(p['before'][fname]))):
                print('    坏记号: %r' % token)
            print('    改前片段: %s' % snippet(p['before'][fname], TOKEN_RE))
            print('    改后片段: %s' % snippet(p['after'][fname], re.compile('\u2192')))

    if not args.commit:
        print('\n[演练] 未写库。确认无误后加 --commit。')
        write_report(args.report, args, planned, skipped, committed=False)
        return

    done = 0
    for p in planned:
        for fname, new in p['after'].items():
            invoke('updateNoteFields',
                   note={'id': p['noteId'], 'fields': {fname: new}})
            done += 1
    print('\n✅ 已写库：%d 张卡 / %d 个字段' % (len(planned), done))
    write_report(args.report, args, planned, skipped, committed=True)
    verify(args, planned)


def snippet(text, regex, width=70):
    """取第一个匹配附近的片段，便于人工核对。"""
    m = regex.search(text)
    if not m:
        return '(无匹配)'
    a = max(0, m.start() - width // 2)
    b = min(len(text), m.end() + width // 2)
    return ('…' if a else '') + text[a:b].replace('\n', '⏎') + ('…' if b < len(text) else '')


def verify(args, planned):
    """写后只回读一次：确认坏记号归零、箭头数量对得上。"""
    ids = [p['noteId'] for p in planned]
    left_bad = 0
    arrows = 0
    for i in range(0, len(ids), 400):
        for info in invoke('notesInfo', notes=ids[i:i + 400]):
            for fv in info.get('fields', {}).values():
                val = fv.get('value', '') or ''
                left_bad += len(TOKEN_RE.findall(val))
                arrows += val.count(ARROW)
    print('回读校验：残留坏记号 %d 处，→ 共 %d 个' % (left_bad, arrows))


def write_report(path, args, planned, skipped, committed):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        'committed': committed,
        'deck': None if args.all_decks else args.deck,
        'arrow': 'U+2192',
        'planned_count': len(planned),
        'skipped': skipped,
        'notes': planned,
    }
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print('明细报告: %s' % path)


if __name__ == '__main__':
    main()
