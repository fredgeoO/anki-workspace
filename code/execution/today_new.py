# -*- coding: utf-8 -*-
"""今日新卡 → 日语讲义（每日任务：取卡 → 直连本地模型生成 → 合并渲染）

每天早上学新卡**之前**跑的一条固定链路：

    1. plan    取今天的新卡（词汇 + 语法），落盘 cards_<日期>.json
    2. gen     **直连本地模型**（OpenAI Responses API：/v1/responses）逐张或逐批生成讲解，
               落盘 lessons/cards/NN_out.json + metrics，然后自动合并渲染讲义
    3. merge   只做「合并已有产出 → 闸门 → 渲染」（不调模型）
       apply   同 merge；也可用来合并人工写好的一整份 lesson_*.json
       models  只探一次端点：列出可用模型 + 验 api key

为什么直连而不是派子代理
------------------------
以前是「切批 → 派子代理 → 子代理读规范文档 → 写 part_NN_out.json」。
子代理每次启动都要背一整套 harness 系统提示词 + 工具目录（与日语教学毫无关系），
每个子代理还要**完整重读一遍规范文档**，10 张卡就是 10 份规范。
钱和显存都花在这些固定开销上，真正用于教学的 token 占比很低。

直连之后：

* 没有 harness 系统提示词、没有工具目录；
* 规范（= `lesson_local_prompt.md`）作为 **instructions 发一次**，
  逐卡请求时前缀逐字节不变（NInfer 按**精确前缀**复用缓存，usage 里 `cached_tokens` 会报）；
* 每张卡只发**这一张卡的数据**，不再带全量卡片当背景；
* 模型侧关掉思考链（`reasoning.effort=none`），
  实测 completion tokens 降为 1/9（90 → 10），其中还有一半是纯思考浪费；
  注意 usage 的 `reasoning_tokens` 恒为 0（端点不单列），思考量只能按 completion − 正文估。

token 账本每次都落盘（`lessons/metrics_<日期>.json`）并打印，方便和子代理时代对比。

本地端点与 api key
------------------
    base_url   默认 http://127.0.0.1:8080/v1
    model      默认 qwen3.8-27b
    api key    按下面顺序找，找到第一个就用：
                 1. --api-key
                 2. 环境变量  $env:DSH_LOCAL_LLM_API_KEY
                 3. 配置文件  ~/.dsh/local-llm.json    {"api_key": "...", "base_url": "...", "model": "..."}
                            （工作区 .dsh/local-llm.json 若存在则覆盖；NInfer 默认不要 key）
               配置文件里只放 key/base_url/model；**不要把 key 写进这份脚本**。

用法
----
    $PY = "python"
    $WS = "<工作区根>"
    $TN = "$WS\\code\\execution\\today_new.py"

    & $PY $TN models                    # 探端点：api key 对不对、模型名是什么、ctx 多大
    & $PY $TN stats                     # 只看库存：各单元还有多少新卡
    & $PY $TN plan --dry-run            # 看一眼今天取到哪些卡（只读，不落盘）

    & $PY $TN plan                      # 取卡 + 预取 JMdict 事实 → 落盘
    & $PY $TN check                     # 预取/复核词典（词形/读音/词性 + 义项/语域；不调模型）
    & $PY $TN gen                       # 直连本地模型逐张生成 → 闸门 → 讲义（默认 --per-batch 1）
    & $PY $TN gen --per-batch 3         # 一次给模型 3 张（省 system 前缀，但输出更长）
    & $PY $TN gen --restart             # 忽略已有产出，全部重生成
    & $PY $TN gen --no-merge            # 只生成，不渲染讲义

    & $PY $TN merge                     # 只合并已有产出（补跑过个别卡之后用）
    & $PY $TN merge --intro "今天这批以接续词为主"

产出（全部在 output/daily/ 下）
------------------------------
    cards_<日期>.json           今天这批卡的原始数据（= manifest；词汇卡自带 `dict` 事实）
    cards_latest.json           最近一次的副本
    lessons/cards/NN_out.json   第 NN 个请求的产出（**断点续跑的最小单位**）
    lessons/cards/NN_in.json    第 NN 个请求实际发出去的卡片数据（含 `dict`，可单独交接）
    lessons/split_<日期>.json   请求清单（merge 按它核对）
    lessons/dict_<日期>.json   JMdict 预取结果（每张词汇卡的核验 + facts；带缓存 meta）
    lessons/metrics_<日期>.json token 账本：每次请求的 prompt/completion/cached tokens 与耗时
    lessons/lesson_<日期>.json  合并后的整份 lesson JSON（= merge 的输入）
    lesson_<日期>.md            最终讲义，这是每天早上读的那份
    lesson_latest.md            最近一次的副本

词典口径（2026-10-25 起）：**plan 查一次，之后不再查**
-----------------------------------------------------
plan 把 JMdict 查一遍：核对词形/读音/词性，并把义项、语域、适用限制整理成事实，
挂到每张词汇卡的 `dict` 字段上（随卡进模型输入、进 NN_in.json）。gen / merge / apply
只读 `dict_<日期>.json`，不再打开词典库；缓存按「日期 + 卡片指纹 + 词典版本 + 缓存版本」
校验，任何一项不符才自动重查一次（`--refresh-dict` 强制重查）。

依赖：AnkiConnect 在 127.0.0.1:8765（Anki 需开着）+ 本地模型端点。只用 Python 标准库。
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request


_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))   # paths.py / jp_decks.py
import anki_api as AK  # noqa: E402  唯一的 Anki 访问点
import jmdict_check as JC  # noqa: E402  JMdict 词典核验（只读，用于纠错）
import jp_decks as JD  # noqa: E402  牌组常量 + 标签→级别（考级词汇已扁平化）
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

OUTDIR = os.path.join(WSP.OUTPUT, 'daily')
LESSON_DIR = os.path.join(OUTDIR, 'lessons')
CARDS_DIR = os.path.join(LESSON_DIR, 'cards')          # 每个请求一个 NN_out.json
# 教学规范 = 直连时作为 system 消息发出去的提示词；改它就能改模型的教学口径。
SYSTEM_PROMPT_FILE = os.path.join(_HERE, 'lesson_local_prompt.md')

# ============================================================================
# JMdict 词典层（对应技能 jmdict-lookup）
#
# 口径（2026-10-25 起）：**一次预取，之后不再查库**。
#   plan 先查一遍 → 词形/读音/词性核验 + 义项/语域事实
#   → 事实挂到每张词汇卡的 `dict` 字段（随卡进模型输入、进 NN_in.json）
#   → gen / merge / apply 只读 lessons/dict_<日期>.json 里的结果，不开词典库。
# 缓存带 date / 卡片指纹 / 词典版本 / 缓存版本；任一不符才自动重查一次。
# 词典打不开（jmdictpy 没装 / 库没建）时整段跳过，绝不挡住讲义。
# ============================================================================
_DICT = {'lk': None}


def dict_lookup():
    """进程内复用一个 Lookup（开库约 0.5s，之后每次查询 <1ms）。"""
    if _DICT['lk'] is None:
        _DICT['lk'] = JC.Lookup()
    return _DICT['lk']


def dict_path(date):
    return os.path.join(LESSON_DIR, 'dict_%s.json' % date)


def dict_fingerprint(manifest):
    """今天词汇卡的指纹：词形/读音/词性任一被改，缓存就失效（要重查一次）。"""
    rows = []
    for c in manifest.get('cards') or []:
        if c.get('kind') != 'vocab':
            continue
        rows.append('%s|%s|%s|%s' % (c.get('id'), c.get('word') or '',
                                     c.get('reading') or '', c.get('pos') or ''))
    rows.sort()
    key = '%s|%s' % (manifest.get('date'), ';'.join(rows))
    return hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]


def load_dict_cache(manifest, path=None):
    """读已落盘的预取结果 → (rep | None, 失效原因)。**只读文件，不碰词典库。**"""
    path = path or dict_path(manifest.get('date'))
    if not os.path.exists(path):
        return None, '还没有预取结果'
    try:
        with open(path, encoding='utf-8') as fh:
            rep = json.load(fh)
    except (OSError, ValueError) as e:
        return None, '缓存读不出来（%s）' % e
    if not isinstance(rep, dict) or not isinstance(rep.get('cards'), dict):
        return None, '缓存格式不对'
    if not rep.get('available'):
        return None, '上次词典不可用'
    meta = rep.get('meta') or {}
    if meta.get('cache_version') != JC.CACHE_VERSION:
        return None, '缓存版本变了（%s → %s）' % (meta.get('cache_version'), JC.CACHE_VERSION)
    if str(meta.get('date') or rep.get('date')) != str(manifest.get('date')):
        return None, '日期对不上（缓存是 %s）' % (meta.get('date') or rep.get('date'))
    if meta.get('fingerprint') != dict_fingerprint(manifest):
        return None, '卡片集/词形/读音/词性变了'
    now_db = JC.db_version()
    if meta.get('db_version') and now_db and meta['db_version'] != now_db:
        return None, '词典版本变了（%s → %s）' % (meta['db_version'], now_db)
    return rep, ''


def build_dict_report(manifest, lookup=None):
    """真正打开词典查一遍（只有缓存缺失/失效、或 --refresh-dict 才会走到这里）。"""
    rep = JC.check_manifest(manifest, lookup or dict_lookup())
    if rep.get('available'):
        rep['meta'] = {
            'date': manifest.get('date'),
            'fingerprint': dict_fingerprint(manifest),
            'db_version': JC.db_version(),
            'cache_version': JC.CACHE_VERSION,
            'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        }
    return rep


def ensure_dict(args, manifest, cache_path=None, lookup=None, write=True):
    """确保今天有一份可用的词典事实 → (dinfo | None, rep | None, computed)。

    缓存有效 = **零查库**；缺失/过期才查一次并写回（--refresh-dict 强制重查）。
    `lookup` / `cache_path` 可注入，测试用假词典、临时文件。
    """
    if getattr(args, 'no_dict', False):
        return None, None, False
    force = bool(getattr(args, 'refresh_dict', False))
    path = cache_path or dict_path(manifest.get('date'))
    why = ''
    if not force:
        rep, why = load_dict_cache(manifest, path)
        if rep:
            print('📖 词典：复用 %s（未查库）' % os.path.basename(path), file=sys.stderr)
            return rep.get('cards') or {}, rep, False
    else:
        why = '--refresh-dict'
    rep = build_dict_report(manifest, lookup)
    if not rep.get('available'):
        print('提示：%s；本次跳过 JMdict 词典层。' % (rep.get('reason') or '词典不可用'),
              file=sys.stderr)
        return None, rep, False
    if write:
        write_json(path, rep)
    print('📖 词典：%s → 已预取 %d 张词汇卡（%s）'
          % (why or '还没有预取结果', rep.get('checked'), os.path.basename(path)),
          file=sys.stderr)
    return rep.get('cards') or {}, rep, True


def attach_dict(manifest, rep):
    """把词典事实挂到词汇卡的 `dict` 字段（清掉旧值；无事实/禁用时不带字段）。"""
    facts = {}
    if rep:
        for cid, res in (rep.get('cards') or {}).items():
            if isinstance(res, dict) and res.get('facts'):
                facts[str(cid)] = res['facts']
    for c in manifest.get('cards') or []:
        fact = facts.get(str(c.get('id'))) if c.get('kind') == 'vocab' else None
        if fact:
            c['dict'] = fact
        else:
            c.pop('dict', None)
    return manifest


def print_dict_report(rep, limit=8, title='JMdict 核验'):
    """把词典核验报告打到 stderr（讲义正文不掺这些）。"""
    if not rep or not rep.get('available'):
        return
    print()
    for line in JC.format_report(rep, limit=limit, title=title):
        print(line, file=sys.stderr)


# ============================================================================
# 本地模型（OpenAI 兼容）配置
# ============================================================================
LLM_DEFAULT_BASE = 'http://127.0.0.1:8080/v1'
# OpenAI Responses API 路由（2026-10 从 /chat/completions 切过来）
LLM_RESPONSES_PATH = '/responses'
LLM_DEFAULT_MODEL = 'qwen3.8-27b'
LLM_CONFIG_FILE = os.path.join(WSP.ROOT, '.dsh', 'local-llm.json')
# 全局（机器级）正本配置；工作区那份若存在则覆盖它
LLM_GLOBAL_CONFIG_FILE = os.path.join(
    os.environ.get('DSH_HOME') or os.path.join(os.path.expanduser('~'), '.dsh'),
    'local-llm.json')
LLM_KEY_ENV = ['DSH_LOCAL_LLM_API_KEY', 'LOCAL_LLM_API_KEY']
LLM_TIMEOUT = 1800          # 单次请求上限（秒）；27B Q4 逐张卡通常 10–60s
LLM_HTTP_RETRIES = 3        # 连接/5xx/429 的重试次数（指数退避）
LLM_MAX_TOKENS = 4096       # 单次回复上限；超了会被截断，截断算失败并重试
LLM_TEMPERATURE = 0.3
LLM_TOP_P = 0.9

# ============================================================================
# 配置区：换收藏结构时改这里
#
#   一个「学习单元」= deck + 模型过滤。字段名逐单元指定（不同模型字段名不同）。
#       deck     学习单元所在的 deck（AnkiConnect 会连带子 deck，所以写父 deck 即可）
#       model    笔记模型名；写 '' 表示不按模型过滤
#       kind     vocab / grammar
#       level    默认识别到的级别（eggrolls 会用标签细化到具体 N 级）
#       per_day  上限兜底值（实读 getDeckConfig 失败时才用）
#       skip_taught  这个字段非空 = 这张卡已经讲过，跳过（'' = 不过滤）
#       sort     position（按卡在队列里的位置）| index（按笔记 Index 字段）
#                | tree（先按牌组树顺序，树内再按队列位置——父 deck 单元用）
#       light_deck_suffix  卡所在 deck 以它结尾 = 只做轻量呈现（不调模型）
#       fields   取值模板，{N} 表示例句序号 1..3
#
#   ⚠️ 改 vocab 的 deck 结构时，也要同步改 code/execution/pipeline.py 的 CFG。
# ============================================================================
EGGROLL_FIELDS = dict(w1='VocabKanji', read='VocabFurigana', pos='VocabPoS',
                      mean='VocabDefSC', sent='SentKanji{N}', trans='SentDefSC{N}',
                      audio='VocabAudio', sent_audio='SentAudio{N}')
CORE_FIELDS = dict(w1='Word', read='Transliteration', pos='Part of Speech',
                   mean='Meaning', sent='Sentence', trans='Sentence Translation',
                   audio='Word Audio', sent_audio='Sentence Audio')
GRAMMAR_FIELDS = dict(w1='Card', pos='ConnectiveType1', mean='MeaningCN',
                      mean_jp='MeaningJP', sent='Sentence{N}', trans='CN{N}',
                      audio='SentenceAudio{N}', note='CNote{N}', extra='AIConclusion')
# 视频例句卡（Basic 模型）：卡片自带 AINote 讲解 + 振假名 HTML + 原声，
# 讲义只做轻量呈现（句子 + 中文 + 要点一行），**不发给模型**。
SENTENCE_FIELDS = dict(w1='Sentence', ruby='Sentence HTML', note='AINote',
                       source='Source', audio='Sentence Audio')

DECKS = [
    # ---- 词汇：考级词汇（学习单元 = 父 deck「2-考级词汇」，上限 8）----
    dict(deck='0-日本语学习::0-词汇::2-考级词汇', model='eggrolls-JLPT10k-v3.5',
         kind='vocab', level='考级', per_day=8, skip_taught='', sort='position',
         level_from_tag=True, fields=EGGROLL_FIELDS),
    # ---- 词汇：词频词（学习单元 = 父 deck「6000」，上限 7）----
    # ⚠️ 这 3598 张卡的 AINote 字段**早就被批量填满**（3598/3598 非空），
    # 拿它当「已讲过」的判据会让这个单元天天取到 0 张 —— 所以这里不过滤。
    # 排序也改成队列位置（= Anki 里实际会先出现的词），不再按 Index 词频序。
    dict(deck='0-日本语学习::0-词汇::1-高频日语单词 6000', model='Japanese Vocabulary',
         kind='vocab', level='Core6000', per_day=7, skip_taught='',
         sort='position', fields=CORE_FIELDS),
    # ---- 词汇：素材生词（mine.py 建的第 3 个词汇 deck，与 core6000 同模板）----
    # 上限实读 deckConfig「素材生词」（当前 new.perDay=13，兜底只写同值）；
    # 卡按队列位置（card.due = JitenAnimeRank 序）取，讲义顺序 = 当天实际学习顺序。
    # 同样**不按 AINote 过滤**：这批卡的讲解正是每天早上现讲的，不是「已讲过」。
    dict(deck='0-日本语学习::0-词汇::0-素材生词', model='Japanese Vocabulary',
         kind='vocab', level='素材生词', per_day=13, skip_taught='',
         sort='position', fields=CORE_FIELDS),
    # ---- 语法：整个「1-语法」子树算**一个**学习单元，上限取父 deck 自己的
    #      deckConfig（当前 5）。子 deck 各自的日上限会先各自出卡、再由父上限
    #      截断，只有这样才能和 Anki 首页显示的今日新卡数对上。
    #      取卡顺序 = 牌组树顺序（3-N3 → 4-N2 → 5-N1），树内按队列位置。
    #      子 deck 里「…例句」的卡只做轻量呈现（卡片自带 AIConclusion），不调模型。
    dict(deck='0-日本语学习::1-语法', model='どんなときどう使う日本語表現文型Note',
         kind='grammar', level='N3', per_day=5, skip_taught='', sort='tree',
         level_from_deck=True, light_deck_suffix='例句', fields=GRAMMAR_FIELDS),
    # ---- 例句：视频原声例句卡（Basic 模型），上限实读 deckConfig，轻量呈现 ----
    dict(deck='0-日本语学习::2-例句', model='Basic',
         kind='sentence', level='例句', per_day=10, skip_taught='',
         sort='position', fields=SENTENCE_FIELDS),
]

# 按 deck 路径覆盖上限（留空表示不覆盖）。例：
#   PER_DECK_LIMIT = {'0-日本语学习::0-词汇::2-考级词汇': 15}
PER_DECK_LIMIT = {}

MAX_SENTENCES = 3          # 每张卡最多取几条例句
NOTE_CHUNK = 200           # notesInfo 的批量大小
LESSON_BACKUP = True       # 写讲义前把已有讲义改名为 .bak

# 每个请求塞几张卡。
# 默认 1 —— 输出最短、失败面最小、最容易断点续跑；本地 27B Q4 逐张约 10–60s。
# 调大（如 3）能省掉重复的 system 前缀，但单次输出变长、被截断和漏卡的概率上升。
# 想要"一次讲完全部"就 --per-batch 0（0 / 负数 = 不分批）。
PER_BATCH = 1

# eggrolls 标签里带着真实级别，用它细化 level。
# 形如 `eggrolls-JLPT10k-v3.5::4-N2::N2高频`（N3/N2/N1）或 `…::1-N5`（N5/N4，没有频段），
# 解析交给 code/common/jp_decks.py —— 考级词汇扁平化后这是**唯一**的级别来源。
def eggroll_level(tags):
    return JD.level_from_tags(tags or [])


# ============================================================================
# AnkiConnect（实现已收进 code/common/anki_api.py；AnkiError 留个别名给本文件的 except）
# ============================================================================
AnkiError = AK.AnkiError


# ============================================================================
# 文本清洗与振假名
# ============================================================================
TAG = re.compile(r'<[^>]+>')
BR = re.compile(r'<br\s*/?>', re.I)
SOUND = re.compile(r'\[sound:([^\]]+)\]')
# 注音记法：读法一律写在 [ ] 里，基底在左边。基底不用正则硬吃，改用
# _split_ruby() 向左扩展（见下），因为「は勝[か]」这种「假名直接贴汉字」的情况
# 正则回溯会算错。
BRACKET = re.compile(r'\[([^\]]+)\]')
# 「多句挤在一个字段里」的两种分隔：连续的 <br>，或段落标签之间
SENT_PAIR_BR = re.compile(r'(?:\s*<br\s*/?>\s*){2,}', re.I)
SENT_PAIR_P = re.compile(r'</p>\s*<p[^>]*>', re.I)
DOUBLE_KANA = re.compile(r'([\u3040-\u309f\u30a0-\u30ff])\s+(?=[\u3040-\u309f\u30a0-\u30ff])')
KANJI = re.compile(r'[\u4e00-\u9fff]')
PLACEHOLDER = re.compile(r'\{\{[^{}]*\}\}')


def strip_tags(text):
    """去 HTML 标签，<br> 变成真换行，保留其余文字。"""
    text = text or ''
    text = BR.sub('\n', text)
    text = TAG.sub('', text)
    return text


def _kana_or_space(ch):
    return ('\u3040' <= ch <= '\u309f') or ('\u30a0' <= ch <= '\u30ff') or ch in ' \u3000'


def _is_kanji(ch):
    # 汉字 + 々〆ヶ 这类汉字辅助字符（「次々[つぎつぎ]」的 々 要能进基底）
    return bool(KANJI.match(ch)) or ch in '\u3005\u3006\u30f6'


def _split_ruby(text):
    """把 漢字[かんじ] 记法拆成 [(基底, 读法), ...]，其余文字原样保留。

    基底向左扩展：先吃掉紧邻的汉字串（**允许汉字之间夹空格**，因为
    「どんなときどう使う」系列用空格给长词分词），再在**前导假名段里含空格**时
    多吃那一段（覆盖 彼[かの] 女[じょ] / 大[たい] 切[せつ]）。

    为什么要卡「假名段里必须有空格」：例句里满是「愛あっての結婚生活」这种写法——
    `の` 是词「あっての」的一部分，不是 `愛` 的读音。只有权威数据里
    「彼[かの] 女[じょ]」这种以空格分词的形态才值得向左吃假名，
    否则只吃汉字串（`は勝[か]` 里的 は 就不会被吃进基底）。
    """
    out, i = [], 0
    while i < len(text):
        j = text.find('[', i)
        if j < 0 or ']' not in text[j:]:
            out.append((text[i:], None))
            break
        k = text.find(']', j)
        if j == i:                      # 左边没有基底，当作普通文字
            out.append((text[i:k + 1], None))
            i = k + 1
            continue
        end = j - 1
        while end >= i and text[end] in ' \u3000':
            end -= 1
        if end < i or not _is_kanji(text[end]):
            out.append((text[i:k + 1], None))
            i = k + 1
            continue
        start = end
        while start - 1 >= i and (_is_kanji(text[start - 1]) or text[start - 1] in ' \u3000'):
            start -= 1
        if start - 1 >= i and _kana_or_space(text[start - 1]):
            m = start - 1
            while m - 1 >= i and _kana_or_space(text[m - 1]):
                m -= 1
            lead = text[m:start]
            if ' ' in lead or '\u3000' in lead:
                if m > i and _is_kanji(text[m - 1]):
                    start = m
        out.append((text[i:start], None))
        base = re.sub(r'[\s\u3000]+', '', text[start:end + 1])
        reading = re.sub(r'[\s\u3000]+', '', text[j + 1:k])
        out.append((base, reading))
        i = k + 1
    return out


def _extract_existing_ruby(text, store):
    """把已经带 <ruby> 的片段挖出来占位，返回替换后的文本。

    这类片段本身就是完整注音，必须原样保留——否则会被 strip_tags 连标签一起删掉，
    静默丢掉振假名。
    """
    def keep(m):
        store.append(m.group(0))
        return '\x00RUBY%d\x00' % (len(store) - 1)

    return re.sub(r'<ruby>.*?</ruby>', keep, text or '', flags=re.S | re.I)


def _put_back_ruby(text, store):
    for i, frag in enumerate(store):
        text = text.replace('\x00RUBY%d\x00' % i, frag)
    return text


def strip_ruby_base(text):
    """把 漢字[かんじ] 记法去掉读音，只留汉字原文（例句正文用）。"""
    store = []
    saved = _extract_existing_ruby(text, store)
    saved = strip_tags(saved)
    text = ''.join(base for base, _ in _split_ruby(saved))
    text = _put_back_ruby(text, store)
    # 词典数据用空格给长词分词（「勝 ち 負 け」），假名之间的空格要收掉；
    # 词与词之间是真空格（至少一侧是汉字），保留。
    text = DOUBLE_KANA.sub(r'\1', text)
    return re.sub(r'[ \u3000]{2,}', ' ', text).strip()


def to_ruby(text):
    """把 漢字[かんじ] / <b>漢字[かんじ]</b> 记法转成 <ruby>漢字<rt>かんじ</rt></ruby>。

    用于例句正文，让讲义在浏览器/Markdown 预览里直接带假名。
    已经带 ruby 标签的内容原样保留（重复处理是幂等的）。
    """
    store = []
    saved = _extract_existing_ruby(text, store)
    saved = strip_tags(saved)
    pieces = []
    for base, reading in _split_ruby(saved):
        pieces.append('<ruby>%s<rt>%s</rt></ruby>' % (base, reading) if reading else base)
    out = ''.join(pieces)
    out = _put_back_ruby(out, store)
    out = DOUBLE_KANA.sub(r'\1', out)
    out = re.sub(r'</rt></ruby>[ \u3000]+(?=<ruby>)', '</rt></ruby>', out)   # 相邻 ruby 之间不留缝
    out = re.sub(r'\n{2,}', '\n', out)
    return re.sub(r'[ \u3000]{2,}', ' ', out).strip()


def plain_jp(text):
    """讲义里当纯文本用的日语：去标签、去注音、压缩空白、换行变空格。"""
    return re.sub(r'\s+', ' ', strip_ruby_base(text)).strip()


def clean_mean(text, limit=80):
    """释义：去标签、把 eggrolls 的 [ ] 注音括号展开、压缩空白、限长。"""
    text = strip_tags(text)
    text = re.sub(r'\[([^\]]*)\]', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + '…'
    return text


def audio_files(text):
    """从字段里抽出 [sound:xxx] 的文件名（可能多个）。"""
    return SOUND.findall(text or '')


def as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ============================================================================
# 取字段
# ============================================================================
def value_of(fields, name):
    item = fields.get(name)
    if isinstance(item, dict):
        return item.get('value', '')
    return item or ''


def pick_reading(raw, word):
    """读音清洗：去标签/去括号/去空格；不可信就返回空。"""
    read = strip_tags(raw or '')
    read = re.sub(r'\[([^\]]*)\]', r'\1', read)
    read = re.sub(r'[\s\u3000]+', '', read).strip()
    if not read or len(read) > 24:
        return ''
    if KANJI.search(read) or re.search(r'[\dA-Za-z]', read):
        return ''
    if not re.search(r'[\u3040-\u309f\u30a0-\u30ff]', read):
        return ''
    return '' if read == word else read


def collect_sentences(fields, cfg, limit=None):
    """按 {N} 模板取例句（日语 + 振假名 + 中文 + 音频）。

    limit 默认 MAX_SENTENCES；例句卡要按卡的模板序号精确取第 N 句，所以放宽。

    两种情况：
    * 模板带 `{N}`（eggrolls 的 `SentKanji1..3`、语法卡的 `Sentence1..5`）→ 逐字段取；
    * 模板**不带** `{N}`（Core6000：整个 `Sentence` / `Sentence Translation` / `Sentence Audio`
      各只有一个字段，多句用 `<br><br>` 塞在一起）→ 按块切开，**按序号配对**译文与音频。
      早先没走这条分支，导致同一句被读了 3 遍、讲义里显示 3 条一模一样的例句。
    """
    limit = MAX_SENTENCES if limit is None else limit
    f = cfg['fields']
    tpl = f['sent']
    if '{N}' not in tpl:
        return _collect_blocks_sentences(fields, f, limit)
    out = []
    for n in range(1, limit + 2):
        jp_raw = value_of(fields, tpl.format(N=n))
        if not jp_raw or not plain_jp(jp_raw):
            continue
        trans_tpl = f.get('trans')
        out.append({
            'jp': plain_jp(jp_raw),
            'ruby': to_ruby(jp_raw),
            'cn': clean_mean(value_of(fields, trans_tpl.format(N=n)), 120) if trans_tpl else '',
            'audio': audio_files(value_of(fields, f['audio'].format(N=n))) if f.get('audio') else [],
        })
        if len(out) >= limit:
            break
    return out


def split_field_blocks(raw):
    """把一个「多句挤在一个字段里」的字段按句切开（Core6000 的 `句1<br><br>句2`）。

    先按连续的 `<br>` 切；切不开再试 `</p><p>` 这类段落分隔。单句就返回 1 个元素。
    """
    if not raw:
        return []
    blocks = SENT_PAIR_BR.split(raw)
    if len(blocks) == 1:
        blocks = SENT_PAIR_P.split(raw)
    return [x for x in (b.strip() for b in blocks) if x and plain_jp(x)]


def _collect_blocks_sentences(fields, f, limit):
    """不带 `{N}` 的字段：按块切句，逐块配对该句的中文与**该句自己的音频**。

    音频优先取 `sent_audio`（Core6000 的 `Sentence Audio` 是逐句一条的），
    没有才退回 `audio`（单词音频）。两个都不带 `{N}` 时才是这一路径。
    """
    jp_blocks = split_field_blocks(value_of(fields, f['sent']))
    trans_tpl = f.get('trans')
    cn_blocks = (split_field_blocks(value_of(fields, trans_tpl))
                 if trans_tpl and '{N}' not in trans_tpl else [])
    sounds = []
    for key in ('sent_audio', 'audio'):
        tpl = f.get(key)
        if tpl and '{N}' not in tpl:
            sounds = audio_files(value_of(fields, tpl))
            if sounds:
                break
    out = []
    for i, jp in enumerate(jp_blocks[:limit]):
        out.append({
            'jp': plain_jp(jp),
            'ruby': to_ruby(jp),
            'cn': clean_mean(cn_blocks[i], 120) if i < len(cn_blocks) else '',
            'audio': [sounds[i]] if i < len(sounds) else [],
        })
    return out


# ---- 例句卡（视频原声 / 语法例句）的轻量呈现 -------------------------------
# 视频例句卡的 AINote 形如：<p><b>中文翻译：</b>…</p><p><b>核心词汇：</b><br>…</p>
A_NOTE_BLOCK = re.compile(r'<p>(.*?)</p>', re.S | re.I)
A_NOTE_LABEL = re.compile(r'<b>\s*(.*?)\s*[:：]\s*</b>', re.S | re.I)
ANIME_TAG = re.compile(r'^动画::(.+?)::(.+?)::(第\d+集)$')
TIME_IN_SOURCE = re.compile(r'\((\d+)h(\d+)m([\d.]+)s\)')


def strip_ruby_readings(text):
    """去注音：整块删掉 <rt>…</rt>（读法），再剥其余标签，<br> 变真换行。

    不能只 strip_tags：那样会留下读法，把「お<ruby>散歩<rt>さんぽ</rt></ruby>」
    变成「お散歩さんぽ」。
    """
    t = re.sub(r'<rt>.*?</rt>', '', text or '', flags=re.S | re.I)
    return strip_tags(t)


def sentence_html_line(html):
    """例句卡正文的 HTML：先去掉被塞进 <ruby> 里的 <br>，再把换行变成 ' / '。

    ABS 导出的例句里偶有 `シルフと<ruby>呼<rt>よ</rt></ruby>ばれる<br><br>
    <ruby><br><br><br><br>風<rt>かぜ</rt></ruby>…` 这种畸形注音（换行落进了 ruby 基底），
    直接渲染会出来一串空行。
    """
    def drop_br(m):
        return re.sub(r'<br\s*/?>', '', m.group(0), flags=re.I)

    html = re.sub(r'<ruby>.*?</ruby>', drop_br, html or '', flags=re.S | re.I)
    html = BR.sub(' / ', html)
    return re.sub(r'(?:\s*/\s*){2,}', ' / ', html)


def parse_ainote(html):
    """把例句卡的 AINote 拆成 {标签: 纯文本}（标签如 中文翻译/核心词汇/语法要点）。"""
    out = {}
    for block in A_NOTE_BLOCK.findall(html or ''):
        m = A_NOTE_LABEL.search(block)
        if not m:
            continue
        label = strip_tags(m.group(1)).strip()
        body = strip_ruby_readings(block[m.end():]).strip()
        if label and body:
            out.setdefault(label, body)
    return out


def first_line(text, limit=70):
    """取一段说明的第一行/第一句，压成一行，限长。"""
    line = re.split(r'\n', (text or '').strip())[0]
    line = re.sub(r'\s+', ' ', line).strip()
    return line[:limit] + ('…' if len(line) > limit else '')


def source_line(raw, tags):
    """例句卡的出处：动画标签（作品 + 第NN集）+ SRT 里的时间点。"""
    label = ''
    for t in tags or []:
        m = ANIME_TAG.match(t)
        if m:
            label = '%s %s' % (m.group(1), m.group(3))
            break
    m = TIME_IN_SOURCE.search(raw or '')
    if m:
        secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(float(m.group(3)))
        when = '%02d:%02d' % (secs // 60, secs % 60)
        return ('%s %s' % (label, when)).strip()
    return label or strip_tags(raw or '').strip()[:60]


def make_card(note, cfg, pos, deck=None):
    """把一条笔记变成讲义用的一条卡。取不到主词形就返回 None。

    deck = 这张卡实际所在的 deck（父 deck 单元里各子 deck 混在一起，
    要靠它区分「解释卡」和「例句卡」）。style='light' 的卡只做轻量呈现，
    不发给模型。
    """
    fields = note.get('fields', {})
    f = cfg['fields']
    tags = note.get('tags', []) or []
    word = clean_mean(value_of(fields, f['w1']), 40)
    word = re.sub(r'\[([^\]]*)\]', '', word)           # 流行[はや]る -> 流行る
    word = re.sub(r'^[〜～~\-—–]+', '', word).strip()
    if not word:
        return None
    card_deck = deck or cfg['deck']
    light = bool(cfg.get('light_deck_suffix') and card_deck.endswith(cfg['light_deck_suffix']))

    if cfg['kind'] == 'sentence':
        # 视频例句卡：句子 + 中文 + 要点（全部来自卡片自带的 AINote，不调模型）
        parsed = parse_ainote(value_of(fields, f.get('note') or ''))
        raw_sent = value_of(fields, f['w1'])
        html_sent = value_of(fields, f.get('ruby') or f['w1']) or raw_sent
        # 要点不再硬截 60 字（实测会把「句末用…」这类说明切在半句上）：
        # 先按句末标点切，切不动才标「（后略）」。
        points = []
        for label in ('核心词汇', '语法要点'):
            if parsed.get(label):
                points.append('%s：%s' % (label, clip_sentence(first_line(parsed[label], 400), 160)))
        return {
            'id': int(note['noteId']),
            'kind': 'sentence',
            'level': '',
            'deck': card_deck,
            'deck_short': card_deck.replace('0-日本语学习::', '').replace('::', ' / '),
            'model': note.get('modelName', cfg.get('model', '')),
            'queue_pos': pos,
            'word': word,
            'reading': '',
            'pos': '',
            'meaning': clean_mean(parsed.get('中文翻译', ''), 60),
            'audio': audio_files(value_of(fields, f.get('audio') or '')) if f.get('audio') else [],
            'sentences': [],
            'style': 'light',
            'light': {
                'jp_ruby': to_ruby(sentence_html_line(html_sent)).strip(),
                'cn': parsed.get('中文翻译', ''),
                'points': points,
                'warnings': _sentence_warnings(word, points,
                                               to_ruby(sentence_html_line(html_sent))),
                'source': source_line(value_of(fields, f.get('source') or ''), tags),
            },
        }

    level = cfg['level']
    if cfg.get('level_from_tag'):
        level = eggroll_level(tags) or level
    if cfg.get('level_from_deck'):
        # 语法那一支没有扁平化：级别仍写在子 deck 名里（…::3-N3::1-N3-解释）
        m = re.search(r'-(N[1-5])(?:::|\Z)', card_deck or '')
        if m:
            level = m.group(1)
    card = {
        'id': int(note['noteId']),
        'kind': cfg['kind'],
        'level': level,
        'deck': card_deck,
        'deck_short': card_deck.replace('0-日本语学习::', '').replace('::', ' / '),
        'model': note.get('modelName', cfg.get('model', '')),
        'queue_pos': pos,
        'word': word,
        'reading': pick_reading(value_of(fields, f['read']), word) if f.get('read') else '',
        'pos': clean_mean(value_of(fields, f['pos']), 40) if f.get('pos') else '',
        'meaning': clean_mean(value_of(fields, f['mean']), 120),
        'audio': audio_files(value_of(fields, f['audio'])) if f.get('audio') else [],
        'sentences': collect_sentences(fields, cfg, 11 if light else None),
        'style': 'light' if light else 'full',
    }
    if cfg['kind'] == 'grammar':
        card['meaning_jp'] = clean_mean(value_of(fields, f['mean_jp']), 60) if f.get('mean_jp') else ''
        notes = []
        for n in range(1, 6):
            t = clean_mean(value_of(fields, f['note'].format(N=n)), 200) if f.get('note') else ''
            if t:
                notes.append(t)
        card['notes'] = notes
        card['existing'] = strip_tags(value_of(fields, f['extra']))[:400] if f.get('extra') else ''
    if light:
        # 语法例句卡：卡片自带 CNote，取第一条当要点（同样不调模型）
        card['light'] = {
            'cn': card['meaning'],
            'points': [first_line(x, 90) for x in (card.get('notes') or [])[:1]],
            'source': '',
            'jp_ruby': '',
        }
    return card


# ============================================================================
# 队列：今天的新卡
# ============================================================================
_DECK_LIMIT_CACHE = {}


def deck_new_limit_raw(deck):
    """某个 deck 自己的每日新卡上限（deckConfig）。读不到就当 0（这个 deck 不出卡）。"""
    if deck not in _DECK_LIMIT_CACHE:
        _DECK_LIMIT_CACHE[deck] = AK.deck_new_per_day(deck)
    return _DECK_LIMIT_CACHE[deck]


def deck_new_limit(cfg, cli_limit):
    """这个学习单元今天放几张新卡。优先级：
    --limit > PER_DECK_LIMIT > getDeckConfig(实读) > 配置 per_day 兜底
    """
    if cli_limit:
        return int(cli_limit), '命令行 --limit'
    if cfg['deck'] in PER_DECK_LIMIT:
        return int(PER_DECK_LIMIT[cfg['deck']]), 'PER_DECK_LIMIT'
    try:
        conf = AK.deck_config(cfg['deck'])
        per_day = int(conf['new']['perDay'])
        _DECK_LIMIT_CACHE[cfg['deck']] = per_day
        if per_day:
            return per_day, 'deckConfig「%s」' % conf.get('name', '')
    except Exception:
        pass
    return int(cfg.get('per_day') or 0), '配置兜底 per_day'


def query_for(cfg, skip_taught=True):
    q = 'deck:"%s" is:new -is:suspended -is:buried' % cfg['deck']
    if cfg.get('model'):
        q += ' note:"%s"' % cfg['model']
    if skip_taught and cfg.get('skip_taught'):
        q += ' -%s:_*' % cfg['skip_taught']
    return q


def pick_queue(cfg, limit, skip_taught=True):
    """返回 (cards, stats)：按 Anki 队列顺序取前 limit 张新卡，再按笔记合并成讲义条目。

    队列顺序 = card.due（新卡的 due 就是它在队列里的位置）；sort='index' 的单元
    改用笔记里的 Index 字段；sort='tree' 的单元先按牌组树顺序、树内再按队列位置
    （父 deck 单元专用：Anki 从父 deck 收集新卡就是这个顺序）。

    ⚠️ 先取满 limit 张**卡**、再合并笔记。同一笔记的多张卡（例如语法例句卡的
    4 个卡模板）只出 1 条讲义条目，但 4 张卡照样计入今日张数——Anki 首页显示的
    「今天 30 张」是卡数，不是笔记数。
    """
    query = query_for(cfg, skip_taught)
    cids = AK.find_cards(query)
    stats = {'deck': cfg['deck'], 'model': cfg.get('model', ''), 'level': cfg['level'],
             'kind': cfg['kind'], 'query': query, 'new_cards_total': len(cids),
             'limit': limit, 'taken': 0, 'taken_notes': 0, 'skipped': 0,
             'limit_source': ''}
    if not cids or not limit:
        stats['limit_source'] = '队列为空或上限为 0'
        return [], stats

    infos = AK.cards_info(cids, chunk=500)

    if cfg.get('sort') == 'index':
        # 排序键是笔记里的 Index（词频序），不是卡位置
        note_ids = list({int(i['note']) for i in infos})
        idx_of = {}
        for n in AK.notes_info(note_ids, chunk=NOTE_CHUNK):
            idx_of[int(n['noteId'])] = as_int(value_of(n.get('fields', {}), 'Index'), 10 ** 9)
        infos.sort(key=lambda i: (idx_of.get(int(i['note']), 10 ** 9), i['cardId']))
    elif cfg.get('sort') == 'tree':
        # 父 deck 单元：Anki 从父 deck 收集新卡时**每棵子 deck 各按自己的日上限出卡**
        # （解释 deck 1 张、例句 deck 4 张……），再被父 deck 的上限截断。
        # 所以这里先按牌组树顺序排，再逐 deck 限制，最后取单元总上限。
        per_deck = {}
        for name in AK.deck_names():
            if name == cfg['deck'] or name.startswith(cfg['deck'] + '::'):
                per_deck[name] = deck_new_limit_raw(name)
        infos.sort(key=lambda i: (i.get('deckName') or '', as_int(i.get('due')), i['cardId']))
        kept, used = [], {}
        for info in infos:
            deck_name = info.get('deckName') or cfg['deck']
            if used.get(deck_name, 0) >= per_deck.get(deck_name, 0):
                continue
            used[deck_name] = used.get(deck_name, 0) + 1
            kept.append(info)
            if len(kept) >= int(limit):
                break
        infos = kept
    else:
        infos.sort(key=lambda i: (as_int(i.get('due')), i['cardId']))

    taken = infos[:int(limit)]
    picked, n_cards, ords, seen = [], {}, {}, set()
    for info in taken:
        nid = int(info['note'])
        n_cards[nid] = n_cards.get(nid, 0) + 1
        # 卡模板序号：语法例句卡的模板就是「第 N 句例句」的展示卡（ord=1 → 第①句）
        ords.setdefault(nid, []).append(as_int(info.get('ord')))
        if nid in seen:
            continue
        seen.add(nid)
        picked.append((nid, as_int(info.get('due')), info.get('deckName') or cfg['deck']))
    stats['taken'] = len(taken)
    stats['taken_notes'] = len(picked)
    stats['skipped'] = max(0, len(cids) - len(taken))

    by_id = AK.notes_map([nid for nid, _, _ in picked], chunk=NOTE_CHUNK)

    cards = []
    for nid, pos, deck in picked:
        note = by_id.get(nid)
        if not note:
            continue
        card = make_card(note, cfg, pos, deck)
        if card:
            card['tags'] = note.get('tags', []) or []
            card['n_cards'] = n_cards.get(nid, 1)
            card['card_ords'] = sorted(set(ords.get(nid) or []))
            cards.append(card)
    return cards, stats


def collect(opts):
    """按配置取今天全部新卡。opts 来自命令行。"""
    groups = DECKS
    if opts.only == 'vocab':
        groups = [g for g in DECKS if g['kind'] == 'vocab']
    elif opts.only == 'grammar':
        groups = [g for g in DECKS if g['kind'] == 'grammar']
    if getattr(opts, 'deck', None):
        want = [p.strip() for p in opts.deck.split(',') if p.strip()]
        groups = [g for g in groups if any(g['deck'] == w or g['deck'].startswith(w) for w in want)]
        if not groups:
            raise SystemExit('--deck 没有匹配到配置单元（前缀匹配，必须从头匹配）。可用：\n  ' +
                             '\n  '.join(g['deck'] for g in DECKS) +
                             '\n例：--deck "1-语法::5-N1"')

    cards, stats = [], []
    for cfg in groups:
        limit, src = deck_new_limit(cfg, opts.limit)
        got, st = pick_queue(cfg, limit, skip_taught=not opts.include_taught)
        st['limit_source'] = src
        st['taken_notes'] = len(got)      # 讲义条目数（同一笔记的多张卡算 1 条）
        cards.extend(got)
        stats.append(st)

    # 排序：先词汇后语法/例句，级别从低到高，同级按 deck 与队列位置
    lv_order = {'N5': 0, 'N4': 1, 'N3': 2, 'N2': 3, 'N1': 4, 'Core6000': 5,
                '素材生词': 6}
    kind_order = {'vocab': 0, 'grammar': 1, 'sentence': 2}
    cards.sort(key=lambda c: (kind_order.get(c['kind'], 9), lv_order.get(c['level'], 9),
                              c['deck'], c['queue_pos']))

    def card_count(pred):
        """按**卡**计数（同一笔记的多张卡各算一张），和 Anki 首页的口径一致。"""
        return sum(c.get('n_cards') or 1 for c in cards if pred(c))

    manifest = {
        'version': 2,
        'date': opts.date,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'system_prompt': SYSTEM_PROMPT_FILE,
        'counts': {
            'total': card_count(lambda c: True),
            'entries': len(cards),
            'vocab': card_count(lambda c: c['kind'] == 'vocab'),
            'grammar': card_count(lambda c: c['kind'] == 'grammar'),
            'sentence': card_count(lambda c: c['kind'] == 'sentence'),
        },
        'decks': stats,
        'cards': cards,
    }
    return manifest


# ============================================================================
# 本地模型客户端（OpenAI Responses API：/v1/responses）
# ============================================================================
class LLMError(RuntimeError):
    pass


def load_llm_config(args):
    """api key / base_url / model 的来源与优先级，见文件头。

    配置文件读两份：全局 `~/.dsh/local-llm.json`（机器级正本）打底，
    工作区 `.dsh/local-llm.json` 若存在则覆盖（临时特例才需要）。
    """
    file_cfg = {}
    for path in (LLM_GLOBAL_CONFIG_FILE, LLM_CONFIG_FILE):
        if not os.path.exists(path):
            continue
        try:
            # utf-8-sig：PowerShell 的 Set-Content -Encoding utf8 会写 BOM
            with open(path, encoding='utf-8-sig') as fh:
                file_cfg.update(json.load(fh) or {})
        except (OSError, json.JSONDecodeError) as e:
            print('警告：读不出 %s（%s），忽略它。' % (path, e), file=sys.stderr)

    def pick(cli, envs, key, default):
        if cli:
            return cli
        for name in envs:
            if os.environ.get(name):
                return os.environ[name]
        if file_cfg.get(key):
            return file_cfg[key]
        return default

    return {
        'base_url': pick(getattr(args, 'base_url', None), ['DSH_LOCAL_LLM_BASE_URL'],
                         'base_url', LLM_DEFAULT_BASE).rstrip('/'),
        'model': pick(getattr(args, 'model', None), ['DSH_LOCAL_LLM_MODEL'],
                      'model', LLM_DEFAULT_MODEL),
        'api_key': pick(getattr(args, 'api_key', None), LLM_KEY_ENV, 'api_key', ''),
    }


def llm_headers(cfg):
    headers = {'Content-Type': 'application/json'}
    if cfg.get('api_key'):
        headers['Authorization'] = 'Bearer ' + cfg['api_key']
    return headers


def _http_json(url, payload, headers, timeout):
    """POST 一个 JSON、拿一个 JSON 回来。"""
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def llm_list_models(cfg, timeout=20):
    req = urllib.request.Request(cfg['base_url'] + '/models', headers=llm_headers(cfg))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def split_llm_messages(messages):
    """chat 形状的 messages → (instructions, input)。

    Responses 没有 role=system 的位置：规范折进 `instructions`，其余消息进 `input`。
    """
    instructions, items = [], []
    for msg in messages or []:
        role = str(msg.get('role') or 'user')
        content = msg.get('content')
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = '\n'.join(str(p.get('text') or '') for p in content if isinstance(p, dict))
        else:
            text = '' if content is None else str(content)
        if role in ('system', 'developer'):
            if text:
                instructions.append(text)
            continue
        items.append({'role': role, 'content': text})
    return '\n\n'.join(instructions), items


def _responses_finish_reason(data):
    """Responses 的 status/incomplete_details → chat 风格的 finish_reason。"""
    status = data.get('status')
    if status == 'incomplete':
        reason = (data.get('incomplete_details') or {}).get('reason')
        return 'length' if reason == 'max_output_tokens' else (reason or 'incomplete')
    if status == 'failed':
        err = data.get('error') or {}
        return 'error:%s' % (err.get('message') or err.get('code') or 'failed')
    if status == 'completed':
        return 'stop'
    return status


def _responses_texts(data):
    """Responses 的 `output[]` → (正文, 思考链)。"""
    content, reasoning = [], []
    for item in data.get('output') or []:
        if not isinstance(item, dict):
            continue
        kind = item.get('type')
        if kind == 'reasoning':
            for part in item.get('content') or []:
                if isinstance(part, dict) and part.get('text'):
                    reasoning.append(str(part['text']))
            if not reasoning:
                for part in item.get('summary') or []:
                    if isinstance(part, dict) and part.get('text'):
                        reasoning.append(str(part['text']))
        elif kind == 'message':
            for part in item.get('content') or []:
                if isinstance(part, dict) and part.get('text'):
                    content.append(str(part['text']))
    return ''.join(content), ''.join(reasoning)


def build_llm_body(cfg, messages, json_mode=True, stream=False):
    """Responses API 的请求体（规范 → instructions，卡数据 → input）。

    ⚠️ NInfer 实测的硬差别（弄错就是 400）：
      * 输出上限叫 `max_output_tokens`（`max_tokens` 不认）；
      * **没有结构化输出**：`text.format` 只接受 `{"type":"text"}`，`json_object` 回
        400 `structured_outputs_not_supported`。所以 `json_mode` 只为签名兼容，
        JSON 形状靠提示词 + `extract_json` 的解析/重试；
      * 没有 `messages`：system 折进 `instructions`，其余进 `input`；
      * 思考开关是 **`reasoning.effort`**（`none` 关），不是 llama.cpp 的
        `chat_template_kwargs`（NInfer 回 400），也不是顶层 `reasoning_effort`。
    """
    instructions, items = split_llm_messages(messages)
    body = {
        'model': cfg['model'],
        'input': items,
        'temperature': LLM_TEMPERATURE,
        'top_p': LLM_TOP_P,
        'max_output_tokens': LLM_MAX_TOKENS,
        'stream': stream,
        # 本地推理最省 token 的一刀：关掉思考链（NInfer：effort=none）。
        'reasoning': {'effort': 'none'},
    }
    if instructions:
        body['instructions'] = instructions
    return body


def llm_chat(cfg, messages, json_mode=True, timeout=None, stream=True, quiet=False, label=''):
    """直连本地模型，返回 (content, usage, meta)。

    默认走流式：27B Q4 逐张卡就要几十秒，流式能拿到**首字延迟**、并避免
    长时间没有数据导致的读超时；思考链（`response.reasoning_text.delta`）一并收着
    （本脚本已把思考关掉，所以通常为空）。
    """
    url = cfg['base_url'] + LLM_RESPONSES_PATH
    timeout = timeout or LLM_TIMEOUT
    last = ''
    for attempt in range(1, LLM_HTTP_RETRIES + 1):
        t0 = time.time()
        try:
            if stream:
                return _llm_stream(cfg, url, messages, json_mode, timeout, quiet, label, t0)
            data = _http_json(url, build_llm_body(cfg, messages, json_mode, False),
                              llm_headers(cfg), timeout)
            if data.get('status') == 'failed' or data.get('error'):
                err = data.get('error') or {}
                raise LLMError('端点返回失败：%s'
                               % (err.get('message') or err.get('code') or data.get('status')))
            return _pack_response(data, time.time() - t0)
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8', 'replace')[:400]
            except Exception:
                pass
            if e.code in (400, 401, 403, 404):
                raise LLMError('端点返回 HTTP %s：%s\n'
                               '（401/403 → api key 不对；404 → base_url 或模型名不对'
                               '（本脚本打的是 <base_url>/responses）；'
                               '400 看 code：context_length_exceeded → 超窗；'
                               'structured_outputs_not_supported → 不要再发 text.format；'
                               'chat_template_option_not_supported / unknown_parameter → 思考走 reasoning.effort）'
                               % (e.code, body))
            last = 'HTTP %s %s' % (e.code, body)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = '%s: %s' % (type(e).__name__, e)
        except json.JSONDecodeError as e:
            last = '端点返回的不是合法 JSON：%s' % e
        if attempt < LLM_HTTP_RETRIES:
            wait = min(30, 2 ** attempt) + random.random()
            print('    端点失败（%s），%.1fs 后重试 %d/%d'
                  % (last, wait, attempt, LLM_HTTP_RETRIES - 1), file=sys.stderr)
            time.sleep(wait)
    raise LLMError('端点连续 %d 次失败：%s' % (LLM_HTTP_RETRIES, last))


def _pack_response(data, elapsed):
    """Responses 的 `output[]` → (正文, usage, meta)。思考链单独收，不当答案。"""
    content, reasoning = _responses_texts(data)
    usage = data.get('usage') or {}
    meta = {
        'elapsed': elapsed,
        'finish_reason': _responses_finish_reason(data),
        'reasoning_chars': len(reasoning),
        'timings': data.get('timings') or {},
    }
    return content, usage, meta


def _llm_stream(cfg, url, messages, json_mode, timeout, quiet, label, t0):
    """手写 SSE 解析（标准库就够，不用 openai SDK）。

    Responses 的流是**命名事件**：正文在 `response.output_text.delta`（内容在 `delta` 字段），
    结束事件是 `response.completed`（usage 在里面），**没有 `[DONE]`**。
    """
    payload = build_llm_body(cfg, messages, json_mode, True)
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                 headers=llm_headers(cfg))
    content, reasoning, usage, finish = [], [], {}, None
    t_first = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode('utf-8', 'replace').strip()
            if not line or not line.startswith('data:'):
                continue          # `event:` 行跳过：事件名在 data 的 type 里也有
            data = line[5:].strip()
            if data == '[DONE]':
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            etype = obj.get('type') or ''
            if etype == 'response.output_text.delta':
                piece = obj.get('delta')
                if piece:
                    if t_first is None:
                        t_first = time.time() - t0
                        if not quiet:
                            print('    %s首字 %.1fs' % (label, t_first), file=sys.stderr)
                    content.append(piece)
            elif etype == 'response.reasoning_text.delta':
                if obj.get('delta'):
                    reasoning.append(obj['delta'])
            elif etype in ('response.completed', 'response.incomplete', 'response.failed'):
                final = obj.get('response') or {}
                if final.get('usage'):
                    usage = final['usage']
                finish = _responses_finish_reason(final)
                if not content:                       # 兜底：没有 delta 时从整段取
                    text, think = _responses_texts(final)
                    if text:
                        content.append(text)
                    if think and not reasoning:
                        reasoning.append(think)
            elif etype in ('error', 'response.error'):
                finish = 'error'
                print('    %s⚠️ 流里报错：%s' % (label, obj.get('message') or obj), file=sys.stderr)
    meta = {'elapsed': time.time() - t0, 'finish_reason': finish,
            'reasoning_chars': sum(len(x) for x in reasoning),
            'first_token': t_first, 'timings': {}}
    return ''.join(content), usage, meta


def usage_row(usage):
    """把端点给的 usage 压成统一口径（协议不同字段名不同）。

    Responses 只给 `input_tokens`/`output_tokens`/`total_tokens`：**没有**缓存与思考明细，
    所以账本里 `cached_tokens` / `reasoning_tokens` 恒为 0（拿不到，不是没发生）。
    """
    def first(*values):
        for v in values:
            if v is not None:
                return v
        return None

    cached = first(((usage.get('prompt_tokens_details') or {}).get('cached_tokens')),
                   ((usage.get('input_tokens_details') or {}).get('cached_tokens')),
                   usage.get('cache_read_input_tokens'))
    reasoning = first(((usage.get('completion_tokens_details') or {}).get('reasoning_tokens')),
                      ((usage.get('output_tokens_details') or {}).get('reasoning_tokens')),
                      usage.get('reasoning_tokens'))
    return {
        'prompt_tokens': as_int(first(usage.get('prompt_tokens'), usage.get('input_tokens'))),
        'completion_tokens': as_int(first(usage.get('completion_tokens'),
                                          usage.get('output_tokens'))),
        'cached_tokens': as_int(cached),
        'reasoning_tokens': as_int(reasoning),
        'total_tokens': as_int(usage.get('total_tokens')),
    }


# ============================================================================
# 生成的提示词（system = 规范，一次构造、逐请求复用；user = 这张卡的数据）
# ============================================================================
def load_system_prompt(path=None):
    path = path or SYSTEM_PROMPT_FILE
    if not os.path.exists(path):
        raise SystemExit('找不到系统提示词文件：%s' % path)
    with open(path, encoding='utf-8') as fh:
        return fh.read().strip()


# 只把模型真正需要的字段发过去：deck/model/queue_pos/tags 对写讲解没用，
# 每张卡少发几十个 token，10 张卡就是几百。
# `dict` = 发请求前预取的 JMdict 事实（词形/读音/词性/义项/语域），只有词汇卡有。
CARD_PAYLOAD_KEEP = ('id', 'kind', 'level', 'word', 'reading', 'pos', 'meaning',
                     'meaning_jp', 'sentences', 'notes', 'existing', 'dict')


def card_payload(card):
    out = {k: card[k] for k in CARD_PAYLOAD_KEEP if card.get(k) not in (None, '', [], {})}
    if card.get('kind') == 'vocab':
        # 语法卡的 pos 是接续表（要在 structure 里整理）；词汇卡的 pos 是词性标签。
        pass
    return out


def other_words(manifest, cards):
    """给模型一句"今天还有哪些词"——只为让它不要跟同批词讲重复，不带数据。"""
    ids = {c['id'] for c in cards}
    return [c['word'] for c in manifest['cards'] if c['id'] not in ids]


def build_messages(manifest, cards, system_prompt, nudge=None, others=None):
    payload = {
        'date': manifest['date'],
        'cards': [card_payload(c) for c in cards],
    }
    note = []
    note.append('今天是 %s。下面是要讲的卡片数据（JSON）。' % manifest['date'])
    if others:
        note.append('今天同一批里还有这些词，由别的请求负责，**不要**在你的输出里重复讲它们：'
                    + '、'.join(others))
    note.append('')
    note.append('```json')
    note.append(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    note.append('```')
    note.append('')
    note.append('按 system 里的规范输出一个 JSON 对象，`entries` 只包含上面这 %d 张卡（id：%s）。'
                % (len(cards), '、'.join(str(c['id']) for c in cards)))
    if nudge:
        note.append('')
        note.append('⚠️ 上一次的输出不能用：%s。请重新完整输出一遍，只输出 JSON。' % nudge)
    return [{'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': '\n'.join(note)}]


# ============================================================================
# JSON 抢救
# ============================================================================
FENCE = re.compile(r'```(?:json)?\s*(.*?)```', re.S)


def extract_json(raw):
    """从模型输出里抠出一个 JSON 对象。返回 (obj, 说明) 或 (None, 原因)。"""
    if not raw or not raw.strip():
        return None, '回复是空的'
    text = raw.strip()
    m = FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text), ''
    except json.JSONDecodeError:
        pass
    # 去掉可能的前后开场白，取最外层的 { ... }
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        for candidate in (text[start:end + 1],
                          re.sub(r',\s*([\]}])', r'\1', text[start:end + 1])):
            try:
                return json.loads(candidate), '（剥掉了 JSON 之外的内容）'
            except json.JSONDecodeError:
                continue
    return None, '回复里没有合法 JSON（前 200 字：%s）' % text[:200].replace('\n', ' ')


def pick_entries(obj, cards):
    """从模型输出里取出这一批卡的 teach，返回 (entries, 问题描述)。

    顺手把 teach 里的字段整形（见 normalize_teach）——模型偶尔会把 examples 写成
    数组里的字符串、把 usage 写成字符串，渲染器按规范的类型取值会直接崩。
    """
    if not isinstance(obj, dict):
        return {}, '顶层不是 JSON 对象'
    raw = obj.get('entries')
    if not isinstance(raw, dict):
        return {}, '缺少 entries 对象'
    want = [str(c['id']) for c in cards]
    entries, missing = {}, []
    for key in want:
        item = raw.get(key)
        teach = item.get('teach') if isinstance(item, dict) else None
        if not isinstance(teach, dict) or not any(v for v in teach.values()):
            missing.append(key)
        else:
            entries[key] = {'teach': normalize_teach(teach)}
    if missing:
        return entries, '这些卡没有有效讲解：%s' % '、'.join(missing)
    return entries, ''


TEXTY_FIELDS = ('one_line', 'core', 'structure', 'contrast', 'memory', 'pitfall')
LIST_FIELDS = ('usage', 'uses', 'notes')
EX_SPLIT = re.compile(r'\s*(?:——|--|—|\||｜|\t)\s*')


def normalize_teach(teach):
    """把 teach 整形成渲染器认的类型（只做形状转换，不改内容）。"""
    out = {}
    for k, v in teach.items():
        if k in LIST_FIELDS:
            if isinstance(v, str):
                v = [v] if v.strip() else []
            elif not isinstance(v, list):
                v = [v] if v else []
            out[k] = [str(x) for x in v if str(x).strip()]
        elif k == 'examples':
            items = v if isinstance(v, list) else ([v] if v else [])
            exs = []
            for e in items:
                if isinstance(e, dict):
                    jp = e.get('jp') or e.get('ja') or e.get('japanese') or ''
                    cn = e.get('cn') or e.get('zh') or e.get('translation') or ''
                    if jp or cn:
                        exs.append({'jp': str(jp), 'cn': str(cn)})
                elif isinstance(e, str) and e.strip():
                    bits = EX_SPLIT.split(e.strip(), 1)
                    exs.append({'jp': bits[0], 'cn': bits[1] if len(bits) > 1 else ''})
            out[k] = exs
        elif k in TEXTY_FIELDS:
            if isinstance(v, (list, tuple)):
                v = '；'.join(str(x) for x in v if str(x).strip())
            out[k] = v if isinstance(v, str) else ('' if v is None else str(v))
        else:
            out[k] = v
    return out


# ============================================================================
# 请求切批 / 落盘
# ============================================================================
def req_paths(n):
    """第 n 个请求（从 1 开始）的输入卡片、产出、元数据路径。"""
    stem = os.path.join(CARDS_DIR, '%02d' % n)
    return {'in': stem + '_in.json', 'out': stem + '_out.json', 'meta': stem + '_meta.json'}


def make_batches(cards, per_batch):
    """per_batch <= 0 表示不分批（一次全给）。"""
    if per_batch is None or per_batch <= 0:
        return [list(cards)] if cards else []
    return [cards[i:i + per_batch] for i in range(0, len(cards), per_batch)]


def batch_fingerprint(date, ids):
    """一批卡的指纹：批内 noteId 集合的 sha1（前 12 位）。

    批号相同但批内卡变了（改 --per-batch、换 deck、换 --limit、隔天重跑同一天）时，
    指纹对不上 → 旧产出作废，必须重生成；否则会静默漏卡或串卡。
    """
    key = '%s|%s' % (date, ','.join(str(i) for i in sorted(ids)))
    return hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]


def plan_requests(manifest, per_batch):
    """切批 + 落盘每批的卡片数据，返回请求清单（不删已有产出，交接给 gen 判断）。"""
    os.makedirs(CARDS_DIR, exist_ok=True)
    batches = make_batches(manifest['cards'], per_batch)
    reqs = []
    for i, cards in enumerate(batches, 1):
        paths = req_paths(i)
        ids = [c['id'] for c in cards]
        req = {'no': i, 'total': len(batches), 'count': len(cards), 'ids': ids,
               'words': [c['word'] for c in cards],
               'fingerprint': batch_fingerprint(manifest['date'], ids),
               'in': paths['in'], 'out': paths['out'], 'meta': paths['meta']}
        write_json(paths['in'], {'date': manifest['date'], 'req': i, 'total': len(batches),
                                 'fingerprint': req['fingerprint'], 'cards': cards})
        reqs.append(req)
    return reqs


def cleanup_stale_requests(total):
    """删掉上次留下的、编号超出本次请求数的 0N_* 文件（否则 merge 会捡到旧卡）。"""
    removed = []
    if not os.path.isdir(CARDS_DIR):
        return removed
    for name in sorted(os.listdir(CARDS_DIR)):
        m = re.match(r'(\d+)_(in|out|meta)\.json$', name)
        if m and int(m.group(1)) > total:
            os.remove(os.path.join(CARDS_DIR, name))
            removed.append(name)
    return removed


def read_out_file(path, ids):
    """读一个已有的产出文件；卡集对不上就返回 None（= 需要重生成）。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            obj = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    entries = obj.get('entries')
    if not isinstance(entries, dict) or set(entries) != set(map(str, ids)):
        return None
    return obj


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1))


