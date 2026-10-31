# -*- coding: utf-8 -*-
"""回归测试：batchjob 清单层（split / todo / failed）。

挡四件事：
1. 分批数、每批条数、manifest 与落盘一致；
2. 断点续跑只跳过「同源」产出，不同源必须重做；
3. --force 全部重做；
4. failed.json 的 key 形状（pipeline=cards / mine=candidates）与清理。

纯离线：只写 temp/test_batchjob，不碰 Anki、不碰 data/。
跑法：& $PY code\\tests\\test_batchjob.py
"""
import contextlib
import io
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio  # noqa: E402  stdio 唯一入口
import paths as WSP  # noqa: E402
import batchjob as BJ  # noqa: E402

BD = os.path.join(WSP.TEMP, 'test_batchjob')
FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def reset_bd():
    if os.path.isdir(BD):
        shutil.rmtree(BD)
    os.makedirs(BD)


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def test_split():
    reset_bd()
    items = [{'word': 'w%d' % i} for i in range(5)]
    m = BJ.split(BD, items, 2)
    check('5 条切 2 批 → 2 批', len(m) == 2, m)
    check('每批 3/2', [x['count'] for x in m] == [3, 2], [x['count'] for x in m])
    check('manifest 落盘一致', BJ.load_manifest(BD) == m, BJ.load_manifest(BD))
    check('input 文件存在',
          all(os.path.exists(os.path.join(BD, x['input'])) for x in m), m)
    check('output 命名', [x['output'] for x in m] == ['output_01.json', 'output_02.json'], m)
    check('内容不丢', sum(x['count'] for x in m) == 5, m)


def test_split_more_batches_than_items():
    reset_bd()
    m = BJ.split(BD, [{'word': 'a'}, {'word': 'b'}], 5)
    check('空批不写进 manifest', len(m) == 2, m)
    check('批号连续', [x['batch'] for x in m] == [1, 2], m)


def test_todo():
    reset_bd()
    m = BJ.split(BD, [{'word': 'a'}, {'word': 'b'}, {'word': 'c'}], 3)
    BJ.write_output(BD, m[0]['output'], [{'ok': 1}])
    todo = quiet(BJ.todo, m, BD, same_source=lambda x: True)
    check('同源 → 跳过第 1 批', [x['batch'] for x in todo] == [2, 3], todo)
    todo = quiet(BJ.todo, m, BD, same_source=lambda x: False)
    check('不同源 → 重做第 1 批', [x['batch'] for x in todo] == [1, 2, 3], todo)
    todo = quiet(BJ.todo, m, BD, force=True, same_source=lambda x: True)
    check('--force → 全部重做', [x['batch'] for x in todo] == [1, 2, 3], todo)


def test_failed():
    reset_bd()
    BJ.save_failed(BD, [{'noteId': 1}], note='n', key='cards')
    doc = textio.load_json(BJ.failed_path(BD))
    check('failed 文件存在', os.path.exists(BJ.failed_path(BD)), BJ.failed_path(BD))
    check('pipeline 形状 cards', doc.get('cards') == [{'noteId': 1}], doc)
    check('带 generated_at', bool(doc.get('generated_at')), doc)
    BJ.save_failed(BD, [{'word': 'a'}], note='n', key='candidates')
    doc = textio.load_json(BJ.failed_path(BD))
    check('mine 形状 candidates', doc.get('candidates') == [{'word': 'a'}], doc)
    check('清理成功', BJ.clear_failed(BD) and not os.path.exists(BJ.failed_path(BD)), '')
    check('重复清理不报错', BJ.clear_failed(BD) is True, '')


def test_run():
    reset_bd()
    m = BJ.split(BD, [{'id': 1}, {'id': 2}], 2)
    calls = []

    def rb(row, rows):
        calls.append(row['batch'])
        out = [{'id': r['id'], 'v': 1} for r in rows]
        bad = [{'noteId': r['id']} for r in rows] if row['batch'] == 2 else []
        return out, bad, (1, 10, 5)

    failed, totals, _elapsed, path = quiet(BJ.run, m, BD, rb, note='n', key='cards')
    check('run 跑了 2 批', calls == [1, 2], calls)
    check('run 写 output',
          all(os.path.exists(os.path.join(BD, x['output'])) for x in m), m)
    check('run 汇总 failed', len(failed) == 1, failed)
    check('run token 累计', totals == [2, 20, 10], totals)
    check('run 写 failed.json', bool(path) and os.path.exists(path), path)


def test_run_all_ok_clears():
    reset_bd()
    m = BJ.split(BD, [{'id': 1}], 1)
    BJ.save_failed(BD, [{'x': 1}], note='n')
    failed, _totals, _elapsed, _path = quiet(
        BJ.run, m, BD, lambda row, rows: ([{'id': 1}], [], (1, 1, 1)))
    check('全通过 → 清 failed',
          failed == [] and not os.path.exists(BJ.failed_path(BD)), failed)


def main():
    for fn in (test_split, test_split_more_batches_than_items, test_todo, test_failed,
               test_run, test_run_all_ok_clears):
        print(fn.__name__)
        fn()
    reset_bd()
    print()
    if FAIL:
        print('✗ %d 项失败：%s' % (len(FAIL), FAIL))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
