# -*- coding: utf-8 -*-
"""本地模型「产出吸收层」的回归测试（llm_out / check_cards / check_mine / pipeline 分组）。

跑法：`& $PY code\tests\test_llm_out.py`

覆盖的都是**真实发生过的崩法**（2026-10-12 复盘，见 docs/troubleshooting/local-llm-guardrails.md）：
* 模型把字符串字段回成数字 → 校验器必须报一条硬错误，**不许抛异常**
* 模型把 `include` 写成 `"false"` / `"收录"` → 前者按排除收，后者报硬错误（不静默丢词）
* 一条畸形回复 → 只影响这一组，别把整批 12 张带崩
* 一组 prompt 超预算 → 自动切小（而不是等端点回 400 之后整批白跑）
* 没做出来的组 → 原始回复必须落盘
"""
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'execution'))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))

import textio                 # noqa: E402  （stdio/文件一律 UTF-8，见 AGENTS.md §3）
import check_cards as CC      # noqa: E402
import check_mine as CM       # noqa: E402
import llm_out as OUT         # noqa: E402
import pipeline as P          # noqa: E402

FAILED = []


def ok(cond, label):
    print('  [%s] %s' % ('OK' if cond else '!!', label))
    if not cond:
        FAILED.append(label)


def section(t):
    print('== %s ==' % t)


TMP = os.path.join(_WS, 'temp', 'test_llm_out')

