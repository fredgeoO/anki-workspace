# -*- coding: utf-8 -*-
"""core6000 补例句②的例句源：Jisho 真实语料。**新句不是模型写的**。

从 ``execution/core6000_example.py`` 抽出（2026-11-02，Issue #4「按能力切分超大流程
文件」）。这块能单独调用、单独测（不连网时把 ``jisho_fetch`` 换成固定候选就行）：
抓一页 Jisho → 落缓存 → 四道闸门挑一条**真实**例句。契约文档：
docs/core6000-example-design.md §5–§6。

留在巨石里的是流程（scan / gen / tts / apply / revert）；机械闸门 1-5 判的是
**模型产出**，在 ``core6000_gates``。口径一字未改；``core6000_example`` 仍以同名
模块级别名导出这些函数（测试照旧用 ``CX.pick_jisho`` / ``CE.jisho_fetch``，探针脚本
sense_repair 也照旧）。

**调用约定**：这块内部的跨函数调用（``pick_jisho`` 调 ``jisho_fetch`` 等）一律走
``_CE()``——见下面。巨石里 ``from core6000_jisho import …`` 只是别名，补丁打在巨石上，
所以只有经它转发才和拆分前一模一样。
"""
import argparse
import datetime as dt
import difflib
import os
import re
import sys
import unicodedata

# 系列子目录（issue #12）：单独 import 时自己挂上 code/common 与本系列目录。
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(os.path.dirname(os.path.dirname(_HERE)), 'common'), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from htmltext import strip_tags                    # noqa: F401
from ruby_text import KANJI                        # noqa: F401
import core6000_text2                  # JISHO_DIR：巨石 import 后写回它那份（见 jisho_cache_path）
from core6000_text2 import (JISHO_MIN_SIMILARITY,  # noqa: F401  换皮句阈值，同一份
                            JISHO_SOURCE_FIELD,     # noqa: F401
                            RE_KANA_ONLY, RE_RT, RE_RUBY, RE_WS, clean_malformed_ruby,
                            flatten, one_line, plain, read_json, ruby_covers, write_json)

# 闸门 2 的新句长度区间（去空白）：随这块能力一起搬过来。
SENT_MIN, SENT_MAX = 6, 45


def _CE():
    """跨函数调用一律走这里：巨石 import 本模块后，这些名字的真身在它的全局表里，
    测试 ``CX.jisho_fetch = fake`` 才照样拦得住（拆分前它们本来就同一个命名空间）。

    单独 import 本模块（测试 / 探针）时巨石还没加载，就直接调本模块里的实现。
    """
    return sys.modules.get('core6000_example') or sys.modules[__name__]


# ============================================================================
# 目标词形态：只用来把纯假名动词展开成活用形，不做词性判断
# ============================================================================
# ============================================================================
# 机械闸门 1-5（gen 阶段：拿到模型产出就能判的）
# ============================================================================
# 五段动词的行（行 = 段）：只用来把纯假名动词展开成活用形，不做词性判断。
_GODAN_ROWS = {
    'う': 'わいうえお', 'く': 'かきくけこ', 'ぐ': 'がぎぐげご', 'す': 'さしすせそ',
    'つ': 'たちつてと', 'ぬ': 'なにぬねの', 'ぶ': 'ばびぶべぼ', 'む': 'まみむめも',
    'る': 'らりるれろ',
}

# て/た 的音便：しゃがむ → しゃがんだ / しゃがんで；かく → かいた / かいて …
_ONBIN_TA = {
    'む': ('んだ', 'んで'), 'ぶ': ('んだ', 'んで'), 'ぬ': ('んだ', 'んで'),
    'く': ('いた', 'いて'), 'ぐ': ('いだ', 'いで'),
    'う': ('った', 'って'), 'つ': ('った', 'って'), 'る': ('った', 'って'),
    'す': ('した', 'して'),
}


