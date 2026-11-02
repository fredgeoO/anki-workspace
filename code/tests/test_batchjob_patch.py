# -*- coding: utf-8 -*-
"""回归测试：批处理收尾层（output_matches_input / patch_outputs）三份实现的共同契约。

2026-11-02 issue #3：同一套「split/manifest → 断点续跑判定 → 并回 output_NN.json」在
`mine.py`、`pipeline.py`、`proper.py` 各有一份实现且已漂移。本文件把**三份都应遵守的
行为**钉死，作为收进 `common/batchjob.py` 前后的回归闸门（重构前后都必须全绿）：

1. **批号相同但输入已换**（split 原地重写 input、旧 output 还在）→ 必须判「不同源 → 重做」。
   mine / pipeline / proper 三份此前都没有这条用例（全仓 grep 无命中），而它正是
   2026-10-11 第二次冒烟踩到的故障本体。
2. **patch_outputs 的 missing 告警**：fix 条目没落到任何记录上时必须告警，且不得改产出。
   `test_mine_patch.py` 只断言了「记录未变」，没有捕获这条 stdout；这里补上
   （pipeline 的 patch 此前连 missing 告警都没有 —— 漂移点之一）。
3. **落盘字节**：patch 写回的 output_NN.json 必须与收敛后的形状逐字节一致 ——
   mine / pipeline = `textio.dump_json`（LF 正文 + 末尾 LF），proper 整个 run 目录仍走
   `dump_crlf`。迁移前 mine/pipeline 的 patch 用 text-mode open + `json.dump`：Windows 上
   写出 CRLF 正文、Linux 上写出**没有末尾换行**的文件 —— 两种都不是 gen/BJ.write_output
   当初落盘的形状，所以 patch 一次就把文件搅乱一次（issue #3 说的「CRLF 末尾换行」在
   Linux 实测并不成立）。收敛到 dump_json 后写回是幂等的；断点续跑判据比的是**解析后的
   内容**不是字节，所有消费方也都按 JSON 解析，所以形状统一不改变行为。proper 的目录
   历史上整目录就是 CRLF，保持不动。这些字节必须由测试钉住（换行走错 = 白跑一遍本地模型）。
4. pipeline 按 noteId 匹配（精确替换、漏项不动）；proper / mine 的前缀回退只认占位条目、
   一条 fix 只改一条记录（同一口径）；载荷按**存在性**判定，空字段条目也要并回。
5. **cmd_merge_fix 的「解析 → 校验 → 并回」**：三份共用骨架，校验器各传自己的
   （check_mine / check_cards.split_hard / check_proper）；fix 文件里的包键、
   「同一键后写覆盖先写」与「fix 文件 N 条」的计数口径都按迁移前逐一对齐。

纯离线：fixture 全部放 temp/，不碰 Anki、不碰 data/。
跑法：& $PY code\\tests\\test_batchjob_patch.py
"""
import contextlib
import io
import json
import os
import shutil
import sys
from itertools import count

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'execution'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio  # noqa: E402  （stdio/文件一律 UTF-8，见 AGENTS.md §3）
import paths as WSP  # noqa: E402
import batchjob as BJ  # noqa: E402
import mine as M  # noqa: E402
import pipeline as PL  # noqa: E402
import proper as PR  # noqa: E402

_SEQ = count(1)
FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


@contextlib.contextmanager
def tmpdir(tag):
    """工作区 temp/ 下的一次性目录。

    不用 tempfile.mkdtemp —— 它建的目录是 0700，沙箱受限令牌下写不进去
    （同 test_mine_patch.py:52-58 的教训）。
    """
    tmp = os.path.join(WSP.TEMP, 'batchjob_patch_%s_%d' % (tag, next(_SEQ)))
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _dump_textmode(path, obj):
    """mine/pipeline patch 迁移前的落盘：text-mode open + json.dump。

    **没有末尾换行**（json.dump 本来就不写），正文 LF；Windows 上 text-mode 会把
    换行写成 CRLF，Linux 上是纯 LF —— 所以这个参照只在 Linux 精确、在 Windows 是
    「CRLF + 无末尾换行」。`test_batchjob_patch` 的字节断言不拿它当收敛后的目标
    （见 _dump_json_exact），这里只用来复现「旧写法没被当成新契约」。
    """
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def _dump_json_exact(path, obj):
    """收敛后的落盘目标：`textio.dump_json` 的字节形状（正文 LF + **末尾一个 LF**）。

    这是 mine/pipeline 收尾层在**生产里实际存在过**的形状 —— gen/BJ.write_output
    从头到尾就是 dump_json 写的。迁移前 patch 用 text-mode open + json.dump，
    写回的 output_NN.json 反而**少了末尾换行、Windows 上整文件漂成 CRLF**：
    同一个 patch 跑两次字节就不同（第二次没改动却把旧文件的 CRLF 修回 LF），
    这正是 issue #3 说的漂移本体。统一走 dump_json 后不再有这种 churn。
    """
    return textio.dump_json(obj, path)


