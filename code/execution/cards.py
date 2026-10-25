# -*- coding: utf-8 -*-
"""按张生成 / 写入 `AINote` + `Sentence HTML`（原子能力，和批处理流程无关）。

只做一件事
----------
给**一张或几张**例句卡生成讲解（`AINote`）与带振假名的例句（`Sentence HTML`），
默认**只打印、不写库**；`--commit` 才写这两个字段。

固定的是**方法**，不是流程
--------------------------
1. 输入契约：`Sentence` / `Word` / `Source` 三个字段。`Sentence` 是唯一骨架，
   `Word` 非空时核心词汇第一条必须是它，`Source` 只用来判断语域。
2. 生成：本地模型（OpenAI Responses API），提示词正本 =
   `pipeline.py` 的 `LOCAL_INSTRUCTION`（改提示词只改那一处）。
3. **`Sentence HTML` 不信模型**：`ruby_engine` 拿原始 `Sentence` 当骨架重渲染。
   逐字一致是构造出来的，缺的读音按「人工例外表 → 字幕注音 → 本 deck → Sudachi」补。
   模型给的读法只在没有更权威来源时保留（`repair(mode='fix')`）。
4. 校验只做一次：`check_cards.check()`。`AINote` 不合格才逐张重问（本地模型）；
   `Sentence HTML` 的机械问题**不重问**——`repair` 能确定性修好，重问只会丢掉合格讲解。
5. 写库：只写 `AINote` / `Sentence HTML`，写完回读；目标字段已有内容默认拒绝覆盖。

两条入口
--------
    # ① 本地模型生成（默认演练）
    python code/execution/cards.py gen --note-id 1791727898061
    python code/execution/cards.py gen --query "tag:动画::…::第01集 AINote:" --per-request 3
    python code/execution/cards.py gen --sentence "郵便局に戻った時に調べてみるよ"
    python code/execution/cards.py gen --note-id 123 --commit
    python code/execution/cards.py gen --note-id 123 --overwrite --commit

    # ② 现成 JSON（我 / 强模型 / 人工写的）→ 同一套 repair + 闸门 + 写库
    python code/execution/cards.py write --file fix.json
    python code/execution/cards.py write --file fix.json --commit

JSON 形状（`gen --out` 与 `write --file` 同一份）::

    [{"noteId": 123, "AINote": "<p>…</p>", "SentenceHTML": "<ruby>…</ruby>"}]

`sentence` 可以带上，但写库时**一律以 Anki 里的 `Sentence` 为准**（骨架不能用别人转述的版本）。

不做什么
--------
不切批、不建 manifest、不排队、不跑整集流水线。需要批量跑一集时由调用方决定怎么切、
按什么顺序跑；本脚本每次只处理你点名的那几张卡。清理 / 激活 / 挖生词 / 配音都不在这里。

退出码：0 = 选中的卡都处理完（含有意跳过）；1 = 有卡没做出来 / 被闸门拒绝 / 回读不一致。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_CODE, 'common'))
sys.path.insert(0, _HERE)

import textio                 # noqa: E402  UTF-8 stdio 唯一入口（import 即生效）
import anki_api as AK         # noqa: E402  唯一的 Anki 访问点
import check_cards as CC      # noqa: E402  结构规则的唯一实现（闸门）
import llm_out as OUT         # noqa: E402  模型产出的吸收层
import local_llm as LLM       # noqa: E402  本地模型客户端
import ruby_engine as RE      # noqa: E402  确定性振假名引擎
import pipeline as PL         # noqa: E402  提示词与生成循环的正本（这里只复用，不复制）

DECK = '0-日本语学习::2-例句'
F_SENT, F_WORD, F_SRC = 'Sentence', 'Word', 'Source'
F_NOTE, F_HTML = 'AINote', 'Sentence HTML'
# 草稿（--sentence / --file 里没有 noteId 的条目）用负数占位：模型回传 noteId 时不会互相撞，
# 写库时一律拒绝（<= 0 不是 Anki 的 noteId）。
DRAFT_ID = -1


# ============================================================================
# 小工具
# ============================================================================
def read_json(path):
    if not path:
        raise SystemExit('没有给 --file')
    if not os.path.exists(path):
        raise SystemExit('找不到文件：%s' % path)
    with open(path, encoding='utf-8-sig') as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as e:
            raise SystemExit('%s 不是合法 JSON：%s' % (path, e))


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def rows_of(doc):
    """兼容 `[...]` 与 `{"cards":[...]}` 两种形状。"""
    if isinstance(doc, dict):
        doc = doc.get('cards') or doc.get('outputs') or []
    if not isinstance(doc, list):
        raise SystemExit('--file 里应该是 JSON 数组（或 {"cards":[...] }）')
    rows = [r for r in doc if isinstance(r, dict)]
    if not rows:
        raise SystemExit('--file 里没有卡片条目')
    return rows


def text_field(row, *names):
    for k in names:
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ''


def parse_ids(values):
    out = []
    for raw in values or []:
        for part in str(raw).replace('，', ',').split(','):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                raise SystemExit('noteId 应该是数字：%r' % part)
            val = int(part)
            if val not in out:
                out.append(val)
    if not out:
        raise SystemExit('--note-id 里没有合法的 noteId')
    return out


def note_card(note):
    f = AK.field_values(note)
    return {
        'noteId': int(note['noteId']),
        'sentence': f.get(F_SENT, '') or '',
        'word': f.get(F_WORD, '') or '',
        'source': f.get(F_SRC, '') or '',
        'old_ainote': f.get(F_NOTE, '') or '',
        'old_html': f.get(F_HTML, '') or '',
    }


def filled_fields(card):
    """已经非空的目标字段（默认跳过 / 拒绝覆盖；--overwrite 才重做）。"""
    out = []
    if (card.get('old_ainote') or '').strip():
        out.append(F_NOTE)
    if (card.get('old_html') or '').strip():
        out.append(F_HTML)
    return out


def filled(card):
    return bool(filled_fields(card))


# ============================================================================
# 选卡
# ============================================================================
def select_cards(a):
    """→ ([card], 范围说明)。只读，不写库。"""
    if a.sentence is not None:
        if not a.sentence.strip():
            raise SystemExit('--sentence 是空的')
        if a.note_ids or a.query or a.file:
            raise SystemExit('--sentence 不能和 --note-id / --query / --file 一起用')
        return ([{'noteId': DRAFT_ID, 'sentence': a.sentence, 'word': a.word or '',
                  'source': a.source or '', 'old_ainote': '', 'old_html': ''}],
                '单句草稿（不读 Anki）')

    if a.note_ids:
        ids = parse_ids(a.note_ids)
        notes = AK.notes_map(ids)
        missing = [i for i in ids if i not in notes]
        if missing:
            raise SystemExit('这些 noteId 在 Anki 里不存在：%s'
                             % '、'.join(map(str, missing)))
        return [note_card(notes[i]) for i in ids], 'noteId × %d' % len(ids)

    if a.query:
        ids = AK.find_notes(a.query, limit=a.limit)
        if not ids:
            raise SystemExit('查询无结果：%s' % a.query)
        notes = AK.notes_map(ids)
        return [note_card(notes[i]) for i in ids if i in notes], '查询 %s' % a.query

    rows = rows_of(read_json(a.file))
    ids = [i for i in (OUT.as_int(r.get('noteId')) for r in rows) if i and i > 0]
    notes = AK.notes_map(ids) if ids else {}
    cards = []
    draft = DRAFT_ID
    for row in rows:
        nid = OUT.as_int(row.get('noteId')) or 0
        if nid <= 0:                     # 草稿：给一个不重复的负数占位
            nid, draft = draft, draft - 1
        note = notes.get(nid)
        if note is not None:
            card = note_card(note)                 # 库里的 Sentence 才是骨架
            card['word'] = card['word'] or text_field(row, 'word', 'Word')
            card['source'] = card['source'] or text_field(row, 'source', 'Source')
        else:
            card = {'noteId': nid,
                    'sentence': text_field(row, 'sentence', 'Sentence'),
                    'word': text_field(row, 'word', 'Word'),
                    'source': text_field(row, 'source', 'Source'),
                    'old_ainote': '', 'old_html': ''}
        if nid > 0 and nid not in notes:
            raise SystemExit('noteId %s 在 Anki 里不存在（拼错了？）' % nid)
        if not card['sentence'].strip():
            raise SystemExit('noteId %s 没有 Sentence（Anki 里也没有这句）'
                             % (nid if nid > 0 else '草稿'))
        cards.append(card)
    if not cards:
        raise SystemExit('--file 里没有卡片条目')
    return cards, '文件 %s（%d 张）' % (a.file, len(cards))


def build_lexicon(cards, a):
    """读音词典：例外表 / 字幕注音 / 本 deck / Sudachi（见 ruby_engine）。"""
    ids = [c['noteId'] for c in cards if int(c.get('noteId') or 0) > 0]
    return RE.Lexicon.build(query=a.lexicon, exclude_ids=ids,
                            srt=a.srt, plan=a.plan,
                            use_deck=not a.no_deck_lexicon)


# ============================================================================
# 生成结果 → 最终记录
# ============================================================================
def finalize(card, ainote, html, lex):
    """`(记录, 状态, 问题, repair 信息)`；状态 ∈ ok / skipped / bad。

    关键：`Sentence HTML` 一律过 `ruby_engine.repair(mode='fix')`。
    `mode='fix'` 让**权威读音**（例外表/字幕注音/本 deck）优先于模型给的读法；
    两个字段都空 = 模型判定"讲不了"，按规范有意跳过，不写库。
    """
    ainote = OUT.as_text(ainote)
    html = OUT.as_text(html)
    if not ainote and not html.strip():
        return ({'noteId': card['noteId'], 'sentence': card['sentence'],
                 'AINote': '', 'SentenceHTML': ''}, 'skipped', [], {})
    new_html, info = RE.repair(card['sentence'], html, lex, mode='fix')
    rec = {'noteId': card['noteId'], 'sentence': card['sentence'],
           'AINote': ainote, 'SentenceHTML': new_html}
    hard, _soft = CC.check(rec)
    return rec, ('bad' if hard else 'ok'), hard, info


# ============================================================================
# 写库
# ============================================================================
def commit(records, a):
    """只写 AINote / Sentence HTML；返回回读不一致的 `{noteId: [字段]}`。"""
    if not records:
        print('没有可写入的卡。')
        return {}
    no_id = [r['noteId'] for r in records if int(r.get('noteId') or 0) <= 0]
    if no_id:
        raise SystemExit('这些卡是草稿（没有真实 noteId），不能写库：%s'
                         % '、'.join(map(str, no_id[:10])))

    ids = [int(r['noteId']) for r in records]
    live = AK.note_values(ids, names=[F_NOTE, F_HTML])
    missing = [i for i in ids if i not in live]
    if missing:
        raise SystemExit('这些 noteId 在 Anki 里不存在：%s'
                         % '、'.join(map(str, missing)))
    clash = [i for i in ids
             if not a.overwrite and ((live[i].get(F_NOTE) or '').strip()
                                     or (live[i].get(F_HTML) or '').strip())]
    if clash:
        detail = '、'.join('%s(%s)' % (i, '/'.join(
            [k for k in (F_NOTE, F_HTML) if (live[i].get(k) or '').strip()]))
            for i in clash[:10])
        raise SystemExit('这些卡的目标字段已有内容，拒绝覆盖（加 --overwrite）：%s' % detail)

    for n, rec in enumerate(records, 1):
        AK.update_note_fields(rec['noteId'], {'AINote': rec['AINote'],
                                              'Sentence HTML': rec['SentenceHTML']})
        if n % 25 == 0:
            print('  已写入 %d/%d' % (n, len(records)))
    want = {int(r['noteId']): {'AINote': r['AINote'],
                               'Sentence HTML': r['SentenceHTML']} for r in records}
    bad = AK.verify_note_fields(want, settle=0.5)
    print('写入 %d 张；回读不一致 %d 张' % (len(records), len(bad)))
    for nid, fields in sorted(bad.items()):
        print('  ✗ noteId %s  %s' % (nid, '、'.join(fields)))
    return bad


# ============================================================================
# 汇报
# ============================================================================
def show(rec, status, problems, info, quiet=False):
    nid = rec['noteId']
    print()
    print('=' * 72)
    print('noteId %s' % nid)
    print('=' * 72)
    if status == 'skipped':
        if not quiet:
            print('【Sentence】')
            print(rec['sentence'])
        print('（模型判定无法给出可靠讲解：两个字段都留空，按规范跳过）')
        return
    if not quiet:
        print('【Sentence】')
        print(rec['sentence'])
        print('【AINote】')
        print(rec['AINote'])
        print('【Sentence HTML】')
        print(rec['SentenceHTML'])
    if status == 'bad':
        print('【未通过】')
        for p in problems:
            print('  ✗ %s' % p)
    for row in (info or {}).get('unknown', []):
        print('  ⚠ 读音无来源：%s→%s（没标 ruby，其余照常）' % (row[0], row[1]))
    for row in (info or {}).get('review', []):
        print('  ⚠ 只有 Sudachi 有不同意见（待复核）：%s 卡里 %s / sudachi %s'
              % (row[0], row[1], row[2]))
    for row in (info or {}).get('conflict', []):
        print('  · 读音按权威来源改正：%s %s → %s（%s）'
              % (row[0], row[1], row[2], row[3]))


def finish(a, cards, made, records, label, t0):
    """统一出口：打印 + 落盘 + 可选写库 + 退出码。

    `made`    = {noteId: (状态, 问题, repair 信息)}，状态 ∈ ok / skipped / bad
    `records` = {noteId: 最终记录}（bad 的可能没有；skipped 的是一对空串）
    """
    ok, skipped, bad = [], [], []
    for card in cards:
        nid = card['noteId']
        status, problems, info = made[nid]
        rec = records.get(nid)
        if status == 'ok':
            ok.append(rec)
        elif status == 'skipped':
            skipped.append(card)
        else:
            bad.append((rec, problems, info))
        show(rec or {'noteId': nid, 'sentence': card['sentence'],
                     'AINote': '', 'SentenceHTML': ''},
             status, problems if status == 'bad' else [], info, a.quiet)

    if a.out:
        rows = [records.get(c['noteId'])
                or {'noteId': c['noteId'], 'sentence': c['sentence'],
                    'AINote': '', 'SentenceHTML': ''} for c in cards]
        write_json(a.out, rows)
        print('\n产出已写入：%s（%d 张）' % (a.out, len(rows)))

    print()
    print('-' * 72)
    print('%s ｜ 选中 %d 张：合格 %d ｜ 有意跳过 %d ｜ 未完成 %d ｜ 用时 %.0fs'
          % (label, len(cards), len(ok), len(skipped), len(bad), time.time() - t0))
    for rec, problems, _info in bad:
        nid = rec['noteId'] if rec else '?'
        print('  ✗ noteId %s：%s' % (nid, '；'.join(problems)[:200]))

    mism = {}
    if a.commit:
        if bad:
            print('有 %d 张未通过：只写合格的卡（未通过的不写，修好后重跑）。' % len(bad))
        mism = commit(ok, a)
    elif ok:
        print('演练：未写库。加 --commit 写这两个字段（已有内容会被拒绝，需 --overwrite）。')
    return 1 if (bad or mism) else 0


# ============================================================================
# gen：本地模型生成
# ============================================================================
def cmd_gen(a):
    t0 = time.time()
    if a.per_request < 1:
        raise SystemExit('--per-request 至少 1')
    cards, label = select_cards(a)
    print('范围：%s ｜ %d 张' % (label, len(cards)))

    skip = [c for c in cards if filled(c) and not a.overwrite]
    skip_ids = {id(c) for c in skip}
    todo = [c for c in cards if id(c) not in skip_ids]
    if skip:
        print('已有内容跳过 %d 张（%s；--overwrite 可重做）'
              % (len(skip), '、'.join(
                  '%s[%s]' % (c['noteId'], '+'.join(filled_fields(c))) for c in skip[:8])))
    if not todo:
        print('没有要生成的卡。')
        return 0
    if a.commit and any(c['noteId'] <= 0 for c in todo):
        raise SystemExit('--sentence / 草稿没有真实 noteId，不能 --commit（先落到 Anki 卡上）')

    cfg = LLM.load_config()
    print('本地模型：%s @ %s（每请求 %d 张，重问 %d 轮）'
          % (cfg['model'], cfg['base_url'], a.per_request, a.retries))
    ns = argparse.Namespace(per_request=a.per_request, retries=a.retries)
    done, failed, stat = PL.gen_loop(ns, cfg, LLM, todo, 0, tag='')
    print('本地模型结束：%d 次请求，prompt %d + completion %d tokens，耗时 %.0fs'
          % (stat[0], stat[1], stat[2], time.time() - t0))

    lex = build_lexicon(todo, a)
    records, made = {}, {}
    for card in todo:
        got = done.get(card['noteId'])
        if got is None:
            made[card['noteId']] = ('bad', [failed.get(card['noteId'], '模型没有返回这张卡')], {})
            continue
        rec, status, problems, info = finalize(card, got['AINote'], got['SentenceHTML'], lex)
        records[card['noteId']] = rec
        made[card['noteId']] = (status, problems, info)
    # 已有内容被跳过的卡不参与 / 也不会进 --out，避免拿旧值误覆盖
    return finish(a, todo, made, records, label, t0)


# ============================================================================
# write：现成 JSON → 同一套 repair + 闸门 + 写库
# ============================================================================
def cmd_write(a):
    t0 = time.time()
    rows = rows_of(read_json(a.file))
    by_id = {}
    for row in rows:
        nid = OUT.as_int(row.get('noteId'))
        if not nid or nid <= 0:
            raise SystemExit('每一条都要有真实的 Anki noteId（草稿不能写库）：%r' % row)
        by_id[nid] = row
    ids = list(by_id)
    notes = AK.notes_map(ids)
    missing = [i for i in ids if i not in notes]
    if missing:
        raise SystemExit('这些 noteId 在 Anki 里不存在：%s'
                         % '、'.join(map(str, missing)))
    cards = [note_card(notes[i]) for i in ids]
    todo = [c for c in cards if not filled(c) or a.overwrite]
    if len(todo) < len(cards):
        print('已有内容跳过 %d 张（--overwrite 可覆盖）' % (len(cards) - len(todo)))
    if not todo:
        print('没有要写的卡。')
        return 0

    lex = build_lexicon(todo, a)
    records, made = {}, {}
    for card in todo:
        row = by_id[card['noteId']]
        rec, status, problems, info = finalize(
            card, text_field(row, 'AINote', 'AI_Note'),
            text_field(row, 'SentenceHTML', 'Sentence HTML'), lex)
        records[card['noteId']] = rec
        made[card['noteId']] = (status, problems, info)
    return finish(a, todo, made, records, '文件 %s（%d 张）' % (a.file, len(todo)), t0)


# ============================================================================
# CLI
# ============================================================================
def add_common(p, commit_help):
    p.add_argument('--commit', action='store_true', help=commit_help)
    p.add_argument('--overwrite', action='store_true', help='目标字段已有内容也覆盖')
    p.add_argument('--out', help='把结果写成 JSON（形状同 write --file）')
    p.add_argument('--quiet', action='store_true', help='不逐张打印两个字段的全文')
    p.add_argument('--srt', help='筛选后的 SRT（字幕自带注音，权威读音来源）')
    p.add_argument('--plan', help='filter_subtitle.py 的 plan.json（自动取它的 output）')
    p.add_argument('--lexicon', default=DECK, help='本 deck 读音词典的查询（默认例句 deck）')
    p.add_argument('--no-deck-lexicon', action='store_true',
                   help='不读本 deck 的已有读音（离线 / 提速）')


def build_parser():
    ap = argparse.ArgumentParser(
        prog='cards.py',
        description='按张生成/写入 AINote + Sentence HTML（原子能力，不依赖批次或流水线）',
        epilog='提示词与生成循环复用 pipeline.py，未改动其批量入口；本脚本每次只处理点名的卡。')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('gen', help='本地模型生成 AINote + Sentence HTML（默认只打印）')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--note-id', '--note-ids', dest='note_ids', action='append',
                   metavar='ID[,ID…]', help='Anki noteId，可重复/逗号分隔')
    g.add_argument('--query', help='任意 Anki 查询，如 "tag:动画::…::第01集 AINote:"')
    g.add_argument('--file', help='JSON 数组：noteId 和/或 sentence/word/source')
    g.add_argument('--sentence', help='直接给一句（不读 Anki；不能 --commit）')
    p.add_argument('--word', help='--sentence 时指定重点词')
    p.add_argument('--source', help='--sentence 时指定出处（只影响语域判断）')
    p.add_argument('--limit', type=int, help='--query 命中太多时只取前 N 张')
    p.add_argument('--per-request', type=int, default=3, help='首轮每次请求几张（默认 3）')
    p.add_argument('--retries', type=int, default=1, help='AINote 不合格时重问轮数（默认 1）')
    add_common(p, '真写这两个字段（默认演练）')

    p = sub.add_parser('write', help='把现成 JSON 过 repair + 闸门后写库（默认只打印）')
    p.add_argument('--file', required=True,
                   help='JSON 数组：[{noteId, AINote, SentenceHTML}, …]')
    add_common(p, '真写这两个字段（默认演练）')
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    with AK.guard():                 # Anki 没开时给中文提示，不出 traceback
        return {'gen': cmd_gen, 'write': cmd_write}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
