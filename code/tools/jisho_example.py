# -*- coding: utf-8 -*-
"""jisho.org 例句检索 —— **只取真实句子，不造句子**。

为什么有这个脚本
----------------
给日语词找例句时，让模型「现场编一句」看起来最省事，但句子是否自然、是否真的
用了目标词、读音对不对，全靠运气。Jisho 的 Sentence 搜索页背后是 Tatoeba 与
Jreibun 两个人工语料库，句子、英文翻译、出处链接、部分振假名都是现成的。
本脚本把这些句子**原样取回来**，机械地过滤、排序，并（可选）用
``code/common/ruby_engine.py`` 把振假名补全。

它**不写 Anki**、不调用模型、不改写任何句子。选句是人的判断；脚本只负责把
候选摆出来。

用法
----
::

    # 看 8 条候选（带振假名与出处）
    & $PY code\\tools\\jisho_example.py --word "徹夜" --reading "てつや"

    # 机器可读
    & $PY code\\tools\\jisho_example.py --word "猫" --json --out temp\\jisho_neko.json

    # 只要第 3 条（卡面字段）
    & $PY code\\tools\\jisho_example.py --word "猫" --pick 3

退出码
------
* ``0``：至少有一条候选；
* ``2``：Jisho 有响应，但过滤后没有可用候选（**不要退回模型造句**）；
* ``1``：网络/解析/依赖错误。

依赖：``data/pylibs`` 里的 requests、lxml；``data/pylibs`` 里的 SudachiPy 用于
分词匹配与振假名兜底；``data/dict/jmdictpy/jmdict.db`` 用于否决被 Jisho 截断的
读音（``私達 → わたし``），词典不可用时自动降级。Jisho 的 robots.txt 要求
Crawl-delay: 40，本脚本**一次调用只抓一页**（最多 20 条），不要拿它循环刷词。
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as html_mod
import io
import json
import os
import re
import sys
from collections import Counter
from contextlib import redirect_stdout
from urllib.parse import quote

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))
sys.path.insert(0, os.path.join(_WS, 'data', 'pylibs'))

import paths as WSP          # noqa: E402  工作区路径唯一来源
import textio                # noqa: E402  UTF-8 stdio 唯一入口
import jmdict_check as JC    # noqa: E402  JMdict 读音核验（只读本地词典）
import ruby_engine as RE     # noqa: E402  振假名渲染/校验的唯一实现

try:
    import requests
    from lxml import html as LH
except ImportError as _exc:  # pragma: no cover - 环境缺库时给出可操作提示
    print('❌ 缺少依赖（%s）。请确认 data/pylibs 里有 requests 与 lxml。' % _exc)
    raise SystemExit(1)

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
BASE = 'https://jisho.org'
KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
KANA = re.compile(r'[\u3041-\u3096\u30a0-\u30ff\u30fc]')
BRACKETS = {'(': ')', '（': '）', '[': ']', '［': '］', '{': '}', '｛': '｝',
            '「': '」', '『': '』', '【': '】', '〈': '〉', '《': '》'}
END_PUNCT = re.compile(r'[。．！？!?…][」』”"）\]】]*$')
SOURCE_SCORE = {'Tatoeba': 2, 'Jreibun': 1}
MATCH_SCORE = {'exact': 30, 'compound': 18, 'phrase': 12, 'none': 0}


# ============================================================================
# 解析 Jisho 页面
# ============================================================================
def search_url(word):
    """Jisho 的 Sentence 搜索地址（``#sentences`` 必须编码进路径）。"""
    return '%s/search/%s%%20%%23sentences' % (BASE, quote(word, safe=''))


def _ja_text(ul):
    """``ul.japanese_sentence`` → 纯日文句子（丢掉 furigana、保留标点）。"""
    chunks = []
    if ul.text:
        chunks.append(ul.text)
    for child in ul.iterchildren():
        if child.tag == 'li':
            bases = child.xpath(
                './/span[contains(@class,"unlinked") or contains(@class,"linked")]')
            if bases:
                chunks.append(''.join(b.text_content() for b in bases))
            else:
                clone = LH.fromstring(LH.tostring(child, encoding='unicode'))
                for f in clone.xpath('.//span[contains(@class,"furigana")]'):
                    f.getparent().remove(f)
                chunks.append(clone.text_content())
        elif child.tag == 'br':
            chunks.append(' ')
        if child.tail:
            chunks.append(child.tail)
    text = html_mod.unescape(''.join(chunks))
    text = re.sub(r'[ \t\r\n]+', ' ', text).strip()
    # Jisho 的源码里常有换行/缩进（浏览器会渲染成空格）；日文词之间不留这种
    # 排版空格，但保留拉丁词两侧的空格（「これは pen です」）。
    jp = r'\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f'
    return re.sub(r'(?<=[%s])\s+(?=[%s])' % (jp, jp), '', text)


