# -*- coding: utf-8 -*-
"""从字幕里提取「Anki 中已经存在、但还没学过」的日语生词。

它解决的是什么
--------------
看一集生肉/熟肉时，最想复习的是**自己词库里已经有、但还没学**的词：
这些词不是全新的（Anki 里已有卡片，释义/例句/音频都现成），
只是还没轮到。把它们从字幕里挑出来，就能在 Anki 里直接复习这一集的词。

判定口径
--------
1. **在 Anki 里存在**：只认 `0-日本语学习::0-词汇` 下的词汇卡
   （core6000 / 考级词汇 / 素材生词），按词形（`Word` / `VocabKanji`）匹配。
2. **还没学过**：该词的所有卡都还是新卡（`cards.type == 0`）。
   只要有一张卡是学习中/复习/重学，就算「已学过」，不输出。
3. **挂起卡**（`queue == -1`）与**埋藏卡**（`queue == -3`）单独归类；
   默认不当作可复习目标，但会在报告里列出来。
4. 词形用 Sudachi（SplitMode.C）还原成词典形；字幕里的活用形
   （`取り戻した` → `取り戻す`）会先归一化再查 Anki。
   连续词素拼起来的复合词（`魔神` + `族` → `魔神族`）也会再查一次。

字幕格式
--------
`.srt`（Netflix CC 的 `（说话人）` / 整行音效 / 注音都处理）、`.vtt`、
`.ass` / `.ssa`、纯文本；也支持 `-` 从 stdin 读纯文本。
底层复用 `code/analysis/vocab_cover/srt.py` 的 Netflix 字幕清洗器。

用法
----
    $PY code\\tools\\subtitle_new_words.py "字幕.srt"
    $PY code\\tools\\subtitle_new_words.py "字幕.srt" --out data/subtitle_review/xxx
    $PY code\\tools\\subtitle_new_words.py "字幕.srt" --limit 30 --min-occ 2

产物（默认写到 `data/subtitle_review/<字幕名>/`）
------------------------------------------------
* `words.json` —— 机器读（第二段代码 / 第三段通用任务吃这个）
* `words.tsv`  —— 人看 / Excel
* `report.md`  —— 人看的摘要与词表

只读：不写 Anki。Anki 的词表索引走 `Snapshot.open(live_copy=True)` 的只读副本；
写库只有 `subtitle_tag.py` 的加标签（只打 `复习::<来源>`，不改 due）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'analysis', 'vocab_cover'))

import anki_api as AK          # noqa: E402  Anki 访问的唯一入口
import jp_decks as JD          # noqa: E402  牌组常量
import paths as WSP           # noqa: E402  工作区路径
import textio                  # noqa: E402  UTF-8 stdio / 文件 I/O

try:                            # Netflix CC 清洗器（analysis/vocab_cover）
    import srt as VC_SRT        # noqa: E402
except Exception:               # pragma: no cover - 只在分析区被搬走时发生
    VC_SRT = None

# ============================================================================
# 配置
# ============================================================================
DEFAULT_SCOPES = (JD.DECK_VOCAB,)          # 0-日本语学习::0-词汇，含三个子牌组
DEFAULT_OUT_ROOT = os.path.join(WSP.DATA, 'subtitle_review')

# 值得做成词汇卡的内容词性（Sudachi 的 pos[0]）
CONTENT_POS = {'名詞', '動詞', '形容詞', '形容動詞', '副詞'}
# 名詞里这些子类不是「词」而是语法/数量
DROP_NOUN_POS1 = {'代名詞', '数詞'}
KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
KANA_ONLY = re.compile(r'^[\u3041-\u3096\u30a1-\u30fa\u30fc\u309d\u309eー]+$')
DIGIT_PUNCT = re.compile(r'^[\d\s\W_]+$', re.UNICODE)
MAX_WORD_LEN = 30

# 人名后缀：`バン様`、`キング様`、`エリザベス様`。纯片假名/专有名词 + 这些后缀
# 一律当人名（这类词在 Anki 里也常被当成「外来语」收进来，但不该进复习词表）。
HONORIFICS = ('様', 'さん', 'ちゃん', '君', 'くん', '殿', '氏', '王子', '王女', '姫')
# 人称代词：Sudachi 通常标 代名詞，但口语里偶尔标成名词，补一张小名单。
PRONOUNS = {
    'てめえ', 'てまえ', 'お前', '俺', '僕', '私', 'あたし', 'わたし', 'あなた',
    '君', 'きみ', '彼', '彼女', 'やつ', '奴', 'あいつ', 'こいつ', 'そいつ',
    'どいつ', 'われ', '我', '我々', 'おれ', 'わし', '自分',
}

# 词表字段按笔记类型取
_MODEL_FIELDS = {
    'Japanese Vocabulary': {
        'word': 'Word', 'reading': 'Transliteration', 'pos': 'Part of Speech',
        'meaning': 'Meaning',
    },
    'eggrolls-JLPT10k-v3.5': {
        'word': 'VocabKanji', 'reading': 'VocabFurigana', 'pos': 'VocabPoS',
        'meaning': 'VocabDefSC',
    },
    'ImmersionKitCard': {
        'word': 'Word', 'reading': 'Reading', 'pos': '', 'meaning': 'Definition',
    },
}


# ============================================================================
# 小工具
# ============================================================================
def norm(s):
    """NFKC + 去首尾空白。索引与字幕两侧必须用同一套归一化。"""
    return unicodedata.normalize('NFKC', (s or '').strip())


def kata2hira(s):
    out = []
    for ch in s or '':
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return ''.join(out)


def _word_keys(word):
    """一个词形可能有的写法（只做保守变体，不做片假名→平假名）。"""
    w = norm(word)
    keys = {w}
    for sep in ('・', ' ', '\u3000', '=', '＝'):
        if sep in w:
            keys.add(w.replace(sep, ''))
    return {k for k in keys if k}


def _fmt_ms(ms):
    if not ms:
        return ''
    sec, _ = divmod(int(ms), 1000)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return ('%d:%02d:%02d' % (h, m, s)) if h else ('%02d:%02d' % (m, s))


def _slug(s, limit=60):
    s = re.sub(r'[\s\u3000]+', '_', s or '')
    s = re.sub(r'[^\w\u3040-\u30ff\u4e00-\u9fff.\-]+', '_', s, flags=re.UNICODE)
    return (s.strip('_') or 'subtitle')[:limit]


def _deck_priority(deck):
    """同形词出现在多个牌组时的偏好：core6000 / 考级（读音经过校对）优先于素材生词。"""
    if deck == JD.DECK_CORE6000:
        return 0
    if deck == JD.DECK_KAOKYU:
        return 1
    if deck == JD.DECK_MINED:
        return 2
    return 3


def _bad_anki_pos(pos, include_phrases=False):
    """Anki 的 `Part of Speech` 里哪些不是「一个词」：惯用句/成句/词缀/代词/数词。"""
    p = (pos or '').strip()
    if not p:
        return False
    if not include_phrases and any(x in p for x in (
            '惯用句', '慣用句', '成句', 'Interjection', 'Phrase', 'Expression',
            '感動詞', '感动词')):
        return True
    if any(x in p for x in ('接頭', '接尾', 'Prefix', 'Suffix')) or p == '造':
        return True
    if any(x in p for x in ('代名詞', '代词', '数詞', '数词')):
        return True
    return False


def _compound_ok(t):
    """复合词只允许内容词 + 词缀拼接（`魔神`+`族` 可以，`た`+`ん` 不行）。"""
    return t.pos0 in CONTENT_POS or t.pos0 in ('接尾辞', '接頭辞')


# ============================================================================
# 字幕解析
# ============================================================================
@dataclass
class Cue:
    index: int
    start: str
    text: str


def _clean(line):
    """→ (台词, 是否台词)。优先用分析区那份 Netflix 清洗器。"""
    if VC_SRT is not None:
        text, is_speech, _speakers = VC_SRT.clean_line(line)
        return text, is_speech
    raw = norm(line)
    raw = re.sub(r'\{[^}]*\}', '', raw)
    raw = re.sub(r'</?[a-zA-Z][^>]*>', '', raw)
    raw = raw.replace('\\N', ' ').replace('\\n', ' ')
    raw = re.sub(r'[♪♬♩♭]', '', raw)
    if re.match(r'^[（(\[［【][^）)\]］】]*[）)\]］】][。、！？!?…～\s]*$', raw.strip()):
        return '', False
    raw = re.sub(r'^[（(\[［【][^）)\]］】]{1,24}[）)\]］】]\s*', '', raw)
    raw = re.sub(r'[（(][^）)]{0,20}[）)]', '', raw)
    raw = re.sub(r'[\s\u3000]+', ' ', raw).strip(' \u3000-–—')
    if not raw or not re.search(r'[\u3041-\u3096\u30a1-\u30fa\u4e00-\u9fff]', raw):
        return '', False
    return raw, True


def _parse_srt_fallback(text):
    cues = []
    norm_text = text.replace('\r\n', '\n').replace('\r', '\n')
    for chunk in re.split(r'\n[ \t]*\n', norm_text.strip('\n')):
        lines = [l for l in chunk.split('\n') if l.strip()]
        if len(lines) < 2:
            continue
        tc = next((l for l in lines[:3] if '-->' in l), None)
        if not tc:
            continue
        start = tc.split('-->')[0].strip()
        for body in lines[lines.index(tc) + 1:]:
            cleaned, ok = _clean(body)
            if ok and cleaned:
                cues.append((start, cleaned))
    return cues


def _parse_vtt(text):
    cues = []
    norm_text = text.replace('\r\n', '\n').replace('\r', '\n')
    for block in re.split(r'\n[ \t]*\n', norm_text.strip('\n')):
        lines = [l for l in block.split('\n') if l.strip()]
        if not lines or lines[0].strip().upper().startswith('WEBVTT'):
            continue
        tc = next((l for l in lines if '-->' in l), None)
        if not tc:
            continue
        start = tc.split('-->')[0].strip()
        for body in lines[lines.index(tc) + 1:]:
            cleaned, ok = _clean(body)
            if ok and cleaned:
                cues.append((start, cleaned))
    return cues


def _parse_ass(text):
    cues = []
    in_events = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('['):
            in_events = s.lower().startswith('[events]')
            continue
        if not in_events or not s.lower().startswith('dialogue:'):
            continue
        payload = s.split(':', 1)[1]
        parts = payload.split(',', 9)
        if len(parts) < 10:
            continue
        start = parts[1].strip()
        body = parts[9].replace('\\N', ' ').replace('\\n', ' ')
        cleaned, ok = _clean(body)
        if ok and cleaned:
            cues.append((start, cleaned))
    return cues


def load_cues(path):
    """读字幕 → [Cue]。path 为 '-' 时按纯文本读 stdin。"""
    if path == '-':
        text = textio.read_stdin()
        ext = '.txt'
        name = 'stdin'
    else:
        text = textio.read_text(path, encodings=(
            'utf-8-sig', 'utf-8', 'cp932', 'shift_jis', 'euc_jp', 'gb18030'))
        ext = os.path.splitext(path)[1].lower()
        name = os.path.splitext(os.path.basename(path))[0]

    if ext == '.srt' and VC_SRT is not None:
        ep = VC_SRT.parse_srt(path) if path != '-' else None
        if ep is not None:
            return [Cue(c.index, _fmt_ms(c.start_ms), c.text.strip())
                    for c in ep.cues if c.is_speech and c.text.strip()]
        cues = _parse_srt_fallback(text)
    elif ext in ('.ass', '.ssa'):
        cues = _parse_ass(text)
    elif ext == '.vtt':
        cues = _parse_vtt(text)
    elif ext == '.srt':
        cues = _parse_srt_fallback(text)
    else:
        cues = []
        for i, line in enumerate(text.splitlines(), 1):
            cleaned, ok = _clean(line)
            if ok and cleaned:
                cues.append((str(i), cleaned))

    return [Cue(i, start, txt) for i, (start, txt) in enumerate(cues, 1)]


# ============================================================================
# 分词
# ============================================================================
@dataclass
class Tok:
    surface: str
    base: str
    norm_form: str
    reading: str
    pos0: str
    pos1: str
    begin: int
    end: int


_TOKENIZER = None


def _tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        pylibs = os.path.join(WSP.DATA, 'pylibs')
        if pylibs not in sys.path:
            sys.path.append(pylibs)
        from sudachipy import Dictionary, SplitMode
        d = Dictionary(dict='core')
        maker = getattr(d, 'tokenizer', None) or d.create
        _TOKENIZER = (maker(), SplitMode.C)
    return _TOKENIZER


def tokenize(text):
    tok, mode = _tokenizer()
    out = []
    for m in tok.tokenize(text, mode):
        pos = m.part_of_speech()
        out.append(Tok(
            surface=m.surface(),
            base=m.dictionary_form() or m.surface(),
            norm_form=m.normalized_form() or m.surface(),
            reading=kata2hira(m.reading_form() or ''),
            pos0=pos[0] if len(pos) > 0 else '',
            pos1=pos[1] if len(pos) > 1 else '',
            begin=m.begin(),
            end=m.end(),
        ))
    return out


def word_reading(word):
    """词典形本身的读音（不是活用形的读音）。

    直接 tokenize `知れる` 得 しれる，而字幕里 `知れ` 的 token.reading 是 しれ；
    读音一律以词典形为准，避免把 `知れ/成そう/効か` 的活用尾音当成词条读音。
    """
    try:
        ms = tokenize(word)
    except Exception:
        return ''
    return ''.join(m.reading for m in ms).strip()


def is_content_token(t, extra_pos=()):
    """内容词判定。``extra_pos`` 额外放行某些词性（如 ``('助詞', '感動詞')``）。

    放开助词时**必须同时放开单字假名**：``ね`` / ``よ`` / ``か`` / ``の`` 都是
    一个字、纯假名，会被下面那条「单字非汉字」规则直接丢掉。
    """
    allowed = tuple(CONTENT_POS) + tuple(extra_pos or ())
    if t.pos0 not in allowed:
        return False
    if t.pos0 == '名詞' and t.pos1 in DROP_NOUN_POS1:
        return False
    if not t.base or DIGIT_PUNCT.match(t.base):
        return False
    is_extra = bool(extra_pos) and t.pos0 in tuple(extra_pos)
    if not is_extra and len(t.base) == 1 and not KANJI.search(t.base):
        return False
    if len(t.base) > MAX_WORD_LEN:
        return False
    return True


# ============================================================================
# Anki 词表索引（只读快照）
# ============================================================================
@dataclass
class Entry:
    word: str
    reading: str
    pos: str
    deck: str
    level: str
    note_id: int
    card_id: int
    type: int
    queue: int
    due: int
    interval: int
    factor: int
    reps: int
    lapses: int
    jiten: int
    meaning: str
    tags: tuple = ()


class VocabIndex:
    """Anki 词汇卡的词形 → 卡片状态索引。"""

    def __init__(self, entries, key2words, kana2words):
        self.entries = entries          # canonical word -> [Entry]
        self.key2words = key2words      # 归一化写法 -> [canonical word]
        self.kana2words = kana2words    # 假名读音 -> [纯假名词]

    # ---- 构建 ------------------------------------------------------------
    @classmethod
    def load(cls, scopes=None, snapshot_path=None):
        scopes = list(scopes or DEFAULT_SCOPES)
        entries = {}
        key2words = {}
        kana2words = {}
        with AK.Snapshot.open(path=snapshot_path,
                              live_copy=not bool(snapshot_path)) as snap:
            decks = snap.decks()
            deck_ids = set()
            for scope in scopes:
                ids = snap.deck_id(scope)
                if not ids:
                    raise SystemExit('牌组不存在或没有子牌组：%s' % scope)
                deck_ids.update(ids)
            if not deck_ids:
                raise SystemExit('没有找到任何词汇牌组')

            sql = (
                'SELECT n.id AS nid, n.mid AS mid, n.flds AS flds, n.tags AS tags, '
                'c.id AS cid, c.did AS did, c.type AS type, c.queue AS queue, '
                'c.due AS due, c.ivl AS ivl, c.factor AS factor, '
                'c.reps AS reps, c.lapses AS lapses '
                'FROM notes n JOIN cards c ON c.nid = n.id '
                'WHERE c.did IN (%s)' % ','.join('?' * len(deck_ids))
            )
            rows = list(snap.con.execute(sql, tuple(sorted(deck_ids))))

            # 按笔记分组：字段只解一次
            by_note = {}
            for r in rows:
                by_note.setdefault(int(r['nid']), []).append(r)

            for nid, cards in by_note.items():
                r0 = cards[0]
                model, _order = snap.notetype(int(r0['mid']))
                fmap = _MODEL_FIELDS.get(model)
                if not fmap:
                    continue
                vals = snap.split_fields(int(r0['mid']), r0['flds'])
                word = norm(vals.get(fmap['word']) or '')
                if not word or len(word) > MAX_WORD_LEN:
                    continue
                reading = norm(vals.get(fmap['reading']) or '')
                pos = norm(vals.get(fmap['pos']) or '')
                meaning = (vals.get(fmap['meaning']) or '').strip()
                try:
                    jiten = int(str(vals.get('JitenAnimeRank') or '999999').strip())
                except ValueError:
                    jiten = 999999
                tags = tuple((r0['tags'] or '').split())
                deck0 = decks.get(int(r0['did']), '')
                level = JD.level_from_tags(tags)
                if not level:
                    if deck0 == JD.DECK_CORE6000:
                        level = 'Core6000'
                    elif deck0 == JD.DECK_MINED:
                        level = '素材生词'
                    else:
                        level = deck0.split('::')[-1] if deck0 else '?'

                for r in cards:
                    deck = decks.get(int(r['did']), deck0)
                    entries.setdefault(word, []).append(Entry(
                        word=word, reading=reading, pos=pos, deck=deck,
                        level=(JD.level_from_tags(tags) or level),
                        note_id=nid, card_id=int(r['cid']),
                        type=int(r['type']), queue=int(r['queue']),
                        due=int(r['due']), interval=int(r['ivl'] or 0),
                        factor=int(r['factor'] or 0), reps=int(r['reps'] or 0),
                        lapses=int(r['lapses'] or 0), jiten=jiten,
                        meaning=meaning, tags=tags,
                    ))

        for word in entries:
            for key in _word_keys(word):
                key2words.setdefault(key, []).append(word)
            if KANA_ONLY.match(word) and len(word) >= 2:
                kana2words.setdefault(kata2hira(word), []).append(word)
        return cls(entries, key2words, kana2words)

    # ---- 查询 ------------------------------------------------------------
    def words_for_key(self, key):
        return self.key2words.get(norm(key), [])

    def resolve(self, word):
        """把用户给的词（可能是活用形/表记变体）解析成 Anki 里的 canonical 词。"""
        key = norm(word)
        hits = list(self.words_for_key(key))
        if hits:
            return hits
        try:
            toks = tokenize(key)
        except Exception:
            toks = []
        if len(toks) == 1:
            for cand in (toks[0].base, toks[0].norm_form, toks[0].surface):
                hits = self.words_for_key(cand)
                if hits:
                    return hits
        if len(toks) > 1:
            joined = ''.join(t.surface for t in toks)
            hits = self.words_for_key(joined)
            if hits:
                return hits
        # 汉字写法 ↔ 纯假名词：只接受唯一候选，避免 かえる→帰る/変える 这类歧义
        if len(toks) == 1 and toks[0].reading:
            cands = self.kana2words.get(toks[0].reading, [])
            if len(cands) == 1:
                return cands
        return []


# ============================================================================
# 匹配
# ============================================================================
@dataclass
class Hit:
    word: str
    begin: int
    end: int
    surface: str
    reading: str = ''
    proper: bool = False
    name_like: bool = False
    pos0: str = ''
    pos1: str = ''


def _dedupe_hits(hits):
    """同一段文字只留最长的那个词（魔神族 覆盖 魔神）。"""
    uniq = {}
    for h in hits:
        uniq.setdefault((h.word, h.begin, h.end), h)
    ordered = sorted(uniq.values(), key=lambda h: (-(h.end - h.begin), h.begin, h.word))
    kept = []
    for h in ordered:
        if any(not (h.end <= k.begin or h.begin >= k.end) for k in kept):
            continue
        kept.append(h)
    kept.sort(key=lambda h: (h.begin, h.end))
    return kept


def find_hits(text, index, include_names=False, include_phrases=False,
              proper_out=None, extra_pos=()):
    toks = tokenize(text)
    hits = []
    # 1) 单词素：只用词典形 / 规范形，**不用表面形**
    #    （否则 `出`（base=出る）会把一张坏卡「出」也匹配出来；
    #     假名词写成汉字的情况由 kana2words 兜底。）
    for t in toks:
        if not is_content_token(t, extra_pos=extra_pos):
            continue
        if t.pos1 == '固有名詞':
            # 同一个词可能一处标专名、一处标普通名词；只要有一处是专名，
            # 就整词当人名/地名（`バン` 在「バンも…」里是普通名词）。
            if proper_out is not None:
                proper_out.update(_word_keys(t.base))
                proper_out.update(_word_keys(t.surface))
            if not include_names:
                continue
        if t.base in PRONOUNS or t.surface in PRONOUNS:
            continue
        words = []
        for key in (t.base, t.norm_form):
            words = index.words_for_key(key)
            if words:
                break
        if not words and t.reading and not KANA_ONLY.match(t.surface):
            # 汉字词写成假名，而 Anki 里是纯假名词（唯一候选才收，避免 かえる 歧义）
            cands = index.kana2words.get(t.reading, [])
            if len(cands) == 1:
                words = cands
        for w in words:
            hits.append(Hit(w, t.begin, t.end, t.surface,
                            reading=t.reading, proper=(t.pos1 == '固有名詞'),
                            pos0=t.pos0, pos1=t.pos1))

    # 2) 连续词素拼起来的复合词（魔神 + 族 → 魔神族）。
    #    只允许内容词 / 词缀参与，避免 `た`+`ん` → `たん`、`ん`+`な` → `んな` 这类假阳性。
    for i in range(len(toks)):
        if not _compound_ok(toks[i]):
            continue
        for k in range(2, min(4, len(toks) - i) + 1):
            window = toks[i:i + k]
            if not all(_compound_ok(x) for x in window):
                continue
            if not include_names and any(x.pos1 == '固有名詞' for x in window):
                continue
            joined = ''.join(x.surface for x in window)
            if len(joined) < 2:
                continue
            for w in index.words_for_key(joined):
                hits.append(Hit(w, toks[i].begin, toks[i + k - 1].end, joined,
                                reading=''.join(x.reading for x in window)))

    hits = _dedupe_hits(hits)
    # 人名启发：纯片假名 / 专有名词 + 敬称后缀 → 当人名（バン様 / キング様 / エリザベス様）
    for h in hits:
        tail = text[h.end:h.end + 2].lstrip(' \u3000')
        if tail and tail[0] in HONORIFICS and (KANA_ONLY.match(h.word) or h.proper):
            h.name_like = True
    return hits


# ============================================================================
# 归类与产出
# ============================================================================
def _pick_entry(entries):
    """从同形词的多张卡里挑一张代表卡：新卡优先，读音经过校对的牌组优先。"""
    fresh = [e for e in entries if e.type == 0]
    pool = fresh or entries
    return min(pool, key=lambda e: (e.queue == -1, e.queue == -3,
                                    _deck_priority(e.deck), e.jiten, e.note_id))


def classify(entries):
    """→ (state, pick)。state ∈ new / learned / suspended。"""
    pick = _pick_entry(entries)
    if any(e.type != 0 for e in entries):
        return 'learned', pick
    if all(e.queue == -1 for e in entries):
        return 'suspended', pick
    return 'new', pick


def build_records(cues, index, min_occ=1, include_names=False,
                  include_phrases=False):
    found = {}
    proper_words = set()
    for cue in cues:
        for h in find_hits(cue.text, index, include_names=include_names,
                           include_phrases=include_phrases,
                           proper_out=proper_words):
            rec = found.setdefault(h.word, {
                'occ': 0, 'surfaces': set(), 'examples': [], 'first': None,
                'readings': [], 'name_like': False,
            })
            rec['occ'] += 1
            rec['surfaces'].add(h.surface)
            if h.reading:
                rec['readings'].append(h.reading)
            if h.name_like:
                rec['name_like'] = True
            if rec['first'] is None:
                rec['first'] = cue
            if len(rec['examples']) < 3:
                if not any(e.index == cue.index for e in rec['examples']):
                    rec['examples'].append(cue)

    words, excluded = [], {'learned': [], 'suspended': []}
    filtered = {'names': 0, 'phrases': 0}
    for word, agg in found.items():
        if agg['occ'] < min_occ:
            continue
        entries = index.entries[word]
        usable = [e for e in entries if not _bad_anki_pos(e.pos, include_phrases)]
        if not usable:
            filtered['phrases'] += 1
            continue
        if not include_names and (agg['name_like'] or word in proper_words
                                  or any(k in proper_words for k in _word_keys(word))):
            filtered['names'] += 1
            continue
        # 「学过」要看**所有**卡（包括词性不合、被 usable 过滤掉的卡）：
        # 例：`式` 在 core6000 是新卡，但在考级词汇里已是复习卡（词性 名・接尾），
        # 这种词整体算学过，不能因为过滤掉词缀卡就把它当新词再建一张。
        if any(e.type != 0 for e in entries):
            state, pick = 'learned', _pick_entry(entries)
        elif all(e.queue == -1 for e in entries):
            state, pick = 'suspended', _pick_entry(entries)
        else:
            state, pick = classify(usable)

        # 读音：以词典形读音为准（避免把 `知れ/成そう` 的活用尾音当词条读音），
        # 只在“首音节与上下文冲突、而卡片读音与上下文一致”时改用卡片读音。
        # 这一步专治两粒 Sudachi 的怪读音：`民=みん`（上下文 たみ）、`就く=づく`（卡片/上下文 つく）。
        lemma_read = (word_reading(word) or '').replace(' ', '').replace('\u3000', '')
        context_read = ''
        if agg['readings']:
            context_read = Counter(agg['readings']).most_common(1)[0][0]
        context_read = (context_read or '').replace(' ', '').replace('\u3000', '')
        card_read = (pick.reading or '').replace(' ', '').replace('\u3000', '')

        def _first_kana(s):
            for ch in s or '':
                if ('\u3041' <= ch <= '\u3096') or ('\u30a1' <= ch <= '\u30fa'):
                    return ch
            return ''

        lf, cf, kf = _first_kana(lemma_read), _first_kana(context_read), _first_kana(card_read)
        if lemma_read and context_read and card_read and lf and cf and kf \
                and lf != cf and kf == cf:
            reading = card_read
        else:
            reading = lemma_read or context_read or card_read

        base = {
            'word': word,
            'reading': reading,
            'pos': pick.pos,
            'occurrences': agg['occ'],
            'surfaces': sorted(agg['surfaces']),
            'deck': pick.deck,
            'level': pick.level,
            'noteId': pick.note_id,
            'cardId': pick.card_id,
            'jiten': pick.jiten,
            'type': pick.type,
            'queue': pick.queue,
            'due': pick.due,
            'meaning': pick.meaning,
            'duplicates': len({e.note_id for e in entries}),
            'first': {'index': agg['first'].index, 'start': agg['first'].start,
                      'text': agg['first'].text},
            'examples': [{'index': c.index, 'start': c.start, 'text': c.text}
                         for c in agg['examples']],
        }
        if state == 'new':
            if pick.queue == -3:
                base['buried'] = True
            words.append(base)
        else:
            base['reason'] = ('已学过' if state == 'learned' else '已挂起')
            excluded[state].append(base)

    words.sort(key=lambda w: (-w['occurrences'], w['jiten'], w['word']))
    for lst in excluded.values():
        lst.sort(key=lambda w: (-w['occurrences'], w['word']))
    return words, excluded, filtered


def _counts(cues, index, words, excluded, filtered=None):
    return {
        'cues': len(cues),
        'chars': sum(len(c.text) for c in cues),
        'new_words': len(words),
        'learned_words': len(excluded['learned']),
        'suspended_words': len(excluded['suspended']),
        'filtered_names': (filtered or {}).get('names', 0),
        'filtered_phrases': (filtered or {}).get('phrases', 0),
        'occurrences': sum(w['occurrences'] for w in words),
        'decks': _deck_counts(words),
    }


def _deck_counts(words):
    out = {}
    for w in words:
        key = w['deck'].split('::')[-1]
        out[key] = out.get(key, 0) + 1
    return out


def write_outputs(result, out_dir, next_hint=None):
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, 'words.json')
    tsv_path = os.path.join(out_dir, 'words.tsv')
    md_path = os.path.join(out_dir, 'report.md')
    textio.dump_json(result, json_path)

    lines = ['word\treading\tpos\toccurrences\tdeck\tlevel\tjiten\tnoteId\tcardId\tfirst_time\tfirst_text']
    for w in result['words']:
        first = w.get('first') or {}
        lines.append('\t'.join(str(x).replace('\t', ' ') for x in (
            w['word'], w['reading'], w['pos'], w['occurrences'],
            w['deck'], w['level'], w['jiten'], w['noteId'], w['cardId'],
            first.get('start', ''), first.get('text', ''),
        )))
    textio.write_text(tsv_path, '\n'.join(lines) + '\n')

    textio.write_text(md_path, _report_md(result, next_hint=next_hint))
    return json_path, tsv_path, md_path


def _report_md(result, next_hint=None):
    meta = result['meta']
    c = meta['counts']
    out = []
    out.append('# 字幕生词（Anki 已有、尚未学习）')
    out.append('')
    out.append('- 字幕：`%s`' % meta['source'])
    out.append('- 生成：%s' % meta['generated_at'])
    out.append('- 范围：%s' % ' / '.join(meta['scopes']))
    out.append('- 字幕条数：%d（%d 字）' % (c['cues'], c['chars']))
    out.append('- **可复习的新词：%d 个**（共出现 %d 次）' % (c['new_words'], c['occurrences']))
    out.append('- 已学过（排除）：%d 个；已挂起：%d 个'
                % (c['learned_words'], c['suspended_words']))
    if c.get('filtered_names') or c.get('filtered_phrases'):
        out.append('- 已过滤非词条目：人名 %d 个，短语/语气词/词缀 %d 个'
                    % (c['filtered_names'], c['filtered_phrases']))
    if c['decks']:
        out.append('- 按牌组：%s' % '，'.join('%s %d' % (k, v)
                                            for k, v in sorted(c['decks'].items())))
    out.append('')
    out.append('## 词表（按本集出现次数排序）')
    out.append('')
    out.append('| # | 词 | 读音 | 词性 | 次数 | 首次 | 牌组 | Jiten |')
    out.append('|---|---|---|---|---:|---|---|---:|')
    for i, w in enumerate(result['words'], 1):
        first = w.get('first') or {}
        out.append('| %d | %s | %s | %s | %d | %s | %s | %s |' % (
            i, w['word'], w['reading'] or '', w['pos'] or '', w['occurrences'],
            first.get('start', ''), w['deck'].split('::')[-1], w['jiten']))
    out.append('')
    out.append('## 例句（前 10 个词）')
    out.append('')
    for w in result['words'][:10]:
        out.append('### %s（%s）' % (w['word'], w['reading'] or '—'))
        for e in w['examples']:
            out.append('- `%s` %s' % (e['start'], e['text']))
        out.append('')
    if result['excluded']['learned']:
        out.append('## 已学过（不激活）')
        out.append('')
        out.append('、'.join(w['word'] for w in result['excluded']['learned']))
        out.append('')
    if result['excluded']['suspended']:
        out.append('## 已挂起（不激活）')
        out.append('')
        out.append('、'.join(w['word'] for w in result['excluded']['suspended']))
        out.append('')
    if next_hint:
        out.append(next_hint)
    else:
        out.append('> 下一步：给这集打复习标签：`python code\\tools\\subtitle_tag.py "%s" --name <来源> --commit`'
                   % meta['source'])
    out.append('')
    return '\n'.join(out)


# ============================================================================
# 对外 API / CLI
# ============================================================================
def extract(subtitle, scopes=None, out_root=None, limit=0, min_occ=1,
            index=None, quiet=False, include_names=False, include_phrases=False):
    """字幕 → 生词结果 dict。不给 out_dir 时不写盘。"""
    cues = load_cues(subtitle)
    if not cues:
        raise SystemExit('没有从字幕里解析出任何台词：%s' % subtitle)
    if index is None:
        index = VocabIndex.load(scopes=scopes)
    words, excluded, filtered = build_records(
        cues, index, min_occ=min_occ, include_names=include_names,
        include_phrases=include_phrases)
    if limit and limit > 0:
        words = words[:limit]

    name = 'stdin' if subtitle == '-' else os.path.splitext(os.path.basename(subtitle))[0]
    out_dir = os.path.join(out_root or DEFAULT_OUT_ROOT, _slug(name))
    counts = _counts(cues, index, words, excluded, filtered)
    result = {
        'meta': {
            'source': subtitle,
            'source_name': name,
            'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
            'scopes': list(scopes or DEFAULT_SCOPES),
            'out_dir': out_dir,
            'counts': counts,
        },
        'words': words,
        'excluded': excluded,
    }
    if not quiet:
        print('字幕：%s' % subtitle)
        print('  %d 条台词 / %d 字' % (counts['cues'], counts['chars']))
        print('  ✅ 可复习的新词 %d 个（出现 %d 次）'
              % (counts['new_words'], counts['occurrences']))
        print('  ⛔ 已学过 %d 个 / 已挂起 %d 个'
              % (counts['learned_words'], counts['suspended_words']))
        if counts['filtered_names'] or counts['filtered_phrases']:
            print('  🧹 已过滤人名 %d / 短语·语气词·词缀 %d'
                  % (counts['filtered_names'], counts['filtered_phrases']))
    return result


def cmd_main(argv=None):
    ap = argparse.ArgumentParser(description='从字幕提取 Anki 已有但还没学的生词')
    ap.add_argument('subtitle', help='字幕文件（.srt/.vtt/.ass/.txt），或 - 读 stdin')
    ap.add_argument('--scope', action='append', default=None,
                    help='词汇牌组前缀，可重复；默认 %s' % JD.DECK_VOCAB)
    ap.add_argument('--out', default=None, help='输出目录（默认 data/subtitle_review/<字幕名>）')
    ap.add_argument('--limit', type=int, default=0, help='只取前 N 个词（0=全部）')
    ap.add_argument('--min-occ', type=int, default=1, help='至少出现 N 次（默认 1）')
    ap.add_argument('--include-names', action='store_true',
                    help='保留人名/专有名词（默认过滤「バン様」这类纯片假名人名）')
    ap.add_argument('--include-phrases', action='store_true',
                    help='保留 Anki 标为惯用句/成句的词条（Sudachi 判为感叹词/代词的仍会过滤）')
    ap.add_argument('--no-write', action='store_true', help='只打印，不写 words.json/report.md')
    a = ap.parse_args(argv)

    with AK.guard():
        result = extract(a.subtitle, scopes=a.scope, out_root=a.out,
                         limit=a.limit, min_occ=a.min_occ,
                         include_names=a.include_names,
                         include_phrases=a.include_phrases)
    out_dir = result['meta']['out_dir']
    if not a.no_write:
        paths = write_outputs(result, out_dir)
        print('')
        print('已写出：')
        for p in paths:
            print('  %s' % p)
    print('')
    print('下一步：')
    print('  $PY code\\tools\\subtitle_tag.py "%s" --name <来源> --commit' % a.subtitle)
    return 0


if __name__ == '__main__':
    raise SystemExit(cmd_main())