def kana_conjugations(word):
    """纯假名动词的常见活用形（`しゃがむ` → `しゃがんだ`/`しゃがんで`/`しゃがみます`…）。

    闸门 2（真含目标词）用。Jisho 的句子写的是活用形，而纯假名词没有
    「去掉词尾送假名」的汉字骨架可用（`しゃがむ` 拆不出 `しゃがんだ`），
    只拿词典形去比会把正确候选判成 no-target。词尾不在五段行里的
    假名词（`あまり`、`ところ`）不展开 —— 否则 `あまり` → `あま` 这类
    子串会把完全不相干的句子放进候选。
    """
    if len(word) < 2 or not RE_KANA_ONLY.match(word):
        return set()
    stem, last = word[:-1], word[-1]
    row = _GODAN_ROWS.get(last)
    if not row:
        return set()
    ta, te = _ONBIN_TA.get(last, ('た', 'て'))
    out = {stem + ta, stem + te}
    a, i, _, e, o = row
    out |= {stem + a + 'ない', stem + a + 'なかった', stem + a + 'ないで',
            stem + a + 'ず', stem + a + 'れる', stem + a + 'せる',
            stem + i + 'ます', stem + i + 'ました', stem + i + 'たい', stem + i + 'そう',
            stem + e + 'ば', stem + e + 'る', stem + o + 'う'}
    if last == 'る':                      # 一段（たべる）也走这条路：stem+た/て/ます
        out |= {stem + 'た', stem + 'て', stem + 'ます', stem + 'ない'}
    return out


def target_forms(card):
    """目标词的可接受写法：原词、读音、每个汉字串、去掉词尾的词干、活用形。"""
    forms = set()
    for raw in (card['word'], card['reading']):
        if not raw:
            continue
        forms.add(raw)
        core = re.sub(r'[（）()\[\]【】\s]', '', raw).strip('〜～~-—–・')
        if core:
            forms.add(core)
    word = card['word'] or ''
    for run in re.findall(r'[\u4e00-\u9fff\u3005\u3006\u30f6]+', word):
        forms.add(run)
    if word and not RE_KANA_ONLY.match(word):
        stem = re.sub(r'[するるうつくぶむぬぐずふ]$', '', word)
        if len(stem) >= 2:
            forms.add(stem)
    else:
        forms |= _CE().kana_conjugations(word)
    forms.discard('')
    return forms

# ============================================================================
# 例句源：Jisho（真实语料）。**新句不是模型写的**
# ============================================================================

# ============================================================================
# 例句源：Jisho（真实语料）。**新句不是模型写的**
# ============================================================================
def load_jisho():
    """惰性导入 code/tools/jisho_example.py；导入失败返回 (None, 原因)。"""
    try:
        import jisho_example as JX
        return JX, ''
    except Exception as exc:                       # 缺 requests / 语法变了 / 路径问题
        return None, '%s: %s' % (type(exc).__name__, exc)


def jisho_cache_path(note_id):
    # 每次调用时现读 JISHO_DIR，别在 import 时冻结成快照。拆分前它是巨石里的一个全局，
    # `CE.JISHO_DIR = tmp`（测试 / 探针）当场就改到缓存落点；拆开后真身仍应在**巨石那份**，
    # 所以经 `_CE()` 读——巨石在场就读它的全局（与拆分前逐字一致），单独 import 本模块跑
    # 测试时才退回 core6000_text2 的注入值 / paths.py 现拼的默认目录。
    ce = _CE()
    jdir = getattr(ce, 'JISHO_DIR', '') if ce is not sys.modules[__name__] \
        else core6000_text2.JISHO_DIR
    return os.path.join(jdir or _default_jisho_dir(), '%s.json' % note_id)


def _default_jisho_dir():
    """没有巨石注入时（单独 import 本模块跑测试）按 paths.py 现拼一个，口径一致。"""
    import paths as WSP
    data = getattr(WSP, 'DATA_CORE6000', os.path.join(WSP.DATA, 'core6000'))
    return os.path.join(data, 'jisho')


def filter_by_max_len(cands, n):
    """按 ``--jisho-max-len N`` 过滤候选：只留去空白后 ≤N 字的句子。

    ``n`` 不是正整数时原样返回（不启用过滤）。这是**每次运行时的视图**：
    缓存文件存的是全量候选，过滤绝不写回缓存（否则下次不带该参数会读到被截断的列表）。
    下限仍由四道闸门的 SENT_MIN 兜底，这里只做上限。
    """
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        return list(cands)
    return [c for c in cands if len(RE_WS.sub('', c.get('jp') or '')) <= n]


