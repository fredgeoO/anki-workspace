# -*- coding: utf-8 -*-
"""卡片讲解提示词正本装载器：Sentence HTML（振假名）与 AINote（讲解）共用一套规则。

为什么要它：阶段二（`cards.py gen` / `pipeline.py gen`）与 core6000 补例句
（`core6000_example.py gen`）问的是同一件事——「给一句已给定的日语例句标振假名、写讲解」。
以前两处各写一份（`pipeline.LOCAL_INSTRUCTION` 内联、`core6000_example_prompt.md` 整份），
规则一改就要改两遍，还容易各说一套。现在**规则正文只有一份**：

* `code/execution/card_rules.md` —— 正本（人只改这份；用 `{{RULES}}` 占位引用）
* 本模块 —— 装载器：
  * :func:`rules` 读正本（带缓存）；
  * :func:`pipeline_instruction` 拼出 pipeline / `cards.py` 的完整系统提示词
    （批量输入，输出 `AINote` HTML + `SentenceHTML`）；
  * :func:`expand` 把正本填进 core6000 的提示词外壳（那里输出 11 个结构化键）。

两个入口的差别只剩「输入是什么、输出成什么键」，生成逻辑完全一致。
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import paths as WSP     # noqa: E402  工作区路径的唯一来源
import textio           # noqa: E402  UTF-8 stdio 唯一入口

PLACEHOLDER = '{{RULES}}'
_RULES = None


def rules(path=None):
    """正本正文（含首行标题），读一次缓存；`path` 给定时不写缓存。

    正本里给「人」看的维护说明写在 HTML 注释里（`<!-- … -->`），这里剥掉——
    模型只该看到规则本身，不需要知道提示词是怎么拼的。
    """
    global _RULES
    if path is None and _RULES is not None:
        return _RULES
    p = path or WSP.DOC_CARD_RULES
    if not os.path.exists(p):
        raise RuntimeError('找不到卡片讲解正本：%s\n（规则正本应在 code/execution/card_rules.md）' % p)
    text = textio.read_text(p).replace('\r\n', '\n')
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if path is None:
        _RULES = text
    return text


def expand(text, path=None):
    """把提示词外壳里的 `{{RULES}}` 换成正本正文；没有占位符就原样返回。"""
    return (text or '').replace(PLACEHOLDER, rules(path))


_EXAMPLE = (
    '{"cards":[{"noteId":1,"AINote":"<p><b>中文翻译：</b>回邮局的时候我查查看。</p>'
    '<p><b>核心词汇：</b><br><ruby>郵便局<rt>ゆうびんきょく</rt></ruby>：名词。邮局。'
    '<br><ruby>戻<rt>もど</rt></ruby>る：自动词（五段）。返回、回到。'
    '<br><ruby>調<rt>しら</rt></ruby>べる：他动词（一段）。调查、查询。</p>'
    '<p><b>语法要点：</b><br>・〜た時に：表示「在……的时候」，接在动词た形后，'
    '提示后项动作发生的时间点。<br>・〜てみる：表示「试着做某事」，接在动词て形后，'
    '带有尝试的语感。</p>'
    '<p><b>动词变形解析：</b><br>戻る（原形）→ 戻っ（连用形·促音便）→ 戻った（た形）＋時に'
    '<br>調べる（原形）→ 調べて（て形）＋みる → 調べてみる（〜てみる）</p>'
    '<p><b>语境与表达风格：</b>普通体口语，朋友之间随口说的语气，'
    '带着「我先查一下再告诉你」的轻松承诺感。</p>",'
    '"SentenceHTML":"<ruby>郵便局<rt>ゆうびんきょく</rt></ruby>に'
    '<ruby>戻<rt>もど</rt></ruby>った<ruby>時<rt>とき</rt></ruby>に'
    '<ruby>調<rt>しら</rt></ruby>べてみるよ"}]}'
)

# 输入/输出外壳：pipeline（批量、输出整段 AINote HTML + SentenceHTML）
_PIPELINE_HEAD = '''你是精通日语的语言学教授，给中文母语的日语学习者上课。输入是一批 Anki 例句卡，为每张卡生成讲解（AINote）与带振假名的例句 HTML（SentenceHTML）。

【输入】JSON 数组，每项 {noteId, sentence, word, source}
  sentence：例句原文（来自字幕/对白，可能含 <br>、全角空格、〓 这类字幕噪声）——一律原样对待
  word：非空时是这张卡指定的重点词，核心词汇的第一条必须是它
  source：出处，只用来判断语域（动画口语 / 新闻 / 旁白），不要写进结果

【输出】只输出一个 JSON 对象，前后不要任何解释或 markdown 围栏：
{"cards":[{"noteId":123,"AINote":"…","SentenceHTML":"…"}]}
输入里每张卡都要有一条对应输出：noteId 必须是 JSON 数字（照抄输入，别加引号），顺序与输入一致。

【AINote 版式】固定五段、每段一个 <p>；前三段必有，后两段按需：
<p><b>中文翻译：</b>…</p>
<p><b>核心词汇：</b><br>…</p>
<p><b>语法要点：</b><br>…</p>
<p><b>动词变形解析：</b><br>…</p>
<p><b>语境与表达风格：</b>…</p>
- 各段内容按下面共用规则的第二–六节写；段落名一字不差
- 动词变形解析：全句没有活用动词（名词句、形容词句）就整段省略
- 语境与表达风格：信息不足可省略
- 整段 AINote 控制在 400 字以内：这是复习卡，不是词条页

【SentenceHTML】只含例句本身：给日语汉字标 ruby（规则见共用规则第七节），
不加翻译、不加解释、不用 <p> 包裹、不加句末标点、不改任何空格与标点、<br> 原位置保留单个。

【示例】输入 {"noteId":1,"sentence":"郵便局に戻った時に調べてみるよ","word":"","source":"…"}
输出 ''' + _EXAMPLE + '''

上面是输入/输出外壳。下面是**共用规则正本**：pipeline 与 core6000 补例句共用同一份，
每一条都要遵守。'''

# 本入口特有的收尾核对（通用核对在正本第十节）
_PIPELINE_TAIL = '''【本入口的收尾核对】
1. 输出的 noteId 集合与输入完全一致：顺序一致、每张卡一条、不多不少
2. AINote / SentenceHTML 的值都是字符串；确实讲不了（乱码、整句没有可解释的语义单位）时
   两个字段都写空字符串 ""，不要编造；其余卡照常生成——但**不要省掉整个对象**
3. AINote 的段落名一字不差（中文翻译／核心词汇／语法要点／动词变形解析／语境与表达风格），
   前三段必须有'''


def pipeline_instruction(path=None):
    """pipeline / `cards.py` 用的完整系统提示词（批量，输出 AINote HTML + SentenceHTML）。"""
    return (_PIPELINE_HEAD.rstrip() + '\n\n' + rules(path) + '\n\n'
            + _PIPELINE_TAIL.strip()).strip()