def _annotations(li):
    """Jisho 的 ``furigana + unlinked`` 对，按 DOM 顺序保留。

    Jisho 有时会把送假名放进 base（``舐めて`` 的读音只给 ``な``），渲染时会
    检测这种对不齐的情况并交给 Sudachi 兜底，见 :func:`_annotation_ruby`。
    """
    out = []
    for tok in li.xpath('.//li[contains(@class,"clearfix")]'):
        fur = tok.xpath('.//span[contains(@class,"furigana")]')
        bases = tok.xpath(
            './/span[contains(@class,"unlinked") or contains(@class,"linked")]')
        if not fur or not bases:
            continue
        base = ''.join(b.text_content() for b in bases).strip()
        reading = ''.join(f.text_content() for f in fur).strip()
        if base and reading:
            out.append({'base': base, 'reading': reading})
    return out


def _source(li):
    spans = li.xpath('.//span[contains(@class,"inline_copyright")]')
    if not spans:
        return 'Jisho'
    txt = re.sub(r'\s+', ' ', spans[0].text_content()).strip()
    txt = txt.replace('—', '').replace('–', '').strip()
    return txt or 'Jisho'


def _detail_url(li):
    hrefs = li.xpath('.//a[contains(@class,"light-details_link")]/@href')
    if not hrefs:
        return ''
    href = hrefs[0]
    if href.startswith('//'):
        return 'https:' + href
    if href.startswith('/'):
        return BASE + href
    return href


def parse_page(content):
    """Jisho 例句页 HTML → ``{total, entries}``（不联网，便于离线测试）。"""
    if isinstance(content, (bytes, bytearray)):
        content = bytes(content).decode('utf-8', 'replace')
    doc = LH.fromstring(content)
    total = None
    h4 = doc.xpath('//div[contains(@class,"sentences_block")]//h4')
    if h4:
        m = re.search(r'(\d+)\s+found', h4[0].text_content())
        if m:
            total = int(m.group(1))
    entries = []
    for li in doc.xpath('//li[contains(@class,"entry") and contains(@class,"sentence")]'):
        uls = li.xpath('.//ul[contains(@class,"japanese_sentence")]')
        if not uls:
            continue
        ja = _ja_text(uls[0])
        if not ja:
            continue
        en = li.xpath('.//span[contains(@class,"english")]')
        debug = li.xpath('.//div[contains(@class,"debug")]')
        entries.append({
            'ja': ja,
            'en': re.sub(r'\s+', ' ', en[0].text_content()).strip() if en else '',
            'source': _source(li),
            'sentence_id': debug[0].text_content().strip() if debug else '',
            'url': _detail_url(li),
            'annotations': _annotations(li),
        })
    if total is None:
        total = len(entries)
    return {'total': total, 'entries': entries}


def fetch_page(url, timeout=30):
    r = requests.get(url, headers={
        'User-Agent': UA,
        'Accept-Language': 'ja,en;q=0.8',
    }, timeout=timeout)
    r.raise_for_status()
    return r.content


# ============================================================================
# 匹配 / 过滤 / 排序
# ============================================================================
def _token_forms(tok):
    forms = set()
    for name in ('surface', 'dictionary_form', 'normalized_form'):
        try:
            value = getattr(tok, name)()
        except Exception:
            value = ''
        if value:
            forms.add(value)
            forms.add(RE.hira(value))
    try:
        reading = tok.reading_form()
    except Exception:
        reading = ''
    if reading:
        forms.add(reading)
        forms.add(RE.hira(reading))
    return forms


def _target_forms(word, reading=''):
    forms = {word}
    if reading:
        forms.add(reading)
    forms |= {RE.hira(x) for x in list(forms)}
    return {x for x in forms if x}


def _sequence_forms(tokens, attr):
    out = []
    for tok in tokens:
        try:
            value = getattr(tok, attr)()
        except Exception:
            value = ''
        out.append(value or tok.surface())
    return out


