# -*- coding: utf-8 -*-
r"""修一张「读错的单词音频」：Transliteration 错 → Word Audio 跟着错。

背景：`Word Audio` 的 TTS 输入是 `Transliteration`（假名读音），不是 `Word`（词形）。
挖词阶段偶尔会把读音写错（`阻止` 写成 しゅしょう、`罪人` 写成 つみと、`討つ` 写成 うたう），
当时合成的 mp3 也就读错了。修的时候**必须两处一起改**：

  1. `Transliteration` 改成正确读音；
  2. 用新读音重新合成 mp3，**同名覆盖**（文件名只由 `Word` 派生，`[sound:]` 引用不用改）。

只改字段 = 音频还是错的；只换 mp3 = 下次重跑 `mine_audio.py` 又按旧读音合成。

读音的机械依据是**同一张卡 `Sentence HTML` 里的 ruby**（`<ruby>阻止<rt>そし</rt></ruby>`，
连同送假名 `分<rt>わ</rt>かつ` → わかつ）。脚本会自己比对；对不上就拒绝写。
`Sentence HTML` 没有该词 ruby 时（没有机械依据）默认也拒绝 `--commit`，交给强模型/人确认。

用法
----
    # ① 只读预览：不知道正确读音时先跑这条，脚本会把卡上 ruby 读音打出来
    python fix_word_audio.py --word "阻止"

    # ② 只读确认：看现值、目标值、ruby 依据、同词其他卡（<…> 从第①步输出里抄）
    python fix_word_audio.py --word "阻止" --reading "<ruby读音>" --expect "<当前读音>"

    # ③ 确认无误后真写
    python fix_word_audio.py --word "阻止" --reading "<ruby读音>" --expect "<当前读音>" --commit

    # 同词多张卡时用 noteId 精确定位
    python fix_word_audio.py --nid 1792079997191 --reading "<ruby读音>" --expect "<当前读音>" --commit

守卫
----
- `--reading` 必须是纯假名（片假名会转平假名）；汉字/拉丁字母直接拒绝 ——
  这正是 `mine_audio.py` 里「读音不是纯假名就退回词形合成」的错读来源。
- `--commit` 必须带 `--expect`（当前读音），写前断言，防修错卡 / 重复修。
- 新读音与 `Sentence HTML` 的 ruby 不一致 → 拒绝写（`--force` 才放行）。
- 同 deck 里 `Word` 相同的其他卡共用同一个 mp3；若它们的读音与目标不一致 → 拒绝写
  （`--force` 才放行），因为改文件会连带改掉它们的音频。
- 只动 `Transliteration` + `Word Audio`，**不碰 `Sentence Audio` / `Word` / `Meaning` / `AINote`**。
- 幂等：已经是目标状态（读音对、引用对、媒体在）就直接退出，不重合成。

退出码：0 = 成功/无需改动；2 = 守卫拒绝（读输出里的原因）；1 = 运行错误。
"""
import argparse
import hashlib
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_CODE, 'common'))      # anki_api / paths / textio
sys.path.insert(0, _HERE)                             # edge_tts_min
sys.path.insert(0, os.path.join(_CODE, 'execution'))  # mine_audio（命名与 voice 的唯一口径）
import anki_api as AK          # noqa: E402
import edge_tts_min as TTS     # noqa: E402
import textio                  # noqa: E402
from mine_audio import DECK, VOICE, OUT, media_name, word_audio_name  # noqa: E402

KANA = re.compile(r'^[\u3041-\u3096\u30a0-\u30ff\u30fc\u30fb]+$')
RUBY = re.compile(r'<ruby>(.*?)<rt>(.*?)</rt></ruby>', re.S | re.I)
TAG = re.compile(r'<[^>]+>')
BR = re.compile(r'<br\s*/?>', re.I)
SOUND = re.compile(r'\[sound:([^\]]+)\]')


# ============================================================================
# 小工具
# ============================================================================
def to_hira(s):
    """片假名 → 平假名（长音符 ー 原样保留）。读音字段统一用平假名。"""
    return ''.join(chr(ord(c) - 0x60) if '\u30a1' <= c <= '\u30f6' else c for c in (s or ''))