def dated_paths(date):
    return {
        'cards': os.path.join(OUTDIR, 'cards_%s.json' % date),
        'cards_latest': os.path.join(OUTDIR, 'cards_latest.json'),
        'lesson_json': os.path.join(LESSON_DIR, 'lesson_%s.json' % date),
        'lesson_md': os.path.join(OUTDIR, 'lesson_%s.md' % date),
        'lesson_latest': os.path.join(OUTDIR, 'lesson_latest.md'),
        'split': os.path.join(LESSON_DIR, 'split_%s.json' % date),
        'metrics': os.path.join(LESSON_DIR, 'metrics_%s.json' % date),
        'dict': dict_path(date),
    }


# ============================================================================
# 渲染讲义 + 闸门
# ============================================================================
def render_teach(card, teach):
    """把一段 teach 渲染成 Markdown。词汇与语法共用（字段名见规范）。

    词汇卡只出「一句解释 + 一句补充 + 2 条例句」——日常讲义里词汇要短；
    语法卡保持完整讲解。这里对类型再兜一层：teach 来自模型，形状不保证。
    """
    teach = normalize_teach(teach) if isinstance(teach, dict) else {}
    vocab = card['kind'] == 'vocab'
    lines = []

    def para(label, value):
        if value:
            lines.append('**%s**：%s' % (label, value))
            lines.append('')

    def bullet(label, items):
        items = [t for t in (items or []) if t]
        if items:
            lines.append('**%s**' % label)
            for t in items:
                lines.append('- ' + t)
            lines.append('')

    if teach.get('one_line'):
        lines.append('> ' + teach['one_line'])
        lines.append('')
    if vocab:
        para('说明', teach.get('core'))
    else:
        # 接续也过一遍 clean_structure：模型偶尔会写「动词る形」，统一成「动词辞书形」
        para('接续', clean_structure(teach.get('structure') or ''))
        para('核心含义', teach.get('core'))
        bullet('什么时候用', teach.get('uses'))

    examples = [e for e in (teach.get('examples') or []) if e and (e.get('jp') or e.get('cn'))]
    if examples:
        lines.append('**例句**' if vocab else '**我造的例句**')
        for ex in (examples[:2] if vocab else examples):
            jp = (ex.get('jp') or '').strip()
            cn = (ex.get('cn') or '').strip()
            lines.append('- %s%s' % (jp, ('　—— ' + cn) if cn else ''))
        lines.append('')

    if not vocab:
        para('与相近句型的区别', teach.get('contrast'))
        para('易错点', teach.get('pitfall'))
    return lines


