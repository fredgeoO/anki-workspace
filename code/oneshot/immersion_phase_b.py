# -*- coding: utf-8 -*-
"""等 A 阶段（1,916 个新词：例句卡 + 素材卡）跑完，接着跑 B 阶段。

B 阶段＝用户 2026-10-15 追加的要求：**core6000/考级里已有的词**也补例句卡，
只进例句牌组（``--to example``，不建素材生词卡），纯粹用来练对白听力。

为什么要等：两个阶段都用 ``immersionkit`` 的 ``fetch/gen/write``，而这三个阶段
靠 ``data/immersion/latest.json`` 串起来 —— 同时跑会互相踩计划文件，只能串行。

用法：``python code/oneshot/immersion_phase_b.py``（后台跑，A 阶段跑完自动接上）。
"""
import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'execution'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, _HERE)

import immersion_batch as B      # noqa: E402
import paths as WSP              # noqa: E402
import textio                    # noqa: E402

DATA = WSP.DATA_IMMERSION


def log(msg):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


def wait_for(path, timeout, poll=60):
    """等 ``path`` 里的 chunks 记录数达到 total_chunks。→ True 表示 A 阶段跑完了。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            prog = json.loads(textio.read_text(path))
            done = len(prog.get('chunks') or {})
            total = prog.get('total_chunks') or 0
            if total and done >= total:
                bad = [k for k, v in (prog.get('chunks') or {}).items()
                       if v.get('status') == 'error']
                log('A 阶段记录 %d/%d 块（出错 %d 块）→ 开始 B 阶段'
                    % (done, total, len(bad)))
                return True
            log('等 A 阶段… %d/%d 块' % (done, total))
        except FileNotFoundError:
            log('等 A 阶段…（进度文件还没写出来）')
        except Exception as exc:                     # noqa: BLE001
            log('读进度失败（继续等）：%s' % exc)
        time.sleep(poll)
    log('⚠ 等了 %.1f 小时 A 阶段还没跑完，B 阶段不启动（避免踩 latest.json）'
        % (timeout / 3600.0))
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description='A 阶段跑完后接 B 阶段（core6000/考级 补例句卡）')
    ap.add_argument('--watch', default=os.path.join(DATA, 'batch_progress.json'))
    ap.add_argument('--words-file', default=os.path.join(DATA, 'words_known.txt'))
    ap.add_argument('--progress', default=os.path.join(DATA, 'batch_progress_known.json'))
    ap.add_argument('--chunk-size', type=int, default=150)
    ap.add_argument('--timeout-hours', type=float, default=16.0)
    a = ap.parse_args(argv)

    WSP.ensure()
    log('守护启动：等 %s' % os.path.relpath(a.watch, WSP.ROOT))
    if not wait_for(a.watch, a.timeout_hours * 3600):
        return 2
    log('B 阶段开始：%s（--keep-known --to example）'
        % os.path.relpath(a.words_file, WSP.ROOT))
    return B.main(['--words-file', a.words_file, '--chunk-size', str(a.chunk_size),
                   '--keep-known', '--to', 'example', '--progress', a.progress])


if __name__ == '__main__':
    raise SystemExit(main())
