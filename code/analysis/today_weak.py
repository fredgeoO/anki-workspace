# -*- coding: utf-8 -*-
"""列出「最近 N 天答得不好的卡」的名字 —— 只要单词名 / 语法名。

数据默认来自 AnkiConnect（Anki 需开着，永远是实时数据）；加 ``--source snapshot``
则直读收藏快照文件，不需要 Anki 在运行。

用法::

    python code/analysis/today_weak.py                     # 今天（重来+困难）
    python code/analysis/today_weak.py --rating again      # 只看「重来」
    python code/analysis/today_weak.py --rating hard       # 只看「困难」
    python code/analysis/today_weak.py --days 3            # 近三天
    python code/analysis/today_weak.py --plain             # 纯名字，一行一个（好复制/管道）
    python code/analysis/today_weak.py -v                  # 附读音、释义
    python code/analysis/today_weak.py --kind grammar      # 只看语法
    python code/analysis/today_weak.py --deck "日语::N3"   # 限定牌组
    python code/analysis/today_weak.py --json              # 机器可读
    python code/analysis/today_weak.py --out data/weak/today.json

约定：**名字走 stdout，统计信息走 stderr**，所以 ``--plain`` 的输出可以直接
重定向到文件或喂给别的脚本。
"""
import argparse
import html
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import anki_api as AK  # noqa: E402  唯一的 Anki 访问点（在线 AnkiConnect + 离线快照）
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

RATING_CODE = {'again': 1, 'hard': 2}
RATING_CN = {1: '重来', 2: '困难'}
KIND_CN = {'word': '单词', 'grammar': '语法'}

# ---- 「名字」按模型优先取哪个字段（顺序即优先级） -------------------------
NAME_FIELDS = ('Word', 'VocabKanji', 'Card', 'Expression', 'Vocabulary', 'Front')
# ---- -v 时要额外显示的字段 -------------------------------------------------
EXTRA_FIELDS = {
    'Japanese Vocabulary': ('Transliteration', 'Meaning'),
    'eggrolls-JLPT10k-v3.5': ('VocabFurigana', 'VocabDefSC'),
    'どんなときどう使う日本語表現文型Note': ('Bracket', 'MeaningCN'),
}
# ---- 语法类模型的识别（名字里含这些词就算语法） ---------------------------
GRAMMAR_HINTS = ('文型', '语法', '文法', 'grammar')

_TAG = re.compile(r'<[^>]+>')
_KANA_READING = re.compile(r'\[[ぁ-ゖァ-ヺー]+\]')   # 独[どく] → 独