# ============================================================================
# 讲义口径：统一计数 / 清洗脏数据（2026-10-24 复审）
# ============================================================================
# 复审的 17 条里有一半不是「模型写错了」，而是**卡片数据脏 + 渲染没兜住**：
#   词形与读音对不上（词形 `こ` / 读音 `あそこ`）、词性标错（`ん` 标成副词）、
#   同词重复（`うっ` / `ウッ`）、语法接续夹着注音（`動どう 詞しの`）、
#   开头的数字和实际条目对不上。这些都能机械判断，不该每次都靠模型自觉。
# 原则：**能确定对错的就机械处理（合并/校正/隐藏/截断），只是可疑的就标注**，
# 绝不静默改写讲解内容。

TRAILING_KANA = re.compile(r'[\u3040-\u309f]+$')
CJK_SPACE_CJK = re.compile(r'[\u4e00-\u9fff\u3040-\u309f][\u3000 ]+[\u4e00-\u9fff\u3040-\u309f]')

# 词性统一成中文体系（卡片里混着 他動1 / Verb / Verbal Noun / Noun）
POS_NAMES = {
    '他動1': '他动词1类', '他動2': '他动词2类', '他動3': '他动词3类',
    '他动1': '他动词1类', '他动2': '他动词2类', '他动3': '他动词3类',
    '自動1': '自动词1类', '自動2': '自动词2类', '自動3': '自动词3类',
    '自动1': '自动词1类', '自动2': '自动词2类', '自动3': '自动词3类',
    'Verb': '动词', 'Verbal Noun': '动词性名词', 'Noun': '名词', 'Adverb': '副词',
    '名': '名词', '名词': '名词', '副': '副词', '副词': '副词',
    '接尾・名': '接尾辞（名词）',
    '形': '形容词', '形容词': '形容词', 'イ形容词': 'イ形容词', 'ナ形容词': 'ナ形容词',
    '惯用句': '惯用句', '慣用句': '惯用句', '感叹词': '感叹词', '感動詞': '感叹词',
    '终助词': '终助词', '助词': '助词', '接续词': '接续词',
}
# 复审点名的错标：这些词不是副词/惯用句
INTERJECTION_WORDS = ('あっ', 'あー', 'アー', 'うっ', 'ウッ', 'んっ', 'え', 'えっ', 'よし')
FINAL_PARTICLE_WORDS = ('ん', 'もん')
SUSPECT_POS = ('', '副词', '副', '惯用句', '慣用句')

