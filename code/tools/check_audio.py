# -*- coding: utf-8 -*-
"""核对每个单词音频确实是"各自那个词"，且没有被 TTS 读错/读成空。

edge-tts 的 mp3 里带 LAME/Info 头，某些编码器会把输入文本塞进去；
即使没有，也能靠**帧数（≈时长）与词长成正比**做粗校验：
  一个 2 字词不该和 6 字词一样长，反之亦然。
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'common'))
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

HDR = 2 + 2  # 前两字节是头长度前缀的解析见下


def frame_count(path):
    """粗略数 MPEG 帧数：从同步字往后按帧长跳。"""
    d = open(path, 'rb').read()
    i = 0
    n = 0
    # 跳过可能的 ID3
    if d[:3] == b'ID3':
        size = (d[6] << 21) | (d[7] << 14) | (d[8] << 7) | d[9]
        i = 10 + size
    while i + 4 <= len(d):
        if d[i] == 0xFF and (d[i + 1] & 0xE0) == 0xE0:
            # MPEG2 Layer III @48kHz：帧长 = 576/8 * 比特率/采样率 + padding
            b2 = d[i + 2]
            br_idx = (b2 >> 4) & 0x0F
            pad = (b2 >> 1) & 1
            rates = {1: 32, 2: 40, 3: 48, 4: 56, 5: 64, 6: 80, 7: 96, 8: 112,
                     9: 128, 10: 160, 11: 192, 12: 224, 13: 256, 14: 320}
            br = rates.get(br_idx)
            if not br:
                i += 1
                continue
            flen = int(576 / 8 * br * 1000 / 48000) + pad
            if flen <= 0:
                i += 1
                continue
            n += 1
            i += flen
        else:
            i += 1
    return n, len(d)


rows = []
for f in sorted(glob.glob(os.path.join(WSP.OUT_AUDIO, '*.mp3'))):
    name = os.path.basename(f)
    word = name[len('mine-'):].rsplit('-', 1)[0]
    fr, sz = frame_count(f)
    rows.append((word, fr, sz))

print('%-14s %6s %8s %8s' % ('词', '帧数', '时长秒', '字长'))
for w, fr, sz in rows:
    dur = fr * 576 / 48000.0
    print('%-14s %6d %8.2f %8d' % (w, fr, dur, len(w)))

print()
durs = [(w, fr * 576 / 48000.0, len(w)) for w, fr, _ in rows]
mx = max(durs, key=lambda x: x[1])
mn = min(durs, key=lambda x: x[1])
print('最长: %s %.2fs   最短: %s %.2fs' % (mx[0], mx[1], mn[0], mn[1]))
print('所有时长都在 0.2–2.5s 的合理区间:',
      all(0.2 <= d <= 2.5 for _, d, _ in durs))
# 1 字/2 字 与 6 字 应该量级不同
short = [d for _, d, L in durs if L <= 3]
long_ = [d for _, d, L in durs if L >= 6]
if short and long_:
    print('3字以内平均 %.2fs / 6字以上平均 %.2fs' % (sum(short) / len(short),
                                                sum(long_) / len(long_)))
