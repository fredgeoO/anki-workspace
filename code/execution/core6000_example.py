# -*- coding: utf-8 -*-
"""Core6000 按需补例句②（用户点名的词 → 新例句 + 振假名 + 合并讲解 + 配音）

**这是「按需」能力，不是全量补全。** 用户对自己记不住的 core6000 词点名要一句不同语境的
例句，脚本给这些卡补上第二条例句，并把它和已有讲解合成 ①②两段：

    Sentence             原句<br><br>新句            （恰好 2 块）
    Sentence HTML        原句振假名<br><br>新句振假名（恰好 2 块，每个汉字都有 ruby）
    Sentence Translation 原译<br><br>新译
    AINote               沿用原卡版式，每个板块变成「① 原句相关」+「② 新句相关」
    Sentence Audio       原有 [sound:] 原样保留 + [sound:core6000-<noteId>-sentence-2.mp3]

`Word / Transliteration / Meaning / Part of Speech / Index / Pitch Accent*` **一个字都不动**，
不加标签、不动 deck、不动 due。**原句的信息一个字都不丢**：AINote 的 ① 直接用卡里已有的
正文，不交给模型改写。**新例句的句子本身来自 Jisho（真实语料），不是模型写的**：
gen 先用 `code/tools/jisho_example.py` 抓 jisho.org 的 Sentence 搜索结果（Tatoeba / Jreibun），
按「振假名结构合格 / 真含目标词 / 长度进闸门 / 与第一句不像」挑一条，把句子与振假名
**钉死**写进 payload（`sentence_source`），模型只负责中文翻译与 ② 的讲解；
模型若改写了那句，脚本按 Jisho 原句写回并记一条 `sentence_overridden` 警告。
Jisho 零候选时**不退回模型造句**（这张卡记为失败；要退回必须显式 `--allow-model-sentence`）。
已有振假名也不会被模型重写（能按句切开就用卡里的）。

    契约文档（唯一接口契约，改接口先改它）：docs/core6000-example-design.md
    模型侧规范（另一个文件，本脚本只读）：code/execution/core6000_example_prompt.md
    固定流程与坑表：.dsh/skills/jp-anki-daily（第四节 · D 类）

用法：三步固定顺序 gen → tts → apply，每步都带上同一套选择器
------------------------------------------------------------
    $PY = "python"
    $WS = "<工作区根>"
    $CE = "$WS\\code\\execution\\core6000_example.py"

    # 新句来自 Jisho（真实语料），模型只写讲解
    & $PY $CE gen   --words "徹夜,適当,残り"      # Jisho 取新句 → 本地模型写 ② → data/core6000/gen/<noteId>_out.json
    & $PY $CE tts   --words "徹夜,適当,残り"      # edge-TTS → output/audio/core6000/（不碰 Anki）
    & $PY $CE apply --words "徹夜,適当,残り"      # 演练：打印 5 个字段前后对照
    #   ★ 唯一的人看闸门：演练输出的前后对照 + Sentence HTML（2026-10-06 起不再要求听音频确认）
    & $PY $CE apply --words "徹夜,適当,残り" --commit   # 真写（写前自动落 backup_<时间戳>.json）
    & $PY $CE revert --commit                     # 反悔：按 backup 逐条还原那 5 个字段（媒体不删）

    # 「只针对我记不住的」入口：直接吃今天/近几天的弱项
    & $PY $CE gen --from-weak --days 3 --rating again
    #   内部跑 code/analysis/today_weak.py --plain --days 3 --rating again，取它的 stdout 词表

    # Jisho 相关开关（gen）
    & $PY $CE gen --words "徹夜" --refresh-jisho         # 忽略缓存，重新抓 Jisho 一页
    & $PY $CE gen --words "徹夜" --allow-model-sentence  # Jisho 零候选时退回模型造句（默认不退回）

目标选择器（按优先级取**第一个**给出的；gen/tts/apply 必须有其一）
--------------------------------------------------------------
    --note-ids 1621392074520,1621392074521   Anki 的 noteId
    --words "徹夜,あまり"                     比 Word 字段（退回 Transliteration），忽略大小写与空格
    --from-file PATH                         一行一个词或 noteId（# 注释与空行忽略）
    --from-weak [--days N] [--rating again|hard]   今天/近几天的弱项词（跑 today_weak.py 取词表）
    --query "<任意 Anki 查询>"                如 'tag:待补例句'；默认只加 deck+模型过滤
    --all                                    显式全库（≈6000 张，只读体检/批量补时才用）
    --only SCOPE, --limit N                  范围过滤 + 最多做几张（作用在「待做卡」上）

范围 `--only`（默认**不含** not-merged，见契约 §5.3）
-----------------------------------------------------
    missing-sentence  Sentence 只有 1 块 → 从 **Jisho** 取第 2 句（真实语料，不是造句）
    missing-ruby      Sentence HTML 有汉字但没有振假名 / 为空 → 模型补振假名
                      （已有 2 句的卡：第 1 句走 `sentence1_ruby`，第 2 句缺/坏振假名走 `sentence2_ruby`）
    not-merged        已有 2 句但 AINote 里没有 ①② 合并 → 契约 §5.3 要求**① 也由模型产出**
                      （响应里额外给 core1/grammar1/conjugation1/context1）
                      ⚠️ 当前 `core6000_example_prompt.md` 只让模型输出 10 个键、没有这四个，
                      所以这个范围会被**提前拦下**并在报告里写明原因（要跑它先给提示词加那一节）

没有目标选择器时：`gen/tts/apply` 直接拒绝并打印选择器清单（不默认全库；要全库必须显式 `--all`，
或用 `--only SCOPE --limit N` 限定规模）。只有 `scan`（体检）和 `status`（看进度）能不带选择器跑。

只做用户点名的卡
----------------
* **already_ok**：已经有合规「② + 音频」的卡（2 块句 + 完整振假名 + 2 个 `[sound:]` + 有中文），
  重跑报 `already_ok` 跳过 —— 不会重复追加第二句、不会重复写同一个 `[sound:]`；
  写库后的卡再渲染是**逐字不动点**（同一条模型产出渲染两次结果完全一样）。`--force` 才重做。
* 修不了的卡（3 句以上、提示词不支持的 not-merged）会在报告里
  逐条列出原因，绝不动它。
* `--words` / `--from-weak` 的词形匹配走本地精确比对（忽略大小写与空格）；Anki 的字段查询
  对中日文只是子串匹配，所以匹配不上的词会查 `word_index.json`（**词形索引缓存**，
  首次建一次，约 6000 张卡读一遍，之后毫秒级）。

安全
----
* `apply` 默认**演练**（打印 5 个字段的原文前后对照 + 完整 Sentence HTML + AINote 前 700 字）；
  `--commit` 前把 5 个旧字段值写进 `backup_<时间戳>.json`（revert 的唯一依据），
  媒体上传后 `getMediaFilesNames` 回读确认，写完逐卡回读校验。
* 全程只碰那 5 个字段；从不 `addTags`、不动 deck、不动 `cards.due`。

落盘（全部在 data/core6000/ 与 output/audio/core6000/）
-------------------------------------------------------
    state.json               本次选择的每张卡状态（句块/版式/范围/缺什么/已合规）
    plan_<日期>.json         本次要做的清单 + 渲染所需的每张卡明细（= 断点续跑清单）
    report_<日期>.md         人看的报告（scan/gen/tts/apply 都会刷新它）
    word_index.json          词形索引缓存（--words / --from-weak 用）
    jisho/<noteId>.json      Jisho 例句候选（含振假名、出处链接、过滤统计；重跑/gen 重试都读它）
    gen/<noteId>_in.json     发给模型的那张卡 + 本次选定的 sentence_source（追溯）
    gen/<noteId>_out.json    模型产出（**断点续跑的最小单位**）
    gen/<noteId>_meta.json   usage / 耗时 / 闸门结论
    metrics_<日期>.json      token 账本
    backup_<时间戳>.json     apply --commit 前的字段快照（revert 的唯一依据）
    output/audio/core6000/core6000-<noteId>-sentence-2.mp3

坑（实测）
----------
1. **标签可能带振假名**：`<b>中文<ruby>翻译<rt>ほんやく</rt></ruby></b>` —— 比对板块名时必须
   **先删 `<rt>` 再剥标签**，否则 122 张卡的板块认不出来。
2. **标签可能是被 `<p>` 包住的 `<b>`**：`<p><b>中文翻译</b>：正文</p>`。用不重叠的正则扫
   `<p>…</p>` 会把里面的 `<b>` 一起吃掉 → 整个板块连正文一起被静默丢掉（实测 121 张卡全是
   这种形态）。所以标记要**单独扫 `<b>/<strong>/<h3>/<h4>`**，只把「整体就是标签」的裸 `<p>`
   也当候选；认不出的内容一律作为「认不出板块」整块保留。
3. **`Sentence HTML` 的块分隔不一定是 `<br><br>`**：`する` 那类卡是 `<p>句1<br>句2</p>`，
   依次试 `<br><br>` / `</p><p>` / 单个 `<br>`，取块数正好等于原句数的那种；都不等 → 走模型值。
4. **原卡已有两条例句时绝不重写句子**：落库的句子就是原来那两句（响应里的 `new_sentence` 只用来
   对齐振假名与 ② 讲解）。模型另造了一句 → 记一条 `sentence2_mismatch` 警告；第二句缺/坏振假名的
   那种现在能修：输入里带 `need_sentence2_ruby`，模型用 `sentence2_ruby` 交回**同一句 + 振假名**
   （闸门 5b 验「去 ruby 后与卡上第二句逐字一致 + 振假名合规」；不合格就拒绝这张卡，
   绝不把模型改写过的那句写进库）。
5. **闸门 1/2 只管「模型造的新句」**：2 句的卡里 `new_sentence` 只是原样重复第二句，那一句是卡里
   的既有数据（`する` 的第二句「…サッカーをしている」本来就不含「する」），拿闸门 1 卡它是误伤。
6. **3 句以上的卡跳过**（全库 1 张）：闸门 6 要求恰好 2 块，脚本没有安全的自动处置方式。
7. 有人开着 Anki 浏览器看这些卡时，`--commit` 的字段不会刷新（先关掉浏览器 / 切走再切回）。
8. **Jisho 是外部依赖**：一页最多 20 条、robots.txt 要求 crawl-delay 40s，所以
   **一张卡只抓一页**并落 `data/core6000/jisho/<noteId>.json`；重跑 gen / 重试都读缓存
   （`--refresh-jisho` 才重抓）。零候选**不退回模型造句**——宁可这张卡失败、点名换词，
   也不往库里塞一句没人说过的话。`data/pylibs` 里没有 lxml，`jisho_example` 会自动用
   `code/tools/minihtml.py`（标准库实现的等价解析）。

只用 Python 标准库（+ 复用 code/execution/today_new.py、code/tools/edge_tts_min.py、
code/tools/jisho_example.py、code/common/paths.py、code/analysis/today_weak.py）；不 pip install。
AnkiConnect 必须在 127.0.0.1:8765，本地模型默认 http://127.0.0.1:8080/v1（NInfer；Responses API：/v1/responses）。
"""
import argparse
import datetime as dt
import difflib
import glob
import json
import os
import re
import subprocess
import sys
import time
import unicodedata


_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_CODE, 'common'))    # paths.py
sys.path.insert(0, os.path.join(_CODE, 'tools'))     # edge_tts_min.py
sys.path.insert(0, _HERE)                            # today_new.py
import anki_api as AK         # noqa: E402  唯一的 Anki 访问点
import paths as WSP           # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
import today_new as TN        # noqa: E402  （可安全 import：argparse 只在它的 __main__ 里跑）
import edge_tts_min as TTS    # noqa: E402

# ============================================================================
# 常量：路径 / 字段名 / 范围
# ============================================================================
DECK = '0-日本语学习::0-词汇::1-高频日语单词 6000'
NOTE_MODEL = 'Japanese Vocabulary'
ANKI_URL = AK.CONFIG['url']

DATA_DIR = getattr(WSP, 'DATA_CORE6000', os.path.join(WSP.DATA, 'core6000'))
GEN_DIR = os.path.join(DATA_DIR, 'gen')
AUDIO_DIR = getattr(WSP, 'OUT_AUDIO_CORE6000',
                    os.path.join(WSP.OUT_AUDIO, 'core6000'))
STATE_FILE = os.path.join(DATA_DIR, 'state.json')
WORD_INDEX = os.path.join(DATA_DIR, 'word_index.json')   # 词形索引缓存（--words/--from-weak 用）
WEAK_SCRIPT = os.path.join(WSP.ANALYSIS, 'today_weak.py')
# 系统提示词：另一个文件（模型侧规范）。默认读它，--system-prompt 可覆盖。
# 本脚本**只读**这个文件，不生成、不覆盖它。
PROMPT_FILE = os.path.join(_HERE, 'core6000_example_prompt.md')

F_WORD = 'Word'
F_READ = 'Transliteration'
F_POS = 'Part of Speech'
F_MEAN = 'Meaning'
F_SENT = 'Sentence'
F_HTML = 'Sentence HTML'
F_TRANS = 'Sentence Translation'
F_NOTE = 'AINote'
F_AUDIO = 'Sentence Audio'
# apply 只碰这 5 个字段；其余（Index/Word/Transliteration/Meaning/Part of Speech/Pitch Accent*）
# 一个字都不动，也不加标签。
TOUCH_FIELDS = (F_SENT, F_HTML, F_NOTE, F_TRANS, F_AUDIO)

SCOPE_SENT = 'missing-sentence'
SCOPE_RUBY = 'missing-ruby'
SCOPE_MERGE = 'not-merged'
SCOPES = (SCOPE_SENT, SCOPE_RUBY, SCOPE_MERGE)
# 默认不含 not-merged：契约 §5.3「该范围默认不参与，必须显式 --only not-merged」。
DEFAULT_SCOPES = (SCOPE_SENT, SCOPE_RUBY)
# 修不了的缺陷（不在任何 --only 范围里）：报告出来，人工处理。
DEFECT_MULTI = 'multi-sentence'      # 3 句以上，闸门 6 要 2 块
DEFECT_AUDIO = 'audio-count'         # 已有 2 句但 [sound:] 不是 2 个
DEFECT_TRANS = 'translation-empty'   # 中文翻译字段是空的

VOICE = 'ja-JP-NanamiNeural'
MIN_MP3_BYTES = 1024          # 小于它视为没合成功
AUDIO_BPS = 48000             # edge-tts 输出 audio-24khz-48kbitrate-mono-mp3 → 48 kbps
SENT_MIN, SENT_MAX = 6, 45    # 闸门 2：新句长度（去空白）
GATE_KEY_LEN = 12             # 闸门 8：原文首 12 字
NOTE_CHUNK = 200              # notesInfo 批量

# ---- 例句源：Jisho（真实语料），不是模型造句 --------------------------------
# 新句一律来自 jisho.org 的 Sentence 搜索（Tatoeba / Jreibun 人工语料），
# 由 code/tools/jisho_example.py 抓取 + 渲染振假名；模型只写讲解（cn2/grammar2/…），
# 不许改句子。`--allow-model-sentence` 才退回旧行为（模型造句）。
JISHO_DIR = os.path.join(DATA_DIR, 'jisho')    # 按 noteId 缓存的候选（尊重 Jisho crawl-delay）
JISHO_MIN_SIMILARITY = 0.72    # 与第一句的相似度**上限**：再像就是换皮，换下一条
JISHO_SOURCE_FIELD = 'sentence_source'   # payload 里给模型看的键名

# 板块名归一化（只用于内部对齐；渲染时仍用原卡的标签文字，见契约 §5.2）
CANON_ALIASES = (
    ('中文翻译', ('中文翻译', '翻译', '例句翻译')),
    ('核心词汇', ('核心词汇', '重要词汇', '单词')),
    ('语法要点', ('语法要点', '语法', '语法解析', '语法点')),
    ('动词变形解析', ('动词变形解析', '词形解析', '变形解析', '活用', '动词变化')),
    ('语境与表达风格', ('语境与表达风格', '语境', '表达风格', '语境与风格')),
)
CANON_ORDER = ('中文翻译', '核心词汇', '语法要点', '动词变形解析', '语境与表达风格')
REQUIRED_CANON = ('中文翻译', '核心词汇', '语法要点')     # 闸门 7

# ============================================================================
# 正则
# ============================================================================
RE_BR2 = re.compile(r'<br\s*/?>\s*<br\s*/?>', re.I)
RE_BR1 = re.compile(r'<br\s*/?>', re.I)
RE_PBOUND = re.compile(r'</p>\s*<p\b[^>]*>', re.I)
RE_BLOCK = re.compile(r'<br\s*/?>\s*<br\s*/?>|</p>\s*<p\b[^>]*>', re.I)
RE_RUBY = re.compile(r'<ruby\b[^>]*>(.*?)</ruby>', re.S | re.I)
RE_RT = re.compile(r'<rt\b[^>]*>.*?</rt>', re.S | re.I)
RE_BR_ANY = re.compile(r'<br\s*/?>', re.I)
RE_SHELL = re.compile(r'</?(?:p|b|strong|em|i|h1|h2|h3|h4|h5|h6|ul|ol|div|span|font|center|'
                      r'table|thead|tbody|tr|td|th|blockquote)\b[^>]*>', re.I)
