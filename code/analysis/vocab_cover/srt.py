# -*- coding: utf-8 -*-
"""字幕解析：SRT -> 可直接做词汇统计的日语文本。

处理的现实问题
--------------
* 编码不统一：UTF-8 / UTF-8-BOM / CP932 / Shift_JIS 都有（本工作区 3 部作品混用）。
* Netflix 日文字幕的 CC 约定：
    - ``（大家）おっ`` 行首括号 = 说话人标签，只去标签留台词；
    - ``（犬の鳴き声）``、``（大家の鼻歌）`` 整行括号 = 非台词音效，**不计入词汇统计**；
    - ``赤い直垂(ひたたれ)`` 半角括号内纯假名 = 注音（振假名），只留汉字；
    - ``♪``、``<i>``、``<font>`` 等装饰要去掉。
* 台词里用半角/全角空格分词，标点后也可能直接接下一句。
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

ENCODINGS = ('utf-8-sig', 'utf-8', 'cp932', 'shift_jis', 'euc_jp', 'gb18030')

TC_RE = re.compile(
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')
TAG_RE = re.compile(r'</?[a-zA-Z][^>]*>')
SRT_INDEX_RE = re.compile(r'^\d+$')
# 整行都是括号注释（全角或半角）-> 非台词
ANNOT_ONLY_RE = re.compile(r'^[（(\[［【][^）)\]］】]*[）)\]］】][。、！？!?…～\s]*$')
# 行首说话人标签 （名字） / (名字)
SPEAKER_RE = re.compile(r'^[（(\[［【]([^）)\]］】]{1,24})[）)\]］】]\s*')
# 半角括号内纯假名 -> 振假名注音
RUBY_RE = re.compile(r'([\u4e00-\u9fff\u3400-\u4dbf]+)[（(]([\u3041-\u3096\u30a1-\u30fa\u30fc]{1,12})[）)]')
KANA_ONLY_RE = re.compile(r'^[\u3041-\u3096\u30a1-\u30fa\u30fc\u309d\u309eー]+$')
THEATRICAL_RE = re.compile(r'^[（(](?P<who>[^）)]*)[）)]\s*$')
MUSIC_RE = re.compile(r'[♪♬♩♭]')
SPACE_RE = re.compile(r'[\s\u3000]+')
# 句子边界标点
SENT_END = '。！？!?…‥'
CLOSERS = '」』）)】」'


@dataclass
class Cue:
    index: int
    start_ms: int
    end_ms: int
    lines: list = field(default_factory=list)
    is_speech: bool = True          # False = 音效/歌词注释等非台词
    speakers: list = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def text(self) -> str:
        return ''.join(self.lines)


@dataclass
class Episode:
    path: str
    work: str
    title: str
    cues: list = field(default_factory=list)

    @property
    def speech_cues(self) -> list:
        return [c for c in self.cues if c.is_speech and c.text.strip()]

    @property
    def utterances(self) -> list:
        """一条字幕 = 一句话（日语字幕常不带句号，用 cue 作单位最稳）。"""
        return [c.text.strip() for c in self.speech_cues if c.text.strip()]

    @property
    def full_text(self) -> str:
        return '\n'.join(self.utterances)

    @property
    def chars(self) -> int:
        return sum(len(u) for u in self.utterances)

    @property
    def speech_seconds(self) -> float:
        return sum(c.duration_ms for c in self.speech_cues) / 1000.0

    def sentences(self, join: bool = True) -> list:
        """把 cue 合并成句子流：只在句末标点处断开，断开不了就按 cue 断。"""
        if not join:
            return self.utterances
        out, buf = [], ''
        for u in self.utterances:
            buf += u
            if buf and (buf[-1] in SENT_END or buf[-1] in CLOSERS and len(buf) > 1):
                out.append(buf)
                buf = ''
        if buf:
            out.append(buf)
        return out


# --------------------------------------------------------------------- 解析
def read_text(path: str) -> str:
    """读字幕文本。编码判定统一交给 ``textio``（唯一实现），本模块只提供一份
    字幕专用的候选表：老字幕常见 CP932 / Shift_JIS / EUC-JP，最后才轮到 GBK。"""
    return textio.read_text(path, encodings=ENCODINGS, warn=False)


def parse_timecode(line: str):
    m = TC_RE.search(line)
    if not m:
        return None
    h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
    start = ((int(h1) * 60 + int(m1)) * 60 + int(s1)) * 1000 + int(ms1.ljust(3, '0'))
    end = ((int(h2) * 60 + int(m2)) * 60 + int(s2)) * 1000 + int(ms2.ljust(3, '0'))
    return start, end


def clean_line(line: str) -> tuple:
    """清洗一行字幕，返回 (文本, 是否台词, 说话人列表)。"""
    raw = unicodedata.normalize('NFKC', line)
    raw = TAG_RE.sub('', raw)
    text = raw.replace('\\N', ' ').replace('\\n', ' ')
    text = MUSIC_RE.sub('', text)

    if not text.strip():
        return '', True, []
    if ANNOT_ONLY_RE.match(text.strip()):
        return '', False, [text.strip().strip('（）()[]［］【】')]

    # 先去振假名：漢字(かな) -> 漢字。必须先做，否则 （禿(かぶろ)）道をあけろ
    # 的说话人标签会在一半就被截断
    text = RUBY_RE.sub(lambda m: m.group(1), text)

    speakers = []
    # 行首说话人标签可能连续出现（（びわ）（父）…）
    while True:
        m = SPEAKER_RE.match(text)
        if not m:
            break
        name = m.group(1).strip()
        # 括号内是整句台词的一部分（如 (笑) 之类）就停手
        if not name or len(name) > 20:
            break
        speakers.append(name)
        text = text[m.end():]
    # 其余行内括号（音效提示）直接去掉括号内容
    text = re.sub(r'[（(][^）)]{0,20}[）)]', '', text)
    text = text.strip(' \u3000-–—')
    text = SPACE_RE.sub(' ', text).strip()
    if not text or not re.search(r'[\u3041-\u3096\u30a1-\u30fa\u4e00-\u9fff]', text):
        return '', False, speakers
    return text, True, speakers


def parse_srt(path: str, work: str = '', title: str = '') -> Episode:
    return parse_srt_text(read_text(path), work=work or os.path.basename(os.path.dirname(path)),
                          title=title or os.path.splitext(os.path.basename(path))[0])


def parse_srt_text(text: str, work: str = '', title: str = '') -> Episode:
    ep = Episode(path=title, work=work, title=title)
    block, idx = [], 0
    blocks = []
    for line in text.splitlines():
        if line.strip() == '':
            if block:
                blocks.append(block)
                block = []
        else:
            block.append(line.rstrip('\n'))
    if block:
        blocks.append(block)

    for blk in blocks:
        lines = [l for l in blk if l.strip() != '']
        if not lines:
            continue
        tc = None
        body_start = 0
        for i, l in enumerate(lines[:3]):
            tc = parse_timecode(l)
            if tc:
                body_start = i + 1
                break
        if not tc:
            continue
        start, end = tc
        idx += 1
        body = lines[body_start:]
        cue = Cue(index=idx, start_ms=start, end_ms=end)
        for l in body:
            cleaned, is_speech, speakers = clean_line(l)
            cue.speakers.extend(speakers)
            if not is_speech:
                if not cue.lines:          # 整条都是音效 -> 整条非台词
                    cue.is_speech = False
                continue
            cue.lines.append(cleaned)
        if not cue.lines:
            cue.is_speech = False
        ep.cues.append(cue)
    return ep


def parse_plain(path: str, work: str = '', title: str = '') -> Episode:
    """纯文本（无时间轴）：一行 = 一句。"""
    text = read_text(path)
    ep = Episode(path=path, work=work or os.path.basename(os.path.dirname(path)),
                 title=title or os.path.splitext(os.path.basename(path))[0])
    idx = 0
    for line in text.splitlines():
        cleaned, is_speech, speakers = clean_line(line)
        idx += 1
        cue = Cue(index=idx, start_ms=0, end_ms=0,
                  lines=[cleaned] if is_speech and cleaned else [],
                  is_speech=bool(is_speech and cleaned), speakers=speakers)
        ep.cues.append(cue)
    return ep


def load_episode(path: str, work: str = '', title: str = '') -> Episode:
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.srt', '.ass', '.ssa', '.vtt'):
        return parse_srt(path, work=work, title=title)
    return parse_plain(path, work=work, title=title)


if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        e = load_episode(p)
        print(f'== {os.path.basename(p)}')
        print(f'   cues={len(e.cues)}  台词条={len(e.speech_cues)}  非台词={len(e.cues)-len(e.speech_cues)}'
              f'  字数={e.chars}  台词时长={e.speech_seconds/60:.1f} 分')
        for u in e.utterances[:8]:
            print('   |', u)
