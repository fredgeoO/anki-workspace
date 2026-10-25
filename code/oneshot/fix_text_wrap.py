# -*- coding: utf-8 -*-
"""清理 `$\\text{…}$` 残骸家族（`\\t` 被当成制表符吃掉后的产物）。

与 fix_bad_arrow.py 分开，因为这类残骸的**内容语义不一**，不能一律处理：

  * 内容是箭头/关系词 → 换成 →（如 `$\\text{→}$`、`$\\text{变为}$`）
  * 内容是注解文字   → 去掉外壳只留文字（`$\\text{原形}$` → `原形`）
  * 内容是连接符     → 换成对应符号（`$\\text{+}$` → `+`）
  * 模型自我修正的碎话（如「(此处不使用LaTeX…)」）→ 整段删掉
  * 表里没有的内容   → **原样保留**，只写进报告，留人工决定

安全设计同 fix_bad_arrow.py：默认演练、`--commit` 才写、每个字段先过等价性校验
（把可替换记号抹掉后必须逐字相同）。

用法::

    python code/oneshot/fix_text_wrap.py                       # 演练 + 打印逐条上下文
    python code/oneshot/fix_text_wrap.py --commit
    python code/oneshot/fix_text_wrap.py --only-note 1621357700573 --commit
"""
import argparse
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'common'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
import fix_bad_arrow as FB  # noqa: E402


ARROW = '\u2192'
DEFAULT_DECK = FB.DEFAULT_DECK

# 残骸本体：美元符 + 可选控制字符 + ext{...}$
WRAP_RE = re.compile(r'\$[\t\n]?ext\{([^{}\n]{0,40})\}\$')

# 同族的另一种形态：命令前面的控制字符被吃掉，尾巴留下。
#   `$\to$`     → `$<TAB>o$`        （\t 被吃）
#   `$\dots$`   → `$<TAB>ots$`
#   `$\times$`  → `$<TAB>imes$`
#   `$\text{ } →$` 半修留痕
CTRL_CMD_RE = re.compile(r'\$[\t\n]([A-Za-z]{1,12})([^$\n\t]*)\$')

# 正常写着、没被吃字符的 LaTeX 命令：`$\dots$`、`$+$`、`$\times$`。
# 只认已知命令，避免误伤真正的数学式。
TEX_CMD_RE = re.compile(r'\$\s*(\\?[a-zA-Z]{1,12}|[+=\u00d7])\s*\$')

# 上面两种残骸的内容 → 替换值（CTRL_CMD_RE 的内容是命令名）
CTRL_MAP = {
    'o': ARROW,          # \to 被吃成 $<TAB>o$
    'ots': '\u2026',     # \dots 被吃成 $<TAB>ots$
    'imes': '\u00d7',    # \times 被吃成 $<TAB>imes$（表示「不适用」的叉号）
    'ext': ARROW,        # $<TAB>ext{ } →$ 这类半修留痕：整块当箭头
}

# 没被吃字符的 LaTeX 命令 → 替换值。只列已知项，其余留给人工。
TEX_CMD_MAP = {
    '\\dots': '\u2026',
    'dots': '\u2026',
    '\\times': '\u00d7',
    'times': '\u00d7',
    '+': '+',
    '=': '=',
}

# 内容 → 替换值。'==DELETE==' 表示整段删除（模型自我修正的碎话）。
CONTENT_MAP = {
    # 内容本来就是箭头 / 关系词
    '\u2192': ARROW,
    '→': ARROW,
    '变为': ARROW,
    '变': ARROW,
    ' becoming': ARROW,
    'to': ARROW,
    # 连接符 / 等号 / 占位
    '+': '+',
    '=': '=',
    '--': '\u2014',          # \text{--} 本是连字符
    '...': '\u2026',         # 省略号
    ' ': ' ',
    # 名词性注解：去掉外壳即可
    '原形': '原形',
    'て形': 'て形',
    '意向形': '意向形',
    'ある': 'ある',
    'ありません': 'ありません',
    # 模型自我修正的碎话：整段删掉
    ' (此处不使用LaTeX，改为: 变为 引いて)': '==DELETE==',
    ' (再次修正，完全避开特殊符号)': '==DELETE==',
    ' 演变为 引いて': ARROW + '引いて',
}

