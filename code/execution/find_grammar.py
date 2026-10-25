# -*- coding: utf-8 -*-
"""查语法点卡并 dump 全部内容（解释 + 例句 + 简繁翻译），供快速回答「某语法点的例句和讲解」。

背景 / 已验证的坑（2026-10-09，查「そうだ」时踩过的）
------------------------------------------------------
1. 语法卡组是**顶层卡组**（形如 `0-日本语学习::1-语法`）；对它用 deck: 查询会
   包含 N5–N1 全部子卡组。**卡组名不是稳定的**：本工作区曾从 `0-日本語学習`
   改名为 `0-日本语学习`，硬编码旧名字会静默返回 0 命中。所以默认不写死名字，
   而是列出所有 deck、取名字含「语法」的最顶层那个（--deck 可显式覆盖）。
2. Anki 裸关键词 = **全字段子串匹配**：查「そうだ」命中 40 张，其中 36 张只是
   例句/对话里顺带出现（そうです・そうだった・そうだね）。真正的语法点卡是
   **Card 字段精确等于关键词**的那几张。所以默认按 Card 精确过滤。
3. 语法点卡的模型固定为 `どんなときどう使う日本語表現文型Note`，字段布局稳定：
   Card / Bracket / Star / MeaningJP·EN·CN / ConnectiveType1–3 / JNote1–7 /
   CNote1–7 / Sentence1–11（例文，带振假名与 <b> 高亮）/ CN1–11 / CHT1–11 /
   AIConclusion（HTML 讲解）/ BookOrder。详见 docs/find_grammar-使用说明.md。
4. 卡的 deck 字段在 notesInfo dump 里是 None，子卡组归属看 tags
   （如 `日本語表現文型::N4`）。

用法
----
$python code/execution/find_grammar.py そうだ        # stdio 由 code/common/textio.py 接管，不必再设 PYTHONIOENCODING
  → temp\\find_grammar_そうだ.txt（每张卡全字段，UTF-8）+ 控制台摘要

选项：
  --deck NAME                   显式指定卡组（默认自动解析名字含「语法」的最顶层卡组）
  --no-filter                   不按 Card 精确过滤，dump 全部子串命中
  --out PATH                    输出文件（默认 temp\\find_grammar_<关键词>.txt）

依赖：AnkiConnect 在 127.0.0.1:8765；只读，不写库。
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'common'))   # paths.py / anki_api.py
import anki_api as AK  # noqa: E402  唯一的 Anki 访问点
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

ROOT = os.path.abspath(os.path.join(_HERE, '..', '..'))   # 工作区根
SKIP_FIELDS = {'Index'}      # entry_link-N 锚点，无阅读价值


def resolve_grammar_deck():
    """取名字含「语法」的最顶层卡组（父卡组查询覆盖全部子卡组）。

    不硬编码：本工作区的根卡组名曾从 `0-日本語学習` 改为 `0-日本语学习`，
    写死旧名字会静默返回 0 命中。
    """
    cands = [d for d in AK.deck_names() if '语法' in d]
    if not cands:
        return None
    return min(cands, key=lambda d: (d.count('::'), len(d)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('keyword', help='语法关键词，如 そうだ / てしまう')
    ap.add_argument('--deck', default=None,
                    help='目标卡组（默认自动解析名字含「语法」的最顶层卡组）')
    ap.add_argument('--no-filter', action='store_true', help='不按 Card 字段精确过滤')
    ap.add_argument('--out', default=None, help='输出文件路径')
    args = ap.parse_args(argv)


    deck = args.deck or resolve_grammar_deck()
    if not deck:
        print('找不到名字含「语法」的卡组，请用 --deck 指定。')
        return 1
    query = 'deck:"%s" "%s"' % (deck, args.keyword)
    ids = AK.find_notes(query)
    if not ids:
        print('没有命中：%r' % query)
        return 1
    notes = list(AK.notes_map(ids).values())

    def card_of(n):
        return AK.field(n, 'Card', '').strip()

    hits = notes if args.no_filter else [n for n in notes if card_of(n) == args.keyword]
    if not hits:
        print('子串命中 %d 张，但没有 Card 字段精确等于「%s」的语法点卡。' % (len(notes), args.keyword))
        cards = sorted({c for c in map(card_of, notes) if c})
        print('这些命中里出现的 Card 值（供挑选）：')
        for c in cards[:20]:
            print('  - %s' % c)
        return 2

    out = args.out or os.path.join(ROOT, 'temp', 'find_grammar_%s.txt' % args.keyword)
    lines = []
    for n in hits:
        nid = n.get('id')
        tags = n.get('tags', '')
        lines.append('=' * 72)
        lines.append('noteId: %s | tags: %s' % (nid, tags))
        for k, v in (n.get('fields') or {}).items():
            if k in SKIP_FIELDS:
                continue
            v = (v or '').strip()
            if not v:
                continue
            lines.append('-' * 72)
            lines.append('[%s]' % k)
            lines.append(v)
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    print('命中 %d / %d 张（deck:"%s" "%s"%s）' % (
        len(hits), len(notes), deck, args.keyword,
        '' if not args.no_filter else '，未过滤'))
    for n in hits:
        f_ = n.get('fields') or {}
        sents = sum(1 for i in range(1, 12) if (f_.get('Sentence%d' % i) or '').strip())
        print('- noteId %s | %s%s | %s | %s | 例句%d | BookOrder %s' % (
            n.get('id'),
            AK.field(n, 'Card', '?'),
            ('〈%s〉' % AK.field(n, 'Bracket', '')) if AK.field(n, 'Bracket') else '',
            AK.field(n, 'MeaningCN', '?'),
            AK.field(n, 'ConnectiveType1', '?').replace('<s>', '').replace('</s>', ''),
            sents,
            AK.field(n, 'BookOrder', '?'),
        ))
    print('输出：%s' % os.path.abspath(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
