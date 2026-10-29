#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ankiR 分析入口 —— 用 R 包 ankiR 读收藏库出留存/负荷/预测报告。

    python code/analysis/ankir.py list --grep retention
    python code/analysis/ankir.py summary
    python code/analysis/ankir.py report --json --out temp/report.json
    python code/analysis/ankir.py weak --arg days=30
    python code/analysis/ankir.py call anki_retention_by_type --json
    python code/analysis/ankir.py plot anki_plot_heatmap --out output/reports/heatmap.png

分工：
  * **本文件**负责「取数来源」「时效」和「编码」——默认把**当前 live 收藏**（含 -wal/-shm）
    只读复制到 temp\\，再交给 R；跑完即删。每次打印三行时效（最新复习时间 / 落盘时间 /
    AnkiConnect 今日复习对账），报告里的「数据截至」就抄这一行。
  * **ankir_bridge.R** 负责调 ankiR，把返回值/打印内容写成 UTF-8 JSON。
  * 报告正文由人/模型写，本入口只负责把数字和图表拿出来。

**数据源红线**：出当期报告只许用默认 live。`data\\snapshots` 里的旧快照（实测旧约 3 天）
只能通过显式 `--db <路径>` 使用；`--source snapshot` 不带 `--db` 直接报错，
就是为了堵住「悄悄拿旧快照出报告」这条路。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'common'))
import paths as WSP          # noqa: E402  工作区路径唯一来源
import textio                # noqa: E402  UTF-8 stdio 唯一入口
import anki_api as AK        # noqa: E402  Anki 唯一通道（这里只用它的只读快照复制）

R_HOME = os.path.join(WSP.DATA, 'r-env', 'R')
RSCRIPT = os.path.join(R_HOME, 'bin', 'Rscript.exe')
BRIDGE = os.path.join(WSP.ANALYSIS, 'ankir_bridge.R')
R_TMP = os.path.join(WSP.TEMP, 'ankir_tmp')

#: 预设 = 「一句话能说清的分析」→ ankiR 函数名。其余一律走 `call <fn>`。
PRESETS = {
    'summary':   ('anki_quick_summary', '一行总览：卡数/到期/连续天数/7 日留存'),
    'report':    ('anki_report',        '综合统计（卡量、留存、间隔、复习量）'),
    'health':    ('anki_health_check',  '0–100 健康分 + 扣分项'),
    'weak':      ('anki_weak_areas',    '按标签/牌组找留存最低的弱项'),
    'retention': ('anki_retention_rate', '留存率（可 --arg days=30 / by_deck=TRUE）'),
    'today':     ('anki_today',         '今天的学习明细'),
    'streak':    ('anki_streak',        '连续学习天数'),
}


def _die(msg, code=2):
    textio.warn(msg)
    return code


def _check_r():
    if not os.path.exists(RSCRIPT):
        return ('找不到 Rscript：%s\n  先装 R + ankiR（见技能 anki-r-analysis 的「安装」一节），'
                '或确认 data\\r-env 还在。' % RSCRIPT)
    if not os.path.exists(BRIDGE):
        return '找不到 R 桥：%s' % BRIDGE
    return None


def _r_env():
    os.makedirs(R_TMP, exist_ok=True)
    env = textio.child_env()
    # R 4.2+ 在 Windows 上内部是 UTF-8；把 locale 也钉成 UTF-8，控制台输出才不会变 '?'
    env['LC_ALL'] = 'Japanese_Japan.utf8'
    env['LANG'] = 'Japanese_Japan.utf8'
    # R 启动要建 R_TempDir；dsh 沙箱给的 TEMP 在提权/非提权之间不总可写，统一落到工作区 temp\
    env['TEMP'] = env['TMP'] = env['TMPDIR'] = R_TMP
    return env


def _coerce(value):
    """`--arg k=v` 的 v：先按 JSON 解（数字/布尔/数组），再认 R 风格的 TRUE/FALSE/NULL。"""
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        pass
    low = value.strip().lower()
    if low in ('true', 't'):
        return True
    if low in ('false', 'f'):
        return False
    if low in ('null', 'none', 'na'):
        return None
    return value


def _provenance(snap):
    """从只读副本里读「数据到哪儿了」：最新一次复习、复习总数、卡数。

    报告里的「数据截至」就用这个，不用文件时间——文件可能被 Anki 后台改而内容没变。
    """
    row = snap.con.execute('SELECT MAX(id), COUNT(*) FROM revlog').fetchone()
    latest_ms = int(row[0] or 0)
    cards = int(snap.con.execute('SELECT COUNT(*) FROM cards').fetchone()[0])
    return {
        'latest_review_ms': latest_ms,
        'latest_review': _fmt_ms(latest_ms),
        'reviews': int(row[1] or 0),
        'cards': cards,
    }