USEFUL_AINOTE = ('<p><b>中文翻译：</b>这是测试。</p>'
                 '<p><b>核心词汇：</b><br><ruby>錆<rt>さび</rt></ruby>：名词。锈。</p>'
                 '<p><b>语法要点：</b><br>「〜は〜だ」：判断句。</p>')


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)

    section('1. llm_out：类型归一')
    ok(OUT.as_text('abc') == 'abc', '字符串原样通过')
    ok(OUT.as_text(12) == '' and OUT.as_text(None) == '' and OUT.as_text(['x']) == '',
       '数字/None/列表 → 空串（不抛异常）')
    ok(OUT.as_bool('false') is False and OUT.as_bool('True') is True,
       '"false"/"True" 归一成布尔')
    ok(OUT.as_bool(0) is False and OUT.as_bool(1) is True, '0/1 归一成布尔')
    ok(OUT.as_int('42') == 42 and OUT.as_int('x', -1) == -1, 'as_int 转不了给默认值')
    ok(OUT.is_boolish(True) and OUT.is_boolish('false') and OUT.is_boolish(1),
       'is_boolish 认得 true/false/0/1')
    ok(not OUT.is_boolish('收录') and not OUT.is_boolish(None),
       'is_boolish 不认 "收录"/None（→ 报硬错误）')

    section('2. llm_out.dump_raw：留证且不覆盖')
    p1 = OUT.dump_raw(TMP, 'batch_01_r0', '第一次的原始回复', header='测试')
    p2 = OUT.dump_raw(TMP, 'batch_01_r0', '第二次的原始回复', header='测试')
    ok(p1 and p2 and p1 != p2, '同名两次落盘写成两个文件')
    ok('第一次' in open(p1, encoding='utf-8').read()
       and '第二次' in open(p2, encoding='utf-8').read(), '两份证据都在，旧的不被覆盖')
    ok(OUT.raw_text(None).startswith('(没有拿到') and OUT.raw_text('x') == 'x',
       'raw_text 对 None/字符串都不抛')

    section('3. check_cards：畸形回复是硬错误，不是异常')
    bad = {'noteId': 1, 'sentence': 'テスト', 'AINote': 123, 'SentenceHTML': ''}
    hard, _html, _soft = CC.split_hard(bad)
    ok(any('类型不是字符串' in h for h in hard), 'AINote 是数字 → 报「类型不是字符串」')
    ok(not any('Traceback' in h for h in hard), '没有异常穿透')
    hard2, _, _ = CC.split_hard(['not', 'a', 'dict'])
    ok(any('不是对象' in h for h in hard2), '条目不是对象 → 硬错误而不是 AttributeError')
    good = {'noteId': 2, 'sentence': 'テスト', 'AINote': USEFUL_AINOTE,
            'SentenceHTML': 'テスト'}
    hard3, _h3, _s3 = CC.split_hard(good)
    ok(not any('类型不是字符串' in h for h in hard3), '正常卡不受影响')

    section('4. check_mine：include 写错不静默')
    base = {'word': '錆', 'reading': 'さび', 'pos': '名词', 'meaning': '锈',
            'translation': '铁锈味。', 'a_note': USEFUL_AINOTE, 'reason': ''}
    h_ok, _ = CM.check(dict(base, include=True))
    ok(not h_ok, '正常收录条目通过')
    h_no, _ = CM.check(dict(base, include='false', reason='口语缩略'))
    ok(not h_no, 'include="false" 按排除收下（不是当 True）')
    h_weird, _ = CM.check(dict(base, include='收录'))
    ok(any('include 不是布尔值' in h for h in h_weird),
       'include="收录" → 硬错误（不静默丢词）')
    h_num, _ = CM.check(dict(base, include=True, translation=12))
    ok(any('类型不是字符串' in h for h in h_num), 'translation 是数字 → 硬错误')

    section('5. pipeline：分组按预算切小')
    cards = [{'noteId': i, 'sentence': 'あ' * 40, 'word': '', 'source': ''}
             for i in range(1, 13)]

    class FakeLLM:                      # 只用来给 fit_groups 提供估算/预算
        calls = 0

        @staticmethod
        def estimate_tokens(text):
            return len(text)

        @staticmethod
        def budget(cfg):
            return FakeLLM.calls

    FakeLLM.calls = 10 ** 6
    g_big = P.fit_groups(cards, 12, P.group_user, {}, FakeLLM)
    ok(len(g_big) == 1 and len(g_big[0]) == 12, '预算足够时按 size 成一组')
    FakeLLM.calls = 200
    g_small = P.fit_groups(cards, 12, P.group_user, {}, FakeLLM)
    ok(len(g_small) > 1 and sum(len(g) for g in g_small) == 12,
       '预算很小时自动切成多组（总数不丢）')
    ok(all(FakeLLM.estimate_tokens(P.group_user(g)) <= 200 or len(g) == 1
           for g in g_small), '每组都在预算内（除非单条就超）')
    ok(P.group_user(cards[:1]).endswith(P.group_payload(cards[:1])),
       '分组估算与真实请求正文共用同一份渲染')

    section('6. pipeline.gen_request：AI 回复畸形也不崩')
    got = {}

    class Resp:
        prompt_tokens = 1
        completion_tokens = 1

    class StubLLM:
        @staticmethod
        def call_json(*_a, **_k):
            return ({'cards': [{'noteId': '9', 'AINote': 5, 'SentenceHTML': None},
                               'not-a-dict',
                               {'noteId': 'bad', 'AINote': 'x'}]}, Resp(), [])

    got, _res = P.gen_request({}, StubLLM, cards[:2])
    ok(list(got.keys()) == [9] and got[9]['AINote'] == '',
       '只收下能解析的条目，字段畸形的吸收成空串')

    section('7. 提示词接线：硬约束确实进了 body')
    import mine as M  # noqa: E402  阶段四（任务 B）

    ok('任务 A 的规范要求字段是 JSON 字符串', 'JSON 字符串' in P.LOCAL_INSTRUCTION)
    ok('任务 A 的规范要求振假名以词为单位', '以"词"为单位' in P.LOCAL_INSTRUCTION)
    ok('任务 B 的规范要求保留候选作为子串', '候选必须是 word 的子串' in M.MINE_INSTRUCTION)
    ok('任务 B 的规范要求 include 是 JSON 布尔', 'JSON 的 true 或 false' in M.MINE_INSTRUCTION)
    one = [{'word': '錆臭ぇ', 'count': 1, 'occurrences': [{'noteId': 1, 'sentence': '｡'}]}]
    ok(M.mine_user(one) == M.MINE_INSTRUCTION + '\n' + M.mine_payload(one),
       'mine_user = 规范 + 载荷（分组估算与真实请求同一份）')
    ok(M.mine_user(one, '上次不合格').endswith('上次不合格'), 'feedback 拼在 user 末尾')

    section('8. pipeline.gen_loop：一条坏回复不连坐，重问后能救回，出事的组留证')
    import types as _types

    good_hard = CC.split_hard(good)[0]
    ok(not good_hard, '测试卡本身是合格形状（%s）' % (good_hard or '无硬错误'))

    class LoopLLM:
        """首轮漏掉第 2 张，重问轮（逐张）才给出。"""
        n = 0
        budget = staticmethod(lambda cfg: 10 ** 6)
        estimate_tokens = staticmethod(lambda t: len(t))

        @staticmethod
        def call_json(cfg, msgs, **_k):
            LoopLLM.n += 1
            if LoopLLM.n == 1:
                return ({'cards': [{'noteId': 1, 'AINote': USEFUL_AINOTE,
                                    'SentenceHTML': 'テスト'}]}, Resp(), [])
            nid = int(msgs[1]['content'].split('"noteId": ')[-1][:1])
            return ({'cards': [{'noteId': nid, 'AINote': USEFUL_AINOTE,
                                'SentenceHTML': 'テスト'}]}, Resp(), [])

    P.GEN_RAW = os.path.join(TMP, 'raw')          # 别往真工作目录里写测试证据
    cards2 = [{'noteId': 1, 'sentence': 'テスト', 'word': '', 'source': ''},
              {'noteId': 2, 'sentence': 'テスト', 'word': '', 'source': ''}]
    a = _types.SimpleNamespace(per_request=2, retries=1)
    done, bad, _mech = P.gen_loop(a, {}, LoopLLM, cards2, 99, tag='[测试]')
    ok(set(done) == {1, 2} and not bad, '漏掉的那张在重问轮被救回（%s / %s）' % (set(done), bad))
    ok(os.path.isdir(P.GEN_RAW) and os.listdir(P.GEN_RAW),
       '首轮出事的组留了原始回复证据')

    shutil.rmtree(TMP, ignore_errors=True)
    print()
    if FAILED:
        print('✗ %d 项未通过：%s' % (len(FAILED), '；'.join(FAILED)))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