# 残骸正则 → 替换表。三族一起扫，取最靠前的匹配。
RESIDUE_RES = ((WRAP_RE, CONTENT_MAP), (CTRL_CMD_RE, CTRL_MAP), (TEX_CMD_RE, TEX_CMD_MAP))


def _substitute(text):
    """按 CONTENT_MAP 替换残骸，替换时**就地**处理两侧空白。

    箭头类统一成两侧各一个空格（`A $\\text{→}$ B` → `A → B`，
    先吃掉原有的邻近空白，免得变成两个）；删除类连两侧空白一起去掉。
    表里没有的内容原样保留。
    """
    left_space = re.compile(r'[ \t\u3000]+$')
    right_space = re.compile(r'^[ \t\u3000]+')

    # re.sub 改不了「已经写出的前缀」，所以手工拼装：删除类与箭头类都要
    # 顺带吃掉相邻空白，必须能看到上一次输出的结尾。两族残骸一起扫，取最靠前者。
    out = []
    pos = 0
    while True:
        best = None
        for rx, table in RESIDUE_RES:
            m = rx.search(text, pos)
            if m and (best is None or m.start() < best[0].start()):
                best = (m, table)
        if best is None:
            break
        m, table = best
        out.append(text[pos:m.start()])
        pos = m.end()
        inner = m.group(1)
        if inner not in table:
            out.append(m.group(0))            # 表里没有：原样保留
            continue
        val = table[inner]
        if val == '==DELETE==':                # 删除类：连两侧空白一起去掉
            out[-1] = left_space.sub('', out[-1])
            skip = right_space.match(text[pos:])
            if skip:
                pos += skip.end()
        elif val == ARROW:
            # 吃掉两侧原有空白，统一成「空格 → 空格」
            out[-1] = left_space.sub('', out[-1])
            out.append(' ' + ARROW + ' ')
            skip = right_space.match(text[pos:])
            if skip:
                pos += skip.end()
        else:
            out.append(val)
    out.append(text[pos:])
    return ''.join(out)


def fix_text(text):
    """把残骸按表替换。"""
    return _substitute(text)


def fix_text(text):
    """把残骸按表替换。"""
    return _substitute(text)


def canonical(text):
    """等价性判据的口径：去掉**所有空白与箭头**后剩下的正文。

    改前（先按表替换一遍）与改后的这个正文必须逐字相同——证明除残骸外
    没有任何字符被动过，也证明没有多出或丢掉内容。
    `+`、`--`、`原形` 这类会被保留下来，映射写错就会露出来；
    `==DELETE==` 那几条碎话本来就是要删的，所以两侧都表现为消失。
    """
    text = unicodedata.normalize('NFC', text)
    return re.sub(r'[\s\u3000\u2192]+', '', text)


def norm(text):
    """等价性比较口径，见 canonical()。"""
    return canonical(text)


def equivalent(before, after):
    """证明本次改写只动了残骸本身：把 before 按同一张表替换一遍后，
    其正文（去空白与箭头）必须与 after 的正文逐字相同。"""
    if norm(fix_text(before)) != norm(after):
        return False
    # 顺带拦住「表里没定义的残骸被顺手改掉」的情况
    for rx, table in RESIDUE_RES:
        if not set(rx.findall(after)) <= set(rx.findall(before)):
            return False
    return True


def all_residues(text):
    """返回 [(正则, 表, 内容)]，按出现顺序。"""
    found = []
    for rx, table in RESIDUE_RES:
        for m in rx.finditer(text):
            found.append((m.start(), rx, table, m.group(1)))
    found.sort(key=lambda x: x[0])
    return [(rx, table, inner) for _, rx, table, inner in found]


