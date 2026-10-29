# -*- coding: utf-8 -*-
"""外部词频表（Jiten）当排序源：让存量新卡按**动画通用频率**排（全局新卡顺序）。

为什么换成外部词表
------------------
``study_plan.py`` 的排序来自本工作区自己的 36 集字幕（8.2 小时）：最高频词只有
196 次，第 50 名往后就掉到个位数，排名基本是噪声；而且被单部作品污染（緑目 55 次
排第 9、武士 24 次排第 19）。Jiten 的 Anime 词表建在 **3,762 部动画字幕**上，
排序深度好得多，而且它按「出现在多少部不同作品里」排、不按单部里的重复次数排
—— 正好抵消上面那种单集噪声。

它换不掉什么（别混）
------------------
* **每集激活照旧**：外部词表答的是「动画里普遍常不常见」，答不了「我下一集马上
  会碰到什么」。阶段 3（activate.py）不动。
* **挖词照旧**：外部词表只能给**已有卡**排序，补不了卡组外的缺口 —— 覆盖率报告里
  那「最高频 1000 词里卡组没有的 242 个」仍要走 mine.py。

用法::

    python code/analysis/vocab_cover/freq_external.py download --media Anime
    python code/analysis/vocab_cover/freq_external.py build    --media Anime
    python code/analysis/vocab_cover/freq_external.py compare  --media Anime

    # 注解：按待办 tag 回填 JitenAnimeRank
    python code/analysis/vocab_cover/freq_external.py field --tag 需更新JAR --remove-tag --commit

    # 注解：全量回填另一套词表（Global -> JitenGlobalRank，两类词汇卡）
    python code/analysis/vocab_cover/freq_external.py field \\
        --models vocab --media Global --field JitenGlobalRank --add-field --commit

产物::

    data/freq/jiten_freq_Anime.csv                 原始词表（CC BY-SA 4.0，见 data/freq/README.md）
    data/freq/jiten_freq_Global.csv                全媒介词表（同上）
    data/vocab_cover/study_plan_jiten_anime.json   与 study_plan_critical_path.json 同形状
    data/vocab_cover/freq_compare_anime.json       对比数据
    docs/reports/外部词表排序对比.md                对比报告

接上既有链路（既有脚本一行不用改）::

    python code/analysis/vocab_cover/make_activate_plan.py \\
        --words-file data/vocab_cover/study_plan_jiten_anime.json --tag jiten
    python code/execution/activate.py apply  --plan data/plans/plan_activate_jiten.json           # 演练
    python code/execution/activate.py apply  --plan data/plans/plan_activate_jiten.json --commit  # 真写
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import hashlib
import json
import math
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _deps import DATA_DIR, WSP, add_pylibs, write_json  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
import anki_api as AK  # noqa: E402  Anki 读写唯一接口（code/common/anki_api.py）
from _norm import norm_word, primary_form  # noqa: E402

FREQ_DIR = os.path.join(WSP.DATA, 'freq')
API = 'https://api.jiten.moe/api/frequency-list/download'
LICENSE = 'CC BY-SA 4.0'

# 合成词频的标度：CSV 只给 Rank 不给次数，make_activate_plan.py 却按 corpus_count
# 过滤/展示。这里用 ``10**6 // rank``（≈「每百万词出现次数」的粗估）填一个单调值，
# **真实排名以 freq_rank 为准**；plan 里的 occurrences 是合成值，别当语料实测。
COUNT_SCALE = 10 ** 6
MEDIA_HELP = 'Global / Anime / Drama / Movie / Manga / Novel / VisualNovel / VideoGame / WebNovel / YouTube / Audio / NonFiction / Kanji'

# 词字段候选（与 make_activate_plan.py WORD_FIELDS 一致），取第一个非空。
WORD_FIELDS = ('Word', 'VocabKanji', 'Expression', 'Front', 'Vocabulary', '単語')

# 已知笔记类型的词字段映射（与 cmd_field 的 --all-notes 路径一致）。
KNOWN_WORD_FIELD = {
    'Japanese Vocabulary': ('Word',),
    'eggrolls-JLPT10k-v3.5': ('VocabKanji',),
}

# 库里两个「词汇卡」笔记类型。`--models vocab` 是它们的简写，避免手打长名拼错
# （拼错不会报错，只会 0 命中 —— 白跑一趟）。
VOCAB_MODELS = ('Japanese Vocabulary', 'eggrolls-JLPT10k-v3.5')

# 旧字体 -> 新字体：Jiten 词表只收新字体，卡组里偶有旧字体词条（`剝げる`）。
# 只在首次查表落空时再试一次；新遇到的旧字体往这里加（保持一字符对一字符）。
KYUJITAI = {
    '剝': '剥',
}


# --------------------------------------------------------------- 工具

def _now() -> str:
    return _dt.datetime.now().isoformat(timespec='seconds')


def _url(media: str) -> str:
    q = {'downloadType': 'csv'}
    if media and media.lower() != 'global':
        q['mediaType'] = media
    return API + '?' + urllib.parse.urlencode(q)


def _csv_path(media: str) -> str:
    return os.path.join(FREQ_DIR, 'jiten_freq_%s.csv' % (media or 'global'))


def _slug(media: str) -> str:
    return (media or 'global').lower()


def _plan_path(media: str) -> str:
    """默认词表档名：带 jiten 前缀，别和 study_plan.py 的本地语料清单混。"""
    return os.path.join(DATA_DIR, 'study_plan_jiten_%s.json' % _slug(media))


def _rankdata(xs):
    """并列取平均秩 —— 与 study_plan.py 的算法一致，别换实现。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(a, b) -> float:
    if len(a) < 2:
        return 0.0
    ra, rb = _rankdata(a), _rankdata(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else 0.0


# --------------------------------------------------------------- 1. download

def cmd_download(args) -> int:
    os.makedirs(FREQ_DIR, exist_ok=True)
    dest = _csv_path(args.media)
    if os.path.exists(dest) and not args.force:
        print('已存在，跳过（--force 重下）：%s' % os.path.relpath(dest, WSP.ROOT))
        print('  行数 %d · 大小 %.1f MB' % (_count_rows(dest), os.path.getsize(dest) / 1e6))
        return 0

    url = _url(args.media)
    print('下载 %s' % url)
    req = urllib.request.Request(url, headers={'User-Agent': 'anki-workspace/1.0'})
    with urllib.request.urlopen(req, timeout=args.timeout) as r:
        body = r.read()
        disp = r.headers.get('Content-Disposition') or ''
    # 服务端给的档名最可信（mediaType 拼错时也能看出来下到的是哪份）
    server_name = ''
    if 'filename=' in disp:
        server_name = disp.split('filename=')[-1].split(';')[0].strip().strip('"')
    with open(dest, 'wb') as fh:
        fh.write(body)
    rows = _count_rows(dest)
    sha = hashlib.sha256(body).hexdigest()
    print('  -> %s' % os.path.relpath(dest, WSP.ROOT))
    print('  服务端档名 %s · %d 行 · %.1f MB · sha256 %s' % (server_name or '?', rows, len(body) / 1e6, sha[:16]))

    _write_readme(args.media, dest, url, server_name, rows, sha)
    return 0


def _count_rows(path: str) -> int:
    n = 0
    with open(path, encoding='utf-8-sig', newline='') as fh:
        for _ in fh:
            n += 1
    return max(0, n - 1)


def _write_readme(media, dest, url, server_name, rows, sha) -> None:
    path = os.path.join(FREQ_DIR, 'README.md')
    entry = (
        '### %s\n\n'
        '* 档名：`%s`（服务端：`%s`）\n'
        '* 来源：`%s`\n'
        '* 许可：**%s**（Jiten，https://jiten.moe/frequency-dictionaries）\n'
        '* 下载于：%s · %d 行 · sha256 `%s`\n'
        '* 格式：`Word,Form,Rank`。Rank 1 = 最常用；排序按「出现在多少部不同作品里」，\n'
        '  不按单部作品里的重复次数 —— 所以单集反复出现的词不会顶到前面。\n'
    ) % (media, os.path.basename(dest), server_name or '-', url, LICENSE, _now(), rows, sha)

    head = ('# data/freq —— 外部词频表\n\n'
            'Jiten 的动画/全媒介词频表，由 `code/analysis/vocab_cover/freq_external.py download` 拉取。\n'
            '**许可 CC BY-SA 4.0**：自用没问题；若把派生卡组或清单分发出去，要保留署名并以相同许可分享。\n\n'
            '重建：`python code/analysis/vocab_cover/freq_external.py download --media Anime --force`\n\n')
    old = ''
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            old = fh.read()
    # 同一 media 重复下载时替换旧条目，别越堆越多
    blocks = [b for b in old.split('\n### ')[1:]] if old.startswith(head) else []
    kept = [b for b in blocks if not b.startswith(media + '\n')]
    body = head + entry + ''.join('\n### ' + b for b in kept)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body.rstrip() + '\n')


