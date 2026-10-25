# -*- coding: utf-8 -*-
"""把 Anki 里的「词汇资产」抽成一份紧凑快照，供覆盖率统计使用。

产出 ``data/vocab_cover/vocab_state.json``，结构::

    {
      "generated_at": "2026-10-05T17:20:00",
      "source": "anki-connect v6",
      "mature_days": 21,
      "decks": {                     # 每个逻辑卡组的 note 级统计
        "core6000": {"notes": 6000, "studied": 2409, "mature": 1930, "deck_names": [...]},
        "jlpt":     {...}, "mined": {...}
      },
      "words": {                     # 规范键 = 归一化写法，一个词条一条
        "食べる": {
          "surface": "食べる", "readings": ["たべる"],
          "core": 192,               # core6000 排序号；null = 不在 core6000
          "jlpt": ["N4"],            # 考级词汇命中的级别/频段（可多个；扁平化前是子卡组名）
          "mined": false,            # 是否来自「素材生词 / 例句」
          "reps": 7, "lapses": 1, "interval": 63, "type": 2, "queue": 2,
          "known": true,             # 刷过至少一次
          "mature": true,            # 复习卡且间隔 >= 21 天
          "kana_only": false
        }, ...
      },
      "affixes": ["さん", "やすい", ...]     # 卡组里以 〜 标记的接辞（只作参考）
    }

注意：**不建「读音 -> 汉字词」的别名表**。原因是实测发现它制造大量假命中
（假名 た 会被对上 他/田，ガス 会被对上 8 个不相干的词）。假名写法 -> 汉字词
交给 Sudachi 的 normalized_form 处理（已验证 キレイ->奇麗、やけ->焼け）。

用法::

    python code/analysis/vocab_cover/collect_vocab.py            # 连 AnkiConnect 现拉
    python code/analysis/vocab_cover/collect_vocab.py --offline  # 读已有 JSON 打印概况
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import re
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _norm import norm_word, primary_form, reading_keys  # noqa: E402
from _deps import DATA_DIR, STATE_JSON, WSP  # noqa: E402
import jp_decks as JD  # noqa: E402  牌组常量 + 标签→级别/频段（考级词汇已扁平化）
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

OUT_JSON = STATE_JSON
AC_URL = os.environ.get('ANKICONNECT_URL', 'http://127.0.0.1:8765')

# 逻辑卡组 -> 卡组名（前缀匹配，含子卡组）
DECK_SPECS = {
    'core6000': ['0-日本语学习::0-词汇::1-高频日语单词 6000'],
    'jlpt': ['0-日本语学习::0-词汇::2-考级词汇'],
    'mined': ['0-日本语学习::0-词汇::0-素材生词', '0-日本语学习::2-例句'],
}

WORD_FIELDS = ('Word', 'VocabKanji', 'Expression', 'Front', 'Vocabulary', '単語')
READING_FIELDS = ('Transliteration', 'VocabFurigana', 'Reading', 'Kana')
INDEX_FIELDS = ('Index', 'NoteID', 'Order')
MATURE_DAYS = 21          # Anki 的「成熟卡」阈值
BATCH = 400
TAG_RE = re.compile(r'<[^>]+>')


# ---------------------------------------------------------------- AnkiConnect
def ac(action: str, **params):
    payload = json.dumps({'action': action, 'version': 6, 'params': params}).encode('utf-8')
    req = urllib.request.Request(AC_URL, data=payload,
                                headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as fh:
        body = json.loads(fh.read().decode('utf-8'))
    if body.get('error'):
        raise RuntimeError(f'AnkiConnect {action}: {body["error"]}')
    return body.get('result')


def chunks(seq, n=BATCH):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def clean_field(value: str) -> str:
    """去 HTML、去 [sound:...]、合并空白。"""
    if not value:
        return ''
    v = re.sub(r'\[sound:[^\]]*\]', '', value)
    v = re.sub(r'<br\s*/?>', ' ', v, flags=re.I)
    v = TAG_RE.sub('', v)
    v = (v.replace('&nbsp;', ' ').replace('&amp;', '&')
          .replace('&lt;', '<').replace('&gt;', '>'))
    return re.sub(r'\s+', ' ', v).strip()


# ------------------------------------------------------------------- 抽取主流程
def pick(fields: dict, names) -> str:
    for name in names:
        v = fields.get(name, '')
        if v:
            return v
    return ''


def collect() -> dict:
    version = ac('version')
    deck_names = ac('deckNames') or []

    def logical_of(deck_name: str) -> str:
        for logical, prefixes in DECK_SPECS.items():
            for p in prefixes:
                if deck_name == p or deck_name.startswith(p + '::'):
                    return logical
        return ''

    words: dict = {}
    affixes: set = set()
    deck_stats = collections.defaultdict(lambda: {'notes': 0, 'studied': 0, 'mature': 0,
                                                  'deck_names': []})
    note_lex = {}       # nid -> 规范键

    for deck_name in deck_names:
        logical = logical_of(deck_name)
        if not logical:
            continue
        deck_stats[logical]['deck_names'].append(deck_name)
        nids = ac('findNotes', query=f'deck:"{deck_name}"') or []
        for batch in chunks(nids):
            for note in ac('notesInfo', notes=batch) or []:
                nid = note['noteId']
                fields = {k: clean_field(v.get('value', ''))
                          for k, v in note.get('fields', {}).items()}
                raw_surface = pick(fields, WORD_FIELDS)
                if not raw_surface:
                    raw_surface = next((v for v in fields.values() if v), '')
                if not raw_surface:
                    continue
                if '〜' in raw_surface or '～' in raw_surface:
                    affixes.add(norm_word(raw_surface))
                surface = primary_form(raw_surface)
                key = norm_word(surface)
                if not key:
                    continue

                entry = words.get(key)
                if entry is None:
                    entry = words[key] = {
                        'surface': surface, 'readings': [], 'core': None, 'jlpt': [],
                        'mined': False, 'reps': 0, 'lapses': 0, 'interval': 0,
                        'type': 0, 'queue': 0, 'known': False, 'mature': False,
                    }
                for rk in reading_keys(pick(fields, READING_FIELDS)):
                    if rk and rk not in entry['readings']:
                        entry['readings'].append(rk)
                if logical == 'core6000':
                    rank_txt = re.sub(r'\D', '', pick(fields, INDEX_FIELDS))
                    if rank_txt:
                        rank = int(rank_txt)
                        if entry['core'] is None or rank < entry['core']:
                            entry['core'] = rank
                elif logical == 'jlpt':
                    # 考级词汇已扁平化：子卡组没了，级别/频段改由 eggrolls 标签给出
                    tags = note.get('tags', [])
                    lv = JD.level_from_tags(tags)
                    label = ('%s%s' % (lv, JD.band_from_tags(tags) or '')) if lv else deck_name
                    if label not in entry['jlpt']:
                        entry['jlpt'].append(label)
                elif logical == 'mined':
                    entry['mined'] = True
                note_lex[nid] = (key, logical)

    # 卡片状态
    by_note = collections.defaultdict(list)
    for batch in chunks(list(note_lex)):
        cids = ac('findCards', query=' OR '.join(f'nid:{n}' for n in batch)) or []
        for cbatch in chunks(cids, 200):
            for card in ac('cardsInfo', cards=cbatch) or []:
                by_note[card['note']].append(card)

    for nid, (key, _logical) in note_lex.items():
        cards = by_note.get(nid, [])
        reps = max([c.get('reps') or 0 for c in cards] or [0])
        lapses = max([c.get('lapses') or 0 for c in cards] or [0])
        interval = max([c.get('interval') or 0 for c in cards] or [0])
        known = reps > 0
        mature = any((c.get('type') == 2) and (c.get('interval') or 0) >= MATURE_DAYS
                     for c in cards)
        best = max(cards, key=lambda c: (c.get('interval') or 0), default={})
        entry = words[key]
        entry['reps'] = max(entry['reps'], reps)
        entry['lapses'] = max(entry['lapses'], lapses)
        entry['interval'] = max(entry['interval'], interval)
        entry['type'] = max(entry['type'], max([c.get('type') or 0 for c in cards] or [0]))
        entry['queue'] = best.get('queue', entry['queue'])
        entry['known'] = entry['known'] or known
        entry['mature'] = entry['mature'] or mature

    # 卡组 note 级统计（每个 note 只算一次，避免同词多卡/跨卡组重复计数）
    for nid, (key, logical) in note_lex.items():
        cards = by_note.get(nid, [])
        known = max([c.get('reps') or 0 for c in cards] or [0]) > 0
        mature = any((c.get('type') == 2) and (c.get('interval') or 0) >= MATURE_DAYS
                     for c in cards)
        st = deck_stats[logical]
        st['notes'] += 1
        st['studied'] += 1 if known else 0
        st['mature'] += 1 if mature else 0

    return {
        'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
        'source': f'anki-connect v{version}',
        'mature_days': MATURE_DAYS,
        'decks': {k: dict(v) for k, v in deck_stats.items()},
        'words': words,
        'affixes': sorted(a for a in affixes if a),
    }


def summarize(state: dict) -> None:
    words = state['words']
    print(f"来源 {state['source']}  生成于 {state['generated_at']}")
    for logical, st in sorted(state['decks'].items()):
        print(f"  {logical:<9} notes={st['notes']:>6}  已学={st['studied']:>6}"
              f"  成熟={st['mature']:>6}  卡组 x{len(st['deck_names'])}")
    core = [w for w in words.values() if w['core']]
    jlpt = [w for w in words.values() if w['jlpt']]
    mined = [w for w in words.values() if w['mined']]
    print(f"  词条 {len(words)}：core6000 {len(core)} / 考级 {len(jlpt)} / 素材 {len(mined)}"
          f"  接辞条目 {len(state.get('affixes', []))}")


def main() -> int:
    ap = argparse.ArgumentParser(description='抽取 Anki 词汇资产快照')
    ap.add_argument('--offline', action='store_true', help='不联网，只读已有 JSON 打印概况')
    ap.add_argument('--out', default=OUT_JSON)
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    if args.offline:
        with open(args.out, encoding='utf-8') as fh:
            summarize(json.load(fh))
        return 0

    state = collect()
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False)
    summarize(state)
    print(f'\n写出 {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
