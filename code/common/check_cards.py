# -*- coding: utf-8 -*-
"""日语例句卡自检器 —— 实现 jp-card-agent-instruction.md 第 7 节的清单。

用法：
  python check_cards.py sample_output.json                     # 校验 JSON 文件
  python check_cards.py --anki "tag:动画::<作品名>::<季>::第NN集"   # 直接从 Anki 拉取校验
  python check_cards.py --anki "deck:0-日本语学习::2-例句 AINote:_*" --limit 50

输入 JSON 格式：[{"noteId":123,"sentence":"…","AINote":"…","SentenceHTML":"…"}, ...]
（--anki 模式会自动把 AINote / Sentence HTML 字段映射进来）
"""
import json, os, re, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import anki_api as AK  # noqa: E402  唯一的 Anki 访问点（传输/分块/字段拆包都在里面）
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
from llm_out import as_text  # noqa: E402  「模型产出吸收层」：非字符串字段一律当空串

TAG = re.compile(r'<[^>]+>')
RT_BLOCK = re.compile(r'<rt>.*?</rt>', re.S)
RUBY_BLOCK = re.compile(r'<ruby>.*?</ruby>', re.S)
KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
WHITELIST = {'p', 'br', 'b', 'ruby', 'rt'}
SECTIONS = ('中文翻译', '核心词汇')
MARKER = '<p><b>待人工处理：</b>'


def stray_rt(s):
    """`<ruby>` 之外的 `<rt>`（例如 `<ruby>救<rt>すく</rt></ruby>援<rt>えん</rt>`）。

    配对计数查不出来（两边都成对），但渲染时会把这个读音当普通文字显示在词条里。
    返回这些野 `<rt>` 的片段，供校验器报错。
    """
    rest = RUBY_BLOCK.sub('', s or '')
    return re.findall(r'.{0,6}<rt>.{0,4}', rest)


def load_from_anki(query, limit=None):
    cards = []
    for n in AK.notes_info(AK.find_notes(query, limit=limit)):
        f = AK.field_values(n)
        cards.append({
            'noteId': n['noteId'],
            'sentence': f.get('Sentence', ''),
            'AINote': f.get('AINote', ''),
            'SentenceHTML': f.get('Sentence HTML', ''),
        })
    return cards


def text_of(s):
    """删掉 <rt>假名</rt> 整块，再剥其余标签 —— 用于与 Sentence 逐字比对"""
    return TAG.sub('', RT_BLOCK.sub('', s))


def outside_ruby(s):
    """删掉整个 <ruby>…</ruby> 后剩下的可见文本"""
    return TAG.sub('', RUBY_BLOCK.sub('', s))


def field_hard(field, val):
    """**单个字段自身**的硬性问题：非法字符、标签白名单、ruby/rt 配对、野 `<rt>`。

    （逐字一致、汉字覆盖、段落齐全这类"跨字段/内容级"判断不在这里。）
    """
    hard = []
    if not val:
        return hard
    if '\\' in val:
        hard.append('%s 含反斜杠' % field)
    if '$' in val:
        hard.append('%s 含 $' % field)
    if '```' in val or '**' in val:
        hard.append('%s 含 Markdown 标记' % field)
    if '"' in val:
        hard.append('%s 含半角双引号' % field)
    for m in re.finditer(r'<\s*/?\s*([a-zA-Z0-9]+)', val):
        if m.group(1).lower() not in WHITELIST:
            hard.append('%s 用了白名单外标签 <%s>' % (field, m.group(1)))
    if re.search(r'(class|style)\s*=', val):
        hard.append('%s 含 class/style 属性' % field)
    if val.count('<ruby>') != val.count('</ruby>') or val.count('<rt>') != val.count('</rt>'):
        hard.append('%s 的 ruby/rt 标签不配对' % field)
    for frag in stray_rt(val):
        hard.append('%s 有 <ruby> 之外的 <rt>：%s' % (field, frag))
    return hard


