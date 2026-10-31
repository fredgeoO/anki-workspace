# -*- coding: utf-8 -*-
"""批处理作业的清单层：split / manifest / 断点续跑 / failed.json。

`mine.py` 与 `pipeline.py` 的这三件事本来是一字不差地各写一遍：

1. 把候选切成 N 批 → ``input_NN.json`` + ``manifest.json``；
2. 生成前跳过「已存在且与当前输入同源」的产出（断点续跑）；
3. 把本地模型没做出来的条目写进 ``failed.json``，全部通过时清掉旧清单。

2026-11-01 抽到这里。**生成循环仍留在各自脚本**：mine 按词重问、pipeline 按
noteId 重问，闸门不同，先不硬并。

约定：一批 = ``{'batch': 1, 'input': 'input_01.json',
'output': 'output_01.json', 'count': 14}``。
"""

from __future__ import annotations

import datetime as dt
import os
import time

import textio


def manifest_path(workdir):
    return os.path.join(workdir, 'manifest.json')


def failed_path(workdir):
    return os.path.join(workdir, 'failed.json')


def split(workdir, items, batches, *, prefix='input', output_prefix='output'):
    """把 ``items`` 切成 ``batches`` 批，写 input_NN.json + manifest.json。

    返回 manifest（与落盘内容一致）。空批不写文件、不进 manifest。
    """
    items = list(items)
    n = max(1, int(batches))
    size = (len(items) + n - 1) // n
    os.makedirs(workdir, exist_ok=True)
    manifest = []
    for b in range(n):
        chunk = items[b * size:(b + 1) * size]
        if not chunk:
            continue
        name = '%s_%02d.json' % (prefix, b + 1)
        textio.dump_json(chunk, os.path.join(workdir, name))
        manifest.append({'batch': b + 1, 'input': name,
                         'output': '%s_%02d.json' % (output_prefix, b + 1),
                         'count': len(chunk)})
    textio.dump_json(manifest, manifest_path(workdir))
    return manifest


def load_manifest(workdir, hint=''):
    path = manifest_path(workdir)
    if not os.path.exists(path):
        raise SystemExit('没有 %s%s' % (path, ('；' + hint) if hint else ''))
    return textio.load_json(path)


def todo(manifest, workdir, *, force=False, same_source=None, label='批'):
    """返回还要做的批次：没产出、或产出与当前输入不同源（``same_source(m)`` 为假）。

    同源判定由调用方给（mine 按 word、pipeline 按 noteId），这里只负责跳过与提示。
    """
    out = []
    for m in manifest:
        out_path = os.path.join(workdir, m['output'])
        if force or not os.path.exists(out_path):
            out.append(m)
            continue
        if same_source is not None and same_source(m):
            print('  %s%02d %s 已存在且与输入同源 → 跳过（--force 重做）'
                  % (label, m['batch'], m['output']))
            continue
        print('  ⚠ %s%02d %s 已存在但与本批输入对不上（同一批号的旧产出）→ 重做'
              % (label, m['batch'], m['output']))
        out.append(m)
    return out


def run(batches, workdir, run_batch, *, note='', key='cards'):
    """跑一批已筛选的批次（``todo()`` 的返回值）。

    ``run_batch(m, rows)`` 返回 ``(输出行, 失败行, (请求数, prompt, completion))``。
    本函数负责：读 input、写 output、累计 token、汇总 failed.json（全空时清掉）。
    返回 ``(failed, totals, elapsed, failed_path)``。
    """
    failed = []
    totals = [0, 0, 0]
    t0 = time.time()
    for m in batches:
        rows = textio.load_json(os.path.join(workdir, m['input']))
        out, bad, usage = run_batch(m, rows)
        write_output(workdir, m['output'], out)
        failed.extend(bad or [])
        for i, v in enumerate((usage or (0, 0, 0))[:3]):
            totals[i] += int(v or 0)
    elapsed = time.time() - t0
    if failed:
        save_failed(workdir, failed, note=note, key=key)
        path = failed_path(workdir)
    else:
        clear_failed(workdir)
        path = ''
    print('本地模型结束：%d 次请求，prompt %d + completion %d tokens，耗时 %.0fs'
          % (totals[0], totals[1], totals[2], elapsed))
    return failed, totals, elapsed, path


def write_output(workdir, name, rows):
    textio.dump_json(rows, os.path.join(workdir, name))


def save_failed(workdir, rows, note, key='cards'):
    """写 failed.json。``key`` 沿用各自历史形状（pipeline=cards / mine=candidates）。"""
    doc = {'generated_at': dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
           'note': note,
           key: list(rows)}
    textio.dump_json(doc, failed_path(workdir))
    return doc


def clear_failed(workdir):
    path = failed_path(workdir)
    if os.path.exists(path):
        os.remove(path)
    return not os.path.exists(path)
