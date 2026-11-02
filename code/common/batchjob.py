# -*- coding: utf-8 -*-
"""批处理作业的清单层 + 收尾层：split / manifest / 断点续跑 / failed.json / 并回。

`mine.py`、`pipeline.py`、`proper.py` 的这三件事本来就各写一遍（2026-11-02 issue #3
收敛掉最后一段）：

1. 把候选切成 N 批 → ``input_NN.json`` + ``manifest.json``；
2. 生成前跳过「已存在且与当前输入同源」的产出（断点续跑）；
3. 收尾：把强模型补做的 fix **解析 → 校验 → 并回**对应批次的 ``output_NN.json``，
   没修好的写进 ``failed.json``，全部通过时清掉旧清单。

2026-11-01 抽的是清单层（split / manifest / todo / run / failed）；收尾层
（``output_matches_input`` / ``patch_outputs`` / missing 告警）当时还留在三份本地实现里，
且已经漂移：pipeline 的 patch 没有 missing 告警、proper 整个没接上这一层、
mine 的 split 打印引用了随迁移退场的 ``size``（一跑就 NameError）。

**与匹配键无关的脚手架在这里，语义差异参数化**：

* ``key_of(rec)`` —— mine / proper 给「词形归一」（``P.norm``），pipeline 给 ``noteId``；
* ``validate(rec)`` —— 三处各传自己的校验器（check_mine / check_cards / check_proper）；
* ``dump=``       —— 落盘函数按目录选择：默认 ``textio.dump_json``（mine / pipeline 的
  gen 目录一直是 LF + 末尾 LF），proper 整个 run 目录历史上走 ``dump_crlf``，传它进来。

**生成循环与 fix_failed 仍留在各自脚本**（2026-11-01 定的边界不变）：mine 按词重问、
pipeline 按 noteId 重问、proper 多一个 ``--run`` 维度，闸门也不同，不硬并。

约定：一批 = ``{'batch': 1, 'input': 'input_01.json',
'output': 'output_01.json', 'count': 14}``。
"""

from __future__ import annotations

import datetime as dt
import re
import os
import time

import textio


def manifest_path(workdir):
    return os.path.join(workdir, 'manifest.json')


def failed_path(workdir):
    return os.path.join(workdir, 'failed.json')


def split(workdir, items, batches, *, prefix='input', output_prefix='output', dump=None):
    """把 ``items`` 切成 ``batches`` 批，写 input_NN.json + manifest.json。

    返回 manifest（与落盘内容一致）。空批不写文件、不进 manifest。
    ``dump`` 是落盘函数（默认 ``textio.dump_json``）：proper 的 run 目录整目录走
    ``dump_crlf``，由调用方传进来；分批算法本身只有一份。
    """
    dump = dump or textio.dump_json
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
        dump(chunk, os.path.join(workdir, name))
        manifest.append({'batch': b + 1, 'input': name,
                         'output': '%s_%02d.json' % (output_prefix, b + 1),
                         'count': len(chunk)})
    dump(manifest, manifest_path(workdir))
    return manifest


def load_manifest(workdir, hint=''):
    path = manifest_path(workdir)
    if not os.path.exists(path):
        raise SystemExit('没有 %s%s' % (path, ('；' + hint) if hint else ''))
    return textio.load_json(path)


_SKIP_MSG = '  批%02d %s 已存在且与输入同源 → 跳过（--force 重做）'
_REDO_MSG = '  ⚠ 批%02d %s 已存在但与本批输入对不上（同一批号的旧产出）→ 重做'


def todo(manifest, workdir, *, force=False, same_source=None, skip_fmt=_SKIP_MSG,
         redo_fmt=_REDO_MSG):
    """返回还要做的批次：没产出、或产出与当前输入不同源（``same_source(m)`` 为假）。

    同源判定由调用方给（mine 按 word、pipeline 按 noteId），这里只负责跳过与提示。
    提示文案三份脚本历史上就有两种措辞，逐字保留在参数里（非目标：不改 stdout）：
    mine / pipeline 用默认值（带产出文件名），proper 传自己那两条（不带）。
    """
    def say(fmt, m):
        # proper 的旧文案只有一个占位符（不带产出文件名）；按 fmt 实际需要的参数个数喂，
        # 而不是数 '%s' 字面量 —— 措辞里出现字面 %s 也不会误判。
        n = len(re.findall(r'%[-#0-9.]*[a-zA-Z]', fmt))
        print(fmt % ((m['batch'], m['output'])[:n]))

    out = []
    for m in manifest:
        out_path = os.path.join(workdir, m['output'])
        if force or not os.path.exists(out_path):
            out.append(m)
            continue
        if same_source is not None and same_source(m):
            say(skip_fmt, m)
            continue
        say(redo_fmt, m)
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


