# -*- coding: utf-8 -*-
"""原子能力：**一段文字 + 背景信息 → 专有名词清单**（不碰 Anki、不写库）。

这是本工作区里「专有名词」的唯一提取实现。上层 `code/execution/proper.py` 只是
把很多段字幕喂给这里的 `extract_batch()`，再负责合并、判收录、写卡；口径不复制。

为什么需要模型层（不是纯脚本能做的）
------------------------------------
Sudachi 只认词典里的固有名詞：`エリザベス`/`ディアンヌ`/`マーリン` 标得对，但
`メリオダス`/`ゴウセル`/`キング`/`エスカノール`/`ギルサンダー` 全被判成
`名詞-普通名詞`（2026-10-22 实测）。所以：

* **确定性预扫**（`candidates()`）只当**提示**：Sudachi 固名 + 句内片假名长串。
  它召回不全，但便宜、可复现，能给小模型兜住片假名名字。
* **模型层**读「文字 + 背景」判哪些是本作专有，并给出类别/读音/一句话说明。

两者输出都过同一道**机械闸门**：`word` 必须是原文子串 —— 模型幻觉在这里就被拦掉。

对外接口
--------
::

    import proper_extract as PE

    names, issues = PE.extract('憤怒の罪のメリオダス', background='作品=七大罪')
    # names -> [{'word': 'メリオダス', 'categories': ['人名', '称号'], 'reading': 'めりおだす',
    #            'gloss': '…', 'why': '…', 'evidence': '…', 'source': 'model'}, …]

    batch, issues = PE.extract_batch([{'text': '…', 'background': '…'}, …], per_request=8)

命令行
------
::

    python code/tools/proper_extract.py --text "気持ちを届けるのはシルフさんたちのお仕事" \
        --background "作品=水星领航员" --json
    python code/tools/proper_extract.py --file temp/scene.txt --background "平家物语 第02集"
    Get-Content temp/cue.txt | python code/tools/proper_extract.py --stdin --background "…" --json
    python code/tools/proper_extract.py --text "…" --no-model     # 只跑确定性预扫
"""
import argparse
import json
import os
import re
import sys
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
for _p in (os.path.join(_CODE, 'common'), os.path.join(_CODE, 'analysis', 'vocab_cover')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import textio  # noqa: E402  UTF-8 stdio 唯一入口（import 即生效）
from _deps import add_pylibs  # noqa: E402  SudachiPy 在 data/pylibs 里
from _norm import norm_word, to_hiragana  # noqa: E402  词形归一的唯一实现

add_pylibs()

# ============================================================================
# 常量
# ============================================================================
#: 专有名词的类别（卡片的**扁平类别标签**与 `Categories` 字段都是这一份枚举）
CATEGORIES = ('人名', '地名', '组织', '概念', '技能', '种族', '称号', '作品名', '其他')

#: 一条专名记录的字段（JSON 形状的唯一说明）
NAME_FIELDS = ('word', 'categories', 'reading', 'gloss', 'why', 'evidence', 'source')

KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30a0-\u30ff\u30fc\u309d\u309e]+$')
KATA_RUN = re.compile(r'[\u30a1-\u30f6\u30fc]{4,}')
LATIN = re.compile(r'[A-Za-z0-9]')
TAG = re.compile(r'<[^>]+>')

MAX_WORD_LEN = 12          # 「七つの大罪」= 6；超过基本是整句误抽
MIN_WORD_LEN = 1           # 单字名字（千/悟/律）确实存在，交给模型判
CONTEXT_CHARS = 8          # evidence 取命中位置前后各多少字

PROPER_MAX_TOKENS = 8192   # 单次请求的输出上限
DEFAULT_PER_REQUEST = 8    # 一次请求塞几段文字


# ============================================================================
# 确定性预扫
# ============================================================================
_TAGGER = None


def tagger():
    """Sudachi 分词器（C 模式 = 最长单位；懒加载、进程内复用）。"""
    global _TAGGER
    if _TAGGER is None:
        from sudachipy import Dictionary, SplitMode
        d = Dictionary(dict='core')
        maker = getattr(d, 'tokenizer', None) or d.create
        _TAGGER = (maker(), SplitMode.C)
    return _TAGGER