def _fmt_ms(ms):
    if not ms:
        return '(无复习记录)'
    return datetime.datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M')


def _live_mtime():
    """live 收藏（含 -wal）最后落盘时间，只用来提示「磁盘上的数据有多新」。"""
    newest = 0.0
    for suf in ('', '-wal', '-shm'):
        p = WSP.LIVE_COLLECTION + suf
        if os.path.exists(p):
            newest = max(newest, os.path.getmtime(p))
    return datetime.datetime.fromtimestamp(newest).strftime('%Y-%m-%d %H:%M') if newest else '?'


def _due_stats(snap, horizon=14):
    """**正确的**到期口径（ankiR 自己那套是错的，见下）。

    Anki 的复习卡 `due` 是「距收藏创建日（col.crt）的天数」，不是 1970 起的绝对天数。
    本库 crt=2026-06-09 04:00，所以今天是第 143 天；复习卡 due 值都在 143–1280 之间。
    ankiR 拿它跟「1970 起的日数」（≈20,756）比，于是把**全部** 7,105 张复习卡都算成到期，
    连带 overdue / forecast 一起虚高。这里按 Anki 自己的算法重算。
    """
    con = snap.con
    crt = int(con.execute('SELECT crt FROM col').fetchone()[0])
    now = int(time.time())
    today = (now - crt) // 86400

    def count(sql, params=()):
        return int(con.execute(sql, params).fetchone()[0])

    due_today = count('SELECT COUNT(*) FROM cards WHERE queue=2 AND due<=?', (today,))
    overdue7 = count('SELECT COUNT(*) FROM cards WHERE queue=2 AND due<=?', (today - 7,))
    learning = count('SELECT COUNT(*) FROM cards WHERE queue IN (1,3) AND due<=?', (now,))
    new = count('SELECT COUNT(*) FROM cards WHERE queue=0')
    rows = con.execute('SELECT due, COUNT(*) FROM cards WHERE queue=2 AND due>? AND due<=? '
                       'GROUP BY due ORDER BY due', (today, today + horizon)).fetchall()
    base = datetime.date.today()
    future = [{'date': (base + datetime.timedelta(days=int(d) - today)).isoformat(),
               'day': int(d), 'n': int(n)} for d, n in rows]
    return {'crt': crt, 'today': today, 'due_today': due_today, 'overdue_7d': overdue7,
            'learning': learning, 'new': new, 'future': future,
            'future_total': sum(x['n'] for x in future)}


def _print_due(due):
    textio.warn('[到期] 今天是第 %d 天（crt=%s）· 待复习 %s · 逾期>7天 %s · 学习中 %s'
                % (due['today'],
                   datetime.datetime.fromtimestamp(due['crt']).strftime('%Y-%m-%d'),
                   format(due['due_today'], ','), format(due['overdue_7d'], ','),
                   format(due['learning'], ',')))
    if due['future']:
        head = '、'.join('%s:%s' % (x['date'][5:], x['n']) for x in due['future'][:7])
        textio.warn('[到期] 未来 14 天：%s …（合计 %s，日均 %.0f）'
                    % (head, format(due['future_total'], ','),
                       due['future_total'] / max(len(due['future']), 1)))


def _stamp(snap, live):
    """打印数据时效；live 时再跟 AnkiConnect 对一次「今天复习了几次」，防副本落后。"""
    info = _provenance(snap)
    textio.warn('[数据] %s · 最新复习 %s · %s 张 / %s 次复习'
                % ('live 收藏（现在）' if live else '指定库（历史）',
                   info['latest_review'], format(info['cards'], ','), format(info['reviews'], ',')))
    if not live:
        return info
    textio.warn('[数据] 磁盘落盘时间 %s' % _live_mtime())
    try:
        anki_today = int(AK.call('getNumCardsReviewedToday'))
    except Exception:
        textio.warn('[数据] Anki 未开（读的是磁盘上的收藏；数字仍然是真实的，只是没有在线校验）')
        return info
    day_start = int(datetime.datetime.combine(datetime.date.today(), datetime.time.min).timestamp() * 1000)
    copy_today = int(snap.con.execute('SELECT COUNT(*) FROM revlog WHERE id >= ?',
                                      (day_start,)).fetchone()[0])
    if anki_today > copy_today:
        textio.warn('[!] 副本落后：Anki 今天已复习 %d 次，副本里只有 %d 次 → 重跑一次'
                    % (anki_today, copy_today))
    else:
        textio.warn('[数据] Anki 在线校验通过：今日复习 %d 次，副本一致' % anki_today)
    return info