# 语法接续里常见的记号写法 → 中文词性说法（只做等价替换，不改结构）
STRUCT_REPLACE = (
    ('する動詞の', '动词的'), ('する動詞', '动词'), ('動詞', '动词'),
    ('ナＡ', 'ナ形容词'), ('イＡ', 'イ形容词'),
    ('Ｖる形', '动词辞书形'), ('动词る形', '动词辞书形'), ('Ｖる', '动词辞书形'),
    ('Ｖた形', '动词た形'), ('Ｖて形', '动词て形'), ('Ｖない形', '动词ない形'),
    ('Ｖ', '动词'), ('Ｎ', '名词'), ('Ａ', '形容词'),
)


def hira_text(text):
    """片假名 → 平假名（只用于比较，不用于显示）。"""
    return ''.join(chr(ord(ch) - 0x60) if '\u30a1' <= ch <= '\u30f6' else ch
                   for ch in (text or ''))


def kana_key(text):
    """归一化后的假名键：平/片假名、空格、标点、浊音差异都不算区别。"""
    t = re.sub(r'[\s\u3000]+', '', hira_text(text))
    t = re.sub(r'[（）()\[\]【】「」『』・、。,.!?！？〜～~:：/／]', '', t)
    return t.replace('ぢ', 'じ').replace('づ', 'ず').replace('を', 'お').replace('ゔ', 'ぶ')