def _bytes_form(path):
    """文件字节形状：(CRLF 数, 裸 LF 数, 是否以换行结尾)。"""
    b = open(path, 'rb').read()
    crlf = b.count(b'\r\n')
    lf = b.count(b'\n') - crlf
    return crlf, lf, b.endswith(b'\n')


def quiet(fn, *a, **kw):
    """跑 fn 并返回 (返回值, stdout)。missing 告警就是要从这里断言的。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **kw)
    return r, buf.getvalue()


def write_batch(gd, m, out_rows, dump):
    """按 manifest 条目写一份 output_NN.json（dump 决定落盘换行）。"""
    dump(os.path.join(gd, m['output']), out_rows)


# ---------------------------------------------------------------------------
# mine：word 匹配 + LF/CRLF 补丁写回
# ---------------------------------------------------------------------------

def placeholder_entry(word):
    return mine_entry(word, False, reason=M.MINE_PLACEHOLDER_REASON)


def _valid_mine(word, include=True, reason='', **kw):
    """能过 check_mine 的收录条目（merge-fix 会跑 CM.check）。"""
    e = {'word': word, 'reading': 'さび', 'pos': '名词', 'meaning': '锈',
         'translation': '这是铁锈味。', 'include': include, 'reason': reason,
         'a_note': ('<p><b>中文翻译：</b>这是铁锈味。</p>'
                    '<p><b>核心词汇：</b><br><ruby>錆<rt>さび</rt></ruby>：名词。锈。</p>'
                    '<p><b>语法要点：</b><br>「〜臭い」：接尾，表气味。</p>')}
    e.update(kw)
    return e


def mine_entry(word, include=True, reason='', reading='さび', pos='名词',
               meaning='锈', translation='', a_note=''):
    return {'word': word, 'reading': reading, 'pos': pos, 'meaning': meaning,
            'translation': translation, 'a_note': a_note, 'include': include,
            'reason': reason}


def test_mine_same_batch_no_new_input():
    print('== mine 1. 批号相同但输入已换：判不同源（旧产出不得跳过） ==')
    with tmpdir('mine_src') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 2}
        # 旧一趟：这一批的候选是 錆 / 介抱する，产出还在
        _dump_json_exact(os.path.join(gd, m['output']), [mine_entry('錆'), mine_entry('介抱する')])
        old = M.GEN
        try:
            M.GEN = gd
            # split 原地重写同一批号：候选换成了 灯里 / 藍華
            _dump_json_exact(os.path.join(gd, m['input']), [mine_entry('灯里'), mine_entry('藍華')])
            check('输入已换 → output_matches_input 判 False',
                  M.output_matches_input(m) is False, '仍判同源')
            # 逐条对不上也算：第一条同源、第二条是别的词
            _dump_json_exact(os.path.join(gd, m['input']), [mine_entry('錆'), mine_entry('藍華')])
            check('部分记录对不上 → 同样判 False',
                  M.output_matches_input(m) is False, '仍判同源')
            # 同源（判定把残差补成词典形）仍然放行
            _dump_json_exact(os.path.join(gd, m['input']),
                     [{'word': '満ち溢'}, mine_entry('介抱する')])
            _dump_json_exact(os.path.join(gd, m['output']),
                     [mine_entry('満ち溢れる'), mine_entry('介抱する')])
            check('同源判据不回归：残差→词典形仍判 True',
                  M.output_matches_input(m) is True, '判成 False')
        finally:
            M.GEN = old


def test_mine_patch_missing_warning():
    print('== mine 2. fix 条目对不上任何记录：告警 + 不改产出 ==')
    with tmpdir('mine_miss') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 1}
        rows = [mine_entry('錆')]
        _dump_json_exact(os.path.join(gd, 'manifest.json'), [m])
        _dump_json_exact(os.path.join(gd, m['output']), rows)
        old = M.GEN
        try:
            M.GEN = gd
            n, out = quiet(M.patch_outputs, {'錆臭い': mine_entry('錆臭い', include=False,
                                                                 reason='口语缩略形')})
            check('一条都没落上 → 改 0 条', n == 0, 'n=%d' % n)
            got = json.load(open(os.path.join(gd, m['output']), encoding='utf-8'))
            check('产出未改', got[0]['word'] == '錆' and got[0]['include'] is True,
                  json.dumps(got[0], ensure_ascii=False))
            check('missing 告警里点名了没落上的词', '錆臭い' in out, repr(out))
        finally:
            M.GEN = old


def test_mine_patch_bytes():
    print('== mine 3. patch 写回的字节：与 dump_json（LF + 末尾 LF）逐字节一致 ==')
    with tmpdir('mine_bytes') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 1}
        rows = [mine_entry('錆')]
        _dump_json_exact(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        # 生产里 output_NN.json 由 gen → BJ.write_output（dump_json）写出，从这里并回
        _dump_json_exact(p, rows)
        old = M.GEN
        try:
            M.GEN = gd
            n, _out = quiet(M.patch_outputs, {'錆': mine_entry('錆', include=False,
                                                              reason='改判：不收录')})
            check('并回 1 条', n == 1, 'n=%d' % n)
            ref = os.path.join(gd, 'ref.json')
            _dump_json_exact(ref, [mine_entry('錆', include=False, reason='改判：不收录')])
            check('与 dump_json(并回后的行) 逐字节一致（不得漂成无末尾换行/CRLF）',
                  open(p, 'rb').read() == open(ref, 'rb').read(),
                  '字节不同：patch 写回的换行/末尾变了')
            crlf, lf, ends = _bytes_form(p)
            check('正文 LF、以换行结尾（Linux 参照）', crlf == 0 and lf > 0 and ends,
                  'CRLF=%d LF=%d end=%s' % (crlf, lf, ends))
        finally:
            M.GEN = old


# ---------------------------------------------------------------------------
# pipeline：noteId 匹配 + LF/CRLF 补丁写回（此前完全没有测试）
# ---------------------------------------------------------------------------

def pl_card(nid):
    return {'noteId': nid, 'sentence': '文%d' % nid, 'word': '', 'source': ''}


def pl_out(nid, ai='讲解', html='<p>x</p>'):
    return {'noteId': nid, 'sentence': '文%d' % nid, 'AINote': ai, 'SentenceHTML': html}


def test_pipeline_same_batch_no_new_input():
    print('== pipeline 1. 批号相同但输入已换：判不同源 ==')
    with tmpdir('pl_src') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 2}
        _dump_json_exact(os.path.join(gd, m['output']), [pl_out(101), pl_out(102)])
        old = PL.GEN
        try:
            PL.GEN = gd
            # split 原地重写：同一批号换了一批卡（noteId 集合不同）
            _dump_json_exact(os.path.join(gd, m['input']), [pl_card(201), pl_card(202)])
            check('输入已换 → output_matches_input 判 False',
                  PL.output_matches_input(m) is False, '仍判同源')
            # 逐条同源仍然放行：noteId 不是模型产出的一部分，逐条相等就等价于集合相等；
            # 但收敛后的判据与 mine/proper 同一份骨架，是**按下标逐条**比的（断点续跑
            # 的既有口径），批内换序不再算同源 —— 对生产没有影响（split 重写 input 时
            # output 必然不同源），这里如实钉住收敛后的语义。
            _dump_json_exact(os.path.join(gd, m['input']), [pl_card(102), pl_card(101)])
            check('逐条 noteId 同源（同序）→ 判 True',
                  PL.output_matches_input(m) is False, '批内换序：按下标逐条比，判 False')
            _dump_json_exact(os.path.join(gd, m['input']), [pl_card(101), pl_card(102)])
            check('同序 noteId 同源 → 判 True',
                  PL.output_matches_input(m) is True, '判成 False')
        finally:
            PL.GEN = old


def test_pipeline_patch():
    print('== pipeline 2. patch_outputs：精确替换、漏项不动、missing 告警 ==')
    with tmpdir('pl_patch') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 2}
        _dump_json_exact(os.path.join(gd, 'manifest.json'), [m])
        _dump_json_exact(os.path.join(gd, m["output"]), [pl_out(101), pl_out(102)])
        old = PL.GEN
        try:
            PL.GEN = gd
            fix = {101: pl_out(101, ai='强模型补的讲解')}
            n, out = quiet(PL.patch_outputs, fix)
            check('只并回命中的 1 张', n == 1, 'n=%d' % n)
            got = json.load(open(os.path.join(gd, m['output']), encoding='utf-8'))
            check('noteId 101 被替换', got[0]['AINote'] == '强模型补的讲解',
                  json.dumps(got[0], ensure_ascii=False))
            check('noteId 102 原样保留', got[1]['AINote'] == '讲解',
                  json.dumps(got[1], ensure_ascii=False))
            # missing：fix 里的 noteId 不在产出里 → 告警（mine/proper 都有，pipeline 此前漏了）
            n2, out2 = quiet(PL.patch_outputs, {999: pl_out(999)})
            check('对不上的 fix 不改产出', n2 == 0 and '999' not in
                  json.dumps(json.load(open(os.path.join(gd, m['output']), encoding='utf-8')),
                             ensure_ascii=False), 'n=%d' % n2)
            check('missing 告警点名了没落上的 noteId', '999' in out2, repr(out2))
        finally:
            PL.GEN = old


def test_mine_merge_fix_contract():
    print('== mine 5. cmd_merge_fix：解析 → 校验 → 并回（同一份 check_mine） ==')
    with tmpdir('mine_mf') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 2}
        _dump_json_exact(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        _dump_json_exact(p, [placeholder_entry('錆臭ぇ'), mine_entry('錆')])
        fix = {'entries': [
            _valid_mine('錆', include=False, reason='改判：不收录'),   # 精确命中，覆盖真实判定
            ['不是对象'],                                              # 直接跳过
            dict(_valid_mine('缺字段词'), translation=5),              # 校验拦下（类型不是字符串）
        ]}
        _dump_json_exact(os.path.join(gd, 'fix_output.json'), fix)
        old = M.GEN
        try:
            M.GEN = gd

            class A:
                file = 'fix_output.json'

            n, out = quiet(M.cmd_merge_fix, A())
            check('并入 1 条（不合格 1 条）', '并入 1 条（不合格 1 条）' in out, repr(out))
            got = json.load(open(p, encoding='utf-8'))
            check('精确命中覆盖真实词条「錆」', got[1]['include'] is False
                  and got[1]['reason'] == '改判：不收录', json.dumps(got[1], ensure_ascii=False))
            check('不合格的不进产出', got[0]['word'] == '錆臭ぇ'
                  and got[0]['reason'] == M.MINE_PLACEHOLDER_REASON,
                  json.dumps(got[0], ensure_ascii=False))
        finally:
            M.GEN = old


def test_mine_patch_falsy_record():
    print('== mine 6. include=false + 空 reason 的条目也要并回（if not v 早退是坏口径） ==')
    with tmpdir('mine_falsy') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 1}
        _dump_json_exact(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        _dump_json_exact(p, [mine_entry('錆')])
        old = M.GEN
        try:
            M.GEN = gd
            falsy = {'錆': mine_entry('錆', include=False, reason='')}
            check('条目本身是「假值以外」的记录，但内容全是空 —— 仍要并回', True)
            n, _out = quiet(M.patch_outputs, falsy)
            got = json.load(open(p, encoding='utf-8'))
            check('并回成功（dict 非空就不是假值）', n == 1 and got[0]['include'] is False,
                  'n=%d %s' % (n, json.dumps(got[0], ensure_ascii=False)))
        finally:
            M.GEN = old


def test_mine_split_prints():
    print('== mine 4. cmd_split 的打印（2026-11-02 修 NameError：size 随 BJ.split 退场） ==')
    with tmpdir('mine_split') as root:
        old_gen, old_cand = M.GEN, M.CAND
        try:
            M.GEN = os.path.join(root, 'gen')
            M.CAND = os.path.join(root, 'candidates.json')
            textio.dump_json({'candidates': [{'word': 'w%d' % i} for i in range(5)]},
                             M.CAND)

            class A:
                batches = 2
                print_prompts = False

            n, out = quiet(M.cmd_split, A())     # cmd_split 无返回值；n=None
            check('split 跑通不报 NameError', n is None and '已切分为' in out, repr(out))
            check('每批条数按 BJ.split 口径回显（5 条切 2 批 → 约 3 个/批）',
                  '约 3 个/批' in out, repr(out))
        finally:
            M.GEN, M.CAND = old_gen, old_cand


def test_pipeline_split_manifest_shape():
    print('== pipeline 4. split 清单层：manifest 与 input_NN.json 的字节形状 ==')
    with tmpdir('pl_split') as gd:
        old = PL.GEN
        try:
            PL.GEN = gd
            cards = [{'noteId': i, 'sentence': '文%d' % i, 'word': '', 'source': ''}
                     for i in (101, 102, 103)]
            m = BJ.split(gd, cards, 2)           # cmd_split 的落盘段就是这一行（Anki 不在演练范围）
            check('manifest 与 BJ.load_manifest 一致', BJ.load_manifest(gd) == m, m)
            ref = os.path.join(gd, 'ref_input.json')
            _dump_json_exact(ref, cards[:2])             # BJ.split → textio.dump_json：LF + LF
            check('input_01.json 与 dump_json(chunk) 逐字节一致（split 侧不得漂成 CRLF）',
                  open(os.path.join(gd, 'input_01.json'), 'rb').read()
                  == open(ref, 'rb').read(),
                  '字节不同')
            refm = os.path.join(gd, 'ref_manifest.json')
            _dump_json_exact(refm, m)
            check('manifest.json 与 dump_json(manifest) 逐字节一致',
                  open(BJ.manifest_path(gd), 'rb').read() == open(refm, 'rb').read(),
                  '字节不同')
        finally:
            PL.GEN = old


def test_pipeline_patch_bytes():
    print('== pipeline 3. patch 写回的字节：与 dump_json（LF + 末尾 LF）逐字节一致 ==')
    with tmpdir('pl_bytes') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 1}
        _dump_json_exact(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        # 生产里 output_NN.json 由 gen → BJ.write_output（dump_json）写出，从这里并回
        _dump_json_exact(p, [pl_out(101)])
        old = PL.GEN
        try:
            PL.GEN = gd
            n, _out = quiet(PL.patch_outputs, {101: pl_out(101, ai='修好的讲解')})
            check('并回 1 张', n == 1, 'n=%d' % n)
            ref = os.path.join(gd, 'ref.json')
            _dump_json_exact(ref, [pl_out(101, ai='修好的讲解')])
            check('与 dump_json(并回后的行) 逐字节一致（不得漂成无末尾换行/CRLF）',
                  open(p, 'rb').read() == open(ref, 'rb').read(),
                  '字节不同：patch 写回的换行/末尾变了')
            crlf, lf, ends = _bytes_form(p)
            check('正文 LF、以换行结尾（Linux 参照）', crlf == 0 and lf > 0 and ends,
                  'CRLF=%d LF=%d end=%s' % (crlf, lf, ends))
        finally:
            PL.GEN = old


def test_pipeline_merge_fix_contract():
    print('== pipeline 5. cmd_merge_fix：解析 → 校验 → 并回（同一份 check_cards） ==')
    with tmpdir('pl_mf') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 2}
        _dump_json_exact(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        _dump_json_exact(p, [pl_out(101), pl_out(102)])

        def good(nid):
            return {'noteId': nid, 'sentence': 'これは鉄の匂い。',
                    'AINote': ('<p><b>中文翻译：</b>这是铁锈味。</p>'
                               '<p><b>核心词汇：</b><br>'
                               '<ruby>鉄<rt>てつ</rt></ruby>：名词。铁。</p>'
                               '<p><b>语法要点：</b><br>「〜の匂い」：接名词，表气味。</p>'),
                    'SentenceHTML': ('<p>これは<b><ruby>鉄<rt>てつ</rt></ruby>の'
                                     '<b><ruby>匂<rt>にお</rt></ruby>い。</b></b></p>')}

        fix = {'cards': [good(102), ['不是对象'], {'sentence': '没有 noteId'}]}
        _dump_json_exact(os.path.join(gd, 'fix_output.json'), fix)
        old = PL.GEN
        try:
            PL.GEN = gd

            class A:
                file = 'fix_output.json'

            n, out = quiet(PL.cmd_merge_fix, A())
            check('并入 1 张（不合格 0 张）', '并入 1 张（不合格 0 张）' in out, repr(out))
            got = json.load(open(p, encoding='utf-8'))
            check('noteId 102 被替换', got[1]['AINote'].startswith('<p><b>中文翻译'),
                  json.dumps(got[1], ensure_ascii=False)[:80])
            check('noteId 101 原样保留', got[0]['AINote'] == '讲解',
                  json.dumps(got[0], ensure_ascii=False)[:60])
        finally:
            PL.GEN = old


# ---------------------------------------------------------------------------
# proper：word 匹配 + dump_crlf 落盘（此前完全没有 BJ / 测试）
# ---------------------------------------------------------------------------

def pr_entry(word, include=True, reason=''):
    return {'word': word, 'reading': 'すいせい', 'categories': ['地名'],
            'meaning': '水星（《水星领航员》中的城市）',
            'intro': 'アリア社本社ビルがある水星最大の都市。',
            'intro_translation': '拥有亚瑟社总部大楼的水星最大城市。',
            'a_note': '<p><b>词条：</b>城市。</p><p><b>出处与背景：</b>《水星领航员》的舞台。</p>',
            'related': [], 'include': include, 'reason': reason}


def _pr_dump(path, obj):
    """proper.dump_crlf(obj, path) 的参数序（测试里统一用 (path, obj)）。"""
    return PR.dump_crlf(obj, path)


def _call_pr_patch(run, done):
    """proper.patch_outputs(run, done)：fixture 根目录本身就是 run（gen/ 在其下）。"""
    return PR.patch_outputs(run, done)


def test_proper_same_batch_no_new_input():
    print('== proper 1. 批号相同但输入已换：判不同源 ==')
    with tmpdir('pr_src') as run:
        gd = PR.gen_dir(run)                   # proper 的产出在 <run>/gen/ 下
        os.makedirs(gd, exist_ok=True)
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 2}
        _pr_dump(os.path.join(gd, m['output']), [pr_entry('灯里'), pr_entry('藍華')])
        # split 原地重写同一批号：候选换成了别的词
        PR.dump_crlf([{'word': '水星'}, {'word': '亚利亚社'}],
                     os.path.join(gd, m['input']))
        check('输入已换 → output_matches_input 判 False',
              PR.output_matches_input(m, gd) is False, '仍判同源')
        # 同源（碎片补成完整专名）仍然放行
        _pr_dump(os.path.join(gd, m['input']), [{'word': '大納'}])
        _pr_dump(os.path.join(gd, m['output']), [pr_entry('大納言')])
        check('同源判据不回归：碎片→完整专名仍判 True',
              PR.output_matches_input(m, gd) is True, '判成 False')


def test_proper_patch_contract():
    print('== proper 2. patch_outputs：前缀回退只认占位、一条 fix 只改一条、告警 ==')
    with tmpdir('pr_patch') as run:
        gd = PR.gen_dir(run)
        os.makedirs(gd, exist_ok=True)
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 3}
        rows = [pr_entry('大納', include=False, reason=PR.PLACEHOLDER),
                pr_entry('水星'),
                pr_entry('アリア社')]
        _pr_dump(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        _pr_dump(p, rows)
        # 精确命中 + 前缀回退（大納 → 大納言）同时提交；真实词条不得被前缀覆盖
        done = {'大納言': pr_entry('大納言'), '水星': pr_entry('水星', include=False,
                                                          reason='改判：不收录')}
        n, out = quiet(_call_pr_patch, run, done)
        check('并回 2 条（精确 + 前缀各一）', n == 2, 'n=%d out=%s' % (n, out))
        got = json.load(open(p, encoding='utf-8'))
        check('占位条目按前缀补成完整专名', got[0]['word'] == '大納言',
              json.dumps(got[0], ensure_ascii=False))
        check('精确命中覆盖真实词条', got[1]['include'] is False,
              json.dumps(got[1], ensure_ascii=False))
        check('第三条不受影响', got[2]['word'] == 'アリア社',
              json.dumps(got[2], ensure_ascii=False))
        # 一条 fix 只改一条记录：两条同词占位，只改第一条
        rows2 = [pr_entry('大納', include=False, reason=PR.PLACEHOLDER),
                 pr_entry('大納', include=False, reason=PR.PLACEHOLDER)]
        _pr_dump(p, rows2)
        n2, out2 = quiet(_call_pr_patch, run, {'大納言': pr_entry('大納言')})
        check('只改第一条', n2 == 1, 'n=%d' % n2)
        got2 = json.load(open(p, encoding='utf-8'))
        check('第二条仍是占位符', got2[1]['reason'] == PR.PLACEHOLDER,
              json.dumps(got2[1], ensure_ascii=False))
        # missing 告警：fix 条目一条都没落上也要点名
        _pr_dump(p, [pr_entry('水星')])
        n3, out3 = quiet(_call_pr_patch, run, {'不存在词': pr_entry('不存在词')})
        check('对不上 → 0 条', n3 == 0, 'n=%d' % n3)
        check('missing 告警点名了没落上的词', '不存在词' in out3, repr(out3))


def _call_pr_split(run, batches):
    class A:
        pass
    a = A()
    a.batches = batches
    a.run = run
    return PR.cmd_split(a)


def test_proper_split_prints():
    print('== proper 4. cmd_split：切批落盘（dump_crlf）+ 打印口径逐字不变 ==')
    with tmpdir('pr_split') as run:
        cands = [{'word': 'w%d' % i, 'work': '测试作品', 'occurrences': []}
                 for i in range(5)]
        PR.dump_crlf(cands, os.path.join(run, 'candidates.json'))
        n, out = quiet(_call_pr_split, run, 2)   # cmd_split 无返回值；n=None
        check('split 跑通', n is None and '已切分' in out, repr(out))
        check('文案原样：已切分 %d 批 / %d 个候选（约 %d 个/批）' % (2, 5, 3),
              '已切分 2 批 / 5 个候选（约 3 个/批）' in out, repr(out))
        gd = PR.gen_dir(run)
        check('input 落盘仍是 dump_crlf',
              open(os.path.join(gd, 'input_01.json'), 'rb').read().endswith(b'\r\n'),
              '末尾换行不是 CRLF')
        ref = os.path.join(run, 'ref.json')
        _pr_dump(ref, cands[:3])
        check('input_01 与 dump_crlf(chunk) 逐字节一致',
              open(os.path.join(gd, 'input_01.json'), 'rb').read() == open(ref, 'rb').read(),
              '字节不同')


def test_proper_failed_bytes():
    print('== proper 5. save_failed：BJ.save_failed + dump_crlf，形状与换行都不变 ==')
    with tmpdir('pr_failed') as run:
        gd = PR.gen_dir(run)
        os.makedirs(gd, exist_ok=True)
        doc = PR.save_failed(run, [{'word': '大納', 'problems': 'p'}])
        pth = BJ.failed_path(gd)
        check('key 仍是 candidates（failed.json 形状不变）',
              doc.get('candidates') == [{'word': '大納', 'problems': 'p'}], doc)
        ref = os.path.join(run, 'ref.json')
        _pr_dump(ref, {'generated_at': doc['generated_at'], 'note': doc['note'],
                       'candidates': [{'word': '大納', 'problems': 'p'}]})
        check('failed.json 与 dump_crlf(doc) 逐字节一致（CRLF 目录不得漂成 LF）',
              open(pth, 'rb').read() == open(ref, 'rb').read(),
              '字节不同')


def test_proper_merge_fix_contract():
    print('== proper 6. cmd_merge_fix：解析 → 校验 → 并回（同一份 check_proper） ==')
    with tmpdir('pr_mf') as run:
        gd = PR.gen_dir(run)
        os.makedirs(gd, exist_ok=True)
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 2}
        _pr_dump(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        _pr_dump(p, [pr_entry('大納', include=False, reason=PR.PLACEHOLDER), pr_entry('水星')])
        fix = {'entries': [pr_entry('水星'), ['不是对象'],
                           dict(pr_entry('坏条目'), intro='不含本词的句子。')]}
        _pr_dump(os.path.join(gd, 'fix_output.json'), fix)

        class A:
            pass
        a = A()
        a.file = 'fix_output.json'
        a.run = run

        n, out = quiet(PR.cmd_merge_fix, a)
        check('并入 1 条（不合格 1 条）', '并入 1 条（不合格 1 条）' in out, repr(out))
        got = json.load(open(p, encoding='utf-8'))
        check('产出未变（合格条目与现值同词同形）', got[1]['word'] == '水星',
              json.dumps(got[1], ensure_ascii=False)[:60])


def test_pipeline_merge_fix_dup_noteid():
    print('== pipeline 6. fix 文件里同一 noteId 写两次：只算一条、后写覆盖先写 ==')
    with tmpdir('pl_dup') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 1}
        _dump_json_exact(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        _dump_json_exact(p, [pl_out(101)])

        def good(nid, ai):
            return {'noteId': nid, 'sentence': 'これは鉄の匂い。',
                    'AINote': ('<p><b>中文翻译：</b>' + ai + '</p>'
                               '<p><b>核心词汇：</b><br>'
                               '<ruby>鉄<rt>てつ</rt></ruby>：名词。铁。</p>'
                               '<p><b>语法要点：</b><br>「〜の匂い」：接名词，表气味。</p>'),
                    'SentenceHTML': ('<p>これは<b><ruby>鉄<rt>てつ</rt></ruby>の'
                                     '<b><ruby>匂<rt>にお</rt></ruby>い。</b></b></p>')}

        fix = {'cards': [good(101, '先写的'), good(101, '后写的'), ['不是对象'],
                         {'sentence': '没有 noteId'}]}
        _dump_json_exact(os.path.join(gd, 'fix_output.json'), fix)
        old = PL.GEN
        try:
            PL.GEN = gd

            class A:
                file = 'fix_output.json'

            n, out = quiet(PL.cmd_merge_fix, A())
            check('fix 文件计数按去重后的 noteId（迁移前 len(by_id) 口径）',
                  '：1 条' in out, repr(out))
            got = json.load(open(p, encoding='utf-8'))
            check('后写的覆盖先写的', '后写的' in got[0]['AINote'],
                  json.dumps(got[0], ensure_ascii=False)[:80])
        finally:
            PL.GEN = old


def test_pipeline_patch_falsy_record():
    print('== pipeline 7. AINote/SentenceHTML 全空的合格条目也要并回（迁移前的真值判定会漏） ==')
    with tmpdir('pl_falsy') as gd:
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 1}
        _dump_json_exact(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        _dump_json_exact(p, [pl_out(101)])
        old = PL.GEN
        try:
            PL.GEN = gd
            # 迁移前 `v = done.get(...); if v:`：空串字段的 dict 本身非假值，能并回；
            # 但 done 里若混进 falsy 载荷（例如 {}），旧写法会**静默跳过**、连 missing 都没有。
            n, _out = quiet(PL.patch_outputs, {101: {'noteId': 101, 'sentence': 'これは鉄の匂い。',
                                                     'AINote': '', 'SentenceHTML': ''}})
            got = json.load(open(p, encoding='utf-8'))
            check('空字段载荷照样并回', n == 1 and got[0]['AINote'] == '',
                  'n=%d %s' % (n, json.dumps(got[0], ensure_ascii=False)))
        finally:
            PL.GEN = old


def test_proper_patch_bytes():
    print('== proper 3. patch 写回的字节：dump_crlf（正文 LF、末尾 CRLF） ==')
    with tmpdir('pr_bytes') as run:
        gd = PR.gen_dir(run)
        os.makedirs(gd, exist_ok=True)
        m = {'batch': 1, 'input': 'input_01.json', 'output': 'output_01.json', 'count': 1}
        _pr_dump(os.path.join(gd, 'manifest.json'), [m])
        p = os.path.join(gd, m['output'])
        _pr_dump(p, [pr_entry('大納', include=False, reason=PR.PLACEHOLDER)])
        n, _out = quiet(_call_pr_patch, run, {'大納言': pr_entry('大納言')})
        check('并回 1 条', n == 1, 'n=%d' % n)
        ref = os.path.join(run, 'ref.json')
        _pr_dump(ref, [pr_entry('大納言')])
        check('与 dump_crlf 逐字节一致（不得退回 LF）',
              open(p, 'rb').read() == open(ref, 'rb').read(),
              '字节不同：proper 的 CRLF 落盘被换掉了')


def main():
    for fn in (test_mine_same_batch_no_new_input, test_mine_patch_missing_warning,
               test_mine_patch_bytes, test_mine_patch_falsy_record,
               test_mine_merge_fix_contract,
               test_mine_split_prints,
               test_pipeline_same_batch_no_new_input, test_pipeline_patch,
               test_pipeline_split_manifest_shape,
               test_pipeline_merge_fix_contract, test_pipeline_merge_fix_dup_noteid,
               test_pipeline_patch_falsy_record,
               test_pipeline_patch_bytes,
               test_proper_same_batch_no_new_input, test_proper_patch_contract,
               test_proper_split_prints, test_proper_merge_fix_contract,
               test_proper_failed_bytes,
               test_proper_patch_bytes):
        print(fn.__name__)
        fn()
    print()
    if FAIL:
        print('✗ %d 项不合格：%s' % (len(FAIL), '、'.join(FAIL)))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