def classify_match(sentence, word, reading, tokens):
    """``exact``（整词/词典形/读音命中）/ ``compound``（在含汉字的复合词里）/
    ``phrase``（多词短语）/ ``none``。

    用 Sudachi 的 token 边界挡住 Jisho 的模糊命中：搜 ``ヤニ`` 会命中
    ``ニヤニヤ``，字面看包含「ヤニ」，但那是跨词边界的假阳性——纯假名 token
    内部的子串一律不算。

    ``体中`` 这类词 Sudachi 会切成 ``体`` + ``中``，所以除了单 token 比对，
    还要按顺序拼连续 token（surface / dictionary_form / normalized_form /
    reading_form）再比一次。
    """
    targets = _target_forms(word, reading)
    for tok in tokens:
        if targets & _token_forms(tok):
            return 'exact'
    for attr in ('surface', 'dictionary_form', 'normalized_form', 'reading_form'):
        seq = _sequence_forms(tokens, attr)
        for i in range(len(seq)):
            joined = ''
            for piece in seq[i:]:
                joined += piece or ''
                if joined in targets or RE.hira(joined) in targets:
                    return 'exact'
                if len(joined) > max(len(word), len(reading or '')) + 8:
                    break
    for tok in tokens:
        surface = tok.surface()
        if not KANJI.search(surface):
            continue
        surface_h = RE.hira(surface)
        if word in surface or (reading and RE.hira(reading) in surface_h):
            return 'compound'
        if RE.hira(word) in surface_h:
            return 'compound'
    if len(word) >= 4 and (word in sentence or (reading and reading in sentence)):
        return 'phrase'
    return 'none'


def _balanced(text):
    stack = []
    for ch in text:
        if ch in BRACKETS:
            stack.append(BRACKETS[ch])
        elif ch in BRACKETS.values():
            if not stack or stack.pop() != ch:
                return False
    return not stack


def _dedupe_key(text):
    return re.sub(r'[\s。、，．.!?！？「」『』（）()\[\]【】]', '', text)


def _score(match, source, chars):
    return (MATCH_SCORE[match] + SOURCE_SCORE.get(source, 0)
            + max(0, 25 - abs(chars - 22)))


def filter_entries(entries, word, reading, lex, args):
    """过滤 + 排序；返回 ``(kept, dropped_counts)``。"""
    dropped = Counter()
    seen = set()
    kept = []
    for entry in entries:
        ja = entry['ja']
        chars = len(ja)
        key = _dedupe_key(ja)
        if key in seen:
            dropped['duplicate'] += 1
            continue
        seen.add(key)
        if chars < args.min_chars or chars > args.max_chars:
            dropped['length'] += 1
            continue
        if not _balanced(ja):
            dropped['brackets'] += 1
            continue
        if not END_PUNCT.search(ja):
            dropped['no_end_punct'] += 1
            continue
        try:
            tokens = lex.tokenize(ja)
        except Exception:
            tokens = []
        match = classify_match(ja, word, reading, tokens)
        if match == 'none' or (args.exact and match != 'exact'):
            dropped['no_match'] += 1
            continue
        entry = dict(entry)
        entry['chars'] = chars
        entry['match'] = match
        entry['score'] = _score(match, entry['source'], chars)
        kept.append(entry)
    kept.sort(key=lambda e: (-e['score'], e['chars'], e['ja']))
    return kept, dropped


# ============================================================================
# 振假名：Jisho 注解优先，对不齐的 token 交给 ruby_engine 的 Sudachi 兜底
# ============================================================================
_DICT_CACHE = {}


def _dict_readings(lookup, base):
    """JMdict 里 ``base`` 的合法读音集合；查不到返回 ``None``（不据此否决）。"""
    if lookup is None or not getattr(lookup, 'available', False):
        return None
    key = (id(lookup), base)
    if key in _DICT_CACHE:
        return _DICT_CACHE[key]
    try:
        entries = JC.match_entries(lookup.lookup(base), base)
        readings = None
        if entries:
            readings = {JC.kana_key(x) for x in JC.candidate_readings(entries, limit=16)}
    except Exception:
        readings = None
    _DICT_CACHE[key] = readings
    return readings


def _render_gap(text, lex):
    if not text:
        return ''
    if not KANJI.search(text):
        return text
    try:
        return RE.render(text, lex)
    except Exception:
        return text


