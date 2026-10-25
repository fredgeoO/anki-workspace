# -*- coding: utf-8 -*-
"""回归测试：阶段四 merge-fix 的前缀回退（2026-10-12 事故）

事故：`mine.py merge-fix` 只提交了 1 条 fix（word=`錆臭ぇ`），却报「并入 2 条」——
同批里真实收录的 `錆` 恰好是 `錆臭ぇ` 的前缀，被前缀回退整条覆盖成排除条目，
产出出现两条 `錆臭ぇ`、`write` 被堵死。

跑法（只用工作区的 python）：
  & $PY code\tests\test_mine_patch.py
不碰 Anki、不碰 data/：全部在临时目录里造 manifest/output 再断言。
"""
import json
import os
import shutil
import sys
from itertools import count

_SEQ = count(1)

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'execution'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio  # noqa: E402  （stdio/文件一律 UTF-8，见 AGENTS.md §3）
import mine as M  # noqa: E402

FAIL = []


def entry(word, include, reason='', reading='', pos='', meaning='',
          translation='', a_note=''):
    return {'word': word, 'reading': reading, 'pos': pos, 'meaning': meaning,
            'translation': translation, 'a_note': a_note, 'include': include,
            'reason': reason}


def placeholder(word):
    """gen 判定失败留下的占位条目（与 cmd_gen 写出的形状一致）。"""
    return entry(word, False, reason=M.MINE_PLACEHOLDER_REASON)


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def run_patch(records, done, batches=1):
    """在临时 GEN 目录里跑一次 patch_outputs，返回 (改了几条, 产出, stdout)。

    临时目录放工作区的一次性文件区 temp/ 里（沙箱只允许写工作区，系统 temp 会被拒），
    且用 os.makedirs 而不是 tempfile.mkdtemp —— mkdtemp 建的目录是 0700，
    沙箱受限令牌下反而写不进去。
    """
    base = M.WSP.TEMP
    tmp = os.path.join(base, 'mine_patch_%d' % next(_SEQ))
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    old = M.GEN
    try:
        M.GEN = tmp
        manifest = []
        for b in range(1, batches + 1):
            manifest.append({'batch': b, 'input': 'input_%02d.json' % b,
                             'output': 'output_%02d.json' % b, 'count': len(records)})
            _dump(os.path.join(tmp, 'output_%02d.json' % b), records)
        _dump(os.path.join(tmp, 'manifest.json'), manifest)
        n = M.patch_outputs(done)
        got = json.load(open(os.path.join(tmp, 'output_01.json'), encoding='utf-8'))
        return n, got
    finally:
        M.GEN = old
        shutil.rmtree(tmp, ignore_errors=True)


