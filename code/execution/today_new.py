# -*- coding: utf-8 -*-
"""今天学习生词 → 日语讲义（每日任务：取卡 → 直连本地模型生成 → 合并渲染）

每天早上学今天这批生词**之前**跑的一条固定链路：

    1. plan    取今天要讲的词：全库 tag「今天学习生词」命中的词汇笔记
               （由 jp-anki-today-new 从当天字幕选出、全量替换）
               → 落盘 cards_<日期>.json；**没有这个 tag 就不生成讲义**
    2. gen     **直连本地模型**（OpenAI Responses API：/v1/responses）逐张或逐批生成讲解，
               落盘 lessons/cards/NN_out.json + metrics，然后自动合并渲染讲义
    3. merge   只做「合并已有产出 → 闸门 → 渲染」（不调模型）
       apply   同 merge；也可用来合并人工写好的一整份 lesson_*.json
       models  只探一次端点：列出可用模型 + 验 api key

为什么按 tag 取词（2026-10-28）
------------------------------
以前的口径是「按牌组 new.perDay 从新卡队列里分发今日新卡」，和「今天到底学哪些词」
是两套逻辑：讲义可能讲到用户今天并不打算学的词。现在统一成——**选词归选词、
讲义只讲 tag**：

    jp-anki-today-new  从当天字幕挑 N 个词 → 打上 tag「今天学习生词」（全量替换）
    today_new.py       只认这个 tag：tag 里有词就讲，没有就什么都不生成

排序取当天 ``data/daily_new/<日期>/picked.json`` 里的入选顺序（A→B→D 分池顺序），
没有这份记录时按「级别 → 牌组 → 词形」兜底。

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
    model      **默认沿用端点当时在用的模型**（配置文件里 `pin_active: true`）：
               发请求前问一次 `/props` 的 `model_alias`，把 model 对齐到它——
               讲义是卡片类任务，同一批词要用同一个模型讲完，中途换会混风格。
               配置文件/profile 里写的 `qwen3.8-27b` 只是声明，服务换了它不跟着变。
               只有显式 `--model <id>` 或 `$env:DSH_LOCAL_LLM_MODEL` 才覆盖（那是人在指定）；
               临时关掉对齐：`$env:DSH_LOCAL_LLM_PIN='0'`。**换端点用 --profile，不要用 --model 切。**
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
    & $PY $TN stats                     # 只看库存：tag 今天命中了多少个词
    & $PY $TN plan --dry-run            # 看一眼今天取到哪些词（只读，不落盘）

    & $PY $TN plan                      # 按 tag 取词 + 预取 JMdict 事实 → 落盘
    & $PY $TN check                     # 预取/复核词典（词形/读音/词性 + 义项/语域；不调模型）
    & $PY $TN gen                       # 直连本地模型逐张生成 → 闸门 → 讲义（默认 --per-batch 1）
    & $PY $TN gen --per-batch 3         # 一次给模型 3 张（省 system 前缀，但输出更长）
    & $PY $TN gen --restart             # 忽略已有产出，全部重生成
    & $PY $TN gen --no-merge            # 只生成，不渲染讲义

    & $PY $TN merge                     # 只合并已有产出（补跑过个别卡之后用）
    & $PY $TN merge --intro "今天这批以接续词为主"

产出（全部在 output/daily/ 下）
------------------------------
    cards_<日期>.json           今天这批词的原始数据（= manifest；词汇卡自带 `dict` 事实；
                                **没有 tag 时落一份空清单**，让 gen/merge 明确地什么都不做）
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
import ruby_engine as RE  # noqa: E402  <ruby> 标签的唯一构造器（wrap）
import ruby_text as RT  # noqa: E402  漢字[かんじ] ↔ <ruby> 的解析（common）
from htmltext import strip_tags, TAG, BR  # noqa: E402  HTML 去标签（common）
from audio_names import sounds_of  # noqa: E402  [sound:…] 解析（common）
from jp_text import as_int  # noqa: E402  纯转换（common/jp_text.py）
from llm_client import (  # noqa: E402  本地模型客户端（common/llm_client.py）
    LLMError, LLM_DEFAULT_BASE, LLM_RESPONSES_PATH, LLM_DEFAULT_MODEL,
    LLM_CONFIG_FILE, LLM_GLOBAL_CONFIG_FILE, LLM_KEY_ENV, LLM_TIMEOUT,
    LLM_HTTP_RETRIES, LLM_MAX_TOKENS, LLM_TEMPERATURE, LLM_TOP_P,
    llm_pin_enabled, llm_active_model, llm_window_for, load_llm_config,
    llm_headers, llm_list_models, split_llm_messages, build_llm_body,
    llm_chat, usage_row, extract_json,
)
from lesson_text import (strip_ruby_readings, normalize_teach, clean_structure,
                         structure_looks_garbled, grammar_structure, render_teach)
# 机械判定（词形/读音/词性、内容问题、闸门）：实现在 execution/lesson_check.py
# （2026-11-01 抽出）。名字全部保持原样，调用方与测试不用改。
from lesson_check import (  # noqa: E402,F401
    PLACEHOLDER, TRAILING_KANA, POS_NAMES, INTERJECTION_WORDS, FINAL_PARTICLE_WORDS,
    SUSPECT_POS, KANA_ONLY, hira_text, kana_key, is_kana_only, reading_problem,
    pos_label, display_pos, group_vocab, unfinished_text, redundant_cn, self_compare,
    target_forms, example_uses_target, looks_like_labeled_prose, teach_issues,
    core_word_seen, light_card_issues, check_coverage, plain_for_gate, check_render,
    local_entries, check_quality)
# 讲义落盘路径与原子写：实现在 execution/lesson_paths.py（2026-11-02）。
# `lesson_render` 也用它，所以这里是**别名**而不是定义——两边拿到的是同一组路径。
from lesson_paths import (  # noqa: E402,F401
    OUTDIR, LESSON_DIR, CARDS_DIR, TAG_TODAY, LESSON_BACKUP, dict_path, write_text,
    write_json, dated_paths)

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
# 端点/模型/key 默认值与本地模型客户端都在 code/common/llm_client.py（issue #5：
# core6000_example 也要用同一套客户端）。本文件保留模块级名字，调用方不用改。

# ============================================================================
# 配置区：换收藏结构时改这里
#
#   一个「词汇卡组」= deck + 模型过滤。字段名逐单元指定（不同模型字段名不同）。
#       deck     卡组路径（AnkiConnect 会连带子 deck，所以写父 deck 即可）
#       model    笔记模型名；写 '' 表示不按模型过滤
#       kind     vocab（讲义只讲词汇；语法/例句单元已移出，见下）
#       level    默认识别到的级别（eggrolls 会用标签细化到具体 N 级）
#       level_from_tag  级别写在 eggrolls 标签里（考级词汇扁平化后唯一来源）
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
# 语法/例句单元已移出每日讲义（2026-10-28：讲义只讲 tag「今天学习生词」里的词）。
# 字段模板与渲染分支保留着，`merge --date <旧日期>` 还能渲染当时带语法/例句的 manifest。
GRAMMAR_FIELDS = dict(w1='Card', pos='ConnectiveType1', mean='MeaningCN',
                      mean_jp='MeaningJP', sent='Sentence{N}', trans='CN{N}',
                      audio='SentenceAudio{N}', note='CNote{N}', extra='AIConclusion')
SENTENCE_FIELDS = dict(w1='Sentence', ruby='Sentence HTML', note='AINote',
                       source='Source', audio='Sentence Audio')

DECKS = [
    # ---- 考级词汇（eggrolls 模板，级别在标签里）----
    dict(deck='0-日本语学习::0-词汇::2-考级词汇', model='eggrolls-JLPT10k-v3.5',
         kind='vocab', level='考级', level_from_tag=True, fields=EGGROLL_FIELDS),
    # ---- 词频词（core6000，Japanese Vocabulary 模板）----
    dict(deck='0-日本语学习::0-词汇::1-高频日语单词 6000', model='Japanese Vocabulary',
         kind='vocab', level='Core6000', fields=CORE_FIELDS),
    # ---- 素材生词（mine.py 建的第 3 个词汇 deck，与 core6000 同模板）----
    dict(deck='0-日本语学习::0-词汇::0-素材生词', model='Japanese Vocabulary',
         kind='vocab', level='素材生词', fields=CORE_FIELDS),
]

# 今天的词由 jp-anki-today-new（code/tools/today_new_words.py）打在笔记上；
# 没有这个 tag 的日子，讲义不生成。`TAG_TODAY` 改为从 lesson_paths import（见文件头）。
# 选词顺序（JitenAnimeRank 升序）落在 data/daily_new/<日期>/picked.json；
# 有这份记录就按它排讲义，没有就按级别/牌组兜底。
PICKED_DIR = os.path.join(WSP.DATA, 'daily_new')

MAX_SENTENCES = 3          # 每张卡最多取几条例句
NOTE_CHUNK = 200           # notesInfo 的批量大小

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
# 「多句挤在一个字段里」的两种分隔：连续的 <br>，或段落标签之间
SENT_PAIR_BR = re.compile(r'(?:\s*<br\s*/?>\s*){2,}', re.I)
SENT_PAIR_P = re.compile(r'</p>\s*<p[^>]*>', re.I)

# 文本清洗与振假名：实现已收进 common（htmltext.py / ruby_text.py）。
# 这里保留旧名字，调用方（含 core6000 的 TN.KANJI）不用改。
KANJI = RT.KANJI
to_ruby = RT.to_ruby
strip_ruby_base = RT.strip_ruby_base
plain_jp = RT.plain_jp
# 这两个是 ruby_text 内部的 ruby 占位工具，core6000_example.clean_label 直接用到（2026-11-01 补）：
# 漏了它们，scan/apply 一进 parse_sections 就 AttributeError。
_extract_existing_ruby = RT._extract_existing_ruby
_put_back_ruby = RT._put_back_ruby


# 振假名解析与纯文本提取的实现：common/ruby_text.py（2026-11-01 抽出）


def clean_mean(text, limit=80):
    """释义：去标签、把 eggrolls 的 [ ] 注音括号展开、压缩空白、限长。"""
    text = strip_tags(text)
    text = re.sub(r'\[([^\]]*)\]', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + '…'
    return text


# `[sound:…]` 解析与媒体命名：common/audio_names.py（issue #5）
audio_files = sounds_of



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
# 取词：全库 tag「今天学习生词」
# ============================================================================
def query_for(cfg):
    """某个词汇卡组里今天要讲的笔记：deck + 模型 + tag。

    注意这里是**笔记**查询（findNotes），不按 `is:new` 过滤：词是先由
    jp-anki-today-new 从当天字幕选好、打上 tag 的；讲义只管讲，不再按
    新卡队列/日上限另算一遍。
    """
    q = 'deck:"%s"' % cfg['deck']
    if cfg.get('model'):
        q += ' note:"%s"' % cfg['model']
    return q + ' tag:"%s" -is:suspended' % TAG_TODAY


def picked_order(date):
    """当天选词顺序：{noteId: 名次}（picked.json 里的 Jiten 升序）。

    读不到（没跑过 today_new_words、或手动打的 tag）就返回 {}，
    排序退回「级别 → 牌组 → 词形」。
    """
    path = os.path.join(PICKED_DIR, date, 'picked.json')
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    order = {}
    for i, w in enumerate(data.get('picked') or []):
        # 2026-10-28 起一个词可能对应多张笔记（听辨/辨意各一张）：`notes` 是全集，
        # 旧记录只有 `noteId`，两种都认。
        ids = w.get('notes') or ([w.get('noteId')] if w.get('noteId') else [])
        for nid in ids:
            try:
                order[int(nid)] = i
            except (TypeError, ValueError):
                continue
    return order


LEVEL_ORDER = {'N5': 0, 'N4': 1, 'N3': 2, 'N2': 3, 'N1': 4,
               'Core6000': 5, '素材生词': 6}


def sort_cards(cards, order=None):
    """按 picked.json 的选词顺序排；不在记录里的排最后，再按级别/牌组/词形兜底。"""
    order = order or {}
    return sorted(cards, key=lambda c: (order.get(c['id'], len(order) + 1),
                                        LEVEL_ORDER.get(c['level'], 9),
                                        c['deck'], c['word']))


def pick_tagged(cfg):
    """取一个词汇卡组里今天要讲的笔记 → (cards, stats)。

    每个笔记就是一条讲义条目（这三个词汇模型的笔记都只有 1 张卡，
    所以 笔记数 = 卡片数）。卡当前在哪个 deck 不重要——词可能被临时
    收进筛选牌组；讲义按 noteId 取字段，牌组只用来标级别。
    """
    query = query_for(cfg)
    nids = [int(x) for x in AK.find_notes(query)]
    stats = {'deck': cfg['deck'], 'model': cfg.get('model', ''), 'level': cfg['level'],
             'kind': cfg['kind'], 'query': query, 'tagged': len(nids),
             'taken': 0, 'taken_notes': 0, 'skipped': 0}
    if not nids:
        return [], stats
    by_id = AK.notes_map(nids, chunk=NOTE_CHUNK)
    cards = []
    for nid in nids:
        note = by_id.get(nid)
        if not note:
            continue
        card = make_card(note, cfg, 0)
        if card:
            card['tags'] = note.get('tags', []) or []
            card['n_cards'] = 1
            card['card_ords'] = [0]
            cards.append(card)
    stats['taken'] = len(cards)
    stats['taken_notes'] = len(cards)
    stats['skipped'] = max(0, len(nids) - len(cards))
    return cards, stats


def collect(opts):
    """按 tag 取今天全部要讲的词。opts 来自命令行。"""
    groups = DECKS
    if getattr(opts, 'deck', None):
        want = [p.strip() for p in opts.deck.split(',') if p.strip()]
        groups = [g for g in groups
                  if any(g['deck'] == w or g['deck'].startswith(w) for w in want)]
        if not groups:
            raise SystemExit('--deck 没有匹配到词汇卡组（前缀匹配，必须从头匹配）。可用：\n  ' +
                             '\n  '.join(g['deck'] for g in DECKS))

    order = picked_order(opts.date)
    cards, stats = [], []
    for cfg in groups:
        got, st = pick_tagged(cfg)
        cards.extend(got)
        stats.append(st)
    cards = sort_cards(cards, order)

    n = len(cards)
    manifest = {
        'version': 3,
        'mode': 'tag',
        'tag': TAG_TODAY,
        'date': opts.date,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'system_prompt': SYSTEM_PROMPT_FILE,
        'counts': {'total': n, 'entries': n, 'vocab': n, 'grammar': 0, 'sentence': 0},
        'decks': stats,
        'cards': cards,
    }
    return manifest


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


# JSON 抢救（extract_json）的实现在 common/llm_client.py（issue #5）
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


# teach 整形与渲染：execution/lesson_text.py（2026-11-01 抽出）


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


# ============================================================================
# 渲染讲义 + 闸门（实现已抽到 execution/lesson_render.py，2026-11-02）
# ============================================================================
# 渲染只吃 manifest + 模型产出 + dinfo，不碰 Anki / LLM；流程（取卡、切批、直连模型）
# 留在本文件。名字全部保持原样，调用方与测试（TN.render_lesson …）不用改。
from lesson_render import (  # noqa: E402,F401
    clip_sentence, _sentence_warnings, light_sentences, cell, render_light_card,
    dict_card, dict_reading_issue, render_lesson, merge_and_render)
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
        print('今天没有 tag:「%s」的词 → 跳过，不调模型、不生成讲义。' % TAG_TODAY)
        return 0
    # 清单里的词必须仍然带着今天的 tag：tag 被换批/清空后，旧清单不再有效
    if not getattr(args, 'allow_stale_tag', False):
        live = {int(x) for x in AK.find_notes('tag:"%s"' % TAG_TODAY)}
        stale = [c for c in manifest['cards'] if int(c['id']) not in live]
        if stale:
            raise SystemExit(
                '卡片数据里有 %d 个词已不在 tag:「%s」里（可能换过一批或清空了）。\n'
                '重跑 plan 按当前 tag 取词；要照旧清单生成就加 --allow-stale-tag。'
                % (len(stale), TAG_TODAY))
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
        prev_model = (metrics or {}).get('model')
        if metrics and str(metrics.get('date')) != str(manifest['date']):
            metrics = None
        if metrics and prev_model and prev_model != cfg['model']:
            # 端点中途换了服务（NInfer ↔ Strata）：同一份账本会把两个模型的 token 混在一起。
            # 生成物不拦（还是当天这批卡），只把旧账本另存一份，核对时看得见。
            alt = p['metrics'].replace('.json', '_%s.json' % prev_model)
            print('⚠️ 今天的账本记的是 %s，本次是 %s（端点换过了）。旧账本另存 %s，新账本只记本次。'
                  % (prev_model, cfg['model'], alt), file=sys.stderr)
            try:
                write_json(alt, metrics)
            except OSError as e:
                print('（旧账本没存成：%s）' % e, file=sys.stderr)
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
    if not manifest['cards']:
        print('今天没有 tag:「%s」的词 → 跳过，不生成讲义。' % TAG_TODAY)
        return 0
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
        if loaded is None:
            # 路由器（本机 Strata）用 status.value 标「正在服务」的是哪一条
            loaded = (m.get('status') or {}).get('value') == 'loaded'
        print('%-44s %-12s %-10s %s'
              % (m.get('id'), m.get('quant') or '—', window,
                 '—' if loaded is None else ('是' if loaded else '否')))
    ids = [m.get('id') for m in data.get('data') or []]
    if cfg['model'] not in ids:
        print()
        print('⚠️ 配置的模型 %s 不在上面的列表里。' % cfg['model'])
    active = llm_active_model(cfg['base_url'], cfg['api_key'])
    if active and active != cfg.get('declared_model'):
        aligned = '已经自动对齐，实际发的就是它' if active == cfg['model'] else \
                  '本次**没**对齐（显式给了 --model，或 pin 被关）：实际发的是 %s' % cfg['model']
        print()
        print('ℹ️ 端点当前在服务 %s，配置里声明的是 %s（profile=%s）——%s。'
              '卡片类任务沿用当前在用的模型，**不要用 --model 单独换档位**；要换端点用 --profile。'
              % (active, cfg.get('declared_model'), cfg.get('profile') or '（顶层默认）', aligned))
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
    """只看库存：tag「今天学习生词」今天在各个词汇卡组里命中多少条笔记。"""
    print('%-40s %-24s %8s' % ('词汇卡组（deck）', '模型', 'tag 命中'))
    print('-' * 78)
    total = 0
    for cfg in DECKS:
        try:
            n = len(AK.find_notes(query_for(cfg)))
        except AnkiError as e:
            print('%-40s  ERR %s' % (cfg['deck'].replace('0-日本语学习::', ''), e))
            continue
        total += n
        print('%-40s %-24s %8d'
              % (cfg['deck'].replace('0-日本语学习::', ''), cfg.get('model') or '—', n))
    print('-' * 78)
    print('合计 %d 个笔记（tag:「%s」）' % (total, TAG_TODAY))
    if not total:
        print('（今天还没选词：先跑 jp-anki-today-new 从字幕挑词、打标签。）')
    return 0


# ============================================================================
# main
# ============================================================================
def cmd_plan(args):
    manifest = collect(args)
    p = dated_paths(manifest['date'])

    print('今天学习生词（%s）' % manifest['date'])
    print('=' * 78)
    print('%-40s %-24s %8s' % ('词汇卡组（deck）', '模型', 'tag 命中'))
    print('-' * 78)
    for st in manifest['decks']:
        print('%-40s %-24s %8d'
              % (st['deck'].replace('0-日本语学习::', ''), st.get('model') or '—',
                 st['tagged']))
    print('-' * 78)
    cnt = manifest['counts']
    print('合计 %d 个词' % cnt['total'])
    print()
    for c in manifest['cards']:
        print('  [%-5s] %-16s %-12s %s'
              % (c['level'] or '—', c['word'], c['reading'] or '—', c['meaning'] or ''))

    # 没有 tag 就什么都不生成：落一份空清单，免得 gen/merge 捡到之前那天的数据。
    if not manifest['cards']:
        print()
        print('今天没有 tag:「%s」的词 → 不生成讲义（不调模型、不落请求）。' % TAG_TODAY)
        print('（先跑 jp-anki-today-new 从当天的字幕/文字里选词；清空 tag 时也一样。）')
        if not args.dry_run:
            write_json(p['cards'], manifest)
            write_json(p['cards_latest'], manifest)
            print('已落一份空清单：%s（gen / merge 看到它会直接跳过）' % p['cards'])
        return 0

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

    write_json(p['cards'], manifest)
    write_json(p['cards_latest'], manifest)
    # 只给「需要模型讲解」的卡切请求：示例/例句卡自带讲解，不占请求
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
    if not manifest['cards']:
        print('今天没有 tag:「%s」的词 → 没有要核的词。' % TAG_TODAY)
        return 0
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
    """读当天的 cards_*.json。

    默认只认**今天**的清单：隔天直接跑 gen/merge 会捡到昨天那批词，
    等于把旧讲义当今天的发出去。要重看旧日期就显式 `--date <日期>`。
    """
    cands = []
    if getattr(args, 'cards', None):
        cands.append(args.cards)
    if getattr(args, 'date', None):
        cands.append(dated_paths(args.date)['cards'])
    explicit = bool(getattr(args, 'cards', None) or getattr(args, 'date', None))
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
            today = dt.date.today().isoformat()
            if not explicit and str(manifest.get('date')) != today:
                raise SystemExit(
                    '卡片数据是 %s 的，不是今天（%s）。\n'
                    '今天没有 tag:「%s」？先跑 plan（没有词时它会落一份空清单）；'
                    '要重看旧日期就显式加 --date %s。'
                    % (manifest.get('date'), today, TAG_TODAY, manifest.get('date')))
            if not explicit and manifest.get('mode') != 'tag':
                raise SystemExit(
                    '卡片数据是旧口径（按新卡队列取的）：%s。\n'
                    '现在只按 tag:「%s」取词——重跑 plan 覆盖它（没有 tag 会落空清单，不会生成讲义）。'
                    % (path, TAG_TODAY))
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
    sp.add_argument('--model', default=None,
                    help='★ 模型名（覆盖配置）。**卡片任务一般不该给**：给了就等于绕过'
                         '「沿用端点当前在用的模型」去切换模型（默认自动对齐，见 --profile）')
    sp.add_argument('--profile', default=None,
                    help='用 ~/.dsh/local-llm.json 里 profiles 的哪一项（ninfer / strata…）；'
                         '也可用 $env:DSH_LOCAL_LLM_PROFILE。换端点走这个，不要用 --model 切')
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
        description='取 tag「%s」里的词 → 直连本地模型生成讲解 → 渲染成一份讲义。'
                    % TAG_TODAY,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='详见文件头的用法说明，以及 docs/today_new-使用说明.md')
    sub = ap.add_subparsers(dest='cmd')

    sp = sub.add_parser('plan', help='按 tag 取今天要讲的词并落盘（只读 Anki）')
    sp.add_argument('--date', default=dt.date.today().isoformat(),
                    help='把这天当成「今天」（用于文件名与 manifest，默认系统日期）')
    sp.add_argument('--deck', default=None,
                    help='只取这些词汇卡组（逗号分隔，从头前缀匹配），如 "0-素材生词"')
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
    sp.add_argument('--allow-stale-tag', action='store_true',
                    help='清单里的词已不在 tag「%s」里也照样生成（默认拒绝：先重跑 plan）' % TAG_TODAY)
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
    sp.add_argument('--model', default=None,
                    help='★ 模型名（覆盖配置）。**卡片任务一般不该给**：给了就等于绕过'
                         '「沿用端点当前在用的模型」去切换模型（默认自动对齐，见 --profile）')
    sp.add_argument('--profile', default=None,
                    help='用 ~/.dsh/local-llm.json 里 profiles 的哪一项（ninfer / strata…）；'
                         '也可用 $env:DSH_LOCAL_LLM_PROFILE。换端点走这个，不要用 --model 切')
    sp.add_argument('--api-key', default=None, help='api key')
    sp.set_defaults(func=cmd_models)

    sp = sub.add_parser('prompt', help='打印真正会发给模型的消息（排查提示词，不调模型）')
    add_common(sp)
    sp.add_argument('--system-prompt', default=None)
    sp.add_argument('--cards-only', type=int, default=0, help='只取前 N 张卡做样例')
    sp.add_argument('--others', action='store_true', help='带上「今天还有哪些词」那句')
    sp.add_argument('--stdout', action='store_true', help='打到标准输出')
    sp.set_defaults(func=cmd_prompt)

    sp = sub.add_parser('stats', help='只看库存：tag 今天在各个词汇卡组里命中多少条')
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