def _request(db, fn, args, want_json, head, plot_out, width, height):
    return {'db': db, 'mode': 'call', 'fn': fn, 'args': args or {},
            'json': bool(want_json), 'head': head, 'plot_out': plot_out,
            'width': width, 'height': height}


def _run_r(request, workdir, timeout=900):
    """跑一次桥，返回 (result_dict, r_stderr)。超时连**进程树**一起杀。"""
    req_path = os.path.join(workdir, 'request.json')
    res_path = os.path.join(workdir, 'result.json')
    textio.dump_json(request, req_path, indent=1)
    cmd = [RSCRIPT, '--vanilla', BRIDGE, req_path, res_path]
    # cwd 钉到本次工作目录：绘图函数若走默认设备，R 会把 Rplots.pdf 丢在 cwd，
    # 留在工作区根目录会被 doctor 第 9 项判成计划外条目（踩过）。
    proc = subprocess.Popen(cmd, env=_r_env(), cwd=workdir, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **textio.text_kwargs())
    try:
        _out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Rscript 会再起一个 R.exe；只杀子进程会留下占满 CPU 的孤儿（实测踩过）
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.communicate()
        raise RuntimeError('ankiR 调用超过 %d 秒被杀（进程树已清）：%s' % (timeout, request.get('fn')))
    if not os.path.exists(res_path):
        raise RuntimeError('R 桥没产出结果（exit=%s）\n%s'
                           % (proc.returncode, (err or '').strip()[-2000:]))
    result = textio.load_json(res_path, default=None)
    if result is None:
        raise RuntimeError('结果 JSON 解不开：%s' % res_path)
    return result, (err or '')


def _emit(result, args, due=None):
    """把桥的结果按 --json / --out 的约定吐出去。

    ⚠ ankiR 的 `anki_quick_summary` 里的 "Due today" 是错的（把相对天数当成绝对日期），
    这里用 `_due_stats` 的真值换掉，并在 stderr 说明；JSON 里另给 `due_today` 修正值。
    """
    if not result.get('ok'):
        textio.warn('ankiR 报错：%s' % result.get('error'))
        return 1
    for w in result.get('warnings') or []:
        textio.warn('R warning: %s' % w)
    body = ''
    fn = result.get('fn')
    if args.json:
        payload = result.get('data_json')
        data = json.loads(payload) if payload else None
        if due and fn == 'anki_quick_summary' and isinstance(data, dict):
            data['due_today_ankir_wrong'] = data.get('due_today')
            data['due_today'] = due['due_today']
            data['overdue_7d'] = due['overdue_7d']
            data['today_index'] = due['today']
            textio.warn('[修正] ankiR 的 due_today 不可用（相对天数当日期），已换成真实值 %s'
                        % format(due['due_today'], ','))
        elif due and fn == 'anki_quick_summary' and isinstance(data, str):
            data, n = re.subn(r'Due today:\s*[\d,]+',
                              'Due today: %s' % format(due['due_today'], ','), data)
            if n:
                textio.warn('[修正] ankiR 报的 Due today 已换成真实值 %s'
                            % format(due['due_today'], ','))
        elif due and fn == 'anki_health_check' and isinstance(data, dict):
            warn = (data.get('warnings') or {}).get('many_overdue') if isinstance(data.get('warnings'), dict) else None
            if isinstance(warn, dict):
                warn['count'] = due['overdue_7d']
                warn['message'] = ('%d cards are overdue by more than a week '
                                   '（修正值；ankiR 原报 7105，是把相对天数当日期算错的）'
                                   % due['overdue_7d'])
                textio.warn('[修正] 健康检查的 many_overdue 已换成真实逾期 %s'
                            % format(due['overdue_7d'], ','))
        body = json.dumps(data, ensure_ascii=False, indent=1) if data is not None else 'null'
    else:
        body = (result.get('text') or '').rstrip()
        if due and fn == 'anki_quick_summary' and body:
            fixed, n = re.subn(r'Due today:\s*[\d,]+',
                               'Due today: %s' % format(due['due_today'], ','), body)
            if n:
                body = fixed
                textio.warn('[修正] ankiR 报的 Due today 是错的（把复习卡的相对天数当成了日期），'
                            '已换成 Anki 口径的真实值 %s；逾期>7天 %s'
                            % (format(due['due_today'], ','), format(due['overdue_7d'], ',')))
        if due and fn == 'anki_health_check' and body:
            body, n = re.subn(r'\d+ cards are overdue by more than a week',
                              '%d cards are overdue by more than a week（修正值）' % due['overdue_7d'],
                              body)
            body, m = re.subn(r'(\$warnings\$many_overdue\$count\s*\n\s*\[1\]\s*)\d+',
                              r'\g<1>%d' % due['overdue_7d'], body)
            if n or m:
                textio.warn('[修正] 健康检查里「逾期 7105 张」是 ankiR 算错的，真实逾期 %s'
                            % format(due['overdue_7d'], ','))
        if not body and result.get('data_json'):
            body = result['data_json']
    if args.out:
        textio.write_text(args.out, body + '\n', newline='\n')
        textio.warn('已写入 %s（%s，%.2fs）' % (args.out, result.get('fn'), result.get('seconds') or 0))
    else:
        print(body)
    return 0