RE_MARKER = re.compile(r'<(h3|h4|h5|b|strong)\b[^>]*>(.*?)</\1\s*>', re.S | re.I)
# 裸写在一个 <p> 里的板块名（`<p>1. 中文翻译</p>`，没有 <b>）。
# 注意：标记扫描里**不能**把 `p` 放进 RE_MARKER 的候选里 —— finditer 是不重叠扫描，
# `<p><b>中文翻译</b>：正文</p>` 会被整个 <p> 吃掉，里面的 <b> 就再也扫不到（踩过）。
RE_PBLOCK = re.compile(r'<p\b[^>]*>(.*?)</p>', re.S | re.I)
RE_NUMBER = re.compile(r'^\s*[（(\[]?\s*(?:\d+|[一二三四五六七八九十]+)\s*[.、,，)）\]:：]\s*')
RE_LABEL_TAIL = re.compile(r'\s*[:：]\s*$')
RE_SPACES = re.compile(r'[ \t\u3000]{2,}')
RE_WS = re.compile(r'\s+')
RE_KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30a0-\u30ffー]+$')


# ============================================================================
# 小工具：JSON / 文本
# ============================================================================
def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1))


def read_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print('警告：读不出 %s（%s）' % (path, e), file=sys.stderr)
        return default


def flatten(text):
    """闸门用口径：整块删掉 <rt>…</rt>（读音），再剥标签，再去掉所有空白。"""
    return RE_WS.sub('', TN.strip_ruby_readings(text or ''))


def plain(text):
    """人看的纯文本：去 ruby 读音、去标签、空白压成一个空格。"""
    return RE_WS.sub(' ', TN.strip_ruby_readings(text or '')).strip()


def one_line(text, limit=120):
    t = plain(text)
    return t if len(t) <= limit else t[:limit] + '…'


def clean_malformed_ruby(html):
    """`<ruby><br>…風<rt>かぜ</rt></ruby>` 这类畸形注音：清掉基底里的 <br>。

    口径同 today_new.py::sentence_html_line（那里还会把 <br> 换成 ' / '，
    这里是字段重建，只清 ruby 内部的换行）。
    """
    def drop_br(m):
        return RE_BR_ANY.sub('', m.group(0))

    return RE_RUBY.sub(drop_br, html or '')


def strip_outer_wrappers(html):
    """剥掉最外层唯一的 <div …> / <p …> 外壳（只剥一层壳，不拆里面的块）。"""
    s = (html or '').strip()
    for _ in range(4):
        if (re.match(r'^<div\b', s, re.I) and re.search(r'</div>\s*$', s, re.I)
                and len(re.findall(r'<div\b', s, re.I)) == 1):
            s = re.sub(r'</div>\s*$', '', re.sub(r'^<div\b[^>]*>', '', s, count=1, flags=re.I),
                       flags=re.I).strip()
            continue
        if (re.match(r'^<p\b', s, re.I) and re.search(r'</p>\s*$', s, re.I)
                and len(re.findall(r'<p\b', s, re.I)) == 1):
            s = re.sub(r'</p>\s*$', '', re.sub(r'^<p\b[^>]*>', '', s, count=1, flags=re.I),
                       flags=re.I).strip()
            continue
        break
    return s


def count_blocks(text):
    """按主分隔（`<br><br>` / `</p><p>`）数块；先剥外壳、清畸形 ruby。"""
    core = strip_outer_wrappers(clean_malformed_ruby(text or ''))
    return len([x for x in RE_BLOCK.split(core) if flatten(x)])


def ruby_covers(html):
    """这块 HTML 是否给**所有汉字**都配了合规振假名（契约闸门 4 的口径）。

    * 每个 `<ruby>` 都必须有 `<rt>`；
    * ruby 基底不得只含假名（お/ご 这类敬语接头辞不能单独进基底）；
    * ruby 之外不能再有汉字（否则有汉字没注音）。
    """
    h = clean_malformed_ruby(html or '')
    if not h.strip():
        return False
    for inner in RE_RUBY.findall(h):
        if not re.search(r'<rt\b[^>]*>.*?</rt>', inner, re.S | re.I):
            return False
        base = TN.strip_tags(RE_RT.sub('', inner)).strip()
        if not base or not TN.KANJI.search(base):
            return False
        if RE_BR_ANY.search(base):
            return False
    return not TN.KANJI.search(TN.strip_tags(RE_RUBY.sub('', h)))


def block_needs_ruby(block):
    """去掉读音后仍有汉字 = 这块需要振假名。"""
    return bool(TN.KANJI.search(TN.strip_tags(RE_RT.sub('', block or ''))))


def block_ruby_ok(block):
    return (not block_needs_ruby(block)) or ruby_covers(block)


def split_sentence_html(html, n):
    """把 `Sentence HTML` 切成 n 块（逐块去外壳，返回内层 HTML）。

    依次试 `<br><br>` / `</p><p>` / 单个 `<br>`，取块数正好等于 n 的那一种；
    都不等 → None（= 不可用，走模型值）。
    """
    s = clean_malformed_ruby(html or '')
    if not flatten(s):
        return None
    core = strip_outer_wrappers(s)
    for rx in (RE_BR2, RE_PBOUND, RE_BR1):
        parts = [strip_outer_wrappers(x) for x in rx.split(core)]
        parts = [x for x in parts if flatten(x)]
        if len(parts) == n:
            return parts
    return None


def split_blocks(text):
    """按 `<br><br>` 切块（`Sentence` / `Sentence Translation` 用）。"""
    return [x.strip() for x in RE_BR2.split(text or '') if flatten(x)]


def join_blocks(text):
    """把字段里的多个块用标准 `<br><br>` 重新拼起来（内容是原来的）。"""
    return '<br><br>'.join(split_blocks(text))


def dedupe(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


# ============================================================================
# 板块解析（契约 §5.2）：标签归一化 / 版式族 / 正文清洗
# ============================================================================
def normalize_label(inner_html):
    """把板块标签文字归一化到 5 个规范名之一；认不出来返回 ''。"""
    t = TN.strip_tags(RE_RT.sub('', inner_html or ''))    # 先删读音再剥标签（坑 1）
    t = RE_WS.sub('', t)
    t = RE_NUMBER.sub('', t)
    t = RE_LABEL_TAIL.sub('', t)
    if not t:
        return ''
    for canon, aliases in CANON_ALIASES:
        if t in aliases:
            return canon
    return ''


def clean_label(inner_html):
    """标签文字（沿用原卡）：只留文字与 `<ruby>`，去掉 `<p>/<b>/<strong>` 外壳与序号外的东西。"""
    store = []
    saved = TN._extract_existing_ruby(inner_html or '', store)   # 先把 ruby 片段挖出来占位
    saved = RE_WS.sub(' ', TN.strip_tags(saved))
    return TN._put_back_ruby(saved, store).strip()


def clean_section_body(raw):
    """清洗原卡板块正文：删外壳标签，保留 <ruby> / <br> / 正文与序号。

    `ul` 列表的 `</li>` 变成 `<br>`（这样 ul 版式渲染回 `<li>` 时行数不变）；
    标签后面的分隔冒号（`<b>中文翻译</b>：正文`）属于标签，不留在正文里。
    """
    s = raw or ''
    s = re.sub(r'<li\b[^>]*>', '', s, flags=re.I)
    s = re.sub(r'</li\s*>', '<br>', s, flags=re.I)
    s = RE_SHELL.sub('', s)
    s = RE_BR2.sub('<br>', s)
    s = re.sub(r'(?:\s*<br\s*/?>\s*)+$', '', s.strip(), flags=re.I)
    s = re.sub(r'^(?:\s*<br\s*/?>\s*)+', '', s, flags=re.I)
    s = RE_SPACES.sub(' ', s)
    s = re.sub(r'^\s*[:：]\s*', '', s)          # 标签后面的分隔冒号
    return s.strip()


def parse_sections(ainote):
    """把 AINote 拆成板块列表。

    返回 (sections, layout, outer_open)：
      sections   顺序列表，每项 {'canon','label','body','raw'}；`canon` 为空 = 认不出，
                 `raw` 整块原样保留（契约 §5.2：不丢信息）
      layout     h3 / p-b / ul / plain（判定见契约 §5.2 表格）
      outer_open 原卡最外层的 `<div …>` 开标签（没有则 '<div>'）

    标记（= 板块名）可能是 `<h3>`/`<h4>`、`<b>`/`<strong>`，也可能是裸写在一个 `<p>` 里的
    `1. 中文翻译`。要点：
      * 标记的**内层标签要单独扫**：`<p><b>中文翻译</b>：正文</p>` 里 `<b>` 被 `<p>` 包住，
        只扫 `<p>` 会整块漏掉（121 张卡踩过），于是正文被静默丢掉；
      * 被别的候选**包住**的外层候选要丢掉（`<p><b>X</b></p>` 只留 `<b>`），否则会多出空板块；
      * 标记之间/之前那些**不属于任何板块**的内容，一律作为「认不出」板块整块保留。
    """
    html = ainote or ''
    outer = re.match(r'^\s*(<div\b[^>]*>)', html, re.I)
    outer_open = outer.group(1) if outer else '<div>'

    cands = []
    for m in RE_MARKER.finditer(html):           # <h3>/<h4>/<h5>/<b>/<strong>
        cands.append({'tag': m.group(1).lower(), 'start': m.start(), 'end': m.end(),
                      'canon': normalize_label(m.group(2)), 'label': clean_label(m.group(2))})
    for m in RE_PBLOCK.finditer(html):           # <p>1. 中文翻译</p>（裸标签）
        canon = normalize_label(m.group(1))
        if canon:
            cands.append({'tag': 'p', 'start': m.start(), 'end': m.end(),
                          'canon': canon, 'label': clean_label(m.group(1))})
    cands = [c for c in cands if c['canon']]
    if not cands:                                # 一个板块名都认不出 → 整块原样保留
        if flatten(html):
            return ([{'canon': '', 'label': '', 'body': clean_section_body(html),
                      'raw': html.strip()}], 'plain', outer_open)
        return ([], 'plain', outer_open)
    kept = [c for c in cands
            if not any(o is not c and o['start'] >= c['start'] and o['end'] <= c['end']
                       and (o['start'] > c['start'] or o['end'] < c['end']) for o in cands)]
    seen_span, uniq = set(), []
    for c in sorted(kept, key=lambda c: (c['start'], c['end'])):
        if (c['start'], c['end']) in seen_span:
            continue
        seen_span.add((c['start'], c['end']))
        uniq.append(c)

    sections, pos = [], 0
    for i, c in enumerate(uniq):
        gap = html[pos:c['start']]
        if flatten(gap):                         # 标记之前有内容 → 认不出的板块
            sections.append({'canon': '', 'label': '', 'body': clean_section_body(gap),
                             'raw': gap.strip()})
        stop = uniq[i + 1]['start'] if i + 1 < len(uniq) else len(html)
        raw = html[c['end']:stop]
        sections.append({'canon': c['canon'], 'label': c['label'],
                         'body': clean_section_body(raw), 'raw': raw.strip()})
        pos = stop

    low = html.lower()
    if '<h3' in low or any(c['tag'] in ('h3', 'h4', 'h5') for c in uniq):
        layout = 'h3'
    elif any(c['tag'] in ('b', 'strong') for c in uniq) or '<p><b>' in low.replace(' ', ''):
        layout = 'p-b'
    elif '<ul' in low:
        layout = 'ul'
    else:
        layout = 'plain'
    return sections, layout, outer_open


def section_map(sections):
    """canon -> 该板块的（首个）正文；认不出的板块单独列出来。"""
    known, unknown = {}, []
    for sec in sections:
        if sec['canon']:
            known.setdefault(sec['canon'], sec)
        else:
            unknown.append(sec)
    return known, unknown


# ============================================================================
# 单张卡分析
# ============================================================================
def first_translation(trans_field, n_sent):
    """原句的中文：块数与句数对得上就逐句给，否则整块给。"""
    blocks = split_blocks(trans_field)
    if not blocks:
        return ['' for _ in range(max(1, n_sent))]
    if len(blocks) == n_sent:
        return blocks
    out = list(blocks)
    while len(out) < n_sent:
        out.append('')
    return out[:n_sent]


def analyze_note(note):
    """把一条笔记变成「状态 + 明细」。用不到的东西一律不动。"""
    fields = note.get('fields', {})
    val = lambda k: (fields.get(k) or {}).get('value', '') or ''
    word = plain(val(F_WORD)).split('\n')[0].strip()
    reading = RE_WS.sub('', plain(val(F_READ)))
    pos = plain(val(F_POS))
    meaning = plain(val(F_MEAN))
    sent_field = val(F_SENT)
    html_field = val(F_HTML)
    trans_field = val(F_TRANS)
    ainote = val(F_NOTE)
    audio_field = val(F_AUDIO)

    sent_blocks = split_blocks(sent_field)
    n_sent = len(sent_blocks)
    html_blocks = split_sentence_html(html_field, n_sent) if 1 <= n_sent <= 2 else None
    sections, layout, outer_open = parse_sections(ainote)
    known, unknown = section_map(sections)
    flat_note = flatten(ainote)
    unmerged = n_sent >= 2 and not ('①' in flat_note and '②' in flat_note)

    need_ruby1 = (html_blocks is None) or (not block_ruby_ok(html_blocks[0]))
    need_ruby2 = (n_sent >= 2) and ((html_blocks is None) or (not block_ruby_ok(html_blocks[1])))

    scopes = []
    if n_sent == 1:
        scopes.append(SCOPE_SENT)
    if need_ruby1 or need_ruby2:
        scopes.append(SCOPE_RUBY)
    if unmerged:
        scopes.append(SCOPE_MERGE)

    trans = first_translation(trans_field, max(1, n_sent))
    sentences = []
    for i in range(n_sent):
        sentences.append({
            'jp': plain(sent_blocks[i]),
            'cn': plain(trans[i]) if i < len(trans) else '',
            'ruby': (html_blocks[i] if html_blocks and i < len(html_blocks) else ''),
        })
    return {
        'id': int(note['noteId']),
        'index': TN.as_int(val('Index'), 10 ** 9),
        'word': word,
        'reading': reading,
        'pos': pos,
        'meaning': meaning,
        'n_sent': n_sent,
        'unmerged': unmerged,
        'need_new': (n_sent == 1),
        'need_ruby1': need_ruby1,
        'need_ruby2': need_ruby2,
        'scopes': scopes,
        'layout': layout,
        'outer_open': outer_open,
        'sentences': sentences,
        'sent_blocks': sent_blocks,
        'trans_blocks': split_blocks(trans_field),
        'audio_files': TN.audio_files(audio_field),
        'sections': sections,
        'section_missing': [c for c in REQUIRED_CANON if c not in known],
        'section_unknown': [s['label'] or '(无标签)' for s in unknown],
        'snapshot': {k: val(k) for k in TOUCH_FIELDS},
    }


def card_deficits(card, scopes):
    """这张卡离「两条例句 + 完整振假名 + 2 条音频」还差什么。

    返回缺陷列表；空 = **already_ok**（重跑是 no-op）。
    `not-merged` 只在显式要求（scopes 里有它）时才算缺陷 —— 契约 §5.3。
    """
    d = []
    if card['n_sent'] > 2:
        d.append(DEFECT_MULTI)
    elif card['n_sent'] == 1:
        d.append(SCOPE_SENT)
    if card['need_ruby1'] or card['need_ruby2']:
        d.append(SCOPE_RUBY)
    if card['n_sent'] >= 2 and len(card['audio_files']) != 2:
        d.append(DEFECT_AUDIO)
    if not any(s['cn'] for s in card['sentences']):
        d.append(DEFECT_TRANS)
    if card['n_sent'] >= 2 and card['unmerged'] and SCOPE_MERGE in scopes:
        d.append(SCOPE_MERGE)
    return dedupe(d)


def card_state(card, scopes, force=False):
    """→ ('work' | 'already_ok' | 'blocked', 缺陷列表)。"""
    d = card_deficits(card, scopes)
    if not d:
        return ('work' if force else 'already_ok'), d
    if any(x in scopes for x in d):
        return 'work', d
    return 'blocked', d


# ============================================================================
# 目标选择（按需：用户点名的卡）
# ============================================================================
def base_query():
    return 'deck:"%s" note:"%s"' % (DECK, NOTE_MODEL)


def query_with_defaults(raw):
    """`--query` 直接给整条查询；缺 deck:/note: 过滤就补上（避免误伤别的牌组）。"""
    q = (raw or '').strip()
    if not q:
        return base_query()
    low = q.lower()
    if 'deck:' not in low and 'deck :' not in low:
        q = 'deck:"%s" %s' % (DECK, q)
    if 'note:' not in low:
        q = '%s note:"%s"' % (q, NOTE_MODEL)
    return q


def fetch_notes(query):
    ids = AK.find_notes(query)
    notes = AK.notes_info(ids, chunk=NOTE_CHUNK)
    notes.sort(key=lambda n: (TN.as_int((n.get('fields', {}).get('Index') or {}).get('value'),
                                        10 ** 9), int(n['noteId'])))
    return notes, len(ids)


def parse_words(text):
    return [w for w in re.split(r'[,，、\s]+', text or '') if w.strip()]


def norm_word(text):
    """比词形用：去标签/去读音、去掉所有空白、统一大小写、去掉装饰符。"""
    t = RE_WS.sub('', plain(text))
    t = t.strip('〜～~・-—–')
    return t.lower()


def word_of(card):
    return norm_word(card['word']), norm_word(card['reading'])


def match_words(cards, words):
    """返回 (命中卡列表, 没匹配上的词)。忽略大小写与空格。"""
    want = [(w, norm_word(w)) for w in words]
    hits, unmatched = {}, []
    for card in cards:
        w, r = word_of(card)
        for raw, key in want:
            if key and (key == w or (r and key == r)):
                hits.setdefault(key, []).append(card)
    out = []
    for raw, key in want:
        got = hits.get(key)
        if got:
            out.extend(got)
        else:
            unmatched.append(raw)
    seen, uniq = set(), []
    for c in out:
        if c['id'] not in seen:
            seen.add(c['id'])
            uniq.append(c)
    return uniq, unmatched


def _anki_word_clause(field, word):
    w = (word or '').replace('"', '').strip()
    if not w:
        return ''
    if re.search(r'[\s:()\[\]{}]', w):
        return '"%s:%s"' % (field, w)
    return '%s:%s' % (field, w)


def word_index(rebuild=False):
    """{归一化词形: [noteId]}，落盘缓存（首次建一次，之后按需选中是毫秒级）。

    Anki 的字段查询对中日文只是子串匹配、也不做大小写/空格归一，所以「点名的词到底在不在卡里」
    最终要用本地精确比对来判。整库读一遍（≈6000 张）比较贵，所以缓存到
    `data/core6000/word_index.json`；牌组张数对不上（新增/删卡）就重建。
    """
    ids = AK.find_notes(base_query())
    cache = read_json(WORD_INDEX) or {}
    if (not rebuild and cache.get('count') == len(ids)
            and isinstance(cache.get('map'), dict) and cache['map']):
        return cache['map']
    notes, _n = fetch_notes(base_query())
    idx = {}
    for n in notes:
        fields = n.get('fields', {})
        for key in (F_WORD, F_READ):
            w = norm_word((fields.get(key) or {}).get('value', ''))
            if not w:
                continue
            idx.setdefault(w, [])
            if int(n['noteId']) not in idx[w]:
                idx[w].append(int(n['noteId']))
    write_json(WORD_INDEX, {'built_at': dt.datetime.now().isoformat(timespec='seconds'),
                            'count': len(ids), 'deck': DECK, 'map': idx})
    print('已建词形索引 %d 条（%d 张卡）→ %s' % (len(idx), len(ids), WORD_INDEX), file=sys.stderr)
    return idx


def notes_by_words(words):
    """按词形取笔记（返回**原始 note 对象**，不是分析结果）。

    先用 Anki 的 `Word:` / `Transliteration:` 粗筛（快），再本地精确比对（忽略大小写/空格）；
    还有词没匹配上 → 查词形索引（缓存，首次会建一次）。
    """
    clauses = []
    for w in words:
        for field in ('Word', 'Transliteration'):
            c = _anki_word_clause(field, w)
            if c:
                clauses.append(c)
    notes, _n = fetch_notes('(%s) %s' % (' OR '.join(clauses), base_query()))
    hits, unmatched = match_words([analyze_note(n) for n in notes], words)
    hit_ids = {c['id'] for c in hits}
    out = [n for n in notes if int(n['noteId']) in hit_ids]
    if unmatched:
        print('提示：Anki 字段查询没匹配上 %d 个词，改用词形索引…' % len(unmatched),
              file=sys.stderr)
        idx = word_index()
        have = {int(n['noteId']) for n in out}
        want, still = [], []
        for w in unmatched:
            got = idx.get(norm_word(w)) or []
            if got:
                want.extend(got)
            else:
                still.append(w)
        want = [i for i in dedupe(want) if i not in have]
        out.extend(AK.notes_info(want, chunk=NOTE_CHUNK))
        unmatched = still
    return out, unmatched


def notes_by_ids(text):
    ids = [int(x) for x in re.split(r'[,，、\s]+', text or '') if x.strip().isdigit()]
    if not ids:
        raise SystemExit('--note-ids 里没有合法的 noteId：%r' % text)
    notes = AK.notes_info(ids, chunk=NOTE_CHUNK)
    got = {int(n['noteId']): n for n in notes}
    missing = [i for i in ids if i not in got]
    if missing:
        raise SystemExit('这些 noteId 在 Anki 里不存在：%s' % '、'.join(map(str, missing)))
    wrong = [int(n['noteId']) for n in notes if n.get('modelName') != NOTE_MODEL]
    if wrong:
        raise SystemExit('这些 noteId 不是 %s 模型的卡：%s'
                         % (NOTE_MODEL, '、'.join(map(str, wrong))))
    notes.sort(key=lambda n: (TN.as_int((n.get('fields', {}).get('Index') or {}).get('value'),
                                        10 ** 9), int(n['noteId'])))
    return notes


def read_from_file(path):
    if not os.path.exists(path):
        raise SystemExit('--from-file 找不到文件：%s' % path)
    ids, words = [], []
    with open(path, encoding='utf-8-sig') as fh:
        for line in fh:
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            if line.isdigit():
                ids.append(line)
            else:
                words.extend(parse_words(line))
    if not ids and not words:
        raise SystemExit('--from-file 里没有内容（一行一个词或 noteId，# 是注释）：%s' % path)
    return ids, words


def weak_words(args):
    """跑 today_weak.py --plain 取词表（名字走 stdout，统计走 stderr）。

    这里**不用管道**接子进程输出（沙箱里管道可能被拒）：stdout/stderr 各写一个临时文件再读。
    """
    if not os.path.exists(WEAK_SCRIPT):
        raise SystemExit('找不到 %s（--from-weak 用它取词表）' % WEAK_SCRIPT)
    days = str(getattr(args, 'days', 1) or 1)
    rating = getattr(args, 'rating', None)
    cmd = [sys.executable, WEAK_SCRIPT, '--plain', '--days', days]
    if rating:
        cmd += ['--rating', rating]
    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, '_from_weak_stdout.txt')
    err_path = os.path.join(DATA_DIR, '_from_weak_stderr.txt')
    print('跑弱项取词：%s' % ' '.join('"%s"' % c if ' ' in c else c for c in cmd[1:]))
    with open(out_path, 'wb') as fo, open(err_path, 'wb') as fe:
        proc = subprocess.run(cmd, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL)
    err = ''
    if os.path.exists(err_path):
        with open(err_path, encoding='utf-8', errors='replace') as fh:
            err = fh.read()
        os.remove(err_path)
    if err:
        sys.stderr.write(err if err.endswith('\n') else err + '\n')
    words = []
    if os.path.exists(out_path):
        with open(out_path, encoding='utf-8', errors='replace') as fh:
            words = [ln.strip() for ln in fh if ln.strip()]
        os.remove(out_path)
    if proc.returncode != 0:
        raise SystemExit('today_weak.py 退出码 %s；--from-weak 拿不到词表。' % proc.returncode)
    if not words:
        raise SystemExit('today_weak.py 没输出任何词（近 %s 天没有弱项？）' % days)
    print('弱项词表 %d 个：%s' % (len(words), '、'.join(words[:12])
                                 + ('…' if len(words) > 12 else '')))
    return words


