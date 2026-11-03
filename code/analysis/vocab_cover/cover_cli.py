# -*- coding: utf-8 -*-
"""★ 可复用入口：给任意一段日语文本（或一集字幕），回答三个问题

1. 这段文字里有多少词落在我的 core6000 / 考级词汇 / 素材生词里（覆盖率，两套口径）
2. 有多少词完全不在我的卡组里（新词），以及卡组里有卡但我还没学的（待激活）
3. 按我现在的水平，这段文字我能懂多少（句子级实测 + 覆盖率经验映射）

用法::

    # 一集字幕（.srt 自动按字幕解析）
    python cover_cli.py "subtitles/Yani Neko/ヤニねこ.S01E01...srt"

    # 一篇纯文本 / 一段话
    python cover_cli.py article.txt
    python cover_cli.py --text "日本語の文章..."
    Get-Content x.txt -Raw | python cover_cli.py --stdin

    # 机器可读 + 导出新词表（可直接喂给 mine 流水线）
    python cover_cli.py ep.srt --json --out-json result.json \
        --oov-out data/vocab_cover/oov_ep01.json \
        --untackled-out data/vocab_cover/untackled_ep01.txt

    # 换分词粒度看敏感度（A 最短单位 / B 中间 / C 最长）
    python cover_cli.py ep.srt --split-mode C
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _deps import STATE_JSON, add_pylibs, write_json  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

add_pylibs()

import analyze  # noqa: E402
import jp_tok  # noqa: E402
import srt as srt_mod  # noqa: E402


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='给任意日语文本/字幕算「占我卡组多少 + 有多少新词 + 我能懂多少」',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument('paths', nargs='*', help='文件路径（.srt 按字幕解析，其它按纯文本）')
    ap.add_argument('--text', help='直接给一段文字')
    ap.add_argument('--stdin', action='store_true', help='从标准输入读')
    ap.add_argument('--srt', action='store_true', help='强制按字幕解析')
    ap.add_argument('--plain', action='store_true', help='强制按纯文本解析')
    ap.add_argument('--split-mode', default='A', choices=['A', 'B', 'C'],
                    help='Sudachi 切分粒度，默认 A（最短单位，与词表粒度最接近）')
    ap.add_argument('--state', default=STATE_JSON, help='换一份词汇快照 JSON')
    ap.add_argument('--top', type=int, default=25, help='打印多少个新词/待学词')
    ap.add_argument('--json', action='store_true', help='只输出 JSON')
    ap.add_argument('--out-json', help='把完整结果写到这个文件')
    ap.add_argument('--oov-out', help='把「卡组外新词表」写到这个文件（JSON）')
    ap.add_argument('--untackled-out', help='把「卡组里有卡但没刷过」的词写到这个文件（一行一个）')
    ap.add_argument('--no-lists', action='store_true', help='不打印词表')
    ap.add_argument('--quiet', action='store_true', help='不打印人类可读报告（配合 --out-json）')
    ap.add_argument('--screen', action='store_true',
                    help='附加「卡组外新词筛选」：复用 today-new 的内容词闸（Sudachi C 粒度），'
                         '挡掉の/ぞ/すっ 这类切分碎片与语气词')
    ap.add_argument('--rank', action='store_true',
                    help='在 --screen 基础上再调本地模型整集精排（复用 rank_gate，一集一次）')
    ap.add_argument('--rank-k', type=int, default=30, help='精排让模型给回多少个（默认 30）')
    ap.add_argument('--screen-out', help='把筛选结果写到这个文件（JSON）')
    return ap


def read_inputs(args) -> list:
    """-> [(label, text, is_srt)]"""
    items = []
    if args.text:
        items.append(('--text', args.text, False))
    if args.stdin:
        items.append(('stdin', textio.read_stdin(), False))
    for p in args.paths:
        if not os.path.exists(p):
            print(f'[跳过] 找不到文件：{p}', file=sys.stderr)
            continue
        ext = os.path.splitext(p)[1].lower()
        is_srt = (not args.plain) and (args.srt or ext in ('.srt', '.ass', '.ssa', '.vtt'))
        # SRT 一律把**原始文件内容**交给 analyze.sentences_of 解析，
        # 否则二次解析会因为没有时间轴而得到空文本
        items.append((p, srt_mod.read_text(p), is_srt))
    if not items:
        print('没有输入。用 paths / --text / --stdin 指定内容。', file=sys.stderr)
    return items


def summarize(res: dict) -> dict:
    """面板/脚本用的头条指标（口径与 analyze.render 完全一致）。"""
    ca = res.get('cover_all') or {}
    comp = res.get('comprehension') or {}
    sent = res.get('sentences') or {}
    reach = (res.get('reach') or {}).get('deck') or {}
    return {
        'chars': res.get('chars'),
        'tokens': res.get('tokens'),
        'types': res.get('types'),
        # 主推：含语法词口径（与报告里「★我实际能懂（宽口径）」同一列）
        'deck': ca.get('deck'),
        'known': ca.get('known'),
        'mature': ca.get('mature'),
        'understood': ca.get('understood_lenient'),
        'strict': ca.get('understood'),
        'comprehension': comp.get('by_understood'),
        'sentence_full': sent.get('full'),
        'sentence_lenient': sent.get('lenient_l'),
        'oov_types': len(res.get('oov') or []),
        'untackled_types': len(res.get('untackled') or []),
        'deck_total': reach.get('deck_total'),
        'deck_seen': reach.get('seen'),
    }


def annotate(res: dict) -> dict:
    """给单份结果补 schema/摘要（旧字段一个不动，向后兼容）。"""
    res['schema'] = 1
    res['tool'] = 'vocab-cover'
    res['generated_at'] = dt.datetime.now().isoformat(timespec='seconds')
    res['summary'] = summarize(res)
    return res


def main() -> int:
    args = build_argparser().parse_args()
    items = read_inputs(args)
    if not items:
        return 2

    vocab = jp_tok.Vocabulary.load(args.state, split_mode=args.split_mode)
    want_screen = bool(args.screen or args.rank or args.screen_out)
    if want_screen:
        import screen as SCR      # 复用 today-new 的内容词闸 / 精排（延迟导入）
    results, screens = [], []
    for label, text, is_srt in items:
        sentences, clean_text, ep = analyze.sentences_of(text, is_srt=is_srt)
        res = analyze.analyze_text(vocab, clean_text, sentences=sentences, label=label)
        if want_screen:
            sres = SCR.collect(sentences, vocab)
            picks, meta = ([], {})
            if args.rank:
                picks, meta = SCR.rank(sres['items'], clean_text, k=args.rank_k)
            screens.append((sres, picks, meta))
            res['screen'] = SCR.to_json(sres, picks, meta)
        results.append(res)

    for res in results:
        annotate(res)

    payload = results[0] if len(results) == 1 else results
    if args.out_json:
        write_json(payload, args.out_json)
    if args.screen_out:
        blobs = [SCR.to_json(s, p, m) for s, p, m in screens]
        write_json(blobs[0] if len(blobs) == 1 else blobs, args.screen_out)
    if args.oov_out:
        oov = results[0]['oov'] if len(results) == 1 else [
            r['oov'] for r in results]
        write_json(oov, args.oov_out)
    if args.untackled_out:
        rows = results[0]['untackled'] if len(results) == 1 else [
            r['untackled'] for r in results]
        with open(args.untackled_out, 'w', encoding='utf-8') as fh:
            for row in rows:
                fh.write(f'{row[0]}\t{row[1]}\t{row[2]}\n')

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not args.quiet:
        for i, res in enumerate(results):
            print(analyze.render(res, top=args.top, show_lists=not args.no_lists))
            if i < len(screens):
                sres, picks, meta = screens[i]
                print(SCR.render(sres, picks, meta, top=args.top))
            print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