def sha1_12(data):
    return hashlib.sha1(data).hexdigest()[:12]


def die(msg, code=2):
    """守卫拒绝 / 运行错误：打印原因后带退出码退出。"""
    print(msg, file=sys.stderr)
    sys.exit(code)


def texts_of(note):
    return AK.field_values(note)


def sounds_of(value):
    return SOUND.findall(value or '')


def ruby_readings(html, word):
    """从 Sentence HTML 的 ruby 还原 `word` 的读音（含送假名）。

    返回去重后的读音列表（平假名）。例：
      `<ruby>阻止<rt>そし</rt></ruby>`            → ['そし']
      `<ruby>分<rt>わ</rt></ruby>かつ`            → ['わかつ']
      `<ruby>罪人<rt>ざいにん</rt></ruby>`         → ['ざいにん']
    """
    s = BR.sub('\n', html or '')
    segs = []          # [(表面, 读音或 None)]，读音为 None 表示裸文本（假名/标点）
    pos = 0
    for m in RUBY.finditer(s):
        if m.start() > pos:
            plain = TAG.sub('', s[pos:m.start()])
            segs.extend((ch, None) for ch in plain)
        base = TAG.sub('', m.group(1)).strip()
        rt = to_hira(TAG.sub('', m.group(2)).strip())
        if base:
            segs.append((base, rt))
        pos = m.end()
    if pos < len(s):
        plain = TAG.sub('', s[pos:])
        segs.extend((ch, None) for ch in plain)
    if not segs:
        return []

    starts, ends, cur = [], [], 0
    for surface, _reading in segs:
        starts.append(cur)
        cur += len(surface)
        ends.append(cur)
    plain = ''.join(surface for surface, _ in segs)

    out = []
    i = plain.find(word)
    while i >= 0:
        j = i + len(word)
        if i in starts and j in ends:
            si, ei = starts.index(i), ends.index(j)
            reading = ''.join(r if r else surface
                              for surface, r in segs[si:ei + 1])
            reading = to_hira(reading)
            if KANA.match(reading) and reading not in out:
                out.append(reading)
        i = plain.find(word, i + 1)

    # 兜底：词形含送假名、上面按边界没对齐时，直接找基底完全相同的 ruby
    if not out:
        for surface, reading in segs:
            if surface == word and reading and reading not in out:
                out.append(reading)
    return out


def resolve_note(args):
    """--nid 或 --word → 唯一一张 note；多张时报错退出。"""
    if args.nid:
        notes = AK.notes_info([args.nid])
        if not notes:
            die('没找到 noteId=%d' % args.nid)
        note = notes[0]
        if args.word and texts_of(note).get('Word', '') != args.word:
            die('noteId=%d 的 Word 是 %r，不是 %r'
                % (args.nid, texts_of(note).get('Word'), args.word))
        return note

    q = 'deck:"%s" Word:"%s"' % (args.deck, args.word)
    notes = AK.notes_info(AK.find_notes(q))
    hits = [n for n in notes if texts_of(n).get('Word', '') == args.word]
    if not hits:
        die('deck 里没找到 Word=%r（查询 %s）' % (args.word, q))
    if len(hits) > 1:
        print('命中 %d 张，无法唯一确定（用 --nid 指定）：' % len(hits))
        for n in hits:
            f = texts_of(n)
            print('  noteId=%-16s 读音=%-12r Word Audio=%r'
                  % (n['noteId'], f.get('Transliteration', ''), f.get('Word Audio', '')))
        sys.exit(2)
    return hits[0]


def same_word_others(note, deck, word):
    """同 deck 里 Word 相同的其他卡（它们与目标共用同一个 mine-*.mp3）。"""
    q = 'deck:"%s" Word:"%s"' % (deck, word)
    ids = [i for i in AK.find_notes(q) if int(i) != int(note['noteId'])]
    out = []
    for n in AK.notes_info(ids):
        f = texts_of(n)
        if f.get('Word', '') == word:
            out.append((int(n['noteId']), f.get('Transliteration', ''),
                        f.get('Word Audio', '')))
    return out


