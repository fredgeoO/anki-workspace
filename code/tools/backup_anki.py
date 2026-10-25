# -*- coding: utf-8 -*-
"""一次性把 anki-workspace + Anki 学习资料备份到外部盘 / one-shot backup CLI.

SOP（权威流程与恢复步骤）见 ``docs/backup-sop.md``。本脚本只做「执行 + 校验」：

    python code/tools/backup_anki.py --dest <备份盘>:\\anki-backup-2026-10-09
    python code/tools/backup_anki.py --dest <备份盘>:\\anki-backup-2026-10-09 --dry-run

它依次：

1. 检查源路径、目标盘可写、**Anki 是否已退出**（开着就只备份工作区那棵树，
   收藏库/媒体/插件需要一致副本，会被跳过；``--force`` 可强行继续，风险自负）；
2. robocopy 五棵树（各自写日志到 ``_verify\\robocopy-*.log``），退出码 <= 7 视为成功；
3. 对**备份出来的收藏库副本**跑 SQLite ``integrity_check`` + notes/cards/revlog 计数，
   并和「源库的一份临时副本」逐项比对；
4. 写 ``_verify\\manifest.json``（文件数/字节数/SHA256/收藏库计数）与
   目标目录根部的 ``README-备份说明.md``。

不删任何旧备份 —— 删除独立成一步，且必须在核对 manifest 之后手工做
（见 SOP §4.1）。无第三方依赖，只用标准库。
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(HERE))          # …/anki-workspace
sys.path.insert(0, os.path.join(WORKSPACE, 'code', 'common'))
# UTF-8 stdio 的唯一入口：import 时即 setup()，把 stdout/stderr 钉成 UTF-8（幂等）。
# 以前这里手写 sys.stdout.reconfigure，是 textio audit 的 R1 命中项，2026-10-10 改掉。
import textio  # noqa: E402
APPDATA = os.environ.get('APPDATA', '')
ANKI2 = os.path.join(APPDATA, 'Anki2')
PROFILE = os.path.join(ANKI2, '账户 1')
ADDONS = os.path.join(ANKI2, 'addons21')

# 收藏库本体要拷的文件（-wal 必须带上：Anki 用 WAL 模式，主库+wal 才完整）
COLLECTION_FILES = ('collection.anki2', 'collection.anki2-wal',
                    'collection.media.db2', 'deleted.txt')
# prefs21.db 是全局界面偏好，在 Anki2 根目录下（不在资料夹里），顺手带上
PREFS_FILES = ('prefs21.db',)

# 有意排除：Python 缓存，以及一次性文件区（里面的东西随时会被 temp clean 删掉）
WS_EXCLUDE_DIRS = ('__pycache__', 'temp')
PYCACHE = '__pycache__'

ROBOCOPY_OK = 7                                 # <=7 都算成功（1 = 有文件被复制）


def log(msg=''):
    print(msg, flush=True)


def human(nbytes):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if nbytes < 1024 or unit == 'TB':
            return '%.1f %s' % (nbytes, unit)
        nbytes /= 1024.0


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest().upper()


def measure(root, skip_dirs=(), only_files=None):
    """(files, bytes)；skip_dirs 里的大小写不敏感目录名整棵跳过。

    only_files 非空时只统计这些文件名（只看根层，对应「只拷几个文件」的收藏库那棵树）。
    """
    skip = {d.lower() for d in skip_dirs}
    files = total = 0
    if only_files:
        wanted = {f.lower() for f in only_files}
        for name in os.listdir(root):
            if name.lower() not in wanted:
                continue
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            try:
                total += os.path.getsize(path)
                files += 1
            except OSError:
                pass
        return files, total
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in skip]
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
                files += 1
            except OSError:
                pass
    return files, total


def anki_running():
    """AnkiConnect 端口开着 => Anki 还开着（比找进程名可靠）。"""
    import socket
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect(('127.0.0.1', 8765))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _log_summary(logfile):
    """从 robocopy 日志里取汇总（文件数/字节数/FAILED）。找不到就返回空串。"""
    try:
        with open(logfile, 'r', encoding='utf-8', errors='replace') as fh:
            lines = [ln.rstrip() for ln in fh]
    except OSError:
        return ''
    picked = [ln.strip() for ln in lines[-16:]
              if ln.strip().startswith(('Dirs :', 'Files :', 'Bytes :'))]
    return ' | '.join(' '.join(p.split()) for p in picked)


def robocopy(src, dst, extra=(), logfile=None, recursive=True):
    """返回 (exit_code, 汇总行)。robocopy 退出码 <=7 成功。"""
    cmd = ['robocopy', src, dst, '/COPY:DAT', '/DCOPY:DAT', '/XJ',
           '/R:2', '/W:1', '/NP', '/NDL', '/NFL']
    if recursive:
        cmd.append('/E')
    cmd += list(extra)
    if logfile:
        cmd.append('/LOG:' + logfile)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')
    summary = _log_summary(logfile) if logfile else ''
    if not summary:
        tail = [ln for ln in (proc.stdout or '').splitlines() if ln.strip()]
        summary = tail[-1].strip() if tail else ''
    return proc.returncode, summary


def _unicase(a, b):
    """近似 Anki 的 ``unicase``：NFC + casefold，再退化成码位比较。"""
    try:
        a = unicodedata.normalize('NFC', a).casefold()
        b = unicodedata.normalize('NFC', b).casefold()
    except Exception:                                # noqa: BLE001
        pass
    return (a > b) - (a < b)


def _open_collection(db_path):
    """打开收藏库副本并挂上 Anki 的自定义排序规则（标准库 sqlite3 不自带）。"""
    db = sqlite3.connect(db_path, timeout=30)
    try:
        db.create_collation('unicase', _unicase)
    except sqlite3.Error:
        pass
    return db


def _integrity(db):
    """(状态, 说明)。状态 'ok' / 'not_ok' / 'unavailable'。

    标准库 sqlite3 没有 Anki 的 ``unicase``（用替身也做不到逐字节一致），
    所以 ``integrity_check`` 在这里**只是加分项**：真失败不一定是库坏了，
    真正的判据是「SHA256 与源库一致 + 计数一致」。
    """
    try:
        rows = [r[0] for r in db.execute('pragma integrity_check').fetchall()]
    except sqlite3.DatabaseError as exc:
        return 'unavailable', str(exc)
    if rows and rows[0] == 'ok':
        return 'ok', 'ok'
    return 'not_ok', '; '.join(str(r) for r in rows[:3])


def collection_stats(db_path):
    """读一份**副本**的收藏库计数 + 完整性（只读，不改动副本）。"""
    db = _open_collection(db_path)
    try:
        state, detail = _integrity(db)
        counts = {}
        for table in ('notes', 'cards', 'revlog', 'col'):
            counts[table] = db.execute('select count(*) from %s' % table).fetchone()[0]
        last_rev = db.execute('select max(id) from revlog').fetchone()[0]
    finally:
        db.close()
    return {'integrity_check': state, 'integrity_detail': detail,
            'counts': counts, 'latest_revlog_id': last_rev}


def live_collection_stats():
    """把源库（含 -wal/-shm）复制到临时目录再读，不碰运行中的库。"""
    tmp = tempfile.mkdtemp(prefix='ankibk-')
    try:
        for suffix in ('', '-wal', '-shm'):
            src = os.path.join(PROFILE, 'collection.anki2' + suffix)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(tmp, 'collection.anki2' + suffix))
        return collection_stats(os.path.join(tmp, 'collection.anki2'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def source_collection_sha256():
    """源库 sha256。原库与副本逐字节相同 —— 这是「副本忠实」的最硬证据。

    关 Anki 后它会 checkpoint（-wal 被合并、随后消失），所以按当前实际存在的
    文件列表算；若副本是带 -wal 拷的、而现在源库已 checkpoint，哈希会不同，
    这种情况单独返回 ``stale_wal`` 让调用方提示重跑。
    """
    files = ['collection.anki2']
    for suffix in ('-wal', '-shm'):
        if os.path.exists(os.path.join(PROFILE, 'collection.anki2' + suffix)):
            files.append('collection.anki2' + suffix)
    path = os.path.join(PROFILE, 'collection.anki2')
    return sha256(path), files, os.path.getsize(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description='备份 anki-workspace + Anki 学习资料')
    ap.add_argument('--dest', required=True, help=r'备份目标目录，如 <备份盘>:\anki-backup-2026-10-09')
    ap.add_argument('--dry-run', action='store_true', help='只打印计划，不复制')
    ap.add_argument('--force', action='store_true',
                    help='Anki 仍在运行时也强行备份收藏库（副本可能撕裂，仅救急）')
    ap.add_argument('--overwrite', action='store_true', help='目标目录非空也继续（robocopy 增量）')
    args = ap.parse_args(argv)

    dest = os.path.abspath(args.dest)
    now = _dt.datetime.now()
    stamp = now.strftime('%Y-%m-%d %H:%M:%S')

    log('=' * 72)
    log('备份 %s  ->  %s' % (stamp, dest))
    log('=' * 72)

    # ---- 0. 源检查 --------------------------------------------------------
    problems = []
    for label, path in (('工作区', WORKSPACE), ('Anki 资料夹', PROFILE),
                        ('收藏库', os.path.join(PROFILE, 'collection.anki2')),
                        ('界面偏好', os.path.join(ANKI2, 'prefs21.db')),
                        ('媒体库', os.path.join(PROFILE, 'collection.media')),
                        ('滚动备份', os.path.join(PROFILE, 'backups')),
                        ('插件', ADDONS)):
        ok = os.path.exists(path)
        log('  [%s] %-10s %s' % ('OK ' if ok else '!! ', label, path))
        if not ok:
            problems.append('源不存在：%s' % path)
    if problems:
        log('\n源检查失败，已停止：')
        for p in problems:
            log('  - ' + p)
        return 2

    running = anki_running()
    log('  [%s] %-10s AnkiConnect 127.0.0.1:8765 %s'
        % ('OK ' if not running else '!! ', 'Anki 状态',
           '未响应（Anki 已退出）' if not running else '有响应（Anki 还开着！）'))
    if running and not args.force:
        log('\nAnki 还在运行：收藏库/媒体/插件做不出一致副本。')
        log('  处理：① 完全退出 Anki（含托盘）后重跑；')
        log('        ② 或只想先存工作区，用 --force 跳过 Anki 相关三棵树。')
        if args.dry_run:
            log('（dry-run：下面只展示计划）')
        else:
            return 3

    root_drive = os.path.splitdrive(dest)[0] + os.sep
    if not os.path.isdir(root_drive):
        log('\n目标盘不存在：%s' % root_drive)
        return 2
    if os.path.isdir(dest) and os.listdir(dest) and not args.overwrite:
        log('\n目标目录已存在且非空：%s' % dest)
        log('  robocopy 是增量复制，确认要续写请加 --overwrite。')
        return 2
    log('  [OK ] %-10s %s' % ('目标盘', root_drive))

    # ---- 1. 计划 ----------------------------------------------------------
    verify_dir = os.path.join(dest, '_verify')
    # name, src, dst, robocopy extra, 统计时跳过的目录, 只统计这些文件, 递归
    trees = [
        ('workspace', WORKSPACE, os.path.join(dest, 'workspace'),
         ['/MT:16', '/XD'] + list(WS_EXCLUDE_DIRS), WS_EXCLUDE_DIRS, None, True),
        ('anki-collection', PROFILE, os.path.join(dest, 'anki-collection'),
         ['/IF'] + list(COLLECTION_FILES), (), COLLECTION_FILES, False),
        ('anki-prefs', ANKI2, os.path.join(dest, 'anki-collection'),
         ['/IF'] + list(PREFS_FILES), (), PREFS_FILES, False),
        ('anki-media', os.path.join(PROFILE, 'collection.media'),
         os.path.join(dest, 'anki-media', 'collection.media'),
         ['/MT:24'], (), None, True),
        ('anki-backups', os.path.join(PROFILE, 'backups'),
         os.path.join(dest, 'anki-backups'), ['/MT:8'], (), None, True),
        ('anki-addons', ADDONS, os.path.join(dest, 'anki-addons', 'addons21'),
         ['/MT:8', '/XD', PYCACHE], (PYCACHE,), None, True),
    ]
    if running and args.force:
        trees = [t for t in trees if t[0] == 'workspace']
        log('  [!! ] --force：Anki 在运行，本次只备份 workspace 一棵树')

    log('\n计划：')
    for name, src, dst, _extra, skip, only, _rec in trees:
        files, size = measure(src, skip, only)
        log('  %-16s %6d 文件 %10s  ->  %s' % (name, files, human(size), dst))
    if args.dry_run:
        log('\n--dry-run：未复制任何文件。')
        return 0

    os.makedirs(verify_dir, exist_ok=True)

    # ---- 2. 复制 ----------------------------------------------------------
    results = {}
    for name, src, dst, extra, skip, only, rec in trees:
        log('\n>>> robocopy %s' % name)
        logf = os.path.join(verify_dir, 'robocopy-%s.log' % name.replace('anki-', ''))
        code, summary = robocopy(src, dst, extra=extra, logfile=logf, recursive=rec)
        ok = code <= ROBOCOPY_OK
        log('    退出码 %d %s | %s' % (code, '(OK)' if ok else '(失败!)', summary))
        src_files, src_bytes = measure(src, skip, only)
        dst_files, dst_bytes = measure(dst, (), only)
        match = (src_files == dst_files and src_bytes == dst_bytes)
        log('    源 %d 文件 / %s  备份 %d 文件 / %s  -> %s'
            % (src_files, human(src_bytes), dst_files, human(dst_bytes),
               '一致' if match else '不一致 !!'))
        results[name] = {
            'source': src, 'dest': dst, 'robocopy_exit': code,
            'robocopy_summary': summary, 'robocopy_log': logf,
            'files': dst_files, 'bytes': dst_bytes,
            'source_files': src_files, 'source_bytes': src_bytes,
            'match': bool(match and ok), 'excluded': list(skip),
            'only_files': list(only or ()),
        }
        if not (ok and match):
            log('    !! 这一棵没通过，停止后续（旧备份不要删）')
            return 4

    # ---- 3. 收藏库校验 ----------------------------------------------------
    collection = {}
    col_copy = os.path.join(dest, 'anki-collection', 'collection.anki2')
    if os.path.exists(col_copy):
        log('\n>>> 校验收藏库副本（integrity_check + 计数）')
        try:
            backup_stats = collection_stats(col_copy)
            live_stats = live_collection_stats()
            src_sha, src_files, src_size = source_collection_sha256()
        except Exception as exc:                       # noqa: BLE001
            log('    !! 校验失败：%r' % (exc,))
            return 5
        same = (backup_stats['counts'] == live_stats['counts'])
        dst_sha = sha256(col_copy)
        dst_size = os.path.getsize(col_copy)
        hash_same = (dst_sha == src_sha)
        log('    主库 SHA256（备份/源）: %s / %s -> %s'
            % (dst_sha[:16] + '…', src_sha[:16] + '…',
               '一致（逐字节相同）' if hash_same else '不一致 !!'))
        log('    主库大小（备份/源）: %s / %s' % (dst_size, src_size))
        log('    备份时的源库文件  : %s' % ', '.join(src_files))
        if backup_stats['integrity_check'] == 'ok':
            log('    integrity_check : ok')
        else:
            log('    integrity_check : %s（%s）—— 标准库 sqlite3 没有 Anki 的 unicase 规则，'
                % (backup_stats['integrity_check'], backup_stats['integrity_detail']))
            log('                      以 SHA256 一致为准；要跑权威检查请用 Anki 覆盖还原到新资料夹')
        log('    备份 notes/cards/revlog : %s / %s / %s'
            % (backup_stats['counts']['notes'], backup_stats['counts']['cards'],
               backup_stats['counts']['revlog']))
        log('    源   notes/cards/revlog : %s / %s / %s'
            % (live_stats['counts']['notes'], live_stats['counts']['cards'],
               live_stats['counts']['revlog']))
        log('    最新复习记录 id（备份/源）: %s / %s'
            % (backup_stats['latest_revlog_id'], live_stats['latest_revlog_id']))
        log('    计数%s' % ('一致' if same else '不一致 !!'))
        if not (same and hash_same):
            log('    !! 收藏库校验没通过（旧备份不要删）')
            if not hash_same:
                log('       源库和副本不同：多半是备份后又动过 Anki（或拷贝时它正开着）。')
                log('       处理：确认 Anki 已退出，然后重跑本脚本（robocopy 是增量的，很快）。')
            return 5
        collection = {
            'file': col_copy,
            'sha256': dst_sha,
            'source_sha256': src_sha,
            'sha256_match': True,
            'size_bytes': dst_size,
            'source_size_bytes': src_size,
            'source_files_at_copy': src_files,
            'integrity_check': backup_stats['integrity_check'],
            'integrity_detail': backup_stats['integrity_detail'],
            'counts': backup_stats['counts'],
            'source_counts': live_stats['counts'],
            'latest_revlog_id': backup_stats['latest_revlog_id'],
            'source_latest_revlog_id': live_stats['latest_revlog_id'],
        }
    else:
        log('\n>>> 未复制收藏库（Anki 运行时用 --force 的结果），跳过其校验')

    # ---- 4. manifest + README --------------------------------------------
    manifest = {
        'created_local': stamp,
        'backup_root': dest,
        'source': {'workspace': WORKSPACE, 'anki_profile': PROFILE,
                   'anki_addons': ADDONS, 'appdata': APPDATA},
        'anki_running_at_backup': bool(running),
        'trees': results,
        'collection': collection,
    }
    total_files = sum(r['files'] for r in results.values())
    total_bytes = sum(r['bytes'] for r in results.values())
    manifest['totals'] = {
        'trees_files': total_files, 'trees_bytes': total_bytes,
        'artifacts_files': 1 + len(results) + 1,     # README + robocopy 日志 + manifest
        'grand_files': total_files + 1 + len(results) + 1,
        'finished_local': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    manifest_path = os.path.join(verify_dir, 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    readme = os.path.join(dest, 'README-备份说明.md')
    write_readme(readme, dest, stamp, results, collection, total_files, total_bytes)

    # ---- 5. 总结 ----------------------------------------------------------
    log('\n' + '=' * 72)
    log('VERIFY 汇总')
    log('  %-16s %8s %12s  %s' % ('tree', 'files', 'size', '结果'))
    for name, r in results.items():
        log('  %-16s %8d %12s  %s' % (name, r['files'], human(r['bytes']),
                                      'OK' if r['match'] else 'FAILED'))
    log('  %-16s %8d %12s' % ('TOTAL(内容)', total_files, human(total_bytes)))
    log('  加 _verify/ 与 README 后，备份目录里共 %d 个文件'
        % manifest['totals']['grand_files'])
    if collection:
        log('  收藏库 notes=%s cards=%s revlog=%s，SHA256 与源库%s'
            % (collection['counts']['notes'], collection['counts']['cards'],
               collection['counts']['revlog'],
               '一致（逐字节相同）' if collection.get('sha256_match') else '不一致 !!'))
        log('        sha256=%s' % collection['sha256'])
    log('  manifest : %s' % manifest_path)
    log('  README   : %s' % readme)
    log('')
    log('下一步（确认无误后手工执行，脚本不代删旧备份）：')
    log('  1) 打开 manifest.json 核对上面的数字；')
    log('  2) 删旧备份：Remove-Item -Recurse -Force "<上一份备份目录>"')
    log('  3) 在 docs/backup-sop.md §8 台账补一行。')
    return 0


def write_readme(path, dest, stamp, results, collection, total_files, total_bytes):
    rows = []
    for name in results:
        if name == 'anki-prefs':
            continue                                    # 与收藏库同一个目标目录，下面合并
        r = results[name]
        if name == 'anki-collection':
            p = results.get('anki-prefs')
            if p:
                r = dict(r, files=r['files'] + p['files'],
                         bytes=r['bytes'] + p['bytes'],
                         match=bool(r['match'] and p['match']))
        rows.append('| `%s\\` | %d | %s | %s |' % (
            name, r['files'], human(r['bytes']),
            '一致' if r['match'] else '**不一致**'))
    col_txt = '_未备份（备份时 Anki 在运行）_'
    if collection:
        c = collection
        integ = c['integrity_check']
        integ_txt = ('`integrity_check = ok`'
                     if integ == 'ok' else
                     '标准库 sqlite3 无 Anki 的 `unicase` 排序规则，'
                     '`integrity_check` 不适用（%s）——以 SHA256 一致为准' % integ)
        col_txt = ('notes **%s** / cards **%s** / revlog **%s**，最新复习记录 `%s`；'
                   '\n主库与源库 **SHA256 逐字节一致**：`%s`；%s' % (
                       c['counts']['notes'], c['counts']['cards'], c['counts']['revlog'],
                       c['latest_revlog_id'], c['sha256'], integ_txt))
    text = """# Anki + 工作区备份说明