def save_failed(workdir, rows, note, key='cards', dump=None):
    """写 failed.json。``key`` 沿用各自历史形状（pipeline=cards / mine=candidates）。

    ``dump`` 是落盘函数（默认 ``textio.dump_json``）；proper 的 run 目录历史上整目录走
    ``dump_crlf``，由调用方传进来 —— failed.json 的**内容形状不变**，只有换行按目录选。
    """
    doc = {'generated_at': dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
           'note': note,
           key: list(rows)}
    (dump or textio.dump_json)(doc, failed_path(workdir))
    return doc


def clear_failed(workdir):
    path = failed_path(workdir)
    if os.path.exists(path):
        os.remove(path)
    return not os.path.exists(path)


# ============================================================================
# 收尾层（2026-11-02 issue #3）：同源判定 + 「解析 → 校验 → 并回」骨架
# ============================================================================

def same_source(m, workdir, key_of):
    """这一批的 output 是不是**当前 input** 的产出（断点续跑的唯一判据）。

    **只看文件名是不够的。** split 会原地重写 ``input_NN.json``，而上一趟的
    ``output_NN.json`` 还在、批号也一样 —— 那是**另一批**的产出，照它跳过就等于整批
    不判定（2026-10-11 第二次冒烟实测踩到，mine / pipeline / proper 同一课）。

    判据是逐条 ``key_of`` **同源**而不是相等：判定方的职责恰恰是把残差补成词典形
    （``満ち溢``→``満ち溢れる``、``大納``→``大納言``），字面本来就会变，所以允许
    「一方包含另一方」；``pipeline`` 的键是 noteId（不是模型产出的一部分），逐条相等
    与旧实现的「集合相等」等价。批内换序只有 split 会做，而 split 重写 input 时旧
    output 必然对不上 —— 所以按下标逐条比对生产没有影响（口径见测试）。

    读不动 / 条数不一致 / 任何一条对不上 → False（宁可重跑一遍本地模型，
    不能拿旧产出当已判定）。
    """
    ip = os.path.join(workdir, m['input'])
    op = os.path.join(workdir, m['output'])
    if not os.path.exists(op):
        return False
    try:
        src = textio.load_json(ip)
        got = textio.load_json(op)
    except (ValueError, TypeError, OSError):
        return False
    if len(src) != len(got):
        return False
    for a, b in zip(src, got):
        try:
            k1, k2 = key_of(a), key_of(b)
        except Exception:                       # noqa: BLE001  畸形记录一律算对不上
            return False
        if not k2 or not (k1 == k2 or (isinstance(k1, str) and isinstance(k2, str)
                                      and (k1 in k2 or k2 in k1))):
            return False
    return True