def _annotation_ruby(base, reading, lex, lookup=None):
    """返回 ruby HTML；返回 ``None`` 表示这条注解不可信，交给 Sudachi。"""
    if not KANJI.search(base):
        return base
    pinned = lex.pinned.get(base)
    reading = RE.hira((pinned or reading or '').strip())
    if not reading:
        return None
    # Jisho 的 furigana 偶尔会把复合词截断（私達 → わたし、長生き → ながい）。
    # 全汉字/含汉字的 base 先对 JMdict 的读音表；对不上就不信这条注解。
    # 人工例外表（pinned）优先，不受词典否决。
    if not pinned:
        candidates = _dict_readings(lookup, base)
        if candidates and JC.kana_key(reading) not in candidates:
            return None
    segs = RE.split_segments(base, reading)
    for surface, read in segs:
        if read and KANA.search(surface):
            return None
    if len(segs) == 1 and segs[0][0] == base and not all(KANJI.match(c) for c in base):
        return None
    return RE.pieces(base, reading, segs)


def render_ruby(sentence, annotations, lex, lookup=None):
    """用 Jisho 的逐词注音拼出 ``Sentence HTML``，再用 ``ruby_engine`` 校验。"""
    out, pos = [], 0
    for ann in annotations:
        base = ann.get('base') or ''
        if not base:
            continue
        idx = sentence.find(base, pos)
        if idx < 0:
            continue
        if idx > pos:
            out.append(_render_gap(sentence[pos:idx], lex))
        ruby = _annotation_ruby(base, ann.get('reading', ''), lex, lookup)
        out.append(ruby if ruby is not None else _render_gap(base, lex))
        pos = idx + len(base)
    if pos < len(sentence):
        out.append(_render_gap(sentence[pos:], lex))
    html = ''.join(out)
    hard, soft = RE.validate(sentence, html)
    return html, hard + soft