def resolve_targets(args):
    """按优先级取一个目标选择器：note-ids > words > from-file > from-weak > query。"""
    given = [k for k in ('note_ids', 'words', 'from_file', 'from_weak', 'query')
             if getattr(args, k, None)]
    if len(given) > 1:
        print('提示：同时给了 %s，按优先级只用 --%s'
              % ('、'.join('--' + g.replace('_', '-') for g in given),
                 given[0].replace('_', '-')), file=sys.stderr)
    if getattr(args, 'note_ids', None):
        return {'mode': 'note-ids', 'ids': getattr(args, 'note_ids'), 'words': []}
    if getattr(args, 'words', None):
        return {'mode': 'words', 'ids': '', 'words': parse_words(args.words)}
    if getattr(args, 'from_file', None):
        ids, words = read_from_file(args.from_file)
        return {'mode': 'from-file', 'ids': ','.join(ids), 'words': words,
                'path': args.from_file}
    if getattr(args, 'from_weak', False):
        return {'mode': 'from-weak', 'ids': '', 'words': weak_words(args),
                'days': getattr(args, 'days', 1), 'rating': getattr(args, 'rating', None)}
    if getattr(args, 'query', None):
        return {'mode': 'query', 'ids': '', 'words': [], 'query': args.query}
    if getattr(args, 'all', False):
        return {'mode': 'all', 'ids': '', 'words': []}
    return None


SELECTOR_HELP = """没有给目标选择器 —— 按需补例句必须点名要补哪些卡，这里拒绝全库跑。

请挑一个（按优先级）：
  --note-ids 1621392074520,1621392074521     点名的 noteId
  --words "徹夜,適当,残り"                    按 Word（退回 Transliteration）比词形
  --from-file data\\core6000\\my_words.txt     一行一个词或 noteId（# 注释）
  --from-weak --days 3 --rating again        今天/近几天的弱项词（跑 today_weak.py 取词表）
  --query 'tag:待补例句'                      任意 Anki 查询
  --all                                      显式全库（≈6000 张；或配合 --query 限定）
另外 `--only SCOPE --limit N` 也能跑（限定了规模的全库范围筛选），SCOPE ∈ %s。
只看进度/体检（只读）：  status / scan""" % '、'.join(SCOPES)


def select_cards(args, allow_deckwide=False, require_selector=True):
    """按选择器读 Anki（只读），返回 (cards, sel)。

    cards 按 Index 排序，每张都是 analyze_note 的明细；--limit 不在这里截断
    （截断作用在「待做卡」上，见 pick_work）。
    """
    limit = getattr(args, 'limit', None) or 0
    sel = resolve_targets(args)

    if sel is None:
        if allow_deckwide:
            sel = {'mode': 'deck-wide', 'ids': '', 'words': [], 'query': base_query()}
        elif getattr(args, 'only', None) and limit:
            sel = {'mode': 'deck-wide-scoped', 'ids': '', 'words': [],
                   'query': base_query()}
        elif require_selector:
            raise SystemExit(SELECTOR_HELP)
        else:
            sel = {'mode': 'deck-wide', 'ids': '', 'words': [], 'query': base_query()}

    mode = sel['mode']
    unmatched = []
    notes = []
    if mode == 'note-ids':
        notes = notes_by_ids(sel['ids'])
        sel['query'] = 'noteId ∈ {%s}' % sel['ids']
    elif mode in ('words', 'from-file'):
        if sel.get('ids'):
            notes.extend(notes_by_ids(sel['ids']))
        if sel.get('words'):
            got, unmatched = notes_by_words(sel['words'])
            seen = {int(n['noteId']) for n in notes}
            notes.extend([n for n in got if int(n['noteId']) not in seen])
        sel['query'] = '（按词形 / noteId 匹配）'
    elif mode == 'from-weak':
        notes, unmatched = notes_by_words(sel['words'])
        sel['query'] = '（弱项词表按词形匹配）'
    elif mode == 'query':
        q = query_with_defaults(sel['query'])
        notes, _n = fetch_notes(q)
        sel['query'] = q
    else:                                   # all / deck-wide
        q = query_with_defaults(sel.get('query') or base_query())
        notes, _n = fetch_notes(q)
        sel['query'] = q

    notes.sort(key=lambda n: (TN.as_int((n.get('fields', {}).get('Index') or {}).get('value'),
                                        10 ** 9), int(n['noteId'])))
    cards = [analyze_note(n) for n in notes]
    if mode in ('words', 'from-file', 'from-weak'):
        sel['unmatched_words'] = unmatched
        if unmatched:
            print('⚠️ 这些词在牌组里找不到对应卡（检查写法/是否已删除）：%s%s'
                  % ('、'.join(unmatched[:8]),
                     '（另外 %d 个）' % (len(unmatched) - 8) if len(unmatched) > 8 else ''),
                  file=sys.stderr)
    sel['scopes'] = parse_only(getattr(args, 'only', None))
    sel['limit'] = limit
    return cards, sel


def state_map(cards, scopes, force=False):
    """{noteId: (state, deficits)}，state ∈ work / already_ok / blocked。"""
    return {str(c['id']): card_state(c, scopes, force) for c in cards}


def capabilities(system_prompt_path=None):
    """当前系统提示词能支撑到哪一步。

    `not-merged` 范围（契约 §5.3）要求响应里额外给 `core1`/`grammar1`/`conjugation1`/`context1`
    —— ① 也由模型产出。提示词里没有这四个键（模型只输出 10 个键）时，这个范围做不了，
    与其让模型瞎猜 ① ，不如**提前拦下**并说明原因。
    """
    path = system_prompt_path or PROMPT_FILE
    text = ''
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
        except OSError:
            text = ''
    return {'merge': all(k in text for k in ('core1', 'grammar1', 'conjugation1', 'context1')),
            'prompt': path, 'prompt_exists': bool(text)}


def unsupported_reasons(card, deficits, caps):
    """当前提示词/脚本做不到的缺陷 → 提前拦下，别白花模型调用。"""
    out = []
    if SCOPE_MERGE in deficits and not caps.get('merge'):
        out.append('not-merged 需要响应扩展 core1/grammar1/conjugation1/context1（契约 §5.3），'
                   '当前系统提示词没要求模型输出这几个键 → 缺 ①，做不了')
    return out


def pick_work(cards, sel, force=False, caps=None):
    """算状态 + 用 --limit 截断「待做」清单（--force 时 already_ok 也进待做）。

    返回 (work, already, blocked, states)；states 是**截断前**每张卡的状态。
    blocked 每项是 (card, 原因列表)。
    """
    caps = caps or capabilities()
    states = state_map(cards, sel['scopes'], force)
    work, already, blocked = [], [], []
    for c in cards:
        state, d = states[str(c['id'])]
        hard = unsupported_reasons(c, d, caps) if state == 'work' else []
        if hard:
            blocked.append((c, d + hard))
            states[str(c['id'])] = ('blocked', d + hard)   # 状态表里也算 blocked
        elif state == 'work':
            work.append((c, d))
        elif state == 'already_ok':
            already.append((c, d))
        else:
            blocked.append((c, d))
    limit = sel.get('limit') or 0
    if limit:
        work = work[:limit]
    return work, already, blocked, states


# ============================================================================
# plan / state / report
# ============================================================================
def plan_path(date):
    return os.path.join(DATA_DIR, 'plan_%s.json' % date)


def report_path(date):
    return os.path.join(DATA_DIR, 'report_%s.md' % date)


def metrics_path(date):
    return os.path.join(DATA_DIR, 'metrics_%s.json' % date)


def gen_paths(note_id):
    stem = os.path.join(GEN_DIR, str(note_id))
    return {'in': stem + '_in.json', 'out': stem + '_out.json', 'meta': stem + '_meta.json'}


def parse_only(values):
    if not values:
        return list(DEFAULT_SCOPES)
    out = []
    for v in values:
        for part in str(v).split(','):
            part = part.strip()
            if not part:
                continue
            if part in ('all', 'ALL'):
                return list(SCOPES)
            if part not in SCOPES:
                raise SystemExit('--only 只能是 %s 或 all，收到 %r' % ('、'.join(SCOPES), part))
            if part not in out:
                out.append(part)
    return out or list(DEFAULT_SCOPES)


def build_state(date, cards, states, sel):
    return {
        'version': 1,
        'date': date,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'deck': DECK, 'model_name': NOTE_MODEL,
        'selection': {k: v for k, v in sel.items() if k not in ('ids',)},
        'scopes': list(sel.get('scopes') or []),
        'counts': {
            'selected': len(cards),
            'work': sum(1 for s, _d in states.values() if s == 'work'),
            'already_ok': sum(1 for s, _d in states.values() if s == 'already_ok'),
            'blocked': sum(1 for s, _d in states.values() if s == 'blocked'),
        },
        'cards': [{
            'id': c['id'], 'index': c['index'], 'word': c['word'], 'reading': c['reading'],
            'n_sent': c['n_sent'], 'layout': c['layout'], 'scopes': c['scopes'],
            'state': states[str(c['id'])][0], 'deficits': states[str(c['id'])][1],
            'sections': [s['canon'] or ('?' + (s['label'] or '')) for s in c['sections']],
        } for c in cards],
        'snapshot': {str(c['id']): c['snapshot'] for c in cards},
    }