def plain(text):
    """统一口径：NFKC（半角片假名 → 全角）、去标签、合并空白。"""
    s = unicodedata.normalize('NFKC', str(text or ''))
    s = TAG.sub('', s.replace('<br>', '\n'))
    return re.sub(r'[ \t\u3000]+', ' ', s).strip()


def candidates(text):
    """确定性预扫 —— **只当提示，不单独定稿**。

    两路：
      A. Sudachi `名詞-固有名詞`（相邻固名 token 合并；带 人名/地名/一般 提示）；
      C. 句内片假名长串（≥4 字）—— 覆盖「Sudachi 判成普通名词」的片假名名字。

    B 路（生词残差）需要 Anki 的已知词表，由上层用 `hints=` 传进来。
    """
    s = plain(text)
    if not s:
        return []
    out, seen = [], set()

    def add(word, pos3='', source='sudachi'):
        w = unicodedata.normalize('NFKC', word or '').strip()
        k = norm_word(w)
        if not k or k in seen:
            return
        if not (KANJI.search(w) or KANA.search(w)) or LATIN.search(w):
            return
        if not (MIN_WORD_LEN <= len(w) <= MAX_WORD_LEN):
            return
        seen.add(k)
        out.append({'word': w, 'pos3': pos3, 'source': source})

    tok, mode = tagger()
    run, run_pos3 = '', ''

    def flush():
        nonlocal run, run_pos3
        if run:
            add(run, run_pos3, 'sudachi')
        run, run_pos3 = '', ''

    for m in tok.tokenize(s, mode):
        pos = m.part_of_speech()
        p1 = pos[0] if len(pos) > 0 else ''
        p2 = pos[1] if len(pos) > 1 else ''
        p3 = pos[2] if len(pos) > 2 else ''
        if p1 == '名詞' and p2 == '固有名詞':
            run += m.surface()
            run_pos3 = run_pos3 or p3
        else:
            flush()
    flush()

    for m in KATA_RUN.finditer(s):
        add(m.group(0), 'カタカナ', 'kana-run')
    return out


# ============================================================================
# 机械闸门
# ============================================================================
def _norm_categories(raw):
    """模型给的类别 → 合法枚举（保序去重；一个都不合法就记 `其他`）。"""
    vals = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
    out = []
    for v in vals:
        c = str(v or '').strip()
        # 容忍「人名」写成「人物」这类近义写法：映射到最近的枚举，不整条丢掉
        alias = {'人物': '人名', '角色': '人名', '人物名': '人名',
                 '地点': '地名', '场所': '地名', '国名': '地名',
                 '团体': '组织', '团体名': '组织', '机构': '组织',
                 '设定': '概念', '世界观': '概念', '术语': '概念',
                 '招式': '技能', '魔法': '技能', '能力': '技能',
                 '职业': '称号', '身份': '称号', '阶级': '称号',
                 '民族': '种族', '人种': '种族', '种族名': '种族'}.get(c, c)
        if alias in CATEGORIES and alias not in out:
            out.append(alias)
    return out or ['其他']


def _hira(reading):
    """读音 → 纯平假名；不是纯假名就清空（宁缺勿错）。"""
    r = unicodedata.normalize('NFKC', str(reading or '')).strip()
    if not r or not KANA_ONLY.match(r):
        return ''
    return to_hiragana(r)


def _evidence(text, word):
    """命中的原文片段（前后各带几个字），人工核对用。"""
    i = text.find(word)
    if i < 0:
        return ''
    a = max(0, i - CONTEXT_CHARS)
    b = min(len(text), i + len(word) + CONTEXT_CHARS)
    return text[a:b].replace('\n', '⏎')


def _token_spans(text):
    """[ (start, end), … ] —— Sudachi 在**这段文字**上的切词边界。"""
    tok, mode = tagger()
    spans, pos = [], 0
    for m in tok.tokenize(text, mode):
        n = len(m.surface())
        spans.append((pos, pos + n))
        pos += n
    return spans


