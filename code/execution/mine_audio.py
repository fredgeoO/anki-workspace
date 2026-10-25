# -*- coding: utf-8 -*-
"""阶段五 · 给素材生词卡挂音频（Word Audio / Sentence Audio）

音频方案（用户指定）
--------------------
| 字段 | 来源 | 理由 |
|---|---|---|
| `Word Audio` | **edge-TTS** `ja-JP-NanamiNeural` 读**假名读音** | 单词没有现成音频可用 |
| `Sentence Audio` | **复用来源例句卡的原声**（ASB Player 从字幕轨切出的 `asbp_*.mp3`）| 演员原声，语速/连读/语气真实，且文件已在媒体库里，不重复占空间 |
| `Sentence Audio`（无原声时）| edge-TTS 兜底 | 个别来源卡没切出音频 |

**为什么 Word Audio 喂的是读音（假名）而不是汉字词形**
--------------------------------------------------
TTS 读裸汉字词形有同音异读风险，且**错了听不出来**：`新興` 可能读成 しんきょう，
`叶う` 可能读成 かない。edge-tts 返回的 mp3 里也查不到它实际读的文本
（LAME 头只有编码器元数据；同一文本两次合成字节并不相同，所以也无法靠比对来验证）。
而 `Transliteration`（读音）字段是生成阶段就校验过的，直接拿它合成即可消除全部歧义，
代价只是音频听起来和词形完全一样（本来就是同一个词）。
`Word Audio` 只负责发声，不显示文本 —— 卡面显示的是 `Word` 字段的词典形。

为什么不用 edge-tts 这个包
--------------------------
本机 pip 在工作区里解包 wheel 会被沙箱拒（临时文件 EPERM），而 TTS 协议本身不复杂。
所以 `edge_tts_min.py` 用纯标准库实现：Sec-MS-GEC 令牌 + WebSocket 帧 + SSML。
少一层依赖，也便于在别的机器上直接跑。

用法
----
    python mine_audio.py plan                  # 只读：列出每张卡将要挂什么音频
    python mine_audio.py apply                 # 演练：合成 TTS 到 output/audio/，不写库
    python mine_audio.py apply --commit        # 真写：上传媒体 + 写两个字段
    python mine_audio.py verify                # 回读校验：字段与媒体库是否一致
    python mine_audio.py revert --commit       # 清空这两个字段（媒体文件保留，无害）

只补某一集/某一批时用 `--tag`（plan / apply / verify 都支持）限定范围：

    python mine_audio.py apply --tag "素材生词::<来源>" --commit

不加 `--tag` 就是整个素材生词 deck。换集后补音频**务必带 `--tag`**：deck 里别的集的卡
若因 `Sentence` 与来源例句卡对不上而找不到原声，`apply` 会把已有的原声 `[sound:asbp_*]`
改写成 TTS 兜底（质量下降）。

幂等：已有正确 `[sound:...]` 的字段默认跳过；`--force` 强制重做。
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_CODE, 'common'))    # paths.py
sys.path.insert(0, os.path.join(_CODE, 'tools'))     # edge_tts_min.py
sys.path.insert(0, _HERE)                            # pipeline.py
import anki_api as AK         # noqa: E402  唯一的 Anki 访问点
import pipeline as P          # noqa: E402
import edge_tts_min as TTS    # noqa: E402
import paths as WSP           # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

OUT = WSP.OUT_AUDIO           # 合成音频输出（原 ./out_audio）

DECK = P.CFG['mine_deck']
VOICE = 'ja-JP-NanamiNeural'


# ============================================================================
SOUND = re.compile(r'\[sound:([^\]]+)\]')
TAG = re.compile(r'<[^>]+>')


def sounds_of(field):
    return SOUND.findall(field or '')


def sentence_for_tts(sentence):
    """把例句转成适合朗读的纯文本。

    - `<br>` → 空格（字幕换行处不该读出停顿感）
    - 剥其余标签、去 ruby
    - 全角空格 U+3000 → 半角
    - 折叠多余空白
    """
    s = re.sub(r'<br\s*/?>', ' ', sentence or '', flags=re.I)
    s = re.sub(r'<rt>.*?</rt>', '', s, flags=re.I | re.S)
    s = TAG.sub('', s)
    import html as _h
    s = _h.unescape(s)
    s = s.replace('\u3000', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def safe_token(s):
    """文件名里可用的片段：保留日文/字母数字，其余换下划线。"""
    return re.sub(r'[^\w\u3040-\u30ff\u4e00-\u9fff]+', '_', s or '').strip('_') or 'x'


def word_audio_name(word):
    h = hashlib.sha1(word.encode('utf-8')).hexdigest()[:8]
    return 'mine-%s-%s.mp3' % (safe_token(word), h)


def media_name(name):
    """Anki 存媒体时会把文件名里的拉丁字母转小写（`ＯＫ` → `ｏｋ`）。

    所以**先按小写去存**，字段里写的和实际落库的名字才一致；否则 `[sound:...]`
    指向一个不存在的文件（2026-10-12 补历史缺口时实测 20 张全角拉丁词全中）。
    """
    return name.lower() if name != name.lower() else name


def sent_tts_name(note_id):
    return 'mine-sent-%s.mp3' % note_id


# ============================================================================
# plan
# ============================================================================
def gather(tag=None, query=None):
    """拉取新牌组的卡，配对来源例句卡，算出每个字段该放什么。

    tag 非空时只取该标签下的卡（换集后补音频用，别动到别的集）。
    query 非空时**完全取代**默认查询（给驱动用：`nid:1,2,3` 精确点名这一次新建的卡，
    避免「按标签圈范围」时把同标签下别的卡一起卷进来 —— 那些卡若因 Sentence 与来源卡
    对不上，`apply` 会把已有的原声降级成 TTS）。
    """
    q = query or ('deck:"%s"' % DECK)
    if tag and not query:
        q += ' tag:"%s"' % tag
    ids = AK.find_notes(q)
    if not ids:
        raise SystemExit('没有命中素材生词卡（查询 %s）' % q)
    print('范围：%s' % q)
    notes = AK.notes_info(ids)
    # 来源例句卡：按 Sentence 精确配对（写库时记录的就是来源卡的 Sentence）
    ex_ids = AK.find_notes('deck:"%s"' % P.CFG['deck'])
    by_sent = {}
    for n in AK.notes_info(ex_ids):
        s = n['fields'].get('Sentence', {}).get('value', '')
        if s:
            by_sent.setdefault(s, n)

    media = set(AK.media_names('*'))
    rows = []
    for n in notes:
        f = n['fields']
        sent = f['Sentence']['value']
        src = by_sent.get(sent)
        src_audio = []
        if src:
            src_audio = sounds_of(src['fields'].get('Sentence Audio', {}).get('value', ''))
        rows.append({
            'noteId': int(n['noteId']),
            'word': f['Word']['value'],
            'reading': f['Transliteration']['value'],
            'sentence': sent,
            'tts_text': sentence_for_tts(sent),
            'word_audio_field': f.get('Word Audio', {}).get('value', ''),
            'sentence_audio_field': f.get('Sentence Audio', {}).get('value', ''),
            'src_noteId': int(src['noteId']) if src else None,
            'src_audio': src_audio,
            'src_exists': bool(src_audio) and all(a in media for a in src_audio),
            'word_name': word_audio_name(f['Word']['value']),
        })
    return rows, media


def cmd_plan(a):
    rows, media = gather(getattr(a, 'tag', None), getattr(a, 'query', None))
    print('新牌组 %d 张   媒体库 %d 个文件' % (len(rows), len(media)))
    print()
    print('%-10s %-8s %-28s %-28s' % ('词', '读音', 'Word Audio', 'Sentence Audio'))
    print('-' * 82)
    n_src = n_tts = 0
    for r in rows:
        if r['src_exists']:
            sent = '原声 %s' % r['src_audio'][0][:26]
            n_src += 1
        elif r['src_audio']:
            sent = '!! 原声引用但文件缺失 → TTS'
            n_tts += 1
        else:
            sent = '无原声 → TTS'
            n_tts += 1
        print('%-10s %-8s %-28s %-28s' % (r['word'], r['reading'],
                                          r['word_name'][:26], sent))
    print()
    print('Sentence Audio：原声 %d 张 / TTS 兜底 %d 张' % (n_src, n_tts))
    print('Word Audio   ：TTS %d 张（%s）' % (len(rows), VOICE))
    print('需要新生成并上传的媒体文件：%d 个' % (len(rows) + n_tts))
    print('（原声文件已在媒体库，不重复占用）')
    print()
    print('下一步：python mine_audio.py apply            # 演练（只合成，不写库）')


# ============================================================================
# apply
# ============================================================================
def cmd_apply(a):
    rows, media = gather(getattr(a, 'tag', None), getattr(a, 'query', None))
    os.makedirs(OUT, exist_ok=True)
    todo = []
    for r in rows:
        wa, sa = r['word_audio_field'], r['sentence_audio_field']
        r['need_word'] = a.force or not sounds_of(wa)
        if r['src_exists']:
            want = ['[sound:%s]' % x for x in r['src_audio']]
            r['sent_plan'] = 'reuse'
            r['sent_value'] = ''.join(want)
            r['need_sent'] = a.force or sounds_of(sa) != r['src_audio']
        else:
            r['sent_plan'] = 'tts'
            r['sent_name'] = sent_tts_name(r['noteId'])
            r['sent_value'] = '[sound:%s]' % r['sent_name']
            r['need_sent'] = a.force or sounds_of(sa) != [r['sent_name']]
        if r['need_word'] or r['need_sent']:
            todo.append(r)

    print('目标 %d 张，需要处理 %d 张（其余已有正确音频，跳过）' % (len(rows), len(todo)))
    if not todo:
        print('无需改动。')
        return
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（只合成 TTS，不写库）'))
    print()

    # ---- 1) 合成 Word Audio（以及无原声时的 Sentence Audio）
    manifest = []
    for i, r in enumerate(todo, 1):
        wp = os.path.join(OUT, r['word_name'])
        if r['need_word'] or not os.path.exists(wp):
            if a.commit or True:      # 演练也合成，便于检查音频文件
                tts_input = r['reading'] or r['word']
                if not re.fullmatch(r'[\u3040-\u309f\u30a0-\u30ff\u30fc\u30fbー]+', tts_input):
                    print('    ⚠ %s 的读音不是纯假名（%r），退回用词形合成'
                          % (r['word'], tts_input))
                    tts_input = r['word']
                data = TTS.synth(tts_input, voice=VOICE)
                if not data:
                    raise SystemExit('TTS 返回空音频：%s' % tts_input)
                open(wp, 'wb').write(data)
                print('  [%d/%d] 单词 %-10s ← %-10s %s  %d bytes'
                      % (i, len(todo), r['word'], tts_input, r['word_name'], len(data)))
        r['word_path'] = wp
        if r['sent_plan'] == 'tts':
            sp = os.path.join(OUT, r['sent_name'])
            if r['need_sent'] or not os.path.exists(sp):
                data = TTS.synth(r['tts_text'], voice=VOICE)
                if not data:
                    raise SystemExit('TTS 返回空音频：%s' % r['tts_text'])
                open(sp, 'wb').write(data)
                print('  [%d/%d] 句子 %-10s %s  %d bytes'
                      % (i, len(todo), r['word'], r['sent_name'], len(data)))
            r['sent_path'] = sp
        manifest.append({k: r[k] for k in
                         ('noteId', 'word', 'word_name', 'sent_plan', 'sent_value')})

    json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print()
    print('已合成音频到 %s' % OUT)

    if not a.commit:
        print()
        print('演练结束，未写库。检查 output/audio/ 里的 mp3，确认发音无误后加 --commit。')
        return

    # ---- 2) 上传媒体 + 写字段
    print()
    print('上传媒体并写字段…')
    ok = 0
    for r in todo:
        fields = {}
        if r['need_word']:
            name = media_name(r['word_name'])
            AK.store_media_file(name, path=r['word_path'], delete_existing=True)
            fields['Word Audio'] = '[sound:%s]' % name
        if r['need_sent']:
            if r['sent_plan'] == 'tts':
                AK.store_media_file(r['sent_name'], path=r['sent_path'],
                                    delete_existing=True)
            fields['Sentence Audio'] = r['sent_value']
        if fields:
            AK.update_note_fields(r['noteId'], fields)
            ok += 1
    print('  已更新 %d 张' % ok)

    # ---- 3) 回读校验
    print()
    verify_rows(todo)


# ============================================================================
# verify
# ============================================================================
def verify_rows(rows=None):
    if rows is None:
        rows, _media = gather()
    ids = [r['noteId'] for r in rows]
    live = AK.notes_map(ids)
    media = set(AK.media_names('*'))
    bad = []
    n_word = n_sent = 0
    for r in rows:
        n = live.get(r['noteId'])
        if n is None:
            bad.append((r['word'], 'noteId 不存在'))
            continue
        f = n['fields']
        w_refs = sounds_of(f.get('Word Audio', {}).get('value', ''))
        s_refs = sounds_of(f.get('Sentence Audio', {}).get('value', ''))
        if w_refs:
            n_word += 1
            for x in w_refs:
                if x not in media:
                    bad.append((r['word'], 'Word Audio 引用了不存在的文件 %s' % x))
        else:
            bad.append((r['word'], 'Word Audio 为空'))
        if s_refs:
            n_sent += 1
            for x in s_refs:
                if x not in media:
                    bad.append((r['word'], 'Sentence Audio 引用了不存在的文件 %s' % x))
        else:
            bad.append((r['word'], 'Sentence Audio 为空'))
    print('回读校验 %d 张：Word Audio %d / Sentence Audio %d 非空'
          % (len(rows), n_word, n_sent))
    if bad:
        print('★ 问题 %d 条：' % len(bad))
        for w, why in bad:
            print('   ✗ %-10s %s' % (w, why))
    else:
        print('★ 全部通过：两个字段都非空，且引用的文件都在媒体库里。')
    return bad


def cmd_verify(a):
    tag, query = getattr(a, 'tag', None), getattr(a, 'query', None)
    verify_rows(gather(tag, query)[0] if (tag or query) else None)


# ============================================================================
# revert
# ============================================================================
def cmd_revert(a):
    ids = AK.find_notes('deck:"%s"' % DECK)
    notes = AK.notes_info(ids)
    print('将清空 %d 张卡的 Word Audio / Sentence Audio 字段' % len(notes))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练'))
    if not a.commit:
        return
    for n in notes:
        AK.update_note_fields(int(n['noteId']),
                              {'Word Audio': '', 'Sentence Audio': ''})
    print('已清空。媒体文件保留在库里（无害，可另行清理）。')


# ============================================================================
def main():
    ap = argparse.ArgumentParser(description='给素材生词卡挂音频')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan', help='只读：列出每张卡要挂什么音频')
    p.add_argument('--tag', default=None, help='只处理该标签下的卡（换集后补音频用）')
    p.add_argument('--query', default=None,
                   help='直接给 Anki 查询（取代 deck+tag；驱动用 nid:… 精确点名本次新建的卡）')
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser('apply', help='合成并写库（默认演练）')
    p.add_argument('--commit', action='store_true')
    p.add_argument('--force', action='store_true', help='已有音频也重做')
    p.add_argument('--tag', default=None, help='只处理该标签下的卡（换集后补音频用）')
    p.add_argument('--query', default=None,
                   help='直接给 Anki 查询（取代 deck+tag；驱动用 nid:… 精确点名本次新建的卡）')
    p.set_defaults(func=cmd_apply)
    p = sub.add_parser('verify', help='回读校验字段与媒体库')
    p.add_argument('--tag', default=None, help='只校验该标签下的卡')
    p.add_argument('--query', default=None, help='直接给 Anki 查询（取代 deck+tag）')
    p.set_defaults(func=cmd_verify)
    p = sub.add_parser('revert', help='清空两个音频字段')
    p.add_argument('--commit', action='store_true')
    p.set_defaults(func=cmd_revert)
    a = ap.parse_args()
    with AK.guard():          # AnkiConnect 出错 → 中文提示，不出 traceback
        a.func(a)


if __name__ == '__main__':
    main()
