# -*- coding: utf-8 -*-
"""ImmersionKit 全量分批驱动 —— 把词表切成小块，逐块跑完 fetch → gen → write → verify。

为什么必须切块：``immersionkit.cmd_fetch`` 只在**整轮跑完后**才落盘一次计划
（``code/execution/immersionkit.py:264``），1,900 个词要跑 ~1.6 小时，中途断掉
整轮白跑。切成 150 词一块（约 8 分钟），每块独立落盘、独立写库，断了只丢当前块。

每块的动作（全部走 ``code/execution/immersionkit.py`` 的同一套 CLI 入口，
不另写一套口径）：

1. ``fetch --words-file <块词表>``  选句出计划（含振假名闸门，优先挑对得上的句子）
2. ``gen``                          本地模型出 读音/词性/释义/中文翻译/讲解
3. ``write --to both --commit --no-order``  落地媒体（原声+截图）并建卡，逐字段回读
   （``--no-order``：本机 AnkiConnect 写不了 ``due``，新素材卡的位置由 Anki 插件
   ``jiten_reorder`` 在 Anki 进程内排 —— 见 docs/decisions/2026-10-jitenanimerank仅作注解.md）
4. ``verify --written <刚写的那份>`` 只读校验（字段/振假名/媒体）

标签口径（2026-10-17）：例句卡 ``动画::<中文名>`` / ``日剧::<中文名>``，素材卡裸 ``素材生词``
（中文名查 data/evidence/immersion_retag/slug_map.yaml；未映射的先用英文 slug 顶着，
清单落在 data/immersion/unmapped_slugs.txt）。

进度写 ``data/immersion/batch_progress.json``：重跑时已完成的块直接跳过（断点续跑）。
**一批一个进度文件**（``--progress``）：共用会让新词表的前几块被误判成「已完成」。
"""
import argparse
import datetime as dt
import glob
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'execution'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))

import immersionkit as IK       # noqa: E402
import anki_api as AK           # noqa: E402
import paths as WSP             # noqa: E402
import textio                   # noqa: E402

DATA = WSP.DATA_IMMERSION
CHUNK_DIR = os.path.join(DATA, 'chunks')
PROGRESS = os.path.join(DATA, 'batch_progress.json')


def stamp():
    return dt.datetime.now().strftime('%Y%m%d-%H%M%S')


def read_words(path):
    out = []
    for line in textio.read_text(path).splitlines():
        line = line.split('#')[0].strip()
        if line:
            out.append(line.split('\t')[0].strip())
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq


def load_progress(path):
    if os.path.exists(path):
        try:
            import json
            return json.loads(textio.read_text(path))
        except Exception:
            pass
    return {'chunks': {}}


def save_progress(path, prog):
    import json
    prog['updated'] = dt.datetime.now().isoformat(timespec='seconds')
    textio.write_text(path, json.dumps(prog, ensure_ascii=False, indent=1) + '\n')


def newest(pattern):
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else ''


def log(msg):
    print('[%s] %s' % (dt.datetime.now().strftime('%H:%M:%S'), msg), flush=True)


def wait_anki(minutes=120, poll=30):
    """等 AnkiConnect 可用。Anki 关着的时候**不要**继续跑块 —— 否则每个块都会
    「瞬时失败」被记成 error，一口气把几十个块烧完（2026-10-16 实测）。"""
    t0 = time.time()
    while time.time() - t0 < minutes * 60:
        try:
            if AK.health().get('ok'):
                if time.time() - t0 > 5:
                    log('AnkiConnect 回来了，继续')
                return True
        except Exception:                                # noqa: BLE001
            pass
        log('AnkiConnect 不可用（Anki 没开或正忙）→ 等 %d 秒' % poll)
        time.sleep(poll)
    return False


def parse_windows(specs):
    """``HH:MM-HH:MM`` → [(起始分钟, 结束分钟)]（跨零点支持，相等＝全天）。"""
    out = []
    for s in specs or []:
        try:
            lo, hi = str(s).split('-')
            h1, m1 = [int(x) for x in lo.strip().split(':')]
            h2, m2 = [int(x) for x in hi.strip().split(':')]
        except Exception:                                # noqa: BLE001
            raise SystemExit('--pause-window 格式应为 HH:MM-HH:MM，收到：%s' % s)
        out.append(((h1 * 60 + m1) % 1440, (h2 * 60 + m2) % 1440))
    return out