def _aligned(word, text, spans):
    """`word` 是否落在**整词边界**上（起点是某个 token 的起点、终点是某个 token 的终点）。

    拦的是「把下一个词的一个字粘上来」这类碎片：`晃知りません` 里 Sudachi 切的是
    `晃` + `知り`，模型给出 `晃知` 就能通过子串闸门 —— 但它的结尾在 `知り` 中间，
    不是词边界。真正的专名（`水無灯里`=水無+灯里、`ネオ・ヴェネツィア`=ネオ+・+ヴェネツィア）
    都是若干整 token 的拼接，照样通过。
    """
    starts = {a for a, _b in spans}
    ends = {b for _a, b in spans}
    i = text.find(word)
    while i >= 0:
        if i in starts and (i + len(word)) in ends:
            return True
        i = text.find(word, i + 1)
    return False


BAD_TAIL = ('...', '…', '、、', '。', '、', '！', '？', '!', '?')


def validate(text, names, source='model'):
    """把一批候选名过机械闸门，返回 (合格的, 问题列表)。

    ★ 三条硬判据：
    1. `word` 必须是**原文的子串**（NFKC 之后）—— 模型幻觉、改写在这里被拦掉；
       也正因如此，模型可以把脚本提示的碎片**前后补全**成完整专名（`大納` → `大納言`）。
    2. `word` 必须落在**整词边界**上（见 `_aligned`）—— 拦「多粘一个字」的碎片。
    3. 不含空格、不以标点结尾 —— `その 透明な少女と...` 这种预告标题不该当词条。
    """
    s = plain(text)
    spans = _token_spans(s) if s else []
    ok, issues, seen = [], [], set()
    for raw in names or []:
        if not isinstance(raw, dict):
            issues.append('条目不是对象：%r' % (raw,))
            continue
        w = unicodedata.normalize('NFKC', str(raw.get('word') or '')).strip()
        if not w:
            issues.append('word 为空')
            continue
        # 先查形状、再查子串：这样「David」报的是"含拉丁"，而不是含糊的"不在原文里"
        if LATIN.search(w):
            issues.append('「%s」含拉丁/数字（本牌组只收日文写法）' % w)
            continue
        if not (KANJI.search(w) or KANA.search(w)):
            issues.append('「%s」不含日文字符' % w)
            continue
        if not (MIN_WORD_LEN <= len(w) <= MAX_WORD_LEN):
            issues.append('「%s」长度 %d 越界（%d–%d）' % (w, len(w), MIN_WORD_LEN, MAX_WORD_LEN))
            continue
        if w not in s:
            issues.append('「%s」不在原文里（模型可能改写了词形）' % w)
            continue
        if re.search(r'\s', w):
            issues.append('「%s」含空格（词条不该带空格）' % w)
            continue
        if w.endswith(BAD_TAIL):
            issues.append('「%s」以标点结尾（像标题/台词片段，不是词条）' % w)
            continue
        if spans and not _aligned(w, s, spans):
            issues.append('「%s」不是整词边界（像是把相邻词的一个字粘上来了）' % w)
            continue
        k = norm_word(w)
        if k in seen:
            continue
        seen.add(k)
        ok.append({
            'word': w,
            'categories': _norm_categories(raw.get('categories')),
            'reading': _hira(raw.get('reading')),
            'gloss': str(raw.get('gloss') or '').strip(),
            'why': str(raw.get('why') or '').strip(),
            'evidence': _evidence(s, w),
            'source': source,
        })
    return ok, issues