def jisho_fetch(card, args):
    """抓 Jisho 例句候选（含振假名渲染），按 noteId 缓存。

    返回 ``(candidates, reason)``：``reason`` 非空表示没抓到（网络/依赖/零候选）。
    Jisho 的 robots.txt 要求 crawl-delay 40s，所以**一张卡只抓一页并落盘**，
    重跑 gen / 重试闸门都读缓存。

    ``--jisho-max-len N``（正整数）在**取回候选之后、编号之前**做 in-place 过滤
    （``filter_by_max_len``）：``--list-jisho`` 的清单与自动/``--jisho-pick`` 的选句
    看到的是同一个过滤后的列表，编号天然一致；过滤结果不落缓存。
    """
    n_max = getattr(args, 'jisho_max_len', None)
    path = _CE().jisho_cache_path(card['id'])
    if not getattr(args, 'refresh_jisho', False):
        cached = read_json(path)
        if isinstance(cached, dict) and cached.get('candidates') is not None \
                and cached.get('word') == card['word']:
            cands = cached['candidates']
            kept = filter_by_max_len(cands, n_max)
            if len(kept) < len(cands):
                print('提示：%s（%d）--jisho-max-len %d 滤掉 %d/%d 条长候选'
                      % (card['word'], card['id'], n_max, len(cands) - len(kept), len(cands)),
                      file=sys.stderr)
            return kept, ''
    JX, why = _CE().load_jisho()
    if JX is None:
        return [], 'jisho_example 不可用（%s）' % why
    ns = argparse.Namespace(min_chars=SENT_MIN, max_chars=SENT_MAX, exact=False)
    try:
        content = JX.fetch_page(JX.search_url(card['word']),
                                getattr(args, 'jisho_timeout', 30.0) or 30.0)
        page = JX.parse_page(content)
    except Exception as exc:
        return [], '抓 Jisho 失败：%s' % exc
    if not page['entries']:
        return [], 'Jisho 没有返回例句（0 条或页面结构变了）'
    try:
        lex = JX.build_lexicon()
    except Exception as exc:
        return [], '初始化 Sudachi/ruby_engine 失败：%s' % exc
    lookup = JX.build_jmdict(not getattr(args, 'no_dict', False))
    matched, dropped = JX.filter_entries(page['entries'], card['word'], card['reading'], lex, ns)
    out = []
    for c in matched:
        html, issues = JX.render_ruby(c['ja'], c['annotations'], lex, lookup)
        out.append({'jp': c['ja'], 'en': c.get('en') or '', 'source': c.get('source') or '',
                    'url': c.get('url') or '', 'match': c.get('match') or '',
                    'ruby': html, 'ruby_ok': not issues, 'ruby_issues': issues})
    write_json(path, {'noteId': card['id'], 'word': card['word'],
                      'reading': card['reading'], 'fetched_at': dt.datetime.now().isoformat(
                          timespec='seconds'),
                      'query_url': JX.search_url(card['word']),
                      'total_found': page['total'], 'dropped': dict(dropped),
                      'candidates': out})
    if not out:
        return [], 'Jisho 有 %d 条但过滤后 0 条可用（%s）' % (
            len(page['entries']), ' / '.join('%s %d' % kv for kv in dropped.items()) or '无')
    # 现抓路径：缓存已存全量候选，这里只做运行时视图过滤（不落盘）。
    kept = filter_by_max_len(out, n_max)
    if len(kept) < len(out):
        print('提示：%s（%d）--jisho-max-len %d 滤掉 %d/%d 条长候选'
              % (card['word'], card['id'], n_max, len(out) - len(kept), len(out)),
              file=sys.stderr)
    if not kept:
        return [], ('Jisho 有 %d 条候选，--jisho-max-len %d 过滤后无候选'
                    % (len(out), n_max))
    return kept, ''


def jisho_similarity(a, b):
    """两句的字符相似度（0–1）；用来挡「只换主语」的换皮句。"""
    return difflib.SequenceMatcher(None, flatten(a), flatten(b)).ratio()