def cmd_list(args):
    with _workdir() as wd:
        result, _ = _run_r({'mode': 'list'}, wd)
    if not result.get('ok'):
        return _die('拿不到函数清单：%s' % result.get('error'))
    fns = result.get('functions') or []
    grep = (args.grep or '').lower()
    rows = [f for f in fns if not grep or grep in f['fn'].lower() or grep in (f.get('title') or '').lower()]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    textio.warn('ankiR %s：%d 个导出函数，匹配 %d 个' % (result.get('version'), len(fns), len(rows)))
    for f in rows:
        print('%-28s %s' % (f['fn'], (f.get('title') or '').strip()))
    return 0


def _workdir():
    """temp\\ankir\\run-<ts>-<pid>\\，用完即删（--keep 时保留并打印路径）。"""
    import contextlib
    import shutil
    import time as _t

    @contextlib.contextmanager
    def _cm():
        wd = os.path.join(WSP.TEMP, 'ankir', 'run-%s-%d' % (_t.strftime('%Y%m%d-%H%M%S'), os.getpid()))
        os.makedirs(wd, exist_ok=True)
        try:
            yield wd
        finally:
            if os.environ.get('ANKIR_KEEP') == '1':
                textio.warn('保留工作目录：%s' % wd)
            else:
                shutil.rmtree(wd, ignore_errors=True)
    return _cm()


def _execute(args, fn):
    err = _check_r()
    if err:
        return _die(err)
    req_args = {}
    if args.args_json:
        try:
            req_args.update(json.loads(args.args_json))
        except ValueError as exc:
            return _die('--args 不是合法 JSON：%s' % exc)
    for kv in args.arg or []:
        if '=' not in kv:
            return _die('--arg 要写成 key=value：%s' % kv)
        k, v = kv.split('=', 1)
        req_args[k] = _coerce(v)

    plot_out = os.path.abspath(args.plot) if args.plot else None
    if plot_out:
        os.makedirs(os.path.dirname(plot_out), exist_ok=True)

    with _workdir() as wd:
        try:
            if args.source == 'snapshot' and not args.db:
                # 历史快照只用于复现；不给 --db 就拒绝，避免静默拿 3 天前的 _anki_snap 出报告
                return _die('--source snapshot 只用于复现历史，必须同时给 --db <快照路径>。\n'
                            '  日常报告请用默认（live＝当前收藏）：去掉 --source snapshot，或加 --db。')
            if args.db:
                db = args.db
                if not os.path.exists(db):
                    return _die('指定的库不存在：%s' % db)
                with AK.Snapshot.open(path=db) as probe:
                    _stamp(probe, live=False)
                    due = _due_stats(probe)
                    _print_due(due)
                result, stderr = _run_r(_request(db, fn, req_args, args.json, args.head,
                                                 plot_out, args.width, args.height), wd)
            else:
                # live 副本：当前收藏（含 -wal/-shm）的只读复制，跑完即删
                with AK.Snapshot.open(live_copy=True, copy_to=wd) as snap:
                    _stamp(snap, live=True)
                    due = _due_stats(snap)
                    _print_due(due)
                    result, stderr = _run_r(_request(snap.path, fn, req_args, args.json, args.head,
                                                     plot_out, args.width, args.height), wd)
        except (RuntimeError, OSError) as exc:
            return _die('跑 ankiR 失败：%s' % exc)
        except AK.SnapshotError as exc:
            return _die('读收藏失败：%s' % exc)
        code = _emit(result, args, due)
    if code == 0 and stderr.strip():
        tail = [ln for ln in stderr.strip().splitlines() if ln.strip()][-3:]
        for ln in tail:
            textio.warn('R: %s' % ln)
    return code