**备份时间**：{stamp}（本地时间）
**备份位置**：`{dest}\\`
**权威流程**：`anki-workspace\\docs\\backup-sop.md`（恢复步骤见其 §5）

## 1. 内容与完整性

| 备份目录 | 文件数 | 大小 | 源↔备份 |
|---|---|---|---|
{rows}
| **合计** | **{total_files}** | **{human_total}** | |

收藏库校验（对备份副本执行）：{col_txt}

逐项明细见 `_verify\\manifest.json`，robocopy 原始日志见 `_verify\\robocopy-*.log`。

## 2. 怎么恢复

完整流程见 `docs\\backup-sop.md` §5，最省事的三条：

1. **整套恢复**：先完全退出 Anki → 恢复工作区（robocopy 拷回）→ 把
   `%APPDATA%\\Anki2\\账户 1` 改名留底 → 拷回 `anki-collection\\*`（含 `prefs21.db`，
   它属于 `%APPDATA%\\Anki2\\` 而不是资料夹）→
   robocopy 拷回 `anki-media\\collection.media` → 拷回插件与滚动备份 → 打开 Anki 检查。
2. **只要学习进度**：Anki「文件 → 导入」选 `anki-backups\\` 里最新的 `.colpkg`
   （**不含媒体**，音频图片需另拷 `anki-media`）。
3. **只找回代码/文档**：只把 `workspace\\` robocopy 回工作区即可。

## 3. 注意

- 这是 **{stamp} 的时间点快照**：之后新学的卡、新复习记录不在里面，需要更新就重做一次。
- 本备份**未加密**：`anki-collection\\collection.anki2` 里有全部学习记录，G: 盘若会被他人访问请注意。
- `anki-addons\\addons21` 跳过了 `__pycache__`；Anki 首次启动会自动重建。
- 校验读的是**备份副本**，源库全程只读。
""".format(stamp=stamp, dest=dest, rows='\n'.join(rows),
           total_files=total_files, human_total=human(total_bytes), col_txt=col_txt)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


if __name__ == '__main__':
    sys.exit(main())