# ============================================================================
# 提示词（正本；改提示词只改这里）
# ============================================================================
PROPER_INSTRUCTION = '''你是日语专有名词抽取器。输入是「一段日文文字」+「背景信息」+「脚本预扫提示」，你要找出这段文字里出现的**专有名词**。

【输入】
- background：这段文字出自什么作品/场景/上下文（例如「作品=水星领航员 第01集」「作品=七大罪；七位被定罪的骑士」）
- items：若干段文字，每项 {idx, text, hints}
  - hints 是脚本用分词器预扫出的候选，**只是提示、可能碎片化或漏掉**：可以忽略，可以前后补全成完整专名
  - hints 里带 `※` 的是**行首发话人标签**（脚本从 `(名前)` 抽的），几乎一定是人物名
  - 同一个名字可能同时属于**多种类别**：那就把多个类别都写上。例：
    メリオダス = 人名 + 称号；七つの大罪 = 作品名 + 组织；ウンディーネ = 种族 + 称号

【要抽什么】
人名（角色名、绰号）、虚构或真实地名、组织/团体、世界观概念、技能/招式/魔法名、种族、称号、作品名。
判断标准是「在这个作品/语境里它是不是一个专名」，不是「是不是一个生词」。

【不要抽什么】
- 普通名词与普通动词：魔法、悪魔、正義、王子、気持ち、お仕事
- 语气词、语法词、拟声词、指示词
- 只是泛指、没有专指对象的词
判不准就不输出，宁可漏，不要凑。

【每条输出什么】
- word：**必须在 text 里逐字出现**（允许把 hints 的碎片前后补全成完整专名；补全后仍须在 text 里）
- categories：1 个或多个，只能取：人名／地名／组织／概念／技能／种族／称号／作品名／其他
- reading：纯平假名（例：めりおだす）；不确定就留空
- gloss：一句话说明它在作品里是什么（例：〈憤怒の罪〉を背負う骑士／七大罪的主角）
- why：一句话说明你凭什么判它是专有名词（给人工抽检用）

【输出格式】
只输出一个 JSON 对象，前后不要任何解释或 markdown 围栏：
{"items":[{"idx":0,"names":[{"word":"…","categories":["人名"],"reading":"…","gloss":"…","why":"…"}]}]}
- items 的**条数、idx 与输入一一对应**，不许漏、不许合并、不许自创
- 某段文字没有专名就给空数组 "names": []
- 字符串里不要用半角双引号（用「」代替），不要写 true/false 之外的 JSON 扩展'''


def _render_items(items):
    """一次请求的 user 正文（与 token 估算共用同一份渲染）。

    带 `※` 的 hint = 行首发话人标签（`(名前)`）—— 它是「这是人物名」的强信号，
    模型据此不会把 `ギルサンダー` 误判成技能名。
    """
    payload = []
    for i, it in enumerate(items):
        hs = []
        for h in (it.get('hints') or []):
            if isinstance(h, str):
                hs.append(h)
                continue
            w = h.get('word') or ''
            if w:
                hs.append(w + ('※' if h.get('source') == 'speaker' else ''))
        payload.append({'idx': i, 'text': plain(it.get('text') or ''),
                        'hints': [h for h in hs if h]})
    return json.dumps({'items': payload}, ensure_ascii=False, indent=1)


def _user(items):
    backgrounds = sorted({str(it.get('background') or '').strip() for it in items} - {''})
    bg = '；'.join(backgrounds) if backgrounds else '（未提供）'
    return ('背景：' + bg + '\n\n' + _render_items(items))


def _fit(idxs, per_request, items, cfg, LLM):
    """按下标切块，但保证每块 prompt 不超本地模型预算（同 pipeline.fit_groups 的口径）。

    切的是**下标**不是条目本身：两段文字完全相同时，用 `items.index(...)` 会把第二段
    错认成第一段，产出错位。
    """
    cap = LLM.budget(cfg)
    out, cur = [], []
    for i in idxs:
        if cur and (len(cur) >= per_request
                    or LLM.estimate_tokens(_user([items[j] for j in cur + [i]])) > cap):
            out.append(cur)
            cur = []
        cur.append(i)
    if cur:
        out.append(cur)
    return out


# ============================================================================
# 模型层
# ============================================================================
def _default_llm():
    try:
        import local_llm as LLM
    except ImportError as exc:                       # 极端环境：没有本地模型客户端
        raise SystemExit('找不到本地模型客户端 code/common/local_llm.py：%s' % exc)
    return LLM, LLM.load_config()


