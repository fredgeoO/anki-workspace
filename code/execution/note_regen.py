# -*- coding: utf-8 -*-
"""按卡上现有的 ① / ② 两句重写 AINote（与「增加例句」同一套 ①② 讲解）。

为什么要它
----------
「卡片修正」里的 AINote 以前走 `cards.py gen --only ainote`：它把整张卡的
`Sentence`（可能已经含 ①、② 两句）当成**一整段**讲，生成的是
`<p><b>中文翻译：</b>…</p>` 的五段式，没有 ①②。而「增加例句」走的是
`core6000_example_prompt.md` + `core6000_render.render_ainote`：同一份提示词、
同一套渲染器，每个板块写成「① 第一句 + ② 第二句」。两套逻辑讲的是同一件事，
长出来的版式却不一样——用户 2026-11-14 要求统一到 ①② 这一套。

本脚本只补上「按卡上现有两句重写」这个入口，**不新增提示词、不新增渲染器**：

* 提示词：`CE.load_system_prompt()`（即 `core6000_example_prompt.md` + `card_rules.md`）
* 请求/解析：`CE.build_payload` / `CE.build_messages` / `CE.parse_response`
* 闸门：`CE.gate_gen(..., require_ruby=False)`（AINote 不写 HTML，ruby 闸门不适用）
  + `CE.gate_apply(..., [F_NOTE])`（板块 / ① ② / 空值）
* 渲染：`CE.render_ainote`

句子从哪来
----------
**卡上现有的两句话**（① = 第一句，② = 第二句），不抓 Jisho、不造新句。
所以它只处理已经有 2 句的卡：

* `<br><br>` 分块（与 `core6000_example` 同口径）；或
* 单个 `<br>` 两侧都以句末标点结尾（字幕/旧数据把两句写成一行时也能认）。

只有一句的卡 → 明确报错「先用增加例句补第二句」，不在这里偷偷补句。

写什么
------
**只写 `AINote` 一个字段**。Sentence / Sentence HTML / Sentence Translation /
Sentence Audio / Word 等一个字不动。写前由 `writeback.write_fields` 备份旧值，
写后回读校验；默认演练（`--commit` 才真写），已有内容默认拒绝覆盖（`--overwrite`）。

用法
----
    python code/execution/note_regen.py gen --note-id 1621392118854
    python code/execution/note_regen.py gen --note-id 1621392118854 --overwrite --commit
    python code/execution/note_regen.py gen --note-id 123 --out temp/note.json

退出码：0 = 选中的卡都生成了合格 AINote（演练也算）；1 = 有卡失败 / 被拒 / 回读不一致。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
for _p in (os.path.join(_CODE, 'common'), _HERE, os.path.join(_HERE, 'core6000')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import textio                 # noqa: E402  UTF-8 stdio 唯一入口
import anki_api as AK         # noqa: E402  唯一的 Anki 访问点
import writeback as WB        # noqa: E402  写库事务（演练/备份/回读）
import core6000_example as CE  # noqa: E402  提示词 / 请求 / 闸门 / 渲染的正本

F_NOTE = CE.F_NOTE
END_PUNCT = '。！？!?…'
CLOSERS = '」』）)】』"\''
MAX_SENTENCES = 2


# ============================================================================
# 纯函数：选句 / 造一张「供 core6000 渲染」的合成卡
# ============================================================================
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


def ends_sentence(text):
    """去掉句末引号/括号后，最后一个是句末标点。"""
    t = (text or '').rstrip().rstrip(CLOSERS).rstrip()
    return bool(t) and t[-1] in END_PUNCT


def split_sentences(sentence):
    """把 `Sentence` 切成句子块（最多 2 块；不猜第 3 句）。

    * `<br><br>`（字幕里两句的标准分隔）——与 `core6000_example` 同口径；
    * 单个 `<br>` 且两侧都以句末标点结尾——兼容把两句挤在一行的旧卡。
    """
    s = (sentence or '').strip()
    blocks = [b.strip() for b in CE.RE_BR2.split(s) if CE.flatten(b)]
    if len(blocks) >= 2:
        return blocks
    parts = [p.strip() for p in CE.RE_BR1.split(s, 1)]
    if len(parts) == 2 and all(parts) and all(ends_sentence(p) for p in parts):
        return parts
    return blocks


def build_regen_card(note):
    """Anki note → core6000 渲染器认的卡结构（① / ② 两句 + 空 sections）。

    `sections=[]` 是关键：渲染器因此不会拿旧 AINote 的正文当 ①，而是用模型
    这次产出的 `core1` / `grammar1` / `conjugation1` / `context1` **重写** ①。
    `unmerged=True` 同时让 `gate_apply` 跳过闸门 8（不要求旧板块原文出现在新 AINote 里）。
    """
    card = CE.analyze_note(note)
    if not card['word']:
        raise ValueError('这张卡没有 Word 字段（不是词汇卡）；① ② 讲解需要词汇卡的两条例句')
    sent_field = card['snapshot'].get(CE.F_SENT, '')
    parts = split_sentences(sent_field)
    if len(parts) < 2:
        raise ValueError('这张卡只有一句（%s）；① ② 版式需要两句，'
                         '请先用「增加例句」补第二句再重写 AINote' % CE.one_line(sent_field, 40))
    if len(parts) > MAX_SENTENCES:
        raise ValueError('这张卡有 %d 句；本入口只处理两句卡' % len(parts))

    jp = [CE.plain(p) for p in parts]
    trans = CE.split_blocks(card['snapshot'].get(CE.F_TRANS, ''))
    cn = (trans + ['', ''])[:2] if len(trans) == 2 else ['', '']
    # 不把卡上的 Sentence HTML 注音带进 payload：这一入口**不写 HTML**，而卡上的旧注音
    # 可能本身就是错的（实测「放った」被标成 はな）；让模型按 Word + reading 判断读音。
    ruby = ['', '']

    card.update({
        'n_sent': 2,
        'unmerged': True,              # ① 也由模型产出（契约 §5.3）
        'need_new': False,
        'need_ruby1': False,
        'need_ruby2': False,
        'sentences': [
            {'jp': jp[0], 'cn': cn[0], 'ruby': ruby[0]},
            {'jp': jp[1], 'cn': cn[1], 'ruby': ruby[1]},
        ],
        'sent_blocks': jp,
        'trans_blocks': trans,
        'sections': [],                # 不沿用旧 AINote（否则 ① 仍是旧正文）
        'section_missing': list(CE.REQUIRED_CANON),
        'section_unknown': [],
        'layout': 'p-b',
        'outer_open': '<div>',
        'scopes': [CE.SCOPE_MERGE],
    })
    return card


# ============================================================================
# 单卡：请求 → 闸门 → 渲染 → 闸门 7/9
# ============================================================================
def generate_one(card, cfg, args):
    """→ (note 或 None, problems, warnings)。与 `CE.gen_one` 同一条请求/重问流程。"""
    payload = CE.build_payload(card)
    prompt = CE.load_system_prompt(getattr(args, 'system_prompt', None))
    problems, warnings, nudge = [], [], None
    tries = 1 + max(0, int(getattr(args, 'retries', 1) or 0))
    for attempt in range(1, tries + 1):
        messages = CE.build_messages(prompt, [payload], nudge)
        raw, _usage, meta = CE.LC.llm_chat(
            cfg, messages,
            json_mode=not getattr(args, 'no_json_mode', False),
            stream=not getattr(args, 'no_stream', False),
            label='    ')
        if meta.get('finish_reason') == 'length':
            problems = ['回复被长度上限截断（JSON 不完整）']
            nudge = '上一次回复被长度上限截断了'
            continue
        entry, why = CE.parse_response(raw, card['id'])
        if entry is None:
            problems = ['回复不是可用的 JSON：%s' % why]
            nudge = why
            continue
        problems, warnings = CE.gate_gen(
            card, entry, {CE.SCOPE_MERGE}, require_ruby=False)
        if not problems:
            note = CE.render_ainote(card, entry)
            problems = CE.gate_apply(
                card, entry, {'fields': {F_NOTE: note}}, [F_NOTE])
            if problems:
                nudge = '；'.join(problems[:4])
                continue
            return note, [], warnings
        nudge = '；'.join(problems[:4])
        if attempt < tries:
            print('    ⚠️ %s；重问一次' % nudge, file=sys.stderr)
    return None, problems, warnings


# ============================================================================
# CLI
# ============================================================================
def add_llm_args(sp):
    """与 core6000 同一套档位参数：换端点走 --profile，钉模型走 --model。"""
    sp.add_argument('--system-prompt', default=None, help='覆盖提示词文件（默认 core6000 正本）')
    sp.add_argument('--base-url', default=None, help='端点 base_url')
    sp.add_argument('--model', default=None, help='模型 id（覆盖配置；通常留空，沿用端点当前模型）')
    sp.add_argument('--profile', default=None, help='~/.dsh/local-llm.json 的 profile 名')
    sp.add_argument('--api-key', default=None, help='api key')
    sp.add_argument('--no-json-mode', action='store_true', help='保留兼容参数')
    sp.add_argument('--no-stream', action='store_true', help='关掉流式')
    return sp


def build_parser():
    ap = argparse.ArgumentParser(
        prog='note_regen.py',
        description='按卡上现有的 ①② 两句重写 AINote（与增加例句同一套提示词/渲染器）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('gen', help='生成并（--commit 时）写 AINote')
    p = add_llm_args(p)
    p.add_argument('--note-id', '--note-ids', dest='note_ids', action='append', required=True,
                   metavar='ID[,ID…]', help='Anki noteId，可重复 / 逗号分隔')
    p.add_argument('--commit', action='store_true', help='真写 AINote（默认演练）')
    p.add_argument('--overwrite', action='store_true', help='AINote 已有内容也覆盖')
    p.add_argument('--out', help='把结果写成 JSON（形状同 cards.py --out）')
    p.add_argument('--retries', type=int, default=1, help='不合格时重问轮数（默认 1）')
    p.set_defaults(func=cmd_gen)
    return ap


def cmd_gen(args):
    t0 = time.time()
    ids = parse_ids(args.note_ids)
    notes = AK.notes_map(ids)
    missing = [i for i in ids if i not in notes]
    if missing:
        raise SystemExit('这些 noteId 在 Anki 里不存在：%s' % '、'.join(map(str, missing)))
    cfg = CE.llm_config_or_empty(args)
    print('本地模型：%s @ %s' % (cfg['model'], cfg['base_url']))

    rows, bad = [], []
    for nid in ids:
        try:
            card = build_regen_card(notes[nid])
        except ValueError as e:
            bad.append((nid, str(e)))
            rows.append({'noteId': nid, 'sentence': '', 'AINote': '', 'SentenceHTML': ''})
            continue
        print()
        print('=' * 72)
        print('noteId %s（%s）' % (nid, card['word'] or '无明显重点词'))
        print('=' * 72)
        print('【Sentence】')
        print(card['snapshot'].get(CE.F_SENT, ''))
        note, problems, warnings = generate_one(card, cfg, args)
        for w in warnings or []:
            print('  ⚠ %s' % w)
        if not note:
            bad.append((nid, '；'.join(problems)[:300]))
            rows.append({'noteId': nid, 'sentence': card['snapshot'].get(CE.F_SENT, ''),
                         'AINote': '', 'SentenceHTML': ''})
            continue
        print('【AINote】')
        print(note)
        rows.append({'noteId': nid, 'sentence': card['snapshot'].get(CE.F_SENT, ''),
                     'AINote': note, 'SentenceHTML': ''})

    if args.out:
        CE.write_json(args.out, rows)
        print('\n产出已写入：%s（%d 张）' % (args.out, len(rows)))

    ok_rows = [r for r in rows if (r.get('AINote') or '').strip()]
    print()
    print('-' * 72)
    print('选中 %d 张：合格 %d ｜ 失败 %d ｜ 用时 %.0fs'
          % (len(ids), len(ok_rows), len(bad), time.time() - t0))
    for nid, why in bad:
        print('  ✗ noteId %s：%s' % (nid, why), file=sys.stderr)

    if not args.commit:
        print('演练：未写库。加 --commit 写 AINote（已有内容默认拒绝，需 --overwrite）。')
        return 0 if not bad else 1
    if not ok_rows:
        print('没有可写入的卡。', file=sys.stderr)
        return 1

    want = {}
    live = AK.note_values([r['noteId'] for r in ok_rows], names=[F_NOTE])
    for r in ok_rows:
        nid = r['noteId']
        if (live.get(nid, {}).get(F_NOTE) or '').strip() and not args.overwrite:
            bad.append((nid, 'AINote 已有内容，拒绝覆盖（加 --overwrite）'))
            continue
        want[nid] = {F_NOTE: r['AINote']}
    if not want:
        print('没有可写入的卡（都被 --overwrite 闸门拦下）。', file=sys.stderr)
        return 1
    rep = WB.write_fields(want, commit=True, label='note_regen')
    if rep.get('bad'):
        return 1
    return 0 if not bad else 1


def main(argv=None):
    a = build_parser().parse_args(argv)
    with AK.guard():
        return a.func(a)


if __name__ == '__main__':
    sys.exit(main())
