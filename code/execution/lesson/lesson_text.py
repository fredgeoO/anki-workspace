# -*- coding: utf-8 -*-
"""讲义的文本整形与 teach 渲染：与 Anki / LLM 无关的纯函数。

从 ``execution/today_new.py`` 抽出（2026-11-01 第二批）：这组函数只依赖正则与
``htmltext.strip_tags``，放进独立模块后可以脱离 3k 行巨石单独测试/复用。
"""
import os
import re
import sys

# 系列子目录（issue #12）：单独 import 时自己把 code/common 挂上 sys.path。
_COMMON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                       os.path.abspath(__file__)))), 'common')
if _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)

from htmltext import strip_tags
from ruby_text import strip_ruby_readings  # noqa: F401  正本在 common/ruby_text.py（issue #5）

TEXTY_FIELDS = ('one_line', 'core', 'structure', 'contrast', 'memory', 'pitfall')
LIST_FIELDS = ('usage', 'uses', 'notes')
EX_SPLIT = re.compile(r'\s*(?:——|--|—|\||｜|\t)\s*')
CJK_SPACE_CJK = re.compile(r'[\u4e00-\u9fff\u3040-\u309f][\u3000 ]+[\u4e00-\u9fff\u3040-\u309f]')

# 语法接续里常见的记号写法 → 中文词性说法（只做等价替换，不改结构）
STRUCT_REPLACE = (
    ('する動詞の', '动词的'), ('する動詞', '动词'), ('動詞', '动词'),
    ('ナＡ', 'ナ形容词'), ('イＡ', 'イ形容词'),
    ('Ｖる形', '动词辞书形'), ('动词る形', '动词辞书形'), ('Ｖる', '动词辞书形'),
    ('Ｖた形', '动词た形'), ('Ｖて形', '动词て形'), ('Ｖない形', '动词ない形'),
    ('Ｖ', '动词'), ('Ｎ', '名词'), ('Ａ', '形容词'),
)


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