def cmd_due(args):
    """只出到期/负荷（不调 R）——这是报告里唯一可信的「今天到期」来源。"""
    err = _check_r()
    if err:
        return _die(err)
    with _workdir() as wd:
        try:
            if args.db:
                if not os.path.exists(args.db):
                    return _die('指定的库不存在：%s' % args.db)
                with AK.Snapshot.open(path=args.db) as snap:
                    _stamp(snap, live=False)
                    due = _due_stats(snap, horizon=max(args.days, 1))
            else:
                with AK.Snapshot.open(live_copy=True, copy_to=wd) as snap:
                    _stamp(snap, live=True)
                    due = _due_stats(snap, horizon=max(args.days, 1))
        except (RuntimeError, OSError) as exc:
            return _die('读收藏失败：%s' % exc)
        except AK.SnapshotError as exc:
            return _die('读收藏失败：%s' % exc)

    if args.json:
        body = json.dumps(due, ensure_ascii=False, indent=1)
    else:
        lines = ['今天（第 %d 天，自 %s）' % (due['today'],
                                            datetime.datetime.fromtimestamp(due['crt']).strftime('%Y-%m-%d')),
                 '  待复习      %s' % format(due['due_today'], ','),
                 '  逾期>7天    %s' % format(due['overdue_7d'], ','),
                 '  学习中      %s' % format(due['learning'], ','),
                 '  新卡        %s' % format(due['new'], ',')]
        if due['future']:
            lines.append('未来 %d 天：' % len(due['future']))
            for x in due['future']:
                lines.append('  %s  %s' % (x['date'], format(x['n'], ',')))
            lines.append('  合计 %s，日均 %.0f'
                         % (format(due['future_total'], ','),
                            due['future_total'] / max(len(due['future']), 1)))
        body = '\n'.join(lines)
    if args.out:
        textio.write_text(args.out, body + '\n', newline='\n')
        textio.warn('已写入 %s' % args.out)
    else:
        print(body)
    return 0


def _common(p):
    p.add_argument('--source', choices=('live', 'snapshot'), default='live',
                   help='数据源：live＝当前收藏的只读副本（默认，报告一律用它）；'
                        'snapshot 只用于复现历史，必须配 --db')
    p.add_argument('--db', help='指定一个 collection.anki2（历史快照/备份副本，只读）')
    p.add_argument('--json', action='store_true', help='输出 JSON（默认输出 R 渲染的文本）')
    p.add_argument('--out', help='把结果写进文件（UTF-8），不给就打到 stdout')
    p.add_argument('--head', type=int, default=20, help='文本模式下列表最多打印多少行（默认 20）')
    p.add_argument('--plot', help='ggplot 类函数：把图存成 PNG（配合 call/plot 用）')
    p.add_argument('--width', type=float, default=9)
    p.add_argument('--height', type=float, default=5)


def _fn_args(p):
    p.add_argument('--arg', action='append', metavar='k=v', help='给函数传参，可重复')
    p.add_argument('--args', dest='args_json', help='给函数传参（一整段 JSON）')


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    _common(common)
    sub_ap = argparse.ArgumentParser(
        prog='ankir', description='ankiR（R 包）分析入口：留存、负荷、弱项、预测、图表')
    sub = sub_ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('list', parents=[common], help='列出 ankiR 的导出函数（可 grep 标题）')
    p.add_argument('--grep', help='按函数名/标题过滤')
    p.set_defaults(func=cmd_list)

    for name, (fn, desc) in PRESETS.items():
        p = sub.add_parser(name, parents=[common], help='%s（%s）' % (desc, fn))
        _fn_args(p)
        p.set_defaults(func=lambda a, fn=fn: _execute(a, fn))

    p = sub.add_parser('due', parents=[common],
                       help='到期/负荷（不调 R，Anki 口径）：今天待复习、逾期、未来 14 天')
    p.add_argument('--days', type=int, default=14, help='未来多少天（默认 14）')
    p.set_defaults(func=cmd_due)

    p = sub.add_parser('call', parents=[common], help='直接调任意 ankiR 函数')
    p.add_argument('fn', help='函数名（先 list 查）')
    _fn_args(p)
    p.set_defaults(func=lambda a: _execute(a, a.fn))

    p = sub.add_parser('plot', parents=[common], help='画图并落 PNG（默认 output\\reports\\ankir\\<fn>.png）')
    p.add_argument('fn', help='绘图函数名，如 anki_plot_heatmap')
    _fn_args(p)
    p.set_defaults(func=lambda a: _execute(a, a.fn))

    args = sub_ap.parse_args(argv)
    if args.cmd == 'plot' and not args.plot:
        args.plot = os.path.join(WSP.OUTPUT, 'reports', 'ankir', args.fn + '.png')
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