def in_window(windows, now=None):
    t = now or dt.datetime.now()
    cur = t.hour * 60 + t.minute
    for lo, hi in windows:
        if lo == hi:
            return True
        if lo < hi:
            if lo <= cur < hi:
                return True
        elif cur >= lo or cur < hi:
            return True
    return False


def minutes_until_window(windows, now=None):
    """距下一个暂停窗口开始还有几分钟（返回 None＝没配窗口）。"""
    if not windows:
        return None
    t = now or dt.datetime.now()
    cur = t.hour * 60 + t.minute
    return min(((lo - cur) % 1440) or 1440 for lo, _hi in windows)


def est_chunk_minutes(prog, chunk_words, default=25.0):
    """按历史记录估一块要多久（分钟/词 × 本块词数）。t_total 是**秒**。"""
    ts = [(v.get('t_total'), v.get('words')) for v in (prog.get('chunks') or {}).values()
          if v.get('status') == 'done' and v.get('t_total') and v.get('words')]
    if not ts:
        return default
    rate = sum(t for t, _w in ts) / max(1, sum(w for _t, w in ts)) / 60.0   # 秒/词 → 分/词
    return max(2.0, rate * chunk_words)


def run_pipeline(a, chunks, tag, prog, windows):
    """流水线跑法（`--pipeline`）：**下载与生成不再串着等**。

    用户 2026-10-16 的要求：「下载音频/anki 卡牌的任务可以和卡片生成任务并列运行，
    卡牌的下载提前一个块运行，AI 生成注解处理之前下载的组块」。于是分两端：

    * **生产端**（一个线程）：只跑 `fetch`（选词选句，网络 + 磁盘缓存）；
      它跑到第 N+1 块时，消费端还在处理第 N 块 —— fetch 与本地模型并行。
    * **消费端**（主线程）：`prewarm`（下媒体）**与** `gen`（本地模型注解）**并行**，
      两者都好了再 `write --commit`（媒体已 cached，write 只剩 addNotes）→ `verify`。

    文件竞争避免：消费端一律用 `--in <明确路径>`，不读 `latest.json`；
    `fetch_*.json` 只有生产端写、`plan_*.json`/`written_*.json` 只有消费端写，
    所以 `newest()` 探到的必是自己那一份。
    """
    import queue
    import threading

    q = queue.Queue()
    pending = []
    grand = {'words': 0, 'notes': 0, 'problems': 0, 'fallback': 0, 'skip': 0}
    for i, batch in enumerate(chunks, 1):
        key = 'chunk_%03d' % i
        if a.only and i != a.only:
            continue
        if i < a.start:
            continue
        old = prog['chunks'].get(key) or {}
        if old.get('status') == 'done' and not a.redo:
            log('%s 已完成（%d 词，%d 张卡）→ 跳过'
                % (key, old.get('words', 0), old.get('notes', 0)))
            grand['words'] += old.get('words', 0)
            grand['notes'] += old.get('notes', 0)
            grand['problems'] += old.get('verify_problems', 0)
            grand['skip'] += 1
            continue
        pending.append((i, key, batch))

    if not pending:
        log('没有待跑的块。')
        return 0

    halt = {'code': None}

    def preflight(i, batch):
        """开跑前的三件事：没按暂停 → 不在学习时段 → Anki 就绪。"""
        while True:
            if os.path.exists(a.stop_file):
                log('发现 STOP 文件（%s）→ 干净停下；删掉它重跑同一命令即续'
                    % os.path.relpath(a.stop_file, WSP.ROOT))
                return 5
            if in_window(windows):
                log('在暂停窗口内 → 睡 60 秒，不碰 Anki')
                time.sleep(60)
                continue
            need = a.min_headroom_minutes or est_chunk_minutes(prog, len(batch))
            left = minutes_until_window(windows)
            if left is not None and left < need:
                log('距暂停窗口只剩 %.0f 分钟（开一块要约 %.0f 分钟）→ 先停'
                    % (left, need))
                return 4
            if not wait_anki(a.anki_wait_minutes):
                log('Anki 一直没回来 → 先停（进度已存，重跑同一命令即续）')
                return 3
            if in_window(windows) or (left is not None
                                      and minutes_until_window(windows) < need):
                continue
            return None

    def producer():
        """只做 fetch：跑在第 N+1 块，与消费端的第 N 块并行。"""
        try:
            for i, key, batch in pending:
                code = preflight(i, batch)
                if code is not None:
                    halt['code'] = code
                    break
                chunk_file = os.path.join(CHUNK_DIR, '%s_%s.txt' % (tag, key))
                textio.write_text(chunk_file,
                                  '# %s：%d 个词\n' % (key, len(batch))
                                  + '\n'.join(batch) + '\n')
                log('')
                log('---- %s ｜%d 个词（%d/%d）｜ 生产端 fetch ----'
                    % (key, len(batch), i, len(chunks)))
                t0 = time.time()
                argv_f = ['fetch', '--words-file', chunk_file, '--n', str(a.n)]
                if a.keep_known:
                    argv_f.append('--keep-known')
                try:
                    IK.main(argv_f)
                except SystemExit as exc:
                    q.put(('chunk', i, key, batch, chunk_file, None,
                           round(time.time() - t0, 1), 'SystemExit %s' % exc))
                    continue
                except Exception as exc:                # noqa: BLE001
                    q.put(('chunk', i, key, batch, chunk_file, None,
                           round(time.time() - t0, 1),
                           '%s: %s' % (type(exc).__name__, exc)))
                    continue
                q.put(('chunk', i, key, batch, chunk_file,
                       newest(os.path.join(DATA, 'fetch_*.json')),
                       round(time.time() - t0, 1), None))
        finally:
            q.put(('end',))

    th = threading.Thread(target=producer, name='producer')
    th.daemon = True
    th.start()

    while True:
        item = q.get()
        if item[0] == 'end':
            break
        _tag, i, key, batch, chunk_file, fetch_plan, t_fetch, fetch_err = item
        if halt['code'] is not None:
            log('%s 已 fetch 但收到停止信号 → 丢弃（结果在缓存里，重跑近乎零成本）' % key)
            continue
        rec = {'i': i, 'words': len(batch), 'file': chunk_file,
               't_fetch': t_fetch, 'fetch_plan': fetch_plan or ''}
        for attempt in (1, 2):
            t_total = time.time()
            try:
                if fetch_err:
                    raise SystemExit('fetch 失败：%s' % fetch_err)
                # ① 媒体预下 ∥ ② 本地模型注解（用户要求并列跑）
                box = {}

                def _warm(plan=fetch_plan, box=box):
                    t = time.time()
                    try:
                        IK.main(['prewarm', '--in', plan])
                        box['t'] = round(time.time() - t, 1)
                    except SystemExit as exc:
                        box['err'] = str(exc)
                    except Exception as exc:            # noqa: BLE001
                        box['err'] = '%s: %s' % (type(exc).__name__, exc)

                warm = threading.Thread(target=_warm, name='prewarm')
                warm.daemon = True
                warm.start()
                t0 = time.time()
                IK.main(['gen', '--quiet', '--in', fetch_plan])
                rec['t_gen'] = round(time.time() - t0, 1)
                warm.join()
                rec['t_prewarm'] = box.get('t')
                if box.get('err'):
                    rec['prewarm_error'] = box['err']
                    log('   ⚠ 预下媒体有错（write 里还会再试一次）：%s' % box['err'])

                rec['gen_plan'] = newest(os.path.join(DATA, 'plan_*.json'))
                before = set(glob.glob(os.path.join(DATA, 'written_*.json')))
                t0 = time.time()
                argv_w = ['write', '--to', a.to, '--in', rec['gen_plan'], '--no-order'] + (
                    [] if a.dry_run else ['--commit'])
                IK.main(argv_w)
                rec['t_write'] = round(time.time() - t0, 1)
                new = set(glob.glob(os.path.join(DATA, 'written_*.json'))) - before
                rec['written'] = max(new, key=os.path.getmtime) if new else ''
                if a.dry_run or not rec['written']:
                    rec['notes'] = 0
                    rec['verify_problems'] = 0
                else:
                    t0 = time.time()
                    rc = IK.main(['verify', '--written', rec['written']])
                    rec['t_verify'] = round(time.time() - t0, 1)
                    rec['verify_rc'] = rc
                    import json
                    w = json.loads(textio.read_text(rec['written']))
                    rec['notes'] = len(w.get('notes') or [])
                    rec['verify_problems'] = 1 if rc else 0
                rec['status'] = 'done'
            except SystemExit as exc:
                rec['status'] = 'error'
                rec['error'] = 'SystemExit %s' % exc
                log('   ✗ %s：%s' % (key, rec['error']))
            except Exception as exc:                    # noqa: BLE001
                rec['status'] = 'error'
                rec['error'] = '%s: %s' % (type(exc).__name__, exc)
                log('   ✗ %s：%s' % (key, rec['error']))
            rec['t_total'] = round(time.time() - t_total, 1)
            if rec['status'] == 'error' and rec['t_total'] < 30 and attempt == 1:
                log('   瞬时失败（%.1fs）→ 等 Anki 回来重试本块' % rec['t_total'])
                wait_anki(a.anki_wait_minutes)
                continue
            break
        try:
            import json
            st = json.loads(textio.read_text(rec.get('gen_plan') or fetch_plan or ''))
            plan = st.get('plan') or []
            rec['planned'] = len(plan)
            rec['fallback'] = sum(1 for r in plan if r.get('gen') == 'fallback')
        except Exception:                               # noqa: BLE001
            pass
        prog['chunks'][key] = rec
        save_progress(a.progress, prog)
        grand['words'] += rec['words']
        grand['notes'] += rec.get('notes', 0)
        grand['problems'] += rec.get('verify_problems', 0)
        grand['fallback'] += rec.get('fallback', 0)
        log('   %s：词 %d ｜ 计划 %s ｜ fallback %s ｜ 卡 %s ｜ 校验问题 %s ｜ '
            '用时 %.1f 分（fetch %.0fs / 媒体 %.0fs ∥ gen %.0fs / write %.0fs）'
            % (key, rec['words'], rec.get('planned', '—'), rec.get('fallback', '—'),
               rec.get('notes', 0), rec.get('verify_problems', 0), rec['t_total'] / 60,
               rec.get('t_fetch', 0), rec.get('t_prewarm') or 0, rec.get('t_gen', 0),
               rec.get('t_write', 0)))

    log('')
    log('=' * 88)
    log('本轮合计：词 %d ｜ 新建卡 %d ｜ 校验有问题 %d ｜ fallback %d ｜ 跳过已完成 %d 块'
        % (grand['words'], grand['notes'], grand['problems'], grand['fallback'],
           grand['skip']))
    err = [k for k, v in prog['chunks'].items() if v.get('status') == 'error']
    if err:
        log('⚠ 出错待重跑的块：%s（重跑同一命令会自动续）' % '、'.join(sorted(err)))
    log('进度文件 %s' % os.path.relpath(a.progress, WSP.ROOT))
    log('=' * 88)
    return halt['code'] or 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='ImmersionKit 分批全量跑')
    ap.add_argument('--words-file', default=os.path.join(DATA, 'words.txt'))
    ap.add_argument('--chunk-size', type=int, default=150)
    ap.add_argument('--n', type=int, default=1, help='每个词最多几条例句')
    ap.add_argument('--to', default='both', choices=('example', 'mined', 'both'))
    ap.add_argument('--keep-known', action='store_true',
                    help='fetch 加 --keep-known：只抓 core6000/考级已有的词（配 --to example）')
    ap.add_argument('--progress', default=PROGRESS)
    ap.add_argument('--only', type=int, default=0, help='只跑第 N 块（1 起，调试用）')
    ap.add_argument('--from', dest='start', type=int, default=1, help='从第 N 块开始')
    ap.add_argument('--dry-run', action='store_true', help='只演练 write，不写库')
    ap.add_argument('--pipeline', action='store_true',
                    help='流水线：第 N+1 块的 fetch 与第 N 块的 gen+write 并行；'
                         '块内「预下媒体」与「gen」也并行（下载不再串着等）')
    ap.add_argument('--redo', action='store_true', help='忽略进度重跑')
    ap.add_argument('--anki-wait-minutes', type=float, default=120,
                    help='Anki 不可用时最多等多久（默认 120 分钟）')
    ap.add_argument('--pause-window', action='append', default=[], metavar='HH:MM-HH:MM',
                    help='学习时段：落在这个窗口里就完全不动 Anki（可重复给）')
    ap.add_argument('--min-headroom-minutes', type=float, default=0,
                    help='距暂停窗口至少还剩这么多分钟才开新块（0＝按历史估的块时长）')
    ap.add_argument('--stop-file', default=os.path.join(DATA, 'STOP'),
                    help='存在这个文件就在块之间干净停下（删掉重跑即续）')
    a = ap.parse_args(argv)

    windows = parse_windows(a.pause_window)

    WSP.ensure()
    os.makedirs(CHUNK_DIR, exist_ok=True)
    words = read_words(a.words_file)
    size = max(1, a.chunk_size)
    chunks = [words[i:i + size] for i in range(0, len(words), size)]
    tag = os.path.splitext(os.path.basename(a.words_file))[0]
    prog = load_progress(a.progress)
    prog.setdefault('chunks', {})
    prog['words_file'] = os.path.abspath(a.words_file)
    prog['total_words'] = len(words)
    prog['total_chunks'] = len(chunks)
    prog.setdefault('started', dt.datetime.now().isoformat(timespec='seconds'))

    log('=' * 88)
    log('全量分批：%d 个词 → %d 块（每块 %d）｜ 目标牌组 %s ｜ %s%s'
        % (len(words), len(chunks), size, a.to,
           '演练' if a.dry_run else '★ 真写库',
           ' ｜ 流水线（fetch 提前一块 ∥ 媒体预下 ∥ gen）' if a.pipeline else ''))
    log('=' * 88)

    if a.pipeline:
        return run_pipeline(a, chunks, tag, prog, windows)

    grand = {'words': 0, 'notes': 0, 'problems': 0, 'fallback': 0, 'skip': 0}
    for i, batch in enumerate(chunks, 1):
        key = 'chunk_%03d' % i
        if a.only and i != a.only:
            continue
        if i < a.start:
            continue
        old = prog['chunks'].get(key) or {}
        if old.get('status') == 'done' and not a.redo:
            log('%s 已完成（%d 词，%d 张卡）→ 跳过' % (key, old.get('words', 0),
                                                old.get('notes', 0)))
            grand['words'] += old.get('words', 0)
            grand['notes'] += old.get('notes', 0)
            grand['problems'] += old.get('verify_problems', 0)
            grand['skip'] += 1
            continue

        chunk_file = os.path.join(CHUNK_DIR, '%s_%s.txt' % (tag, key))
        textio.write_text(chunk_file,
                          '# %s：%d 个词\n' % (key, len(batch)) + '\n'.join(batch) + '\n')
        log('')
        log('---- %s ｜%d 个词（%d/%d）----' % (key, len(batch), i, len(chunks)))

        for attempt in (1, 2):
            # 开跑前先把三件事确认掉：没按暂停 → 不在学习时段 → Anki 就绪。
            # 一块 ~20 分钟，开进复习时段会拖慢 Anki（用户 2026-10-16 明确要求让路）。
            while True:
                if os.path.exists(a.stop_file):
                    log('发现 STOP 文件（%s）→ 干净停下；删掉它重跑同一命令即续'
                        % os.path.relpath(a.stop_file, WSP.ROOT))
                    return 5
                if in_window(windows):
                    log('在暂停窗口内（%s）→ 睡 60 秒，不碰 Anki'
                        % '、'.join('%02d:%02d-%02d:%02d'
                                    % (x[0] // 60, x[0] % 60, x[1] // 60, x[1] % 60)
                                    for x in windows))
                    time.sleep(60)
                    continue
                need = a.min_headroom_minutes or est_chunk_minutes(prog, len(batch))
                left = minutes_until_window(windows)
                if left is not None and left < need:
                    log('距暂停窗口只剩 %.0f 分钟（开一块要约 %.0f 分钟）→ '
                        '这块不跑了，先停' % (left, need))
                    return 4
                # Anki 关着/重启时不要「瞬时失败 → 立刻翻下一块」（2026-10-16 实测：
                # Anki 一关，27 个块在几分钟内全被记成 error）。先等它回来。
                if not wait_anki(a.anki_wait_minutes):
                    log('Anki 一直没回来 → 先停（进度已存，重跑同一命令即续）')
                    return 3
                # 等 Anki 的这段时间里可能已经进了窗口/余量不够 → 再判一轮
                if in_window(windows) or (left is not None
                                          and minutes_until_window(windows) < need):
                    continue
                break
            rec = {'i': i, 'words': len(batch), 'file': chunk_file, 'status': 'running'}
            t_total = time.time()
            try:
                t0 = time.time()
                argv_f = ['fetch', '--words-file', chunk_file, '--n', str(a.n)]
                if a.keep_known:
                    argv_f.append('--keep-known')
                IK.main(argv_f)
                rec['t_fetch'] = round(time.time() - t0, 1)
                rec['fetch_plan'] = newest(os.path.join(DATA, 'fetch_*.json'))

                t0 = time.time()
                IK.main(['gen', '--quiet'])
                rec['t_gen'] = round(time.time() - t0, 1)
                rec['gen_plan'] = newest(os.path.join(DATA, 'plan_*.json'))

                before = set(glob.glob(os.path.join(DATA, 'written_*.json')))
                t0 = time.time()
                argv_w = ['write', '--to', a.to, '--no-order'] + (
                    [] if a.dry_run else ['--commit'])
                IK.main(argv_w)
                rec['t_write'] = round(time.time() - t0, 1)
                new = set(glob.glob(os.path.join(DATA, 'written_*.json'))) - before
                rec['written'] = max(new, key=os.path.getmtime) if new else ''

                if a.dry_run or not rec['written']:
                    rec['status'] = 'done'
                    rec['verify_problems'] = 0
                    rec['notes'] = 0
                else:
                    t0 = time.time()
                    rc = IK.main(['verify', '--written', rec['written']])
                    rec['t_verify'] = round(time.time() - t0, 1)
                    rec['verify_rc'] = rc
                    import json
                    w = json.loads(textio.read_text(rec['written']))
                    rec['notes'] = len(w.get('notes') or [])
                    rec['verify_problems'] = 1 if rc else 0
                    rec['status'] = 'done'
            except SystemExit as exc:                   # CLI 出错不该整轮倒下
                rec['status'] = 'error'
                rec['error'] = 'SystemExit %s' % exc
                log('   ✗ %s：%s' % (key, rec['error']))
            except Exception as exc:                    # noqa: BLE001
                rec['status'] = 'error'
                rec['error'] = '%s: %s' % (type(exc).__name__, exc)
                log('   ✗ %s：%s' % (key, rec['error']))
            rec['t_total'] = round(time.time() - t_total, 1)
            if rec['status'] == 'error' and rec['t_total'] < 30 and attempt == 1:
                log('   瞬时失败（%.1fs）→ 等 Anki 回来重试本块，不占用后面的块'
                    % rec['t_total'])
                continue
            break
        # 每块都重算一次「计划里的词数 / fallback 数」
        try:
            import json
            st = json.loads(textio.read_text(rec.get('gen_plan') or rec.get('fetch_plan') or ''))
            plan = st.get('plan') or []
            rec['planned'] = len(plan)
            rec['fallback'] = sum(1 for r in plan if r.get('gen') == 'fallback')
        except Exception:
            pass
        prog['chunks'][key] = rec
        save_progress(a.progress, prog)
        grand['words'] += rec['words']
        grand['notes'] += rec.get('notes', 0)
        grand['problems'] += rec.get('verify_problems', 0)
        grand['fallback'] += rec.get('fallback', 0)
        log('   %s：词 %d ｜ 计划 %s ｜ fallback %s ｜ 卡 %s ｜ 校验问题 %s ｜ '
            '用时 %.1f 分（fetch %.0fs / gen %.0fs / write %.0fs）'
            % (key, rec['words'], rec.get('planned', '—'), rec.get('fallback', '—'),
               rec.get('notes', 0), rec.get('verify_problems', 0),
               rec['t_total'] / 60, rec.get('t_fetch', 0), rec.get('t_gen', 0),
               rec.get('t_write', 0)))

    log('')
    log('=' * 88)
    log('本轮合计：词 %d ｜ 新建卡 %d ｜ 校验有问题 %d ｜ fallback %d ｜ 跳过已完成 %d 块'
        % (grand['words'], grand['notes'], grand['problems'], grand['fallback'],
           grand['skip']))
    err = [k for k, v in prog['chunks'].items() if v.get('status') == 'error']
    if err:
        log('⚠ 出错待重跑的块：%s（重跑同一命令会自动续）' % '、'.join(sorted(err)))
    log('进度文件 %s' % os.path.relpath(a.progress, WSP.ROOT))
    log('=' * 88)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