def is_kana_only(text):
    return bool(KANA_ONLY.match((text or '').strip()))


def reading_problem(word, reading):
    """词形与读音的**机械矛盾**；返回人话原因，看起来没问题就返回 ''。

    只报能证伪的：纯假名词读音对不上、读音里混进汉字、送假名对不上。
    读音本身选得对不对（上＝かみ/うえ）脚本判断不了——那类靠例句读音闸门。
    """
    w = (word or '').strip()
    r = (reading or '').strip()
    if not w or not r:
        return ''
    if KANJI.search(r):
        return '读音里混进了汉字'
    wn, rn = kana_key(w), kana_key(r)
    if not rn:
        return ''
    if is_kana_only(wn) and is_kana_only(rn) and wn != rn:
        return '词形是假名「%s」，读音却写「%s」' % (w, r)
    if KANJI.search(w):
        tail = TRAILING_KANA.search(w)
        if tail and not rn.endswith(kana_key(tail.group(0))):
            return '送假名对不上（词形「%s」/ 读音「%s」）' % (w, r)
    return ''


def pos_label(raw):
    """词性显示名：统一成中文体系（他動1→他动词1类、Verb→动词…）。"""
    raw = (raw or '').strip()
    if not raw:
        return ''
    if raw in POS_NAMES:
        return POS_NAMES[raw]
    m = re.match(r'^(他動|自動|他动|自动)([123])$', raw)
    if m:
        return '%s词%s类' % ('他动' if m.group(1).startswith('他') else '自动', m.group(2))
    parts = re.split(r'[/／、]', raw)
    if len(parts) > 1:
        return '／'.join(pos_label(p) for p in parts if p.strip())
    return raw


def display_pos(card, dinfo=None):
    """返回 (显示用词性, 是否按语言事实校正过)。

    优先级：**JMdict**（词典判定卡片词性冲突且能唯一确定）> 复审点名的硬编码校正
    > 卡片原值。`dinfo` 是 jmdict_check.check_card() 的结果；没有词典时行为不变。
    硬编码只兜住 JMdict 收不全的几个句末助词/感叹词（`ん`/`もん`/`え`）。
    """
    pos = pos_label(card.get('pos') or '')
    if card.get('kind') != 'vocab':
        return pos, False
    if dinfo:
        fix = (dinfo.get('pos_fix') or '').strip()
        if fix:
            return fix, pos != fix
    w = (card.get('word') or '').strip()
    if (card.get('pos') or '').strip() not in SUSPECT_POS:
        return pos, False
    if w in INTERJECTION_WORDS:
        return '感叹词', pos != '感叹词'
    if w in FINAL_PARTICLE_WORDS:
        return '终助词', pos != '终助词'
    return pos, False


def clean_structure(raw):
    """把语法接续整理成一行可背的中文：去标签/去注音、压空格、记号换说法。"""
    s = strip_ruby_readings(raw or '')   # 先整块删 <rt>，否则会留下「漢かん」
    s = re.sub(r'\[([\u3040-\u309f\u30a0-\u30ffー]+)\]', '', s)   # 動[どう] → 動
    s = re.sub(r'[\s\u3000]+', ' ', s).strip()
    for a, b in STRUCT_REPLACE:
        s = s.replace(a, b)
    s = re.sub(r'\s*([＋+／/、，,])\s*', r'\1', s)
    return s.strip(' 　·')


def structure_looks_garbled(text):
    """接续字段里「汉字/假名之间夹空格」= 注音被拍平成了正文（動どう 詞しの）。"""
    return bool(CJK_SPACE_CJK.search(text or ''))


def grammar_structure(card, teach):
    """接续的显示文本 + 状态：'' 正常 / 'fallback' 用卡片字段 / 'dirty' 都不可信。"""
    cand = clean_structure((teach or {}).get('structure') or '')
    if cand and not structure_looks_garbled(cand):
        return cand, ''
    raw = clean_structure(card.get('pos') or '')
    if raw and not structure_looks_garbled(raw):
        return raw, 'fallback'
    return '—', 'dirty'


def group_vocab(cards):
    """把**纯假名**的同词形条目并成一条（うっ / ウッ、あー / アー）。

    只并在假名词之间：会う / 合う 这种汉字不同的词绝不能并（读音一样也不是同一个词）。
    返回 [(主条目, [变体…]), …]，顺序不变。
    """
    groups, where = [], {}
    for c in cards:
        w = (c.get('word') or '').strip()
        key = kana_key(w) if is_kana_only(w) else w
        if key and key in where:
            groups[where[key]][1].append(c)
            continue
        if key:
            where[key] = len(groups)
        groups.append((c, []))
    return groups


def clip_sentence(text, limit=160):
    """取第一句/第一行，超长时按**句末标点**截断（绝不截在半个词上）。"""
    line = re.split(r'\n', (text or '').strip())[0]
    line = re.sub(r'\s+', ' ', line).strip()
    if len(line) <= limit:
        return line
    cut = 0
    for m in re.finditer(r'[。！？!?]', line[:limit]):
        cut = m.end()
    if cut < 20:
        cut = line.rfind('、', 0, limit)
        if cut > 20:
            cut += 1
    if cut < 20:
        return line[:limit] + '…（后略）'
    return line[:cut] + '（后略）'


def unfinished_text(text):
    """这句话明显没写完：停在开引号/开括号/顿号/冒号，或用「…」糊过去。"""
    t = (text or '').strip()
    if not t:
        return False
    if t.endswith('…'):
        return True
    return t[-1] in '「『（(【、，,：:'


REDUNDANT_AMOUNT = re.compile(r'(?:大约|大概|约|将近|差不多)[^，。；]{0,10}(?:左右|上下)')
SELF_COMPARE = re.compile(r'比\s*[「『“"]([^」』”"]{1,12})[」』”"]\s*(?:更|还)')


def redundant_cn(cn):
    """中文翻译语义重复：「大约一百日元左右」「大概十点左右」。"""
    return bool(REDUNDANT_AMOUNT.search(cn or ''))


def self_compare(text, word):
    """拿目标词跟它自己比：「比『想像』更常用」——比较对象就是目标词本身。"""
    word_key = kana_key(word)
    for m in SELF_COMPARE.finditer(text or ''):
        quoted = m.group(1).strip()
        if quoted == (word or '').strip() or (word_key and kana_key(quoted) == word_key):
            return True
    return False


def teach_issues(card, teach):
    """模型写出来的内容里**机械可判**的错。返回人话列表（空 = 没问题）。

    这些错在 `gen` 里会被当成重试理由（同一条最多重来 retries_per_card 次），
    跑完 `merge` 时再报一次。判断不了「日语自不自然」，只抓能证伪的形态问题。
    """
    issues = []
    word = card.get('word') or ''
    seen_jp = []
    for ex in (teach.get('examples') or []):
        if not isinstance(ex, dict):
            continue
        jp = (ex.get('jp') or '').strip()
        cn = (ex.get('cn') or '').strip()
        if not jp or looks_like_labeled_prose(jp):
            continue
        if not example_uses_target(card, jp):
            issues.append('例句「%s」没有用上目标词' % jp[:40])
            continue
        seen_jp.append(jp)
        if not cn:
            issues.append('例句「%s」没有中文翻译' % jp[:30])
        elif redundant_cn(cn):
            issues.append('中文翻译「%s」语义重复（「大约」和「左右」只能留一个）' % cn)
        if unfinished_text(jp) or unfinished_text(cn):
            bad = jp if unfinished_text(jp) else cn
            issues.append('「%s」没写完（结尾停在「%s」）' % (bad[:30], bad.strip()[-1]))
    if len(seen_jp) != len(set(seen_jp)):
        issues.append('两条例句一模一样，等于只讲了一个场景')
    for field, label in (('one_line', '一句解释'), ('core', '语感补充')):
        text = teach.get(field)
        text = text.strip() if isinstance(text, str) else ''
        if not text:
            continue
        if unfinished_text(text):
            issues.append('%s没写完（结尾停在「%s」）' % (label, text[-1]))
        if self_compare(text, word):
            issues.append('%s拿「%s」跟它自己比（「比『%s』更常用」讲不通）'
                          % (label, word, word))
    return issues


def core_word_seen(word, sentence):
    """例句卡的核心词在句子里出现过吗（允许词典形 vs 活用形）。

    汉字词按词干比（送る → 送った）；假名词按归一化整词比。
    """
    w = re.sub(r'[（(].*?[）)]', '', word or '').strip()
    if not w:
        return True
    if w in sentence:
        return True
    stem = TRAILING_KANA.sub('', w)
    if stem and len(stem) >= 2 and stem in sentence:
        return True
    key = kana_key(w)
    return bool(key) and is_kana_only(key) and key in kana_key(sentence)


def light_card_issues(card):
    """例句卡（讲解来自卡片自带的 AINote）里机械可判的毛病。"""
    out = []
    light = card.get('light') or {}
    # jp_ruby 是 HTML（<ruby>漢<rt>かん</rt></ruby>）：先整块删 <rt>，否则会拼成「漢かん」
    sentence = strip_ruby_readings(light.get('jp_ruby') or '') or card.get('word') or ''
    for p in light.get('points') or []:
        head, sep, body = p.partition('：')
        # 视频例句卡的要点带「核心词汇：」前缀；语法例句卡的 CNote 往往没有前缀
        label = head if (sep and head in ('核心词汇', '语法要点', '要点')) else '要点'
        if label == '核心词汇':
            w = re.split(r'[：:。，、／/]', body, 1)[0].strip()
            if w and not core_word_seen(w, sentence):
                out.append('核心词汇「%s」在本句里找不到' % w)
        if p.rstrip().endswith(('…', '「', '（')):
            out.append('%s这条讲解没写完（结尾停在「%s」）' % (label, p.rstrip()[-1]))
        # 「意为『觉得一定是～』」= 既“觉得”又“一定”，自相矛盾（复审点名）
        m = re.search(r'觉得[^。！？]{0,12}一定|一定[^。！？]{0,12}觉得', p)
        if m:
            out.append('%s表述自相矛盾（「%s」里既说「觉得」又说「一定」）'
                       % (label, m.group(0)))
    return out


def _sentence_warnings(word, points, jp_ruby):
    """make_card 里用：只拿刚拼好的要点和句子做检查，不必构造整张卡。"""
    return light_card_issues({'word': word,
                              'light': {'points': points, 'jp_ruby': jp_ruby}})


def light_sentences(card):
    """按卡模板序号挑出今天真正会看到的那几句例句。

    这套语法例句模型的模板就是「第 N 句例句」的展示卡（Card 02 = 例句①，…），
    所以 ord=N → Sentence{N}；ord=0 是解释卡（全句都列）。
    """
    sents = card.get('sentences') or []
    ords = sorted({o for o in (card.get('card_ords') or []) if o > 0})
    if not ords:
        return sents
    out = [sents[o - 1] for o in ords if 1 <= o <= len(sents)]
    return out or sents


def cell(text):
    """Markdown 表格单元格：竖线换全角、换行压平，空值显示 —。"""
    t = re.sub(r'\s+', ' ', str(text or '')).strip()
    return t.replace('|', '｜') or '—'


def render_light_card(card, A):
    """轻量渲染一条例句卡：句子（带振假名）+ 中文 + 要点一行，内容全部来自卡片本身。"""
    light = card.get('light') or {}
    if card['kind'] == 'sentence':
        A('### %s' % card['word'])
        A('')
        if light.get('jp_ruby'):
            A(light['jp_ruby'])
            A('')
        if light.get('cn'):
            A('中文：%s' % light['cn'])
            A('')
        for p in light.get('points') or []:
            A('- %s' % p)
        # warnings 在 plan 时算过一次；旧 manifest 里没有就现算（merge 老卡片数据也不漏）。
        warns = light.get('warnings')
        if warns is None:
            warns = light_card_issues(card)
        for w in warns or []:
            A('- ⚠️ %s（讲解来自卡片 AINote，建议核对或补全后改卡）' % w)
        if light.get('points') or warns:
            A('')
        if light.get('source'):
            A('*%s*' % light['source'])
            A('')
        return
    # 语法例句卡
    A('### %s　`%s`' % (card['word'], card['level']))
    A('')
    head = '中文 **%s**' % (card['meaning'] or '—')
    struct = clean_structure(card.get('pos') or '')
    if struct and not structure_looks_garbled(struct):
        head += '｜接续 %s' % struct
    A(head)
    A('')
    sents = light_sentences(card)
    if sents:
        A('**今天要看的 %d 句**' % len(sents))
        A('')
        for s in sents:
            A('- %s%s' % (s['ruby'] or s['jp'], ('　—— ' + s['cn']) if s['cn'] else ''))
        A('')
    for p in light.get('points') or []:
        A('**要点**：%s' % p)
        A('')
    warns = light.get('warnings')
    if warns is None:
        warns = light_card_issues(card)
    for w in warns or []:
        A('> ⚠️ %s（要点来自卡片自带讲解，建议核对后改卡）' % w)
        A('')


def dict_card(dinfo, card):
    """取某张卡的词典核验结果（没有就返回空 dict）。"""
    return (dinfo or {}).get(str(card.get('id'))) or {}


def dict_reading_issue(dinfo, card):
    """卡片读音被 JMdict 判成错时返回那条 issue；否则 None。"""
    for iss in dict_card(dinfo, card).get('issues') or []:
        if iss.get('field') == 'reading' and iss.get('level') == 'error':
            return iss
    return None


