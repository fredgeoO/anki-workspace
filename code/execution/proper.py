# -*- coding: utf-8 -*-
"""专有名词收集：字幕 → 专名清单 → 卡片（`0-日本语学习::0-词汇::3-专有词汇`）。

**只收集，不进学习队列**：本脚本不写 `due`/`type`/`queue`、不 suspend、不改牌组选项。

两层分工
--------
* 提取口径只有一份：`code/tools/proper_extract.py`（文字 + 背景 → 专名清单）。
* 本脚本负责确定性部分：字幕切窗、三路提示、合并去重、查重、校验、写库、配音。

子命令
------
    model   --check / --commit / --delete     笔记类型 `Japanese Proper Noun`（卡面在代码里）
    scan    <srt…> --work <作品>              只读：出候选 + 报告
    split   --batches N                       切批
    gen     [--fix-failed]                    本地模型写成卡片内容
    verify                                    写库前唯一一道校验 → verified.json
    write   [--commit]                        入库（默认演练）
    audio   [--commit]                        读法音频（edge-TTS 读 Reading 假名）
    add     --word … --source …               手动补一张不在字幕里的卡
    merge-fix --file fix_output.json          强模型补做的产出并回

卡片
----
正面只有 `Word`；背面 `Reading` + `Word Audio`（自动播）+ `[Categories] Meaning` +
日语介绍句 `Intro`（带振假名）+ 中文翻译 + `AINote` + 底部 `Source`（出处与原句追溯）。
`Intro` 的振假名由 `ruby_engine` 确定性渲染（模型只给纯文本），与例句卡同一分工。

标签
----
    专有名词                       必有（根标签）
    人名/地名/组织/概念/技能/种族/称号/作品名/其他   1..n，**扁平**（= Categories 字段同一份数据）
    动画::水星领航员                出处：继承库里现有动画标签的**前两层**，不带季度/集数
    亚瑟王传说                      非动画出处就是一条裸标签

类别扁平是因为一个专名可能同时是「人名」和「称号」；出处继承 `动画::<作品>` 是为了
`tag:动画::水星领航员` 能同时搜到例句卡与专名卡。**不写批次/日期标签**
（2026-10-22 用户口径：没必要）。「关联/原型」也不进标签，写进 `AINote` 的「关联」段。
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
for _p in (os.path.join(_CODE, 'common'), _HERE,
           os.path.join(_CODE, 'tools'),
           os.path.join(_CODE, 'analysis', 'vocab_cover')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import textio  # noqa: E402  UTF-8 stdio 唯一入口
import anki_api as AK  # noqa: E402  唯一的 Anki 访问点
import check_proper as CP  # noqa: E402  专名条目的唯一规则实现
import jp_decks as JD  # noqa: E402  牌组路径的唯一来源
import llm_out as OUT  # noqa: E402  模型产出吸收层
import paths as WSP  # noqa: E402  工作区路径的唯一来源
import pipeline as P  # noqa: E402  复用 CFG / norm / strip_html / fit_groups
import mine as M  # noqa: E402  复用 slug / next_index / 余差法 / 已知词表
import proper_extract as PE  # noqa: E402  原子能力（文字 + 背景 → 专名）
import ruby_engine as RE  # noqa: E402  确定性振假名引擎
import srt as SRT  # noqa: E402  字幕解析（NFKC/发话人/音效过滤都在里面）
from _norm import norm_word, to_hiragana  # noqa: E402  词形归一的唯一实现

DECK = JD.DECK_PROPER
MODEL = 'Japanese Proper Noun'
TAG_ROOT = '专有名词'

ROOT = os.path.join(WSP.DATA_VOCAB, 'proper')     # data/vocab/proper/<slug>/
LATEST = os.path.join(ROOT, 'latest.json')

VOICE = 'ja-JP-NanamiNeural'

# 判定/写入时的硬约束
MAX_OCCURRENCES = 3
DEFAULT_WINDOW = 6          # 一次送模型几条台词（窗口内有上下文才能判「本作独有」）
GEN_MAX_TOKENS = 8192


# ============================================================================
# 笔记类型（卡面在代码里，不靠手工在 Anki 里编辑）
# ============================================================================
MODEL_FIELDS = ('Index', 'Word', 'Reading', 'Meaning', 'Categories',
                'Intro', 'Intro Translation', 'AINote', 'Source', 'Word Audio')

MODEL_FRONT = '<div class="pn-word">{{Word}}</div>'

MODEL_BACK = '''<div class="pn-word pn-small">{{Word}}</div>
<hr id=answer>
<div id="autoplay" class="pn-reading">{{Reading}} {{Word Audio}}</div>
<div class="pn-meaning">[{{Categories}}] {{Meaning}}</div>
<hr>
<div class="pn-intro">{{Intro}}</div>
<div class="pn-intro-cn">{{Intro Translation}}</div>
<hr>
<div class="pn-ainote">{{AINote}}</div>
<div class="pn-source">{{Source}}</div>
<script>
  var elem = document.querySelector("#autoplay .soundLink, #autoplay .replaybutton");
  if (elem) { elem.click(); }
</script>'''

MODEL_CSS = '''.card {
  font-family: aozora mincho;
  font-size: 20px;
  text-align: center;
  color: black;
  background-color: white;
}
.pn-word { font-size: 48px; line-height: 1.3; padding: 24px 0; }
.pn-word.pn-small { font-size: 34px; padding: 8px 0 0; }
.pn-reading { font-size: 26px; color: #444; }
.pn-meaning { font-size: 26px; padding: 6px 0; }
.pn-intro { font-size: 26px; padding: 10px 0 4px; line-height: 1.7; }
.pn-intro-cn { font-size: 20px; color: #555; padding-bottom: 6px; }
.pn-ainote { font-family: Arial; font-size: 18px; text-align: left; line-height: 1.7; }
.pn-source { font-size: 14px; color: #888; padding-top: 10px; }
ruby { ruby-position: over; }
rt { font-size: 0.55em; color: #555; }
'''

MODEL_TEMPLATES = [{'Name': 'Word -> Meaning', 'Front': MODEL_FRONT, 'Back': MODEL_BACK}]


def ensure_model(commit=False, force_templates=False):
    """建/校验笔记类型。返回 True = 现在就绪。

    * 不存在：`commit` 才建（`createModel` 不是幂等的，建之前先问 `model_exists`）；
    * 已存在：**只校验不覆盖** —— 卡面以代码为准，漂移要显式 `--force-templates` 才改。
    """
    exists = AK.model_exists(MODEL)
    if not exists:
        if not commit:
            print('笔记类型「%s」不存在（--commit 时才建）' % MODEL)
            return False
        AK.create_model(MODEL, MODEL_FIELDS, MODEL_TEMPLATES, MODEL_CSS)
        print('已建笔记类型「%s」（%d 字段）' % (MODEL, len(MODEL_FIELDS)))
        return True

    problems = []
    fields = tuple(AK.model_field_names(MODEL))
    if fields != MODEL_FIELDS:
        problems.append('字段不一致\n    库内：%s\n    代码：%s' % (list(fields), list(MODEL_FIELDS)))
    tpl = AK.model_templates(MODEL).get('Word -> Meaning') or {}
    if (tpl.get('Front') or '').strip() != MODEL_FRONT.strip():
        problems.append('正面模板与代码不一致')
    if (tpl.get('Back') or '').strip() != MODEL_BACK.strip():
        problems.append('背面模板与代码不一致')
    css = AK.model_css(MODEL)
    if css.strip() != MODEL_CSS.strip():
        problems.append('CSS 与代码不一致')
    if not problems:
        print('笔记类型「%s」：字段 %d / 模板 / CSS 全部一致' % (MODEL, len(MODEL_FIELDS)))
        return True
    print('笔记类型「%s」存在，但与代码不一致：' % MODEL)
    for p in problems:
        print('  ✗ %s' % p)
    if commit and force_templates:
        AK.update_model_templates(MODEL, MODEL_TEMPLATES)
        AK.update_model_styling(MODEL, MODEL_CSS)
        print('  已按代码覆盖模板与 CSS（字段改动不支持自动做）')
        return True
    print('  → 要按代码覆盖模板/CSS：model --commit --force-templates')
    return False


def cmd_model(a):
    if a.delete:
        if not AK.model_exists(MODEL):
            print('笔记类型「%s」本来就不存在' % MODEL)
            return 0
        n = len(AK.find_notes('note:"%s"' % MODEL))
        if n:
            raise SystemExit('还有 %d 张卡在用「%s」，先删卡再删笔记类型' % (n, MODEL))
        AK.call('deleteModel', modelName=MODEL)
        print('已删除笔记类型「%s」' % MODEL)
        return 0
    ok = ensure_model(commit=a.commit, force_templates=getattr(a, 'force_templates', False))
    return 0 if ok else 1


# ============================================================================
# 运行目录 / 标签 / 查重
# ============================================================================
def slot(s, limit=40):
    """目录名/标签里可用的片段：保留日文与字母数字，其余换下划线。"""
    s = re.sub(r'[^\w\u3040-\u30ff\u4e00-\u9fff]+', '_', s or '').strip('_')
    return (s or 'run')[:limit]


def episode_of(path, override=''):
    """从文件名猜「第NN集」（`S01E05` / `03.jp` / `第03集` 都认）。"""
    if override:
        return override
    b = os.path.splitext(os.path.basename(path))[0]
    b = re.sub(r'[（(][^）)]*[）)]', '', b)
    b = re.sub(r'\.(jp|ja|jpn)$', '', b, flags=re.I).strip()
    m = re.search(r'[Ss](\d{1,2})[Ee](\d{1,3})', b)
    if m:
        return '第%02d集' % int(m.group(2))
    m = re.search(r'第\s*(\d{1,3})\s*集', b)
    if m:
        return '第%02d集' % int(m.group(1))
    m = re.search(r'(?<!\d)(\d{1,3})$', b)
    if m:
        return '第%02d集' % int(m.group(1))
    return ''


def resolve_run(explicit=''):
    """找到要操作的工作目录（`--run` 显式给，否则用 latest.json 指的那个）。"""
    if explicit:
        p = explicit if os.path.isabs(explicit) else os.path.join(ROOT, explicit)
        if not os.path.isdir(p):
            raise SystemExit('找不到工作目录 %s' % p)
        return p
    if not os.path.exists(LATEST):
        raise SystemExit('还没有任何 run（先跑 proper.py scan）')
    info = json.load(open(LATEST, encoding='utf-8'))
    p = os.path.join(ROOT, info['run'])
    if not os.path.isdir(p):
        raise SystemExit('latest.json 指向的目录不存在：%s' % p)
    return p


def gen_dir(run):
    return os.path.join(run, 'gen')


def load_candidates(run):
    p = os.path.join(run, 'candidates.json')
    if not os.path.exists(p):
        raise SystemExit('没有 candidates.json（先跑 proper.py scan）')
    return json.load(open(p, encoding='utf-8'))


def tag_safe(s):
    """标签里不能有空格；其余照抄。"""
    return re.sub(r'\s+', '_', str(s or '')).strip()


def build_tags(category_list, work_tag):
    """标签集合：根 + 类别（扁平、可多个） + 出处标签。

    * 出处标签由 `resolve_work_tag()` 决定：动画作品继承库里现有的两层
      `动画::<作品>`（**不带季度/集数**），非动画出处（`亚瑟王传说`）就是裸名一条；
    * 类别一律扁平（`人名`/`称号` 并列）—— 一个专名可能同时属于好几类；
    * **不写批次/日期标签**（2026-10-22 用户口径：没必要）。回滚按「牌组 + 出处标签」
      或浏览器的 `Added` 列来圈范围；
    * 「关联/原型」（`related`）**不进标签**：实测模型把它当「相关词」用
      （`晃`→`蓝华`、`オレンジぷらねっと`→`アリア社`），当标签就是噪声，改写到
      `AINote` 的「关联」段。
    """
    tags = [TAG_ROOT]
    for c in category_list or []:
        t = tag_safe(c)
        if t and t in CP.CATEGORIES and t not in tags:
            tags.append(t)
    w = tag_safe(work_tag)
    if w and w not in tags:
        tags.append(w)
    return tags


_TAGS_CACHE = None


def library_tags():
    """库里现有的全部标签（判「这个作品的动画标签长什么样」用，进程内只取一次）。"""
    global _TAGS_CACHE
    if _TAGS_CACHE is None:
        _TAGS_CACHE = set(AK.tags() or [])
    return _TAGS_CACHE


def resolve_work_tag(work, explicit=''):
    """作品名 → 出处标签。

    规则（2026-10-22 用户口径）：**动画作品名继承现有的 `动画::<作品>` 标签，但不要
    季度/集数那两层** —— 库里例句卡是 `动画::水星领航员::第一季::第04集`，
    专名卡只挂 `动画::水星领航员`，这样 `tag:动画::水星领航员` 能同时搜到两种卡。

    * 显式给了带 `::` 的写法（`--work "动画::水星领航员"`）→ 原样用；
    * 裸作品名 → 库里存在 `动画::<作品>`（或它的更长形式）就用两层的那个；
    * 库里没有（例：`亚瑟王传说` 这种非动画出处）→ 用裸名当扁平标签。
    """
    w = tag_safe(work)
    if not w:
        return ''
    if explicit:
        return tag_safe(explicit)
    if '::' in w:
        return w
    anime = '动画::' + w
    for t in library_tags():
        if t == anime or t.startswith(anime + '::'):
            return anime
    return w


def work_of_source(text):
    """从 `Source` 字段反推出处**作品名**（写入时的格式是 `出自「<work>」…`）。"""
    m = re.search(r'出自「([^」]+)」', text or '')
    return m.group(1) if m else ''


def work_tag_from_tags(tags):
    """从笔记标签里反推出处标签（根与类别以外的那一个）。

    老卡上可能还留着 `专有名词-批次-*`（该机制已按用户口径取消），这里一并跳过，
    保证去重键不会被历史标签带偏。
    """
    for t in tags or []:
        if t == TAG_ROOT or t in CP.CATEGORIES:
            continue
        if t.startswith('专有名词-批次-'):
            continue
        return t
    return ''


def card_key(word, work_tag):
    """去重键：`(归一化词形, 出处标签)` —— **建卡、校验、写库、查重共用这一个**。

    2026-10-22 的重复建卡事故就是这里分叉造成的：`existing_keys()` 用「出处标签」做键，
    而 `write_cards()` 还在用「裸作品名」做键 → 键永远对不上，重跑一次就多出 43 张
    （Index 44–86 全是重复卡）。所以口径收敛到这一个函数。
    """
    return (norm_word(word or ''), tag_safe(work_tag or ''))


def existing_keys():
    """目标牌组里已有的 `(归一化词形, 出处标签)` —— 幂等写入的判据。"""
    ids = AK.find_notes('deck:"%s"' % DECK)
    out = {}
    for n in AK.notes_info(ids) if ids else []:
        f = n['fields']
        key = card_key(f.get('Word', {}).get('value', ''),
                       work_tag_from_tags(n.get('tags') or []))
        if key[0]:
            out[key] = int(n['noteId'])
    return out


def _mined_words():
    """第三个词汇牌组（素材生词）里已有的词 → {归一化词形: 原词}。

    判据是「已经在词汇卡组里就不收专名卡」——素材生词也是词汇卡组，
    `ゴンドラ` 这种已经挖成生词卡的不该再收一张专名卡（2026-10-22 实测踩到）。
    """
    ids = AK.find_notes('deck:"%s"' % JD.DECK_MINED)
    out = {}
    for n in AK.notes_info(ids) if ids else []:
        w = n['fields'].get('Word', {}).get('value', '')
        k = P.norm(w)
        if k:
            out.setdefault(k, w)
    return out


_KNOWN = None


def known_sets():
    """(canonical, variant2c, heads, mined_words) —— 进程内只建一次。"""
    global _KNOWN
    if _KNOWN is None:
        canonical, variant2c, heads = M.build_index()
        _KNOWN = (canonical, variant2c, heads, _mined_words())
    return _KNOWN


def known_hit(word, canonical, variant2c):
    """「这个词已经在词汇牌组里」→ 命中的词典形；否则 None。

    **只有含汉字的词才查变体表/活用反推**（与 `mine.hit_inflection` 同一取舍）：
    变体表为了「卡片写片假名、字幕写平假名」也做了 kata2hira（デモ→でも），
    拿它匹配纯假名名字会把 `アンナ`（人名）误判成 `あんな`（那样）——
    2026-10-22 实测踩到。纯假名只认精确命中。
    """
    key = P.norm(word).strip('〜～')
    if not key:
        return None
    hit = canonical.get(key)
    if hit:
        return key
    if not KANJI.search(word):
        return None
    return variant2c.get(key) or M.hit_inflection(key, canonical, variant2c)


# ============================================================================
# scan
# ============================================================================
KATA_ONLY = re.compile(r'^[\u30a1-\u30f6\u30fc]+$')
KANJI_ONLY = re.compile(r'^[\u4e00-\u9fff\u3400-\u4dbf]+$')
KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')

#: 敬称/呼びかけの尾 —— `アイちゃん` 要收成 `アイ`（词条不是称呼）
HONORIFIC = re.compile(r'(ちゃん|さん|くん|君|様|さま|殿|先生|先輩|後輩|氏)$')


def strip_honorific(w):
    """去掉名字后面的敬称（`アイちゃん`→`アイ`、`晃さん`→`晃`）。

    `アリア社長` 这种「职务是名字的一部分」不在替换表里，不会被动到。
    去掉后词干为空（整词就是敬称）就保留原样。
    """
    if not w:
        return w
    m = HONORIFIC.search(w)
    if not m:
        return w
    stem = w[:m.start()]
    return stem or w


def name_like(w):
    """残差像不像一个名字：纯片假名 ≥3 字，或纯汉字 ≥2 字（`漕ぐ`/`訪ね` 排除）。"""
    if not w:
        return False
    if KATA_ONLY.match(w):
        return len(w) >= 3
    if KANJI_ONLY.match(w):
        return len(w) >= 2
    return False


def collect_files(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(sorted(os.path.join(p, f) for f in os.listdir(p)
                              if f.lower().endswith(('.srt', '.ass', '.vtt'))))
        elif os.path.isfile(p):
            out.append(p)
        else:
            raise SystemExit('找不到字幕文件/目录：%s' % p)
    if not out:
        raise SystemExit('没有可读的字幕文件')
    return out


def residuals(text, canonical, variant2c, heads):
    """B 路：生词残差（已知词表覆盖之外、形状像名字的片段）。"""
    hints = []
    raw = P.strip_html(text).replace('\u3000', ' ')
    for r in M.extract_residuals(raw, heads):
        rn = P.norm(M.trim_functional(r))
        if not name_like(rn):
            continue
        if next((h for h in M.known_lookups(rn, variant2c, canonical) if h), None):
            continue
        hints.append({'word': rn, 'source': 'residual'})
    return hints


def cmd_scan(a):
    files = collect_files(a.paths)
    work = (a.work or '').strip()
    if not work:
        raise SystemExit('必须用 --work 指定出处（例：--work 水星领航员）')
    if not AK.model_exists(MODEL):
        print('⚠ 笔记类型「%s」还没建（写卡前跑 proper.py model --commit）' % MODEL)

    known = existing_keys()
    canonical, variant2c, heads, mined = known_sets()

    windows, meta = [], []
    for path in files:
        ep = SRT.load_episode(path, work)
        cues = [c for c in ep.speech_cues if c.text.strip()]
        if a.limit:
            cues = cues[:a.limit]
        print('  %s：%d 条台词（%s）' % (os.path.basename(path), len(cues),
                                      episode_of(path, a.episode) or '集数未识别'))
        items = []
        step = max(1, int(a.window))
        for i in range(0, len(cues), step):
            chunk = cues[i:i + step]
            text = '\n'.join(c.text.strip() for c in chunk if c.text.strip())
            if not text:
                continue
            hints = []
            for c in chunk:
                for sp in (c.speakers or []):
                    hints.append({'word': sp, 'source': 'speaker'})
                hints.extend(residuals(c.text, canonical, variant2c, heads))
            items.append({'text': text, 'background': background_for(work, path),
                          'hints': hints})
            meta.append({'path': path, 'episode': episode_of(path, a.episode),
                         'cues': chunk})
        windows.extend(items)

    if not windows:
        raise SystemExit('字幕里没有可用台词')
    print('窗口 %d 段 → 送专名抽取（每请求 %d 段）…' % (len(windows), a.per_request))
    t0 = time.time()
    results, issues = PE.extract_batch(windows, per_request=a.per_request)
    print('抽取完成：%d 段，用时 %.0fs，%d 条问题' % (len(windows), time.time() - t0, len(issues)))
    for why in issues[:10]:
        print('  ⚠ %s' % why)

    cands = {}
    work_tag = resolve_work_tag(work)
    if work_tag != work:
        print('出处标签：%s（继承库里的动画作品标签，不带季度/集数）' % work_tag)
    for wi, names in enumerate(results):
        m = meta[wi]
        for nm in names:
            nm = dict(nm)
            nm['word'] = strip_honorific(nm['word'])
            key = (norm_word(nm['word']), work)
            e = cands.get(key)
            if e is None:
                e = cands[key] = {
                    'word': nm['word'], 'work': work, 'work_tag': work_tag,
                    'count': 0,
                    'sources': [], 'categories_hint': [], 'gloss_hint': '',
                    'reading_hint': '', 'speaker_hit': False, 'occurrences': [],
                }
            e['count'] += 1
            if nm['source'] not in e['sources']:
                e['sources'].append(nm['source'])
            if not e['speaker_hit'] and any(
                    nm['word'] in (c.speakers or []) for c in m['cues']):
                # 行首 `(名前)` 是发话人 → 几乎一定是人物名（机械信号，不靠模型猜）
                e['speaker_hit'] = True
            for c in nm['categories']:
                if c not in e['categories_hint']:
                    e['categories_hint'].append(c)
            e['gloss_hint'] = e['gloss_hint'] or nm['gloss']
            e['reading_hint'] = e['reading_hint'] or nm['reading']
            cue = cue_with(m['cues'], nm['word'])
            if cue is None:
                continue
            if len(e['occurrences']) < MAX_OCCURRENCES:
                e['occurrences'].append({
                    'episode': m['episode'],
                    'speaker': '/'.join(cue.speakers or []),
                    'sentence': '<br>'.join([ln for ln in cue.lines if ln.strip()]),
                    'plain': cue.text.strip(),
                    'work': work,
                    'srt': os.path.basename(m['path']),
                })

    # 判据：已在词汇牌组（core6000 / 考级词汇 / 素材生词）里的不收
    kept, skipped_known, skipped_have, no_occ = {}, [], [], []
    for key, e in cands.items():
        if not e['occurrences']:
            no_occ.append(e['word'])
            continue
        if not a.include_known:
            why = []
            hit = known_hit(e['word'], canonical, variant2c)
            if hit:
                why.append('考级/core6000: %s' % hit)
            mk = P.norm(e['word'])
            if mk in mined:
                why.append('素材生词: %s' % mined[mk])
            if why:
                skipped_known.append((e['word'], '；'.join(why)))
                continue
        if key in known:
            skipped_have.append((e['word'], known[key]))
            continue
        kept[key] = e

    cands = sorted(kept.values(), key=lambda x: (-x['count'], x['word']))
    run = os.path.join(ROOT, run_slug(work, files, a.episode))
    os.makedirs(run, exist_ok=True)
    json.dump(cands, open(os.path.join(run, 'candidates.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    json.dump({'run': os.path.basename(run),
               'created': dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
               'work': work, 'files': [os.path.basename(f) for f in files],
               'episodes': sorted({episode_of(f, a.episode) for f in files} - {''})},
              open(LATEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    write_report(os.path.join(run, 'report.md'), work, files, cands,
                 skipped_known, skipped_have, no_occ, issues, a)

    print()
    print('候选 %d 个 → %s' % (len(cands), os.path.join(run, 'candidates.json')))
    print('  已在词汇牌组、跳过 %d 个%s' % (len(skipped_known),
                                      '（--include-known 可强收）' if skipped_known else ''))
    print('  已在专有牌组（同出处）、跳过 %d 个' % len(skipped_have))
    print('  抽出来但落不回具体台词、丢弃 %d 个' % len(no_occ))
    print('报告：%s' % os.path.join(run, 'report.md'))
    print('下一步：proper.py split --batches N')
    return run


def run_slug(work, files, override=''):
    eps = sorted({episode_of(f, override) for f in files} - {''})
    tail = eps[0] if len(eps) == 1 else ('%s等%d集' % (eps[0], len(eps)) if eps else '全集')
    return slot('%s_%s' % (work, tail))


def background_for(work, path):
    """背景信息：作品 + 集 +（可选）一句话作品背景。

    作品背景手填在 `data/vocab/proper_works.json`：
        {"works": {"水星领航员": "威尼斯风的火星水星城，贡多拉领航员的日常。"}}
    没有就退化成「作品 + 集」，不阻塞。
    """
    bg = ['作品=%s' % work]
    ep_name = episode_of(path)
    if ep_name:
        bg.append(ep_name)
    synopsis = works_synopsis().get(work)
    if synopsis:
        bg.append(synopsis)
    return '；'.join(bg)


_WORKS = None


def works_synopsis():
    global _WORKS
    if _WORKS is None:
        p = os.path.join(WSP.DATA_VOCAB, 'proper_works.json')
        try:
            _WORKS = {k: str(v) for k, v in
                      (json.load(open(p, encoding='utf-8')).get('works') or {}).items()}
        except (OSError, ValueError):
            _WORKS = {}
    return _WORKS


def cue_with(cues, word):
    """名字落回具体台词：第一条包含它的 cue（NFKC 后子串）。"""
    w = unicodedata.normalize('NFKC', word)
    for c in cues:
        if w in unicodedata.normalize('NFKC', c.text):
            return c
    return None


def write_report(path, work, files, cands, skipped_known, skipped_have, no_occ, issues, a):
    lines = ['# 专有名词候选报告：%s' % work, '',
             '- 生成时间：%s' % dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             '- 字幕：%s' % '、'.join(os.path.basename(f) for f in files),
             '- 窗口：%d 条台词/请求；每请求 %d 段；--include-known=%s'
             % (a.window, a.per_request, a.include_known),
             '- 候选 %d 个' % len(cands), '']
    by_cat = {}
    for e in cands:
        for c in (e['categories_hint'] or ['其他']):
            by_cat.setdefault(c, []).append(e['word'])
    lines += ['## 按类别', '']
    for c in CP.CATEGORIES:
        ws = by_cat.get(c) or []
        if ws:
            lines.append('- **%s**（%d）：%s' % (c, len(ws), '、'.join(ws[:24])))
    lines += ['', '## 候选明细', '',
              '| 词 | 次数 | 类别 | 来源 | 首例句 |', '|---|---|---|---|---|']
    for e in cands[:400]:
        lines.append('| %s | %d | %s | %s | %s |' % (
            e['word'], e['count'], '/'.join(e['categories_hint']) or '-',
            '/'.join(e['sources']), (e['occurrences'][0]['plain'][:30] if e['occurrences'] else '')))
    lines += ['', '## 已被词汇牌组收录、跳过（可 --include-known 强收）', '']
    lines += ['- %s ← %s' % (w, h) for w, h in skipped_known] or ['（无）']
    lines += ['', '## 已在专有牌组（同出处）、跳过', '']
    lines += ['- %s（noteId %s）' % (w, nid) for w, nid in skipped_have] or ['（无）']
    lines += ['', '## 抽出来但落不回具体台词、丢弃', '']
    lines += ['- %s' % w for w in no_occ] or ['（无）']
    lines += ['', '## 抽取问题', '']
    lines += ['- %s' % x for x in issues] or ['（无）']
    textio.write_text(path, '\n'.join(lines) + '\n')


# ============================================================================
# split / gen
# ============================================================================
def candidate_payload(c):
    """发给模型的一条候选（与 token 估算共用同一份渲染）。"""
    return {'word': c['word'], 'work': c['work'],
            'categories_hint': c.get('categories_hint') or [],
            'gloss_hint': c.get('gloss_hint') or '',
            'reading_hint': c.get('reading_hint') or '',
            'speaker_hit': bool(c.get('speaker_hit')),
            'occurrences': [{'speaker': o.get('speaker') or '',
                             'sentence': o['plain']} for o in (c.get('occurrences') or [])]}


def cmd_split(a):
    run = resolve_run(getattr(a, 'run', ''))
    cands = load_candidates(run)
    if not cands:
        raise SystemExit('候选为空（scan 一个都没抽到？）')
    gd = gen_dir(run)
    os.makedirs(gd, exist_ok=True)
    size = (len(cands) + a.batches - 1) // a.batches
    manifest = []
    for b in range(a.batches):
        chunk = cands[b * size:(b + 1) * size]
        if not chunk:
            continue
        name = 'input_%02d.json' % (b + 1)
        json.dump(chunk, open(os.path.join(gd, name), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        manifest.append({'batch': b + 1, 'input': name,
                         'output': 'output_%02d.json' % (b + 1), 'count': len(chunk)})
    json.dump(manifest, open(os.path.join(gd, 'manifest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('已切分 %d 批 / %d 个候选（约 %d 个/批）' % (len(manifest), len(cands), size))
    print('下一步：proper.py gen')


PROPER_GEN_INSTRUCTION = '''你是日语词典编辑。输入是一批从字幕里抽出的**专有名词**候选，请为每个候选写出一张收集卡的内容。

【输入】{"word","work","categories_hint","gloss_hint","reading_hint","occurrences":[{"speaker","sentence"}]}
- word：候选词形（脚本用分词器 + 已知词表残差抽出来的，可能是碎片）
- work：它出自哪部作品
- categories_hint / gloss_hint / reading_hint：上一轮抽取给的提示，可以采信也可以改写
- occurrences：它出现的台词（第一条是首例句），speaker 是发话人（可能为空）
- speaker_hit：true 表示这个词形在字幕里做过**行首发话人标签**（`(名前)`）—— 几乎一定是人物名，
  类别里必须有「人名」（脚本也会机械补上）

【输出】只输出一个 JSON 对象，前后不要任何解释或 markdown 围栏：
{"entries":[{"word":"…","reading":"…","categories":["人名"],"meaning":"…","intro":"…","intro_translation":"…","a_note":"…","related":[],"include":true,"reason":""}]}
每一条输入都要有一条对应输出，**顺序与输入一致**。

字段：
- word        ：保留候选写法；候选若是碎片，可**前后补全**成完整专名，但补全后必须逐字出现在 occurrences 的句子里。
                反过来，候选若把**前面的普通词**也粘了进来（例：`くるみパン晃` → `晃`、`水の三大妖精` 是正当的），
                就只保留真正的专名部分。补全/截短之后都必须仍在句子里。
                判断不了就原样回填（脚本会机械核对"word 是否在首例句里"）。
- reading     ：纯平假名（片假名名字也要转成平假名：メリオダス → めりおだす）；不确定留空
- categories  ：1 个或多个，只能取：人名／地名／组织／概念／技能／种族／称号／作品名／其他
                **同时属于几类就写几类**（メリオダス = 人名 + 称号；七つの大罪 = 作品名 + 组织；
                ウンディーネ = 种族 + 称号）。跨类别在专名里很常见。
- meaning     ：一句话中文意思（≤40 字，含出处；例：梅利奥达斯（《七大罪》主角，〈憤怒の罪〉））
- intro       ：**日语定义句**（一句，≤60 字，必须以 。结尾，必须出现本词，不要 HTML、不要振假名）。
                例：メリオダスは「七つの大罪」の主人公で、〈憤怒の罪〉を背負う騎士。
                **作品名只能照抄 background 里给的写法**；background 没给日文名就不要在句子里写作品名。
                不确定的设定/人物关系用保守说法（「作品に登場する人物」），**不要编造**。
- intro_translation：intro 的自然中文翻译（一句）
- a_note      ：两段 HTML（只用 <p> <br> <b> <ruby> <rt>）：
                <p><b>词条：</b>这是什么、在作品里是谁/什么。</p>
                <p><b>出处与背景：</b>作品设定、现实原型、跨作品关联。</p>
                日语汉字必须标 ruby（送假名在 <rt> 外）；**中文汉字绝不标 ruby**；
                **片假名/平假名不需要 ruby**（`ウッディー` 直接写，别给假名包 <ruby>/<rt>）。
- related     ：0..n 个**原型/跨作品出处**（短名，例：["亚瑟王传说"]）；没有就给 []
                **不要放同作品的其他角色/组织/地名**（那不是"关联出处"，是正文内容，写进 a_note）
- include     ：true=确实是值得收集的专有名词；false=碎片/普通名词/误抽
- reason      ：include=false 时必填一句话；include=true 留空字符串

【铁律】
1. a_note 禁止 div/span/style/class、禁止 LaTeX、禁止反斜杠、禁止 $、禁止半角双引号（用「」）、禁止 markdown
2. word / reading / categories / meaning / intro / intro_translation 里不要放任何 HTML 或 ruby
3. intro 是**介绍这个专名**的句子，不是它的台词摘抄；但必须包含 word
4. 作品名/人物关系/设定拿不准时用保守说法，**绝不编造**；**绝不给作品起新名字**
   （作品名只能取自 background 里给的写法，中文名不要硬翻成日语）
5. 判不准是不是真专名时倾向 include=false（宁可漏收，不要掺普通词）'''


def gen_user(group):
    return ('背景（作品名照抄这里的写法）：%s\n' % _background_of(group)
            + json.dumps([candidate_payload(c) for c in group], ensure_ascii=False, indent=1))


def _background_of(group):
    """这批候选的背景信息（作品 + 一句话设定），成卡阶段也要给模型。"""
    works = []
    for c in group:
        w = c.get('work') or ''
        if w and w not in works:
            works.append(w)
    parts = []
    for w in works:
        syn = works_synopsis().get(w)
        parts.append('%s%s' % (w, ('：' + syn) if syn else ''))
    return '；'.join(parts) or '（未提供）'


def gen_request(cfg, LLM, group, feedback=None):
    user = gen_user(group)
    if feedback:
        user += ('\n\n上面这些条目上一次的输出不合格，问题如下，这次只重做这几条（word 照抄）：\n'
                 + feedback)
    msgs = [{'role': 'system', 'content': PROPER_GEN_INSTRUCTION},
            {'role': 'user', 'content': user}]
    obj, res, problems = LLM.call_json(cfg, msgs, require='entries', json_mode=True,
                                       enable_thinking=False, quiet=True,
                                       max_tokens=GEN_MAX_TOKENS)
    got = {}
    if isinstance(obj, dict):
        for item in (obj.get('entries') or []):
            if not isinstance(item, dict):
                continue
            w = P.norm(OUT.as_text(item.get('word')))
            if w:
                got[w] = item
    if problems:
        print('    ⚠️ 回复形状不合格：%s' % '；'.join(problems)[:160], file=sys.stderr)
    return got, res


def judge_proper(group, got):
    """把模型结果按候选配回来，跑一次 check_proper；返回 (合格的, {key: 问题})。"""
    ok, bad = {}, {}
    exact = {P.norm(c['word']) for c in group}
    for c in group:
        key = P.norm(c['word'])
        item = got.get(key)
        if item is None:
            # 模型把碎片补全成完整专名（大納 → 大納言）：允许找"以候选开头"的更长键
            longer = sorted((k for k in got if k.startswith(key) and len(k) > len(key)
                             and k not in exact), key=len)
            if longer:
                item = got[longer[-1]]
        if item is None:
            bad[key] = '模型没有返回这条候选'
            continue
        raw_w = item.get('word')
        entry = {
            'word': OUT.as_text(raw_w) or c['word'],
            'reading': OUT.as_text(item.get('reading')),
            'categories': item.get('categories'),
            'meaning': OUT.as_text(item.get('meaning')),
            'intro': OUT.as_text(item.get('intro')),
            'intro_translation': OUT.as_text(item.get('intro_translation')),
            'a_note': OUT.as_text(item.get('a_note')),
            'related': item.get('related') or [],
            'include': OUT.as_bool(item.get('include')),
            'reason': OUT.as_text(item.get('reason')),
        }
        try:
            hard, _soft = CP.check(entry)
        except Exception as exc:
            bad[key] = '校验异常：%s: %s' % (type(exc).__name__, exc)
            continue
        if hard:
            bad[key] = '；'.join(hard)
            continue
        if entry['include']:
            # 行首发话人标签 → 机械补「人名」（模型容易把它误判成技能/招式）
            cats = [OUT.as_text(x) for x in (entry.get('categories') or [])]
            if c.get('speaker_hit') and '人名' not in cats:
                cats.insert(0, '人名')
            entry['categories'] = cats or ['其他']
            # word 必须真的出现在某条台词里（模型自己改写过词形就会在这里被拦下）
            sents = [o.get('plain') or o.get('sentence') or ''
                     for o in (c.get('occurrences') or [])]
            plain = unicodedata.normalize('NFKC', '\n'.join(sents))
            if unicodedata.normalize('NFKC', entry['word']) not in plain:
                bad[key] = ('word「%s」不在它自己的台词里（补全后必须仍是原句的子串）'
                            % entry['word'])
                continue
        ok[key] = entry
    return ok, bad


FAILED = 'failed.json'
PLACEHOLDER = '模型未能给出合格判定，留待人工'


def output_matches_input(m, gd):
    """这一批产出是不是当前输入的产出（断点续跑判据，口径同 mine.py）。"""
    ip, op = os.path.join(gd, m['input']), os.path.join(gd, m['output'])
    if not os.path.exists(op):
        return False
    try:
        src = json.load(open(ip, encoding='utf-8'))
        got = json.load(open(op, encoding='utf-8'))
    except (ValueError, TypeError):
        return False
    if len(src) != len(got):
        return False
    for a, b in zip(src, got):
        w1, w2 = P.norm(a.get('word') or ''), P.norm(b.get('word') or '')
        if not w2 or not (w1 == w2 or w1 in w2 or w2 in w1):
            return False
    return True


def cmd_gen(a):
    run = resolve_run(getattr(a, 'run', ''))
    gd = gen_dir(run)
    mp = os.path.join(gd, 'manifest.json')
    if not os.path.exists(mp):
        raise SystemExit('没有 manifest.json，先跑：proper.py split --batches N')
    import local_llm as LLM
    cfg = LLM.load_config()
    manifest = json.load(open(mp, encoding='utf-8'))
    if a.fix_failed:
        return fix_failed(run, a, cfg, LLM)

    print('本地模型：%s @ %s（每请求最多 %d 条）' % (cfg['model'], cfg['base_url'], a.per_request))
    todo = []
    for m in manifest:
        if a.force or not os.path.exists(os.path.join(gd, m['output'])):
            todo.append(m)
        elif output_matches_input(m, gd):
            print('  批%02d 已存在且与输入同源 → 跳过（--force 重做）' % m['batch'])
        else:
            print('  ⚠ 批%02d 存在但与输入对不上 → 重做' % m['batch'])
            todo.append(m)
    if not todo:
        print('没有要判定的批次。下一步：proper.py verify')
        return

    t0 = time.time()
    tp = tc = req = 0
    failed = []
    for m in todo:
        cands = json.load(open(os.path.join(gd, m['input']), encoding='utf-8'))
        done, bad = {}, {}
        pending, rounds = list(cands), 0
        while pending:
            fb = []
            size = a.per_request if rounds == 0 else 1
            for group in P.fit_groups(pending, size, gen_user, cfg, LLM):
                res = None
                try:
                    got, res = gen_request(cfg, LLM, group,
                                           feedback='\n'.join(fb) if fb else None)
                    req += 1
                    tp += res.prompt_tokens
                    tc += res.completion_tokens
                    ok, problems = judge_proper(group, got)
                except Exception as exc:
                    req += 1
                    print('  ⚠ 批%02d 一组出意外：%s: %s → 这 %d 条按未判定处理'
                          % (m['batch'], type(exc).__name__, exc, len(group)))
                    ok, problems = {}, {P.norm(c['word']): '%s: %s' % (type(exc).__name__, exc)
                                        for c in group}
                done.update(ok)
                bad.update(problems)
                for k, why in problems.items():
                    fb.append('- %s：%s' % (k, why[:200]))
                if problems and res is not None:
                    dump_raw(run, m['batch'], rounds, group, res)
            if not bad or rounds >= a.retries:
                break
            rounds += 1
            pending = [c for c in cands if P.norm(c['word']) in bad]
            bad = {}
            print('  批%02d 重问第 %d 轮（逐条）：%d 条' % (m['batch'], rounds, len(pending)))

        out = []
        for c in cands:
            key = P.norm(c['word'])
            out.append(done.get(key) or {
                'word': c['word'], 'reading': '', 'categories': [], 'meaning': '',
                'intro': '', 'intro_translation': '', 'a_note': '', 'related': [],
                'include': False, 'reason': PLACEHOLDER})
        json.dump(out, open(os.path.join(gd, m['output']), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        n_inc = sum(1 for e in out if e.get('include'))
        print('  批%02d 写出 %s：收录 %d / 排除 %d'
              % (m['batch'], m['output'], n_inc, len(out) - n_inc))
        for c in cands:
            key = P.norm(c['word'])
            if key in bad:
                failed.append(dict(c, batch=m['batch'], problems=bad[key]))
    print('判定结束：%d 次请求，prompt %d + completion %d tokens，耗时 %.0fs'
          % (req, tp, tc, time.time() - t0))
    if failed:
        save_failed(run, failed)
        print('有 %d 条没判出来 → %s' % (len(failed), os.path.join(gd, FAILED)))
        print('下一步：proper.py gen --fix-failed，或让强模型出 fix_output.json 后 merge-fix')
    else:
        p = os.path.join(gd, FAILED)
        if os.path.exists(p):
            os.remove(p)
        print('全部一次判定通过。下一步：proper.py verify')


RAW_DIR = 'raw'


def dump_raw(run, batch, rounds, group, res):
    body = ('# 候选：%s\n# 轮次：%d\n\n' % ('、'.join(c['word'] for c in group), rounds)
            + OUT.raw_text(res))
    p = OUT.dump_raw(os.path.join(gen_dir(run), RAW_DIR),
                     'batch_%s_r%d' % (('%02d' % batch) if isinstance(batch, int) else batch,
                                       rounds),
                     body, header='专有名词 gen：这一组没判出来')
    if p:
        print('    模型原始回复已存：%s' % p)


def save_failed(run, entries):
    doc = {'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'note': '这些候选本地模型重试后仍未通过 check_proper；'
                   '用 proper.py merge-fix --file <产出> 并回，或人工处理',
           'candidates': entries}
    json.dump(doc, open(os.path.join(gen_dir(run), FAILED), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    return doc


def patch_outputs(run, done):
    """把 {归一化 word: 条目} 并回对应批次产出（精确命中优先，前缀回退只认占位条目）。"""
    if not done:
        return 0
    gd = gen_dir(run)
    manifest = json.load(open(os.path.join(gd, 'manifest.json'), encoding='utf-8'))
    n = 0
    used = {}
    for m in manifest:
        p = os.path.join(gd, m['output'])
        if not os.path.exists(p):
            continue
        out = json.load(open(p, encoding='utf-8'))
        exact = {P.norm(r.get('word') or '') for r in out}
        changed = False
        for i, rec in enumerate(out):
            key = P.norm(rec.get('word') or '')
            v = done.get(key)
            if v is None and (not rec.get('include')
                              and PLACEHOLDER in (rec.get('reason') or '')):
                longer = sorted((k for k in done if k.startswith(key) and len(k) > len(key)
                                 and k not in exact), key=len)
                if longer:
                    v = done[longer[-1]]
            if not v:
                continue
            vk = P.norm(v.get('word') or '')
            if vk in used:
                print('  ⚠ %s 已改过 %s，又命中 %s → 跳过' % (vk, used[vk], m['output']))
                continue
            out[i] = v
            used[vk] = '%s 第 %d 条' % (m['output'], i + 1)
            changed = True
            n += 1
            print('  并回 %s ← %s' % (vk, used[vk]))
        if changed:
            json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    missing = sorted(k for k in done if k not in used)
    if missing:
        print('  ⚠ %d 条 fix 没落到任何记录上：%s' % (len(missing), '、'.join(missing)))
    return n


def fix_failed(run, a, cfg, LLM):
    p = os.path.join(gen_dir(run), FAILED)
    if not os.path.exists(p):
        raise SystemExit('没有 failed.json（本地模型没有遗留失败项）')
    doc = json.load(open(p, encoding='utf-8'))
    cands = doc.get('candidates') or []
    if not cands:
        print('failed.json 是空的。')
        return
    print('重跑 %d 条（逐条请求）' % len(cands))
    done, bad = {}, {}
    pending, rounds = list(cands), 0
    while pending:
        fb = []
        for group in P.fit_groups(pending, a.per_request if rounds == 0 else 1,
                                  gen_user, cfg, LLM):
            try:
                got, _res = gen_request(cfg, LLM, group,
                                        feedback='\n'.join(fb) if fb else None)
                ok, problems = judge_proper(group, got)
            except Exception as exc:
                ok, problems = {}, {P.norm(c['word']): '%s: %s' % (type(exc).__name__, exc)
                                    for c in group}
            done.update(ok)
            bad.update(problems)
            for k, why in problems.items():
                fb.append('- %s：%s' % (k, why[:200]))
        if not bad or rounds >= a.retries:
            break
        rounds += 1
        pending = [c for c in cands if P.norm(c['word']) in bad]
        bad = {}
        print('  重问第 %d 轮：%d 条' % (rounds, len(pending)))
    patch_outputs(run, done)
    remain = [dict(c, problems=bad.get(P.norm(c['word']), '')) for c in cands
              if P.norm(c['word']) in bad]
    save_failed(run, remain)
    print('本轮修好 %d 条，仍剩 %d 条' % (len(done), len(remain)))


def cmd_merge_fix(a):
    run = resolve_run(getattr(a, 'run', ''))
    path = a.file if os.path.isabs(a.file) else os.path.join(gen_dir(run), a.file)
    if not os.path.exists(path):
        raise SystemExit('找不到 %s' % path)
    merge = json.load(open(path, encoding='utf-8'))
    if isinstance(merge, dict):
        merge = merge.get('entries') or merge.get('outputs') or []
    ok, bad = {}, {}
    for item in merge:
        if not isinstance(item, dict):
            continue
        w = P.norm(item.get('word') or '')
        if not w:
            continue
        entry = {'word': item.get('word') or '', 'reading': item.get('reading') or '',
                 'categories': item.get('categories') or [],
                 'meaning': item.get('meaning') or '', 'intro': item.get('intro') or '',
                 'intro_translation': item.get('intro_translation') or '',
                 'a_note': item.get('a_note') or '', 'related': item.get('related') or [],
                 'include': OUT.as_bool(item.get('include')),
                 'reason': item.get('reason') or ''}
        hard, _soft = CP.check(entry)
        if hard:
            bad[w] = '；'.join(hard)
        else:
            ok[w] = entry
    n = patch_outputs(run, ok)
    print('并入 %d 条（不合格 %d 条）' % (n, len(bad)))
    for w, why in sorted(bad.items())[:10]:
        print('  ✗ %s %s' % (w, why[:160]))
    print('下一步：proper.py verify')


# ============================================================================
# verify：把产出拼成卡片载荷（唯一的校验点）
# ============================================================================
def load_outputs(run):
    gd = gen_dir(run)
    manifest_p = os.path.join(gd, 'manifest.json')
    if not os.path.exists(manifest_p):
        raise SystemExit('没有 manifest.json，先跑 proper.py split')
    manifest = json.load(open(manifest_p, encoding='utf-8'))
    merged, missing = [], []
    for m in manifest:
        p = os.path.join(gd, m['output'])
        if not os.path.exists(p):
            missing.append(m['output'])
            continue
        merged.extend(json.load(open(p, encoding='utf-8')))
    if missing:
        raise SystemExit('尚未生成：%s' % ', '.join(missing))
    return merged


_LEX = None


RUBY_RE = re.compile(r'<ruby>(.*?)<rt>(.*?)</rt></ruby>', re.S)
TAG_RE = re.compile(r'<[^>]+>')
#: 把 `Intro` 拆成「可见片段 → 读音」的单元：ruby 用 rt，普通文本用自身
UNIT_RE = re.compile(r'<ruby>(?P<base>.*?)<rt>(?P<rt>.*?)</rt></ruby>|(?P<text>[^<]+)', re.S)


def _intro_spans(html):
    """把 `Intro` 拆成 [(a, b, 可见文字, 读音, 是否 ruby)]，a/b 是**可见文本**下标。

    ruby 段：可见文字 = 基底、读音 = rt；普通文本段：两者都是原文。
    """
    spans, pos = [], 0
    for m in UNIT_RE.finditer(html or ''):
        if m.group('base') is not None:
            vis = TAG_RE.sub('', m.group('base'))
            rd, is_ruby = m.group('rt').strip(), True
        else:
            vis = m.group('text')
            rd, is_ruby = vis, False
        spans.append((pos, pos + len(vis), vis, rd, is_ruby))
        pos += len(vis)
    return spans


def reading_from_intro(word, html):
    """从 `Intro` 的振假名反推整词读音（覆盖模型给的 `Reading`）。

    两个来源独立：`Reading` 是模型写的，`Intro` 的 ruby 是 `ruby_engine` 用
    Sudachi + 人工例外渲染的。实测模型把 `藍華` 读成 `らんか`、`火の番人` 读成
    `かんじん`，而同一张卡的 ruby 写的是 `あいか` / `ひのばんにん` ——
    卡面自相矛盾、以及 TTS 念错，都是从这儿来的。

    做法：在 `Intro` 的可见文本里找整词；把覆盖它的片段逐段取读音
    （ruby 段取 rt、普通文字取自身），拼起来转平假名。
    词被切在某个 ruby 段中间（片段只标了半个词）就换下一个出现位置，找不到就放弃。
    """
    spans = _intro_spans(html)
    visible = ''.join(s[2] for s in spans)
    start = visible.find(word)
    while start >= 0:
        end = start + len(word)
        out, ok = [], True
        for a, b, _vis, rd, is_ruby in spans:
            if b <= start or a >= end:
                continue
            if is_ruby:
                if a < start or b > end:        # 词被这段 ruby 切开 → 这次不算
                    ok = False
                    break
                out.append(rd)
            else:
                out.append(visible[max(a, start):min(b, end)])
        if ok and out:
            return to_hiragana(''.join(out))
        start = visible.find(word, start + 1)
    return ''


def render_intro(text):
    """日语介绍句 → 带 <ruby> 的 HTML（确定性；不靠模型写 HTML）。"""
    global _LEX
    s = unicodedata.normalize('NFKC', (text or '').strip())
    if not s:
        return ''
    try:
        if _LEX is None:
            # use_deck=False：只要「人工例外表 + 字幕注音 + Sudachi」，不读 1 万张卡
            _LEX = RE.Lexicon.build(use_deck=False)
        html = RE.render(s, _LEX)
    except Exception as exc:
        print('  ⚠ 振假名渲染失败（%s: %s）→ 按纯文本写入' % (type(exc).__name__, exc))
        return s
    if KANJI.search(RE.strip_text(html)) and '<ruby>' not in html:
        print('  ⚠ 介绍句含汉字但没有渲染出振假名 → 按纯文本写入：%s' % s[:24])
        return s
    return html


def sentence_for_card(c, entry):
    """取首例句：第一条真正包含该词的台词（找不到就用第一条）。"""
    w = unicodedata.normalize('NFKC', entry['word'])
    for o in c.get('occurrences') or []:
        if w in unicodedata.normalize('NFKC', o.get('plain') or ''):
            return o
    return (c.get('occurrences') or [{}])[0]


def build_cards(entries, cands, include_known=False):
    """把判定产出 + 候选拼成待写载荷，逐条跑 check_proper.check_card。"""
    by_key = {(norm_word(c['word']), tag_safe(c['work'])): c for c in cands}
    canonical, variant2c, _heads, mined = known_sets()
    have = existing_keys()
    cards, bad, known, already, merged = [], [], [], [], []
    seen = set()
    for e in entries:
        key = (norm_word(e.get('word') or ''), '')
        if not e.get('include'):
            continue
        # 找出这条产出对应哪个候选：先按归一化词形，再按前缀（模型补全），
        # 最后按「候选包含产出词」（模型把粘连的普通词截掉了，例：くるみパン晃 → 晃）
        c = None
        for (k, w), cand in by_key.items():
            if k == key[0]:
                c = cand
                break
        if c is None:
            # 模型把碎片补全成完整专名（大納 → 大納言）：候选必须是产出词的前缀
            for (k, _w), cand in sorted(by_key.items(), key=lambda kv: -len(kv[0][0])):
                if key[0].startswith(k):
                    c = cand
                    break
        if c is None:
            for (_k, _w), cand in sorted(by_key.items(), key=lambda kv: len(kv[0][0])):
                if key[0] and key[0] in norm_word(cand['word']):
                    c = cand
                    break
        if c is None:
            bad.append((e.get('word'), ['找不到对应的候选（产出与输入对不上）']))
            continue
        wtag = c.get('work_tag') or resolve_work_tag(c['work'])
        dkey = card_key(e['word'], wtag)
        if dkey in seen:
            # 两条候选收敛成同一个词（碎片 + 完整形）→ 留第一张，静默跳过
            merged.append(e['word'])
            continue
        seen.add(dkey)
        if dkey in have:
            # 已存在只记账，**不在这里丢**：verified.json 是这一趟的完整记录，
            # 真正跳过发生在 write（那时才会重新查一遍库）。否则重跑 verify 会把它清空。
            already.append((e['word'], have[dkey]))
        if not include_known:
            hit = known_hit(e['word'], canonical, variant2c)
            if hit:
                known.append((e['word'], '考级/core6000: %s' % hit))
                continue
            mk = P.norm(e['word'])
            if mk in mined:
                known.append((e['word'], '素材生词: %s' % mined[mk]))
                continue
        occ = sentence_for_card(c, e)
        sentence = occ.get('sentence') or occ.get('plain') or ''
        card = dict(e)
        card['intro_html'] = render_intro(e.get('intro') or '')
        # 读音以卡面 ruby 为准（同一张卡里 Reading 与 ruby 不一致是最难看的错）
        derived = reading_from_intro(e['word'], card['intro_html'])
        if derived:
            old = to_hiragana((e.get('reading') or '').strip())
            if old and old != derived:
                # a_note 里常常写着「藍華（らんか）」—— 读音被覆盖后要同步改掉
                for a, b in (('（%s）' % old, '（%s）' % derived),
                             ('(%s)' % old, '（%s）' % derived)):
                    card['a_note'] = (card.get('a_note') or '').replace(a, b)
            card['reading'] = derived
        card['categories_text'] = ' / '.join(e.get('categories') or [])
        card['source_text'] = '出自「%s」%s｜原句：%s' % (
            c['work'], occ.get('episode') or '', (occ.get('plain') or '')[:80])
        card['tags'] = build_tags(e.get('categories'), wtag)
        card['work'] = c['work']
        card['work_tag'] = wtag
        card['sentence'] = sentence
        rel = [tag_safe(x) for x in (e.get('related') or []) if tag_safe(x)]
        if rel:
            card['a_note'] = (e.get('a_note') or '').rstrip() + (
                '<p><b>关联：</b>%s</p>' % '、'.join(rel))
        hard, soft = CP.check_card(card)
        if hard:
            bad.append((e['word'], hard))
            continue
        cards.append(card)
    return cards, bad, known, already, merged


def cmd_verify(a):
    run = resolve_run(getattr(a, 'run', ''))
    cands = load_candidates(run)
    entries = load_outputs(run)
    cards, bad, known, already, merged = build_cards(entries, cands, a.include_known)
    n_inc = sum(1 for e in entries if e.get('include'))
    print('产出 %d 条（收录 %d / 排除 %d）' % (len(entries), n_inc, len(entries) - n_inc))
    print('  字段不合格 %d' % len(bad))
    for w, hard in bad[:20]:
        print('    ✗ %s  %s' % (w, '; '.join(hard)[:200]))
    print('  已在词汇牌组（应剔除） %d%s' % (len(known),
                                       '（--include-known 可强收）' if known else ''))
    for w, hit in known[:20]:
        print('    ⊘ %s  ← %s' % (w, hit))
    print('  已在专有牌组（同出处，write 会跳过） %d' % len(already))
    if merged:
        print('  多条候选收敛成同一个词、合并 %d：%s'
              % (len(merged), '、'.join(sorted(set(merged))[:12])))
    if bad:
        print()
        print('存在问题，未通过。修掉上面带 ✗ 的条目后重跑（或把问题条目改成 include=false）。')
        raise SystemExit(1)
    p = os.path.join(gen_dir(run), 'verified.json')
    json.dump(cards, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print()
    print('全部通过。载荷 %d 张（已写入 %s）' % (len(cards), p))
    return cards


def verified_fresh(run):
    p = os.path.join(gen_dir(run), 'verified.json')
    if not os.path.exists(p):
        return False
    t = os.path.getmtime(p)
    gd = gen_dir(run)
    try:
        manifest = json.load(open(os.path.join(gd, 'manifest.json'), encoding='utf-8'))
    except (OSError, ValueError):
        return False
    files = [os.path.join(gd, 'manifest.json'), os.path.join(run, 'candidates.json')]
    for m in manifest:
        files += [os.path.join(gd, m['input']), os.path.join(gd, m['output'])]
    return all(os.path.exists(f) and os.path.getmtime(f) <= t for f in files)


# ============================================================================
# write
# ============================================================================
def card_fields(card, index):
    return {
        'Index': str(index),
        'Word': card['word'],
        'Reading': card['reading'],
        'Meaning': card['meaning'],
        'Categories': card['categories_text'],
        'Intro': card['intro_html'],
        'Intro Translation': card['intro_translation'],
        'AINote': card['a_note'],
        'Source': card['source_text'],
    }


def write_cards(cards, commit, run=None):
    if not cards:
        print('没有可写入的卡片。')
        return []
    if not commit:
        print('将创建 %d 张笔记（演练，未写库）：' % len(cards))
        for c in cards:
            print('   %-14s [%s] %s' % (c['word'], c['categories_text'], c['meaning'][:30]))
            print('        标签：%s' % '  '.join(c['tags']))
        out = os.path.join(gen_dir(run), 'dryrun_notes.json') if run else None
        if out:
            json.dump(cards, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            print('载荷已存：%s' % out)
        print('确认无误后加 --commit 重跑。')
        return cards

    ensure_model(commit=True)
    AK.create_deck(DECK)
    # ★ 写库这一刻再查一次「目标牌组里有没有同 (词形, 出处) 的卡」。
    #   不能只靠 verify 那一道：verified.json 可能被复用（几个小时内重跑 write 很常见），
    #   而 verify 之后的写入已经让库里有了这些卡 —— 少了这道闸，重跑就是重复建卡。
    have = existing_keys()
    dupes = []
    for c in cards:
        wtag = c.get('work_tag') or resolve_work_tag(c.get('work') or '')
        if card_key(c['word'], wtag) in have:
            dupes.append(c)
    if dupes:
        print('已存在、跳过 %d 张：%s' % (len(dupes), '、'.join(c['word'] for c in dupes[:12])))
        cards = [c for c in cards if c not in dupes]
    if not cards:
        print('没有需要新建的卡片（全部已存在）。')
        return []
    start = M.next_index(MODEL)
    print('Index 序号：%d…%d' % (start, start + len(cards) - 1))
    notes = []
    for i, c in enumerate(cards):
        notes.append(AK.new_note(DECK, MODEL, card_fields(c, start + i),
                                 tags=c['tags'], allow_duplicate=False,
                                 duplicate_scope='collection'))
    print('写入中…（addNotes 批量提交 %d 条）' % len(notes))
    t0 = time.time()
    res = AK.add_notes(notes)
    ok = [(cards[i], int(r)) for i, r in enumerate(res) if r]
    null = [cards[i]['word'] for i, r in enumerate(res) if not r]
    print('  addNotes 成功 %d / %d  (%.1fs)' % (len(ok), len(notes), time.time() - t0))
    for w in null[:20]:
        print('    ✗ 被拒（多半是查重）：%s' % w)

    ids = [nid for _c, nid in ok]
    back = AK.notes_map(ids) if ids else {}
    mism = []
    for c, nid in ok:
        n = back.get(nid)
        if n is None:
            mism.append((c['word'], 'noteId %s 查不到' % nid))
            continue
        raw_idx = str((n['fields'].get('Index') or {}).get('value', '') or '').strip()
        if not raw_idx.isdigit():
            mism.append((c['word'], 'Index'))
            continue
        want = card_fields(c, int(raw_idx))
        for f, v in want.items():
            if n['fields'].get(f, {}).get('value') != v:
                mism.append((c['word'], f))
    print('  回读逐字一致：%d / %d' % (len(ok) - len({w for w, _ in mism}), len(ok)))
    for w, f in mism[:20]:
        print('   ✗ %-14s %s' % (w, f))
    print()
    print('已入库 %d 张到 %s' % (len(ok), DECK))
    tags = sorted({t for c, _nid in ok for t in c.get('tags') or []})
    print('回滚：浏览器搜 deck:"%s" 再按出处标签收窄 → 全选删除' % DECK)
    if tags:
        print('      本次的标签：%s' % '、'.join(tags))
    print('      （没有批次标签；要按批回滚就用浏览器 `Added` 列排序，或按出处标签整批删）')
    print('下一步：proper.py audio（读法音频）')
    new_per_day = AK.deck_new_per_day(DECK)
    print('⚠ 该牌组当前 new/day = %s（脚本没有改它）。要让它不进学习队列，二选一：' % new_per_day)
    print('   ① Anki 牌组选项 → 这个牌组的预设 → 新卡/天 = 0')
    print('   ② 浏览器搜 deck:"%s" 全选 → 挂起' % DECK)
    return ok


def cmd_write(a):
    run = resolve_run(getattr(a, 'run', ''))
    if verified_fresh(run):
        p = os.path.join(gen_dir(run), 'verified.json')
        print('复用 %s（比全部产出都新，不再校验一遍）' % p)
        cards = json.load(open(p, encoding='utf-8'))
    else:
        cards = cmd_verify(argparse.Namespace(run=getattr(a, 'run', ''),
                                             include_known=getattr(a, 'include_known', False)))
    write_cards(cards, a.commit, run)
    if a.commit and cards:
        p = os.path.join(gen_dir(run), 'written.json')
        json.dump([{'word': c['word'], 'tags': c['tags']} for c in cards],
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ============================================================================
# audio
# ============================================================================
def cmd_audio(a):
    import edge_tts_min as TTS
    import mine_audio as MA
    q = 'deck:"%s"' % DECK
    if a.tag:
        q += ' tag:"%s"' % a.tag
    ids = AK.find_notes(q)
    if not ids:
        print('牌组里没有卡（%s）' % q)
        return
    media = set(AK.media_names('*'))
    todo, bad = [], []
    for n in AK.notes_info(ids):
        f = n['fields']
        if MA.sounds_of(f.get('Word Audio', {}).get('value', '')) and not a.force:
            continue
        w = f.get('Word', {}).get('value', '')
        r = f.get('Reading', {}).get('value', '')
        if not re.fullmatch(r'[\u3040-\u309f\u30a0-\u30ff\u30fc\u30fbー]+', r or ''):
            bad.append((w, 'Reading 不是纯假名：%r' % r))
            continue
        todo.append({'noteId': int(n['noteId']), 'word': w, 'reading': r})
    print('范围：%s' % q)
    print('待配音 %d 张；跳过（已有音频）%d；Reading 不合格 %d'
          % (len(todo), len(ids) - len(todo) - len(bad), len(bad)))
    for w, why in bad[:10]:
        print('  ⚠ %-14s %s' % (w, why))
    if not todo:
        return

    rows = []
    for r in todo:
        name = 'proper-%s-%s.mp3' % (MA.safe_token(r['word']),
                                     hashlib.sha1(r['reading'].encode('utf-8'))
                                     .hexdigest()[:8])
        rows.append(dict(r, name=MA.media_name(name)))

    if not a.commit:
        print()
        print('%-14s %-12s %s' % ('词', '读音', '媒体文件'))
        for r in rows:
            print('%-14s %-12s %s' % (r['word'], r['reading'], r['name']))
        print()
        print('演练结束，未写任何数据。确认后加 --commit。')
        return

    os.makedirs(WSP.OUT_AUDIO, exist_ok=True)
    ok = 0
    for i, r in enumerate(rows, 1):
        try:
            data = TTS.synth(r['reading'], voice=VOICE)
            if not data:
                raise RuntimeError('TTS 返回空音频')
            path = os.path.join(WSP.OUT_AUDIO, r['name'])
            with open(path, 'wb') as fh:
                fh.write(data)
            AK.store_media_file(r['name'], path=path)
            AK.update_note_fields(r['noteId'], {'Word Audio': '[sound:%s]' % r['name']})
            ok += 1
            print('  [%d/%d] %-14s → %s (%d KB)'
                  % (i, len(rows), r['word'], r['name'], len(data) // 1024))
        except Exception as exc:
            print('  ✗ %-14s %s: %s' % (r['word'], type(exc).__name__, exc))
    print('已配 %d / %d 张' % (ok, len(rows)))
    bad_read = AK.verify_note_fields([r['noteId'] for r in rows],
                                     {r['noteId']: {'Word Audio': '[sound:%s]' % r['name']}
                                      for r in rows})
    print('回读：%d 张有字段差异' % len(bad_read))
    for nid, fields in list(bad_read.items())[:10]:
        print('  ✗ noteId %s %s' % (nid, fields))


# ============================================================================
# add：手动补一张（不在当前字幕里）
# ============================================================================
def cmd_add(a):
    import local_llm as LLM
    cfg = LLM.load_config()
    src = a.source.strip()
    if not src:
        raise SystemExit('--source 必填（出处：作品名 / 动画::作品名 / 亚瑟王传说 / 现实 …）')
    # 出处标签：显式写了 `动画::…` 就用它；裸作品名按库里标签决定（动画作品继承两层）
    wtag = resolve_work_tag(src)
    work = wtag.split('::')[-1] if '::' in wtag else wtag
    text = (a.text or a.word).strip()
    cand = {
        'word': a.word.strip(), 'work': work, 'work_tag': wtag,
        'count': 1, 'sources': ['manual'],
        'categories_hint': [c for c in (a.categories or '').replace('，', ',').split(',') if c],
        'gloss_hint': '', 'reading_hint': a.reading or '',
        'occurrences': [{'episode': '', 'speaker': '', 'sentence': text,
                         'plain': text, 'work': work, 'srt': '(手动)'}],
    }
    group = [cand]
    print('手动补卡：%s（出处 %s → 标签 %s）' % (cand['word'], work, wtag))
    got, _res = gen_request(cfg, LLM, group)
    ok, bad = judge_proper(group, got)
    if not ok:
        print('模型没给出合格产出：')
        for k, why in bad.items():
            print('  ✗ %s %s' % (k, why[:200]))
        return 1
    entry = list(ok.values())[0]
    if not entry.get('include'):
        print('模型判为「不收」：%s' % (entry.get('reason') or '（无理由）'))
        print('若确实要收，请提供元素更足的 --text（词必须出现在里面）。')
        return 1
    if a.categories:
        entry['categories'] = [c for c in a.categories.replace('，', ',').split(',') if c]
    cards, cbad, _known, already, _merged = build_cards([entry], group, include_known=True)
    if cbad:
        for w, hard in cbad:
            print('  ✗ %s %s' % (w, '; '.join(hard)[:200]))
        return 1
    if already:
        print('这张卡已经存在（同词同出处）：%s' % (already[0][1],))
        return 0
    write_cards(cards, a.commit, None)
    return 0


# ============================================================================
# main
# ============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description='专有名词收集（3-专有词汇，不进学习队列）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('model', help='建/校验笔记类型 Japanese Proper Noun')
    p.add_argument('--check', action='store_true', default=True)
    p.add_argument('--commit', action='store_true')
    p.add_argument('--force-templates', action='store_true')
    p.add_argument('--delete', action='store_true')
    p.set_defaults(func=cmd_model)

    p = sub.add_parser('scan', help='只读：字幕 → 候选（candidates.json + report.md）')
    p.add_argument('paths', nargs='+', help='一个或多个 .srt（也可给目录）')
    p.add_argument('--work', default='', help='出处（作品名），必填')
    p.add_argument('--episode', default='', help='集数（默认从文件名猜）')
    p.add_argument('--window', type=int, default=DEFAULT_WINDOW, help='一次送几条台词')
    p.add_argument('--per-request', type=int, default=PE.DEFAULT_PER_REQUEST)
    p.add_argument('--limit', type=int, default=0, help='每集最多处理多少条台词（冒烟用）')
    p.add_argument('--include-known', action='store_true', help='已在词汇牌组里的也收')
    p.add_argument('--run', default='')
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser('split', help='切批')
    p.add_argument('--batches', type=int, default=4)
    p.add_argument('--run', default='')
    p.set_defaults(func=cmd_split)

    p = sub.add_parser('gen', help='本地模型写成卡片内容')
    p.add_argument('--per-request', type=int, default=4)
    p.add_argument('--retries', type=int, default=2)
    p.add_argument('--force', action='store_true')
    p.add_argument('--fix-failed', action='store_true')
    p.add_argument('--run', default='')
    p.set_defaults(func=cmd_gen)

    p = sub.add_parser('verify', help='写库前唯一一道校验')
    p.add_argument('--include-known', action='store_true')
    p.add_argument('--run', default='')
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser('write', help='入库（默认演练）')
    p.add_argument('--commit', action='store_true')
    p.add_argument('--include-known', action='store_true')
    p.add_argument('--run', default='')
    p.set_defaults(func=cmd_write)

    p = sub.add_parser('audio', help='读法音频（edge-TTS 读 Reading 假名）')
    p.add_argument('--commit', action='store_true')
    p.add_argument('--force', action='store_true')
    p.add_argument('--tag', default='')
    p.set_defaults(func=cmd_audio)

    p = sub.add_parser('add', help='手动补一张不在字幕里的卡')
    p.add_argument('--word', required=True)
    p.add_argument('--source', required=True, help='出处：作品名 / 亚瑟王传说 / 现实 …')
    p.add_argument('--reading', default='')
    p.add_argument('--text', default='', help='词所在的句子（省略时用 --word 本身）')
    p.add_argument('--categories', default='', help='逗号分隔，覆盖模型的类别')
    p.add_argument('--commit', action='store_true')
    p.set_defaults(func=cmd_add)

    p = sub.add_parser('merge-fix', help='强模型补做的产出并回')
    p.add_argument('--file', required=True)
    p.add_argument('--run', default='')
    p.set_defaults(func=cmd_merge_fix)

    a = ap.parse_args(argv)
    rc = a.func(a)
    # 各子命令的返回值语义不一（cmd_scan 返回工作目录、cmd_verify 返回卡片列表）；
    # 这里只认 int 当退出码，其余一律 0 —— 否则 sys.exit(路径字符串) 会变成"失败"。
    return rc if isinstance(rc, int) else 0


if __name__ == '__main__':
    sys.exit(main())