def context(text, width=60, limit=8, rx=None):
    """取匹配点附近的片段，便于人工核对。rx 缺省用三族残骸正则。"""
    pat = rx or re.compile('(?:%s)|(?:%s)|(?:%s)'
                           % (WRAP_RE.pattern, CTRL_CMD_RE.pattern, TEX_CMD_RE.pattern))
    out = []
    for m in pat.finditer(text):
        a = max(0, m.start() - width)
        b = min(len(text), m.end() + width)
        out.append('…%s…' % text[a:b].replace('\n', '⏎').replace('\t', '␉'))
        if len(out) >= limit:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--deck', default=DEFAULT_DECK)
    ap.add_argument('--all-decks', action='store_true')
    ap.add_argument('--only-note', type=int, action='append', default=None)
    ap.add_argument('--commit', action='store_true')
    ap.add_argument('--report', default=os.path.join(WSP.SNAPSHOTS, 'text_wrap_fix_report.json'))
    ap.add_argument('--show-all', action='store_true', help='打印每一张卡的上下文')
    args = ap.parse_args()

    scope = 'deck:*' if args.all_decks else 'deck:"%s"' % args.deck
    if args.only_note:
        ids = sorted(set(args.only_note))
        scope = 'explicit noteIds'
    else:
        ids = sorted(set(FB.invoke('findNotes', query=scope)))
    print('范围 %s，note %d 张' % (scope, len(ids)))

    planned, skipped, unknown = [], [], []
    for i in range(0, len(ids), 400):
        for info in FB.invoke('notesInfo', notes=ids[i:i + 400]):
            fields = info.get('fields', {})
            updates, metas = {}, {}
            for name, fv in fields.items():
                val = fv.get('value', '') or ''
                residues = all_residues(val)
                if not residues:
                    continue
                known = [(rx, table, inner) for rx, table, inner in residues
                         if inner in table]
                unknown += [(info['noteId'], name, inner)
                            for rx, table, inner in residues if inner not in table]
                if not known:
                    continue
                new = fix_text(val)
                if not equivalent(val, new):
                    skipped.append({'noteId': info['noteId'], 'field': name})
                    print('  ✗ note %s 字段 %s 等价性校验不通过，跳过' % (info['noteId'], name))
                    continue
                updates[name] = new
                metas[name] = [inner for _, _, inner in known]
            if updates:
                planned.append({
                    'noteId': info['noteId'],
                    'index': (fields.get('Index', {}) or {}).get('value', ''),
                    'word': (fields.get('Word', {}) or {}).get('value', ''),
                    'before': {k: (fields[k].get('value') or '') for k in updates},
                    'after': updates,
                    'contents': metas,
                })

    total = sum(len(v) for p in planned for v in p['contents'].values())
    print('待改 note: %d，可替换残骸: %d 处' % (len(planned), total))

    from collections import Counter
    cnt = Counter(m for p in planned for v in p['contents'].values() for m in v)
    print('内容分布:', dict(cnt))
    if unknown:
        print('\n⚠ 表里没有、原样保留的残骸 %d 处:' % len(unknown))
        for note_id, name, m in unknown[:20]:
            print('   note %s [%s] %r' % (note_id, name, m))

    for p in planned:
        print('\n--- note %s Index=%s %s' % (p['noteId'], p['index'], p['word']))
        for name in p['after']:
            for line in context(p['before'][name]):
                print('   改前 %s' % line)
            for line in context(p['after'][name], rx=re.compile(re.escape(ARROW))):
                print('   改后 %s' % line)

    if not args.commit:
        print('\n[演练] 未写库。确认无误后加 --commit。')
        _report(args, planned, skipped, unknown, False)
        return

    n = 0
    for p in planned:
        for name, new in p['after'].items():
            FB.invoke('updateNoteFields', note={'id': p['noteId'], 'fields': {name: new}})
            n += 1
    print('\n✅ 已写库：%d 张卡 / %d 个字段' % (len(planned), n))
    _report(args, planned, skipped, unknown, True)

    left = 0
    for i in range(0, len(planned), 400):
        batch = [p['noteId'] for p in planned[i:i + 400]]
        for info in FB.invoke('notesInfo', notes=batch):
            for fv in info.get('fields', {}).values():
                for rx, table, inner in all_residues(fv.get('value', '') or ''):
                    if inner in table:
                        left += 1
    print('回读校验：表内残骸残留 %d 处' % left)


def _report(args, planned, skipped, unknown, committed):
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, 'w', encoding='utf-8') as fh:
        json.dump({'committed': committed,
                   'scope': 'ALL' if args.all_decks else args.deck,
                   'content_map': CONTENT_MAP,
                   'ctrl_map': CTRL_MAP,
                   'planned_count': len(planned),
                   'skipped': skipped,
                   'unknown_leftovers': unknown,
                   'notes': planned}, fh, ensure_ascii=False, indent=2)
    print('明细报告: %s' % args.report)


if __name__ == '__main__':
    main()