def render_lesson(manifest, lesson, dinfo=None):
    """渲染讲义。

    `dinfo` = {卡片 id: jmdict_check.check_card() 结果}；给了就用词典校正
    词性、隐藏读音错误并就地标注；不给则退回纯卡片字段（旧行为）。
    """
    cards = manifest['cards']
    counts = manifest['counts']
    vocab = [c for c in cards if c['kind'] == 'vocab']
    grammar = [c for c in cards if c['kind'] == 'grammar' and c.get('style') != 'light']
    light = [c for c in cards if c['kind'] == 'sentence' or
             (c.get('style') == 'light' and c['kind'] != 'sentence')]
    entries = (lesson or {}).get('entries', {}) or {}
    date = manifest['date']

    # 口径：先按「讲义条目」分组，所有计数都从这里派生 —— 开头的数字、表格行数、
    # 来源表的合计必须是同一份数据算出来的（复审点名的「5 / 5 / 7 组」对不上就出在这）。
    vgroups = group_vocab(vocab)
    video = [c for c in light if c['kind'] == 'sentence']
    gram_ex = [c for c in light if c['kind'] != 'sentence']
    n_v, n_g = len(vgroups), len(grammar)
    n_v_cards = sum(1 + len(v) for _, v in vgroups)
    n_merged = sum(len(v) for _, v in vgroups)
    n_sent = sum(len(light_sentences(c)) for c in gram_ex) + len(video)
    n_entries = n_v + n_g + len(light)
    n_notes = sum(st.get('taken_notes', st['taken']) for st in manifest['decks'])
    pos_fixed, pos_fixed_dict, dirty_struct, bad_reading = [], [], [], []
    parts = []
    A = parts.append

    A('# 今日新卡讲义 · %s' % date)
    A('')
    A('共 %d 张卡（词汇 %d / 语法 %d / 例句 %d）｜%d 条讲解'
      '（词汇 %d · 语法 %d · 例句卡 %d 组 / %d 句）｜生成于 %s'
      % (counts['total'], counts['vocab'], counts['grammar'], counts.get('sentence', 0),
         n_entries, n_v, n_g, len(light), n_sent, manifest['generated_at']))
    A('')
    if lesson and lesson.get('intro'):
        A(lesson['intro'])
        A('')

    # ---- 导航：先扫一遍 ----
    A('## 今日新卡一览')
    A('')
    if vgroups:
        A('**词汇 %d 条 / %d 张卡**' % (n_v, n_v_cards))
        A('')
        A('| # | 词形 | 读音 | 词性 | 释义 | 级别 |')
        A('|---|---|---|---|---|---|')
        for i, (c, variants) in enumerate(vgroups, 1):
            names = []
            for item in [c] + variants:
                if item['word'] not in names:
                    names.append(item['word'])
            rp = reading_problem(c['word'], c.get('reading') or '')
            drp = dict_reading_issue(dinfo, c)
            pos, _fixed = display_pos(c, dict_card(dinfo, c))
            A('| %d | %s | %s | %s | %s | %s |'
              % (i, cell(' / '.join(names)),
                 cell('—' if (rp or drp) else (c.get('reading') or '')),
                 cell(pos), cell(c.get('meaning') or ''), cell(c.get('level') or '')))
        A('')
    if grammar:
        A('**语法点 %d 条 / %d 张卡**（语法单元的例句卡在「例句卡」一节展开）' % (n_g, len(grammar)))
        A('')
        A('| # | 句型 | 中文 | 接续 | 级别 |')
        A('|---|---|---|---|---|')
        for i, c in enumerate(grammar, 1):
            teach = (entries.get(str(c['id'])) or {}).get('teach') or {}
            struct, _st = grammar_structure(c, teach)
            A('| %d | %s | %s | %s | %s |'
              % (i, cell(c['word']), cell(c.get('meaning') or ''),
                 cell(struct), cell(c.get('level') or '')))
        A('')
    if light:
        A('**例句卡 %d 组 / %d 句**（视频例句 %d 组 · 语法例句卡 %d 组）'
          % (len(light), n_sent, len(video), len(gram_ex)))
        A('')
        A('| # | 例句卡 | 中文 | 卡数 |')
        A('|---|---|---|---|')
        for i, c in enumerate(light, 1):
            A('| %d | %s | %s | %s |'
              % (i, cell(c['word']), cell(c.get('meaning') or ''), cell(c.get('n_cards') or 1)))
        A('')
    A('> 口径：「张卡」按卡数（同一笔记的多张卡各算一张）；「条讲解」按讲义条目'
      '（同词形的平/片假名条目已合并）。以上三个小标题加起来 = 开头的「%d 条讲解」。' % n_entries)
    A('')

    # ---- 正文：词表 ----
    if vgroups:
        A('## 词表')
        A('')
        for primary, variants in vgroups:
            teach = (entries.get(str(primary['id'])) or {}).get('teach') or {}
            if not teach:
                for v in variants:
                    alt = (entries.get(str(v['id'])) or {}).get('teach') or {}
                    if alt:
                        teach = alt
                        break
            names = []
            for item in [primary] + variants:
                if item['word'] not in names:
                    names.append(item['word'])
            raw_reading = primary.get('reading') or ''
            dcard = dict_card(dinfo, primary)
            rp = reading_problem(primary['word'], raw_reading)
            drp = dict_reading_issue(dinfo, primary)
            if rp:
                bad_reading.append((primary['word'], raw_reading, rp))
            A('### %s%s　`%s`' % (' / '.join(names),
                                 '（%s）' % raw_reading if raw_reading and not (rp or drp) else '',
                                 primary['level']))
            A('')
            pos, fixed = display_pos(primary, dcard)
            if fixed:
                pos_fixed.append(primary['word'])
                if dcard.get('pos_fix'):
                    pos_fixed_dict.append((primary['word'], pos))
            A('%s｜**%s**' % (pos or '—', primary.get('meaning') or '—'))
            A('')
            if rp or drp:
                bits = []
                if rp:
                    bits.append('卡片读音字段写「%s」，与词形「%s」对不上：%s'
                                % (raw_reading, primary['word'], rp))
                if drp:
                    bits.append('JMdict 判定：%s' % drp['message'])
                A('> ⚠️ %s。已隐藏读音；这张卡可能挖错了，'
                  '建议回 Anki 把词形／读音／释义三者对一遍。' % '；'.join(bits))
                A('')
            if variants:
                same = [v['word'] for v in variants if v['word'] != primary['word']]
                if same:
                    A('> 表记变体：%s（同一个词；Anki 里是多张卡，讲义合并为一条）'
                      % '、'.join(same))
                else:
                    A('> 重复卡：Anki 里同一词形有 %d 张（讲义合并为一条）' % (1 + len(variants)))
                A('')
            lines = render_teach(primary, teach)
            if lines:
                A('\n'.join(lines))
            else:
                A('> ⚠️ 本次没有为这张卡生成讲解。')
                A('')
        if pos_fixed:
            hard = [w for w in pos_fixed if w not in {x for x, _p in pos_fixed_dict}]
            note = '> 词性说明：%s 的词性已按语言事实校正' % '、'.join(pos_fixed)
            # 只列今天这批卡里实际走了硬编码兜底表的词；
            # 别把 INTERJECTION_WORDS 全表（如「よし」）抄进脚注——卡里没有它，列出来就是误导
            interj = sorted({w for w in hard if w in INTERJECTION_WORDS})
            finp = sorted({w for w in hard if w in FINAL_PARTICLE_WORDS})
            bits = []
            if finp:
                bits.append('`%s`＝终助词' % '／'.join(finp))
            if interj:
                bits.append('`%s`＝感叹词' % '／'.join(interj))
            if bits:
                note += '（%s）' % '，'.join(bits)
            if pos_fixed_dict:
                note += '；其中 %s 由 JMdict 判定（词典词性：%s）' % (
                    '、'.join(w for w, _p in pos_fixed_dict),
                    '／'.join(sorted({p for _w, p in pos_fixed_dict})))
            note += '；Anki 词性字段里写的是「%s」，建议回改卡片。' % (
                '／'.join(sorted({(c.get('pos') or '空') for c in vocab
                                  if c['word'] in pos_fixed})) or '空')
            A(note)
            A('')

    # ---- 正文：语法 ----
    if grammar:
        A('## 语法')
        A('')
        for c in grammar:
            teach = (entries.get(str(c['id'])) or {}).get('teach') or {}
            struct, st = grammar_structure(c, teach)
            if st == 'dirty':
                dirty_struct.append(c['word'])
            A('### %s　`%s`' % (c['word'], c['level']))
            A('')
            A('中文 **%s**%s｜来自 `%s`'
              % (c.get('meaning') or '—',
                 '｜接续 %s' % struct if struct else '',
                 c['deck_short']))
            A('')
            if st == 'dirty':
                A('> ⚠️ 这张卡的接续字段是脏数据（汉字夹着注音），已显示为「—」；'
                  '补跑 `gen --only-words "%s" --restart` 让模型重新整理。' % c['word'])
                A('')
            lines = render_teach(c, teach)
            if lines:
                A('\n'.join(lines))
            else:
                A('> ⚠️ 本次没有为这张卡生成讲解。')
                A('')
            A('**Anki 自带例句**')
            A('')
            if c['sentences']:
                for s in c['sentences']:
                    A('- %s' % (s['ruby'] or s['jp']))
                    if s['cn']:
                        A('  - %s' % s['cn'])
            else:
                A('- （这张卡没有配例句）')
            A('')

    if light:
        A('## 例句卡')
        A('')
        A('**共 %d 组 / %d 句**：视频例句 %d 组 · 语法例句卡 %d 组 %d 句'
          % (len(light), n_sent, len(video), len(gram_ex), n_sent - len(video)))
        A('')
        A('> 这些卡自带讲解（视频例句的 AINote / 语法例句的结论），这里只列今天要看的内容，'
          '不另写讲解。')
        A('')
        for c in light:
            render_light_card(c, A)

    A('## 今日自测')
    A('')
    A('1. 合上讲义，把上面每个词/句型的中文意思默写一遍。')
    A('2. 每个词自己想一个句子，再对照讲义的「例句」。')
    A('3. 打开 Anki 学这批卡时，注意哪些是刚才没记住的，记下来明天回看。')
    A('')
    A('## 本讲义的卡片来源')
    A('')
    A('| 卡型 | 学习单元（deck） | 模型 | 今日取卡（张） | 笔记（条） | 上限 | 上限来源 |')
    A('|---|---|---|---|---|---|---|')
    for st in manifest['decks']:
        A('| %s | %s | %s | %d | %d | %s | %s |'
          % ({'vocab': '词汇', 'grammar': '语法', 'sentence': '例句'}.get(st['kind'], st['kind']),
             cell(st['deck'].replace('0-日本语学习::', '')), cell(st.get('model') or ''),
             st['taken'], st.get('taken_notes', st['taken']), st['limit'],
             cell(st.get('limit_source', ''))))
    A('| 合计 | — | — | %d | %d | — | — |' % (counts['total'], n_notes))
    A('')
    A('> 本讲义 %d 条讲解 = 词汇 %d 条（%d 张卡，同词形合并 %d 条）＋ 语法 %d 条 ＋ 例句卡 %d 组。'
      % (n_entries, n_v, n_v_cards, n_merged, n_g, len(light)))
    A('> 取卡口径 = Anki 首页的今日新卡队列（父 deck 的日上限生效，同一笔记的多张卡算 1 条笔记）。')
    A('> 退路：讲义只是文本，删掉重跑即可；本脚本从不写 Anki。')
    A('')
    return '\n'.join(parts)


def check_coverage(manifest, lesson):
    """闸门：逐张覆盖 + 不许留空 teach + date 要对得上。"""
    problems = []
    if not isinstance(lesson, dict):
        return ['lesson JSON 顶层不是对象']
    entries = lesson.get('entries')
    if not isinstance(entries, dict):
        return ['lesson JSON 缺少 entries 对象']
    if lesson.get('date') and str(lesson['date']) != str(manifest['date']):
        problems.append('lesson 的 date=%s 与今天的 %s 不一致' % (lesson['date'], manifest['date']))
    want = [str(c['id']) for c in manifest['cards']]
    missing = [i for i in want if i not in entries]
    extra = [i for i in entries if i not in set(want)]
    if missing:
        problems.append('有 %d 张卡没有讲解：%s' % (len(missing), ', '.join(missing)))
    if extra:
        problems.append('多出 %d 个不属于今天的 id：%s' % (len(extra), ', '.join(extra)))
    empty = []
    for i in want:
        item = entries.get(i)
        teach = item.get('teach') if isinstance(item, dict) else None
        if i in entries and (not isinstance(teach, dict)
                             or not any(v for v in teach.values())):
            empty.append(i)
    if empty:
        problems.append('有 %d 张卡的 teach 是空的：%s' % (len(empty), ', '.join(empty)))
    return problems


def plain_for_gate(text):
    """闸门用的纯文本：先整块删 <rt>…</rt>，再剥其余标签。"""
    return strip_ruby_readings(text)


def check_render(text, manifest):
    """渲染后的讲义再做一次粗糙闸门：占位符、词形是否都出现。

    比对的是**去掉振假名标签**后的纯文本：正文渲染成 <ruby>漢字<rt>…</rt></ruby>
    之后逐字比对永远为假。词形被截断（末尾带 …）时只比前 12 字。
    """
    problems = []
    left = PLACEHOLDER.findall(text)
    if left:
        problems.append('讲义里残留占位符 %d 处：%s' % (len(left), ', '.join(sorted(set(left))[:5])))
    plain = plain_for_gate(text)
    missing = []
    for c in manifest['cards']:
        key = (c['word'] or '').rstrip('…')[:12]
        if key and key not in plain:
            missing.append(c['word'])
    if missing:
        problems.append('讲义正文里找不到这些词形：%s' % ', '.join(missing[:10]))
    return problems


def local_entries(manifest):
    """轻量卡（视频例句 / 语法例句）的讲义条目：不调模型，直接用卡片自带的内容。

    这些卡的 AINote / CNote 里本来就有中文翻译和要点，render_light_card 直接
    从卡片的 light 字段渲染，这里的 teach 只是为了让覆盖闸门认账。
    """
    out = {}
    for c in manifest['cards']:
        if c.get('style') != 'light':
            continue
        light = c.get('light') or {}
        out[str(c['id'])] = {'teach': {
            'one_line': light.get('cn') or c.get('meaning') or c['word'],
            'source': light.get('source') or '卡片自带讲解',
        }}
    return out


# 「这个词在这句里真的用上了吗」——机械可查。
# 实测本地模型偶尔会造出不含目标词的例句（例：给「〜あまり」造了「節約しすぎて…」，
# 还自己加了一句「注：此句为错误用法示例」）。这类句子对学习者是干扰，必须报出来。
KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30a0-\u30ffー]+$')


def target_forms(card):
    """目标词的可接受写法：原词 + 读音，再各自取最长的汉字/假名片段。"""
    forms = set()
    for raw in (card.get('word') or '', card.get('reading') or ''):
        if not raw:
            continue
        forms.add(raw)
        # 去掉「〜」「～」「【】」这类修饰，只留词本身
        core = re.sub(r'[（）()\[\]【】\s]', '', raw).strip('〜～~-—–')
        if core:
            forms.add(core)
    forms.discard('')
    return forms


def example_uses_target(card, jp):
    """例句里是否出现目标词（任一可接受写法）。纯假名词要求整词出现。"""
    jp = jp or ''
    if not jp:
        return False
    for form in target_forms(card):
        if form in jp:
            return True
        if KANA_ONLY.match(form) and len(form) >= 2:
            # 假名词条也要认活用形：ひく → ひいて / ひかれた。
            # 两字假名词（ひく/あう）只能看「首字 + 一个假名」，宁可放过也别误报。
            stem = form[:-1]
            if len(stem) >= 2 and stem in jp:
                return True
            if len(form) == 2 and re.search(re.escape(form[0]) + r'[\u3040-\u309f]', jp):
                return True
        # 汉字词允许只出现词干：動詞「引き落とす」→ 例句里是「引き落とされた」。
        # 词干只剩一个汉字也算（「申す」→「申します」、「見る」→「見た」）：
        # 这类两字词干本就只有一个汉字，硬要求 ≥2 字会把正确例句误报成没用上目标词。
        if not KANA_ONLY.match(form) and len(form) >= 2:
            stem = form.rstrip('するるうつくぶむぬぐずふ')
            if stem and stem in jp:
                return True
    return False


# 模型偶尔把某条 examples 写成「pitfall：……」这种**把说明文字塞进例句字段**的形态
# （内容正确、位置错）。那不是例句，不该按"没用上目标词"报警。
FIELD_LABEL = re.compile(r'^\s*(one_line|core|usage|uses|structure|contrast|memory|'
                         r'pitfall|examples?|notes?|例句|用法|易错点|记忆|接续|释义)\s*[:：]')


def looks_like_labeled_prose(jp):
    return bool(FIELD_LABEL.match(jp or ''))


def check_quality(manifest, lesson, dinfo=None):
    """报告（不拦讲义）：讲义的**内容层**还有哪些机械可判的问题。

    分三类，都来自复审：
      * 卡片数据：词形/读音对不上、语法接续是脏数据；
      * 模型讲解：例句没用上目标词、中文语义重复、拿目标词自比、句子没写完；
      * 例句卡数据：核心词不在句子里、要点被截断。
    讲义里已经逐处标注（读音隐藏、⚠️ 行、接续显示「—」），这里再集中报一次，
    方便决定要不要 `gen --only-words … --restart` 或回改 Anki 卡片。

    `dinfo` 只用来**去重**：JMdict 已经判过的读音错不再重复报一遍。
    """
    entries = (lesson or {}).get('entries') or {}
    issues, seen = [], set()

    def add(msg):
        if msg not in seen:
            seen.add(msg)
            issues.append(msg)

    for card in manifest['cards']:
        teach = (entries.get(str(card['id'])) or {}).get('teach') or {}
        if not isinstance(teach, dict):
            teach = {}
        dres = (dinfo or {}).get(str(card['id'])) or {}
        dict_read_err = any(i.get('field') == 'reading' and i.get('level') == 'error'
                            for i in dres.get('issues') or [])
        rp = reading_problem(card.get('word') or '', card.get('reading') or '')
        if rp and not dict_read_err:
            add('读音：%s（%s）→ %s' % (card['word'], card.get('reading') or '—', rp))
        if card.get('kind') == 'grammar' and card.get('style') != 'light':
            _s, st = grammar_structure(card, teach)
            if st == 'dirty':
                add('接续：%s 的字段是脏数据，讲义里显示为「—」（补跑 gen 重新整理）' % card['word'])
        for msg in teach_issues(card, teach):
            add('讲解：%s → %s' % (card['word'], msg))
        if card.get('style') == 'light':
            for msg in light_card_issues(card):
                add('卡片：%s → %s' % (card['word'], msg))
    if not issues:
        return [], 0
    lines = ['⚠️ 讲义里有 %d 条内容问题（讲义正文已就地标注）：' % len(issues)]
    for msg in issues[:12]:
        lines.append('   ' + msg)
    if len(issues) > 12:
        lines.append('   …… 另外 %d 条' % (len(issues) - 12))
    lines.append('   讲解问题：gen --only-words "<那个词>" --restart；'
                 '卡片数据问题：回 Anki 改字段（脚本不写库）。')
    return lines, len(issues)


def merge_and_render(manifest, lesson, tag='merge', dinfo=None):
    """闸门 + 渲染 + 落盘。缺卡就报错，不写讲义。"""
    p = dated_paths(manifest['date'])
    problems = check_coverage(manifest, lesson)
    text = render_lesson(manifest, lesson, dinfo)
    problems.extend(check_render(text, manifest))
    if problems:
        print('%s 未通过闸门，没有写讲义：' % tag, file=sys.stderr)
        for t in problems:
            print('  - ' + t, file=sys.stderr)
        return 1, None
    if LESSON_BACKUP and os.path.exists(p['lesson_md']):
        os.replace(p['lesson_md'], p['lesson_md'] + '.bak')
    write_text(p['lesson_md'], text)
    write_text(p['lesson_latest'], text)
    print('%s：讲义已生成 → %s' % (tag, p['lesson_md']))
    cnt = manifest['counts']
    print('  %d 张卡 / %d 条笔记全部覆盖（词汇 %d / 语法 %d / 例句 %d），共 %d 字'
          % (cnt['total'], cnt.get('entries', len(manifest['cards'])), cnt['vocab'],
             cnt['grammar'], cnt.get('sentence', 0), len(text)))
    return 0, p['lesson_md']


