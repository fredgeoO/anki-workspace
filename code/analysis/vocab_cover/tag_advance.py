# -*- coding: utf-8 -*-
"""给「需要提前学的卡」打临时标签：把 target_gap 里的卡组内未学词 addTags。

词表口径与 metrics.target_gap 完全一致：语料前 V 高频词（V = 达到目标覆盖率所需词数）
中，未学且 bucket 属于 DECK_BUCKETS（core6000/jlpt/mined）的词——卡已在卡组里，无需挖掘。

用法::

    python tag_advance.py --target 0.90 --tag 素材激活 [--dry-run]

产出 ``data/vocab_cover/advance_tag.json``（词表 + note id 清单，留痕可复查）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _deps import DATA_DIR  # noqa: E402
import collect_vocab as CV  # noqa: E402
import metrics as M  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口

OUT_JSON = os.path.join(DATA_DIR, 'advance_tag.json')


def logical_of(deck_name: str) -> str:
    """卡组名 -> 逻辑卡组（前缀匹配，含子卡组）；与 collect_vocab.collect 同规则。"""
    for logical, prefixes in CV.DECK_SPECS.items():
        for p in prefixes:
            if deck_name == p or deck_name.startswith(p + '::'):
                return logical
    return ''


def build_note_lex() -> dict:
    """nid -> (规范键, 逻辑卡组)——与 collect_vocab.collect() 完全相同的取词规则。"""
    note_lex = {}
    for dn in CV.ac('deckNames') or []:
        logical = logical_of(dn)
        if not logical:
            continue
        nids = CV.ac('findNotes', query=f'deck:"{dn}"') or []
        for batch in CV.chunks(nids):
            for note in CV.ac('notesInfo', notes=batch) or []:
                fields = {k: CV.clean_field(v.get('value', ''))
                          for k, v in note.get('fields', {}).items()}
                raw_surface = CV.pick(fields, CV.WORD_FIELDS)
                if not raw_surface:
                    raw_surface = next((v for v in fields.values() if v), '')
                surface = CV.primary_form(raw_surface)
                key = CV.norm_word(surface)
                if key:
                    note_lex[note['noteId']] = (key, logical)
    return note_lex


def main() -> int:
    ap = argparse.ArgumentParser(description='给卡组内未学词打临时标签')
    ap.add_argument('--target', type=float, default=0.90, help='目标覆盖率（见 metrics.target_gap）')
    ap.add_argument('--tag', default='素材激活', help='要打的标签')
    ap.add_argument('--dry-run', action='store_true', help='只算词表，不写 Anki')
    args = ap.parse_args()

    m = M.compute()
    gap = next((g for g in m['target_gap'] if abs(g['target'] - args.target) < 1e-9), None)
    if gap is None:
        sys.exit(f'target {args.target} 不在 target_gap 里')
    top = m['freq_curve']['curve'][:gap['V']]
    targets = [r['word'] for r in top
               if not r['known'] and r['bucket'] in M.DECK_BUCKETS]
    print(f'target={args.target}  V={gap["V"]}  卡组内未学词={len(targets)}')

    note_lex = build_note_lex()
    by_key = {}
    for nid, (key, logical) in note_lex.items():
        by_key.setdefault(key, []).append((nid, logical))

    nids, unmatched = [], []
    for w in targets:
        hits = by_key.get(w)
        if not hits:
            unmatched.append(w)
        else:
            nids.extend(nid for nid, _ in hits)
    print(f'匹配到 note={len(nids)}（同词跨卡组会多张）  未匹配词={len(unmatched)}')
    if unmatched:
        print('未匹配:', ' '.join(unmatched[:20]))

    report = {
        'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
        'target': args.target, 'V': gap['V'], 'tag': args.tag,
        'word_count': len(targets), 'note_count': len(nids),
        'unmatched': unmatched,
        'words': sorted(targets),
        'notes': sorted(set(nids)),
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False)
    print(f'清单写出 {OUT_JSON}')

    if args.dry_run:
        print('--dry-run：未写 Anki')
        return 0

    for batch in CV.chunks(sorted(set(nids))):
        r = CV.ac('addTags', notes=batch, tags=args.tag)
        print(f'addTags {len(batch)} -> {r}')

    tagged = CV.ac('findNotes', query=f'tag:{args.tag}') or []
    print(f'验证 tag:{args.tag} 现有 note={len(tagged)}')
    return 0


if __name__ == '__main__':
    textio.setup()
    raise SystemExit(main())