def clean(s):
    """把 Anki 字段值洗成一行纯文本。"""
    s = re.sub(r'\[sound:[^\]]*\]', ' ', s or '')
    s = re.sub(r'<br\s*/?>', ' / ', s, flags=re.I)
    s = _TAG.sub(' ', s)
    s = html.unescape(s)
    s = _KANA_READING.sub('', s)
    s = re.sub(r'[\x00-\x08\x0b-\x1f]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _note_kind(model, field_names):
    if any(h in model.lower() for h in GRAMMAR_HINTS):
        return 'grammar'
    # 兜底：带 Card + MeaningJP 的文型表也是语法
    if 'Card' in field_names and 'MeaningJP' in field_names:
        return 'grammar'
    return 'word'


def _pick_name(fields):
    for key in NAME_FIELDS:
        v = clean(fields.get(key, ''))
        if v:
            return v
    for key, raw in fields.items():          # 最后兜底：第一个非空字段
        v = clean(raw)
        if v and not v.isdigit():
            return v
    return '(无名字)'


def _extras(model, fields):
    keys = EXTRA_FIELDS.get(model)
    if not keys:                              # 未知模型：挑几个像释义的字段
        keys = tuple(k for k in fields
                     if any(t in k for t in ('Meaning', 'Def', 'Translit', 'Bracket')))
    out = []
    for k in keys:
        v = clean(fields.get(k, ''))
        if v and v not in out:
            out.append(v)
    return out


# ===========================================================================
# 数据源 1：AnkiConnect（实时）
# ===========================================================================
def bad_notes_live(days, ratings, deck=None, kind=None):
    """返回 (笔记列表, 今日作答卡片数)。"""
    per_rating = {}
    for r in ratings:
        per_rating[r] = set(AK.find_notes(AK.rated_query(days, ease=r, deck=deck)))

    note_ids = sorted(set().union(*per_rating.values())) if per_rating else []
    if not note_ids:
        return [], _answered_cards(days, deck)

    by_id = AK.notes_map(note_ids, chunk=100)

    # 牌组名：需要 cardsInfo
    card_ids = [c for n in by_id.values() for c in n.get('cards', [])]
    deck_of_card = {cid: c['deckName']
                    for cid, c in AK.cards_map(card_ids, chunk=500).items()}

    items = []
    for nid in note_ids:
        n = by_id.get(nid)
        if not n:
            continue
        flds = AK.field_values(n)
        model = n['modelName']
        k = _note_kind(model, list(flds))
        if kind and k != kind:
            continue
        items.append({
            'noteId': nid,
            'name': _pick_name(flds),
            'kind': k,
            'model': model,
            'deck': next((deck_of_card[c] for c in n.get('cards', [])
                          if c in deck_of_card), ''),
            'again': 1 if nid in per_rating.get('again', ()) else 0,
            'hard': 1 if nid in per_rating.get('hard', ()) else 0,
            'extras': _extras(model, flds),
        })
    return _sort(items), _answered_cards(days, deck)


def _answered_cards(days, deck=None):
    try:
        return AK.answered_cards(days, deck=deck)
    except AK.AnkiError:
        return None


# ===========================================================================
# 数据源 2：收藏快照（离线）
# ===========================================================================
def bad_notes_snapshot(path, days, ratings, deck=None, kind=None):
    if not os.path.exists(path):
        raise SystemExit('快照不存在：%s' % path)

    codes = [RATING_CODE[r] for r in ratings]
    with AK.Snapshot.open(path=path) as snap:
        mid2model = snap.notetype_map()
        rows = snap.reviewed_rows(days=days, ease=codes)
        total = snap.reviewed_card_count(days=days)

    agg = {}
    for r in rows:
        a = agg.setdefault(r['nid'], {'again': 0, 'hard': 0, 'mid': r['mid'],
                                      'flds': r['flds'], 'deck': r['deck']})
        a['again' if r['ease'] == 1 else 'hard'] += 1

    items = []
    for nid, a in agg.items():
        model, order = mid2model.get(a['mid'], ('?', []))
        vals = (a['flds'] or '').split('\x1f')
        flds = {order[i]: vals[i] for i in range(min(len(order), len(vals)))}
        k = _note_kind(model, list(flds))
        if kind and k != kind:
            continue
        dname = (a['deck'] or '').replace('\x1f', '::')
        if deck and not dname.startswith(deck):
            continue
        items.append({
            'noteId': nid, 'name': _pick_name(flds), 'kind': k, 'model': model,
            'deck': dname, 'again': a['again'], 'hard': a['hard'],
            'extras': _extras(model, flds),
        })
    return _sort(items), total


# ===========================================================================
# 输出
# ===========================================================================
def _sort(items):
    return sorted(items, key=lambda x: (x['kind'], -x['again'], -x['hard'],
                                        x['name']))


def render(items, plain=False, verbose=False):
    if plain:
        for it in items:
            print(it['name'])
        return
    if not items:
        print('（没有符合条件的卡片）')
        return
    for k in ('word', 'grammar'):
        group = [x for x in items if x['kind'] == k]
        if not group:
            continue
        print('%s (%d)' % (KIND_CN[k], len(group)))
        for it in group:
            mark = '重来' if it['again'] else '困难'
            extra = '  ' + ' | '.join(it['extras']) if verbose and it['extras'] else ''
            print('  [%s] %s%s' % (mark, it['name'], extra))
        print()


def main(argv=None):
    p = argparse.ArgumentParser(
        description='列出最近 N 天答得不好的卡（单词名 / 语法名）。',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('用法::')[1] if '用法::' in __doc__ else None)
    p.add_argument('--days', type=int, default=1,
                   help='最近几天，默认 1 = 今天')
    p.add_argument('--rating', default='both',
                   choices=('again', 'hard', 'both'),
                   help='重来 / 困难 / 两者，默认 both')
    p.add_argument('--kind', default='both', choices=('word', 'grammar', 'both'),
                   help='只看单词或只看语法，默认 both')
    p.add_argument('--deck', help='限定牌组（前缀匹配，快照模式）')
    p.add_argument('--source', default='anki', choices=('anki', 'snapshot'),
                   help='数据源：anki=AnkiConnect 实时（默认），snapshot=读快照')
    p.add_argument('--snapshot', default=None,
                   help='快照路径，默认 %s' % WSP.SNAP_ANKI_SNAP)
    p.add_argument('--plain', action='store_true',
                   help='纯名字输出，一行一个')
    p.add_argument('-v', '--verbose', action='store_true',
                   help='附上读音 / 释义')
    p.add_argument('--json', action='store_true', help='输出 JSON')
    p.add_argument('--out', help='额外把结果写到这个文件')
    a = p.parse_args(argv)

    ratings = ('again', 'hard') if a.rating == 'both' else (a.rating,)
    kind = None if a.kind == 'both' else a.kind

    if a.source == 'anki':
        items, answered = bad_notes_live(a.days, ratings, a.deck, kind)
    else:
        items, answered = bad_notes_snapshot(
            a.snapshot or WSP.SNAP_ANKI_SNAP, a.days, ratings, a.deck, kind)

    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
    else:
        render(items, a.plain, a.verbose)

    label = '今天' if a.days == 1 else '近 %d 天' % a.days
    stat = '%s %s → %d 个（重来 %d，困难 %d）' % (
        label, '+'.join(RATING_CN[RATING_CODE[r]] for r in ratings),
        len(items), sum(1 for x in items if x['again']),
        sum(1 for x in items if x['hard']))
    if answered:
        stat += '；同期作答卡片 %d 张（占 %.1f%%）' % (
            answered, 100.0 * len(items) / answered)
    print(stat, file=sys.stderr)

    if a.out:
        path = a.out if os.path.isabs(a.out) else os.path.join(WSP.ROOT, a.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'days': a.days, 'ratings': list(ratings),
                       'answered_cards': answered, 'items': items},
                      fh, ensure_ascii=False, indent=1)
        print('已写入 %s' % path, file=sys.stderr)
    return 0


if __name__ == '__main__':
    # Anki 没开时给一句中文提示（含"请确认 Anki 已启动"），不是 traceback
    with AK.guard():
        raise SystemExit(main())
