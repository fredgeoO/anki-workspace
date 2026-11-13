# -*- coding: utf-8 -*-
"""回归测试：edge-TTS 对 503 / 握手中断的退避重试（**不连网**）。

跑法::

    & $PY code\\tests\\test_edge_tts_retry.py

挡的是 2026-11-13 实测过一次的故障：批量补例句时第二张卡的
``WebSocket 握手失败：HTTP/1.1 503 Service Unavailable`` 让整个 tts 步骤
exit 1，apply 根本没跑。500/429/连接重置是 Edge 端的瞬时问题，隔几秒重连
通常就好；这里固定住四条口径：

1. 瞬时握手错误会重试，成功后返回音频；
2. 非瞬时错误（参数/协议）只试一次，不浪费退避时间；
3. 重试用尽仍失败 → 原样抛出最后一次异常（调用方照旧记失败）；
4. 服务端返回空音频也会重试，最终仍空返回 ``b''``（不改变调用方口径）。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))
sys.path.insert(0, os.path.join(_WS, 'code', 'tools'))

import textio            # noqa: E402  UTF-8 stdio（textio audit 要求）
import edge_tts_min as T  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def main():
    orig_once, orig_sleep = T._synth_once, T.time.sleep
    T.time.sleep = lambda _s: None            # 测试里不真的等退避
    try:
        calls = []

        def flaky(*_a, **_k):
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError('WebSocket 握手失败：HTTP/1.1 503 Service Unavailable')
            return b'audio'

        T._synth_once = flaky
        check('503 重试两次后成功', T.synth('x') == b'audio' and len(calls) == 3, calls)

        calls = []

        def bad(*_a, **_k):
            calls.append(1)
            raise ValueError('参数错误，不该重试')

        T._synth_once = bad
        raised = False
        try:
            T.synth('x')
        except ValueError:
            raised = True
        check('非瞬时错误只试一次', raised and len(calls) == 1, calls)

        calls = []

        def always_503(*_a, **_k):
            calls.append(1)
            raise RuntimeError('WebSocket 握手失败：HTTP/1.1 503 Service Unavailable')

        T._synth_once = always_503
        raised = False
        try:
            T.synth('x')
        except RuntimeError as exc:
            raised = '503' in str(exc)
        check('重试用尽仍抛出最后一次异常', raised and len(calls) == 4, calls)

        calls = []

        def empty(*_a, **_k):
            calls.append(1)
            return b''

        T._synth_once = empty
        check('空音频按原口径返回 b""（先重试）',
              T.synth('x', attempts=2) == b'' and len(calls) == 2, calls)
    finally:
        T._synth_once, T.time.sleep = orig_once, orig_sleep

    print()
    if FAIL:
        print('❌ %d 项失败：%s' % (len(FAIL), ' / '.join(FAIL)))
        return 1
    print('✅ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
