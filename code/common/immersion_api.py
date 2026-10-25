# -*- coding: utf-8 -*-
"""ImmersionKit 只读客户端 + 例句清洗 / 筛选 / 振假名转 HTML。

定位
----
`code/common/anki_api.py` 是 **Anki** 的唯一访问点；本模块只管**网络与文本**，
不 import anki_api —— 抓取与写库分开，缓存和纯函数才好单测（见
`code/tests/test_immersionkit.py`）。

实测事实（2026-10 本地跑通，详见 docs/immersionkit-使用说明.md）
--------------------------------------------------------------
* 数据 API：``https://apiv2.immersionkit.com``（FastAPI，``/openapi.json`` 可读）。
* ``GET /search?q=<词>`` **无需登录**即 200；登录口令在整条流水线里用不上。
* 默认 UA（``Python-urllib/3.x``）会被挡成 **403** → 必须带浏览器 UA。
* ``limit`` **被服务端忽略**（一律客户端切片）；``offset`` 有效，但会连带改变
  ``category_count``（所以计数只当参考）；``index`` 传任何值都 400，别传；
  非法 ``category``（``news``/``zzz``）会**静默变成不筛选** → 客户端得再校验一次。
* ``exactMatch=true`` 时 ``dictionary_entries`` 收敛到 1 条 JMdict 词条
  （headword / reading / tags / glossary_list / sound）。
* ``showUrlInMedia=true`` 时 ``image``/``sound`` 直接是 CDN 全 URL，可直接 GET。
* ``/download_media?path=`` 实测返回 200 + S3 错误 XML（路径口径不对）→ 不用它；
  ``/sentences?ids=`` 500；``/download_sentence`` 只出 apkg，都不走。
* 同一搜索在不同时刻条数会变（后端索引在动）→ 一律落磁盘缓存，重跑零请求。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import paths as WSP
import textio

BASE = 'https://apiv2.immersionkit.com'
#: 浏览器 UA 是必须的：默认 ``Python-urllib/3.x`` 会被挡成 403（实测）
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
REFERER = 'https://www.immersionkit.com/'
TIMEOUT = 60
RETRIES = 3
SORT_DEFAULT = 'sentence_length:asc'
CATEGORIES = ('anime', 'drama', 'games', 'literature', 'news')

CACHE_DIR = os.path.join(WSP.DATA_IMMERSION, 'cache')
MEDIA_DIR = os.path.join(WSP.DATA_IMMERSION, 'media')


class ImmersionAPIError(RuntimeError):
    """网络/协议层出错（重试用尽、非 200、JSON 坏）。"""


# ============================================================================
# 网络
# ============================================================================
def _clean_params(params):
    return {k: v for k, v in (params or {}).items() if v not in (None, '')}


def cache_file(path, params=None):
    key = hashlib.sha1(
        (path + '?' + urllib.parse.urlencode(sorted(_clean_params(params).items())))
        .encode('utf-8')).hexdigest()[:20]
    return os.path.join(CACHE_DIR, '%s.json' % key)


# 全局限速：并发 fetch 时**请求起点**至少隔这么久（秒）。
# 2026-10-23 实测：4 线程无间隔地打 /search 会被服务端 429；拉大间隔后稳定。
# 缓存命中的请求不占这个间隔（见 get_json 的顺序：先查缓存，再排队）。
# 可用环境变量 DSH_IK_MIN_GAP 覆盖（调快/调慢都不用改代码）。
_MIN_GAP = float(os.environ.get('DSH_IK_MIN_GAP') or 1.0)
_pace_lock = threading.Lock()
_pace_next = [0.0]
_pace_penalty_until = [0.0]


def _reserve_slot(delay=0.0):
    """在全局队列里占一个发送时刻并睡到那一刻（多线程共用一个节奏）。"""
    with _pace_lock:
        gap = max(float(delay or 0.0), _MIN_GAP)
        if time.monotonic() < _pace_penalty_until[0]:
            gap = max(gap, 2.5)                 # 刚被 429 过：再慢一阵
        now = time.monotonic()
        slot = max(now, _pace_next[0])
        _pace_next[0] = slot + gap
    wait = slot - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def get_json(path, params=None, refresh=False, timeout=TIMEOUT, retries=RETRIES,
             delay=0.0, use_cache=True):
    """GET 一个 JSON 端点：磁盘缓存优先 + 全局限速 + 退避重试。

    ``delay`` 只对**真上网**的那次生效（命中缓存不睡），这样重跑才够快。
    多线程调用时，真正上网的请求按模块级队列排开（``_reserve_slot``），
    避免并发把服务端打出 429；429 按 ``Retry-After`` 退避，并临时把节奏放慢。
    400/401/403/404 视为参数或权限问题，不重试（重试只会把同一个错刷三遍）。
    """
    params = _clean_params(params)
    cached = cache_file(path, params)
    if use_cache and not refresh and os.path.exists(cached):
        got = textio.load_json(cached, default=None)
        if got is not None:
            return got
    url = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Accept': 'application/json', 'Referer': REFERER})
    last = '未知错误'
    for attempt in range(max(1, int(retries))):
        _reserve_slot(delay)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            textio.dump_json(data, cached)
            return data
        except urllib.error.HTTPError as exc:
            last = 'HTTP %d %s' % (exc.code, exc.reason)
            if exc.code in (400, 401, 403, 404):
                break
            if exc.code == 429:
                wait = exc.headers.get('Retry-After') if exc.headers else None
                try:
                    wait = float(wait)
                except (TypeError, ValueError):
                    wait = 0.0
                _pace_penalty_until[0] = time.monotonic() + 90
                time.sleep(max(wait, 8.0 * (attempt + 1)))
                continue
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last = '%s: %s' % (type(exc).__name__, exc)
        time.sleep(1.5 * (attempt + 1))
    raise ImmersionAPIError('GET %s 失败（%s）' % (url, last))


def download(url, dest, timeout=TIMEOUT):
    """按浏览器 UA 下载二进制（剧照/原声）到 dest，返回字节数。"""
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': REFERER})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        raise ImmersionAPIError('下载到 0 字节：%s' % url)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with open(dest, 'wb') as fh:          # 二进制：textio 审计豁免
        fh.write(data)
    return len(data)


# ============================================================================
# 端点
# ============================================================================
def search(word, category='', sort=SORT_DEFAULT, exact_match=True,
           show_url_in_media=True, jlpt=0, wk=0, offset=0, locale='detect',
           delay=0.5, refresh=False):
    """``/search`` —— 一个词的例句全集（条数由服务端定，别指望 limit）。"""
    params = {'q': word, 'sort': sort or SORT_DEFAULT, 'locale': locale,
              'exactMatch': 'true' if exact_match else 'false',
              'showUrlInMedia': 'true' if show_url_in_media else 'false'}
    if category:
        params['category'] = (category if isinstance(category, str)
                              else ','.join(category))
    if jlpt:
        params['jlpt'] = int(jlpt)
    if wk:
        params['wk'] = int(wk)
    if offset:
        params['offset'] = int(offset)
    return get_json('/search', params, refresh=refresh, delay=delay) or {}


def examples(word, **kw):
    return list(search(word, **kw).get('examples') or [])


def word_entry(word, **kw):
    """JMdict 词条（headword/reading/tags/glossary_list/sound）；没有就 None。"""
    entries = search(word, **kw).get('dictionary_entries') or []
    return entries[0] if entries else None


def category_of(example):
    """anime / drama / games —— 从 id 前缀取（``{category}_{deck}_{9位}``）。"""
    return str((example or {}).get('id', '')).split('_', 1)[0]


def media_url(example, kind='image'):
    """CDN 全 URL（要求查询时 ``showUrlInMedia=true``）。"""
    return str((example or {}).get(kind) or '')


# ============================================================================
# 文本清洗
# ============================================================================
#: bidi 控制符：drama 例句成对出现（``‪…‬``），会把句子切成看不出的一坨
BIDI_RE = re.compile('[\u202a-\u202e\u200e\u200f\u2066-\u2069\ufeff\u200b]')
BR_RE = re.compile(r'<\s*br\s*/?\s*>', re.I)
TAG_RE = re.compile(r'<[^>]+>')
WS_RE = re.compile(r'\s+')
HAN_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
KANA_RE = re.compile(r'[\u3041-\u309f\u30a0-\u30ff]')
PAREN_RE = re.compile(r'[（(][^）)]*[）)]')


def clean_text(s):
    """去不可见控制符、NBSP→空格、折叠连续空格、去首尾。

    **全角空格（U+3000）保留**：它是 ImmersionKit 的词分隔符，
    现有例句卡（如 ``(ｷﾝｸﾞ) かつて 人間の王国は``）也一直保留。
    """
    s = BIDI_RE.sub('', str(s or ''))
    s = s.replace('\u00a0', ' ').replace('\u3000\u3000', '\u3000')
    s = re.sub(r'[ \t]{2,}', ' ', s)
    return s.strip()


def has_br(s):
    return bool(BR_RE.search(str(s or '')))


def strip_tags(s):
    return TAG_RE.sub('', str(s or ''))


def plain(s):
    """去标签 + 去所有空白 —— 只给「逐字对齐」用。"""
    return WS_RE.sub('', strip_tags(str(s or '')))


def text_len(s):
    return len(strip_tags(str(s or '')).strip())


def escape_html(s):
    """只转义 ``<``/``>``，**不碰 ``&``**。

    为什么：``check_cards.py`` 用 ``text_of()``（删 ``<rt>…</rt>`` 再剥标签）与
    ``Sentence`` 字段**逐字**比对，把 ``&`` 写成 ``&amp;`` 就不一致了；
    而裸 ``&`` 在 Anki 里照常渲染。
    """
    return str(s or '').replace('<', '&lt;').replace('>', '&gt;')


def paren_ratio(s):
    """括号内内容占比 —— ``(メリル)`` 这类说话人标记的噪声比例。"""
    body = strip_tags(str(s or ''))
    inside = sum(len(m) for m in PAREN_RE.findall(body))
    return (inside / len(body)) if body else 0.0


# ============================================================================
# 振假名 → Sentence HTML
# ============================================================================
def _runs(text):
    """切成 ``[(是假名, 文本)]`` 的连续段。"""
    out = []
    for ch in text:
        kana = bool(KANA_RE.match(ch))
        if out and out[-1][0] == kana:
            out[-1][1] += ch
        else:
            out.append([kana, ch])
    return [(k, t) for k, t in out]


def align_span(span, reading):
    """``span``（汉字+假名）与 ``reading`` 对齐 → ``[(基, 读音|'')]``；失败 → None。

    整条链最容易错的就是这里，规则写死在这一个函数里（有单测）：
    * 汉字段吞读音 —— 吃到「下一个必须在读音里出现的假名段」之前（至少 1 个字符）；
    * **中间**的假名段必须与读音逐字相同，否则这个 span 作废；
    * **开头**的假名段只有读音真以它开头才算进基（``お金[おかね]`` 是，
      ``この町[まち]`` 不是 —— 后者 ``この`` 保持纯文本）。
    """
    runs = _runs(span)
    if not runs or not reading:
        return None
    tokens, pos = [], 0
    for i, (is_kana, text) in enumerate(runs):
        if is_kana:
            if reading.startswith(text, pos):
                tokens.append([text, text])       # 与紧邻汉字合并成基
                pos += len(text)
            elif i == 0:
                tokens.append([text, ''])         # 前导假名不属于读音 → 纯文本
            else:
                return None
            continue
        nxt = runs[i + 1] if i + 1 < len(runs) and runs[i + 1][0] else None
        if nxt is None:
            take = reading[pos:]
            if not take:
                return None
            tokens.append([text, take])
            pos = len(reading)
        else:
            found = reading.find(nxt[1], pos + 1)     # pos+1：汉字至少吞 1 个读音字符
            if found < 0:
                return None
            tokens.append([text, reading[pos:found]])
            pos = found
    if pos != len(reading):
        return None
    # 开头的「匹配上的假名」：后面还有真 ruby 就并进那个基（``お金[おかね]``），
    # 否则退回纯文本（不给纯假名加 ruby —— check_cards 的软错）
    if tokens and tokens[0][1] and not HAN_RE.search(tokens[0][0]):
        if len(tokens) > 1 and tokens[1][1]:
            tokens[1][0] = tokens[0][0] + tokens[1][0]
            tokens[1][1] = tokens[0][1] + tokens[1][1]
            tokens.pop(0)
        else:
            tokens[0][1] = ''
    return [(t, r) for t, r in tokens]


def tokenize_furigana(furigana):
    """``…私[わたし]　嫌[きら]いよ`` → ``[('…',''), ('私','わたし'), ('　嫌','きら'), ('いよ','')]``

    ``[读音]`` 作用于它**紧前面那段连续的汉字/假名**（空白、标点、括号都不进基）。
    长基优先：整段对不上就从下一个汉字重新起基（``私は学生[がくせい]`` →
    ``私は`` 纯文本 + ``学生[がくせい]``）。
    格式坏掉或某个读音彻底对不上 → 返回 None（调用方整句放弃，**不猜**）。
    空读音（实测 ``痛[]い``）与符号基（``～[から]`` / ``《[きごう]``）不注音、
    括号内容丢掉（句子里的 ``～`` 本来就不带这个音）。
    """
    out, buf, i = [], '', 0
    while i < len(furigana):
        ch = furigana[i]
        if ch != '[':
            buf += ch
            i += 1
            continue
        close = furigana.find(']', i)
        if close < 0:
            return None
        reading = furigana[i + 1:close].strip()
        k = len(buf)
        while k > 0 and (HAN_RE.match(buf[k - 1]) or KANA_RE.match(buf[k - 1])):
            k -= 1
        span = buf[k:]
        if not span or not reading:
            out.append((buf, ''))
            buf = ''
            i = close + 1
            continue
        aligned, prefix = None, span
        # 候选起点：整段（含前导假名，``お金[おかね]`` 走这条）→ 再逐个从汉字起
        # （``私は学生[がくせい]`` 整段对不上 → 缩到 ``学生``）。长的优先，第一个成功即用。
        starts = sorted({0} | {n for n, c in enumerate(span) if HAN_RE.match(c)})
        for j in starts:
            aligned = align_span(span[j:], reading)
            if aligned:
                prefix = span[:j]
                break
        if not aligned:
            return None
        out.append((buf[:k] + prefix, ''))
        out.extend(aligned)
        buf = ''
        i = close + 1
    out.append((buf, ''))
    merged = []
    for text, reading in out:
        if merged and not reading and not merged[-1][1]:
            merged[-1] = (merged[-1][0] + text, '')
        else:
            merged.append((text, reading))
    return [t for t in merged if t[0]]


def furigana_to_html(sentence, furigana):
    """``漢字[よみ]`` → 带 ruby 的 HTML，**原文以 ``sentence`` 为准**。

    两件事分开：**读音**来自 ``furigana``，**字符与空白**一律取自 ``sentence``
    （注音串自己会插空格，实测 ``大っ嫌いです`` 的注音是
    ``大[だい]っ 嫌[きら]いです``）。所以最后 ``text_of(html)`` 与 ``sentence``
    **逐字相同** —— 这正是 check_cards.py 的硬判据。

    返回 ``(html, ok)``。ok=False 表示对不上（字符差异、格式坏）——
    调用方应当**留空而不是猜**（有汉字没 ruby 是硬错、给纯假名加 ruby 是软错）。
    """
    tokens = tokenize_furigana(clean_text(furigana))
    if not tokens:
        return '', False
    raw = str(sentence or '')
    flat, posmap = '', []
    for i, ch in enumerate(raw):
        if ch.isspace():
            continue
        flat += ch
        posmap.append(i)
    if not flat:
        return '', False
    out, cursor, upto = [], 0, 0
    for text, reading in tokens:
        piece = WS_RE.sub('', text)
        if not piece:
            continue
        if not flat.startswith(piece, cursor):
            return '', False
        start, end = cursor, cursor + len(piece)
        cursor = end
        raw_a, raw_b = posmap[start], posmap[end - 1]
        out.append(raw[upto:raw_a])                # 两个 token 之间的原文（空白等）照抄
        seg = raw[raw_a:raw_b + 1]
        if reading and HAN_RE.search(seg):
            out.append('<ruby>%s<rt>%s</rt></ruby>'
                       % (escape_html(seg), escape_html(reading)))
        else:
            out.append(escape_html(seg))
        upto = raw_b + 1
    if cursor != len(flat):
        return '', False
    out.append(raw[upto:])                         # 尾随原文
    return ''.join(out), True


def readings_in(furigana):
    """``{基: 读音}`` —— 给目标词找读音用。"""
    out = {}
    for base, reading in (tokenize_furigana(clean_text(furigana)) or []):
        if reading and HAN_RE.search(base):
            out.setdefault(base, reading)
    return out


def word_reading(example, word):
    """目标词在这句里的读音：取最长的、被 word 包含的基；没有就 ''。"""
    best = (0, '')
    for base, reading in readings_in(
            (example or {}).get('sentence_with_furigana', '')).items():
        if base == word:
            return reading
        if base in word and len(base) > best[0]:
            best = (len(base), reading)
    return best[1]


# ============================================================================
# 命中判定与筛选
# ============================================================================
def is_token_hit(example, word):
    """目标词是否**作为独立词元**出现（matched_indexes 精确切片，或 word_list 整词）。

    单假名词（え/め/ん/や…）靠 ``hits_word`` 的**子串兜底**几乎句句都「命中」——
    实测「め」会命中「ごめんください」，「え」会命中「よく冷えてるよ」。
    所以选句时先用这个更严的判据排序，只有一条独立命中都没有时才退回子串命中。
    """
    wl = list((example or {}).get('word_list') or [])
    for m in (example or {}).get('matched_indexes') or []:
        try:
            i, n = int(m.get('index')), int(m.get('length'))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= i < len(wl) and n > 0 and ''.join(wl[i:i + n]) == word:
            return True
    return word in wl


def hits_word(example, word):
    """这句真的含目标词吗？

    drama 的 ``matched_indexes`` **常常是空的**（实测），所以不能只信它：
    先按 matched_indexes 精确切片，再按 word_list 整词，最后才退回原句子串。
    """
    if is_token_hit(example, word):
        return True
    wl = list((example or {}).get('word_list') or [])
    # 词被拆成多个 token（``['嫌','い','だ']``）时要能拼回来
    if word in ''.join(t for t in wl if t and t.strip()):
        return True
    return word in strip_tags(str((example or {}).get('sentence') or ''))


def select_sentences(examples, word, n=1, categories=(), decks=(),
                     min_len=3, max_len=40, used_ids=None, speaker_max=0.6):
    """挑 n 条可用例句（**否决式**过滤，服务端已按句长升序给序 = 短句优先）。

    ``used_ids`` 跨词共享，保证同一句不会被两个词各写一张卡。
    返回 example 的浅拷贝，附 ``_category`` / ``_reading`` 两个下划线字段。
    """
    used = used_ids if used_ids is not None else set()
    cats = {str(c).strip() for c in (categories or ()) if str(c).strip()}
    decks = {str(d).strip() for d in (decks or ()) if str(d).strip()}
    out = []
    for ex in examples or []:
        s = clean_text((ex or {}).get('sentence'))
        t = clean_text((ex or {}).get('translation'))
        if not s or not t:
            continue
        if has_br(s) or has_br(t):        # 多说话人拼接 / 译文串了别的字幕
            continue
        if ex.get('id') in used:
            continue
        cat = category_of(ex)
        if cats and cat not in cats:
            continue
        if decks and ex.get('title') not in decks:
            continue
        if not hits_word(ex, word):
            continue
        if not (min_len <= text_len(s) <= max_len):
            continue
        if paren_ratio(s) > speaker_max:
            continue
        pick = dict(ex)
        pick['sentence'] = s
        pick['translation'] = t
        pick['_category'] = cat
        pick['_reading'] = word_reading(ex, word)
        out.append(pick)
        used.add(ex.get('id'))
        if len(out) >= max(1, int(n)):
            break
    return out


# ============================================================================
# 词表 / 已知词过滤（纯函数，单测直接调）
# ============================================================================
def read_words_file(path):
    """读词表：一行一个词；``#`` 注释；``词<TAB>条数`` 可覆盖 ``--n``。

    返回 ``[(词, 条数|None)]``，保序去重。
    """
    out, seen = [], set()
    for raw in textio.read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = re.split(r'[\t,;]', line)
        word = parts[0].strip()
        if not word or word in seen:
            continue
        cnt = None
        for p in parts[1:]:
            p = p.strip()
            if p.isdigit():
                cnt = int(p)
                break
        seen.add(word)
        out.append((word, cnt))
    return out


def _lookup_key(word, norm=None):
    return norm(word) if norm else word


def filter_words(words, canonical=None, variants=None, have=None,
                 rank_of=None, norm=None, keep_known=False):
    """剔掉「已在 core6000/考级」和「目标牌组已有」，其余按 Jiten 排名升序。

    ``words`` = 词序列或 ``[(词, 条数)]``；``canonical``/``variants`` 来自
    ``pipeline.rebuild_known_index()``；``have`` 是目标牌组已有的**归一化**词集合。
    ``keep_known=True`` 时**反过来**：只留 core6000/考级里已有的词（给例句牌组
    补对白例句用；目标牌组已有的仍然剔）。返回 ``(todo, skipped)``：
    todo 每项 ``{'word','n','rank'}``，skipped 每项 ``(词, 原因)``。
    """
    canonical = canonical or {}
    variants = variants or {}
    have = have or set()
    todo, skipped = [], []
    for item in words or []:
        word, cnt = item if isinstance(item, (tuple, list)) else (item, None)
        word = str(word).strip()
        if not word:
            continue
        key = _lookup_key(word, norm)
        if key in canonical or key in variants:
            if not keep_known:
                if key in canonical:
                    skipped.append((word, '已在 %s' % (canonical[key] or 'core6000/考级')))
                else:
                    skipped.append((word, '已在 %s（归一为 %s）'
                                    % (canonical.get(variants[key], 'core6000/考级'),
                                       variants[key])))
                continue
        elif keep_known:
            skipped.append((word, '不在 core6000/考级'))
            continue
        if key in have:
            skipped.append((word, '目标牌组已有'))
            continue
        todo.append({'word': word, 'n': cnt,
                     'rank': (rank_of(word) if rank_of else None)})
    todo.sort(key=lambda r: (r['rank'] if isinstance(r.get('rank'), int) else 10 ** 9))
    return todo, skipped


# ============================================================================
# 手工探针（只读）
# ============================================================================
def _probe(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog='immersion_api.py',
                                 description='ImmersionKit 只读探针（选句预览，不写库）')
    ap.add_argument('word')
    ap.add_argument('--n', type=int, default=3)
    ap.add_argument('--category', default='anime,drama')
    ap.add_argument('--max-len', type=int, default=40)
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args(argv)
    data = search(a.word, category=a.category, refresh=a.refresh)
    ex = data.get('examples') or []
    entry = (data.get('dictionary_entries') or [None])[0]
    print('例句 %d 条 ｜ 计数 %s'
          % (len(ex), json.dumps(data.get('category_count'), ensure_ascii=False)))
    print('词条 %s' % json.dumps(entry, ensure_ascii=False))
    picks = select_sentences(ex, a.word, n=a.n,
                             categories=a.category.split(','), max_len=a.max_len)
    for p in picks:
        html, ok = furigana_to_html(p['sentence'], p.get('sentence_with_furigana'))
        print('-' * 70)
        print('  id      %s  [%s] %s' % (p['id'], p['_category'], p['title']))
        print('  句      %s' % p['sentence'])
        print('  译      %s' % p['translation'])
        print('  读音    %s' % (p['_reading'] or '—'))
        print('  ruby    ok=%s %s' % (ok, html[:90]))
        print('  媒体    %s' % media_url(p, 'sound'))
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(_probe())
