# -*- coding: utf-8 -*-
"""义项修复（sense repair）：卡片释义与字幕句义项对不上 → 修好原卡，照常进今天名单。

它解决的是什么
------------
义项闸（``sense_gate.py``）判 ``card_ok=False`` 的词，过去只是「剔掉 + 后面的词补位」。
但判 false 恰恰说明**这张卡本身的释义错了或偏窄**——被剔的词本该修好后照常去学。
本模块把「剔除」变成一条修复链：

1. **补真实例句**：字幕句本身就是该义项的真实语料（sense gate 判定时用的就是它）；
   不合格（太短 / 不含目标词 / 与原句换皮 / 振假名有硬伤）时退回 jisho 真实语料
   （``core6000_example.jisho_fetch`` 的缓存路径），**不退回模型造句**。
2. **修 Meaning**：按字幕义项重写中文释义，卡片原有且仍对的义项用「；」保留；
   ``core6000_meaning.parse_meaning/render_meaning`` 保证配图 tail 原样拼回。
   含内联标签的 Meaning（manual）不自动改 → 该卡修复失败，只报告。
3. **重判**：新释义 + 原字幕句再过一次 sense gate（缓存键含释义，Meaning 一改就是新键）；
   只有不再判 False 才算修好。判不了（None）按放行，与闸同口径。
4. **讲解 ② 与配音**：``AINote`` 追加「② 新句」块（① 原正文一个字不改，marker 幂等）；
   新句 edge-TTS 挂 ``Sentence Audio``（失败不挡，只记录）。

写库只走 ``writeback.write_fields``（备份 / 写 / 回读一次到位），白名单字段：
``Sentence / Sentence HTML / Sentence Translation / Meaning / Part of Speech /
AINote / Sentence Audio``。**不碰** ``Word / Transliteration / Index / Jiten*Rank /
Pitch Accent*``，不碰调度列，不加标签（tag 仍由 ``today_new_words`` 统一打）。

默认演练：模型产出与将写字段全部打印，显式 ``--commit`` 才写库；
``revert --commit --backup <writeback 备份>`` 按备份还原那批字段（媒体文件不删）。

独立用法（当天 ``today-new`` 已跑过，修复记录在 picked.json 的 ``dropped_sense``）::

    $PY code\\tools\\sense_repair.py plan                       # 看将修什么（不写）
    $PY code\\tools\\sense_repair.py apply --commit             # 真写
    $PY code\\tools\\sense_repair.py revert --commit --backup <path>
    $PY code\\tools\\sense_repair.py apply --date 2026-11-02 --words 疲れ,増し --commit
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_CODE, 'common'))
sys.path.insert(0, _HERE)
import paths as WSP              # noqa: E402  工作区路径（先拿 EXEC_CORE6000，issue #12）
sys.path.insert(0, WSP.EXEC_CORE6000)   # core6000_meaning / core6000_text

import anki_api as AK            # noqa: E402  Anki 唯一通道
import jmdict_check as JC        # noqa: E402  词性家族（只读词典，不联网）
import ruby_engine as RE         # noqa: E402  确定性振假名
import textio                    # noqa: E402  UTF-8 唯一入口
import writeback as WB           # noqa: E402  写库事务（备份/写/回读）
import edge_tts_min as TTS       # noqa: E402  纯标准库 TTS
from core6000_meaning import parse_meaning, render_meaning  # noqa: E402  Meaning 拆分/拼回
from core6000_text import POS_CN                            # noqa: E402  词性英文↔中文口径

# 修复只碰这几个字段（白名单；writeback 只写这里出现的名字）
FIELDS_TOUCH = ('Sentence', 'Sentence HTML', 'Sentence Translation', 'Meaning',
                'Part of Speech', 'AINote', 'Sentence Audio')
SENT_MIN, SENT_MAX = 6, 45      # 新句长度（去空白），与 core6000_example 同口径
SIM_MAX = 0.72                  # 与原第一句相似度上限：再像就是换皮
VOICE = 'ja-JP-NanamiNeural'
MIN_MP3_BYTES = 1024
BATCH = 8
A2_MARK = '② 新句（字幕语境）'
A2_RE = re.compile(r'\s*<p><b>%s</b>.*?</p>' % re.escape(A2_MARK), re.S)
AUDIO_PREFIX = 'sense-repair'
DATA_DIR = os.path.join(WSP.DATA, 'daily_new', 'sense_repair')
AUDIO_DIR = os.path.join(WSP.OUT_AUDIO, 'sense_repair')
PICKED_ROOT = os.path.join(WSP.DATA, 'daily_new')

# 词性中文 → 英文（core6000_text.POS_CN 的反表；卡上 Part of Speech 是英文口径）
POS_EN = {v: k for k, v in POS_CN.items()}

SYSTEM = (
    '你是日语词典编者，负责把一张释义写偏的学习卡改回和真实语料一致。'
    '只按给出的句子语境判断词义，不要按词的常见义去猜。'
)

PROMPT = '''下面每条包含：日语词、卡片现在的中文释义（已被判定与字幕句义项不符）、
字幕句、该词在字幕句里的 JMdict 义项（英文 gloss）、JMdict 义项表、以及要补进卡片的新例句
（真实语料，可能为空）。

为每条写四件事：
1. meaning —— 修正后的中文释义。字幕句用的那个义项写成第一条；卡片原释义若是另一个
   常用义且仍对，用「；」放在后面保留。总长 ≤40 字，不带词性括号、不带例句。
2. pos_cn —— 该词**在这个字幕句里**的词性中文（名词/动词/い形容词/な形容词/副词/
   感叹词/惯用语/助词 之类）。
3. translation —— 新例句的中文翻译，直译 ≤40 字。新例句为空就返回 ""。
4. note2 —— ≤120 字讲解「这个词在这个句子里怎么用」：点出它的搭配、句式、语域。
   新例句为空就返回 ""。纯文本：不要半角双引号、反斜杠、Markdown 标记。

只输出 JSON，不要任何解释文字：
{"results":[{"id":1,"meaning":"…","pos_cn":"…","translation":"…","note2":"…"}]}

待写条目：
%s
'''


# ============================================================================
# 纯函数（不碰 Anki / 模型 / 网络，测试直接喂）
# ============================================================================
def sanitize(s, limit=160):
    """模型产出 → 可进卡的纯文本：去反斜杠 / Markdown / 半角双引号，压空白。"""
    s = str(s or '')
    s = s.replace('\\', '').replace('```', '').replace('**', '')
    s = s.replace('"', '').replace('\u201c', '「').replace('\u201d', '」')
    s = re.sub(r'[\s　]+', ' ', s).strip()
    return s[:limit]


def plain_of(html):
    """字段值 → 纯文本（去 ruby/rt 与其余标签）。"""
    return RE.strip_text(html or '')


def flatten(text):
    """比较用：去空白后的文本（相似度、包含判断都走它）。"""
    return re.sub(r'[\s　]+', '', text or '')


def target_forms(word, card_word, reading):
    """目标词的「应在句中出现」写法集合（全部平假名归一）。"""
    out = set()
    for x in (word, card_word, reading):
        x = flatten(x)
        if x:
            out.add(RE.hira(x))
    return out


def sentence_ok(sentence, forms, existing_plain):
    """新句候选是否合格 → ``(bool, 不合格原因)``。

    四条：长度进闸门区间；句中出现目标词（平假名归一后包含）；
    与卡片原第一句不是换皮（相似度 < SIM_MAX）。振假名由调用方另判。
    """
    text = flatten(sentence)
    if len(text) < SENT_MIN:
        return False, '太短（%d 字）' % len(text)
    if len(text) > SENT_MAX:
        return False, '太长（%d 字）' % len(text)
    if not forms:
        return False, '没有可比对的词形'
    flat_hira = RE.hira(text)
    if not any(f in flat_hira for f in forms):
        return False, '句面不含目标词'
    if existing_plain:
        sim = difflib.SequenceMatcher(None, flatten(existing_plain), text).ratio()
        if sim >= SIM_MAX:
            return False, '与原句换皮（%.2f）' % sim
    return True, ''


def merge_block(old, new):
    """多句字段追加：``old<br><br>new``；old 空就只留 new。"""
    old, new = (old or '').strip(), (new or '').strip()
    if old and new:
        return '%s<br><br>%s' % (old, new)
    return new or old


def audio_name(note_id):
    return '%s-%d-sentence-2.mp3' % (AUDIO_PREFIX, int(note_id))


def merge_audio(old, name):
    """`Sentence Audio` 追加一个 [sound:]（去重，绝不重复追加）。"""
    tag = '[sound:%s]' % name
    if tag in (old or ''):
        return old
    return (old or '') + tag


def merge_ainote(old, sentence, note2):
    """`AINote` 追加/替换「② 新句」块（① 原正文一字不动，重跑是幂等的）。"""
    block = '<p><b>%s</b><br>%s<br>%s</p>' % (A2_MARK, sentence, note2)
    old = old or ''
    if A2_RE.search(old):
        return A2_RE.sub('\n%s' % block, old, count=1)
    return (old + '\n' + block) if old else block


def pos_conflict(card_pos, dict_pos_zh):
    """卡片词性与词典义项词性是否**确定冲突**（两边都认得出且不相交才算）。"""
    c = JC.card_families(card_pos or '')
    d = JC.card_families(dict_pos_zh or '')
    return bool(c and d and not (c & d))


def new_pos_en(card_pos, pos_cn_got, dict_pos_zh):
    """冲突时给新词性（英文口径）；模型词性认不出英文写法就不改。"""
    if not pos_conflict(card_pos, dict_pos_zh):
        return ''
    return POS_EN.get((pos_cn_got or '').strip(), '')


def sense_gloss_of(senses, i):
    """义项表第 i 条（1 起）的英文 gloss 拼接。"""
    if 0 < i <= len(senses or []):
        return '；'.join((senses[i - 1] or {}).get('glosses') or [])
    return ''


def dict_pos_of(senses, i):
    if 0 < i <= len(senses or []):
        return (senses[i - 1] or {}).get('pos') or ''
    return ''


def build_fields(live, rec, model, sent='', ruby=''):
    """（卡片现值 + 记录 + 模型产出）→ 要写的字段 dict（纯渲染，可单测）。

    ``sent``/``ruby`` 为空 = 没有可用新句 → 只改 Meaning（+词性）；
    Meaning 含内联标签（manual）由调用方提前拦下，这里不判。
    """
    nid_note = rec['word']          # 仅报错可读性
    fields = {}
    meaning = sanitize(model.get('meaning'), 80)
    if meaning:
        parsed = parse_meaning(live.get('Meaning', ''))
        fields['Meaning'] = render_meaning(parsed, meaning)
    pos = new_pos_en(live.get('Part of Speech', ''), model.get('pos_cn'),
                     rec.get('dict_pos') or '')
    if pos:
        fields['Part of Speech'] = pos
    if sent:
        fields['Sentence'] = merge_block(live.get('Sentence', ''), sent)
        fields['Sentence HTML'] = merge_block(live.get('Sentence HTML', ''), ruby)
        trans = sanitize(model.get('translation'), 60)
        if trans:
            fields['Sentence Translation'] = merge_block(
                live.get('Sentence Translation', ''), trans)
        note2 = sanitize(model.get('note2'), 160)
        if note2:
            fields['AINote'] = merge_ainote(live.get('AINote', ''), sent, note2)
    return fields


def judge_ok(res):
    """重判是否放行：True / None（判不了）都放行，与 sense gate「不误杀」同口径。"""
    return (res or {}).get('card_ok') is not False


def results_fixed_words(results):
    """修复结果 → 修好的词集（回插名单用）。"""
    return {r['word'] for r in results if r.get('ok')}


# ============================================================================
# 模型批量（语义部分；一批一次，不逐卡 ping-pong）
# ============================================================================
def _ask(cfg, chunk, LLM):
    """一批卡片 → {下标: 模型产出}；缺条目带反馈重问一次（口径同 sense_gate）。"""
    payload = json.dumps([{
        'id': i,
        'word': c['rec']['word'],
        'card_word': c['rec'].get('card_word') or '',
        'reading': c['rec'].get('reading') or '',
        'card_meaning': c['rec'].get('card_meaning') or '',
        'sentence': c['rec'].get('sentence') or '',
        'sense_gloss': c['rec'].get('sense_gloss') or '',
        'senses': c['rec'].get('senses') or [],
        'new_sentence': c['sent'] or '',
    } for i, c in enumerate(chunk, 1)], ensure_ascii=False, indent=1)
    msgs = [{'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': PROMPT % payload}]
    obj, _res, problems = LLM.call_json(cfg, msgs, require='results')
    got = {}
    if isinstance(obj, dict) and isinstance(obj.get('results'), list):
        for r in obj['results']:
            if not isinstance(r, dict):
                continue
            try:
                i = int(r.get('id'))
            except (TypeError, ValueError):
                continue
            if 1 <= i <= len(chunk) and i not in got:
                got[i] = {k: str(r.get(k) or '') for k in
                          ('meaning', 'pos_cn', 'translation', 'note2')}
    missing = [i for i in range(1, len(chunk) + 1) if i not in got]
    if missing and not problems:
        msgs2 = msgs + [
            {'role': 'assistant', 'content': json.dumps(obj, ensure_ascii=False)[:3000]},
            {'role': 'user', 'content': '你漏了 id=%s，只补这些，格式同上。' % missing},
        ]
        obj2, _r2, _p2 = LLM.call_json(cfg, msgs2, require='results')
        if isinstance(obj2, dict) and isinstance(obj2.get('results'), list):
            for r in obj2['results']:
                if not isinstance(r, dict):
                    continue
                try:
                    i = int(r.get('id'))
                except (TypeError, ValueError):
                    continue
                if i in missing and i not in got:
                    got[i] = {k: str(r.get(k) or '') for k in
                              ('meaning', 'pos_cn', 'translation', 'note2')}
    return got


def ask_models(cands, quiet=False):
    """候选 → 每张卡的模型产出（就地写进 ``c['model']``）。失败 → 空 dict。"""
    if not cands:
        return
    import local_llm as LLM
    cfg = LLM.load_config()
    for s in range(0, len(cands), BATCH):
        chunk = cands[s:s + BATCH]
        try:
            got = _ask(cfg, chunk, LLM)
        except Exception as exc:                  # noqa: BLE001  模型挂 = 这批失败，不挡流程
            if not quiet:
                print('  ⚠ 义项修复模型调用失败：%s' % exc, file=sys.stderr)
            got = {}
        for i, c in enumerate(chunk, 1):
            c['model'] = got.get(i) or {}


# ============================================================================
# 新句来源（真实语料：字幕句 → jisho；都不合格就没有新句，只改释义）
# ============================================================================
_LEX = None


def lexicon():
    """确定性振假名的读音词典（惰性；pinned + 本 deck + Sudachi）。"""
    global _LEX
    if _LEX is None:
        _LEX = RE.Lexicon.build(use_deck=True)
    return _LEX


def render_sentence(sentence):
    """字幕句 → ``(ruby_html, 硬伤列表)``。逐字一致是构造出来的（ruby_engine 骨架）。"""
    lex = lexicon()
    html = RE.render(sentence, lex)
    hard, _soft = RE.validate(sentence, html)
    bare = RE.bare_kanji(html)
    if bare:
        hard = list(hard) + ['未标假名的汉字：%s' % '、'.join(bare[:6])]
    return html, hard


def jisho_candidates(rec):
    """jisho 真实例句候选（复用 core6000_example 的抓页+过滤+振假名+缓存）。"""
    try:
        import core6000_example as CE
    except Exception:                             # noqa: BLE001
        return []
    ns = argparse.Namespace(refresh_jisho=False, jisho_timeout=30.0, no_dict=False)
    try:
        cands, _why = CE.jisho_fetch(
            {'id': int(rec['note_id']), 'word': rec.get('card_word') or rec['word'],
             'reading': rec.get('reading') or ''}, ns)
    except Exception:                             # noqa: BLE001  网络/依赖问题 = 没有候选
        return []
    return cands or []


def pick_sentence(rec, live):
    """(字幕句 → jisho) 里挑一条新句 → ``(sent, ruby, 来源, 都没有的原因)``。"""
    forms = target_forms(rec['word'], rec.get('card_word'), rec.get('reading'))
    blocks = _sentence_blocks(live.get('Sentence', ''))
    existing = plain_of(blocks[0]) if blocks else ''

    sub = (rec.get('sentence') or '').strip()
    ok, why_sub = sentence_ok(sub, forms, existing)
    if ok:
        ruby, hard = render_sentence(sub)
        if not hard:
            return sub, ruby, '字幕', ''
        why_sub = '振假名硬伤：%s' % '；'.join(hard[:2])

    blocked = []
    for c in jisho_candidates(rec):
        jp = (c.get('jp') or '').strip()
        ok, why = sentence_ok(jp, forms, existing)
        if not ok:
            blocked.append(why)
            continue
        if not c.get('ruby_ok'):
            blocked.append('jisho 振假名不合格')
            continue
        return jp, c.get('ruby') or '', 'jisho', ''
    if not blocked:
        blocked.append('jisho 无候选')
    return '', '', '', ('字幕句不合格（%s）；%s' % (why_sub, '；'.join(blocked[:3])))


def _sentence_blocks(raw):
    """`Sentence` 按块切开（口径同 today_new.split_field_blocks）。"""
    if not raw:
        return []
    blocks = re.split(r'(?:\s*<br\s*/?>\s*){2,}', raw, flags=re.I)
    if len(blocks) == 1:
        blocks = re.split(r'</p>\s*<p[^>]*>', raw, flags=re.I)
    return [b for b in (x.strip() for x in blocks) if b and plain_of(b)]


# ============================================================================
# 修复主流程
# ============================================================================
def _fail(word, nid, why, extra=None):
    r = {'word': word, 'note_id': nid, 'ok': False, 'status': 'failed',
         'why': why, 'fields': {}, 'audio': False}
    r.update(extra or {})
    return r


def repair(records, commit=False, quiet=False, do_tts=True):
    """义项核验剔除记录 → 逐词修复 → 结果列表。

    记录形状（= ``today_new_words`` 的 ``dropped_sense`` / picked.json）：
    ``word / note_id / card_word / reading / card_meaning / sentence(字幕句) /
    sense / senses / sense_gloss / why``。

    返回每张 ``(word, ok, status, why, fields…)``；``ok=True`` 的词回插今天名单。
    ``commit=False`` 只演练：模型产出与将写字段全打印，一个字都不写。
    """
    import sense_gate as SG

    results, cand = [], []
    todo = [r for r in records if r.get('note_id')]
    for r in records:
        if not r.get('note_id'):
            results.append(_fail(r['word'], 0, '旧版记录没有 note_id（重跑 today-new 生成）'))
    live = (AK.note_values([int(r['note_id']) for r in todo], names=FIELDS_TOUCH)
            if todo else {})
    for rec in todo:
        nid = int(rec['note_id'])
        base = live.get(nid) or {}
        if not base:
            results.append(_fail(rec['word'], nid, '笔记不存在'))
            continue
        if len(_sentence_blocks(base.get('Sentence', ''))) >= 2:
            results.append(_fail(rec['word'], nid, '已有 2 条例句（要补例句走 core6000 链路）'))
            continue
        parsed = parse_meaning(base.get('Meaning', ''))
        if parsed['manual']:
            results.append(_fail(rec['word'], nid, 'Meaning 含内联标签，只许手改'))
            continue
        cand.append({'rec': rec, 'live': base, 'sent': '', 'ruby': '', 'src': '',
                     'no_sent_why': '', 'model': {}, 'fields': {}, 'ok': False,
                     'why': ''})

    # ---- 1) 新句（真实语料） ----
    for c in cand:
        sent, ruby, src, why = pick_sentence(c['rec'], c['live'])
        c['sent'], c['ruby'], c['src'], c['no_sent_why'] = sent, ruby, src, why

    # ---- 2) 模型批量：新释义 / 词性 / 译文 / ② 讲解 ----
    ask_models(cand, quiet=quiet)
    for c in cand:
        c['fields'] = build_fields(c['live'], c['rec'], c['model'],
                                   sent=c['sent'], ruby=c['ruby'])
        if not c['fields'].get('Meaning'):
            c['why'] = '模型没给出新释义'
            continue
        c['ok'] = True

    # ---- 3) 重判：新释义对字幕句义项是否成立（缓存键随释义变，自然重判） ----
    items, judged = [], []
    for c in cand:
        if not c['ok']:
            continue
        rec = c['rec']
        items.append({
            'word': rec['word'], 'reading': rec.get('reading') or '',
            'sentence': rec.get('sentence') or c['sent'],
            'card_word': rec.get('card_word') or '',
            'card_meaning': c['fields']['Meaning'],
            'senses': rec.get('senses') or [],
        })
        judged.append(c)
    if judged:
        for c, res in zip(judged, SG.judge(items, quiet=quiet)):
            if not judge_ok(res):
                c['ok'] = False
                c['why'] = '修后重判仍对不上（%s）' % (res.get('why') or '')

    to_write = [c for c in cand if c['ok']]

    # ---- 4) TTS + 媒体（只 commit 时真合成；失败只记不挡） ----
    if commit and do_tts and to_write:
        os.makedirs(AUDIO_DIR, exist_ok=True)
        made = []
        for c in to_write:
            if not c['sent']:
                continue
            name = audio_name(int(c['rec']['note_id']))
            path = os.path.join(AUDIO_DIR, name)
            try:
                data = TTS.synth(plain_of(c['sent']), voice=VOICE)
                if not data or len(data) < MIN_MP3_BYTES:
                    raise RuntimeError('合成返回空音频')
                with open(path, 'wb') as fh:
                    fh.write(data)
                AK.store_media_file(name, path=path, delete_existing=True)
                made.append(name)
            except Exception as exc:              # noqa: BLE001  音频失败不挡修复
                if not quiet:
                    print('  ⚠ %s 配音失败（不挡修复）：%s' % (c['rec']['word'], exc),
                          file=sys.stderr)
                continue
            names = set(AK.media_names('%s-*.mp3' % AUDIO_PREFIX))
            if name not in names:
                if not quiet:
                    print('  ⚠ %s 媒体库缺 %s，不挂音频' % (c['rec']['word'], name),
                          file=sys.stderr)
                continue
            c['fields']['Sentence Audio'] = merge_audio(
                c['live'].get('Sentence Audio', ''), name)
            c['audio'] = True

    # ---- 5) 写库（writeback：备份 / 写 / 回读） ----
    rep = None
    if to_write:
        expected = {int(c['rec']['note_id']): c['fields'] for c in to_write}
        rep = WB.write_fields(expected, commit=commit, label='sense-repair',
                              quiet=quiet)
        if commit and rep and rep.get('bad'):
            for c in to_write:
                if int(c['rec']['note_id']) in rep['bad']:
                    c['ok'] = False
                    c['why'] = '写库/回读失败'

    # ---- 6) 汇报 ----
    if not quiet:
        for c in cand:
            rec = c['rec']
            mark = '✅' if c['ok'] else '⏭'
            sent_line = ('新句（%s）：%s' % (c['src'] or '无', c['sent'])) if \
                (c['sent'] and c['ok']) else (c['no_sent_why'] or c['why'] or
                                              ('只改释义' if c['ok'] else ''))
            print('  %s %-10s %s' % (mark, rec['word'], sent_line))
            if c['ok']:
                print('      释义 「%s」→「%s」｜写：%s%s'
                      % (SG.clean_text(rec.get('card_meaning') or '—', 30),
                         SG.clean_text(c['fields'].get('Meaning'), 40),
                         '、'.join(sorted(c['fields'])),
                         '' if commit else '（演练）'))
    for c in cand:
        rec = c['rec']
        results.append({
            'word': rec['word'], 'note_id': int(rec['note_id']),
            'ok': bool(c['ok']),
            'status': ('fixed' if commit else 'dry') if c['ok'] else 'failed',
            'why': c['why'] or c['no_sent_why'] or
                   ('释义已修 + 例句已补' if c['sent'] else '只改释义'),
            'sentence': c['sent'], 'sentence_source': c['src'],
            'meaning_old': SG.clean_text(rec.get('card_meaning') or '', 60),
            'meaning_new': SG.clean_text(c['fields'].get('Meaning'), 60),
            'audio': bool(c.get('audio')),
            'fields': sorted(c['fields']),
            'backup': (rep or {}).get('backup', '') if commit else '',
        })
    return results


# ============================================================================
# 独立 CLI：吃 picked.json 的 dropped_sense
# ============================================================================
def load_records(date=None, words=None):
    """``data/daily_new/<date>/picked.json`` → dropped_sense 记录列表。"""
    date = date or dt.date.today().isoformat()
    path = os.path.join(PICKED_ROOT, date, 'picked.json')
    if not os.path.isfile(path):
        raise SystemExit('没有 %s：先跑 cli.py today-new，或用 --date 指定' % path)
    data = textio.load_json(path)
    rows = data.get('dropped_sense') or []
    if words:
        want = {w.strip() for w in re.split(r'[,\s，、]+', words) if w.strip()}
        rows = [r for r in rows if r.get('word') in want]
    return path, rows


def cmd_plan(a):
    path, rows = load_records(a.date, a.words)
    print('来源：%s（%d 条义项剔除记录）' % (path, len(rows)))
    if not rows:
        return 0
    results = repair(rows, commit=False, do_tts=False)
    fixed = results_fixed_words(results)
    print('')
    print('可修复 %d / %d；其余维持剔除。真写：apply --commit' % (len(fixed), len(rows)))
    return 0


def cmd_apply(a):
    path, rows = load_records(a.date, a.words)
    print('来源：%s（%d 条义项剔除记录）' % (path, len(rows)))
    if not rows:
        print('没有要修的记录。')
        return 0
    results = repair(rows, commit=a.commit, do_tts=not a.no_tts)
    fixed = results_fixed_words(results)
    print('')
    if a.commit:
        print('已修复 %d / %d 张卡。这些词今天照常打 tag。' % (len(fixed), len(rows)))
        print('回退：revert --commit --backup <上面 writeback 备份路径>（媒体文件不删）')
    else:
        print('演练：%d 张可修，未写库（加 --commit 才写）。' % len(fixed))
    textio.dump_json({'at': dt.datetime.now().isoformat(timespec='seconds'),
                      'date': a.date or dt.date.today().isoformat(),
                      'commit': bool(a.commit), 'results': results},
                     os.path.join(DATA_DIR, 'repair_%s.json'
                                  % dt.datetime.now().strftime('%Y%m%d-%H%M%S')))
    return 0


def cmd_revert(a):
    if not a.backup or not os.path.isfile(a.backup):
        raise SystemExit('需要 --backup <writeback 备份 json>（apply 时打印的路径）')
    data = textio.load_json(a.backup)
    before = data.get('before') or {}
    if not before:
        raise SystemExit('备份里没有 before 字段值：%s' % a.backup)
    expected = {int(nid): vals for nid, vals in before.items() if vals}
    print('将还原 %d 张卡的旧字段（媒体文件不删）' % len(expected))
    rep = WB.write_fields(expected, commit=a.commit, label='sense-repair-revert')
    return 0 if rep['ok'] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description='义项修复：补真实例句 + 修 Meaning（默认演练）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name, func, help_ in (('plan', cmd_plan, '看将修什么（不写）'),
                              ('apply', cmd_apply, '修复（默认演练，--commit 真写）')):
        p = sub.add_parser(name, help=help_)
        p.add_argument('--date', default='', help='picked.json 的日期（默认今天）')
        p.add_argument('--words', default='', help='只修这些词（逗号/空格分隔）')
        p.add_argument('--no-tts', action='store_true', help='不配音')
        if name == 'apply':
            p.add_argument('--commit', action='store_true', help='真写库')
        p.set_defaults(func=func)
    p = sub.add_parser('revert', help='按 writeback 备份还原那批字段')
    p.add_argument('--backup', required=True, help='writeback 备份 json 路径')
    p.add_argument('--commit', action='store_true', help='真写库')
    p.set_defaults(func=cmd_revert)
    a = ap.parse_args(argv)
    os.makedirs(DATA_DIR, exist_ok=True)
    with AK.guard():
        return a.func(a)


if __name__ == '__main__':
    raise SystemExit(main())