def build_lexicon():
    """离线读音词典（人工例外 + Sudachi），不连 Anki。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        return RE.Lexicon.build(use_deck=False)


def build_jmdict(enabled=True):
    """本地 JMdict（只读）；不可用/关闭时返回 ``None``。"""
    if not enabled:
        return None
    try:
        return JC.Lookup()
    except Exception:
        return None


# ============================================================================
# 输出
# ============================================================================
def _candidate(result, index):
    if not 1 <= index <= len(result['candidates']):
        raise IndexError('--pick 超出范围：1–%d' % len(result['candidates']))
    return result['candidates'][index - 1]


def print_table(result):
    word = result['word']
    reading = ('（%s）' % result['reading']) if result['reading'] else ''
    print('# %s%s — Jisho 例句' % (word, reading))
    print('查询：%s' % result['query_url'])
    print('共 %s 条，抓取 %d 条，匹配 %d 条，显示 %d 条' % (
        result['total_found'], result['fetched'], result['matched'],
        len(result['candidates'])))
    dropped = result['dropped']
    if dropped:
        print('过滤：' + ' / '.join('%s %d' % (k, v) for k, v in dropped.items()))
    for i, c in enumerate(result['candidates'], 1):
        print('\n%d. [%s ｜ %s ｜ %d 字] %s' % (
            i, c['match'], c['source'], c['chars'], c['ja']))
        if c.get('en'):
            print('   EN: %s' % c['en'])
        print('   %s' % c['url'])
        if c.get('ruby_html'):
            print('   ruby: %s' % c['ruby_html'])
        if c.get('ruby_ok') is False:
            print('   ⚠️ 振假名未通过结构校验：%s' % '；'.join(c['ruby_issues']))


def print_pick(c):
    print('Sentence: %s' % c['ja'])
    print('Sentence HTML: %s' % (c.get('ruby_html') or ''))
    print('Sentence Translation (EN): %s' % (c.get('en') or ''))
    print('Source: %s' % c['source'])
    print('URL: %s' % c['url'])
    if c.get('ruby_ok') is False:
        print('⚠️ 振假名未通过结构校验：%s' % '；'.join(c['ruby_issues']))


# ============================================================================
# 主流程
# ============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='jisho_example.py',
        description='去 jisho.org 找真实例句（只取不造；不写 Anki）。')
    ap.add_argument('--word', required=True, help='目标日语词（词形或假名）')
    ap.add_argument('--reading', default='', help='可选读音（假名）；用于匹配与注释')
    ap.add_argument('--limit', type=int, default=8, help='最多输出几条（默认 8）')
    ap.add_argument('--min-chars', type=int, default=5, help='句子最短字数（默认 5）')
    ap.add_argument('--max-chars', type=int, default=60, help='句子最长字数（默认 60）')
    ap.add_argument('--exact', action='store_true',
                    help='只保留整词命中（去掉复合词/短语）')
    ap.add_argument('--no-ruby', action='store_true', help='跳过振假名渲染')
    ap.add_argument('--no-dict', action='store_true',
                    help='跳过 JMdict 读音核验（只影响注解可信度，不联网）')
    ap.add_argument('--json', action='store_true', help='输出 JSON（stdout 只有 JSON）')
    ap.add_argument('--pick', type=int, default=0, metavar='N',
                    help='只输出第 N 条候选（1 起）')
    ap.add_argument('--out', default='', help='把完整 JSON 另存到这个路径')
    ap.add_argument('--timeout', type=float, default=30.0, help='HTTP 超时秒数')
    args = ap.parse_args(argv)

    word = args.word.strip()
    if not word:
        ap.error('--word 不能为空')
    if args.limit < 1:
        ap.error('--limit 必须 >= 1')
    if args.min_chars < 0 or args.max_chars < args.min_chars:
        ap.error('--min-chars/--max-chars 不合法')
    reading = args.reading.strip()
    query = search_url(word)

    try:
        content = fetch_page(query, args.timeout)
    except Exception as exc:
        print('❌ 请求 Jisho 失败：%s' % exc, file=sys.stderr)
        print('   查询地址：%s' % query, file=sys.stderr)
        return 1
    try:
        page = parse_page(content)
    except Exception as exc:
        print('❌ 解析 Jisho 页面失败：%s' % exc, file=sys.stderr)
        return 1
    if not page['entries']:
        print('❌ Jisho 没有返回例句（可能 0 条，或页面结构变了）。', file=sys.stderr)
        print('   查询地址：%s' % query, file=sys.stderr)
        return 2

    try:
        lex = build_lexicon()
    except Exception as exc:
        print('❌ 初始化 Sudachi/ruby_engine 失败：%s' % exc, file=sys.stderr)
        print('   请确认 data/pylibs 里有 SudachiPy 与词典。', file=sys.stderr)
        return 1
    lookup = build_jmdict(not args.no_dict)

    matched, dropped = filter_entries(page['entries'], word, reading, lex, args)
    if not matched:
        print('❌ 没有可用候选（抓取 %d 条，全部被过滤）。' % len(page['entries']),
              file=sys.stderr)
        if dropped:
            print('   过滤：' + ' / '.join('%s %d' % (k, v) for k, v in dropped.items()),
                  file=sys.stderr)
        print('   查询地址：%s' % query, file=sys.stderr)
        print('   不要退回模型造句；可换词形/读音，或放宽 --min-chars/--max-chars 再试。',
              file=sys.stderr)
        return 2

    kept = matched[:args.limit]
    for c in kept:
        if args.no_ruby:
            c['ruby_html'] = None
            c['ruby_ok'] = None
            c['ruby_issues'] = []
        else:
            html, issues = render_ruby(c['ja'], c['annotations'], lex, lookup)
            c['ruby_html'] = html
            c['ruby_ok'] = not issues
            c['ruby_issues'] = issues

    result = {
        'word': word,
        'reading': reading,
        'query_url': query,
        'fetched_at': dt.datetime.now().isoformat(timespec='seconds'),
        'total_found': page['total'],
        'fetched': len(page['entries']),
        'matched': len(matched),
        'kept': len(kept),
        'filters': {
            'min_chars': args.min_chars,
            'max_chars': args.max_chars,
            'exact': bool(args.exact),
            'ruby': not args.no_ruby,
            'dict_check': bool(lookup and getattr(lookup, 'available', False)),
        },
        'dropped': dict(dropped),
        'candidates': kept,
    }

    if args.out:
        out_path = args.out if os.path.isabs(args.out) else os.path.join(WSP.ROOT, args.out)
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        textio.dump_json(result, out_path)
        print('已写入：%s' % out_path, file=sys.stderr)

    if args.pick:
        try:
            candidate = _candidate(result, args.pick)
        except IndexError as exc:
            print('❌ %s' % exc, file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(candidate, ensure_ascii=False, indent=2))
        else:
            print_pick(candidate)
        return 0

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_table(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