def patch_outputs(workdir, done, *, key_of, is_placeholder=None, dump=None):
    """把 ``{键: 条目}`` 并回对应批次的 output_NN.json，返回改动条数。

    三份实现（mine / pipeline / proper）里唯一同构的骨架，差异全部参数化：

    * ``key_of(rec)``：从**产出记录**取匹配键（词形归一 / noteId）。
      ``done`` 的键必须用同一个函数算出来。
    * ``is_placeholder(rec)``：给定时启用**前缀回退** —— 判定方把残差补成词典形
      （``ひきこ``→``ひきこもる``）时，允许落在占位条目上；**只认占位条目**，
      且回退到的词不能是本批另一条记录的原词（2026-10-12 「錆 / 錆臭ぇ」事故：
      前缀回退曾把同批真实收录的「錆」整条覆盖）。pipeline 不传 → 只做精确命中。
    * 载荷**按对象存在性**判定（``is not None``），不按真值：旧写法 ``if v:`` 在
      mine/proper 会把「include=false + 空 reason」这种**合法改判条目**静默跳过，
      pipeline 还会把漏项从 missing 名单里吞掉；一条 fix 只要被 parse 出来就必须有下落。
    * ``dump``：落盘函数，默认 ``textio.dump_json``；proper 传它自己的 ``dump_crlf``。

    完整性网（三份原本都有，pipeline 那份漏了 missing 告警 —— 就是漂移本体）：

    * **一条 fix 只改一条记录**：命中第二条就跳过并告警（同批两条同词本身就是坏数据，
      不该继续往上盖）；
    * **fix 条目一条都没落上**也要点名告警，而不是静默吞掉。
    """
    if not done:
        return 0
    manifest = load_manifest(workdir)
    dump = dump or textio.dump_json
    n = 0
    used = {}                                    # fix 条目 key → 改到了哪条记录
    for m in manifest:
        p = os.path.join(workdir, m['output'])
        if not os.path.exists(p):
            continue
        out = textio.load_json(p)
        exact = set()                            # 本批已有记录的原词（前缀回退要避开）
        for r in out:
            try:
                k = key_of(r)
            except Exception:                    # noqa: BLE001
                k = None
            if k is not None:
                exact.add(k)
        changed = False
        for i, rec in enumerate(out):
            try:
                key = key_of(rec)
            except Exception:                    # noqa: BLE001
                continue
            v, how = done.get(key), '精确'
            if v is None and is_placeholder is not None and is_placeholder(rec):
                longer = sorted((k for k in done
                                 if isinstance(k, str) and isinstance(key, str)
                                 and k.startswith(key) and len(k) > len(key)
                                 and k not in exact), key=len)
                if longer:
                    v, how = done[longer[-1]], '前缀'
            if v is None:                       # 载荷按存在性判定，不按真值（见 docstring）
                continue
            try:
                vk = key_of(v)
            except Exception:                    # noqa: BLE001
                continue
            where = '%s 第 %d 条' % (m['output'], i + 1)
            if vk in used:
                print('  ⚠ %s 已改过 %s，又命中 %s → 跳过（一条 fix 只改一条记录）'
                      % (vk, used[vk], where))
                continue
            out[i] = v
            used[vk] = where
            changed = True
            n += 1
            print('  并回 %s ← %s（%s匹配，原词 %r）' % (vk, where, how, key))
        if changed:
            # 落盘走 dump：mine / pipeline = textio.dump_json（LF + 末尾 LF），
            # proper = dump_crlf。断点续跑文件被 patch 改写过一次就再也回不到旧形状，
            # 所以这里必须由测试钉住（见 code/tests/test_batchjob_patch.py）。
            dump(out, p)
    missing = sorted(str(k) for k in done if k not in used)
    if missing:
        print('  ⚠ %d 条 fix 没落到任何记录上（与现有条目和占位条目都对不上，产出未改）：%s'
              % (len(missing), '、'.join(missing)))
    return n


def merge_fix(path, *, parse, validate, dict_keys=('entries', 'cards', 'outputs')):
    """收尾第一步：把 fix 文件（路径）里的条目**解析 → 校验**成 ``(ok, bad, total)``。

    * ``parse(item) -> (key, record) | None``：从一条 fix 里取键并拼出待校验记录；
      返回 None 表示这条根本不该进校验（不是对象 / 没有键）。
    * ``validate(record) -> [问题…]``：各脚本传自己的校验器（check_mine /
      check_cards.split_hard / check_proper），**与生成时同一份口径**。
      校验器自己出意外也算不合格，不中断整批。
    * ``dict_keys``：fix 文件是包一层对象时的取键顺序（mine/proper 用 entries/outputs，
      pipeline 用 cards）—— 各脚本的口径原样保留，不互相兜底。

    ``total`` = 解析出的**去重键数**（覆盖前），给调用方打「fix 文件 …：N 条」。
    返回 ``(ok, bad, total)``；并回交给 ``patch_outputs``，failed.json 的更新留在调用方
    （三处的剩余项算法不同）。
    """
    merge = textio.load_json(path)
    if isinstance(merge, dict):
        for k in dict_keys:                     # 按调用方给的键序取，不跨脚本兜底
            if merge.get(k):
                merge = merge[k]
                break
        else:
            merge = []
    ok, bad, seen = {}, {}, set()
    for item in merge:
        parsed = parse(item)
        if not parsed:
            continue
        key, rec = parsed
        if key is None or key == '':
            continue
        seen.add(key)
        try:
            problems = validate(rec)
        except Exception as e:                  # noqa: BLE001  校验器出意外也要报成不合格
            problems = ['校验异常：%s: %s' % (type(e).__name__, e)]
        if problems:
            bad[key] = '；'.join(problems)
        else:
            ok.pop(key, None)                   # 同一键后写的覆盖先写的（与迁移前一致）
            ok[key] = rec
    return ok, bad, len(seen)
