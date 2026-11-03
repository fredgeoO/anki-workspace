# -*- coding: utf-8 -*-
"""阶段五配音的「只补空字段」判据回归测试（mine_audio.plan_needs）。

跑法：`& $PY code\\tests\\test_mine_audio_need.py`

挡的是 2026-11-01 那次静默改数据：`apply` 旧逻辑拿「按来源例句卡算出来的目标值」
和字段现值比较，不一致就重写，于是**来源卡配不上、但卡上已挂着演员原声**的卡
（`部費`）被降级成 TTS 兜底。新判据只有一条：**字段为空才生成**。

覆盖：
* 两个字段都空 → 都生成；
* 句子字段已有原声（来源配不上）→ 保留，只补单词；
* 两个字段都已有 → 什么都不做（`todo` 为空）；
* 句子已有「不是本次会写的那个」TTS 文件 → 同样保留；
* `--force` → 两个字段都重算；
* `keep_diff_sent` 只在「保留的原声 ≠ 本次会写的值」时为真（供报告点名）。

全程不连 Anki：`gather()` 不参与，直接喂假 row。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
_EXEC = os.path.join(_WS, 'code', 'execution')
for _p in (_EXEC, os.path.join(_EXEC, 'core6000'), os.path.join(_EXEC, 'lesson')):
    sys.path.insert(0, _p)
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))

import textio  # noqa: E402,F401  stdio 统一走 textio（audit R2）
import mine_audio as MA  # noqa: E402

FAIL = []


def check(name, cond, got=None):
    if cond:
        print('  ✓ %s' % name)
    else:
        print('  ✗ %s%s' % (name, '' if got is None else '（got %r）' % (got,)))
        FAIL.append(name)


def row(nid, word, wa='', sa='', src_audio=None, src_exists=None):
    """作假 row：字段名与 gather() 产出的键一致（plan_needs 只读这几个）。"""
    src_audio = src_audio or []
    return {
        'noteId': nid,
        'word': word,
        'word_audio_field': wa,
        'sentence_audio_field': sa,
        'src_audio': src_audio,
        'src_exists': bool(src_audio) if src_exists is None else src_exists,
    }


def main():
    print('一、两个字段都空 → 都生成')
    rows, todo = MA.plan_needs([row(1, '部費')])
    r = rows[0]
    check('need_word', r['need_word'] is True)
    check('need_sent', r['need_sent'] is True)
    check('进 todo', len(todo) == 1)
    check('无原声 → sent_plan=tts', r['sent_plan'] == 'tts', r['sent_plan'])
    check('sent_value 指向 mine-sent-<nid>',
          r['sent_value'] == '[sound:%s]' % MA.sent_tts_name(1), r['sent_value'])

    print('二、句子已挂原声、但来源例句卡配不上 → 原样保留，只补单词')
    orig = 'ik_anime_fate_stay_night_unlimited_blade_works_000007030.mp3'
    rows, todo = MA.plan_needs([row(2, '部費', sa='[sound:%s]' % orig)])
    r = rows[0]
    check('need_word', r['need_word'] is True)
    check('need_sent 关掉', r['need_sent'] is False)
    check('进 todo（补单词）', len(todo) == 1)
    # need_sent 为假 → 写库段 `if r['need_sent']` 不会执行，原声字段保持原样。
    # （sent_value 只是「若要生成会写成什么」的规划值，不代表会写。）
    check('have_sent 记下现有原声', r['have_sent'] == [orig], r['have_sent'])
    check('keep_diff_sent 点名', r['keep_diff_sent'] is True)

    print('三、两个字段都已有 → 什么都不做')
    rows, todo = MA.plan_needs([row(3, '部費', wa='[sound:mine-部費-x.mp3]',
                                    sa='[sound:%s]' % orig)])
    r = rows[0]
    check('need_word 关掉', r['need_word'] is False)
    check('need_sent 关掉', r['need_sent'] is False)
    check('todo 为空', todo == [])

    print('四、句子已有别的 TTS 文件 → 仍然保留（不看内容对不对）')
    rows, todo = MA.plan_needs([row(4, 'のばす', wa='[sound:mine-のばす-y.mp3]',
                                    sa='[sound:mine-sent-999.mp3]')])
    check('todo 为空', todo == [])
    check('keep_diff_sent 为真', rows[0]['keep_diff_sent'] is True)

    print('五、来源卡能配上原声、且字段已有同一原声 → 不算差异、不动')
    rows, todo = MA.plan_needs([row(5, 'x', wa='[sound:a.mp3]', sa='[sound:b.mp3]',
                                    src_audio=['b.mp3'])])
    check('todo 为空', todo == [])
    check('keep_diff_sent 为假', rows[0]['keep_diff_sent'] is False)

    print('六、--force → 两个字段都重算重写')
    rows, todo = MA.plan_needs([row(6, '部費', wa='[sound:mine-部費-x.mp3]',
                                    sa='[sound:%s]' % orig)], force=True)
    r = rows[0]
    check('need_word', r['need_word'] is True)
    check('need_sent', r['need_sent'] is True)
    check('进 todo', len(todo) == 1)

    print()
    if FAIL:
        print('★ 失败 %d 项：%s' % (len(FAIL), '；'.join(FAIL)))
        return 1
    print('★ 全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
