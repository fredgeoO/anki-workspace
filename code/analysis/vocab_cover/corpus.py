# -*- coding: utf-8 -*-
"""把 subtitles/ 下的全部字幕集切成词元，算好每一集的覆盖率，并落盘成
``data/vocab_cover/corpus_tokens.json``，供 report_build.py / cover_cli.py 复用。

按内容哈希缓存，改一集只重算那一集
----------------------------------
每集单独缓存在 ``data/vocab_cover/corpus_cache/<key>.json``，key =
文件相对路径 + 文件内容的 sha1 + 词表（``vocab_state.json``）的 sha1。
所以：换集/改字幕只重算变了的集；**卡组一变（vocab_state 变了）全部自动重算**，
缓存不会给出过期覆盖率。

实测（2026-10-10，48 集 / 10.0 万词元）：全量重算 **约 4 秒**，缓存全命中 **约 0.3 秒**。
（早期文档写的「约 2 分钟」是旧估计，实测没那么慢 —— 缓存的意义主要是
「只改一集时不必重跑全部」和「避免无谓重算」，不是省下几分钟。）

用法::

    python code/analysis/vocab_cover/corpus.py            # 增量：只重算变了的集
    python code/analysis/vocab_cover/corpus.py --force    # 跳过缓存全量重算（并刷新缓存）
    python code/analysis/vocab_cover/corpus.py --list     # 只列发现的集数
    python code/analysis/vocab_cover/corpus.py --prune    # 顺带清掉不再需要的缓存文件
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _deps import (CORPUS_JSON, STATE_JSON, WSP, add_pylibs, ensure_dirs,  # noqa: E402
                   load_state, write_json)
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

add_pylibs()

import jp_tok  # noqa: E402
import srt  # noqa: E402

SUBTITLE_ROOT = os.path.join(WSP.ROOT, 'subtitles')
CACHE_DIR = os.path.join(WSP.DATA, 'vocab_cover', 'corpus_cache')
SKIP_DIRS = {'anki', 'card', 'cards', '_old'}
SKIP_NAME_HINTS = ('（制作', '(制作', '制作anki', 'anki卡牌用')
WORK_LABELS = {
    'ARIA The ANIMATION': 'ARIA The ANIMATION',
    'Heike Monogatari': '平家物語',
    'Yani Neko': 'ヤニねこ',
    'Tensei Oujo to Tensai Reijou no Mahou Kakumei': '転生王女と天才令嬢の魔法革命',
}
BUCKET_CODE = {'core6000': 0, 'jlpt': 1, 'mined': 2, 'oov': 3, 'proper': 4,
               'interj': 5, 'numeral': 6}
CODE_BUCKET = {v: k for k, v in BUCKET_CODE.items()}
WINDOW = 15            # 滑动窗口长度（实词个数）
WINDOW_STEP = 5


def discover(root: str = SUBTITLE_ROOT) -> list:
    """-> [(work, episode_no, path)]，跳过「制作 anki 卡牌用」的裁剪版。"""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        rel = os.path.relpath(dirpath, root)
        work_dir = rel.split(os.sep)[0] if rel != '.' else ''
        for fn in sorted(filenames):
            if not fn.lower().endswith(('.srt', '.txt', '.ass', '.vtt')):
                continue
            if any(h in fn for h in SKIP_NAME_HINTS):
                continue
            ep = episode_no(fn)
            if ep is None:
                continue
            found.append((WORK_LABELS.get(work_dir, work_dir), ep, os.path.join(dirpath, fn)))
    found.sort(key=lambda t: (t[0], t[1]))
    return found


def episode_no(filename: str):
    m = re.search(r'S\d{1,2}E(\d{1,2})', filename)
    if m:
        return int(m.group(1))
    m = re.search(r'第(\d{1,2})[集話话]', filename)
    if m:
        return int(m.group(1))
    stem = os.path.splitext(filename)[0]
    nums = re.findall(r'(?<![\d])(\d{1,2})(?![\d])', stem)
    if nums:
        return int(nums[-1])
    return None


def episode_record(ep: srt.Episode, vocab: 'jp_tok.Vocabulary') -> dict:
    toks = []
    for u in ep.utterances:
        toks.extend(vocab.tokenize(u))
    cov = vocab.coverage(toks, sentences=ep.sentences())
    s = cov.summary()
    ca, cv, cl = s['cover_all'], s['cover_vocab'], s['cover_learnable']

    # 只看词汇词（去掉语法词、符号），并按最懂状态记录
    word_counts = collections.Counter()
    meta = {}
    for t in toks:
        if not t.is_vocab:
            continue
        w = t.key or jp_tok.norm_word(t.surface)
        if not w:
            continue
        word_counts[w] += 1
        cur = meta.get(w)
        if cur is None:
            meta[w] = (BUCKET_CODE[t.bucket], t.known, t.mature, t.pos1, t.pos2,
                       t.compound_of_known)
        else:
            c, k, mt, p1, p2, cp = cur
            meta[w] = (c, k or t.known, mt or t.mature, p1, p2, cp or t.compound_of_known)

    # 滑动窗口可懂度：连续 WINDOW 个词汇词里有没有不懂的词
    content = [t for t in toks if t.is_vocab]
    win_total = win_full = win_len1 = win_full_s = 0
    for i in range(0, max(0, len(content) - WINDOW + 1), WINDOW_STEP):
        chunk = content[i:i + WINDOW]
        unk = sum(1 for t in chunk if not t.understood_lenient)
        unk_s = sum(1 for t in chunk if not t.understood)
        win_total += 1
        win_full += 1 if unk == 0 else 0
        win_len1 += 1 if unk <= 1 else 0
        win_full_s += 1 if unk_s == 0 else 0

    total = s['tokens']['all']
    total_c = s['tokens']['vocab']
    return {
        'work': ep.work, 'episode': None, 'title': ep.title,
        'file': os.path.relpath(ep.path, WSP.ROOT).replace('\\', '/'),
        'cues': len(ep.cues), 'speech_cues': len(ep.speech_cues),
        'chars': ep.chars, 'speech_seconds': round(ep.speech_seconds, 1),
        'tokens': total, 'tokens_vocab': total_c,
        'tokens_learnable': s['tokens']['learnable'],
        'tokens_grammar': s['tokens']['grammar'], 'tokens_symbol': s['tokens']['symbol'],
        'buckets': s['buckets'],
        'types': s['types']['buckets'],
        'types_total': s['types']['vocab'],
        'types_learnable': s['types']['learnable'],
        'types_all': s['types']['all'],
        'cover_all': ca, 'cover_vocab': cv, 'cover_learnable': cl,
        'known_tokens': round(ca.get('known', 0) * total),
        'mature_tokens': round(ca.get('mature', 0) * total),
        'understood_tokens': round(ca.get('understood', 0) * total),
        'understood_lenient_tokens': round(ca.get('understood_lenient', 0) * total),
        'understood_mature_tokens': round(ca.get('understood_mature', 0) * total),
        'sentences': s['sentences'],
        'window_15': {'n': win_total, 'full': round(win_full / win_total, 4) if win_total else 0,
                      'lenient': round(win_len1 / win_total, 4) if win_total else 0,
                      'full_strict': round(win_full_s / win_total, 4) if win_total else 0},
        'oov_top': s['oov'][:200],
        'proper_top': s['proper'][:100],
        'word_counts': {w: [n, meta[w][0], int(meta[w][1]), int(meta[w][2])]
                        for w, n in word_counts.items()},
        'word_meta': {w: [meta[w][3], meta[w][4], int(meta[w][5])] for w in word_counts},
    }


def _vocab_sig() -> str:
    """词表指纹 = ``vocab_state.json`` 的字节 sha1。

    卡组/掌握状态一变，所有缓存自动失效 —— 缓存只会省「字幕没变」的重算，
    **不会**给出过期覆盖率。
    """
    try:
        return hashlib.sha1(textio.read_bytes(STATE_JSON)).hexdigest()
    except OSError:
        return 'nostate'


def _cache_key(rel: str, path: str, vsig: str) -> str:
    """缓存键 = 相对路径 + 文件内容 + 词表指纹（改名/改内容/改卡组都会换键）。"""
    h = hashlib.sha1()
    h.update(rel.encode('utf-8'))
    h.update(b'\x00')
    h.update(textio.read_bytes(path))
    h.update(b'\x00')
    h.update(vsig.encode('ascii'))
    return h.hexdigest()


def build(verbose: bool = True, use_cache: bool = True, prune: bool = False) -> dict:
    """``use_cache=False``（``--force``）只跳过**读**缓存，仍然会刷新写入。"""
    ensure_dirs()
    state = load_state()
    vocab = jp_tok.Vocabulary(state)
    vsig = _vocab_sig()
    os.makedirs(CACHE_DIR, exist_ok=True)
    t0 = time.time()
    hits = misses = 0
    used = set()
    episodes = []
    for work, no, path in discover():
        rel = os.path.relpath(path, WSP.ROOT).replace('\\', '/')
        rec = None
        cpath = None
        from_cache = False
        try:
            cpath = os.path.join(CACHE_DIR, _cache_key(rel, path, vsig) + '.json')
            used.add(os.path.basename(cpath))
            # 缓存文件是 {_cache: {rel, vsig}, rec: {...}} 的信封：
            # ① 不改 rec 的形状（corpus_tokens.json 的输出格式必须原样不变）
            # ② 用 rel 自证「这份缓存确实是这一集」——
            #    注意 rec['file'] 是**文件名 stem**（srt.parse_srt_text 把 ep.path 设成 title），
            #    不能当身份用。
            if use_cache:
                blob = textio.load_json(cpath, default=None)
                if (isinstance(blob, dict) and isinstance(blob.get('rec'), dict)
                        and (blob.get('_cache') or {}).get('rel') == rel):
                    rec = blob['rec']
        except OSError:
            cpath, rec = None, None
        if rec is not None:
            hits += 1
            from_cache = True
        else:
            rec = None
            misses += 1
            ep = srt.load_episode(path, work=work)
            rec = episode_record(ep, vocab)
            if cpath:
                textio.dump_json({'_cache': {'rel': rel, 'vsig': vsig,
                                             'saved_at': _dt.datetime.now().isoformat(timespec='seconds')},
                                  'rec': rec}, cpath)
        rec['episode'] = no          # 集号从文件名现算，不信缓存里那份
        episodes.append(rec)
        if verbose:
            tot = rec['tokens']
            ca = rec['cover_all']
            print(f"  {work:<20} 第{no:>2}集 [{'缓存' if from_cache else '重算'}] "
                  f"词元={tot:>5}  词汇词={rec['tokens_vocab']:>5}  "
                  f"core={ca.get('core', 0)*100:>5.1f}%  卡组={ca.get('deck', 0)*100:>5.1f}%  "
                  f"我懂={ca.get('understood_lenient', 0)*100:>5.1f}%  "
                  f"新词种={rec['types'].get('oov', 0):>4}"
                  f"（专名 {rec['types'].get('proper', 0):>3}）")
    corpus = {
        'generated_at': _dt.datetime.now().isoformat(timespec='seconds'),
        'subtitle_root': os.path.relpath(SUBTITLE_ROOT, WSP.ROOT).replace('\\', '/'),
        'vocab_state': os.path.relpath(os.path.join(WSP.DATA, 'vocab_cover',
                                                   'vocab_state.json'), WSP.ROOT).replace('\\', '/'),
        'vocab_generated_at': state['generated_at'],
        'split_mode': vocab.split_mode,
        'window': WINDOW, 'window_step': WINDOW_STEP,
        'works': sorted({e['work'] for e in episodes}),
        'episodes': episodes,
    }
    write_json(corpus, CORPUS_JSON)
    if prune and use_cache:
        extra = sorted(f for f in os.listdir(CACHE_DIR)
                       if f.endswith('.json') and f not in used)
        if extra:
            print('将删 %d 个不再需要的缓存文件：%s'
                  % (len(extra), '、'.join(extra[:5]) + ('…' if len(extra) > 5 else '')))
            for f in extra:
                os.remove(os.path.join(CACHE_DIR, f))
        else:
            print('缓存目录没有多余文件。')
    if verbose:
        print(f"\n共 {len(episodes)} 集，"
              f"{sum(e['tokens'] for e in episodes)} 词元（词汇词 "
              f"{sum(e['tokens_vocab'] for e in episodes)}），"
              f"{sum(e['types_total'] for e in episodes)} 词汇词种（含跨集重复）")
        print('缓存：命中 %d / 重算 %d（%.1f 秒）'
              % (hits, misses, time.time() - t0))
        print(f'写出 {CORPUS_JSON}')
    return corpus


def main() -> int:
    ap = argparse.ArgumentParser(description='扫描字幕并落盘词元统计（每集增量缓存）')
    ap.add_argument('--list', action='store_true', help='只列发现的集数')
    ap.add_argument('--force', action='store_true',
                    help='忽略缓存，全部重算（并刷新缓存）')
    ap.add_argument('--prune', action='store_true',
                    help='顺带删掉不再需要的缓存文件（删前打印计数）')
    args = ap.parse_args()
    if args.list:
        for work, no, path in discover():
            print(f'{work:<20} 第{no:>2}集  {os.path.relpath(path, WSP.ROOT)}')
        return 0
    build(use_cache=not args.force, prune=args.prune)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