def build_plan(date, sel, work, args, cfg):
    """plan_<日期>.json：本次要做的清单 + 渲染所需的每张卡明细（work 是 (card, 缺陷) 列表）。"""
    cards = [c for c, _d in work]
    return {
        'version': 1,
        'date': date,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'deck': DECK,
        'selection': {k: v for k, v in sel.items() if k not in ('ids',)},
        'scopes': list(sel.get('scopes') or []),
        'per_batch': getattr(args, 'per_batch', 1) or 1,
        'system_prompt': os.path.abspath(getattr(args, 'system_prompt', None) or PROMPT_FILE),
        'model': (cfg or {}).get('model', ''),
        'base_url': (cfg or {}).get('base_url', ''),
        'total': len(cards),
        'ids': [c['id'] for c in cards],
        'cards': {str(c['id']): c for c in cards},
    }


def llm_config_or_empty(args):
    try:
        return TN.load_llm_config(args)
    except Exception:                     # 读不出配置文件不算错
        return {'model': TN.LLM_DEFAULT_MODEL, 'base_url': TN.LLM_DEFAULT_BASE, 'api_key': ''}


def sel_line(sel):
    bits = ['选择器 %s' % sel.get('mode')]
    if sel.get('words'):
        bits.append('词：%s' % '、'.join(sel['words'][:8])
                    + ('…' if len(sel['words']) > 8 else ''))
    if sel.get('ids'):
        bits.append('noteId：%s' % sel['ids'])
    if sel.get('query') and sel.get('mode') not in ('words', 'from-file', 'from-weak'):
        bits.append('查询：%s' % sel['query'])
    if sel.get('path'):
        bits.append('文件：%s' % sel['path'])
    if sel.get('days'):
        bits.append('近 %s 天' % sel['days'])
    return '｜'.join(bits)


def print_pick(cards, work, already, blocked, sel):
    print(sel_line(sel))
    print('选中 %d 张：待做 %d 张 ｜ already_ok（已合规，跳过）%d 张 ｜ 修不了 %d 张'
          % (len(cards), len(work), len(already), len(blocked)))
    by_scope = {s: sum(1 for c in cards if s in c['scopes']) for s in SCOPES}
    print('  范围：%s ｜ %s ｜ %s' % ('、'.join('%s %d' % (s, by_scope[s]) for s in SCOPES),
                                    '版式 ' + '/'.join(sorted({c['layout'] for c in cards}))
                                    if cards else '版式 -',
                                    '句数 ' + '/'.join('%d:%d' % (k, v) for k, v in
                                                      sorted(_counter(c['n_sent']
                                                                      for c in cards).items()))
                                    if cards else ''))
    if already:
        print('  already_ok：%s' % '、'.join('%s(%d)' % (c['word'], c['id'])
                                            for c, _d in already[:8]))
    if blocked:
        for c, d in blocked[:8]:
            print('  ⚠️ 修不了 %s(%d)：%s' % (c['word'], c['id'], '、'.join(d)), file=sys.stderr)


def _counter(seq):
    out = {}
    for x in seq:
        out[x] = out.get(x, 0) + 1
    return out