# ============================================================================
# 主流程
# ============================================================================
def run(args):
    new = None
    if args.reading:
        new = to_hira(args.reading.strip())
        if not new:
            die('--reading 不能为空')
        if not KANA.match(new):
            die('--reading 必须是纯假名，收到 %r（汉字/拉丁字母一律拒绝：'
                '这正是 TTS 读错的来源）' % args.reading)
        if new != args.reading.strip():
            print('读音已规范：%r → %r' % (args.reading, new))

    note = resolve_note(args)
    nid = int(note['noteId'])
    f = texts_of(note)
    word = f.get('Word', '')
    cur = f.get('Transliteration', '')
    cur_h = to_hira(cur.strip())
    wa = f.get('Word Audio', '')
    sa = f.get('Sentence Audio', '')

    print('noteId          : %d' % nid)
    print('Word            : %s' % word)
    print('当前读音        : %r' % cur)
    print('目标读音        : %s' % (repr(new) if new else '（未给 --reading，只预览）'))
    print('Word Audio      : %r' % wa)
    print('Sentence Audio  : %r（本次不动）' % sa)
    print('Sentence        : %s' % (f.get('Sentence') or ''))

    # ---- 读音的机械依据 = 同卡 Sentence HTML 的 ruby
    reads = ruby_readings(f.get('Sentence HTML', ''), word)
    if reads:
        print('ruby 读音       : %s（来自 Sentence HTML）' % ' / '.join(reads))
    else:
        print('ruby 读音       : （Sentence HTML 里找不到 %s 的 ruby）' % word)

    # ---- 同词其他卡（共用同一个 mp3）
    others = same_word_others(note, args.deck, word)
    if others:
        print('同词其他卡      :')
        for o_nid, o_read, o_audio in others:
            flag = ('  ← 读音与目标不一致！'
                    if (new and to_hira(o_read.strip()) != new) else '')
            print('  noteId=%-16s 读音=%-12r Word Audio=%r%s'
                  % (o_nid, o_read, o_audio, flag))
    else:
        print('同词其他卡      : 无')

    # ---- 目标文件名 / 旧文件
    name = media_name(word_audio_name(word))
    refs = sounds_of(wa)
    local = os.path.join(OUT, name)
    old_bytes = None
    if os.path.isfile(local):
        with open(local, 'rb') as fh:
            old_bytes = fh.read()
    media = set(AK.media_names(name))
    print('目标媒体文件    : %s（本地%s，媒体库%s）'
          % (name, '有' if old_bytes is not None else '无',
             '有' if name in media else '无'))
    if old_bytes is not None:
        print('本地旧文件      : %d bytes  sha1=%s'
              % (len(old_bytes), sha1_12(old_bytes)))
    if refs and refs != [name]:
        print('注意            : 现有引用 %r 与目标文件名不同，写完会改引用（旧文件留作孤儿）'
              % (refs,))

    # ---- 只预览：不知道正确读音时先跑这一条，从 ruby 读音里挑
    if new is None:
        print()
        print('只读预览（未给 --reading，不写库）。')
        if reads:
            print('下一步：把 ruby 读音作为 --reading 再跑一次，例如')
            print('  --reading "%s" --expect "%s"' % (reads[0], cur))
        else:
            print('这张卡没有该词的 ruby —— 读音没有机械依据，先交强模型/人确认。')
        return 0

    # ---- 守卫 1：旧值断言
    if args.expect is not None:
        if cur_h != to_hira(args.expect.strip()):
            die('当前读音 %r 与 --expect %r 不符 —— 不写（防止修错卡/重复修）'
                % (cur, args.expect))
    elif args.commit and not args.force:
        die('--commit 必须带 --expect "<当前读音>"（先跑一次只读确认）；'
            '确实要跳过断言才用 --force')

    # ---- 守卫 2：目标读音必须与 ruby 一致
    if reads:
        if new not in reads and not args.force:
            die('目标读音 %r 与卡上 ruby %s 不一致 —— 不写。'
                '先确认哪边错：若 ruby 错，用 ruby_engine.py 修 HTML；'
                '确认 ruby 不可信才加 --force' % (new, ' / '.join(reads)))
    else:
        if args.commit and not args.force:
            die('读音没有机械依据（卡上没有该词的 ruby）—— 不写。'
                '先把读音交强模型/人确认，再带 --force 写')

    # ---- 守卫 3：同词其他卡的读音必须一致
    if others and any(to_hira(o[1].strip()) != new for o in others) and not args.force:
        die('同词还有读音不同的卡，但共用一个 mp3（文件名只由 Word 派生）。'
            '改文件会连带改掉它们的音频 —— 先统一读音，或确认后加 --force')

    noop = (cur_h == new and refs == [name] and name in media)
    if noop and not args.force:
        print()
        print('已经是目标状态（读音对、引用对、媒体在）—— 无需改动。')
        return 0

    print()
    print('将写入          : Transliteration=%r, Word Audio=[sound:%s]' % (new, name))
    print('写入方式        : 同名覆盖媒体文件（[sound:] 引用不变）；Sentence Audio 不动')
    if not args.commit:
        print()
        print('只读模式，未写库。确认 ruby 依据无误后，同一条命令加 --commit。')
        return 0

    # ---- 真写
    print()
    print('合成中（%s, voice=%s）…' % (new, VOICE))
    data = TTS.synth(new, voice=VOICE)
    if not data or len(data) < 1000:
        die('TTS 返回空音频或过小（%s bytes）—— 没写库，可重跑'
            % (len(data) if data else None), code=1)
    os.makedirs(OUT, exist_ok=True)
    with open(local, 'wb') as fh:
        fh.write(data)
    print('已合成          : %d bytes  sha1=%s' % (len(data), sha1_12(data)))

    try:
        AK.store_media_file(name, path=local, delete_existing=True)
        AK.update_note_fields(nid, {
            'Transliteration': new,
            'Word Audio': '[sound:%s]' % name,
        })
    except Exception:
        print('!! 媒体/字段写入中断：媒体可能已覆盖但字段未写；重跑同一命令即可（幂等）。')
        raise

    # ---- 回读
    bad = AK.verify_note_fields([nid], {nid: {'Transliteration': new,
                                              'Word Audio': '[sound:%s]' % name}})
    media = set(AK.media_names(name))
    if bad or name not in media:
        die('回读失败：%r；媒体库内=%s'
            % (bad.get(nid), name in media), code=1)
    print('回读 OK         : Transliteration=%r  Word Audio=[sound:%s]'
          % (new, name))
    if old_bytes is not None:
        if sha1_12(old_bytes) == sha1_12(data):
            print('提示            : 新旧文件哈希相同 —— edge-TTS 每次字节通常不同，'
                  '建议试听确认')
        else:
            print('音频已更换      : 旧 sha1=%s → 新 sha1=%s'
                  % (sha1_12(old_bytes), sha1_12(data)))
    else:
        print('本地无旧副本    : 无法比较哈希；以字段与媒体库回读为准')
    print('DONE')
    return 0


def main():
    ap = argparse.ArgumentParser(
        description='修一张读错的单词音频（Transliteration + Word Audio，同名覆盖）')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--nid', type=int, help='noteId（同词多卡时用）')
    g.add_argument('--word', help='词形（在素材生词 deck 里唯一匹配）')
    ap.add_argument('--reading',
                    help='正确读音（纯假名；片假名会转平假名）。不给 = 只读预览，打印 ruby 读音')
    ap.add_argument('--expect', help='当前读音，写前断言（--commit 必带）')
    ap.add_argument('--deck', default=DECK, help='素材生词 deck（默认 %s）' % DECK)
    ap.add_argument('--commit', action='store_true', help='真写；默认只读')
    ap.add_argument('--force', action='store_true',
                    help='跳过 ruby/同词/断言的守卫（确认来源后才用）')
    a = ap.parse_args()
    textio.setup()
    with AK.guard():
        sys.exit(run(a))


if __name__ == '__main__':
    main()