# ============================================================================
# 生成：直连本地模型
# ============================================================================
def gen_one_request(manifest, req, system_prompt, cfg, opts, others):
    """跑一个请求，必要时按卡降级重试。返回 (entries, req_usage, notes)。"""
    cards = load_req_cards(req, manifest)
    by_id = {str(c['id']): c for c in cards}
    entries, attempts, nudge = {}, [], None

    pending = [str(c['id']) for c in cards]
    for attempt in range(1, (opts.retries_per_card or 1) + 2):
        if not pending:
            break
        want = [by_id[i] for i in pending]
        messages = build_messages(manifest, want, system_prompt, nudge, others)
        label = 'req%02d' % req['no'] if len(want) == len(cards) else 'req%02d(%d张)' % (req['no'], len(want))
        print('  → %s：%s' % (label, '、'.join(c['word'] for c in want)), file=sys.stderr)
        raw, usage, meta = llm_chat(cfg, messages,
                                    json_mode=not opts.no_json_mode,
                                    stream=not opts.no_stream,
                                    quiet=opts.quiet, label='  ')
        row = usage_row(usage)
        row.update({'req': req['no'], 'ids': [c['id'] for c in want],
                    'attempt': attempt, 'elapsed': round(meta.get('elapsed') or 0, 1),
                    'first_token': round(meta.get('first_token') or 0, 2),
                    'finish_reason': meta.get('finish_reason'),
                    'reasoning_chars': meta.get('reasoning_chars'),
                    'ok': False})
        attempts.append(row)

        # 截断 / 空回复 / 漏卡 / 例句没用上目标词 → 重试
        if meta.get('finish_reason') == 'length':
            nudge = '上一次回复被长度上限截断了（JSON 不完整）'
        else:
            obj, why = extract_json(raw)
            if obj is None:
                nudge = why
            else:
                got, why = pick_entries(obj, want)
                if not why:
                    # 机械可查的质量问题：例句用上目标词、中文不重复、句子写得完
                    offenders = []
                    for k, item in got.items():
                        for msg in teach_issues(by_id[k], item['teach']):
                            offenders.append('%s：%s' % (by_id[k]['word'], msg))
                    if offenders and attempt <= (opts.retries_per_card or 1):
                        nudge = ('这些内容不能进讲义，必须改掉：%s。'
                                 '请重写有问题的字段（例句要含目标词、句子要写完整、'
                                 '中文不要「大约…左右」这种重复）'
                                 % '；'.join(offenders[:4]))
                    else:
                        entries.update(got)
                        row['ok'] = True
                        pending = []
                        break
                else:
                    nudge = why
        # 降级：这一轮还剩下没拿到的卡，下一轮把批次再切小一半（最小 1 张）
        rest = [i for i in pending if i not in entries]
        if len(rest) > 1:
            pending = rest[:max(1, len(rest) // 2)]
            nudge += '（这一轮只输出这 %d 张，别的先不管）' % len(pending)
        else:
            pending = rest
        if not pending:
            break
        print('    ⚠️ %s；重试剩余 %d 张' % (nudge, len(pending)), file=sys.stderr)

    missing = [str(c['id']) for c in cards if str(c['id']) not in entries]
    notes = []
    if missing:
        notes.append('这些卡最终没有拿到讲解：%s' % '、'.join(missing))
    return entries, attempts, notes


def load_req_cards(req, manifest):
    """优先读请求自己的 _in.json；`dict` 一律用 manifest 里的最新事实覆盖。

    只补跑（--only-words）时 _in.json 可能是上一次的，而预取事实刚刷新过；
    只覆盖这一个字段，其余内容仍是「实际发出去的卡」。
    """
    by_id = {c['id']: c for c in manifest['cards']}
    if os.path.exists(req['in']):
        try:
            with open(req['in'], encoding='utf-8') as fh:
                obj = json.load(fh)
            cards = obj.get('cards') or []
            if [c['id'] for c in cards] == req['ids']:
                out = []
                for c in cards:
                    fresh = by_id.get(c['id']) or {}
                    if fresh.get('dict'):
                        c = dict(c, dict=fresh['dict'])
                    out.append(c)
                return out
        except (OSError, json.JSONDecodeError):
            pass
    return [by_id[i] for i in req['ids'] if i in by_id]


def load_metrics(path):
    """读已有的 token 账本；读不出来就当没有（不因为账本坏了挡住生成）。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            obj = json.load(fh)
        return obj if isinstance(obj, dict) and isinstance(obj.get('requests'), list) else None
    except (OSError, json.JSONDecodeError):
        return None


def fmt_tokens(rows):
    if not rows:
        return '（没有请求）'
    prompt = sum(r['prompt_tokens'] for r in rows)
    cached = sum(r['cached_tokens'] for r in rows)
    comp = sum(r['completion_tokens'] for r in rows)
    total = sum(r['total_tokens'] for r in rows)
    return ('prompt %d（其中缓存命中 %d，%.0f%%）＋ completion %d ＝ %d tokens'
            % (prompt, cached, (100.0 * cached / prompt) if prompt else 0, comp, total))


def filter_cards(cards, only_words):
    """--only-words 支持「词形」或 note id，逗号分隔。空 = 不筛。"""
    if not only_words:
        return cards
    want = [w.strip() for w in re.split(r'[,，]', only_words) if w.strip()]
    if not want:
        return cards
    keep = [c for c in cards if c['word'] in want or str(c['id']) in want]
    miss = [w for w in want if not any(c['word'] == w or str(c['id']) == w for c in cards)]
    if miss:
        print('提示：--only-words 里这些没在今天的卡里：%s' % '、'.join(miss), file=sys.stderr)
    return keep


def reuse_request_numbers(manifest, cards, per_batch, only_words, split_path):
    """--only-words 时**沿用原来的请求编号**，不要重新编号。

    重新切批会从 01 开始编号，于是「只重来『あまり』」会写到 01_out.json ——
    那是别的卡（比如『そのため』）的位置，等于既覆盖了别人的产出、又让真正的
    09_out.json 还是旧内容，merge 立刻报「有卡没有讲解 / 重复 id」。

    所以这里读回 split_<日期>.json，找出包含这些卡的原请求，沿用它的编号与路径。
    只有 fingerprint 也对得上才敢沿用（per_batch 或卡集变了就退回重新编号）。
    """
    if not os.path.exists(split_path):
        print('提示：没有 %s，无法沿用原请求编号，按新切批编号（可能覆盖别的产出）。'
              % split_path, file=sys.stderr)
        return None
    try:
        with open(split_path, encoding='utf-8') as fh:
            meta = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    want_ids = {c['id'] for c in cards}
    picked = []
    for req in meta.get('reqs') or []:
        ids = req.get('ids') or []
        hit = [i for i in ids if i in want_ids]
        if not hit:
            continue
        if hit != ids:
            print('⚠️ req%02d 里混着别的卡（%s），这批没法只重来一部分；'
                  '整批重来或改 --per-batch 后重跑 plan。'
                  % (req['no'], '、'.join(req.get('words') or [])), file=sys.stderr)
            return None
        expr = batch_fingerprint(manifest['date'], ids)
        if req.get('fingerprint') != expr:
            print('⚠️ req%02d 的卡片指纹与记录不符（per_batch 或卡集变过），'
                  '退回按新切批编号。' % req['no'], file=sys.stderr)
            return None
        paths = req_paths(req['no'])
        out = []
        for i in ids:
            match = [c for c in cards if c['id'] == i]
            if match:
                out.append(match[0])
        picked.append({'no': req['no'], 'total': len(picked) + 1, 'count': len(out),
                       'ids': ids, 'words': [c['word'] for c in out],
                       'fingerprint': req.get('fingerprint'),
                       'in': paths['in'], 'out': paths['out'], 'meta': paths['meta'],
                       'cards': out})
    if not picked:
        return None
    for n, req in enumerate(picked, 1):
        req['total'] = len(picked)
    return picked


def cmd_gen(args):
    manifest = load_manifest(args, allow_plan=False)
    if not manifest['cards']:
        raise SystemExit('卡片数据里没有卡；先跑 plan。')
    # 词典在发请求之前就查完：事实随卡进模型输入；命中缓存则一次库都不开
    _dinfo, rep, _computed = ensure_dict(args, manifest)
    attach_dict(manifest, rep)
    if rep:
        print_dict_report(rep, limit=6, title='JMdict 预检（调模型前）')
    only_words = getattr(args, 'only_words', None)
    manifest = dict(manifest)
    manifest['cards'] = filter_cards(manifest['cards'], only_words)
    if not manifest['cards']:
        raise SystemExit('--only-words 筛完之后没有卡了。')
    # 轻量卡（视频例句 / 语法例句）自带讲解 → 不发给模型，也不占请求
    model_cards = [c for c in manifest['cards'] if c.get('style') != 'light']
    n_light = len(manifest['cards']) - len(model_cards)
    plan_manifest = dict(manifest)
    plan_manifest['cards'] = model_cards
    cfg = load_llm_config(args)
    if not cfg['api_key']:
        print('提示：没有找到 api key（--api-key / $env:DSH_LOCAL_LLM_API_KEY / %s）。'
              '如果端点不校验就无所谓。' % LLM_GLOBAL_CONFIG_FILE, file=sys.stderr)
    system_prompt = load_system_prompt(args.system_prompt)

    # --restart 可以是 True（全部重来）或一串词（只重来这几个）
    restart_all = args.restart is True
    restart_words = set()
    if isinstance(args.restart, str):
        restart_words = {w.strip() for w in re.split(r'[,，]', args.restart) if w.strip()}

    p = dated_paths(manifest['date'])
    reqs = None
    if only_words:
        reqs = reuse_request_numbers(plan_manifest, model_cards, args.per_batch,
                                     only_words, p['split'])
    if reqs is None:
        reqs = plan_requests(plan_manifest, args.per_batch)
        if not only_words:
            write_json(p['split'], {'date': manifest['date'], 'per_batch': args.per_batch,
                                    'total': len(reqs), 'model': cfg['model'],
                                    'base_url': cfg['base_url'], 'reqs': reqs})
        elif not os.path.exists(p['split']):
            print('警告：没有 %s，merge 只能按目录里的产出合并。' % p['split'], file=sys.stderr)

    print('本地模型：%s　@ %s' % (cfg['model'], cfg['base_url']))
    print('今天 %s 张卡 → %d 个请求（每请求 %s 张）%s'
          % (len(model_cards), len(reqs),
             '全部' if args.per_batch <= 0 else args.per_batch,
             '；另有 %d 张例句卡自带讲解，不调模型' % n_light if n_light else ''))

    all_rows, done_from_disk, failed = [], [], []
    t_start = time.time()
    for req in reqs:
        if not restart_all and not (restart_words & set(req['words'])):
            obj = read_out_file(req['out'], req['ids'])
            if obj:
                print('  ↩︎ req%02d 已有产出，跳过（%s）'
                      % (req['no'], '、'.join(req['words'])), file=sys.stderr)
                done_from_disk.append(req['no'])
                continue
        # 语法卡的接续表通常要跟同批近义句型对照，给一句「今天还有哪些词」帮它避开重复；
        # 纯词汇请求不需要（只会多花 token）。
        req_cards = load_req_cards(req, manifest)
        others = other_words(manifest, req_cards) if any(
            c['kind'] == 'grammar' for c in req_cards) else []
        try:
            entries, rows, notes = gen_one_request(manifest, req, system_prompt, cfg, args, others)
        except LLMError as e:
            print('❌ req%02d 失败：%s' % (req['no'], e), file=sys.stderr)
            failed.append((req['no'], req['words'], str(e)))
            continue
        all_rows.extend(rows)
        if entries:
            write_json(req['out'], {'date': manifest['date'], 'req': req['no'],
                                    'fingerprint': req['fingerprint'], 'model': cfg['model'],
                                    'entries': entries})
        if notes:
            failed.append((req['no'], req['words'], '；'.join(notes)))
        for n in notes:
            print('  ⚠️ req%02d %s' % (req['no'], n), file=sys.stderr)

    # ---- token 账本（累加：只补跑几张卡时不要把整天的账本覆盖掉）----
    if all_rows:
        metrics = load_metrics(p['metrics'])
        if metrics and (metrics.get('model') != cfg['model']
                        or str(metrics.get('date')) != str(manifest['date'])):
            metrics = None
        metrics = metrics or {'date': manifest['date'], 'model': cfg['model'],
                              'base_url': cfg['base_url'], 'per_batch': args.per_batch,
                              'requests': [], 'runs': []}
        metrics.setdefault('runs', [])
        metrics.setdefault('requests', [])
        metrics['requests'].extend(all_rows)
        metrics['runs'].append({
            'at': dt.datetime.now().isoformat(timespec='seconds'),
            'only_words': getattr(args, 'only_words', None),
            'requested': [r['no'] for r in reqs],
            'requests': len(all_rows),
            'elapsed': round(time.time() - t_start, 1)})
        rows = metrics['requests']
        metrics['totals'] = {
            'requests': len(rows),
            'prompt_tokens': sum(r['prompt_tokens'] for r in rows),
            'cached_tokens': sum(r['cached_tokens'] for r in rows),
            'completion_tokens': sum(r['completion_tokens'] for r in rows),
            'reasoning_tokens': sum(r['reasoning_tokens'] for r in rows),
            'total_tokens': sum(r['total_tokens'] for r in rows),
            'elapsed': round(sum(r.get('elapsed') or 0 for r in rows), 1)}
        metrics['skipped_requests'] = done_from_disk
        metrics['failed_requests'] = [{'req': n, 'words': w, 'why': y} for n, w, y in failed]
        write_json(p['metrics'], metrics)
        tot = metrics['totals']
        print()
        print('本次跑 %d 个请求，%.0fs：' % (len(all_rows), round(time.time() - t_start, 1)))
        print('  输入 prompt %d（缓存命中 %d，%.0f%%）'
              % (sum(r['prompt_tokens'] for r in all_rows),
                 sum(r['cached_tokens'] for r in all_rows),
                 (100.0 * sum(r['cached_tokens'] for r in all_rows)
                  / max(1, sum(r['prompt_tokens'] for r in all_rows)))))
        print('  输出 completion %d（其中思考链 %d）＝ 合计 %d tokens'
              % (sum(r['completion_tokens'] for r in all_rows),
                 sum(r['reasoning_tokens'] for r in all_rows),
                 sum(r['total_tokens'] for r in all_rows)))
        print('  今天累计（含之前几次跑）：%d 个请求，prompt %d ＋ completion %d ＝ %d tokens'
              % (tot['requests'], tot['prompt_tokens'], tot['completion_tokens'],
                 tot['total_tokens']))
        print('  平均每张卡 %.0f tokens' % (tot['total_tokens'] / max(1, len(manifest['cards']))))
        print('  明细 → %s' % p['metrics'])

    # ---- 合并渲染 ----
    if failed:
        print()
        print('⚠️ 有 %d 个请求没拿到完整产出：' % len(failed), file=sys.stderr)
        for no, words, why in failed:
            print('  req%02d %s → %s' % (no, '、'.join(words), why), file=sys.stderr)
    if args.no_merge:
        print('\n--no-merge：没有渲染讲义。补跑完再执行：  merge')
        return 1 if failed else 0
    return cmd_merge(args)


def cmd_merge(args):
    """合并已有产出 → 闸门 → 渲染讲义。"""
    manifest = load_manifest(args, allow_plan=True)
    p = dated_paths(manifest['date'])
    meta = None
    if os.path.exists(p['split']):
        with open(p['split'], encoding='utf-8') as fh:
            meta = json.load(fh)
    lesson = load_outputs(manifest, (meta or {}).get('reqs'))
    # 轻量卡（视频例句 / 语法例句）不经过模型：条目在本地拼出来
    lesson['entries'].update(local_entries(manifest))
    if getattr(args, 'intro', None):
        lesson['intro'] = args.intro
    # 顺手留一份合并后的整份 lesson JSON，方便人工检查/手工修
    write_json(p['lesson_json'], lesson)
    # 词典：读预取结果（命中就不查库）；形态与之前一致，读音隐藏/词性校正照旧
    dinfo, rep, _computed = ensure_dict(args, manifest)
    attach_dict(manifest, rep)
    rc, _ = merge_and_render(manifest, lesson, tag='merge', dinfo=dinfo)
    if rep:
        print_dict_report(rep, limit=10)
    lines, _nbad = check_quality(manifest, lesson, dinfo)
    if lines:
        print()
        for ln in lines:
            print(ln, file=sys.stderr)
    return rc


def load_outputs(manifest, reqs=None):
    """读回所有请求的产出，合成一份 lesson。缺哪个请求就报哪个。

    reqs 显式传空列表 = 今天没有需要模型的卡（不再退回去扫目录，免得捡到旧产出）。
    """
    if reqs is None:
        if not os.path.isdir(CARDS_DIR):
            raise SystemExit('没有任何产出（%s 不存在）。先跑：\n  gen' % CARDS_DIR)
        nums = sorted({int(re.match(r'(\d+)_out\.json$', n).group(1))
                       for n in os.listdir(CARDS_DIR) if re.match(r'(\d+)_out\.json$', n)})
        reqs = [{'no': n, 'words': [], 'ids': [], 'out': req_paths(n)['out']} for n in nums]

    entries, missing = {}, []
    id_set = {c['id'] for c in manifest['cards']}
    for meta in reqs:
        out = meta.get('out') or req_paths(meta['no'])['out']
        if not os.path.exists(out):
            missing.append((meta['no'], meta.get('words') or [], out))
            continue
        try:
            with open(out, encoding='utf-8') as fh:
                obj = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            missing.append((meta['no'], meta.get('words') or [], '%s（%s）' % (out, e)))
            continue
        for k, v in (obj.get('entries') or {}).items():
            if k in entries:
                print('警告：req%s 与其他请求重复了同一个 id %s，后者被忽略。'
                      % (meta['no'], k), file=sys.stderr)
                continue
            entries[k] = v

    if missing:
        msg = ['还有 %d 个请求没有产出（重跑 gen 即可自动补这些）：' % len(missing)]
        for no, words, out in missing:
            msg.append('  req%02d %s → %s' % (no, '、'.join(words) or '?', out))
        raise SystemExit('\n'.join(msg))

    extra = [k for k in entries if not k.isdigit() or int(k) not in id_set]
    if extra:
        raise SystemExit('产出里有不属于今天的 id（%d 个）：%s。'
                         '多半是隔天剩下的 0N_out.json，删掉那些文件再重跑 gen。'
                         % (len(extra), ', '.join(sorted(extra)[:10])))
    return {'date': manifest['date'], 'intro': '', 'entries': entries}


def cmd_apply(args):
    """人工贴模型那条路：用一整份 lesson_*.json 渲染讲义。"""
    manifest = load_manifest(args, allow_plan=True)
    p = dated_paths(manifest['date'])
    lesson_path = args.lesson or p['lesson_json']
    if not os.path.exists(lesson_path):
        raise SystemExit('找不到 lesson JSON：%s\n'
                         '直连生成请跑 gen；手工贴模型才需要自己准备这份文件。' % lesson_path)
    with open(lesson_path, encoding='utf-8') as fh:
        raw = fh.read()
    obj, why = extract_json(raw)
    if obj is None:
        raise SystemExit('lesson JSON 解析失败（%s）：%s' % (lesson_path, why))
    if getattr(args, 'intro', None):
        obj['intro'] = args.intro
    dinfo, rep, _computed = ensure_dict(args, manifest)
    attach_dict(manifest, rep)
    rc, _ = merge_and_render(manifest, obj, tag='apply', dinfo=dinfo)
    if rep:
        print_dict_report(rep, limit=10)
    return rc


def cmd_models(args):
    """探端点：api key 对不对、有哪些模型、ctx 多大。"""
    cfg = load_llm_config(args)
    print('base_url : %s' % cfg['base_url'])
    print('api_key  : %s' % ('已提供（%d 字符）' % len(cfg['api_key']) if cfg['api_key']
                             else '未提供（--api-key / $env:DSH_LOCAL_LLM_API_KEY / %s）'
                                  % LLM_GLOBAL_CONFIG_FILE))
    print('model    : %s' % cfg['model'])
    print()
    try:
        data = llm_list_models(cfg)
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')[:300]
        except Exception:
            pass
        raise SystemExit('端点返回 HTTP %s：%s\n'
                         '401/403 → api key 不对或没提供；404 → base_url 错。' % (e.code, body))
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit('连不上端点 %s：%s\n'
                         '确认 NInfer 已经起来（工作区 scripts\\serve.cmd，监听 :8080）。'
                         % (cfg['base_url'], e))
    print('%-44s %-12s %-10s %s' % ('模型 id', '量化', 'ctx', '已加载'))
    print('-' * 84)
    for m in data.get('data') or []:
        window = (m.get('context_window') or m.get('context_length')
                  or m.get('max_model_len') or '—')
        loaded = m.get('loaded')
        print('%-44s %-12s %-10s %s'
              % (m.get('id'), m.get('quant') or '—', window,
                 '—' if loaded is None else ('是' if loaded else '否')))
    ids = [m.get('id') for m in data.get('data') or []]
    if cfg['model'] not in ids:
        print()
        print('⚠️ 配置的模型 %s 不在上面的列表里，用 --model 换一个。' % cfg['model'])
    return 0


def cmd_prompt(args):
    """打印真正会发给模型的 system + user 消息（排查提示词用，不调模型）。

    默认只读当天的预取结果（不查库）；`--refresh-dict` 才重查一遍。
    """
    manifest = load_manifest(args, allow_plan=True)
    system_prompt = load_system_prompt(args.system_prompt)
    if getattr(args, 'refresh_dict', False):
        _dinfo, rep, _computed = ensure_dict(args, manifest)
    else:
        rep, why = None, ''
        if not getattr(args, 'no_dict', False):
            rep, why = load_dict_cache(manifest)
            if not rep:
                print('提示：没有可用的词典预取（%s）；请求里不会带 dict。'
                      % (why or '原因不明'), file=sys.stderr)
    attach_dict(manifest, rep)
    cards = manifest['cards']
    if args.cards_only:
        cards = cards[:args.cards_only]
    others = other_words(manifest, cards) if args.others else []
    messages = build_messages(manifest, cards, system_prompt, None, others)
    if args.stdout:
        for m in messages:
            print('=' * 30, m['role'], '=' * 30)
            print(m['content'])
        print()
        print('≈ 估算输入 token（chars/1.6，中文偏保守）：system %d + user %d'
              % (len(messages[0]['content']) / 1.6, len(messages[1]['content']) / 1.6))
        return 0
    p = os.path.join(LESSON_DIR, 'request_%s.md' % manifest['date'])
    write_text(p, '\n\n'.join('## %s\n\n%s' % (m['role'], m['content']) for m in messages))
    print('已写出：%s' % p)
    return 0


def cmd_stats(args):
    """只看库存：每个学习单元还有多少新卡、上限多少、已讲过多少。"""
    print('%-40s %-24s %8s %6s %8s  %s'
          % ('学习单元（deck）', '模型', '新卡池', '上限', '已讲过', '上限来源'))
    print('-' * 108)
    for cfg in DECKS:
        base = 'deck:"%s" is:new -is:suspended -is:buried' % cfg['deck']
        if cfg.get('model'):
            base += ' note:"%s"' % cfg['model']
        try:
            total = len(AK.find_cards(base))
            left = len(AK.find_cards(query_for(cfg, True)))
        except AnkiError as e:
            print('%-40s  ERR %s' % (cfg['deck'], e))
            continue
        limit, src = deck_new_limit(cfg, args.limit)
        print('%-40s %-24s %8d %6d %8d  %s'
              % (cfg['deck'].replace('0-日本语学习::', ''), cfg.get('model') or '—',
                 total, limit, total - left, src))
    return 0


# ============================================================================
# main
# ============================================================================
def cmd_plan(args):
    manifest = collect(args)
    p = dated_paths(manifest['date'])

    print('今天的新卡（%s）' % manifest['date'])
    print('=' * 96)
    print('%-40s %-24s %5s %6s %7s  %s'
          % ('学习单元（deck）', '模型', '上限', '取卡', '新卡池', '上限来源'))
    print('-' * 96)
    for st in manifest['decks']:
        print('%-40s %-24s %5s %6d %7d  %s'
              % (st['deck'].replace('0-日本语学习::', ''), st.get('model') or '—',
                 st['limit'], st['taken'], st['new_cards_total'], st.get('limit_source', '')))
    print('-' * 96)
    cnt = manifest['counts']
    print('合计 %d 张卡 / %d 条讲解（词汇 %d / 语法 %d / 例句 %d）'
          % (cnt['total'], cnt.get('entries', len(manifest['cards'])), cnt['vocab'],
             cnt['grammar'], cnt.get('sentence', 0)))
    print()
    for c in manifest['cards']:
        print('  [%-8s %-5s] %-16s %-12s %s'
              % (c['kind'], c['level'] or '—', c['word'], c['reading'] or '—',
                 c['meaning'] or ''))

    # 词典在这一步就查完：事实挂进每张词汇卡的 `dict`（随后落进 cards / NN_in），
    # gen / merge 只读这份结果，不再打开词典库。--dry-run 只查不落盘。
    dinfo, rep, _computed = ensure_dict(args, manifest, write=not args.dry_run)
    attach_dict(manifest, rep)
    if rep:
        print_dict_report(rep, limit=10, title='JMdict 预检')

    if args.dry_run:
        print()
        print('--dry-run：没有落盘。去掉它就会写 %s' % p['cards'])
        return 0
    if not manifest['cards']:
        print()
        print('今天没有可讲的新卡（可能都学完了，或者都被 skip_taught 过滤掉了）。不落盘。',
              file=sys.stderr)
        return 0

    write_json(p['cards'], manifest)
    write_json(p['cards_latest'], manifest)
    # 只给「需要模型讲解」的卡切请求：例句卡自带讲解，不占请求
    plan_manifest = dict(manifest)
    plan_manifest['cards'] = [c for c in manifest['cards'] if c.get('style') != 'light']
    reqs = plan_requests(plan_manifest, args.per_batch)
    write_json(p['split'], {'date': manifest['date'], 'per_batch': args.per_batch,
                            'total': len(reqs), 'model': '', 'base_url': '', 'reqs': reqs})
    stale = cleanup_stale_requests(len(reqs))
    print()
    print('已落盘：')
    print('  卡片数据   %s' % p['cards'])
    print('  请求清单   %s（%d 个请求，每请求 %s 张）'
          % (p['split'], len(reqs), '全部' if args.per_batch <= 0 else args.per_batch))
    if stale:
        print('  🧹 清掉上次多余的请求文件：%s' % '、'.join(stale))
    print()
    print('下一步：')
    print()
    print('  & $PY "%s" gen' % os.path.abspath(__file__))
    return 0


def cmd_check(args):
    """预取（或复核）JMdict 词典事实：词形/读音/词性 + 义项/语域。

    默认复用当天已落盘的预取结果，**不查库**；`--refresh-dict` 强制重查。
    只读 Anki、不调模型、不写库；退出码：
    0 = 全部对上；1 = 有硬错（读音不在词典读音表）；2 = 只有建议/提示；
    3 = 词典不可用（jmdictpy 没装或库没建）。
    """
    manifest = load_manifest(args, allow_plan=True)
    if getattr(args, 'no_dict', False):
        raise SystemExit('--no-dict 与 check 一起用没有意义。')
    _dinfo, rep, _computed = ensure_dict(args, manifest)
    if not rep or not rep.get('available'):
        print('词典不可用：%s' % ((rep or {}).get('reason') or '原因不明'), file=sys.stderr)
        print('装/建库：& $PY code\\oneshot\\install_workspace_wheels.py jmdictpy '
              '→ & $PY .dsh\\skills\\jmdict-lookup\\scripts\\jmdict.py build', file=sys.stderr)
        return 3
    attach_dict(manifest, rep)
    out = dated_paths(manifest['date'])['dict']
    for line in JC.format_report(rep, limit=999):
        print(line)
    print()
    print('明细已写：%s' % out)
    if rep['counts']['error']:
        return 1
    if rep['counts']['warn']:
        return 2
    return 0


def load_manifest(args, allow_plan=True):
    cands = []
    if getattr(args, 'cards', None):
        cands.append(args.cards)
    if getattr(args, 'date', None):
        cands.append(dated_paths(args.date)['cards'])
    cands.append(os.path.join(OUTDIR, 'cards_latest.json'))
    for path in cands:
        if path and os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    manifest = json.load(fh)
            except (OSError, json.JSONDecodeError) as e:
                raise SystemExit('卡片数据读不出来（%s）：%s' % (path, e))
            if not getattr(args, 'quiet', False):
                print('读取卡片数据：%s' % path, file=sys.stderr)
            return manifest
    raise SystemExit('找不到卡片数据。先跑一次：\n  python today_new.py plan')


def add_common(sp):
    """各子命令共用的参数（--cards / --date / --quiet / --no-dict / --refresh-dict）。"""
    sp.add_argument('--cards', default=None,
                    help='指定 cards_*.json；默认用 cards_latest.json')
    sp.add_argument('--date', default=None, help='指定日期（读 cards_<日期>.json）')
    sp.add_argument('--quiet', action='store_true',
                    help='静默：不打印「读取卡片数据…」和每个请求的首字延迟')
    sp.add_argument('--no-dict', action='store_true',
                    help='跳过 JMdict 词典层（不预取事实、不做读音/词性校正）')
    sp.add_argument('--refresh-dict', action='store_true',
                    help='忽略已预取结果，强制重新查一遍词典并写回 dict_<日期>.json')
    return sp


def add_gen_args(sp):
    add_common(sp)
    sp.add_argument('--per-batch', type=int, default=PER_BATCH,
                    help='每个请求塞几张卡（默认 %d；0 或负数 = 一次全给）。'
                         '调大省 system 前缀，但输出更长、更易截断' % PER_BATCH)
    sp.add_argument('--base-url', default=None, help='端点 base_url（默认 %s）' % LLM_DEFAULT_BASE)
    sp.add_argument('--model', default=None, help='模型名（默认 %s）' % LLM_DEFAULT_MODEL)
    sp.add_argument('--api-key', default=None, help='api key（优先于环境变量与配置文件）')
    sp.add_argument('--system-prompt', default=None,
                    help='替换系统提示词文件（默认 %s）' % SYSTEM_PROMPT_FILE)
    sp.add_argument('--no-json-mode', action='store_true',
                    help='保留兼容参数；NInfer 不支持结构化输出，本脚本已不发 text.format')
    sp.add_argument('--no-stream', action='store_true', help='关掉流式（默认流式）')
    sp.add_argument('--retries-per-card', type=int, default=2,
                    help='一张卡最多重生成几次（默认 2）')
    return sp


def main():
    ap = argparse.ArgumentParser(
        description='取 Anki 今日新卡（词汇 + 语法）→ 直连本地模型生成讲解 → 渲染成一份讲义。',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='详见文件头的用法说明，以及 docs/today_new-使用说明.md')
    sub = ap.add_subparsers(dest='cmd')

    sp = sub.add_parser('plan', help='取今天的新卡并落盘（只读 Anki）')
    sp.add_argument('--date', default=dt.date.today().isoformat(),
                    help='把这天当成「今天」（用于文件名与 manifest，默认系统日期）')
    sp.add_argument('--limit', type=int, default=None,
                    help='每个学习单元最多取几张新卡（覆盖 getDeckConfig 与 PER_DECK_LIMIT）')
    sp.add_argument('--only', choices=['vocab', 'grammar'], default=None,
                    help='只取一类卡（默认两类都取）')
    sp.add_argument('--deck', default=None,
                    help='只取这些单元（逗号分隔，从头前缀匹配），如 "1-语法::5-N1"')
    sp.add_argument('--include-taught', action='store_true',
                    help='不跳过已经讲过（AINote/AIConclusion 非空）的卡')
    sp.add_argument('--per-batch', type=int, default=PER_BATCH,
                    help='每个请求塞几张卡（默认 %d；0 = 一次全给）' % PER_BATCH)
    sp.add_argument('--dry-run', action='store_true', help='只打印，不落盘')
    sp.add_argument('--no-dict', action='store_true',
                    help='跳过 JMdict 词典层（不预取、不留 dict 事实）')
    sp.add_argument('--refresh-dict', action='store_true',
                    help='忽略已预取结果，强制重新查一遍词典')
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser('check', aliases=['dict'],
                        help='预取/复核 JMdict（词形/读音/词性 + 义项/语域；不调模型）')
    add_common(sp)
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser('gen', help='直连本地模型生成讲解 → 闸门 → 渲染讲义')
    add_gen_args(sp)
    sp.add_argument('--restart', nargs='?', const=True, default=None,
                    help='忽略已有产出重新生成：--restart = 全部重来；'
                         '--restart "あまり,しかも" = 只重来这几个词')
    sp.add_argument('--only-words', default=None,
                    help='只处理这些卡（词形或 note id，逗号分隔）')
    sp.add_argument('--no-merge', action='store_true', help='只生成，不渲染讲义')
    sp.add_argument('--intro', default=None, help='手写今日总览（覆盖讲义的 intro）')
    sp.set_defaults(func=cmd_gen)

    sp = sub.add_parser('merge', help='合并已有产出 → 闸门 → 渲染讲义（不调模型）')
    add_common(sp)
    sp.add_argument('--intro', default=None, help='手写今日总览')
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser('apply', help='用一整份 lesson_*.json 渲染讲义（人工贴模型那条路）')
    add_common(sp)
    sp.add_argument('--lesson', default=None, help='指定整份 lesson_*.json')
    sp.add_argument('--intro', default=None, help='手写今日总览')
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser('models', help='探端点：api key 对不对、有哪些模型、ctx 多大')
    sp.add_argument('--base-url', default=None, help='端点 base_url（默认 %s）' % LLM_DEFAULT_BASE)
    sp.add_argument('--model', default=None, help='模型名（默认 %s）' % LLM_DEFAULT_MODEL)
    sp.add_argument('--api-key', default=None, help='api key')
    sp.set_defaults(func=cmd_models)

    sp = sub.add_parser('prompt', help='打印真正会发给模型的消息（排查提示词，不调模型）')
    add_common(sp)
    sp.add_argument('--system-prompt', default=None)
    sp.add_argument('--cards-only', type=int, default=0, help='只取前 N 张卡做样例')
    sp.add_argument('--others', action='store_true', help='带上「今天还有哪些词」那句')
    sp.add_argument('--stdout', action='store_true', help='打到标准输出')
    sp.set_defaults(func=cmd_prompt)

    sp = sub.add_parser('stats', help='只看库存：各单元的新卡数、上限、已讲过多少')
    sp.add_argument('--limit', type=int, default=None)
    sp.add_argument('--quiet', action='store_true', help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    if not getattr(args, 'func', None):
        ap.print_help()
        return 2
    try:
        return args.func(args)
    except AnkiError as e:
        print('Anki 错误：%s' % e, file=sys.stderr)
        return 2
    except LLMError as e:
        print('本地模型错误：%s' % e, file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print('\n中断。已完成的产出都在磁盘上，直接重跑 gen 会接着做。', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