def cmd_scan(args):
    """只读体检：给选择器就只看选中的卡；不给就是全库健康报告。"""
    date = dt.date.today().isoformat()
    cfg = llm_config_or_empty(args)
    if not (getattr(args, 'query', None) or getattr(args, 'all', False)
            or getattr(args, 'note_ids', None) or getattr(args, 'words', None)
            or getattr(args, 'from_file', None) or getattr(args, 'from_weak', False)):
        print('提示：没给选择器 → 这次是**全库体检**（≈6000 张，只读）。'
              '只查几个词请用 --words / --note-ids。', file=sys.stderr)
    cards, sel = select_cards(args, allow_deckwide=True, require_selector=False)
    force = bool(getattr(args, 'force', False))
    work, already, blocked, states = pick_work(cards, sel, force, capabilities(getattr(args, 'system_prompt', None)))
    os.makedirs(GEN_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    write_json(STATE_FILE, build_state(date, cards, states, sel))
    write_json(plan_path(date), build_plan(date, sel, work, args, cfg))
    print('扫描 %s' % DECK)
    print_pick(cards, work, already, blocked, sel)
    write_report(date, cards, work, already, blocked, sel, extra=scan_report_extra(work))
    print()
    print('已落盘：')
    print('  状态   %s' % STATE_FILE)
    print('  清单   %s（待做 %d 张）' % (plan_path(date), len(work)))
    print('  报告   %s' % report_path(date))
    if not work:
        print()
        print('这次没有待做的卡。' if cards else '选择器没选中任何卡。', file=sys.stderr)
        return 1
    print()
    print('下一步：')
    print('  gen   %s' % _next_hint(args))
    return 0


def _next_hint(args):
    if getattr(args, 'words', None):
        return '--words "%s"' % args.words
    if getattr(args, 'note_ids', None):
        return '--note-ids %s' % args.note_ids
    if getattr(args, 'from_file', None):
        return '--from-file "%s"' % args.from_file
    if getattr(args, 'from_weak', False):
        return '--from-weak --days %s%s' % (getattr(args, 'days', 1),
                                            (' --rating %s' % args.rating)
                                            if getattr(args, 'rating', None) else '')
    if getattr(args, 'query', None):
        return "--query '%s'" % args.query
    bits = []
    if getattr(args, 'only', None):
        bits.append('--only %s' % ','.join(args.only))
    if getattr(args, 'limit', None):
        bits.append('--limit %d' % args.limit)
    return ' '.join(bits) or '--all'


def hint_from_sel(sel):
    """按 plan 里记下的选择器回一个可直接复制的参数串（status 提示下一步用）。"""
    sel = sel or {}
    mode = sel.get('mode')
    if mode == 'words':
        return '--words "%s"' % ','.join(sel.get('words') or [])
    if mode == 'note-ids':
        return '--note-ids %s' % sel.get('ids', '')
    if mode == 'from-file':
        return '--from-file "%s"' % sel.get('path', '')
    if mode == 'from-weak':
        return '--from-weak --days %s%s' % (sel.get('days') or 1,
                                            (' --rating %s' % sel['rating'])
                                            if sel.get('rating') else '')
    if mode == 'query':
        return "--query '%s'" % sel.get('query', '')
    return '--all'


def scan_report_extra(work):
    lines = ['## 待做清单（最多列 60 张）', '',
             '| noteId | Index | 词 | 读音 | 句数 | 版式 | 缺什么 |', '|---|---|---|---|---|---|---|']
    for card, deficits in work[:60]:
        lines.append('| %d | %s | %s | %s | %s | %s | %s |'
                     % (card['id'], card['index'], card['word'], card['reading'],
                        card['n_sent'], card['layout'], '、'.join(deficits)))
    if len(work) > 60:
        lines.append('')
        lines.append('（另外 %d 张见 plan 文件）' % (len(work) - 60))
    lines.append('')
    return lines


def write_report(date, cards, work, already, blocked, sel, extra=()):
    by_scope = {s: sum(1 for c in cards if s in c['scopes']) for s in SCOPES}
    lines = ['# Core6000 按需补例句② · 报告 %s' % date, '',
             '生成于 %s｜牌组 `%s`｜模型 `%s`'
             % (dt.datetime.now().isoformat(timespec='seconds'), DECK, NOTE_MODEL), '',
             '## 本次选择', '',
             '`%s`' % sel_line(sel), '',
             '| 指标 | 数量 |', '|---|---|',
             '| 选中卡 | %d |' % len(cards),
             '| 待做（work） | %d |' % len(work),
             '| already_ok（已合规，跳过） | %d |' % len(already),
             '| 脚本修不了 | %d |' % len(blocked),
             '| `%s` | %d |' % (SCOPE_SENT, by_scope[SCOPE_SENT]),
             '| `%s` | %d |' % (SCOPE_RUBY, by_scope[SCOPE_RUBY]),
             '| `%s` | %d |' % (SCOPE_MERGE, by_scope[SCOPE_MERGE]),
             '',
             '`--only` 生效范围：%s（默认不含 `not-merged`，契约 §5.3）'
             % '、'.join(sel.get('scopes') or []), '']
    if sel.get('unmatched_words'):
        lines.extend(['⚠️ 没匹配到卡的词：%s' % '、'.join(sel['unmatched_words']), ''])
    if blocked:
        lines.extend(['## 脚本修不了（人工处理）', '',
                      '| noteId | 词 | 原因 |', '|---|---|---|'])
        for card, deficits in blocked[:40]:
            lines.append('| %d | %s | %s |' % (card['id'], card['word'], '、'.join(deficits)))
        lines.append('')
    lines.extend(extra or [])
    lines.extend(progress_lines())
    write_text(report_path(date), '\n'.join(lines))


def progress_lines():
    """报告里的一段「当前进度」：产出 / 音频 / 备份。"""
    outs = glob.glob(os.path.join(GEN_DIR, '*_out.json'))
    ok = failed = 0
    for path in outs:
        obj = read_json(path, {}) or {}
        if (obj.get('gate') or {}).get('ok'):
            ok += 1
        else:
            failed += 1
    mp3 = glob.glob(os.path.join(AUDIO_DIR, '*.mp3'))
    size = sum(os.path.getsize(p) for p in mp3 if os.path.exists(p))
    backups = sorted(glob.glob(os.path.join(DATA_DIR, 'backup_*.json')))
    return ['', '## 当前进度', '',
            '| 项 | 值 |', '|---|---|',
            '| gen 产出（合格 / 不合格） | %d / %d |' % (ok, failed),
            '| TTS 文件 | %d 个（%d 字节，约 %.0f 秒） |'
            % (len(mp3), size, size * 8.0 / AUDIO_BPS if AUDIO_BPS else 0),
            '| 备份 | %s |' % (backups[-1] if backups else '（还没有 apply --commit）'),
            '',
            '> 音频长度不做机械校验（离线判不了对错）。2026-10-06 用户决定：',
            '> **不再要求听音频确认** —— 演练输出没问题就直接 --commit；',
            '> 事后发现读错用 revert --commit 回退即可。', '']


# ============================================================================
# 模型请求/响应（契约 §4）
# ============================================================================
def build_payload(card):
    """契约 §4.1 的 user JSON（逐卡）。两句话的卡额外带两个自我说明的键。"""
    note = {}
    for sec in card['sections']:
        key = sec['canon'] if sec['canon'] else (sec['label'] or '其它')
        body = RE_WS.sub(' ', RE_BR1.sub('\n', sec['body'])).strip()
        if body and key not in note:
            note[key] = body
    payload = {
        'id': card['id'],
        'word': card['word'],
        'reading': card['reading'],
        'pos': card['pos'],
        'meaning': card['meaning'],
        'existing_sentences': [{
            'jp': s['jp'],
            'cn': s['cn'],
            'ruby': ('' if (i == 0 and card['need_ruby1']) or
                     (i == 1 and card['need_ruby2']) else s['ruby']),
        } for i, s in enumerate(card['sentences'])],
        'need_sentence1_ruby': bool(card['need_ruby1']),
        'existing_note': note,
    }
    if card['n_sent'] >= 2:
        # 已有两条例句 → ② 讲的是**卡上第二句**，不要另造第三句（否则 Sentence 会变 3 块）。
        payload['sentence2_is_existing'] = True
        payload['need_sentence2_ruby'] = bool(card['need_ruby2'])
    return payload


ENTRY_STR = ('new_sentence', 'new_sentence_ruby', 'sentence1_ruby', 'sentence2_ruby', 'cn1', 'cn2',
             'grammar2', 'conjugation2', 'context2', 'contrast',
             'core1', 'grammar1', 'conjugation1', 'context1')


def norm_gloss(item):
    """把一条 new_word_gloss 整形成 {'w','r','pos','mean'}。"""
    if isinstance(item, dict):
        g = {k: str(item.get(k) or '').strip() for k in ('w', 'r', 'pos', 'mean')}
        if not g['w']:
            for alt in ('word', 'base', 'jp'):
                if item.get(alt):
                    g['w'] = str(item[alt]).strip()
                    break
        if not g['mean']:
            for alt in ('meaning', 'gloss', 'cn', 'def'):
                if item.get(alt):
                    g['mean'] = str(item[alt]).strip()
                    break
        return g if g['w'] else None
    if isinstance(item, str) and item.strip():
        text = item.strip()
        first, sep, rest = (text.partition('：') if '：' in text else text.partition(':'))
        if sep and rest:
            w, r = first.strip(), ''
            m = re.match(r'^(.*?)[（(]([^）)]*)[）)]\s*$', w)
            if m:
                w, r = m.group(1).strip(), m.group(2).strip()
            return {'w': w, 'r': r, 'pos': '', 'mean': rest.strip()}
        return {'w': text, 'r': '', 'pos': '', 'mean': ''}
    return None


def norm_entry(raw):
    """整形成契约 §4.2 的响应条目（只做形状转换，不改内容）。"""
    out = {}
    for k in ENTRY_STR:
        v = raw.get(k) if isinstance(raw, dict) else None
        if isinstance(v, (list, tuple)):
            v = '；'.join(str(x) for x in v if str(x).strip())
        v = '' if v is None else str(v).strip()
        # 模型有时会自己带上「① / ②」前缀，渲染时我们还要再加一次 → 先去重。
        # **contrast 例外**：它本身就是「①是…，②是…」的两句对比，那个 ① 是内容，
        # 剥掉就变成「是礼貌体…」（2026-10-26 实测真事）。
        if k != 'contrast':
            v = re.sub(r'^\s*[①②]\s*', '', v).strip()
        out[k] = v
    glosses = []
    items = raw.get('new_word_gloss') if isinstance(raw, dict) else None
    if isinstance(items, dict):
        items = [items]
    for it in (items or []):
        g = norm_gloss(it)
        if g and g['w']:
            glosses.append(g)
    out['new_word_gloss'] = glosses[:4]        # 契约：最多 4 个
    return out


def parse_response(raw, note_id):
    """从模型回复里取出这张卡的条目，返回 (entry, 问题描述)。"""
    obj, why = TN.extract_json(raw)
    if obj is None:
        return None, why
    if not isinstance(obj, dict):
        return None, '顶层不是 JSON 对象'
    entries = obj.get('entries')
    if not isinstance(entries, dict):
        return None, '缺少 entries 对象'
    item = entries.get(str(note_id))
    if item is None:
        item = entries.get(note_id)
    if not isinstance(item, dict):
        return None, 'entries 里没有这张卡（id=%s）；实际有：%s' % (
            note_id, '、'.join(list(entries)[:6]) or '（空）')
    return norm_entry(item), ''


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
        forms |= kana_conjugations(word)
    forms.discard('')
    return forms


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
    return os.path.join(JISHO_DIR, '%s.json' % note_id)


def jisho_fetch(card, args):
    """抓 Jisho 例句候选（含振假名渲染），按 noteId 缓存。

    返回 ``(candidates, reason)``：``reason`` 非空表示没抓到（网络/依赖/零候选）。
    Jisho 的 robots.txt 要求 crawl-delay 40s，所以**一张卡只抓一页并落盘**，
    重跑 gen / 重试闸门都读缓存。
    """
    path = jisho_cache_path(card['id'])
    if not getattr(args, 'refresh_jisho', False):
        cached = read_json(path)
        if isinstance(cached, dict) and cached.get('candidates') is not None \
                and cached.get('word') == card['word']:
            return cached['candidates'], ''
    JX, why = load_jisho()
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
    return out, ''


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


def pick_jisho(card, args):
    """给这张卡挑一条**真实**例句：``{jp, ruby, en, source, url, match}`` 或 ``None``。

    只认：振假名结构合格 + 真含目标词 + 长度进闸门区间 + 与第一句相似度 < 阈值。
    候选本身已由 jisho_example 按 exact>compound>phrase、句长、语料来源排过序；
    这里先挑「**目标词写法一字不差**出现」的（`思い込む` 卡优先要 `思い込んで`，
    而不是只写成假名的 `思いこんで`），一条都没有才退而接受活用形/假名写法。
    """
    cands, why = jisho_fetch(card, args)
    if not cands:
        return None, why
    first = card['sentences'][0]['jp'] if card['sentences'] else ''
    forms = target_forms(card)
    key = word_written_form(card['word'] or '')
    for strict in ((True, False) if key else (False,)):
        skipped = []
        for c in cands:
            jp = c['jp']
            n_chars = len(RE_WS.sub('', jp))
            if not c.get('ruby_ok'):
                skipped.append('ruby')
                continue
            if strict:
                if key not in jp:
                    skipped.append('kana-form')
                    continue
            elif not any(f in jp for f in forms):
                skipped.append('no-target')
                continue
            if not (SENT_MIN <= n_chars <= SENT_MAX):
                skipped.append('length')
                continue
            if first and jisho_similarity(jp, first) >= JISHO_MIN_SIMILARITY:
                skipped.append('too-similar')
                continue
            return {'jp': jp, 'ruby': c['ruby'], 'en': c.get('en') or '',
                    'source': c.get('source') or '', 'url': c.get('url') or '',
                    'match': c.get('match') or ''}, ''
    seen = {}
    for s in skipped:
        seen[s] = seen.get(s, 0) + 1
    return None, 'Jisho 的 %d 条候选都不合适（%s）' % (
        len(cands), ' / '.join('%s %d' % kv for kv in seen.items()))


def check_sentence_ruby(plain_text, ruby_html, label):
    """契约闸门 3/4：ruby 去 ruby 后等于原句；有汉字就必须有合规 ruby。"""
    problems = []
    if flatten(ruby_html) != flatten(plain_text):
        problems.append('%s：去 ruby 后与正文不一致（ruby=%r）'
                        % (label, one_line(ruby_html, 60)))
    if TN.KANJI.search(plain_text or '') and '<ruby' not in (ruby_html or '').lower():
        problems.append('%s：含汉字但没有 <ruby>' % label)
    elif (ruby_html or '').strip() and not ruby_covers(ruby_html):
        problems.append('%s：振假名不合规（有 ruby 缺 <rt> / 基底只含假名 / 有汉字漏注音）' % label)
    return problems


def check_sentence2_ruby(card, entry):
    """闸门 5b：卡上已有两条例句、第二句缺/坏振假名时，`sentence2_ruby` 必须合规。

    口径与 `sentence1_ruby` 对称（闸门 3/4）：**去 ruby 后必须与卡上第二句逐字一致**
    （`check_sentence_ruby` 的第一条就是干这个的），并且每个 `<ruby>` 都有 `<rt>`、
    基底不得只含假名、ruby 之外不得再有汉字。
    这里**只用模型值**，不回退到 `new_sentence_ruby`：模型一旦改写了那句，
    宁可拒绝这张卡（丢用户的原句比跳过更糟）。
    """
    if card['n_sent'] < 2 or not card['need_ruby2']:
        return []                                   # 不适用：没有第二句 / 第二句振假名本来就合规
    if not entry['sentence2_ruby']:
        return ['闸门5b：need_sentence2_ruby=true 但 sentence2_ruby 是空的']
    return check_sentence_ruby(card['sentences'][1]['jp'], entry['sentence2_ruby'], 'sentence2_ruby')


def kana_norm(text):
    """读音比对用的归一化：NFKC + 去空白 + 片假名→平假名。"""
    s = unicodedata.normalize('NFKC', text or '')
    s = RE_WS.sub('', s)
    return ''.join(chr(ord(ch) - 0x60) if '\u30a1' <= ch <= '\u30f6' else ch for ch in s)


def word_reading_in_ruby(word, ruby_html):
    """从 `new_sentence_ruby` 里抽出**目标词**的读音；抽不出（判不了）返回 ''。

    只有能**确定**这个词的读音时才返回内容：要么某个 `<ruby>` 的基底正好是目标词，
    要么目标词被一串 `<ruby>` 基底按顺序完整拼出来（逐字标音那种）。
    拼不齐（例如「受付ける」只标了 `受`+`付`）就返回 '' —— 判不了就不警告，宁可漏报。
    """
    h = clean_malformed_ruby(ruby_html or '')
    if not word or not h:
        return ''
    pairs = []
    for inner in RE_RUBY.findall(h):
        m = re.search(r'<rt\b[^>]*>(.*?)</rt>', inner, re.S | re.I)
        if not m:
            continue
        base = TN.strip_tags(RE_RT.sub('', inner)).strip()
        rt = TN.strip_tags(m.group(1)).strip()
        if base:
            pairs.append((base, rt))
    for base, rt in pairs:                 # 一词一 ruby
        if base == word:
            return rt
    joined, rts = '', []                   # 逐字标音：基底按顺序拼成目标词
    for base, rt in pairs:
        if base and word.startswith(joined + base):
            joined += base
            rts.append(rt)
            if joined == word:
                return ''.join(rts)
    return ''


def target_word_warnings(card, entry):
    """目标词读音 / 义项行的**便宜检查**（警告，不是闸门：误报绝不拦卡）。

    1. 新句里出现了目标词，而它在 `new_sentence_ruby` 里被注的读音与卡上 `reading`
       对不上 → 同一张卡里出现了第二种读音。
    2. `new_word_gloss` 里没有目标词那一行 → ② 的义项行只能用卡上的 `Meaning` 兜底，
       看不出新句实际用的是哪个义项（提示词要求模型把实际用的义项写进那一行）。
    """
    out = []
    word, reading = card['word'], card['reading']
    if word and reading and flatten(word) and flatten(word) in flatten(entry['new_sentence']):
        got = word_reading_in_ruby(word, entry['new_sentence_ruby'])
        if got and kana_norm(got) != kana_norm(reading):
            out.append('target_reading_mismatch：新句里「%s」注的是「%s」，卡上 reading 是「%s」'
                       % (word, got, reading))
    if word and not any(g['w'] == word for g in entry['new_word_gloss']):
        out.append('target_gloss_missing：new_word_gloss 里没有目标词「%s」那一行，'
                   '② 的义项行只能用卡上 Meaning 兜底' % word)
    contrast = entry.get('contrast') or ''
    if contrast and not ('①' in contrast and '②' in contrast):
        out.append('contrast_format：contrast 要求写成「①是…，②是…」，'
                   '现在是「%s」' % one_line(contrast, 40))
    return out


def gate_gen(card, entry, scopes=None):
    """闸门 1-5（契约 §6）。返回 (问题列表, 警告列表)。

    注意闸门 1/2 只对**模型造的新句**有意义：原卡已有两条例句时，`new_sentence` 只是
    把卡上第二句原样重复（用来对齐振假名与 ② 讲解），那一句是卡里的既有数据
    （可能本来就不含目标词，如「する」的第二句「…サッカーをしている」），
    拿闸门 1 去卡它属于误伤。

    `scopes` = 本次 `--only` 选定的范围。`core1/grammar1/conjugation1/context1` 这四个键
    是**契约 §5.3 的 not-merged 扩展**（那个范围里 ① 也要模型产出，且默认不参与）：
    只有真的在跑 not-merged 时才是硬要求。默认范围里处理一张 `unmerged` 的卡时，
    渲染的 ① 用的是**卡里原有的板块正文**（`section_body_html` 的 `orig`），这四个键
    根本不参与渲染 —— 所以这里按范围判，而不是按卡判（`scopes=None` = 不知道范围，从严）。
    """
    p, warn = [], []
    jp = plain(entry['new_sentence'])
    ruby = entry['new_sentence_ruby']
    n_chars = RE_WS.sub('', jp)
    if card['n_sent'] == 1:
        # 1 目标词必须出现
        if not any(f in jp for f in target_forms(card)):
            p.append('闸门1：新句里没有目标词「%s」' % card['word'])
        # 2 长度 + 与原句不同
        if not (SENT_MIN <= len(n_chars) <= SENT_MAX):
            p.append('闸门2：新句长度 %d 字（要求 %d–%d）' % (len(n_chars), SENT_MIN, SENT_MAX))
        if card['sentences'] and flatten(jp) == flatten(card['sentences'][0]['jp']):
            p.append('闸门2：新句与第一句完全相同')
    else:
        # 已有两条例句：new_sentence 必须原样用卡上第二句（缺它的振假名时是硬要求）
        want = card['sentences'][1]['jp']
        if flatten(jp) != flatten(want):
            if card['need_ruby2']:
                p.append('闸门2：原卡已有两条例句且第二句没有可用振假名，new_sentence 必须原样用'
                         '第二句「%s」，实际是「%s」' % (one_line(want, 40), one_line(jp, 40)))
            else:
                warn.append('sentence2_mismatch：② 讲的和卡上第二句不是同一句'
                            '（卡上第二句「%s」）' % one_line(want, 40))
    # 3/4 ruby 一致性
    if not ruby:
        p.append('闸门3：new_sentence_ruby 是空的')
    else:
        p.extend(check_sentence_ruby(jp, ruby, 'new_sentence_ruby'))
    # 5 句①振假名（需要时）
    if card['need_ruby1'] and card['sentences']:
        s1 = card['sentences'][0]['jp']
        if not entry['sentence1_ruby']:
            p.append('闸门5：need_sentence1_ruby=true 但 sentence1_ruby 是空的')
        else:
            p.extend(check_sentence_ruby(s1, entry['sentence1_ruby'], 'sentence1_ruby'))
    # 5b 句②振假名（已有两条例句、且第二句缺/坏振假名时）
    if card['n_sent'] >= 2 and card['need_ruby2']:
        p.extend(check_sentence2_ruby(card, entry))
    # ② 讲解必须齐（否则渲染出来的 ② 是空的）
    for key, name in (('cn2', '新句中文 cn2'), ('grammar2', '语法要点 grammar2'),
                      ('conjugation2', '动词变形解析 conjugation2'),
                      ('context2', '语境与表达风格 context2'), ('contrast', '两句对比 contrast')):
        if not entry[key]:
            p.append('%s 是空的' % name)
    if card['unmerged'] and (scopes is None or SCOPE_MERGE in scopes):
        for key in ('core1', 'grammar1', 'conjugation1', 'context1'):
            if not entry[key]:
                p.append('not-merged 范围缺 %s' % key)
    if not card['sentences'][0]['cn'] and not entry['cn1']:
        p.append('cn1 是空的（原卡没有中文翻译时必须给）')
    # 便宜检查（警告，不拦卡）：目标词读音是否和 reading 一致 / ② 有没有给义项行
    warn.extend(target_word_warnings(card, entry))
    return p, warn


# ============================================================================
# 渲染（契约 §5）
# ============================================================================
def wrap_p(block):
    return '<p>%s</p>' % block


def render_sentences(card, entry):
    """`Sentence`：1 句的卡 = 原句 + 新句；已有 2 句的卡 = 原来那两句（绝不追加第三句）。"""
    if card['n_sent'] >= 2:
        return join_blocks(card.get('snapshot', {}).get(F_SENT, '')) or \
            '<br><br>'.join(s['jp'] for s in card['sentences'])
    first = card['sent_blocks'][0] if card['sent_blocks'] else card['sentences'][0]['jp']
    return '%s<br><br>%s' % (first, plain(entry['new_sentence']))


def render_sentence_html(card, entry):
    """`Sentence HTML`：内容永远是「原句 ruby <br> 新句 ruby」，不加任何外壳标签。

    2026-10-30 起不再沿用原卡的 `<div>` / `<p>` 外壳——Sentence HTML 只含例句本身，
    多句用单个 `<br>` 分隔（不用 `<br><br>`、不用 `<p>` 包裹）。
    """
    ruby1 = card['sentences'][0]['ruby'] or entry['sentence1_ruby'] or ''
    if card['n_sent'] >= 2:
        if card['need_ruby2']:
            # 第二句原本缺/坏振假名 → 只用模型交回的 `sentence2_ruby`
            # （闸门 5b 已验「去 ruby 后与卡上第二句逐字一致 + 振假名合规」；
            #  这里绝不回退到 new_sentence_ruby，也不保留原卡那段坏振假名）
            ruby2 = entry['sentence2_ruby'] or ''
        else:
            ruby2 = card['sentences'][1]['ruby'] or entry['new_sentence_ruby'] or ''
    else:
        ruby2 = entry['new_sentence_ruby'] or ''
    return '%s<br>%s' % (ruby1, ruby2)


def render_translation(card, entry):
    if card['n_sent'] >= 2:
        return join_blocks(card.get('snapshot', {}).get(F_TRANS, '')) or \
            '<br><br>'.join(s['cn'] for s in card['sentences'] if s['cn'])
    orig = join_blocks(card.get('snapshot', {}).get(F_TRANS, ''))
    if not orig:
        orig = entry['cn1']
    return ('%s<br><br>%s' % (orig, entry['cn2'])) if orig else entry['cn2']


def tts_filename(note_id):
    return 'core6000-%d-sentence-2.mp3' % note_id


def render_audio(card):
    """`Sentence Audio`：1 句的卡 = 原来那条 + 新句 TTS（去重，绝不重复追加）。

    已有 2 句的卡 = 原样返回（音频早就齐了）。
    """
    orig = card.get('snapshot', {}).get(F_AUDIO, '')
    if card['n_sent'] >= 2:
        return orig
    names = dedupe(list(card['audio_files']) + [tts_filename(card['id'])])
    return ''.join('[sound:%s]' % f for f in names)


POS_CN = {                       # 卡上 `Part of Speech` 是英文：② 的（词性）按 ① 的中文口径写
    'noun': '名词', 'verb': '动词', 'adjective': 'い形容词',
    'adjectival noun': 'な形容词', 'adverb': '副词', 'verbal noun': '名词/サ変動詞',
    'interrogative': '疑问词', 'pronoun': '代词', 'conjunction': '接续词',
    'particle': '助词', 'counter': '量词', 'numeral': '数词',
    'expression': '惯用语', 'prefix': '接头辞', 'suffix': '接尾辞',
}


def pos_cn(pos):
    """词性英文 → 中文（认不出就原样返回，不丢信息）。"""
    p = (pos or '').strip()
    return POS_CN.get(p.lower(), p)


def ruby_word(w, r):
    """`<ruby>漢字<rt>かな</rt></ruby>`；没有读音或词里没汉字就原样返回。

    口径与 ① 一致：只给汉字注音（假名词不注音 —— 闸门 4 也禁止基底只含假名）。
    """
    w = (w or '').strip()
    if w and (r or '').strip() and TN.KANJI.search(w):
        return '<ruby>%s<rt>%s</rt></ruby>' % (w, r.strip())
    return w


def gloss_lines(word, reading, meaning, glosses, pos=''):
    """② 的词表：目标词一行 + 新句里其它值得讲的词（最多 4 个）。

    行文与 ① 的「核心词汇」对齐：`<ruby>漢字<rt>かな</rt></ruby>（词性）：释义`，
    这样 ①② 看起来是同一套版式（契约 §5.2）。① 用的是**卡里原有的正文**
    （`section_body_html` 的 `orig`），不经过这里 —— 改这里一个字都不会动 ①。

    目标词那一行优先用模型在 `new_word_gloss` 里给的那条（`mean` 要写明新句**实际用的义项**，
    「此处是「…」的意思」就写在这里）；模型没给就回退到卡上的 `Meaning`。
    """
    lines, used, target_line = [], set(), None
    for g in glosses:
        if g['w'] == word or (reading and g['w'] == reading):
            target_line = g
            used.add(g['w'])
    if target_line:
        head_word = target_line['w']
        head_r = target_line['r'] or reading
        head_pos = target_line['pos'] or pos          # 模型没给词性就用卡上的 Part of Speech
        head_mean = target_line['mean'] or meaning
    else:
        head_word, head_r, head_pos, head_mean = word, reading, pos, meaning
    head = ruby_word(head_word, head_r)
    if head:
        head += '（%s）：%s' % (pos_cn(head_pos) or '—', head_mean or '—')
    lines.append(head)
    for g in glosses:
        if g['w'] in used:
            continue
        lines.append('%s（%s）：%s' % (ruby_word(g['w'], g['r']),
                                     pos_cn(g['pos']) or '—', g['mean'] or '—'))
    return lines


def both(one, two):
    one, two = (one or '').strip(), (two or '').strip()
    if one and two:
        return '① %s<br>② %s' % (one, two)
    if one:
        return '① %s' % one
    if two:
        return '② %s' % two
    return ''


def split_merged_body(body):
    """把**已经合并过**的板块正文拆回 ① 部分（丢掉旧的 ②）。

    这一步是为了让 `--force` 重跑是**不动点**：卡里已经是 `① 原文<br>② 旧新句讲解` 时，
    再渲染一次不能变成 `① ① 原文…② …`。我们自己渲染的形态是确定的，所以能安全地认出来。
    返回 (① 部分, ② 部分或 None)；正文不是以 ① 开头就原样返回。
    """
    m = re.match(r'^\s*①\s*(.*?)(?:<br>\s*②\s*(.*))?$', body or '', re.S)
    if not m:
        return body or '', None
    return m.group(1).strip(), (m.group(2) or '').strip()


def section_body_html(canon, card, entry, known):
    """算出某个规范板块的正文（① + ②）。known = 原卡里认出来的板块。

    `orig` 取「原卡正文的 ① 部分」：卡已经被本脚本写过一次时，正文里已经带着
    ①/②，这里要把旧 ② 丢掉再重新拼，否则 `--force` 会把 ①② 套两层。
    """
    sec = known.get(canon)
    orig = split_merged_body(sec['body'])[0] if sec else ''
    if canon == '中文翻译':
        return both(orig or entry['cn1'], entry['cn2'])
    if canon == '核心词汇':
        word, reading, meaning = card['word'], card['reading'], card['meaning']
        two = '<br>'.join(gloss_lines(word, reading, meaning, entry['new_word_gloss'],
                                      card['pos']))
        return both(orig or entry['core1'], two)
    if canon == '语法要点':
        return both(orig or entry['grammar1'], entry['grammar2'])
    if canon == '动词变形解析':
        return both(orig or entry['conjugation1'], entry['conjugation2'])
    if canon == '语境与表达风格':
        two = entry['context2']
        if entry['contrast']:
            two = (two + '<br>' if two else '') + '两句对比：' + entry['contrast']
        return both(orig or entry['context1'], two)
    return both(orig, '')


def render_section_item(layout, label_html, body):
    if layout == 'h3':
        return '<h3>%s</h3><p>%s</p>' % (label_html, body)
    if layout == 'ul':
        lines = [x.strip() for x in RE_BR1.split(body) if x.strip()]
        return '<p><b>%s</b></p><ul>%s</ul>' % (
            label_html, ''.join('<li>%s</li>' % x for x in lines))
    return '<p><b>%s</b><br>%s</p>' % (label_html, body)


def render_ainote(card, entry):
    """`AINote`：沿用原卡版式，每个板块 ①（原文）+ ②（新句）。"""
    known, _unknown = section_map(card['sections'])
    items, done = [], set()
    for sec in card['sections']:
        if not sec['canon']:
            items.append(sec['raw'])                 # 认不出的板块整块原样保留
            continue
        if sec['canon'] in done:                     # 同名板块重复 → 只渲染第一次
            continue
        done.add(sec['canon'])
        body = section_body_html(sec['canon'], card, entry, known)
        if body:
            items.append(render_section_item(card['layout'], sec['label'] or sec['canon'], body))
    for canon in CANON_ORDER:                        # 原卡缺的板块：只写 ②
        if canon in done:
            continue
        body = section_body_html(canon, card, entry, known)
        if body:
            items.append(render_section_item(card['layout'], canon, body))
    return (card.get('outer_open') or '<div>') + ''.join(items) + '</div>'


def field_defects(card, current=None):
    """这次**真的要写**哪几个字段（契约 §5.4：只写缺陷字段）。

    每个字段都有自己的「目标状态」（契约 §5.1 / §5.2），只有**卡上现值没达到目标**、
    而且**这次确实有新内容可写**的字段才写。不是「渲染结果与现值逐字不同就写」——
    渲染时顺手的空白/包裹归一化不算缺陷，写了就是对用户内容的无谓改写。

    | 字段 | 目标状态 | 1 句的卡 | 已有 2 句的卡 |
    |---|---|---|---|
    | `Sentence` | 两条例句（`<br><br>`） | 写（补第 2 块） | **不写**（第 2 块是卡上既有的） |
    | `Sentence HTML` | 每句的汉字都有合规振假名 | 写（新句的振假名） | 有句子缺/坏振假名才写 |
    | `Sentence Translation` | 两条例句的中文 | 写（补新句译文） | **不写**（同上） |
    | `AINote` | 每板块 `① 原句` + `② 新句` | 写（补 ②） | **不写**（①② 合并是 `not-merged` 范围，未实现，见 §5.3） |
    | `Sentence Audio` | 两条 `[sound:]` | 写（加新句 TTS） | **不写**（脚本造不出那条音频；缺音频的卡由 `audio-count` 拦下） |

    **已有 2 条例句的卡，那 4 个字段的目标状态就是「卡上现值」**：第二句不是这次新造的，
    是卡里既有的数据，`Sentence` / `Sentence Translation` / `AINote` / `Sentence Audio`
    对它没有新东西可写。所以这类卡**只补振假名**，其余 4 个字段一个字都不动 ——
    它们里面的 ①② 讲解、`<ul><li>` 排版都是原作者的版式，脚本不该重排；
    这也和「已有 2 句的卡重跑必须是 no-op」是同一件事（契约 §3.1）。
    那 4 个字段**另有**的缺陷（`audio-count` / `translation-empty` / `not-merged`）
    由 §6 的 `blocked` 路径报给人，不由「重渲染一遍」来假装修好。
    """
    if card['n_sent'] > 2:               # 3 句以上：闸门 6 会拦，渲染会截断 → 一个字段都别写
        return []
    if card['n_sent'] < 2:
        return list(TOUCH_FIELDS)        # 1 句 → 2 句：五个字段都还没到目标状态
    if card['need_ruby1'] or card['need_ruby2']:
        return [F_HTML]
    return []


def render_card(card, entry, current=None):
    """渲染 5 个字段，返回 {'fields': {...}, 'write': [...], 'warnings': [...]}。

    `current` = 从 Anki **现场读**的这 5 个字段现值（`live_values` 的结果）。给了就用它当
    「卡上现值」：既用来判 `write`（`field_defects`），也用来当渲染的原值（别拿扫描时的旧快照
    去覆盖人家刚改过的卡）。不给（探针脚本）就退回扫描快照。
    """
    if current:
        card['snapshot'] = dict(current)
    write = field_defects(card, current)
    fields = {
        F_SENT: render_sentences(card, entry),
        F_HTML: render_sentence_html(card, entry),
        F_NOTE: render_ainote(card, entry),
        F_TRANS: render_translation(card, entry),
        F_AUDIO: render_audio(card),
    }
    live = card.get('snapshot') or {}
    warnings = []
    if card['n_sent'] >= 2:
        if card['unmerged']:
            # AINote 里还没有 ①②、但这次不写它（见 field_defects）：不是「留个 ① 的坑」，
            # 是这张卡压根不走 not-merged（契约 §5.3），只补振假名，讲解保持原样。
            warnings.append('note_unmerged_untouched')
        if count_blocks(live.get(F_TRANS, '')) != 2:
            warnings.append('trans_missing_2nd')       # 旧句的译文缺块：脚本不代笔
        if len(card['audio_files']) != 2:
            warnings.append('audio_count_%d' % len(card['audio_files']))
    if card['n_sent'] >= 2 and flatten(entry['new_sentence']) != \
            flatten(card['sentences'][1]['jp']):
        warnings.append('sentence2_mismatch')
    if F_NOTE in write:                  # 只有真的要写 AINote 时，这些「板块」警告才有意义
        for canon in card['section_missing']:
            warnings.append('note_missing_section:' + canon)
        if card['section_unknown']:
            warnings.append('note_unknown_section:' + '/'.join(card['section_unknown']))
    if card['n_sent'] == 1 and len(card['trans_blocks']) > 1:
        warnings.append('trans_extra_blocks')
    return {'fields': fields, 'write': write, 'warnings': warnings}


# ============================================================================
# 机械闸门 6-9（apply 阶段：渲染后）
# ============================================================================
def gate_apply(card, entry, rendered, write=None):
    """闸门 6-9（契约 §6）。返回问题列表。

    **只检查这次真的要写的字段**（`write`，= `field_defects` 的结果；None = 老口径全查）。
    闸门保护的是「别写坏」，不写的字段在库里保持原样、也不会被写坏 ——
    拿卡上**旧值**去卡一张本来能修好的卡（例如已有两句、AINote 还是单句版式的卡）
    会把唯一能做的振假名也一起拦掉，那是误伤。
    闸门 5b（第二句振假名）与写不写无关，永远照查。
    """
    f = rendered['fields']
    write = set(TOUCH_FIELDS if write is None else write)
    p = []
    # 闸门 5b 的**写库前复核**：gen 阶段已经查过一遍，这里再查是为了挡「out.json 被手改 /
    # 用的是旧产出」——写进库的第二句振假名必须以卡上真值为准。
    if card['n_sent'] >= 2 and card['need_ruby2']:
        p.extend(check_sentence2_ruby(card, entry))
    if F_SENT in write and count_blocks(f[F_SENT]) != 2:
        p.append('闸门6：Sentence 渲染后 %d 块（要求 2）' % count_blocks(f[F_SENT]))
    if F_HTML in write and count_blocks(f[F_HTML]) != 2:
        p.append('闸门6：Sentence HTML 渲染后 %d 块（要求 2）' % count_blocks(f[F_HTML]))
    if F_AUDIO in write and len(TN.audio_files(f[F_AUDIO])) != 2:
        p.append('闸门6：Sentence Audio 有 %d 个 [sound:]（要求 2）'
                 % len(TN.audio_files(f[F_AUDIO])))
    if F_NOTE in write:
        flat_note = flatten(f[F_NOTE])
        for canon in REQUIRED_CANON:
            if canon not in flat_note:
                p.append('闸门7：AINote 里没有「%s」板块' % canon)
        if '①' not in flat_note or '②' not in flat_note:
            p.append('闸门7：AINote 里没有 ① / ②')
        if not card['unmerged']:
            for sec in card['sections']:
                src = sec['body'] if sec['canon'] else sec['raw']
                key = flatten(src)[:GATE_KEY_LEN]
                if key and key not in flat_note:
                    p.append('闸门8：原文板块「%s」的前 %d 字没有出现在新 AINote 里'
                             % (sec['label'] or sec['canon'] or '?', GATE_KEY_LEN))
    for name in TOUCH_FIELDS:
        if name in write and not (f.get(name) or '').strip():
            p.append('闸门9：字段 %s 渲染后是空的' % name)
    return p


# ============================================================================
# gen：直连本地模型
# ============================================================================
def load_system_prompt(path=None):
    path = path or PROMPT_FILE
    if not os.path.exists(path):
        raise SystemExit('找不到系统提示词文件：%s\n'
                         '（默认 code/execution/core6000_example_prompt.md；'
                         '用 --system-prompt 指别处）' % path)
    with open(path, encoding='utf-8') as fh:
        return fh.read().strip()


def build_messages(system_prompt, payloads, nudge=None):
    if len(payloads) == 1:
        content = json.dumps(payloads[0], ensure_ascii=False, separators=(',', ':'))
    else:
        content = json.dumps({'cards': payloads}, ensure_ascii=False, separators=(',', ':'))
    if nudge:
        content += '\n\n⚠️ 上一次的输出不能用：%s\n请重新完整输出一遍，只输出 JSON。' % nudge
    return [{'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': content}]


def read_out(note_id):
    """读已有的合格产出；没有 / 不合格返回 None（= 需要重生成）。"""
    obj = read_json(gen_paths(note_id)['out'])
    if not isinstance(obj, dict) or not (obj.get('gate') or {}).get('ok'):
        return None
    entry = (obj.get('entries') or {}).get(str(note_id))
    return norm_entry(entry) if isinstance(entry, dict) else None


def pin_sentence_source(entry, pick):
    """把 Jisho 选定的句子与振假名**钉进** entry，返回警告列表。

    模型改写过的句子留不下来：`new_sentence` / `new_sentence_ruby` 一律被 Jisho 值覆盖，
    只记一条 `sentence_overridden` 警告（人看一眼，不拦卡）。
    """
    if not pick:
        return []
    warn = []
    if flatten(entry.get('new_sentence') or '') != flatten(pick['jp']):
        warn.append('sentence_overridden：模型改写了 Jisho 的句子'
                    '（已按 Jisho 原句写回：%s）' % one_line(pick['jp'], 30))
    entry['new_sentence'] = pick['jp']
    entry['new_sentence_ruby'] = pick['ruby']
    return warn


def gen_one(card, system_prompt, cfg, args, scopes=None):
    """跑一张卡：返回 (entry, warnings, problems, rows, raw)。

    新句来自 **Jisho**（真实语料），模型只写 ② 的讲解。拿到回复后
    `new_sentence` / `new_sentence_ruby` 一律**被 Jisho 值覆盖**（模型改了也留不下），
    闸门 1–4 再拿覆盖后的句子判一次 —— 这既验模型的讲解对齐的是这一句，
    也验这条 Jisho 句子本身合格（含目标词 / 长度 / 振假名结构）。
    """
    payload = build_payload(card)
    pick, pick_why = None, ''
    if card['n_sent'] == 1:
        pick, pick_why = pick_jisho(card, args)
        if pick:
            payload[JISHO_SOURCE_FIELD] = {
                'jp': pick['jp'],
                'ruby': pick['ruby'],
                'en': pick['en'],
                'source': pick['source'],
                'url': pick['url'],
                'note': '这一句是从 jisho.org 的真人语料里取来的，只能逐字使用，不许改写。',
            }
            print('  Jisho 新句（%s）：%s' % (pick['source'] or '?', pick['jp']), file=sys.stderr)
        elif not getattr(args, 'allow_model_sentence', False):
            print('  ❌ 没有可用的 Jisho 例句：%s' % (pick_why or '未知原因'), file=sys.stderr)
            print('     不退回模型造句（要退回请显式加 --allow-model-sentence）。',
                  file=sys.stderr)
            write_json(gen_paths(card['id'])['out'],
                       {'noteId': card['id'], 'date': dt.date.today().isoformat(),
                        'entries': {}, 'gate': {'ok': False,
                                                'problems': ['jisho 零候选：%s' % pick_why],
                                                'warnings': []}})
            return None, [], ['jisho 没有可用例句：%s' % (pick_why or '')], [], ''
    paths = gen_paths(card['id'])
    write_json(paths['in'], {'noteId': card['id'], 'date': dt.date.today().isoformat(),
                             'word': card['word'], 'scopes': card['scopes'],
                             'need_new': card['need_new'], 'sentence_source': pick,
                             'payload': payload})
    rows, nudge, problems, warn, raw = [], None, [], [], ''
    tries = 1 + max(0, getattr(args, 'retries', 1) or 0)
    for attempt in range(1, tries + 1):
        messages = build_messages(system_prompt, [payload], nudge)
        print('  → [%s] %s' % ('重试%d' % attempt if attempt > 1 else '第1次', card['word']),
              file=sys.stderr)
        raw, usage, meta = TN.llm_chat(cfg, messages,
                                       json_mode=not getattr(args, 'no_json_mode', False),
                                       stream=not getattr(args, 'no_stream', False),
                                       label='    ')
        row = TN.usage_row(usage)
        row.update({'noteId': card['id'], 'word': card['word'], 'attempt': attempt,
                    'elapsed': round(meta.get('elapsed') or 0, 1),
                    'first_token': round(meta.get('first_token') or 0, 2),
                    'finish_reason': meta.get('finish_reason'),
                    'reasoning_chars': meta.get('reasoning_chars') or 0, 'ok': False})
        rows.append(row)
        if meta.get('finish_reason') == 'length':
            problems = ['回复被长度上限截断（JSON 不完整）']
            nudge = '上一次回复被长度上限截断了'
        else:
            entry, why = parse_response(raw, card['id'])
            if entry is None:
                problems = ['回复不是可用的 JSON：%s' % why]
                nudge = why
            else:
                if pick:
                    warn.extend(pin_sentence_source(entry, pick))
                problems, warn2 = gate_gen(card, entry, scopes)
                warn.extend(warn2)
                if not problems:
                    row['ok'] = True
                    return entry, warn, [], rows, raw
                nudge = '；'.join(problems[:4])
        if attempt < tries:
            print('    ⚠️ %s；重问一次' % '；'.join(problems[:3]), file=sys.stderr)
    return None, warn, problems, rows, raw


def cmd_gen(args):
    date = dt.date.today().isoformat()
    if getattr(args, 'per_batch', 1) not in (0, 1):
        raise SystemExit(
            '--per-batch 只能是 1：契约 §4.2 的响应按**单张卡**组织（entries 就一个键），\n'
            '系统提示词也明说「你一次只处理一张卡」，一次塞多张只会让模型漏卡/串卡。\n'
            '要省时间请用选择器缩小范围（--words / --note-ids / --from-weak）。')
    cfg = TN.load_llm_config(args)
    if not cfg['api_key']:
        print('提示：没找到 api key（--api-key / $env:DSH_LOCAL_LLM_API_KEY / %s）。'
              '端点不校验就无所谓。' % TN.LLM_GLOBAL_CONFIG_FILE, file=sys.stderr)
    system_prompt = load_system_prompt(args.system_prompt)
    cards, sel = select_cards(args)
    force = bool(getattr(args, 'force', False))
    work, already, blocked, states = pick_work(cards, sel, force, capabilities(getattr(args, 'system_prompt', None)))
    os.makedirs(GEN_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    write_json(STATE_FILE, build_state(date, cards, states, sel))
    write_json(plan_path(date), build_plan(date, sel, work, args, cfg))
    print('本地模型：%s @ %s' % (cfg['model'], cfg['base_url']))
    print('系统提示词：%s（%d 字）' % (os.path.abspath(args.system_prompt or PROMPT_FILE),
                                     len(system_prompt)))
    print_pick(cards, work, already, blocked, sel)
    if not work:
        print()
        print('没有待做的卡（都 already_ok 或修不了）；没有调模型。')
        write_report(date, cards, work, already, blocked, sel,
                     extra=['## 本次 gen', '', '没有待做的卡；0 次请求。', ''])
        return 0

    rows_all, done, failed = [], [], []
    warns_out = []                       # (noteId, 词, [警告]) —— 只进报告，不拦卡
    t0 = time.time()
    for i, (card, deficits) in enumerate(work, 1):
        paths = gen_paths(card['id'])
        if not args.restart:
            entry = read_out(card['id'])
            if entry:
                print('  ↩︎ [%d/%d] %s 已有合格产出，跳过' % (i, len(work), card['word']))
                done.append(card['id'])
                continue
            prev = read_json(paths['out']) or {}
            if (prev.get('gate') or {}).get('problems'):
                print('  ↻ 上次不合格（%s），本次重试'
                      % '；'.join((prev['gate']['problems'] or ['?'])[:2]))
        print('[%d/%d] %s（%s）' % (i, len(work), card['word'], '、'.join(deficits)))
        try:
            entry, warn, problems, rows, raw = gen_one(card, system_prompt, cfg, args,
                                                        sel['scopes'])
        except TN.LLMError as e:
            print('  ❌ 端点失败：%s' % e, file=sys.stderr)
            failed.append((card['id'], card['word'], str(e)))
            write_json(paths['meta'], {'noteId': card['id'], 'date': date,
                                       'word': card['word'], 'model': cfg['model'],
                                       'error': str(e), 'attempts': []})
            continue
        rows_all.extend(rows)
        write_json(paths['meta'], {
            'noteId': card['id'], 'date': date, 'word': card['word'],
            'scopes': card['scopes'], 'deficits': deficits,
            'model': cfg['model'], 'base_url': cfg['base_url'], 'attempts': rows,
            'elapsed': round(time.time() - t0, 1),
            'gate': {'ok': not problems, 'problems': problems, 'warnings': warn},
        })
        if problems:
            print('  ✗ 闸门没过：%s' % '；'.join(problems[:4]), file=sys.stderr)
            failed.append((card['id'], card['word'], '；'.join(problems[:3])))
            write_json(paths['out'], {'noteId': card['id'], 'date': date,
                                      'model': cfg['model'], 'entries': {},
                                      'raw': (raw or '')[:4000],
                                      'gate': {'ok': False, 'problems': problems,
                                               'warnings': warn}})
            continue
        write_json(paths['out'], {'noteId': card['id'], 'date': date, 'model': cfg['model'],
                                  'entries': {str(card['id']): entry},
                                  'gate': {'ok': True, 'problems': [], 'warnings': warn}})
        if warn:
            warns_out.append((card['id'], card['word'], warn))
        print('  ✓ 闸门 1-5 通过' + ('（警告：%s）' % '、'.join(warn) if warn else ''))
    write_metrics(date, cfg, rows_all, len(work), done, failed, time.time() - t0)
    ok_cards = len(work) - len(done) - len(failed)
    print()
    print('gen 结束：请求 %d 次，合格 %d 张，跳过 %d 张（已有产出），失败 %d 张，%.0fs'
          % (len(rows_all), max(0, ok_cards), len(done), len(failed), time.time() - t0))
    if failed:
        print()
        print('⚠️ 这些卡没拿到合格产出（重跑 gen 只重试它们）：', file=sys.stderr)
        for nid, word, why in failed[:20]:
            print('  %s %s → %s' % (nid, word, why), file=sys.stderr)
    write_report(date, cards, work, already, blocked, sel,
                 extra=gen_report(work, done, failed, warns_out))
    if warns_out:
        print()
        print('⚠️ 警告（不拦卡，人看一眼）：', file=sys.stderr)
        for nid, word, ws in warns_out[:20]:
            print('  %s %s → %s' % (nid, word, '；'.join(ws)), file=sys.stderr)
    return 1 if failed else 0


def gen_report(work, done, failed, warns=()):
    lines = ['## 本次 gen', '',
             '待做 %d 张：已有产出跳过 %d 张，本次请求 %d 张，失败 %d 张'
             % (len(work), len(done), len(work) - len(done), len(failed)), '']
    if warns:
        lines.extend(['### 警告（不拦卡，人看一眼）', '',
                      '| noteId | 词 | 警告 |', '|---|---|---|'] +
                     ['| %d | %s | %s |' % (nid, word, '；'.join(ws))
                      for nid, word, ws in warns[:40]] + [''])
    if failed:
        lines.extend(['| noteId | 词 | 原因 |', '|---|---|---|'] +
                     ['| %d | %s | %s |' % (n, w, y) for n, w, y in failed[:40]] + [''])
    return lines


def write_metrics(date, cfg, rows, requested, done, failed, elapsed):
    """token 账本：**只追加**（换过模型也不清账），每行记下是哪个模型。"""
    path = metrics_path(date)
    metrics = read_json(path) or {}
    metrics.update({'date': date, 'model': cfg['model'], 'base_url': cfg['base_url'],
                    'deck': DECK})
    metrics.setdefault('requests', [])
    metrics.setdefault('runs', [])
    for r in rows:
        r.setdefault('model', cfg['model'])
    metrics['requests'].extend(rows)
    metrics['runs'].append({'at': dt.datetime.now().isoformat(timespec='seconds'),
                            'model': cfg['model'],
                            'requested': requested, 'requests': len(rows),
                            'skipped': len(done), 'failed': len(failed),
                            'elapsed': round(elapsed, 1)})
    allr = metrics['requests']

    def total(rs):
        return {
            'requests': len(rs),
            'prompt_tokens': sum(r.get('prompt_tokens') or 0 for r in rs),
            'cached_tokens': sum(r.get('cached_tokens') or 0 for r in rs),
            'completion_tokens': sum(r.get('completion_tokens') or 0 for r in rs),
            'total_tokens': sum(r.get('total_tokens') or 0 for r in rs),
            'elapsed': round(sum(r.get('elapsed') or 0 for r in rs), 1),
        }

    metrics['totals'] = total(allr)
    by_model = {}
    for r in allr:
        by_model.setdefault(r.get('model') or '?', []).append(r)
    metrics['by_model'] = {k: total(v) for k, v in by_model.items()}
    write_json(path, metrics)
    cur = metrics['by_model'].get(cfg['model'], metrics['totals'])
    if rows:
        print()
        print('token 账本：本次 %d 次请求（%s）｜ 今天累计 %d 次 ＝ %d tokens'
              % (len(rows), cfg['model'], metrics['totals']['requests'],
                 metrics['totals']['total_tokens']))
        print('  %s：%d 次请求，prompt %d（缓存 %d）＋ completion %d ＝ %d'
              % (cfg['model'], cur['requests'], cur['prompt_tokens'], cur['cached_tokens'],
                 cur['completion_tokens'], cur['total_tokens']))
        print('  明细 → %s' % path)


# ============================================================================
# 读回 plan / 产出
# ============================================================================
def load_plan(quiet=False):
    date = dt.date.today().isoformat()
    path = plan_path(date)
    if not os.path.exists(path):
        cands = sorted(glob.glob(os.path.join(DATA_DIR, 'plan_*.json')))
        if not cands:
            raise SystemExit('没有清单文件。先跑一次：\n  scan --words "…"')
        path = cands[-1]
        if not quiet:
            print('提示：没有今天的 %s，改用 %s'
                  % (os.path.basename(plan_path(date)), os.path.basename(path)),
                  file=sys.stderr)
    plan = read_json(path)
    if not isinstance(plan, dict) or 'ids' not in plan:      # 空清单（0 张待做）是合法的
        raise SystemExit('清单文件读不出来：%s\n先跑：scan / gen' % path)
    plan['_path'] = path
    return plan


def entry_for(card, required=True):
    """取这张卡的模型产出（合格才返回）。"""
    obj = read_json(gen_paths(card['id'])['out']) or {}
    entry = (obj.get('entries') or {}).get(str(card['id']))
    if not isinstance(entry, dict) or not (obj.get('gate') or {}).get('ok'):
        if required:
            print('  跳过 %s：没有合格产出（先跑 gen）' % card['word'], file=sys.stderr)
        return None
    return norm_entry(entry)


# ============================================================================
# tts
# ============================================================================
def cmd_tts(args):
    date = dt.date.today().isoformat()
    cfg = llm_config_or_empty(args)
    cards, sel = select_cards(args)
    force = bool(getattr(args, 'force', False))
    work, already, blocked, states = pick_work(cards, sel, force, capabilities())
    os.makedirs(DATA_DIR, exist_ok=True)
    write_json(STATE_FILE, build_state(date, cards, states, sel))
    write_json(plan_path(date), build_plan(date, sel, work, args, cfg))
    print_pick(cards, work, already, blocked, sel)
    todo, no_out = [], 0
    for card, deficits in work:
        if card['n_sent'] >= 2:               # 两句话的卡：音频早就齐了
            continue
        entry = entry_for(card, required=False)
        if not entry:
            no_out += 1
            continue
        todo.append((card, entry))
    os.makedirs(AUDIO_DIR, exist_ok=True)
    print()
    print('TTS 目标目录：%s（只写本地磁盘，不碰 Anki）' % AUDIO_DIR)
    if not todo:
        print('没有要合成的卡（两句话的 %d 张，缺模型产出 %d 张）。'
              % (len(work), no_out))
        return 1 if no_out else 0

    made, kept, bad = [], [], []
    for i, (card, entry) in enumerate(todo, 1):
        name = tts_filename(card['id'])
        path = os.path.join(AUDIO_DIR, name)
        text = TN.plain_jp(TN.strip_ruby_readings(entry['new_sentence_ruby'])) or \
            TN.plain_jp(entry['new_sentence'])
        exists = os.path.exists(path) and os.path.getsize(path) >= MIN_MP3_BYTES
        if exists and not force:
            size = os.path.getsize(path)
            kept.append((card, name, size))
            print('  [%d/%d] %-10s 已存在 %s（%d 字节，约 %.1f 秒），跳过'
                  % (i, len(todo), card['word'], name, size, size * 8.0 / AUDIO_BPS))
            continue
        print('  [%d/%d] %-10s ← %s' % (i, len(todo), card['word'], text[:40]))
        try:
            data = TTS.synth(text, voice=VOICE)
        except Exception as e:                  # 网络/协议问题：不让整批挂掉
            print('    ✗ 合成失败：%s' % e, file=sys.stderr)
            bad.append((card['word'], str(e)))
            continue
        if not data:
            print('    ✗ 合成返回空音频', file=sys.stderr)
            bad.append((card['word'], '空音频'))
            continue
        with open(path, 'wb') as fh:
            fh.write(data)
        made.append((card, name, len(data)))
        print('    ✓ %s  %d 字节，约 %.1f 秒' % (name, len(data), len(data) * 8.0 / AUDIO_BPS))
    print()
    print('合成 %d 个 / 跳过 %d 个 / 失败 %d 个；目录 %s'
          % (len(made), len(kept), len(bad), AUDIO_DIR))
    if made:
        print()
        print('★ 音频长度不做机械校验（离线判不了对错）。2026-10-06 起不再要求听音频'
              '确认：演练输出没问题就直接跑 apply --commit，事后发现读错用 revert 回退。')
    for word, why in bad:
        print('  ✗ %s：%s' % (word, why), file=sys.stderr)
    write_report(date, cards, work, already, blocked, sel,
                 extra=['## 本次 tts', '',
                        '新合成 %d 个，跳过 %d 个，失败 %d 个。' % (len(made), len(kept),
                                                                  len(bad)), ''])
    return 1 if bad else 0


# ============================================================================
# apply / revert
# ============================================================================
def live_values(ids):
    """从 Anki 读这 5 个字段的当前值（写库前必须看真值，别用扫描时的旧快照）。"""
    return AK.note_values([int(i) for i in ids], names=TOUCH_FIELDS, chunk=NOTE_CHUNK)


def audio_ready(card):
    if card['n_sent'] != 1:
        return True
    path = os.path.join(AUDIO_DIR, tts_filename(card['id']))
    return os.path.exists(path) and os.path.getsize(path) >= MIN_MP3_BYTES


def cmd_apply(args):
    date = dt.date.today().isoformat()
    cfg = llm_config_or_empty(args)
    cards, sel = select_cards(args)
    force = bool(getattr(args, 'force', False))
    work, already, blocked, states = pick_work(cards, sel, force, capabilities())
    os.makedirs(DATA_DIR, exist_ok=True)
    write_json(STATE_FILE, build_state(date, cards, states, sel))
    write_json(plan_path(date), build_plan(date, sel, work, args, cfg))
    print_pick(cards, work, already, blocked, sel)
    if not work:
        print()
        print('没有待写的卡（都 already_ok 或修不了）。')
        write_report(date, cards, work, already, blocked, sel,
                     extra=['## 本次 apply', '', '没有待写的卡。', ''])
        return 0
    current = live_values([c['id'] for c, _d in work])
    ok_rows, bad_rows, nop_rows = [], [], []
    for card, _d in work:
        entry = entry_for(card, required=False)
        if not entry:
            bad_rows.append((card, None, ['没有合格产出（先跑 gen）']))
            continue
        rendered = render_card(card, entry, current.get(card['id']))
        if not rendered['write']:
            # 目标状态已满足（例如已合规的两句卡被 --force 重新点名）：没有字段要写
            nop_rows.append((card, ['没有任何字段需要写（目标状态已满足）']))
            continue
        problems = gate_apply(card, entry, rendered, rendered['write'])
        row = {'card': card, 'entry': entry, 'rendered': rendered,
               'write': rendered['write'],
               'old': current.get(card['id'], card.get('snapshot', {}))}
        (bad_rows if problems else ok_rows).append((card, row, problems))
    print()
    print('闸门 6-9 通过 %d 张 / 不合格 %d 张 / 无需写字段 %d 张'
          % (len(ok_rows), len(bad_rows), len(nop_rows)))
    need_audio = [r for _c, r, _p in ok_rows if r['card']['n_sent'] == 1]
    ready = [r for r in need_audio if audio_ready(r['card'])]
    if need_audio:
        print('需要上传的媒体文件：%d 个（已就绪 %d 个）' % (len(need_audio), len(ready)))
        for r in ready[:10]:
            name = tts_filename(r['card']['id'])
            size = os.path.getsize(os.path.join(AUDIO_DIR, name))
            print('    %s  %d 字节 约 %.1f 秒' % (name, size, size * 8.0 / AUDIO_BPS))
        if len(ready) < len(need_audio):
            miss = [r['card']['word'] for r in need_audio if not audio_ready(r['card'])]
            print('    ⚠️ 还缺 %d 个音频（%s）→ 先跑 tts；缺音频的卡会跳过'
                  % (len(miss), '、'.join(miss[:8])), file=sys.stderr)
    print()
    print('模式：%s' % ('★ 真写库（--commit）' if args.commit else '演练（不写 Anki，只打印前后对照）'))
    print()
    for card, row, _p in ok_rows:
        new = row['rendered']['fields']
        print('--- %s（noteId %d，%d 句，%s）%s'
              % (card['word'], card['id'], card['n_sent'], card['layout'],
                 '' if audio_ready(card) else '  ⚠️ 缺 TTS 音频'))
        if row['rendered']['warnings']:
            print('    警告：%s' % '、'.join(row['rendered']['warnings']))
        print('    将写字段：%s' % '、'.join(row['write']))
        untouched = [f for f in TOUCH_FIELDS if f not in row['write']]
        if untouched:
            print('    不写的字段（保持卡上现值，逐字不动）：%s' % '、'.join(untouched))
        if args.commit:
            if not audio_ready(card):
                print('    跳过：缺 %s（先跑 tts）' % tts_filename(card['id']))
                continue
        else:
            print_field_diff(row['old'], new, row['write'])
            print_human_gate(row)
    if nop_rows:
        print()
        print('无需写字段（目标状态已满足，不写库）：%s'
              % '、'.join('%s(%d)' % (c['word'], c['id']) for c, _d in nop_rows[:10]))
    if already:
        print()
        print('already_ok（已合规，跳过，不写库）：%s'
              % '、'.join('%s(%d)' % (c['word'], c['id']) for c, _d in already[:10]))
    if bad_rows:
        print()
        print('不合格 %d 张（不写库）：' % len(bad_rows), file=sys.stderr)
        for card, _row, problems in bad_rows[:20]:
            print('  %s %s → %s' % (card['id'], card['word'], '；'.join(problems[:3])),
                  file=sys.stderr)
    if not args.commit:
        print()
        print('演练结束，没有写 Anki。检查上面的前后对照与 %s 里的 mp3（不再要求逐条试听），' % AUDIO_DIR)
        print('确认无误后自己跑同一套选择器 + --commit，例如：')
        print('  apply %s --commit' % _next_hint(args))
        write_report(date, cards, work, already, blocked, sel,
                     extra=apply_report(ok_rows, bad_rows, False, nop_rows))
        return 0
    return do_commit(date, args, cards, work, already, blocked, sel, ok_rows, bad_rows)


def preview(text, limit=150):
    """演练用的**原始**预览：保留标签（ruby 要看得见），块分隔与换行画成 ⏎。"""
    s = (text or '').strip()
    s = RE_BR2.sub(' ⏎⏎ ', s)
    s = RE_BR1.sub(' ⏎ ', s)
    s = s.replace('\n', ' ⏎ ')
    s = RE_SPACES.sub(' ', s)
    return s if len(s) <= limit else s[:limit] + '…'


def print_field_diff(old, new, fields=None, limit=150):
    """打印**要写的那几个字段**的前后对照（原文，不剥标签）。

    `fields=None` = 老口径（5 个都打，探针脚本用）。写库只写 `fields` 里的字段，
    不写的字段保持卡上现值，所以也不在这里制造「旧/新」的错觉。
    """
    for name in (fields or TOUCH_FIELDS):
        o, n = old.get(name, ''), new.get(name, '')
        flag = '  ' if o == n else '≠ '
        print('    %s%-20s 旧: %s' % (flag, name, preview(o, limit)))
        if o != n:
            print('      %-20s 新: %s' % ('', preview(n, limit)))


def print_human_gate(row, ainote_limit=700):
    """演练里给「人看闸门」的那几行：完整振假名 + 段落结构（只打要写的字段）。"""
    f = row['rendered']['fields']
    write = row.get('write') or list(TOUCH_FIELDS)
    if F_HTML in write:
        print('    新 Sentence HTML（逐字检查振假名，重点看 お/ご 有没有被包进 ruby）：')
        print('      %s' % (f[F_HTML].strip() or '（空）'))
    else:
        print('    Sentence HTML 不需要写（卡上振假名已合规），保持原样。')
    if F_NOTE not in write:
        print('    AINote 不需要写（本次不动它），保持卡上原样。')
        return
    note = f[F_NOTE].strip()
    print('    新 AINote%s：' % ('' if len(note) <= ainote_limit else '（前 %d 字）' % ainote_limit))
    print('      %s' % (note[:ainote_limit] + ('…' if len(note) > ainote_limit else '')))


def apply_report(ok_rows, bad_rows, committed, nop_rows=()):
    by_field = {}
    for _card, row, _p in ok_rows:
        for k in row['write']:
            by_field[k] = by_field.get(k, 0) + 1
    lines = ['## 本次 apply（%s）' % ('★ 真写库' if committed else '演练'), '',
             '闸门 6-9 通过 %d 张，不合格 %d 张，无需写字段 %d 张。'
             % (len(ok_rows), len(bad_rows), len(nop_rows)), '']
    if by_field:
        lines.append('将写字段：%s（只写缺陷字段，其余字段逐字不动）'
                     % '、'.join('%s %d 张' % (k, v) for k, v in sorted(by_field.items())))
        lines.append('')
    warn = {}
    for _card, row, _p in ok_rows:
        for w in row['rendered']['warnings']:
            warn[w] = warn.get(w, 0) + 1
    if warn:
        lines.extend(['| 警告 | 张数 |', '|---|---|'])
        for k, v in sorted(warn.items(), key=lambda x: -x[1]):
            lines.append('| %s | %d |' % (k, v))
        lines.append('')
    if bad_rows:
        lines.extend(['| noteId | 词 | 原因 |', '|---|---|---|'])
        for card, _row, problems in bad_rows[:40]:
            lines.append('| %d | %s | %s |' % (card['id'], card['word'],
                                               '；'.join(problems[:2])))
        lines.append('')
    return lines


def do_commit(date, args, cards, work, already, blocked, sel, ok_rows, bad_rows):
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = os.path.join(DATA_DIR, 'backup_%s.json' % stamp)
    todo, skipped = [], []
    for card, row, _p in ok_rows:
        if not audio_ready(card):
            skipped.append((card, ['缺 TTS 音频 %s（先跑 tts）' % tts_filename(card['id'])]))
            continue
        todo.append((card, row))
    if not todo:
        print('没有可写库的卡（都缺音频）。', file=sys.stderr)
        return 1

    # ---- 1) 备份（revert 的唯一依据）：只备份**真的要写、且真的会变**的字段 ----
    #     不写的字段本来就不会动，备份它们只会让 revert 去"还原"一个没人改过的字段。
    notes_backup = {}
    for card, row in todo:
        old, new = row['old'], row['rendered']['fields']
        notes_backup[str(card['id'])] = {k: old.get(k, '') for k in row['write']
                                         if old.get(k, '') != new[k]}
    write_json(backup_path, {'created_at': dt.datetime.now().isoformat(timespec='seconds'),
                             'date': date, 'selection': sel_line(sel),
                             'fields': list(TOUCH_FIELDS),
                             'note': '还原 apply --commit 改过的那几个字段（媒体文件不删）',
                             'notes': notes_backup})
    print('已备份 %d 张卡的旧字段 → %s' % (len(notes_backup), backup_path))

    # ---- 2) 上传媒体 + 回读确认 ----
    for card, _row in todo:
        if card['n_sent'] != 1:
            continue
        name = tts_filename(card['id'])
        print('  上传 %s' % name)
        AK.store_media_file(name, path=os.path.join(AUDIO_DIR, name), delete_existing=True)
    need = [tts_filename(c['id']) for c, _r in todo if c['n_sent'] == 1]
    names = set(AK.media_names('core6000-*.mp3'))
    lost = [n for n in need if n not in names]
    if lost:
        print('❌ 媒体库里没有这些文件，拒绝写库：%s' % '、'.join(lost), file=sys.stderr)
        print('（Anki 一个字都没写；备份留在 %s）' % backup_path, file=sys.stderr)
        return 1

    # ---- 3) 写字段（每张卡只写它自己那几个缺陷字段，见 field_defects） ----
    print()
    print('写 %d 张卡（每张只写它需要写的字段）…' % len(todo))
    for card, row in todo:
        target = {k: row['rendered']['fields'][k] for k in row['write']}
        AK.update_note_fields(card['id'], target)
        print('  ✓ %s（%d）← %s' % (card['word'], card['id'], '、'.join(row['write'])))
    for card, problems in skipped:
        print('  ⏭ %s：%s' % (card['word'], '；'.join(problems)), file=sys.stderr)

    # ---- 4) 回读校验（诚实版）----
    #   * 写过的字段：必须等于写入值；
    #   * 没写的字段：必须**仍然等于写库前的现值**（= 一个字都没动）。
    #     不查这一条，就没法说「其余字段逐字未变」。
    live = live_values([c['id'] for c, _r in todo])
    bad, drifted = [], []
    for card, row in todo:
        cur = live.get(card['id'], {})
        for k in TOUCH_FIELDS:
            if k in row['write']:
                if cur.get(k, '') != row['rendered']['fields'][k]:
                    bad.append((card['word'], k))
            elif cur.get(k, '') != row['old'].get(k, ''):
                drifted.append((card['word'], k))
    print()
    if bad:
        print('⚠️ 回读校验有 %d 处不一致（可能是 Anki 浏览器开着没刷新）：' % len(bad))
        for word, k in bad[:10]:
            print('  %s %s' % (word, k))
    else:
        print('★ 回读校验通过：%d 张卡写入的字段与目标值一致。' % len(todo))
    if drifted:
        print('⚠️ 这些**没打算写**的字段和写库前不一样了（不该发生）：')
        for word, k in drifted[:10]:
            print('  %s %s' % (word, k))
    else:
        print('★ 未写字段校验通过：没写的字段与写库前逐字相同（一个字都没动）。')
    print('退路：revert --commit --backup %s' % backup_path)
    write_report(date, cards, work, already, blocked, sel,
                 extra=apply_report(ok_rows, bad_rows, True))
    return 0


def cmd_revert(args):
    path = args.backup
    if not path:
        cands = sorted(glob.glob(os.path.join(DATA_DIR, 'backup_*.json')))
        if not cands:
            raise SystemExit('没有备份文件（%s/backup_*.json）；revert 没有依据。' % DATA_DIR)
        path = cands[-1]
    obj = read_json(path)
    if not isinstance(obj, dict) or not isinstance(obj.get('notes'), dict):
        raise SystemExit('备份文件读不出来：%s' % path)
    notes = obj['notes']
    print('备份：%s（%s，%d 张卡）%s' % (path, obj.get('created_at', '?'), len(notes),
                                       ('；' + obj['selection']) if obj.get('selection') else ''))
    print('模式：%s' % ('★ 真写库' if args.commit else '演练（不写 Anki）'))
    if not args.commit:
        for nid, fields in list(notes.items())[:10]:
            print('  %s ← %s' % (nid, '、'.join('%s=%s' % (k, preview(v, 40))
                                                for k, v in fields.items())))
        print('（演练结束；加 --commit 才真的还原）')
        return 0
    live = live_values([int(n) for n in notes])
    done = 0
    for nid, fields in notes.items():
        keep = {k: v for k, v in (fields or {}).items()
                if live.get(int(nid), {}).get(k, None) != v}
        if not keep:
            continue
        AK.update_note_fields(int(nid), keep)
        done += 1
    print('已还原 %d 张卡（媒体文件不删，留在媒体库里无害）。' % done)
    return 0


# ============================================================================
# status
# ============================================================================
def cmd_status(args):
    print('牌组：%s' % DECK)
    print('模型：%s ｜ AnkiConnect %s' % (NOTE_MODEL, ANKI_URL))
    print('提示词文件：%s' % ('存在（%d 字节）' % os.path.getsize(PROMPT_FILE)
                            if os.path.exists(PROMPT_FILE) else '★ 还不存在'))
    print('数据目录：%s' % DATA_DIR)
    print()
    plan = None
    try:
        plan = load_plan(quiet=True)
    except SystemExit as e:
        print(e, file=sys.stderr)
    if plan:
        by_id = plan.get('cards') or {}
        # 注意：plan 里 ids 是数字、cards 的键是字符串，必须按 str() 对齐
        cards = [by_id[str(k)] for k in plan.get('ids', []) if str(k) in by_id]
        ok = [c for c in cards if read_out(c['id'])]
        print('清单 %s：待做 %d 张，其中已有合格产出 %d 张'
              % (os.path.basename(plan['_path']), len(cards), len(ok)))
        print('  %s' % plan.get('selection', {}))
        need = [c for c in ok if c['n_sent'] == 1]
        have = [c for c in need if audio_ready(c)]
        print('  TTS：需要 %d 个，已合成 %d 个' % (len(need), len(have)))
        can, bad = 0, []
        for c in ok:
            entry = entry_for(c, required=False)
            if not entry:
                bad.append((c, ['没有产出']))
                continue
            rendered = render_card(c, entry)          # 预检口径与 apply 一致（见 §5.4）
            if not rendered['write']:
                can += 1                              # 目标状态已满足：没有字段要写
                continue
            problems = gate_apply(c, entry, rendered, rendered['write'])
            if problems:
                bad.append((c, problems))
            else:
                can += 1
        print('  apply 预检：可写库 %d 张 / 有问题 %d 张' % (can, len(bad)))
        for c, problems in bad[:5]:
            print('    %s %s → %s' % (c['id'], c['word'], '；'.join(problems[:2])))
    state = read_json(STATE_FILE)
    if state:
        c = state.get('counts', {})
        print()
        print('state.json：%s（%s）选中 %s → work %s / already_ok %s / 修不了 %s'
              % (state.get('date'), state.get('generated_at'), c.get('selected'),
                 c.get('work'), c.get('already_ok'), c.get('blocked')))
    mp3 = glob.glob(os.path.join(AUDIO_DIR, '*.mp3'))
    size = sum(os.path.getsize(p) for p in mp3)
    print()
    print('音频目录 %s：%d 个 mp3，%d 字节（约 %.0f 秒）'
          % (AUDIO_DIR, len(mp3), size, size * 8.0 / AUDIO_BPS))
    backups = sorted(glob.glob(os.path.join(DATA_DIR, 'backup_*.json')))
    print('备份：%s' % (backups[-1] if backups else '（还没有 apply --commit）'))
    metrics = read_json(metrics_path(dt.date.today().isoformat()))
    if metrics and metrics.get('totals'):
        t = metrics['totals']
        print('今日 token：%d 次请求，合计 %d（prompt %d / completion %d）'
              % (t['requests'], t['total_tokens'], t['prompt_tokens'], t['completion_tokens']))
    print()
    print('下一步：%s' % ('gen ' + hint_from_sel(plan.get('selection'))
                         if plan else 'gen --words "…"（先点名要补哪几个词）'))
    return 0


# ============================================================================
# CLI
# ============================================================================
def add_llm_args(sp):
    sp.add_argument('--system-prompt', default=None,
                    help='系统提示词文件（默认 %s）' % PROMPT_FILE)
    sp.add_argument('--base-url', default=None,
                    help='端点 base_url（默认 %s）' % TN.LLM_DEFAULT_BASE)
    sp.add_argument('--model', default=None, help='模型名（默认 %s）' % TN.LLM_DEFAULT_MODEL)
    sp.add_argument('--api-key', default=None,
                    help='api key（优先于 $env:DSH_LOCAL_LLM_API_KEY 与 ~/.dsh/local-llm.json）')
    sp.add_argument('--no-json-mode', action='store_true',
                    help='保留兼容参数；NInfer 不支持结构化输出，已不发 text.format')
    sp.add_argument('--no-stream', action='store_true', help='关掉流式（默认流式）')
    return sp


def add_jisho_args(sp):
    sp.add_argument('--allow-model-sentence', action='store_true',
                    help='Jisho 零候选时允许退回模型造句（默认**不退回**：宁可跳过这张卡）')
    sp.add_argument('--refresh-jisho', action='store_true',
                    help='忽略 data/core6000/jisho/<noteId>.json 缓存，重新抓 Jisho 一页')
    sp.add_argument('--jisho-timeout', type=float, default=30.0, help='Jisho HTTP 超时秒数')
    sp.add_argument('--no-dict', action='store_true',
                    help='振假名渲染时不拿 JMdict 否决 Jisho 被截断的读音')
    return sp


def add_target_args(sp):
    sp.add_argument('--note-ids', default=None, help='点名的 noteId，逗号分隔')
    sp.add_argument('--words', default=None, help='按词形选中，逗号/空格分隔（比 Word，退回 Transliteration）')
    sp.add_argument('--from-file', default=None, help='一行一个词或 noteId（# 注释、空行忽略）')
    sp.add_argument('--from-weak', action='store_true',
                    help='取弱项词表（跑 code/analysis/today_weak.py --plain）')
    sp.add_argument('--days', type=int, default=1, help='--from-weak 看近几天（默认 1）')
    sp.add_argument('--rating', default=None, choices=('again', 'hard', 'both'),
                    help='--from-weak 只看重来/困难（默认 today_weak 自己的默认）')
    sp.add_argument('--query', default=None, help='任意 Anki 查询（默认只加 deck+模型过滤）')
    sp.add_argument('--all', action='store_true', help='★ 显式全库（≈6000 张）')
    sp.add_argument('--only', action='append', default=None,
                    help='范围：%s、all（默认 %s）' % ('、'.join(SCOPES),
                                                    '、'.join(DEFAULT_SCOPES)))
    sp.add_argument('--limit', type=int, default=None, help='最多处理几张卡（作用在待做卡上）')
    return sp


def main():
    ap = argparse.ArgumentParser(
        description='Core6000 按需补例句②：用户点名的词 → 新例句 + 振假名 + 合并讲解 + 配音。',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='契约：docs/core6000-example-design.md；流程：.dsh/skills/jp-anki-daily 第四节。\n'
               '例： gen --words "徹夜,適当"  →  tts --words "徹夜,適当"  →  apply --words "徹夜,適当"')
    sub = ap.add_subparsers(dest='cmd')

    sp = sub.add_parser('scan', help='只读体检（给选择器就只看选中的卡；不给就全库）')
    add_target_args(sp)
    add_llm_args(sp)
    sp.add_argument('--force', action='store_true', help='把 already_ok 的卡也算进待做')
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser('gen', help='Jisho 取真实新句 + 本地模型写 ② 讲解（闸门 1-5，逐张落盘）')
    add_target_args(sp)
    add_llm_args(sp)
    add_jisho_args(sp)
    sp.add_argument('--restart', action='store_true', help='忽略已有产出，重生成')
    sp.add_argument('--force', action='store_true', help='already_ok 的卡也重做')
    sp.add_argument('--per-batch', type=int, default=1,
                    help='一次给模型几张卡（默认 1；>1 只省 system 前缀，不推荐）')
    sp.add_argument('--retries', type=int, default=1, help='闸门 1-5 不过时重问几次（默认 1）')
    sp.set_defaults(func=cmd_gen)

    sp = sub.add_parser('tts', help='只合成新句 mp3 到 output/audio/core6000/（不碰 Anki）')
    add_target_args(sp)
    sp.add_argument('--force', action='store_true', help='已有音频也重做')
    sp.set_defaults(func=cmd_tts)

    sp = sub.add_parser('apply', help='渲染 + 跑闸门 6-9 + 写库（默认演练）')
    add_target_args(sp)
    sp.add_argument('--commit', action='store_true', help='★ 真写库（不加就是演练）')
    sp.add_argument('--force', action='store_true', help='already_ok 的卡也重写')
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser('revert', help='从 backup_*.json 还原那 5 个字段')
    sp.add_argument('--commit', action='store_true', help='★ 真写库（不加就是演练）')
    sp.add_argument('--backup', default=None, help='指定备份文件（默认最近一份）')
    sp.set_defaults(func=cmd_revert)

    sp = sub.add_parser('status', help='进度一览（只读，不调模型、不写 Anki）')
    sp.add_argument('--limit', type=int, default=None)
    sp.set_defaults(func=cmd_status)

    args = ap.parse_args()
    if not getattr(args, 'func', None):
        ap.print_help()
        return 2
    try:
        return args.func(args)
    except AK.AnkiError as e:
        print('Anki 错误：%s' % e, file=sys.stderr)
        return 2
    except TN.LLMError as e:
        print('本地模型错误：%s' % e, file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print('\n中断。已完成的产出都在磁盘上，重跑 gen 会接着做。', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
