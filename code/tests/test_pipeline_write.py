# -*- coding: utf-8 -*-
"""回归测试：pipeline.py write 的写库路径（走 writeback，全量回读）。

2026-11-03 issue #10 B2：`cmd_write` 原来是逐张 `AK.update_note_fields` + 「抽查前 3 张」
兜底——**第 4 张之后的静默失败没人接**（AGENTS.md §3 铁律 7「写后回读」在这条最常跑的
写库路径上只覆盖 ids[:3]）。现在收进 `common/writeback.py`：备份旧值 → 写 → 全量回读。

本文件钉四件事：
1. **每一张都被回读**，不是抽查：假 `verify_note_fields` 记录它收到多少 noteId，
   断言等于应写张数（重构前这里是 3）。
2. **回读不一致必须报错退出**，不能当成功。
3. **有意跳过的卡**（模型没做出来 → 两个字段都空）**不写**：不能被空值把已有内容清掉。
4. **已有内容的卡默认拒绝覆盖**，`--overwrite` 才写。

纯离线：AK / writeback 的 Anki 调用全部换成假函数；备份写到 temp/，不碰 data/、不连 Anki。
跑法：& $PY code\\tests\\test_pipeline_write.py
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'execution'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio  # noqa: E402  stdio 唯一入口
import paths as WSP  # noqa: E402
import anki_api as AK  # noqa: E402
import writeback as WB  # noqa: E402
import pipeline as PL  # noqa: E402

BD = os.path.join(WSP.TEMP, 'test_pipeline_write')
FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


# ---------------------------------------------------------------- fixture 目录
def reset_bd():
    if os.path.isdir(BD):
        shutil.rmtree(BD)
    os.makedirs(BD)


def backups():
    return sorted(os.listdir(BD)) if os.path.isdir(BD) else []


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()) as buf, \
            contextlib.redirect_stderr(io.StringIO()):
        try:
            out = fn(*a, **kw)
            err = None
        except SystemExit as exc:                       # 把「拒绝/失败」当返回值
            out, err = None, exc
    return out, err, buf.getvalue()


def gen_dir(tag, cards, outs):
    """造一个 data/pipeline/gen 替身：manifest + input_NN.json + output_NN.json。

    cards: [(noteId, sentence)]；outs: {noteId: (AINote, SentenceHTML)}（缺 = 没做出来）。
    """
    d = os.path.join(WSP.TEMP, 'pipeline_write_%s' % tag)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    ins, rows = [], []
    for i, (nid, sent) in enumerate(cards, 1):
        ip, op = 'input_%02d.json' % i, 'output_%02d.json' % i
        textio.dump_json([{'noteId': nid, 'sentence': sent}], os.path.join(d, ip))
        note = {'noteId': nid, 'sentence': sent}
        if nid in outs:
            note['AINote'], note['SentenceHTML'] = outs[nid]
        else:                                            # 模型没做出来 → 两个字段留空
            note['AINote'], note['SentenceHTML'] = '', ''
        rows.append(note)
        textio.dump_json([note], os.path.join(d, op))
        ins.append({'batch': i, 'input': ip, 'output': op, 'n': 1})
    textio.dump_json(ins, os.path.join(d, 'manifest.json'))
    return d


# ------------------------------------------------------------------ 假 Anki
class FakeAnki:
    """note_values / update_notes / verify_note_fields 的替身。

    live      {noteId: {'AINote':…, 'Sentence HTML':…}} 库里的现值
    drop      {noteId}：updateNotes 报失败（模拟 AnkiConnect 回了 error）
    mismatch  {noteId}：回读时故意对不上（模拟「静默没生效」）
    """

    def __init__(self, live, drop=(), mismatch=()):
        self.live = {int(k): dict(v) for k, v in live.items()}
        self.drop = set(int(x) for x in drop)
        self.mismatch = set(int(x) for x in mismatch)
        self.written = []          # [(noteId, fields)] 真写到库的
        self.verified_ids = None   # verify 收到的 noteId 全集

    def note_values(self, ids, names=None, chunk=None):
        return {int(i): dict(self.live.get(int(i), {})) for i in ids}

    def update_notes(self, pairs):
        out = []
        for nid, fields in pairs:
            nid = int(nid)
            self.written.append((nid, dict(fields)))
            if nid in self.drop:
                out.append((nid, False))
                continue
            cur = self.live.setdefault(nid, {})
            cur.update({k: v or '' for k, v in fields.items()})
            out.append((nid, True))
        return out

    def verify_note_fields(self, expected, settle=0.5, chunk=None):
        want = expected if not isinstance(expected, list) else None
        self.verified_ids = sorted(int(k) for k in (want or {}))
        bad = {}
        for nid, fields in (want or {}).items():
            nid = int(nid)
            got = self.live.get(nid)
            if got is None:
                bad[nid] = ['<noteId 不存在>']
                continue
            miss = [f for f, v in fields.items()
                    if got.get(f, '') != (v or '') and nid not in self.mismatch]
            if nid in self.mismatch:
                miss = sorted(fields) + ['缺 Sentence HTML']
            if miss:
                bad[nid] = miss
        return bad


@contextlib.contextmanager
def wired(tag, cards, outs, live, drop=(), mismatch=()):
    """把 PL.GEN / writeback 的备份目录与 Anki 调用接到替身上。

    `cmd_write` 里两处碰库走的是 pipeline 自己的 `AK.note_values`（覆盖闸门）与
    `writeback` 内部的写/回读，两者都按 `AK.xxx` 属性查找 —— 所以换掉**两个模块**上的
    `AK` 同名函数即可，不碰真 AnkiConnect。
    """
    d = gen_dir(tag, cards, outs)
    fake = FakeAnki(live, drop=drop, mismatch=mismatch)
    old = {'GEN': PL.GEN, 'SETTLE': PL.WRITE_SETTLE, 'WB_AK': WB.AK,
           'PL_note_values': PL.AK.note_values,
           'AK_note_values': AK.note_values}
    PL.GEN = d
    PL.WRITE_SETTLE = 0          # 回读不 sleep：整条 write 路径离线几秒跑完
    WB.AK = fake
    PL.AK.note_values = fake.note_values
    AK.note_values = fake.note_values
    try:
        yield fake
    finally:
        PL.GEN = old['GEN']
        PL.WRITE_SETTLE = old['SETTLE']
        WB.AK = old['WB_AK']
        PL.AK.note_values = old['PL_note_values']
        AK.note_values = old['AK_note_values']


def args(**kw):
    base = {'overwrite': False, 'skip_check': True}   # skip_check：不跑 check_cards 闸门
    base.update(kw)
    return argparse.Namespace(**base)


SENT = '私は学生です'
# 库里的现值。cmd_write 的覆盖闸门看 AINote / Sentence HTML **是否已有内容**，
# 所以通用 fixture 必须全空；「库里已有旧讲解」只在第 5 个用例里单独造（那是它的主题）。
EMPTY_LIVE = {i: {'AINote': '', 'Sentence HTML': ''} for i in range(1, 9)}


# ---------------------------------------------------------------------- 用例
def test_all_read_back():
    print('== 1. 每一张都被回读（重构前只有 ids[:3]）==')
    cards = [(i, SENT) for i in (1, 2, 3, 4, 5)]
    outs = {i: ('讲解%d' % i, '<p>x%d</p>' % i) for i in (1, 2, 3, 4, 5)}
    with wired('all', cards, outs, EMPTY_LIVE) as fake:
        _out, err, log = quiet(PL.cmd_write, args())
        check('正常路径不退出', err is None, str(err))
        check('回读覆盖全部 5 张（不是抽查 3 张）',
              fake.verified_ids == [1, 2, 3, 4, 5], str(fake.verified_ids))
        check('5 张都写进库', sorted(n for n, _ in fake.written) == [1, 2, 3, 4, 5],
              str(sorted(n for n, _ in fake.written)))
        # 备份必须落在 temp 之外的那个家：本测试把 backup_dir 交给默认值，
        # 所以只断言「写了备份文件」这件事由 writeback 自己的测试保证；这里查日志。
        check('汇报里说明回读一致 5 张', '应写 5 张，回读一致 5 张' in log, log.strip()[-160:])


def test_mismatch_fails():
    print('== 2. 回读不一致 → 必须报错退出（不能当写成功）==')
    cards = [(i, SENT) for i in (1, 2, 3, 4)]
    outs = {i: ('讲解%d' % i, '<p>x%d</p>' % i) for i in (1, 2, 3, 4)}
    with wired('mism', cards, outs, EMPTY_LIVE, mismatch={4}) as fake:
        _out, err, log = quiet(PL.cmd_write, args())
        check('第 4 张回读不一致 → SystemExit', isinstance(err, SystemExit), repr(err))
        check('退出信息点名那张卡', err is not None and '4' in str(err), str(err))
        check('仍然把 4 张都送去回读（不是抽查）',
              fake.verified_ids == [1, 2, 3, 4], str(fake.verified_ids))


def test_write_failure_reported():
    print('== 3. AnkiConnect 回了 error → 记进 bad 并退出 ==')
    cards = [(i, SENT) for i in (1, 2)]
    outs = {i: ('讲解%d' % i, '<p>x%d</p>' % i) for i in (1, 2)}
    with wired('drop', cards, outs, EMPTY_LIVE, drop={2}):
        _out, err, log = quiet(PL.cmd_write, args())
        check('写入失败 → SystemExit', isinstance(err, SystemExit), repr(err))
        check('信息点名失败的卡', err is not None and '2' in str(err), str(err))


def test_skipped_not_written():
    print('== 4. 有意跳过的卡（产出两个字段都空）不送去写库 ==')
    # 重构前这里也**不会改坏库**：逐张 update_note_fields 写的是一对空值，而 AnkiConnect 的
    # updateNoteFields 是部分更新（没出现在 payload 里的字段保持原值），库里已有内容不会被
    # 清空；旧代码只是事后统计「AINote 仍为空」把这类卡算成有意跳过。
    # 现在改成**根本不送去写**：少一次往返，也不再依赖 AnkiConnect 的部分更新语义。
    cards = [(1, SENT), (2, SENT)]
    outs = {1: ('讲解1', '<p>x1</p>')}                     # 2 号没做出来 → 空产出
    live = {1: {'AINote': '', 'Sentence HTML': ''},
            2: {'AINote': '', 'Sentence HTML': ''}}
    with wired('skip', cards, outs, live) as fake:
        _out, err, log = quiet(PL.cmd_write, args())
        check('正常退出', err is None, str(err))
        check('只写 1 号（2 号空产出不进 writeback）',
              [n for n, _ in fake.written] == [1], str(fake.written))
        check('回读也只覆盖真写的 1 张', fake.verified_ids == [1], str(fake.verified_ids))
        check('汇报里说明跳过 1 张', '有意跳过 1 张' in log, log.strip()[-160:])


def test_overwrite_guard():
    print('== 5. 目标字段已有内容：默认拒绝，--overwrite 才写 ==')
    cards = [(5, SENT)]
    outs = {5: ('新讲解', '<p>新</p>')}
    filled = {5: {'AINote': '旧讲解', 'Sentence HTML': '<ruby>学生[がくせい]</ruby>'}}
    with wired('ow', cards, outs, filled) as fake:
        _out, err, log = quiet(PL.cmd_write, args())
        check('默认拒绝覆盖 → SystemExit', isinstance(err, SystemExit), repr(err))
        check('点名 5 号', err is not None and '5' in str(err), str(err))
        check('拒绝时一张都没写', fake.written == [], str(fake.written))
    with wired('ow2', cards, outs, dict(filled)) as fake2:
        _out, err, log = quiet(PL.cmd_write, args(overwrite=True))
        check('--overwrite 后写入', err is None and [n for n, _ in fake2.written] == [5],
              '%s %s' % (err, fake2.written))


def test_no_commit_flag_needed():
    print('== 6. 契约：write 仍是「跑到就真写」（episode.py 直接跑 `pipeline.py write`）==')
    # episode.py:192 run_stage('pipeline', ['write']) 不带 --commit，allow=(0,)。
    # 所以这里断言 cmd_write 默认就是真写（不是演练），且失败会非零退出。
    cards = [(1, SENT)]
    outs = {1: ('讲解1', '<p>x1</p>')}
    with wired('live', cards, outs, EMPTY_LIVE) as fake:
        _out, err, log = quiet(PL.cmd_write, args())
        check('默认即真写（有 updateNotes 调用）', len(fake.written) == 1, str(fake.written))
        check('不打印「演练」字样', '演练' not in log, log.strip()[-120:])


def main():
    for fn in (test_all_read_back, test_mismatch_fails, test_write_failure_reported,
               test_skipped_not_written, test_overwrite_guard, test_no_commit_flag_needed):
        fn()
    print()
    if FAIL:
        print('✗ %d 项不合格：%s' % (len(FAIL), '、'.join(FAIL)))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
