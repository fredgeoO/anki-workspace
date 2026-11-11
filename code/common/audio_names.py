# -*- coding: utf-8 -*-
"""挂进 Anki 媒体库的文件名规则与 `[sound:…]` 解析（issue #5）。

原先只有 `mine_audio.py` 有这三个函数，`proper.py` 要配音就得**跨脚本 import 一个业务脚本**
去借它们（proper.py:1441）。文件名规则和读法字段怎么拼是媒体层的约定，不是流程，
所以家在这里。先例见 `jp_decks.py`（牌组名）、`jp_text.py`（纯文本清洗）。

**没有搬走的**：TTS 合成走 `code/tools/edge_tts_min.py`；写库走 `anki_api`；
「哪些卡要配音」的判定仍是各脚本自己的流程。本模块只回答两件事 ——
**这个字段里已经挂了哪些音频文件**、**这个名字能不能落库**。

跑法（自检）：``& $PY code\\common\\audio_names.py``
"""
import re
import sys
import textio  # noqa: E402  UTF-8 stdio 唯一入口（common）

#: `[sound:文件名]` —— Anki 字段里指向媒体库条目的写法（可能多个）
SOUND = re.compile(r'\[sound:([^\]]+)\]')


def sounds_of(field):
    """从字段值里抽出挂着的音频文件名（可能多个）。空字段 → 空表。"""
    return SOUND.findall(field or '')


def safe_token(s, keep='', fallback='x', limit=None):
    """文件名里可用的片段：保留日文/字母数字（可再加 keep 指定的字符），其余换下划线。

    媒体名要能进 Anki 的 media 目录、还要出现在 `[sound:…]` 里，所以空格、标点、
    斜杠一律换成 `_`；全空就用兜底值，避免拼出 `proper--abc.mp3` 这种没有词干的怪名。

    keep：额外允许保留的字符，如 '-' 或 '.-'（按正则字符类处理）。
    fallback：整段被清空时的兜底值（默认 'x'）。
    limit：截断长度（先 strip 再截，默认不截）。
    """
    chars = r'\w\u3040-\u30ff\u4e00-\u9fff' + re.escape(keep)
    out = re.sub('[^' + chars + ']+', '_', s or '').strip('_')
    if limit:
        out = out[:limit]
    return out or fallback


def media_name(name):
    """Anki 存媒体时会把文件名里的拉丁字母转小写（`ＯＫ` → `ｏｋ`）。

    所以**先按小写去存**，字段里写的和实际落库的名字才一致；否则 `[sound:...]`
    指向一个不存在的文件（2026-10-12 补历史缺口时实测 20 张全角拉丁词全中）。
    """
    return name.lower() if name != name.lower() else name


# ============================================================================
# 自检：python code\common\audio_names.py
# ============================================================================
def _selfcheck():
    bad = []

    def ck(name, cond, detail=''):
        print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                           '' if cond else '  ← %s' % detail))
        if not cond:
            bad.append(name)

    ck('sounds_of 单个', sounds_of('[sound:a.mp3]') == ['a.mp3'], repr(sounds_of('[sound:a.mp3]')))
    ck('sounds_of 多个', sounds_of('[sound:a.mp3][sound:b.mp3]') == ['a.mp3', 'b.mp3'], '')
    ck('sounds_of 空字段不崩', sounds_of('') == [] and sounds_of(None) == [], '')
    ck('safe_token 保留日文', safe_token('気持ちを届ける') == '気持ちを届ける', repr(safe_token('気持ちを届ける')))
    ck('safe_token 空格标点换下划线', safe_token('a b/c!') == 'a_b_c', repr(safe_token('a b/c!')))
    ck('safe_token 空串兜底 x', safe_token('') == 'x' and safe_token(None) == 'x', '')
    ck('media_name 全角拉丁转小写', media_name('ＯＫ') == 'ｏｋ', repr(media_name('ＯＫ')))
    ck('media_name 已小写原样', media_name('mine-a-b.mp3') == 'mine-a-b.mp3', '')
    return bad


def main():
    bad = _selfcheck()
    if bad:
        print('结论：%d 项失败' % len(bad), file=sys.stderr)
        return 1
    print('结论：audio_names 口径自检通过（媒体名规则只有一份）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