# --------------------------------------------------------------- 2. build

def load_index(csv_path: str) -> dict:
    """CSV -> ``{归一化词: (rank, 显示词形)}``。

    ``Word``（汉字形）和 ``Form``（假名形）**两把键都收**，各自记下产出该键的原
    始词形 —— 这样卡组里写「言う」或「いう」都能查到，而且回写给
    make_activate_plan.py 的 ``word`` 一定满足 ``norm_word(word) == 该键``。
    """
    index = {}
    dups = 0
    with open(csv_path, encoding='utf-8-sig', newline='') as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            try:
                rank = int((row.get('Rank') or '').strip())
            except ValueError:
                continue
            for raw in ((row.get('Word') or '').strip(), (row.get('Form') or '').strip()):
                key = norm_word(raw)
                if not key or not raw:
                    continue
                cur = index.get(key)
                if cur is None:
                    index[key] = (rank, raw)
                elif rank < cur[0]:
                    index[key] = (rank, raw)
                    dups += 1
                else:
                    dups += 1
    return index


def lookup_rank(index, word: str) -> int:
    """词 -> 词表 rank（查不到返回 0）。先按原词查，再按旧字体换新字体查一次。"""
    key = norm_word(primary_form(word))
    hit = index.get(key)                        # load_index：键 -> (rank, 原始词形)
    if hit is None:
        fixed = ''.join(KYUJITAI.get(c, c) for c in primary_form(word))
        if fixed != primary_form(word):
            hit = index.get(norm_word(fixed))
    return hit[0] if hit else 0


def derive_field_values(notes, index, no_rank='999999'):
    """notesInfo 结果 → (``{noteId: 字段值}``, ``{noteId: 词}``, 无词笔记数)。

    纯函数（不碰 Anki），``--tag`` 与 ``--models`` 两条路共用同一套推导，
    测试也能离线覆盖：词字段按笔记类型的惯例取，排名 ``%06d`` 补零，
    词表查不到写 ``no_rank``。
    """
    want, words, skipped = {}, {}, 0
    for n in notes:
        nid = int(n['noteId'])
        model = n.get('modelName')
        fields = {k: (v or {}).get('value', '') for k, v in (n.get('fields') or {}).items()}
        cand = KNOWN_WORD_FIELD.get(model, WORD_FIELDS)
        word = next((fields[f] for f in cand if fields.get(f)), '')
        if not word:
            skipped += 1
            continue
        rank = lookup_rank(index, word)
        words[nid] = word
        want[nid] = ('%06d' % rank) if rank else no_rank
    return want, words, skipped


def _expand_models(models):
    """``['vocab']`` -> 两个词汇笔记类型；其余原样（保持顺序、去空）。"""
    out = []
    for m in models or ():
        m = (m or '').strip()
        if not m:
            continue
        out.extend(VOCAB_MODELS if m.lower() == 'vocab' else (m,))
    seen, uniq = set(), []
    for m in out:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq


def cmd_build(args) -> int:
    src = _csv_path(args.media)
    if not os.path.exists(src):
        print('找不到 %s —— 先跑 download' % os.path.relpath(src, WSP.ROOT))
        return 2
    index = load_index(src)
    rows = []
    for key, (rank, raw) in index.items():
        rows.append({'word': raw, 'corpus_count': max(1, COUNT_SCALE // rank),
                     'freq_rank': rank})
    rows.sort(key=lambda r: (r['freq_rank'], r['word']))
    if args.max_rank:
        rows = [r for r in rows if r['freq_rank'] <= args.max_rank]
    if args.top:
        rows = rows[:args.top]

    out = args.out or _plan_path(args.media)
    write_json(rows, out)
    print('词表 %s：%d 行 -> 归一化键 %d 个 -> 写出 %d 条' % (
        os.path.relpath(src, WSP.ROOT), _count_rows(src), len(index), len(rows)))
    print('  %s  (%.1f MB)' % (os.path.relpath(out, WSP.ROOT), os.path.getsize(out) / 1e6))
    print('  排名范围 %d .. %d' % (rows[0]['freq_rank'], rows[-1]['freq_rank']) if rows else '  （空）')
    print('\n下一步（既有链路一行不用改）：')
    print('  python code/analysis/vocab_cover/make_activate_plan.py \\')
    print('      --words-file "%s" --tag %s' % (out, _slug(args.media)))
    return 0


# --------------------------------------------------------------- 3.5 field

# ---- --all-notes 写前快照 / 写后调度列 diff（2026-10-10）-------------------
PRE_SNAP_PREFIX = 'pre_jiten_field_'
SNAP_FRESH_SECONDS = 3600                 # 1 小时内的快照算「够新」，可直接当写前基准
SCHED_COLS = ('due', 'ivl', 'factor', 'reps', 'lapses', 'queue', 'type')


def _newest_fresh_snapshot(max_age: float = SNAP_FRESH_SECONDS):
    """data/snapshots 下最新的一份收藏库副本；比 max_age 旧就不要（返回 None）。"""
    best = None
    if not os.path.isdir(WSP.SNAPSHOTS):
        return None
    for name in sorted(os.listdir(WSP.SNAPSHOTS)):
        d = os.path.join(WSP.SNAPSHOTS, name)
        if not os.path.isdir(d):
            continue
        for fn in ('c.anki2', 'collection.anki2'):
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                age = time.time() - os.path.getmtime(p)
                if age <= max_age and (best is None or age < best[0]):
                    best = (age, p)
    return best[1] if best else None


def _copy_live_snapshot() -> str:
    """把 live 收藏库拷成一份**持久**副本（写前基准，diff 完也不删，留档）。"""
    out = os.path.join(WSP.SNAPSHOTS, PRE_SNAP_PREFIX + time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(out, exist_ok=True)
    src = WSP.LIVE_COLLECTION
    for suf in ('', '-wal', '-shm'):
        if os.path.exists(src + suf):
            shutil.copy2(src + suf, os.path.join(out, 'c.anki2' + suf))
    return os.path.join(out, 'c.anki2')


def _sched_from_snapshot(rows) -> dict:
    return {int(r['cardId']): {c: r.get(c) for c in SCHED_COLS} for r in rows}


def _sched_from_live(cards) -> dict:
    """AnkiConnect 的 cardsInfo 用 ``interval``，快照侧叫 ``ivl`` —— 这里统一。"""
    out = {}
    for c in cards:
        out[int(c['cardId'])] = {
            'due': c.get('due'), 'ivl': c.get('interval', c.get('ivl')),
            'factor': c.get('factor'), 'reps': c.get('reps'),
            'lapses': c.get('lapses'), 'queue': c.get('queue'), 'type': c.get('type'),
        }
    return out


def _sched_diff(before: dict, after: dict):
    """→ [(cardId, 列, 写前, 写后)]（只列两边都有的卡）。"""
    out = []
    for cid, a in after.items():
        b = before.get(cid)
        if not b:
            continue
        for col in SCHED_COLS:
            if a.get(col) != b.get(col):
                out.append((cid, col, b.get(col), a.get(col)))
    return out


def _report_sched_diff(snap_path: str, note_ids: list, chunk: int = 200) -> None:
    """用写前快照 diff 受影响卡片的调度列；非零就大声告警。"""
    import anki_api as AK
    try:
        with AK.Snapshot.open(path=snap_path) as snap:
            before = _sched_from_snapshot(snap.cards(note_ids=note_ids))
    except Exception as exc:                                   # noqa: BLE001
        print('  [!] 读不了写前快照，跳过调度列 diff：%s' % exc)
        return
    cids = AK.cards_of_notes(note_ids)
    after = AK.cards_info(cids, chunk=chunk)
    diffs = _sched_diff(before, _sched_from_live(after))
    print()
    print('写后自检（调度列 diff，基准 %s）：' % os.path.relpath(snap_path, WSP.ROOT))
    print('  对比卡片 %d 张（涉及笔记 %d 个）' % (len(after), len(note_ids)))
    if not diffs:
        print('  ✓ 调度列变化 0 处 —— 字段写没有碰到 due/ivl/factor/reps/lapses/queue/type')
        return
    print('  ✗✗ 调度列有 %d 处变化（字段写**不应该**动调度；'
          '若这份基准不是写入前刚落的，也可能混入了正常复习/同步）' % len(diffs))
    for cid, col, b, a in diffs[:20]:
        print('      card=%s %s: %s -> %s' % (cid, col, b, a))
    if len(diffs) > 20:
        print('      …（共 %d 处）' % len(diffs))


def _cmd_field_tag(args) -> int:
    """按 Anki tag 查询笔记，把笔记里的词查 Jiten 排名，写回 JitenAnimeRank 字段。

    与 --plan / --all-notes 互斥。不落快照、不 diff 调度列、不重拍 due：
    纯粹把词表排名注解到字段上。值相同的笔记跳过（幂等、不动 mod）。
    `--remove-tag`：写完把这批笔记上的待办 tag 摘掉（值已正确 / 刚写好 / 词表查不到写
    no_rank 的都算「已完成」；无词字段和写入失败的不摘）。
    """
    index_path = _csv_path(args.media)
    if not os.path.exists(index_path):
        print('找不到 %s —— 先跑：python code/analysis/vocab_cover/freq_external.py download --media %s'
              % (os.path.relpath(index_path, WSP.ROOT), args.media))
        return 2
    index = load_index(index_path)
    print('Jiten 词表 %s：%d 个归一化键' % (
        os.path.relpath(index_path, WSP.ROOT), len(index)))

    # 查询笔记（tag: 前缀由查询串本身承担，args.tag 只给名字）
    query = 'tag:%s' % args.tag
    try:
        nids = AK.find_notes(query)
    except Exception as exc:                       # noqa: BLE001
        print('✗ 查询 tag %s 失败：%s' % (args.tag, exc))
        return 1
    if not nids:
        print('tag %s 下没有命中笔记' % args.tag)
        return 0
    print('tag %s 下命中 %d 个笔记' % (args.tag, len(nids)))

    # 读字段 + 提取词 → 查排名（推导与 --models 路径共用同一纯函数）
    notes = AK.notes_info(nids)
    want, words, skipped_no_word = derive_field_values(notes, index, args.no_rank)

    # 读取当前字段值，做幂等对照
    current = {int(n['noteId']): (AK.field(n, args.field) or '') for n in notes}

    todo = {n: v for n, v in want.items() if current.get(n) != v}
    ok_ids = [n for n in want if n not in todo]          # 值已经对，不用写
    print('需要写入/更新：%d 个（值已正确的跳过 %d 个，无词字段跳过 %d 个）' % (
        len(todo), len(ok_ids), skipped_no_word))

    miss = sorted({words[n] for n, v in todo.items() if v == args.no_rank})
    print('  词表未命中（写 %s）：%d 个%s' % (
        args.no_rank, len(miss), ('：' + '、'.join(miss[:20])) if miss else ''))
    if args.remove_tag:
        print('摘 tag：从 %d 个笔记移除「%s」（无词字段的 %d 个保留，写入失败的不摘）' % (
            len(want), args.tag, skipped_no_word))

    if not args.commit:
        if todo:
            ex = list(todo.items())[:8]
            print('  样例：%s' % '、'.join('%s(%s)->%s' % (n, words.get(n, '?'), v) for n, v in ex))
        else:
            print('无需变更。')
        print('\n演练结束，未写库。加 --commit 真写。')
        return 0

    # 写库
    done, written_ids, failed = 0, [], []
    for n, v in todo.items():
        try:
            AK.update_note_fields(n, {args.field: v})
            written_ids.append(n)
            done += 1
        except Exception as exc:                   # noqa: BLE001
            failed.append((n, str(exc)[:60]))
    print('已写入 %d / %d，失败 %d' % (done, len(todo), len(failed)))
    if failed:
        print('  失败样例：%s' % failed[:5])

    # 摘 tag：只有「值已经对」的才摘；有失败就整批不摘，避免把没补上的卡也清掉
    if args.remove_tag:
        if failed:
            print('有写入失败，这次不摘 tag：先修掉失败的卡，再跑一次。')
        else:
            ids = written_ids + ok_ids
            try:
                AK.remove_tags(ids, args.tag)
                left = AK.find_notes('tag:%s' % args.tag)
                print('已从 %d 个笔记摘掉 tag「%s」；该 tag 下还剩 %d 个' % (
                    len(ids), args.tag, len(left)))
            except Exception as exc:               # noqa: BLE001
                print('✗ 摘 tag 失败：%s' % exc)

    print('字段值格式：%%06d（补零，文本序=数值序）；%s = 词表里查不到、排在队尾'
          % args.no_rank)
    return 0


def _cmd_field_models(args) -> int:
    """全量回填：直接点名笔记类型，把它们的**全部**笔记按词表排名写进字段。

    与 ``--tag`` 的差别只在「选哪些笔记」：不需要 plan、不需要待办 tag、不摘任何
    tag。护栏与 ``--all-notes`` 相同（同步影响行、写前快照、写后调度列 diff、
    写后回读）。典型用法（Global 词表 -> JitenGlobalRank，两类词汇卡）：

        python code/analysis/vocab_cover/freq_external.py field \\
            --models vocab --media Global --field JitenGlobalRank \\
            --add-field --commit
    """
    models = _expand_models(args.models)
    if not models:
        print('✗ --models 没给出笔记类型')
        return 2

    index_path = _csv_path(args.media)
    if not os.path.exists(index_path):
        print('找不到 %s —— 先跑：python code/analysis/vocab_cover/freq_external.py '
              'download --media %s' % (os.path.relpath(index_path, WSP.ROOT), args.media))
        return 2
    index = load_index(index_path)
    print('Jiten 词表 %s：%d 个归一化键' % (
        os.path.relpath(index_path, WSP.ROOT), len(index)))
    print('目标笔记类型：%s' % '、'.join(models))

    known = set(AK.model_names())
    unknown = [m for m in models if m not in known]
    if unknown:
        print('✗ 库里没有这些笔记类型：%s' % '、'.join(unknown))
        return 2

    # 字段：缺就（--add-field + --commit）加上；否则不写空值，直接停
    missing = [m for m in models if args.field not in AK.model_field_names(m)]
    if missing:
        print('缺字段 %s 的笔记类型：%s' % (args.field, '、'.join(missing)))
        if not args.add_field:
            print('  加 --add-field 才会自动加；否则请先在 Anki 里手动加好这个字段')
            if args.commit:
                return 2
        elif args.commit:
            for m in missing:
                AK.call('modelFieldAdd', modelName=m, fieldName=args.field)
            still = [m for m in missing if args.field not in AK.model_field_names(m)]
            if still:
                print('✗ 加字段失败：%s' % '、'.join(still))
                return 2
            print('  已加字段（注意：Anki 会给这些类型的**全部**笔记补一个空字段，'
                  '同步量比写入数更大）')
        else:
            print('  （演练：加 --commit 才会真加）')

    # 收集：笔记里的词 -> 词表排名 -> 字段值；同时读当前值做幂等对照
    want, words, current = {}, {}, {}
    total_notes = skipped_no_word = 0
    for m in models:
        ids = AK.find_notes('note:"%s"' % m)
        print('  %s：%d 个笔记' % (m, len(ids)))
        for i in range(0, len(ids), 500):
            notes = AK.notes_info(ids[i:i + 500])
            total_notes += len(notes)
            w, wd, sk = derive_field_values(notes, index, args.no_rank)
            want.update(w)
            words.update(wd)
            skipped_no_word += sk
            for n in notes:
                current[int(n['noteId'])] = AK.field(n, args.field) or ''
    print('合计 %d 个笔记，查到词 %d 个（无词字段跳过 %d 个）'
          % (total_notes, len(want), skipped_no_word))

    todo = {n: v for n, v in want.items() if current.get(n) != v}
    print('需要写入/更新：%d 个（值已正确的跳过 %d 个）' % (len(todo), len(want) - len(todo)))
    print('同步影响：改 %d 个笔记 × 1 个字段（%s）→ 下次同步要传约 %d 个笔记'
          % (len(todo), args.field, len(todo)))
    miss = sorted({words[n] for n, v in todo.items() if v == args.no_rank})
    print('  词表未命中（写 %s）：%d 个%s' % (
        args.no_rank, len(miss), ('：' + '、'.join(miss[:20])) if miss else ''))

    if not todo:
        print('无需变更。')
        return 0
    if not args.commit:
        ex = list(todo.items())[:8]
        print('  样例：%s' % '、'.join('%s(%s)->%s' % (n, words.get(n, '?'), v) for n, v in ex))
        print('\n演练结束，未写库。加 --commit 真写。')
        return 0

    # 写前基准（全库写值得留一份快照）
    snap_path = _newest_fresh_snapshot()
    if snap_path:
        print('写前基准：复用 %s（%.1f 分钟前）'
              % (os.path.relpath(snap_path, WSP.ROOT),
                 (time.time() - os.path.getmtime(snap_path)) / 60.0))
    else:
        snap_path = _copy_live_snapshot()
        print('写前基准：现落一份快照 %s' % os.path.relpath(snap_path, WSP.ROOT))
    if snap_path and (time.time() - os.path.getmtime(snap_path)) > SNAP_FRESH_SECONDS:
        print('  ⚠ 这份基准超过 1 小时了，diff 可能混入之后的正常复习活动')

    done, failed = 0, []
    for n, v in todo.items():
        try:
            AK.update_note_fields(n, {args.field: v})
            done += 1
        except Exception as exc:                   # noqa: BLE001
            failed.append((n, str(exc)[:60]))
        if done and done % 2000 == 0:
            print('   ...%d' % done, flush=True)
    print('已写入 %d / %d，失败 %d' % (done, len(todo), len(failed)))
    if failed:
        print('  失败样例：%s' % failed[:5])

    # 写后回读（铁律 7）：只回读这次写过的笔记
    bad = AK.verify_note_fields({n: {args.field: v} for n, v in todo.items()}, settle=1.0)
    if bad:
        print('✗ 回读不一致：%d 个（样例 %s）' % (len(bad), list(bad.items())[:3]))
    else:
        print('✓ 回读一致：%d 个笔记的 %s' % (len(todo), args.field))

    # 写后自检：字段写**不应该**碰调度列
    if snap_path:
        _report_sched_diff(snap_path, list(todo))

    print('字段值格式：%%06d（补零，文本序=数值序）；%s = 词表里查不到、排在队尾'
          % args.no_rank)
    return 0 if not failed and not bad else 1


def cmd_field(args) -> int:
    """把 plan 里的 freq_rank 写成笔记字段（可选：先给笔记类型加这个字段）。

    为什么要有这个字段（以及它**不能**做什么）
    ----------------------------------------
    字段**不能**决定取卡顺序 —— Anki 的新卡队列顺序只有一个来源：``cards.due``
    （= 位置）。筛选牌组的 ``Filtered.SearchTerm.Order`` 和卡组的
    ``NewCardGatherPriority`` / ``NewCardSortOrder`` 两个枚举里都没有「按字段排」
    这一项，手册也写明 ``Reposition`` 才是「Change the order new cards will appear
    in」。所以字段是**注解**，排序仍然靠 ``activate.py`` 写 ``due``。

    它的用处：① 复习/浏览时看得见排名；② 可以建「只学排名 < N」的筛选牌组
    （regex 搜字段）；③ 排序依据留在库里，不依赖工作区脚本。

    ``--all-notes`` 的护栏（2026-10-10 加）
    -------------------------------------
    全库字段写会动上万个笔记（实测 16,649 个），是一次性的大同步 delta。所以：

    * 演练/真写都会打印**同步影响**行（改多少个笔记 → 下次同步要传多少）。
    * ``--commit`` 前先确保有一份**写前快照**（1 小时内的现成快照直接复用，
      否则现落一份 ``data/snapshots/pre_jiten_field_<时间戳>/``）。
    * 写完后用那份快照 diff 受影响卡片的**调度列**（due/ivl/factor/reps/lapses/
      queue/type），非零就大声告警 —— 字段写**不应该**碰到调度。

    ``--models``（2026-10-29 加）：同一个字段写，换成「按笔记类型全量回填」，
    不需要 plan、不需要待办 tag，护栏与 ``--all-notes`` 相同（快照 + 调度列 diff），
    并额外做写后回读。用于给两类词汇卡补 ``JitenGlobalRank``（Global 词表）。
    """
    # ---- --tag 路径：按 tag 查询笔记，按词查 Jiten 排名，写回字段 -------------
    if args.tag:
        if args.models:
            print('✗ --models 与 --tag 互斥：一次只走一条路')
            return 2
        return _cmd_field_tag(args)
    # ---- --models 路径：按笔记类型全量回填（不需要 plan / tag）-------------
    if args.models:
        if args.all_notes:
            print('✗ --models 与 --all-notes 互斥：--models 本身就是全量回填')
            return 2
        return _cmd_field_models(args)

    add_pylibs()
    import make_activate_plan as MAP  # AnkiConnect 调用只此一份

    plan = json.load(open(args.plan, encoding='utf-8'))
    targets = plan['targets']
    want = {}
    for t in targets:
        r = t.get('freq_rank')
        # 补零成 6 位：浏览器按字段排序是**文本序**，补零后文本序 == 数值序
        want[t['noteId']] = ('%06d' % r) if r else args.no_rank
    print('计划 %s：%d 张卡 -> %d 个笔记' % (
        os.path.relpath(args.plan, WSP.ROOT), len(targets), len(want)))

    # 取笔记的类型名 + 该字段当前值（顺带做幂等判断，值一样就不重写、不动 mod）
    models, current = set(), {}
    nids = list(want)
    for i in range(0, len(nids), 200):
        for n in MAP.ac('notesInfo', notes=nids[i:i + 200]) or []:
            models.add(n['modelName'])
            current[n['noteId']] = (n.get('fields', {}).get(args.field) or {}).get('value')
    print('涉及笔记类型 %d 个：%s' % (len(models), '、'.join(sorted(models))))

    missing = [m for m in sorted(models) if args.field not in MAP.ac('modelFieldNames', modelName=m)]
    if missing:
        print('缺字段 %s 的笔记类型：%s' % (args.field, '、'.join(missing)))
        if args.add_field:
            if args.commit:
                for m in missing:
                    MAP.ac('modelFieldAdd', modelName=m, fieldName=args.field)
                print('  已添加字段（注意：Anki 会给这些类型的**全部**笔记补一个空字段，'
                      '同步量会比你写的笔记数更多）')
            else:
                print('  （演练：加 --commit 才会真加）')
        else:
            print('  加 --add-field 才会自动加；否则请手动加，或（--commit 时）会全部写成空值')
            if args.commit:
                return 2

    # --all-notes：把这几个笔记类型下的**全部**笔记都写上（含已学过的旧卡）。
    # 旧卡不在 plan 里，所以要按「笔记里的词 → 词表排名」重新查；顺带与 plan 对一遍当自检。
    skipped_no_word = 0
    if args.all_notes:
        wl = args.words_file or _plan_path(args.media)
        index = {norm_word(r['word']): r['freq_rank']
                 for r in json.load(open(wl, encoding='utf-8'))}
        print('词表 %s：%d 个归一化键' % (os.path.relpath(wl, WSP.ROOT), len(index)))
        alln = []
        for m in sorted(models):
            got = MAP.ac('findNotes', query='note:"%s"' % m)
            print('  %s：%d 个笔记' % (m, len(got)))
            alln.extend(got)
        derived, mismatch = {}, 0
        # 「词」在哪个字段按笔记类型的惯例取；其余退回 make_activate_plan.WORD_FIELDS 的顺序。
        # 刻意不做「取第一个非空字段」的兜底：eggrolls 那种 36 字段的卡会抓到
        # NoteID / VocabDefSC 之类的垃圾。
        KNOWN_WORD_FIELD = {
            'Japanese Vocabulary': ('Word',),
            'eggrolls-JLPT10k-v3.5': ('VocabKanji',),
        }
        for i in range(0, len(alln), 200):
            for n in MAP.ac('notesInfo', notes=alln[i:i + 200]) or []:
                fields = {k: (v.get('value') or '') for k, v in n['fields'].items()}
                # 幂等判断要用**全部**笔记的当前值：上面那次 notesInfo 只覆盖了 plan 里的
                # 11,990 个，若不复用这一趟，旧卡每次重跑都会被再写一遍（白涨 mod）。
                current[n['noteId']] = fields.get(args.field, '')
                cand = KNOWN_WORD_FIELD.get(n['modelName'], MAP.WORD_FIELDS)
                word = next((fields[f] for f in cand if fields.get(f)), '')
                if not word:
                    skipped_no_word += 1
                    continue
                rank = index.get(norm_word(primary_form(word)))
                derived[n['noteId']] = ('%06d' % rank) if rank else args.no_rank
                if n['noteId'] in want and derived[n['noteId']] != want[n['noteId']]:
                    mismatch += 1
        print('  全部笔记 %d -> 查到词的 %d（无词字段跳过 %d）'
              % (len(alln), len(derived), skipped_no_word))
        print('  与 plan 的值逐条对照：不一致 %d 个（应为 0，否则说明两套推导不同源）' % mismatch)
        want = derived

    todo = {n: v for n, v in want.items() if current.get(n) != v}
    print('需要写入/更新：%d 个（值已正确的跳过 %d 个）' % (len(todo), len(want) - len(todo)))
    # 同步影响：Anki 同步以**笔记**为单位；值没变的已跳过，不会重复上传 mod
    print('同步影响：改 %d 个笔记 × 1 个字段（%s）→ 下次同步要传约 %d 个笔记'
          % (len(todo), args.field, len(todo)))
    if args.all_notes:
        print('          ⚠ --all-notes 是全库写：这几个笔记类型的全部笔记都在这条推导路上')
    if not todo:
        print('无需变更。')
        return 0
    if not args.commit:
        ex = list(todo.items())[:8]
        print('  样例：%s' % '、'.join('%s->%s' % (n, v) for n, v in ex))
        print('\n演练结束，未写库。加 --commit 真写。')
        return 0

    # ---- 写前基准（--all-notes 才做：全库写值得留一份快照）
    snap_path = None
    if args.all_notes:
        snap_path = _newest_fresh_snapshot()
        if snap_path:
            print('写前基准：复用 %s（%.1f 分钟前）'
                  % (os.path.relpath(snap_path, WSP.ROOT),
                     (time.time() - os.path.getmtime(snap_path)) / 60.0))
        else:
            snap_path = _copy_live_snapshot()
            print('写前基准：现落一份快照 %s' % os.path.relpath(snap_path, WSP.ROOT))
        if snap_path and (time.time() - os.path.getmtime(snap_path)) > SNAP_FRESH_SECONDS:
            print('  ⚠ 这份基准超过 1 小时了，diff 可能混入之后的正常复习活动')

    done, failed = 0, []
    for n, v in todo.items():
        try:
            MAP.ac('updateNoteFields', note={'id': n, 'fields': {args.field: v}})
            done += 1
        except Exception as exc:
            failed.append((n, str(exc)[:60]))
        if done and done % 2000 == 0:
            print('   ...%d' % done, flush=True)
    print('已写入 %d / %d，失败 %d' % (done, len(todo), len(failed)))
    if failed:
        print('  失败样例：%s' % failed[:5])

    # ---- 写后自检：字段写**不应该**碰调度列
    if snap_path:
        _report_sched_diff(snap_path, list(todo))

    print('字段值格式：%%06d（补零，文本序=数值序）；%s = 词表里查不到、排在队尾'
          % args.no_rank)
    return 0


# --------------------------------------------------------------- 4. compare

def corpus_freq(corpus: dict):
    """与 study_plan.corpus_freq 同一算法：word_counts 的元组以次数打头。"""
    freq = collections.Counter()
    works = collections.defaultdict(set)
    for ep in corpus['episodes']:
        for w, (n, *_rest) in ep['word_counts'].items():
            freq[w] += n
            works[w].add(ep.get('work'))
    return freq, works


def cmd_compare(args) -> int:
    add_pylibs()
    import make_activate_plan as MAP  # 卡组口径、字段名、AnkiConnect 只此一份

    plan_path = args.words_file or _plan_path(args.media)
    index = {}
    for r in json.load(open(plan_path, encoding='utf-8')):
        index[norm_word(r['word'])] = r['freq_rank']
    print('外部词表 %s：%d 个归一化键' % (os.path.relpath(plan_path, WSP.ROOT), len(index)))

    state = json.load(open(os.path.join(DATA_DIR, 'vocab_state.json'), encoding='utf-8'))['words']
    corpus = json.load(open(os.path.join(DATA_DIR, 'corpus_tokens.json'), encoding='utf-8'))
    freq, works_of = corpus_freq(corpus)
    total_tokens = sum(freq.values())

    # ---- A. 覆盖：外部词表能不能给你的词排上名
    def cover(words):
        hit = sum(1 for w in words if norm_word(w) in index)
        return {'n': len(words), 'hit': hit, 'rate': hit / max(1, len(words))}

    cov_all = cover(list(state))
    cov_known = cover([w for w, e in state.items() if e['known']])
    cov_unknown = cover([w for w, e in state.items() if not e['known']])
    cov_corpus = cover(list(freq))

    # live 新卡池（只读 AnkiConnect）
    live = {'n': 0, 'hit': 0, 'rate': 0.0, 'note': 'AnkiConnect 不可用，跳过'}
    live_keys = []
    if not args.no_anki:
        try:
            live_index = MAP.collect_new_cards()
            live_keys = list(live_index)
            hit = sum(1 for k in live_keys if k in index)
            live = {'n': len(live_keys), 'hit': hit, 'rate': hit / max(1, len(live_keys)),
                    'note': 'live 新卡（type==0，core6000/考级/素材生词 三组）'}
        except Exception as exc:  # 报告不该因为 Anki 没开着就废掉
            live = {'n': 0, 'hit': 0, 'rate': 0.0, 'error': str(exc)[:200],
                    'note': 'AnkiConnect 连接失败'}

    # ---- B. 候选池：卡组内未学、但素材里出现过（= study_plan_critical_path.json 的口径）
    crit = sorted(((w, freq[w]) for w, e in state.items()
                   if (e['core'] or e['jlpt'] or e['mined']) and not e['known'] and freq.get(w)),
                  key=lambda t: -t[1])
    crit_cov = cover([w for w, _ in crit])
    matched = [(w, n, index[norm_word(w)]) for w, n in crit if norm_word(w) in index]

    # ---- C. 同池两序：本地素材频率 vs Jiten 排名
    def seg_stats(seg):
        tok = sum(freq.get(w, 0) for w in seg)
        multi = sum(1 for w in seg if len(works_of.get(w) or ()) >= 2)
        seen = sum(1 for w in seg if freq.get(w))
        return {'n': len(seg), 'token_cover': tok / max(1, total_tokens),
                'hit_rate': seen / max(1, len(seg)),
                'multi_work_rate': multi / max(1, len(seg))}

    by_local = [w for w, _n in crit]
    by_ext = [w for w, _n, _r in sorted(matched, key=lambda t: t[2])]
    table = []
    for n in (args.ns or [100, 300, 500, 1000]):
        a = seg_stats(by_local[:n])
        b = seg_stats(by_ext[:n])
        table.append({'n': n, 'local': a, 'external': b,
                      'token_cover_delta': a['token_cover'] - b['token_cover']})

    # ---- D. 两序相关（交集上）：本地次数越多、Jiten 排名越小 -> 期望**负**相关
    # 取法对齐 study_plan.py 的口径（那边报的是「Index 与素材频次」= -0.42）。
    rho_freq = spearman([n for _w, n, _r in matched], [r for _w, _n, r in matched])

    # ---- E. 决定性的那一半：本地序**排不了**的存量新卡
    # 本地清单只覆盖「在这 36 集里出现过」的词；没出现过的次数一律为 0、无法区分先后，
    # make_activate_plan.py 也就完全够不着它们。外部词表对这部分同样能排序。
    queue = {'live_total': 0, 'in_corpus': 0, 'not_in_corpus': 0,
             'not_in_corpus_with_rank': 0, 'note': '需要 AnkiConnect'}
    if live_keys:
        in_c = [k for k in live_keys if freq.get(k)]
        not_c = [k for k in live_keys if not freq.get(k)]
        queue = {'live_total': len(live_keys), 'in_corpus': len(in_c), 'not_in_corpus': len(not_c),
                 'not_in_corpus_with_rank': sum(1 for k in not_c if k in index),
                 'note': 'live 新卡按「是否出现在 36 集语料」拆分'}

    result = {
        'generated_at': _now(), 'media': args.media,
        'source': os.path.relpath(plan_path, WSP.ROOT).replace('\\', '/'),
        'index_size': len(index), 'license': LICENSE,
        'coverage': {'state_all': cov_all, 'state_known': cov_known,
                     'state_unknown': cov_unknown, 'corpus_words': cov_corpus,
                     'live_new_cards': live},
        'critical_pool': {'n': crit_cov['n'], 'jiten_ranked': crit_cov['hit'],
                          'rate': crit_cov['rate']},
        'order_agreement': {'spearman_local_freq_vs_jiten_rank': rho_freq,
                            'n_pairs': len(matched)},
        'queue_reach': queue,
        'top_n': table,
        'total_vocab_tokens': total_tokens,
    }
    out = os.path.join(DATA_DIR, 'freq_compare_%s.json' % _slug(args.media))
    write_json(result, out)

    # ---- 人读报告
    md = _render_md(result, crit, by_ext, freq, works_of, index)
    mdp = os.path.join(WSP.REPORTS, '外部词表排序对比.md')
    with open(mdp, 'w', encoding='utf-8') as fh:
        fh.write(md)

    # ---- 控制台（纯 ASCII，日文写进报告里看）
    print()
    print('A. coverage of Jiten index')
    for k, v in result['coverage'].items():
        print('   %-16s %6d / %-6d  %5.1f%%' % (k, v['hit'], v['n'], v['rate'] * 100))
    print('B. critical pool  %d words, ranked by Jiten: %d (%.1f%%)' % (
        crit_cov['n'], crit_cov['hit'], crit_cov['rate'] * 100))
    print('C. order agreement (Spearman local-freq vs Jiten-rank): %.3f  n=%d' % (
        rho_freq, len(matched)))
    print('   (negative = agree in direction; compare with core6000 Index vs corpus = -0.42)')
    print('D. same pool, top-N:  local-first vs Jiten-first')
    print('   %6s %10s %10s %10s   %9s %9s' % ('N', 'local_cov', 'jiten_cov', 'delta',
                                              'loc_multi', 'jit_multi'))
    for row in table:
        print('   %6d %9.1f%% %9.1f%% %9.1f%%   %8.1f%% %8.1f%%' % (
            row['n'], row['local']['token_cover'] * 100, row['external']['token_cover'] * 100,
            row['token_cover_delta'] * 100, row['local']['multi_work_rate'] * 100,
            row['external']['multi_work_rate'] * 100))
    print('E. live new-card queue reach')
    q = result['queue_reach']
    print('   total %d | in 36-ep corpus %d (local list can rank these) | not in corpus %d'
          % (q['live_total'], q['in_corpus'], q['not_in_corpus']))
    print('   of the "not in corpus" ones, Jiten can rank: %d (%.1f%%) -- local list: 0'
          % (q['not_in_corpus_with_rank'],
             100.0 * q['not_in_corpus_with_rank'] / max(1, q['not_in_corpus'])))
    print()
    print('written -> %s' % os.path.relpath(out, WSP.ROOT))
    print('written -> %s' % os.path.relpath(mdp, WSP.ROOT))
    return 0


def _render_md(res, crit, by_ext, freq, works_of, index) -> str:
    by_local = [w for w, _n in crit]
    L = []
    A = L.append
    c = res['coverage']
    A('# 外部词表排序对比：Jiten %s vs 本地 36 集字幕' % res['media'])
    A('')
    A('> 生成时间 %s · 词表 `%s`（%d 键，许可 %s）'
      % (res['generated_at'], res['source'], res['index_size'], res['license']))
    A('> 语料仍为本工作区 36 集字幕（%d 个词元）；只读分析，未改任何 Anki 数据。'
      % res['total_vocab_tokens'])
    A('')
    A('## 1. 外部词表覆盖得了你多少词')
    A('')
    A('| 范围 | 有 Jiten 排名 | 总数 | 覆盖率 |')
    A('|---|---|---|---|')
    for k, label in (('state_all', 'Anki 全部词（vocab_state）'), ('state_known', '　其中已学'),
                     ('state_unknown', '　其中未学'), ('corpus_words', '36 集语料里的词'),
                     ('live_new_cards', 'live 新卡池（当前可发的）')):
        v = c[k]
        A('| %s | %d | %d | %.1f%% |' % (label, v['hit'], v['n'], v['rate'] * 100))
    if c['live_new_cards'].get('note'):
        A('')
        A('live 新卡池口径：%s。' % c['live_new_cards']['note'])
    A('')
    A('## 2. 候选池（卡组内未学 ∧ 素材出现过）')
    A('')
    A('* 候选池 **%d** 个词，其中 **%d** 个（%.1f%%）在 Jiten 里有排名。'
      % (res['critical_pool']['n'], res['critical_pool']['jiten_ranked'],
         res['critical_pool']['rate'] * 100))
    A('* 这个池子上，本地素材频率与 Jiten 排名的 **Spearman 秩相关 = %.3f**（n=%d）。'
      % (res['order_agreement']['spearman_local_freq_vs_jiten_rank'],
         res['order_agreement']['n_pairs']))
    A('  **负值 = 方向一致**（本地次数越多、Jiten 排名越靠前）。绝对值越大越一致；')
    A('  参考：core6000 的 Index 与本地素材频次的秩相关是 **-0.42** —— 两套外部顺序')
    A('  与本地语料的贴合度是同一量级，都只是中等，谁也不是谁的强代理。')
    A('')
    q = res['queue_reach']
    A('## 3. 外部词表真正多出来的那块：本地序排不了的长尾队列')
    A('')
    A('本地清单只覆盖「在这 36 集里出现过」的词。没出现过的词次数一律为 0、无法区分先后，')
    A('`make_activate_plan.py` 完全够不着它们 —— 而这批卡占现在可发新卡的绝大多数。')
    A('')
    A('| | 张数 |')
    A('|---|---|')
    A('| live 新卡池合计 | %d |' % q['live_total'])
    A('| 　在 36 集语料里出现过（本地序能排） | %d |' % q['in_corpus'])
    A('| 　**没出现过（本地序排不了）** | **%d** |' % q['not_in_corpus'])
    A('| 　　└ 其中 Jiten 能给排名的 | %d（%.1f%%） |'
      % (q['not_in_corpus_with_rank'],
         100.0 * q['not_in_corpus_with_rank'] / max(1, q['not_in_corpus'])))
    A('')
    A('## 4. 同一批候选，两种排序取前 N')
    A('')
    A('`local_cov` = 这批词覆盖本语料多少词元。**注意这一项对本地序有利是结构性的**：')
    A('本地序就是在被评的这个语料上算出来的，它在自己语料上必然占优。')
    A('`delta` = 换成 Jiten 序后损失的覆盖率（= 换序的机会成本）；')
    A('`multi` = 这批词里出现在 ≥2 部作品的比例。')
    A('')
    A('| N | 本地序覆盖 | Jiten 序覆盖 | 损失 | 本地序 multi | Jiten 序 multi |')
    A('|---|---|---|---|---|---|')
    for row in res['top_n']:
        A('| %d | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %.1f%% |' % (
            row['n'], row['local']['token_cover'] * 100, row['external']['token_cover'] * 100,
            row['token_cover_delta'] * 100, row['local']['multi_work_rate'] * 100,
            row['external']['multi_work_rate'] * 100))
    A('')
    A('> `multi` 这一列**不能**当成「泛化性」的证据读：本地语料只有 3 部作品，')
    A('> 「出现在 ≥2 部」更接近「在你这 3 部里都常出现」，而不是「在动画里普遍常见」。')
    A('> 它偏低只说明 Jiten 会推荐「动画里普遍常见、但在你这 3 部里只出现 1 部」的词 ——')
    A('> 那恰恰是本地序看不见的信息，不是它的缺点。')
    A('')
    A('## 5. 两个排序各自的前 20 个词')
    A('')
    A('| # | 本地素材频率序 | 本地次数 | Jiten 排名序 | Jiten 排名 |')
    A('|---|---|---|---|---|')
    for i in range(20):
        lw = by_local[i] if i < len(by_local) else ''
        ln = freq.get(lw, 0) if lw else ''
        ew = by_ext[i] if i < len(by_ext) else ''
        er = index.get(norm_word(ew)) if ew else ''
        A('| %d | %s | %s | %s | %s |' % (i + 1, lw, ln, ew, er))
    A('')
    A('## 6. 本地序排前面、但只出现在 1 部作品里的词（单集噪声）')
    A('')
    A('这些词在本地语料里次数不低，但只来自 1 部作品 —— 本地序会把它们顶到前面，')
    A('而它们对「看下一部动画」几乎没有泛化价值。Jiten 排名一列可以对比它怎么看这些词。')
    A('')
    A('| 词 | 本地次数 | 出现在几部作品 | Jiten 排名 |')
    A('|---|---|---|---|')
    shown = 0
    for w, n in crit:
        if shown >= 15:
            break
        nw = len(works_of.get(w) or ())
        if nw >= 2:
            continue
        A('| %s | %d | %d | %s |' % (w, n, nw, index.get(norm_word(w), '—')))
        shown += 1
    A('')
    return '\n'.join(L) + '\n'


# --------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description='外部词表（Jiten）当排序源')
    sub = ap.add_subparsers(dest='cmd', required=True)

    d = sub.add_parser('download', help='下载 Jiten 词频表 CSV')
    d.add_argument('--media', default='Anime', help=MEDIA_HELP)
    d.add_argument('--force', action='store_true', help='已存在也重下')
    d.add_argument('--timeout', type=int, default=180)
    d.set_defaults(func=cmd_download)

    b = sub.add_parser('build', help='归一化合并键 -> study_plan_<media>.json')
    b.add_argument('--media', default='Anime', help=MEDIA_HELP)
    b.add_argument('--out', default=None)
    b.add_argument('--top', type=int, default=0, help='只保留前 N 条（0=全部）')
    b.add_argument('--max-rank', type=int, default=0, help='丢弃排名大于 N 的（0=不丢）')
    b.set_defaults(func=cmd_build)

    f = sub.add_parser('field', help='把词表排名写成笔记字段（注解，不做排序）')
    f.add_argument('--plan', default=None,
                   help='默认 data/plans/plan_activate_jiten.json')
    f.add_argument('--field', default='JitenAnimeRank', help='字段名')
    f.add_argument('--media', default='Anime', help=MEDIA_HELP + '（--all-notes / --models 用它找词表）')
    f.add_argument('--words-file', default=None,
                   help='--all-notes 用的词表；默认 study_plan_jiten_<media>.json')
    f.add_argument('--models', nargs='+', default=None, metavar='MODEL',
                   help='全量回填：直接点名笔记类型，把这些类型的**全部**笔记按词表排名'
                        '写进字段；不需要 plan，与 --tag / --plan / --all-notes 互斥。'
                        '`--models vocab` 是 "Japanese Vocabulary" + '
                        '"eggrolls-JLPT10k-v3.5" 的简写')
    f.add_argument('--all-notes', action='store_true',
                   help='把这几个笔记类型下的**全部**笔记都写上（含已学过的旧卡——'
                        '旧卡不在 plan 里，改按「笔记里的词 → 词表排名」重新查）')
    f.add_argument('--tag', default=None,
                   help='按 Anki tag 查询笔记（如 tag:需更新JAR），仅更新命中的笔记；'
                        '与 --plan / --all-notes 互斥。词从笔记的词字段读出，查 Jiten 排名后写回。'
                        '旧名 tag:需要更新jitenrank的卡片 同名可用。')
    f.add_argument('--remove-tag', action='store_true',
                   help='写完把这批笔记上的该 tag 摘掉（待办标记已完成即摘）；'
                        '无词字段的笔记与写入失败的笔记保留 tag')
    f.add_argument('--no-rank', default='999999',
                   help='词表里查不到的卡的字段值（默认 999999，文本序排最后）')
    f.add_argument('--add-field', action='store_true',
                   help='缺字段时自动给笔记类型加上（会给该类型全部笔记补空字段）')
    f.add_argument('--commit', action='store_true', help='真写库（不加则只演练）')
    f.set_defaults(func=cmd_field)

    c = sub.add_parser('compare', help='只读对比：覆盖率、秩相关、前 N 损失')
    c.add_argument('--media', default='Anime', help=MEDIA_HELP)
    c.add_argument('--words-file', default=None, help='默认 study_plan_<media>.json')
    c.add_argument('--ns', type=int, nargs='*', default=[100, 300, 500, 1000])
    c.add_argument('--no-anki', action='store_true', help='跳过 live 新卡池')
    c.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
