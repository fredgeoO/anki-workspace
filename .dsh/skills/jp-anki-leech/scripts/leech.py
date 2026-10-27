# -*- coding: utf-8 -*-
r"""leech 难卡：只读扫描 + 计划校验 + 安全改写 + 回滚（默认演练）。

设计约束（与 AGENTS.md 一致）
------------------------------
* 只写白名单字段：`AINote` / `Meaning` / `Sentence Translation` /
  `VocabDefSC` / `VocabPlus` / `SentDefSC1..4`。
* 绝不写调度列（due/ivl/factor/type/queue/reps/lapses），绝不 suspend/unsuspend，
  绝不建卡/删卡/改模板。
* 默认只演练；`--commit` 才写。写前把旧值备份到 `data/leech/backup_*.json`，
  写后 `verify_note_fields` 回读；成功后默认摘掉 `leech` 标签（`--keep-leech` 保留）。
* 语义判断（病因、改写内容、记忆钩子）由调用本脚本的模型负责；脚本只做
  证据汇总、字段白名单、结构闸门、备份、回读。

子命令
------
    python leech.py scan [--query "tag:leech"] [--limit 100] [--out temp/leech_scan.json]
    python leech.py apply --plan data/leech/plan_xxx.json [--commit] [--keep-leech]
    python leech.py restore --backup data/leech/backup_xxx.json [--commit]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
_COMMON = os.path.join(_ROOT, 'code', 'common')
if _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)

import textio as T          # noqa: E402  import 即接管 UTF-8 stdio
import anki_api as AK       # noqa: E402  唯一 Anki 访问点
import check_cards          # noqa: E402  结构闸门（AINote / 字段硬规则）
import paths as WSP         # noqa: E402

# 每个笔记类型允许改的字段。**不要**在这里加 Word / Sentence / 读音 / 音频 / 调度列。
ALLOWED_FIELDS = {
    'Basic': ('AINote',),
    'Japanese Vocabulary': ('AINote', 'Meaning', 'Sentence Translation'),
    'eggrolls-JLPT10k-v3.5': (
        'VocabDefSC', 'VocabPlus',
        'SentDefSC1', 'SentDefSC2', 'SentDefSC3', 'SentDefSC4',
    ),
}

VERDICTS = ('overload', 'vague', 'understanding', 'interference', 'mnemonic')
VERDICT_CN = {
    'overload': '信息过载',
    'vague': '措辞/义项模糊',
    'understanding': '缺乏理解',
    'interference': '记忆干扰',
    'mnemonic': '缺记忆钩子',
}

TAG = re.compile(r'<[^>]+>')

# 数词/助数词识别：只用于**候选分组**，不替代语义判断。
NUMERALS = '一二三四五六七八九十百千万何'
NUMERAL_RE = re.compile(r'^([%s]+)(.+)$' % NUMERALS)
COUNTERS = {
    '日', '月', '年', '時', '分', '秒', '週間', 'ヶ月', 'か月', 'カ月',
    '人', '本', '枚', '回', '歳', '個', '匹', '杯', '階', '度', '遍',
    '番', '号', '円', 'つ', '人前', 'キロ', 'メートル', 'グラム',
    'センチ', 'ミリ', '冊', '台', '着', '足', '軒', '件', '組', '倍',
    '割', '点', '級', '等', '位', '頭', '羽', '皿', '泊', '周', '晩', '食',
}


# --------------------------------------------------------------------------- 小工具
def stamp():
    return datetime.datetime.now().strftime('%Y%m%d_%H%M%S')


def iso_now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def show_path(path):
    try:
        return os.path.relpath(path, WSP.ROOT).replace('\\', '/')
    except ValueError:
        return path


def visible(s):
    return TAG.sub('', s or '')


def plain_len(s):
    return len(visible(s))


def short_value(s, n=140):
    s = (s or '').replace('\r', ' ').replace('\n', ' ')
    return s if len(s) <= n else s[:n] + '…'


def split_senses(text):
    text = text or ''
    marks = re.findall(r'[①②③④⑤⑥]', text)
    if marks:
        return marks
    parts = re.split(r'[；;、，,]|<br\s*/?>', text)
    return [p.strip() for p in parts if p.strip()]


def section_names(ainote):
    return [s for s in re.findall(r'<b>([^<>：:]{1,16})[：:]?</b>', ainote or '') if s.strip()]


def as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if str(x).strip()]
    return [str(v)]


def is_eggrolls(model):
    return str(model or '').startswith('eggrolls')


def word_of(f):
    return f.get('Word') or f.get('VocabKanji') or f.get('Expression') or ''


def reading_of(model, f):
    return f.get('VocabFurigana') or f.get('Transliteration') or ''


def pos_of(model, f):
    return f.get('VocabPoS') or f.get('Part of Speech') or ''


def meaning_of(model, f):
    return f.get('VocabDefSC') if is_eggrolls(model) else (f.get('Meaning') or f.get('VocabDefSC') or '')


def has_audio(f):
    keys = ('Word Audio', 'Sentence Audio', 'VocabAudio',
            'SentAudio1', 'SentAudio2', 'SentAudio3', 'SentAudio4')
    return any('[sound:' in (f.get(k) or '') for k in keys)


def int_ids(v, label):
    """计划里的 id 数组 → [int]。不是数组 / 含非整数 → (None, 错误)。"""
    if not isinstance(v, list):
        return None, '%s 必须是数组' % label
    out = []
    for x in v:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            return None, '%s 含非整数：%r' % (label, x)
    return out, ''


def word_info(r):
    return {
        'noteId': r['noteId'],
        'word': r['word'],
        'reading': r['reading'],
        'lapses': r['lapses'],
    }


def cluster_rows(rows):
    """从本批 leech 里找**候选**干扰组：数词/助数词、同读音。

    数词组用「数字前缀 + 助数词后缀」判定（二日 / 八つ / 二月 / 八月 / 九月），
    所以 `経つ` 这类不以数字开头的词不会误入。分组只是候选，最终由人/模型判断。
    """
    clusters = []

    number_members = []
    for r in rows:
        m = NUMERAL_RE.match(r['word'] or '')
        if m and m.group(2) in COUNTERS:
            number_members.append((r, m.group(2)))
    if len(number_members) >= 2:
        subgroups = defaultdict(list)
        for r, suffix in number_members:
            subgroups[suffix].append(r)
        clusters.append({
            'kind': 'counter',
            'name': '数词/助数词',
            'why': '数字 + 助数词：%s' % '、'.join(sorted(subgroups)),
            'members': [r['noteId'] for r, _ in number_members],
            'words': [word_info(r) for r, _ in number_members],
            'subgroups': [{
                'suffix': suffix,
                'members': [r['noteId'] for r in group],
                'words': [word_info(r) for r in group],
            } for suffix, group in sorted(subgroups.items())],
        })

    by_reading = defaultdict(list)
    for r in rows:
        if r['reading']:
            by_reading[r['reading']].append(r)
    for reading, group in sorted(by_reading.items()):
        if len(group) < 2:
            continue
        clusters.append({
            'kind': 'reading',
            'name': '同读音',
            'why': '读音「%s」' % reading,
            'members': [r['noteId'] for r in group],
            'words': [word_info(r) for r in group],
            'subgroups': [],
        })

    # 去重（同一批 id 只留一组）
    out, seen = [], set()
    for c in clusters:
        key = (c['kind'], tuple(c['members']))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# --------------------------------------------------------------------------- 扫描
def collect(ids):
    """[noteId] → 带证据与提示的行。只读。"""
    notes = AK.notes_map(ids)
    cids = AK.cards_of_notes(ids)
    cards = AK.cards_info(cids) if cids else []
    by_note = defaultdict(list)
    for c in cards:
        try:
            by_note[int(c.get('note'))].append(c)
        except (TypeError, ValueError):
            continue

    rows = []
    for nid in ids:
        n = notes.get(int(nid))
        if not n:
            continue
        f = AK.field_values(n)
        model = n.get('modelName') or ''
        cs = by_note.get(int(nid), [])
        decks = sorted({c.get('deckName') for c in cs if c.get('deckName')})
        ainote = f.get('AINote') or ''
        meaning = meaning_of(model, f)
        if is_eggrolls(model):
            sents = [f.get('SentKanji%d' % i) or '' for i in (1, 2, 3, 4)]
            sents = [s for s in sents if s.strip()]
            examples = len(sents)
            sentence = ' / '.join(sents)
            sentence_len = max([plain_len(s) for s in sents] or [0])
        else:
            sentence = f.get('Sentence') or ''
            examples = 1 if sentence.strip() else 0
            sentence_len = plain_len(sentence)

        senses = split_senses(meaning)
        metrics = {
            'ainote_len': len(check_cards.text_of(ainote)),
            'ainote_sections': section_names(ainote),
            'meaning_len': plain_len(meaning),
            'meaning_senses': len(senses),
            'sentence_len': sentence_len,
            'examples': examples,
            'has_mnemonic': bool((f.get('VocabPlus') or '').strip())
            or any(k in ainote for k in ('记忆钩子', '谐音', '联想', '字源')),
            'has_audio': has_audio(f),
            'has_image': '<img' in ((f.get('Image') or '') + (f.get('Meaning') or '')),
        }
        lapses = max([int(c.get('lapses') or 0) for c in cs] or [0])
        reps = max([int(c.get('reps') or 0) for c in cs] or [0])
        hints = []
        if metrics['ainote_len'] > 400:
            hints.append('overload:AINote %d 字' % metrics['ainote_len'])
        if metrics['meaning_senses'] >= 4:
            hints.append('overload:%d 个义项' % metrics['meaning_senses'])
        if is_eggrolls(model) and examples >= 4:
            hints.append('overload:%d 条例句同屏' % examples)
        if not is_eggrolls(model) and sentence_len > 60:
            hints.append('overload:句长 %d' % sentence_len)
        if (metrics['meaning_senses'] >= 3
                and not re.search(r'[①②③④⑤⑥]', meaning)):
            hints.append('vague:义项未分场景')
        if not metrics['has_mnemonic']:
            hints.append('no-hook')
        if not ainote.strip() and not is_eggrolls(model):
            hints.append('no-ainote')
        if re.search(r'<(div|ul|li)\b', ainote):
            hints.append('legacy-ainote')
        if any(int(c.get('queue') or 0) == -1 for c in cs):
            hints.append('suspended')

        rows.append({
            'noteId': int(nid),
            'model': model,
            'deck': ' / '.join(decks),
            'word': word_of(f),
            'reading': reading_of(model, f),
            'pos': pos_of(model, f),
            'tags': list(n.get('tags') or []),
            'lapses': lapses,
            'reps': reps,
            'cards': [{
                'cardId': c.get('cardId'),
                'type': c.get('type'),
                'queue': c.get('queue'),
                'due': c.get('due'),
                'interval': c.get('interval'),
                'factor': c.get('factor'),
                'lapses': c.get('lapses'),
                'reps': c.get('reps'),
            } for c in cs],
            'fields': f,
            'metrics': metrics,
            'hints': hints,
            'similar': [],
        })
    mark_similar(rows)
    return rows


def mark_similar(rows):
    """同读音 / 近形 / 重复词 —— 只在本批 leech 内找，供人判断。"""
    index = defaultdict(list)
    for r in rows:
        if r['reading']:
            index[r['reading']].append(r)
    for group in index.values():
        if len(group) < 2:
            continue
        for r in group:
            for o in group:
                if o is r:
                    continue
                r['similar'].append({'noteId': o['noteId'], 'word': o['word'], 'why': '同读音'})

    for i, r in enumerate(rows):
        for o in rows[i + 1:]:
            if not r['word'] or not o['word'] or r['word'] == o['word']:
                continue
            if r['word'] in o['word'] or o['word'] in r['word']:
                r['similar'].append({'noteId': o['noteId'], 'word': o['word'], 'why': '近形'})
                o['similar'].append({'noteId': r['noteId'], 'word': r['word'], 'why': '近形'})

    for r in rows:
        seen = set()
        uniq = []
        for s in r['similar']:
            key = (s['noteId'], s['why'])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(s)
        r['similar'] = uniq[:3]


def cmd_scan(args):
    if args.note_id:
        ids = []
        for tok in re.split(r'[,\s]+', args.note_id.strip()):
            if not tok:
                continue
            try:
                ids.append(int(tok))
            except ValueError:
                print('noteId 不是整数：%s' % tok, file=sys.stderr)
                return 1
        existing = set(AK.find_notes('nid:' + ','.join(str(i) for i in ids))) if ids else set()
        missing = [i for i in ids if i not in existing]
        if missing:
            print('这些 noteId 在库里不存在，已跳过：%s' % ', '.join(str(i) for i in missing),
                  file=sys.stderr)
        ids = [i for i in ids if i in existing]
        ids = list(dict.fromkeys(ids))
        query = 'nid:' + ','.join(str(i) for i in ids)
    else:
        query = args.query
        ids = AK.find_notes(query, limit=(args.limit if args.limit and args.limit > 0 else None))

    if not ids:
        print('0 张：%s' % query)
        return 0

    rows = collect(ids)
    rows.sort(key=lambda r: (-r['lapses'], r['noteId']))
    clusters = cluster_rows(rows)
    payload = {
        'version': 1,
        'generated': iso_now(),
        'query': query,
        'count': len(rows),
        'cards': rows,
        'clusters': clusters,
    }

    out_path = None
    if not args.no_out:
        out_path = os.path.abspath(args.out)
        T.dump_json(payload, out_path)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    print('%-14s %-28s %-11s %6s %5s %4s %3s  %s' %
          ('noteId', 'model', 'word', 'lapses', 'AI字', '义项', '例', 'hints'))
    for r in rows:
        m = r['metrics']
        print('%-14d %-28s %-11s %6d %5d %4d %3d  %s' % (
            r['noteId'], str(r['model'])[:28], str(r['word'])[:11],
            r['lapses'], m['ainote_len'], m['meaning_senses'], m['examples'],
            ','.join(r['hints']) or '-'))

    if clusters:
        print('\n候选干扰组（需人判断；脚本不暂停）：')
        for c in clusters:
            members = ' / '.join('%s(%s)' % (w['word'], w['reading'] or '-')
                                 for w in c['words'])
            print('  [%s] %s' % (c['name'], members))
            for sg in c.get('subgroups', []):
                print('      子组 %s：%s' % (
                    sg['suffix'], '、'.join(w['word'] for w in sg['words'])))

    models = Counter(r['model'] for r in rows)
    hints = Counter(h.split(':')[0] for r in rows for h in r['hints'])
    print('\n共 %d 张：%s' % (len(rows), ' / '.join('%s %d' % (k, v) for k, v in models.most_common())))
    print('提示：%s' % (' / '.join('%s %d' % (k, v) for k, v in hints.most_common()) or '无'))
    if args.limit and len(ids) >= args.limit and not args.note_id:
        print('注意：已达到 --limit %d，可能还有更多；用 --limit 0 看全部。' % args.limit)
    if out_path:
        print('JSON：%s' % show_path(out_path))
    print('下一步：按 SKILL.md §三 写 plan.json，再 apply --plan …（先不加 --commit）')
    return 0


# --------------------------------------------------------------------------- 计划校验
def prepare_groups(groups):
    """校验干扰组建议：只读，不写字段、不暂停。"""
    errors, warnings = [], []
    if groups is None:
        return [], errors, warnings
    if not isinstance(groups, list):
        return None, ['groups 必须是数组'], warnings

    prepared = []
    for idx, g in enumerate(groups, 1):
        if not isinstance(g, dict):
            errors.append('groups 第 %d 项不是对象' % idx)
            continue
        name = str(g.get('name') or '').strip()
        if not name:
            errors.append('groups 第 %d 项缺 name' % idx)
            continue

        members, why = int_ids(g.get('members'), 'members')
        if members is None:
            errors.append('groups[%s] %s' % (name, why))
            continue
        if len(members) < 2:
            errors.append('groups[%s] members 至少 2 张' % name)
            continue
        if len(set(members)) != len(members):
            errors.append('groups[%s] members 有重复' % name)
            continue
        try:
            keep = int(g.get('keep'))
        except (TypeError, ValueError):
            errors.append('groups[%s] keep 不是整数' % name)
            continue
        if keep not in members:
            errors.append('groups[%s] keep %s 不在 members 里' % (name, keep))
            continue

        suspend, why = int_ids(g.get('suspend') or [], 'suspend')
        if suspend is None:
            errors.append('groups[%s] %s' % (name, why))
            continue
        if len(set(suspend)) != len(suspend):
            errors.append('groups[%s] suspend 有重复' % name)
            continue
        if keep in suspend:
            errors.append('groups[%s] keep 不能同时出现在 suspend 里' % name)
            continue
        extra = [x for x in suspend if x not in members]
        if extra:
            errors.append('groups[%s] suspend 有非成员：%s' % (name, extra))
            continue

        order, why = int_ids(g.get('order') or [], 'order')
        if order is None:
            errors.append('groups[%s] %s' % (name, why))
            continue
        if len(set(order)) != len(order):
            errors.append('groups[%s] order 有重复' % name)
            continue
        bad_order = [x for x in order if x not in members]
        if bad_order:
            errors.append('groups[%s] order 有非成员：%s' % (name, bad_order))
            continue

        evidence = str(g.get('evidence') or '').strip()
        if not evidence:
            errors.append('groups[%s] 缺 evidence' % name)
            continue
        contrast = str(g.get('contrast') or '').strip()
        if not contrast:
            warnings.append('groups[%s] 缺 contrast：干扰组最好给一张对比表' % name)

        notes = AK.notes_map(members)
        missing = [x for x in members if x not in notes]
        if missing:
            errors.append('groups[%s] 这些 noteId 不存在：%s' % (name, missing))
            continue
        word_map = {}
        for nid in members:
            n = notes[nid]
            f = AK.field_values(n)
            word_map[nid] = {
                'noteId': nid,
                'word': word_of(f) or '(无词字段)',
                'reading': reading_of(n.get('modelName') or '', f),
            }

        suspend_cards = {}
        if suspend:
            scids = AK.cards_of_notes(suspend)
            scards = AK.cards_info(scids) if scids else []
            for c in scards:
                try:
                    suspend_cards.setdefault(int(c.get('note')), []).append(int(c.get('cardId')))
                except (TypeError, ValueError):
                    continue
            for nid in suspend:
                if nid not in suspend_cards:
                    warnings.append('groups[%s] noteId %s 没有卡，无法暂停' % (name, nid))

        prepared.append({
            'name': name,
            'members': members,
            'keep': keep,
            'suspend': suspend,
            'order': order,
            'evidence': evidence,
            'contrast': contrast,
            'word_map': word_map,
            'suspend_cards': suspend_cards,
        })

    if errors:
        return None, errors, warnings
    return prepared, errors, warnings


def prepare_apply(items, allow_untagged):
    """校验整个计划；任何硬错误都返回 (None, errors)，绝不写半批。"""
    errors, warnings = [], []
    nids = []
    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append('第 %d 项不是对象' % idx)
            continue
        try:
            nids.append(int(item.get('noteId')))
        except (TypeError, ValueError):
            errors.append('第 %d 项 noteId 不是整数：%r' % (idx, item.get('noteId')))
    if len(set(nids)) != len(nids):
        errors.append('计划里 noteId 有重复')
    if errors:
        return None, errors, warnings

    notes = AK.notes_map(nids)
    prepared = []
    for idx, item in enumerate(items, 1):
        nid = int(item.get('noteId'))
        n = notes.get(nid)
        if not n:
            errors.append('[%s] 笔记不存在' % nid)
            continue
        model = n.get('modelName') or ''
        allowed = ALLOWED_FIELDS.get(model)
        if not allowed:
            errors.append('[%s] 不认识的笔记类型 %r（本技能只处理 Basic / Japanese Vocabulary / eggrolls-JLPT10k-v3.5）'
                          % (nid, model))
            continue

        old = AK.field_values(n)
        tags = set(n.get('tags') or [])
        old_ainote = old.get('AINote') or ''
        if model == 'Japanese Vocabulary' and old_ainote and re.search(r'<(div|ul|li)\b', old_ainote):
            warnings.append('[%s] 旧 AINote 含 <div>/<ul>，建议整体改成 <p>' % nid)
        verdict = str(item.get('verdict') or '').strip()
        if verdict not in VERDICTS:
            errors.append('[%s] verdict 必须是 %s 之一，收到 %r'
                          % (nid, ' / '.join(VERDICTS), verdict))
            continue
        evidence = str(item.get('evidence') or '').strip()
        if not evidence:
            errors.append('[%s] 缺 evidence：诊断必须引用证据（lapses / 字段内容 / 混淆对象）' % nid)
            continue

        fields = item.get('fields') or {}
        if not isinstance(fields, dict):
            errors.append('[%s] fields 必须是对象' % nid)
            continue
        if verdict == 'understanding' and fields:
            errors.append('[%s] verdict=understanding 时不许写字段；先理解，再回来改卡' % nid)
            continue

        changed = {}
        for key, raw in fields.items():
            if key not in allowed:
                errors.append('[%s] 字段 %r 不在 %s 的白名单 %s 里'
                              % (nid, key, model, ' / '.join(allowed)))
                continue
            if not isinstance(raw, str):
                errors.append('[%s] %s 的值不是字符串' % (nid, key))
                continue
            val = raw.strip()
            if not val:
                errors.append('[%s] %s 是空值；本技能不靠清空字段来“减负”' % (nid, key))
                continue

            hard = []
            if key == 'AINote':
                if val.startswith(check_cards.MARKER):
                    hard.append('不能用“待人工处理”占位符')
                fake = {
                    'noteId': nid,
                    'sentence': old.get('Sentence') or '',
                    'AINote': val,
                    'SentenceHTML': old.get('Sentence HTML') or '',
                }
                ai_hard, _html_hard, soft = check_cards.split_hard(fake)
                hard.extend(ai_hard)
                warnings.extend('[%s] AINote 提示：%s' % (nid, s) for s in soft)
                if len(check_cards.text_of(val)) > 400:
                    warnings.append('[%s] AINote 可见 %d 字 > 400，仍偏长'
                                    % (nid, len(check_cards.text_of(val))))
            else:
                hard.extend(check_cards.field_hard(key, val))
                if key == 'VocabPlus' and re.search(r'[<>]', val):
                    hard.append('VocabPlus 用 furigana: 过滤器渲染，不能写 HTML 标签')
                if '[sound:' in val or '{{' in val:
                    hard.append('不能写音频占位符或模板语法')
                if key in ('Meaning', 'VocabDefSC') and len(split_senses(val)) > 3:
                    warnings.append('[%s] %s 有 %d 个义项，检查是否该收敛'
                                    % (nid, key, len(split_senses(val))))
                if key == 'VocabPlus' and plain_len(val) > 80:
                    warnings.append('[%s] VocabPlus %d 字 > 80，记忆钩子宜短' % (nid, plain_len(val)))

            if hard:
                errors.append('[%s] %s：%s' % (nid, key, '；'.join(hard)))
            elif val != (old.get(key) or ''):
                changed[key] = val

        word = word_of(old)
        if 'AINote' in changed and word and word not in check_cards.text_of(changed['AINote']):
            warnings.append('[%s] AINote 里没出现重点词 %s' % (nid, word))
        if changed and 'leech' not in tags and not allow_untagged:
            errors.append('[%s] 没有 leech 标签（计划过期或已处理）；确认后加 --allow-untagged' % nid)
        if (not fields and not as_list(item.get('split'))
                and not as_list(item.get('suspend')) and not as_list(item.get('study'))):
            warnings.append('[%s] 没有 fields/split/suspend/study，等于空操作' % nid)

        prepared.append({
            'nid': nid,
            'model': model,
            'word': word,
            'verdict': verdict,
            'evidence': evidence,
            'changed': changed,
            'old': {k: (old.get(k) or '') for k in changed},
            'had_leech': 'leech' in tags,
            'study': as_list(item.get('study')),
            'split': as_list(item.get('split')),
            'suspend': as_list(item.get('suspend')),
        })

    # per-item 的 suspend 也用 noteId；解析成 cardId 只为打印（绝不 suspend）。
    suspend_all = []
    for p in prepared:
        suspend_ids = []
        for x in p['suspend']:
            try:
                suspend_ids.append(int(x))
            except (TypeError, ValueError):
                errors.append('[%s] suspend 含非整数：%r' % (p['nid'], x))
        p['suspend'] = suspend_ids
        suspend_all.extend(suspend_ids)
    suspend_all = sorted(set(suspend_all))
    if suspend_all:
        live = AK.notes_map(suspend_all)
        for p in prepared:
            for nid in p['suspend']:
                if nid not in live:
                    warnings.append('[%s] suspend 的 noteId %s 不存在' % (p['nid'], nid))
        scids = AK.cards_of_notes(suspend_all)
        scards = AK.cards_info(scids) if scids else []
        by_note = defaultdict(list)
        for c in scards:
            try:
                by_note[int(c.get('note'))].append(int(c.get('cardId')))
            except (TypeError, ValueError):
                continue
        for p in prepared:
            p['suspend_cards'] = {nid: by_note.get(nid, []) for nid in p['suspend']}
    else:
        for p in prepared:
            p['suspend_cards'] = {}

    if errors:
        return None, errors, warnings
    return prepared, errors, warnings


def print_plan(prepared, warnings):
    n_write = sum(1 for p in prepared if p['changed'])
    n_fields = sum(len(p['changed']) for p in prepared)
    by_verdict = Counter(p['verdict'] for p in prepared)
    print('=' * 78)
    print('计划：%d 张；改写 %d 张 / %d 个字段；只诊断 %d 张'
          % (len(prepared), n_write, n_fields, len(prepared) - n_write))
    print('病因：%s' % ' / '.join('%s %d' % (VERDICT_CN[k], by_verdict[k])
                                   for k in VERDICTS if by_verdict.get(k)))

    for p in prepared:
        head = '[%s] %s %s' % (p['nid'], p['model'], p['word'])
        print('\n' + head)
        print('  病因：%s（%s）' % (VERDICT_CN[p['verdict']], p['evidence']))
        for s in p['study']:
            print('  先理解：%s' % s)
        for s in p['split']:
            print('  拆分建议：%s' % s)
        for nid in p['suspend']:
            cids = p.get('suspend_cards', {}).get(nid, [])
            tail = (' → cardId ' + ', '.join(str(x) for x in cids)) if cids else '（没有卡）'
            print('  暂停建议：noteId %s%s（本脚本不执行；请在 Anki 浏览器里手动暂停）' % (nid, tail))
        all_cids = [c for nid in p['suspend'] for c in p.get('suspend_cards', {}).get(nid, [])]
        if all_cids:
            print('  暂停搜索串：%s' % ' or '.join('cid:%d' % c for c in all_cids))
        if not p['changed']:
            print('  写入：无（只诊断）')
            continue
        print('  写入：%s' % ', '.join(p['changed']))
        for key, val in p['changed'].items():
            old = p['old'].get(key) or ''
            if key == 'AINote':
                old_show = '(空)' if not old else '[%d字] %s' % (
                    len(check_cards.text_of(old)), short_value(check_cards.text_of(old)))
                new_show = '[%d字] %s' % (
                    len(check_cards.text_of(val)), short_value(check_cards.text_of(val)))
            else:
                old_show = '(空)' if not old else short_value(old)
                new_show = short_value(val)
            print('    %s' % key)
            print('      - %s' % old_show)
            print('      + %s' % new_show)

    if warnings:
        print('\n提示（不拦，但值得看一眼）：')
        for w in warnings:
            print('  · %s' % w)


def print_groups(groups):
    if not groups:
        return
    print('=' * 78)
    print('干扰组：%d 组（只给建议；脚本不暂停、不改 queue）' % len(groups))
    for g in groups:
        print('\n[%s]' % g['name'])
        print('  成员：%s' % ' / '.join(
            '%s(%s)' % (w['word'], w['reading'] or '-') for w in g['word_map'].values()))
        print('  证据：%s' % g['evidence'])
        keep = g['word_map'][g['keep']]
        print('  建议保留：%s（noteId %s）' % (keep['word'], g['keep']))
        if g['suspend']:
            print('  建议暂停：')
            for nid in g['suspend']:
                w = g['word_map'].get(nid, {})
                cids = g['suspend_cards'].get(nid, [])
                tail = (' → cardId ' + ', '.join(str(x) for x in cids)) if cids else '（没有卡）'
                print('    - %s（noteId %s%s）' % (w.get('word', '?'), nid, tail))
        all_cids = [c for nid in g['suspend'] for c in g['suspend_cards'].get(nid, [])]
        if all_cids:
            print('  暂停搜索串：%s' % ' or '.join('cid:%d' % c for c in all_cids))
        if g['order']:
            print('  学习顺序：%s' % ' → '.join(
                g['word_map'].get(nid, {}).get('word', str(nid)) for nid in g['order']))
        if g['contrast']:
            print('  对比表：')
            for line in g['contrast'].splitlines():
                print('    ' + line)
        print('  ⚠ 暂停不执行；请在 Anki 浏览器里按上面的 cardId 手动暂停。')


# --------------------------------------------------------------------------- 写库
def make_backup(prepared):
    items = []
    for p in prepared:
        if not p['changed']:
            continue
        items.append({
            'noteId': p['nid'],
            'model': p['model'],
            'had_leech': p['had_leech'],
            'fields': {k: (p['old'].get(k) or '') for k in p['changed']},
        })
    return {
        'version': 1,
        'created': iso_now(),
        'source': 'jp-anki-leech',
        'items': items,
    }


def write_backup(payload, prefix='backup'):
    path = os.path.join(WSP.DATA, 'leech', '%s_%s.json' % (prefix, stamp()))
    T.dump_json(payload, path)
    return path


def cmd_apply(args):
    try:
        payload = T.load_json(args.plan)
    except Exception as exc:                    # noqa: BLE001
        print('读不了计划 %s：%s' % (args.plan, exc), file=sys.stderr)
        return 1
    if isinstance(payload, list):
        payload = {'items': payload}
    if not isinstance(payload, dict):
        print('计划必须是 {version, groups, items} 或直接是 items 数组', file=sys.stderr)
        return 1
    if payload.get('version') not in (None, 1):
        print('不认识的计划版本：%r' % payload.get('version'), file=sys.stderr)
        return 1
    items = payload.get('items') or []
    groups = payload.get('groups') or []
    if not isinstance(items, list):
        print('items 必须是数组', file=sys.stderr)
        return 1
    if not isinstance(groups, list):
        print('groups 必须是数组', file=sys.stderr)
        return 1
    if not items and not groups:
        print('计划里没有 items 或 groups', file=sys.stderr)
        return 1

    prepared_groups, gerrors, gwarnings = prepare_groups(groups)
    warnings = list(gwarnings)
    if items:
        prepared, errors, iwarnings = prepare_apply(items, args.allow_untagged)
        warnings += iwarnings
    else:
        prepared, errors = [], []
    if gerrors or errors:
        all_errors = list(gerrors or []) + list(errors or [])
        print('计划未通过校验，未写任何卡：', file=sys.stderr)
        for e in all_errors:
            print('  ✗ %s' % e, file=sys.stderr)
        if warnings:
            print('\n提示：', file=sys.stderr)
            for w in warnings:
                print('  · %s' % w, file=sys.stderr)
        return 1

    if prepared_groups:
        print_groups(prepared_groups)
    if prepared:
        print_plan(prepared, warnings)
    elif warnings:
        print('\n提示（不拦，但值得看一眼）：')
        for w in warnings:
            print('  · %s' % w)

    if not args.commit:
        print('\n[演练] 未写库。确认上面的改动后，重跑并加 --commit。')
        if any(p['changed'] for p in prepared):
            if not args.keep_leech:
                print('提交成功后会摘掉 leech 标签；想保留加 --keep-leech。')
        else:
            print('（没有字段要写；组建议/暂停仍需你手动执行）')
        return 0

    backup = make_backup(prepared)
    if not backup['items']:
        print('\n没有需要写的字段（组建议已打印；暂停请手动）。')
        return 0

    path = write_backup(backup)
    print('\n备份：%s（%d 张 / %d 个字段）'
          % (show_path(path), len(backup['items']),
             sum(len(x['fields']) for x in backup['items'])))

    ok, failed = [], []
    for p in prepared:
        if not p['changed']:
            continue
        try:
            AK.update_note_fields(p['nid'], p['changed'])
            ok.append(p['nid'])
        except AK.AnkiError as exc:             # noqa: BLE001
            failed.append((p['nid'], str(exc)))

    expected = {p['nid']: p['changed'] for p in prepared if p['nid'] in ok}
    bad = AK.verify_note_fields(expected) if expected else {}
    verified = [nid for nid in expected if nid not in bad]

    cleared, tag_failed = [], []
    if not args.keep_leech:
        for p in prepared:
            if p['nid'] not in verified or not p['had_leech']:
                continue
            try:
                AK.remove_tags([p['nid']], ['leech'])
                cleared.append(p['nid'])
            except AK.AnkiError as exc:         # noqa: BLE001
                tag_failed.append((p['nid'], str(exc)))

    still = []
    if cleared:
        live = AK.notes_map(cleared)
        still = [nid for nid, n in live.items() if 'leech' in (n.get('tags') or [])]

    total = len(backup['items'])
    tag_targets = sum(1 for p in prepared if p['changed'] and p['had_leech'])
    if args.keep_leech:
        tag_line = '保留 leech（--keep-leech）'
    else:
        tag_line = '摘 leech %d/%d' % (len(cleared) - len(still), tag_targets)
    print('已写入 %d/%d；回读一致 %d/%d；%s'
          % (len(ok), total, len(verified), len(ok), tag_line))
    if failed:
        print('写入失败：', file=sys.stderr)
        for nid, why in failed:
            print('  ✗ %s：%s' % (nid, why), file=sys.stderr)
    if bad:
        print('回读不一致：', file=sys.stderr)
        for nid, fields in bad.items():
            print('  ✗ %s：%s' % (nid, ', '.join(fields)), file=sys.stderr)
    if tag_failed:
        print('摘标签失败：', file=sys.stderr)
        for nid, why in tag_failed:
            print('  ✗ %s：%s' % (nid, why), file=sys.stderr)
    if still:
        print('回读时 leech 仍在：%s' % ', '.join(str(i) for i in still), file=sys.stderr)

    print('回退：python -X utf8 %s restore --backup "%s" --commit'
          % (show_path(os.path.abspath(__file__)), path))
    return 0 if not (failed or bad or tag_failed or still) else 1


# --------------------------------------------------------------------------- 回滚
def cmd_restore(args):
    try:
        payload = T.load_json(args.backup)
    except Exception as exc:                    # noqa: BLE001
        print('读不了备份 %s：%s' % (args.backup, exc), file=sys.stderr)
        return 1
    items = payload.get('items') if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        print('备份里没有 items', file=sys.stderr)
        return 1

    nids = []
    for it in items:
        if not isinstance(it, dict):
            print('备份里有非对象条目：%r' % (it,), file=sys.stderr)
            return 1
        try:
            nids.append(int(it.get('noteId')))
        except (TypeError, ValueError):
            print('备份里有非法 noteId：%r' % (it or {}).get('noteId'), file=sys.stderr)
            return 1
    notes = AK.notes_map(nids)

    prepared, errors = [], []
    for it in items:
        nid = int(it.get('noteId'))
        n = notes.get(nid)
        if not n:
            errors.append('[%s] 笔记不存在' % nid)
            continue
        model = it.get('model') or n.get('modelName') or ''
        allowed = ALLOWED_FIELDS.get(model)
        if not allowed:
            errors.append('[%s] 备份里的笔记类型 %r 不认识' % (nid, model))
            continue
        fields = it.get('fields') or {}
        if not isinstance(fields, dict) or not fields:
            errors.append('[%s] 备份里没有字段' % nid)
            continue
        unknown = set(fields) - set(allowed)
        if unknown:
            errors.append('[%s] 备份里有白名单外字段：%s' % (nid, ', '.join(sorted(unknown))))
            continue
        current = {k: (AK.field(n, k) or '') for k in fields}
        prepared.append({
            'nid': nid,
            'model': model,
            'fields': {k: (str(v) if v is not None else '') for k, v in fields.items()},
            'current': current,
            'had_leech': bool(it.get('had_leech')),
            'tags': set(n.get('tags') or []),
        })

    if errors:
        print('备份未通过校验，未写任何卡：', file=sys.stderr)
        for e in errors:
            print('  ✗ %s' % e, file=sys.stderr)
        return 1

    print('=' * 78)
    print('回滚：%d 张 / %d 个字段' % (len(prepared), sum(len(p['fields']) for p in prepared)))
    for p in prepared:
        print('\n[%s] %s' % (p['nid'], p['model']))
        for key, old in p['fields'].items():
            cur = p['current'].get(key) or ''
            if key == 'AINote':
                print('  %s: [当前 %d 字] → [备份 %d 字]' % (key, plain_len(cur), plain_len(old)))
            else:
                print('  %s: %s → %s' % (key, short_value(cur, 60), short_value(old, 60)))

    if not args.commit:
        print('\n[演练] 未写库。确认后重跑并加 --commit。')
        return 0

    pre = {
        'version': 1,
        'created': iso_now(),
        'source': 'jp-anki-leech pre-restore',
        'items': [{
            'noteId': p['nid'],
            'model': p['model'],
            'had_leech': 'leech' in p['tags'],
            'fields': p['current'],
        } for p in prepared],
    }
    pre_path = write_backup(pre, prefix='pre_restore')
    print('\n回滚前备份：%s' % show_path(pre_path))

    ok, failed = [], []
    for p in prepared:
        try:
            AK.update_note_fields(p['nid'], p['fields'])
            ok.append(p['nid'])
        except AK.AnkiError as exc:             # noqa: BLE001
            failed.append((p['nid'], str(exc)))

    expected = {p['nid']: p['fields'] for p in prepared if p['nid'] in ok}
    bad = AK.verify_note_fields(expected) if expected else {}
    verified = [nid for nid in expected if nid not in bad]

    readded = []
    for p in prepared:
        if p['nid'] not in verified or not p['had_leech'] or 'leech' in p['tags']:
            continue
        try:
            AK.add_tags([p['nid']], ['leech'])
            readded.append(p['nid'])
        except AK.AnkiError as exc:             # noqa: BLE001
            failed.append((p['nid'], '补回 leech 失败：%s' % exc))

    print('已回滚 %d/%d；回读一致 %d/%d；补回 leech %d'
          % (len(ok), len(prepared), len(verified), len(ok), len(readded)))
    if failed:
        for nid, why in failed:
            print('  ✗ %s：%s' % (nid, why), file=sys.stderr)
    if bad:
        for nid, fields in bad.items():
            print('  ✗ %s 回读不一致：%s' % (nid, ', '.join(fields)), file=sys.stderr)
    return 0 if not (failed or bad) else 1


# --------------------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(
        description='leech 难卡：扫描 / 按计划改写卡背 / 回滚。默认只演练，--commit 才写。')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('scan', help='只读扫描（默认 tag:leech），产出证据 JSON')
    s.add_argument('--query', default='tag:leech', help='Anki 查询串；默认 tag:leech')
    s.add_argument('--note-id', default='', help='只扫这些 noteId（逗号/空格分隔；覆盖 --query）')
    s.add_argument('--limit', type=int, default=100, help='最多几张；0=全部（默认 100）')
    s.add_argument('--out', default=os.path.join(WSP.TEMP, 'leech_scan.json'),
                   help='JSON 落盘路径（默认 temp/leech_scan.json）')
    s.add_argument('--no-out', action='store_true', help='不落盘，只打印表格')
    s.add_argument('--json', action='store_true', help='只输出完整 JSON（便于管道）')
    s.set_defaults(func=cmd_scan)

    a = sub.add_parser('apply', help='校验并写计划；默认只演练')
    a.add_argument('--plan', required=True, help='plan JSON 路径')
    a.add_argument('--commit', action='store_true', help='真写；不加则只演练')
    a.add_argument('--keep-leech', action='store_true', help='写成功后保留 leech 标签')
    a.add_argument('--allow-untagged', action='store_true',
                   help='允许写没有 leech 标签的笔记（计划过期时用，慎用）')
    a.set_defaults(func=cmd_apply)

    r = sub.add_parser('restore', help='按备份回滚字段')
    r.add_argument('--backup', required=True, help='apply 产出的 backup_*.json')
    r.add_argument('--commit', action='store_true', help='真写；不加则只演练')
    r.set_defaults(func=cmd_restore)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    with AK.guard():
        return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