def word_written_form(word):
    """词形去掉末尾送假名后的「书写骨架」：`思い込む` → `思い込`，`適当` → `適当`。

    用来在真实语料里判「这句写的是不是卡片上的那个词形」：`思い込んでいる` 命中
    `思い込`，而只写假名的 `思いこんで` 不命中。纯假名词或骨架太短（`あまり`）返回 ''，
    调用方据此关掉这条偏好。
    """
    if not word:
        return ''
    key = re.sub(r'[\u3041-\u3096\u30fc]+$', '', word.strip())
    return key if len(key) >= 2 else ''


def _pick_reason(c, strict, forms, key, first, manual=False):
    """四道闸门里第一条不过的原因（全过返回 ''）。

    自动挑选时四道全跑。``manual=True``（用户 ``--jisho-pick N`` 明确点了这条）
    只跳过**偏好类**的「与第一句太像」：人已经做了选择，不该被相似度阈值压掉；
    振假名结构 / 真含目标词 / 长度仍照查（这些是「能不能安全写进卡」的硬条件）。
    长度本身也已被 jisho 抓取阶段按 SENT_MIN–SENT_MAX 过滤过，这里只是兜底。
    """
    jp = c['jp']
    n_chars = len(RE_WS.sub('', jp))
    if not c.get('ruby_ok'):
        return 'ruby'
    if strict:
        if key not in jp:
            return 'kana-form'
    elif not any(f in jp for f in forms):
        return 'no-target'
    if not (SENT_MIN <= n_chars <= SENT_MAX):
        return 'length'
    if not manual and first and _CE().jisho_similarity(jp, first) >= JISHO_MIN_SIMILARITY:
        return 'too-similar'
    return ''


def _pick_result(c):
    return {'jp': c['jp'], 'ruby': c['ruby'], 'en': c.get('en') or '',
            'source': c.get('source') or '', 'url': c.get('url') or '',
            'match': c.get('match') or ''}


def pick_jisho(card, args):
    """给这张卡挑一条**真实**例句：``{jp, ruby, en, source, url, match}`` 或 ``None``。

    只认：振假名结构合格 + 真含目标词 + 长度进闸门区间 + 与第一句相似度 < 阈值。
    候选本身已由 jisho_example 按 exact>compound>phrase、句长、语料来源排过序；
    这里先挑「**目标词写法一字不差**出现」的（`思い込む` 卡优先要 `思い込んで`，
    而不是只写成假名的 `思いこんで`），一条都没有才退而接受活用形/假名写法。

    ``--jisho-pick N``（>0）改用第 N 条候选（1 起，编号与 ``--list-jisho`` 一致）：
    **手动选择优先**——只豁免「与第一句太像」这条偏好闸门，振假名结构 / 真含目标词 /
    长度仍照查；越界或不合格都**明确报错**（带原因），绝不静默退回自动挑选。
    默认 0 时行为与自动挑选逐字一致。
    """
    cands, why = _CE().jisho_fetch(card, args)
    if not cands:
        return None, why
    first = card['sentences'][0]['jp'] if card['sentences'] else ''
    forms = _CE().target_forms(card)
    key = _CE().word_written_form(card['word'] or '')
    pick_n = getattr(args, 'jisho_pick', 0) or 0
    if pick_n > 0:
        if pick_n > len(cands):
            return None, ('Jisho 只有 %d 条候选，--jisho-pick %d 超出范围'
                          % (len(cands), pick_n))
        c = cands[pick_n - 1]
        reason = _pick_reason(c, bool(key), forms, key, first, manual=True)
        if reason:
            return None, ('--jisho-pick %d 指向的第 %d 条候选不合格（%s）：%s'
                          % (pick_n, pick_n, reason, one_line(c['jp'], 40)))
        return _pick_result(c), ''
    for strict in ((True, False) if key else (False,)):
        skipped = []
        for c in cands:
            reason = _pick_reason(c, strict, forms, key, first)
            if reason:
                skipped.append(reason)
                continue
            return _pick_result(c), ''
    seen = {}
    for s in skipped:
        seen[s] = seen.get(s, 0) + 1
    return None, 'Jisho 的 %d 条候选都不合适（%s）' % (
        len(cands), ' / '.join('%s %d' % kv for kv in seen.items()))