def extract_batch(items, per_request=DEFAULT_PER_REQUEST, cfg=None, LLM=None,
                  quiet=True):
    """多段文字一次抽完。返回 (每段的名字列表, 问题列表)。

    items: [{'text': 原文, 'background': 背景, 'hints': [提示词…]}, …]
    **与 `extract()` 走同一条代码路径**（单段就是只有一个 item 的批量），口径不会漂移。
    """
    items = [dict(it) for it in (items or [])]
    if not items:
        return [], []
    if LLM is None or cfg is None:
        LLM, cfg = _default_llm()

    results = [[] for _ in items]
    issues, req = [], 0
    for idxs in _fit(list(range(len(items))), max(1, int(per_request)), items, cfg, LLM):
        group = [items[j] for j in idxs]
        msgs = [{'role': 'system', 'content': PROPER_INSTRUCTION},
                {'role': 'user', 'content': _user(group)}]
        try:
            obj, _res, problems = LLM.call_json(cfg, msgs, require='items', json_mode=True,
                                                enable_thinking=False, quiet=quiet,
                                                max_tokens=PROPER_MAX_TOKENS)
            req += 1
        except Exception as exc:                     # 一段出错不许拖垮整批
            issues.append('一批请求失败（%d 段）：%s: %s'
                          % (len(group), type(exc).__name__, exc))
            continue
        if problems:
            issues.append('回复形状不合格：%s' % '；'.join(problems)[:200])
        got = {}
        if isinstance(obj, dict):
            for row in (obj.get('items') or []):
                if isinstance(row, dict) and isinstance(row.get('idx'), int):
                    got[row['idx']] = row.get('names') or []
        for local_i, it in enumerate(group):
            names = got.get(local_i)
            if names is None:
                issues.append('第 %d 段没有对应输出（idx 对不上）' % (idxs[local_i] + 1))
                continue
            ok, bad = validate(it.get('text') or '', names, source='model')
            results[idxs[local_i]] = ok
            for why in bad:
                issues.append('第 %d 段：%s' % (idxs[local_i] + 1, why))
    return results, issues


def extract(text, background='', hints=(), cfg=None, LLM=None):
    """**原子能力本体**：一段文字 + 背景 → (专名清单, 问题列表)。"""
    res, issues = extract_batch([{'text': text, 'background': background, 'hints': list(hints)}],
                                per_request=1, cfg=cfg, LLM=LLM)
    return (res[0] if res else []), issues


def extract_offline(text, hints=()):
    """不连模型，只跑确定性预扫（测试/离线用）。"""
    names = []
    for h in list(candidates(text)) + list(hints or []):
        w = h.get('word') if isinstance(h, dict) else h
        names.append({'word': w, 'categories': ['其他'], 'reading': '',
                      'gloss': '', 'why': '确定性预扫（未过模型）',
                      'source': (h.get('source') if isinstance(h, dict) else 'caller') or 'caller'})
    return validate(plain(text), names, source='scan')


# ============================================================================
# CLI
# ============================================================================
def _read_input(a):
    if a.text:
        return a.text
    if a.file:
        return textio.read_text(a.file)
    if a.stdin:
        return textio.read_stdin()
    return ''


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='原子能力：一段文字 + 背景 → 专有名词清单（不碰 Anki、不写库）')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--text', help='直接给一段文字')
    src.add_argument('--file', help='从文件读（UTF-8/UTF-16/GBK 自动判）')
    src.add_argument('--stdin', action='store_true', help='从标准输入读')
    ap.add_argument('--background', default='',
                    help='背景信息（作品/场景/上下文）。例：作品=水星领航员 第01集')
    ap.add_argument('--json', action='store_true', help='输出 JSON（默认人读格式）')
    ap.add_argument('--no-model', action='store_true', help='只跑确定性预扫，不连模型')
    ap.add_argument('--per-request', type=int, default=DEFAULT_PER_REQUEST,
                    help='批量模式下一次请求几段文字（默认 %d）' % DEFAULT_PER_REQUEST)
    a = ap.parse_args(argv)

    text = _read_input(a)
    if not text.strip():
        raise SystemExit('输入为空')
    if a.no_model:
        names, issues = extract_offline(text)
    else:
        names, issues = extract(text, background=a.background)

    if a.json:
        print(json.dumps({'background': a.background, 'text': plain(text),
                          'names': names, 'issues': issues},
                         ensure_ascii=False, indent=1))
        return 0 if not issues else 2
    print('文字：%s' % plain(text)[:120])
    print('背景：%s' % (a.background or '（未提供）'))
    print('专名 %d 条：' % len(names))
    for n in names:
        print('  %-12s [%s] %s  ← %s'
              % (n['word'], '/'.join(n['categories']), n['gloss'] or '-', n['evidence'] or '-'))
    for why in issues:
        print('  ⚠ %s' % why)
    return 0 if not issues else 2


if __name__ == '__main__':
    sys.exit(main())