def split_hard(card):
    """把硬性问题按**归属字段**拆开 → `(ainote_hard, html_hard, soft)`。

    为什么需要它：两个字段的"失败"性质完全不同，处置方式也完全不同。

    * `AINote`（中文翻译/核心词汇/语法要点/动词变形）是**纯语义产出** ——
      不合格只能重问模型，或者交给强模型。
    * `Sentence HTML` 的硬性问题（文本漂移、漏标 ruby、`<br>` 数不对）**全是机械问题** ——
      `ruby_engine.py repair` 拿原始 `Sentence` 当骨架重渲染就能确定性地修好
      （逐字一致是构造出来的），再问一次模型不但没用、还会把已经合格的讲解一起丢掉。

    实测（2026-10-11 七大罪 E01，noteId 1791727898061）：本地模型给出的 AINote 完全合格，
    只是把 `様子` 标成了 `<ruby>様<rt>よう</rt></ruby>子`。旧的 `check()` 只看一个混合的
    hard 列表 → 整张卡判失败 → 讲解被丢弃 → 卡被送进 `needs_llm.json` 等强模型，
    而它真正缺的只有一个 `repair` 就能补上的振假名。
    """
    a = as_text(card.get('AINote')) if isinstance(card, dict) else ''
    h = as_text(card.get('SentenceHTML')) if isinstance(card, dict) else ''
    sent = as_text(card.get('sentence')) if isinstance(card, dict) else ''
    soft = []
    ai, html = [], []
    if not isinstance(card, dict):
        return ['条目不是对象：%r' % (card,)], html, soft

    # 本地模型偶尔把字符串字段回成数字/列表（2026-10-12 阶段四就是这样整批崩的）。
    # 这里先吸收成空串，再报一条**明确的硬错误**，交给逐张重问 —— 不抛异常、不连坐同批。
    for key in ('AINote', 'SentenceHTML', 'sentence'):
        v = card.get(key)
        if v is not None and not isinstance(v, str):
            ai.append('%s 字段类型不是字符串：%s %r' % (key, type(v).__name__, v))
    if ai:
        return ai, html, soft

    if not a and not h.strip():
        # 尚未处理，或被判定为"无法给出可靠讲解"而有意跳过（两个字段都留空）
        soft.append('AINote 为空（尚未处理或已跳过生成）')
        return ai, html, soft

    if a.startswith(MARKER):
        # 显式的"待人工处理"标记：允许 Sentence HTML 留空
        soft.append('已标记为待人工处理，跳过内容校验')
        if h.strip():
            soft.append('待人工处理卡通常应留空 Sentence HTML')
        return ai, html, soft

    ai += field_hard('AINote', a)
    if not a:
        ai.append('AINote 为空但 Sentence HTML 非空（留空约定要求两个字段一起留空）')
        return ai, field_hard('SentenceHTML', h), soft

    for key in SECTIONS:
        if '<b>%s：</b>' % key not in a:
            ai.append('AINote 缺少段落：%s' % key)
    if a.count('<p>') != a.count('</p>'):
        ai.append('<p> 标签不配对')

    if not h:
        html.append('AINote 有内容但 Sentence HTML 为空')
    else:
        if text_of(h) != text_of(sent):
            html.append('Sentence HTML 与 Sentence 不一致：%r vs %r' % (text_of(h), text_of(sent)))
        if h.count('<br>') != sent.count('<br>'):
            html.append('<br> 数量不一致（HTML %d / 原文 %d）' % (h.count('<br>'), sent.count('<br>')))
        left = KANJI.findall(outside_ruby(h))
        if left:
            html.append('Sentence HTML 有未标 ruby 的汉字：%s' % ''.join(left))
        for m in re.finditer(r'<ruby>([^<]*)<rt>', h):
            if not KANJI.search(m.group(1)):
                soft.append('Sentence HTML 给纯假名加了 ruby：%s' % m.group(1))
    html += field_hard('SentenceHTML', h)

    # 词条头的 ruby 覆盖（软性：中文语境混排，仅提示）
    for seg in re.split(r'<br>', a):
        if '：' not in seg:
            continue
        head = seg.split('：')[0]
        if head.startswith('<p><b>') or head.startswith('<b>'):
            continue
        if KANJI.search(outside_ruby(head)):
            soft.append('AINote 词条头可能有未标 ruby 的汉字：%s' % outside_ruby(head))
    return ai, html, soft


def check(card):
    """全量校验（入库闸门口径）：返回 `(hard, soft)`。

    与 `split_hard` 的唯一区别：`AINote` 为空**且** `Sentence HTML` 也为空时不算硬错误 ——
    有意跳过生成的卡两个字段本来就该是空的，不该拦住整批入库。需要区分两个字段的
    处置方式（讲解重问模型 / 振假名交给 repair）时用 `split_hard`。
    """
    ai, html, soft = split_hard(card)
    return ai + html, soft


def main():
    args = sys.argv[1:]
    limit = None
    if '--limit' in args:
        i = args.index('--limit')
        limit = int(args[i + 1])
        del args[i:i + 2]
    if args and args[0] == '--anki':
        cards = load_from_anki(args[1], limit)
        label = 'Anki 查询：%s' % args[1]
    else:
        path = args[0] if args else 'sample_output.json'
        cards = json.load(open(path, encoding='utf-8'))
        label = '文件：%s' % path

    print('%s   共 %d 张' % (label, len(cards)))
    print('=' * 70)
    bad = 0
    for c in cards:
        hard, soft = check(c)
        if hard:
            bad += 1
            ok_dict = isinstance(c, dict)
            print('★ noteId %s  《%s》' % (c.get('noteId') if ok_dict else '?',
                                          as_text(c.get('sentence') if ok_dict else '')[:34]))
            for p in hard:
                print('    [不合格] %s' % p)
        for p in soft:
            if hard:
                print('    [提醒]   %s' % p)
    print('=' * 70)
    print('合格 %d / 不合格 %d / 总计 %d' % (len(cards) - bad, bad, len(cards)))


if __name__ == '__main__':
    with AK.guard():          # Anki 没开时给中文提示，不出 traceback
        main()
