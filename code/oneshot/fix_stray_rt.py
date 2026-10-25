# -*- coding: utf-8 -*-
"""修复字段里**野 `<rt>`**（不在 `<ruby>` 里的读音）—— 2026-10-11。

症状（本地模型常见，`check_cards.py` 2026-10-11 起会报）：
    `<ruby>救<rt>すく</rt></ruby>援<rt>えん</rt>：名词。救援。`
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ 这个 `援` 的 rt 没有 ruby 包着
渲染时读音会当普通文字直接显示在词条里（`援えん：名词`）。

修法是确定性的：把 `X<rt>Y</rt>` 包成 `<ruby>X<rt>Y</rt></ruby>`（X 只取一个字）。
**先改产出文件、再改库**，两侧都改才不会再被下一次 `write` 顶回去。

    python fix_stray_rt.py                     # 演练：只打印将要改的片段
    python fix_stray_rt.py --commit            # 改 data/pipeline/gen/output_*.json + 写库
    python fix_stray_rt.py --tag "动画::…" --commit   # 只处理一集（默认整个例句 deck）
"""
import argparse
import glob
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import anki_api as AK      # noqa: E402
import check_cards as C    # noqa: E402  野 <rt> 的判据实现只有一份
import paths as WSP        # noqa: E402
import textio              # noqa: E402

GEN = os.path.join(WSP.DATA_PIPELINE, 'gen')
PAIR = re.compile(r'([^<>])<rt>([^<>]*)</rt>')


def fix(value):
    """把野 <rt> 包进 ruby；返回 (新值, 改动的片段列表)。"""
    if not value or '<rt>' not in value:
        return value, []
    holes = {}

    def stash(m):
        holes['\x00%d\x00' % len(holes)] = m.group(0)
        return '\x00%d\x00' % (len(holes) - 1)

    # 先把成对的 ruby 整块藏起来，剩下能匹配到的 <rt> 才是野的
    masked = C.RUBY_BLOCK.sub(stash, value)
    frags = []

    def wrap(m):
        frags.append(m.group(0))
        return '<ruby>%s<rt>%s</rt></ruby>' % (m.group(1), m.group(2))

    masked = PAIR.sub(wrap, masked)
    for k, v in holes.items():
        masked = masked.replace(k, v)
    return masked, frags


def fix_file(path):
    cards = textio.load_json(path)
    changed = []
    for c in cards:
        for fld in ('AINote', 'SentenceHTML'):
            new, frags = fix(c.get(fld))
            if frags:
                c[fld] = new
                changed.append((c['noteId'], fld, frags))
    if changed:
        textio.dump_json(cards, path)
    return changed


def main():
    ap = argparse.ArgumentParser(description='修复 <ruby> 之外的野 <rt>')
    ap.add_argument('--tag', default=None, help='只处理这一集（默认整个例句 deck）')
    ap.add_argument('--commit', action='store_true', help='真写（默认只演练）')
    a = ap.parse_args()

    total = 0
    print('=' * 96)
    print('产出文件')
    print('=' * 96)
    for p in sorted(glob.glob(os.path.join(GEN, 'output_*.json'))):
        changed = fix_file(p) if a.commit else _dry(p)
        for nid, fld, frags in changed:
            total += 1
            print('  %s %s %s  %s' % (os.path.basename(p), nid, fld, frags[:2]))
    print()
    print('=' * 96)
    print('Anki 字段%s' % ('（真写）' if a.commit else '（演练）'))
    print('=' * 96)
    query = ('tag:%s' % a.tag) if a.tag else 'deck:"%s"' % '0-日本语学习::2-例句'
    ids = AK.find_notes(query)
    todo = []
    for n in AK.notes_info(ids):
        f = AK.field_values(n)
        for fld in ('AINote', 'Sentence HTML'):
            new, frags = fix(f.get(fld, ''))
            if frags:
                todo.append((n['noteId'], fld, new, frags))
                print('  %s %s  %s' % (n['noteId'], fld, frags[:2]))
    if a.commit:
        by_note = {}
        for nid, fld, new, _f in todo:
            by_note.setdefault(nid, {})[fld] = new
        for nid, fields in by_note.items():
            AK.update_note_fields(nid, fields)
        print('  已写库 %d 张' % len(by_note))
    else:
        print('  演练结束，未写库（加 --commit 真改）')
    print()
    print('改动合计：产出 %d 处、库 %d 处' % (total, len(todo)))


def _dry(path):
    """演练：按与 fix_file 完全相同的判据算出改动，但不写文件。"""
    changed = []
    for c in textio.load_json(path):
        for fld in ('AINote', 'SentenceHTML'):
            _new, frags = fix(c.get(fld))
            if frags:
                changed.append((c['noteId'], fld, frags))
    return changed


if __name__ == '__main__':
    with AK.guard():
        main()