def _dump(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def main():
    print('== 1. 事故复现：fix 的 `錆臭ぇ` 不得覆盖真实词条 `錆` ==')
    out = [placeholder('錆臭ぇ'),
           entry('介抱する', True, reading='かいほうする', pos='他动词', meaning='照顾'),
           entry('錆', True, reading='さび', pos='名词', meaning='锈')]
    fix = entry('錆臭ぇ', False, reason='口语缩略形，不单独建卡')
    n, got = run_patch(out, {'錆臭ぇ': fix})
    check('只并入 1 条（不是 2 条）', n == 1, 'n=%d' % n)
    check('占位条目被替换', got[0]['word'] == '錆臭ぇ' and got[0]['include'] is False
          and got[0]['reason'] == '口语缩略形，不单独建卡', json.dumps(got[0], ensure_ascii=False))
    check('真实词条「錆」原样保留', got[2]['word'] == '錆' and got[2]['include'] is True
          and got[2]['reading'] == 'さび', json.dumps(got[2], ensure_ascii=False))
    check('没有出现两条同词记录', len({r['word'] for r in got}) == len(got))

    print('== 2. 词典形补齐（前缀回退的本意）仍然工作 ==')
    out = [placeholder('ひきこ'), entry('錆', True, reading='さび', pos='名词')]
    fix = entry('ひきこもる', True, reading='ひきこもる', pos='自动词', meaning='闷居')
    n, got = run_patch(out, {'ひきこもる': fix})
    check('占位条目按前缀补成词典形', n == 1 and got[0]['word'] == 'ひきこもる', json.dumps(got, ensure_ascii=False))
    check('同批真实词条不受影响', got[1]['word'] == '錆' and got[1]['include'] is True)

    print('== 3. 精确命中可以覆盖真实判定（人工复核修正就该覆盖） ==')
    out = [entry('錆', True, reading='さび', pos='名词', meaning='锈')]
    fix = entry('錆', False, reason='改判：不收录')
    n, got = run_patch(out, {'錆': fix})
    check('精确命中替换生效', n == 1 and got[0]['include'] is False
          and got[0]['reason'] == '改判：不收录')

    print('== 4. 一条 fix 只改一条记录（同批出现两条同词记录时不再往上盖） ==')
    out = [placeholder('錆臭ぇ'), placeholder('錆臭ぇ')]
    fix = entry('錆臭ぇ', False, reason='口语缩略形')
    n, got = run_patch(out, {'錆臭ぇ': fix})
    check('只改第一条', n == 1, 'n=%d' % n)
    check('第二条仍是占位符', got[1]['reason'] == M.MINE_PLACEHOLDER_REASON,
          got[1]['reason'])

    print('== 5. fix 条目对不上任何记录：不改产出（且会告警） ==')
    out = [entry('錆', True, reading='さび', pos='名词')]
    fix = entry('錆臭い', False, reason='口语缩略形')
    n, got = run_patch(out, {'錆臭い': fix})
    check('不动任何记录', n == 0 and got[0]['word'] == '錆' and got[0]['include'] is True)

    print('== 6. judge_mine：返回词属于同组另一条候选时不得前缀回退 ==')
    group = [{'word': '錆'}, {'word': '錆臭ぇ'}]
    got = {'錆臭ぇ': valid('錆臭ぇ')}
    ok, bad = M.judge_mine(group, got)
    check('錆臭ぇ 拿到条目', '錆臭ぇ' in ok, str(list(ok)))
    check('錆 判为「模型没有返回这条候选」', bad.get('錆') == '模型没有返回这条候选', str(bad))

    print('== 7. judge_mine：真正的词典形补齐照旧 ==')
    ok, bad = M.judge_mine([{'word': 'ひきこ'}], {'ひきこもる': valid('ひきこもる')})
    check('ひきこ 按前缀拿到 ひきこもる', ok.get('ひきこ', {}).get('word') == 'ひきこもる', str(bad))

    print('== 8. conjugation_variants：サ変動詞要能生成「〜し／〜した／〜して」 ==')
    v = M.P.conjugation_variants('介抱する')
    check('含 介抱し', '介抱し' in v, str(sorted(v)))
    check('含 介抱して', '介抱して' in v)
    check('含 介抱した', '介抱した' in v)
    check('不再产废变体 介抱すます', '介抱すます' not in v, str(sorted(v)))
    check('例句定位命中（介抱し 在「介抱していただいた…」里）',
          '介抱し' in M.P.norm('介抱していただいたうえに<br>食事まで…｡'))
    check('既有口径不回归：食べる→食べて', '食べて' in M.P.conjugation_variants('食べる'))
    check('既有口径不回归：読む→読みます', '読みます' in M.P.conjugation_variants('読む'))
    check('既有口径不回归：高い→高く', '高く' in M.P.conjugation_variants('高い'))
    # 「する」本身（len 2）走的是老路径，会产出一堆废变体（すます／すた…）——
    # 这是既有的噪声，不在本次修复范围；只确认老路径没被我改动波及。
    check('「する」仍按老路径返回自身', 'する' in M.P.conjugation_variants('する'))

    print('== 9. 模型把字符串字段返回成数字：报「不合格」，不许抛异常 ==')
    # 2026-10-12 第 02 集实测：本地模型把 translation 返回成 int，
    # check_mine 里 (x or '').strip() 直接 AttributeError，整批 gen 连已判好的条目全废。
    bad_e = valid('錆')
    bad_e['translation'] = 5
    hard, _soft = M.CM.check(bad_e)
    check('报成硬错误而不是崩', any('类型不是字符串' in h for h in hard), str(hard))
    hard, _soft = M.CM.check({'word': 5, 'include': True, 'reading': 'さび'})
    check('word 成数字也不崩', bool(hard), str(hard))
    check('非 dict 条目也不崩', bool(M.CM.check(['不是对象'])[0]))
    ok, bad = M.judge_mine([{'word': '錆'}], {'錆': {'word': '錆', 'include': True,
                                                   'reading': 'さび', 'pos': '名词',
                                                   'meaning': '锈', 'translation': 5,
                                                   'a_note': '', 'reason': ''}})
    check('judge_mine 把它判为未通过（不进产出）',
          '錆' in bad and any('类型不是字符串' in v for v in bad.values()), str(bad))

    print('== 10. include 被写成 "false" / 0：不能当成收录 ==')
    # bool("false") 是 True —— 不归一就会把**明确排除**的条目写进库。
    check('as_bool：false/0/None/no → False',
          [M.CM.as_bool(x) for x in ('false', 0, None, 'no')] == [False] * 4,
          str([M.CM.as_bool(x) for x in ('false', 0, None, 'no')]))
    check('as_bool：True/"true" → True',
          M.CM.as_bool('true') is True and M.CM.as_bool(True) is True)
    e = valid('錆')
    e['include'] = 'false'
    check('include="false" 不会被当收录', any('没有 reason' in h for h in M.CM.check(e)[0]),
          str(M.CM.check(e)[0]))

    print('== 11. judge_mine 对畸形条目返回「判定异常」，不许把整批带崩 ==')
    ok, bad = M.judge_mine([{'word': '錆'}], {'錆': ['形状离谱，不是对象']})
    check('返回判定异常而不是抛异常',
          '錆' in bad and bad['錆'].startswith('判定异常'), str(bad))

    print('== 12. strip_html / norm 收到非字符串不崩 ==')
    check('strip_html(int) 返回文本', M.P.strip_html(5) == '5', repr(M.P.strip_html(5)))
    check('norm(int) 返回字符串', isinstance(M.P.norm(5), str), repr(M.P.norm(5)))

    print('== 13. 同源必要条件：写库时才报太晚，判定阶段就要拦（2026-10-12 食わして事故）==')
    # 候选是口语缩略形时，模型"好心"补成词典形 → 互不为子串 → write 判 mismatch。
    # origin_possible 是 same_origin 的**必要条件**，在这里即判即给可执行提示。
    check('残差→词典形（往后接）仍然放行', M.origin_possible('満ち溢', '満ち溢れる')
          and M.origin_possible('ひきこ', 'ひきこもる'))
    check('原样回填放行', M.origin_possible('錆', '錆') and M.origin_possible('食わして', '食わして'))
    check('换成别的活用形/词典形被拦下',
          not M.origin_possible('食わして', '食わす')
          and not M.origin_possible('食わして', '食わせる')
          and not M.origin_possible('錆臭ぇ', '錆臭い'))
    check('非字符串也不抛', M.origin_possible(5, None) is False)

    got = {'食わして': dict(valid('食わして'), word='食わす')}
    ok, bad = M.judge_mine([{'word': '食わして'}], got)
    check('模型换成词典形 → 判不合格（而不是等 write 整批 mismatch）',
          '食わして' in bad and '不同源' in bad['食わして'], str(bad))
    check('重问提示里给了可执行的改法（保留候选作为子串）',
          '子串' in bad['食わして'] and 'a_note' in bad['食わして'], bad.get('食わして', ''))
    ok2, bad2 = M.judge_mine([{'word': '満ち溢'}], {'満ち溢れる': dict(valid('満ち溢れる'),
                                                                  word='満ち溢れる')})
    check('正常补成词典形照旧通过',
          bad2 == {} and ok2['満ち溢']['word'] == '満ち溢れる', '%s / %s' % (ok2, bad2))

    print()
    if FAIL:
        print('✗ %d 项不合格：%s' % (len(FAIL), '、'.join(FAIL)))
        raise SystemExit(1)
    print('✓ 全部通过')


def valid(word):
    """能过 check_mine 的收录条目（judge_mine 会跑 CM.check）。"""
    return {'word': word, 'reading': 'さび', 'pos': '名词', 'meaning': '锈',
            'translation': '这是铁锈味。', 'include': True, 'reason': '',
            'a_note': ('<p><b>中文翻译：</b>这是铁锈味。</p>'
                       '<p><b>核心词汇：</b><br><ruby>錆<rt>さび</rt></ruby>：名词。锈。</p>'
                       '<p><b>语法要点：</b><br>「〜臭い」：接尾，表气味。</p>')}


if __name__ == '__main__':
    main()
