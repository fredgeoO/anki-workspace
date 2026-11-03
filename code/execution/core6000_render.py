# -*- coding: utf-8 -*-
"""core6000 补例句②的字段渲染：卡片结构体 + 模型产出 → 5 个字段的值。

从 ``execution/core6000_example.py`` 抽出（2026-11-02，Issue #4「按能力切分超大流程
文件」）。契约文档：docs/core6000-example-design.md §5——这块就是那份契约的代码形态：
`Sentence` / `Sentence HTML` / `Sentence Translation` / `AINote` / `Sentence Audio`
五个字段怎么拼、哪几个**这次真的要写**（``field_defects``）。

不碰 Anki、不调模型、不落盘：给它卡片结构体（``scan`` 解析出来的那份）和模型的
entry，它返回渲染结果与要写的字段清单。闸门 6-9 仍留在巨石里——它们判的是「写库前」
的现场状态（`live_values`），和 apply 的流程绑在一起。

口径一字未改；``core6000_example`` 仍以同名模块级别名导出这些函数。
纯渲染的那一小撮（词性中文化 / 注音 / 词表）早在 ``core6000_text``。板块解析
（``parse_sections`` / ``section_map``）留在巨石里——它判的是**卡片侧**的版式识别，
与「拼出第 2 句」是两个能力；本模块只吃解析结果（``card['sections']``），
canon → 正文那份映射由巨石 import 后注入（见 ``bind_constants``）。

**调用约定同 ``core6000_jisho``**：这块内部的跨函数调用走 ``_CE()``，字段名 /
触碰清单 / canon 顺序也每次经巨石读（``_ce()``），所以巨石 import 后注入的真值当场
生效；单独 import 本模块时落到下面的默认值（与巨石当前取值一致）。
"""
import re
import sys

from core6000_text2 import (RE_BR1, count_blocks, dedupe, flatten, join_blocks, plain)
# ② 的词表渲染（gloss_lines）在 core6000_text；与这里同为纯渲染，不碰 Anki。
from core6000_text import gloss_lines


def _ce():
    """字段名 / 触碰清单 / canon 顺序经巨石读：真值在它那边，注入一次就都跟着走。"""
    return sys.modules.get('core6000_example') or sys.modules[__name__]


def _CE():
    """跨函数调用一律走这里（口径同 core6000_jisho._CE）。"""
    return sys.modules.get('core6000_example') or sys.modules[__name__]


# ---- 单独 import 本模块时的默认值（巨石 import 后 bind_constants() 注入真值）----
F_SENT = 'Sentence'
F_HTML = 'Sentence HTML'
F_TRANS = 'Sentence Translation'
F_NOTE = 'AINote'
F_AUDIO = 'Sentence Audio'
TOUCH_FIELDS = (F_SENT, F_HTML, F_NOTE, F_TRANS, F_AUDIO)
CANON_ORDER = ('中文翻译', '核心词汇', '语法要点', '动词变形解析', '语境与表达风格')


def section_map(sections):
    """canon → 该板块的（首个）正文；认不出的板块单独列出来。

    默认实现只在单独 import 本模块时兜底；巨石 import 后会用 bind_constants() 把它的
    ``section_map`` 注入进来，保证与 ``parse_sections`` 走同一份实现。
    """
    known, unknown = {}, []
    for sec in sections:
        if sec['canon']:
            known.setdefault(sec['canon'], sec)
        else:
            unknown.append(sec)
    return known, unknown


def bind_constants(field_names, touch_fields, canon_order, section_map_fn):
    """由 core6000_example 在 import 后注入真常量与板块映射（单向，不产生循环 import）。

    ``field_names`` = (F_SENT, F_HTML, F_TRANS, F_NOTE, F_AUDIO)；
    ``section_map_fn`` = 巨石里的 ``section_map``（canon → 正文，属板块解析能力）。
    """
    g = globals()
    F, H, T, N, A = field_names
    for k, v in (('F_SENT', F), ('F_HTML', H), ('F_TRANS', T), ('F_NOTE', N), ('F_AUDIO', A)):
        g[k] = v
    g['TOUCH_FIELDS'] = tuple(touch_fields)
    g['CANON_ORDER'] = tuple(canon_order)
    g['section_map'] = section_map_fn

# ============================================================================
# 渲染（契约 §5）：五个字段的目标形态 + 「这次写哪几个」
# ============================================================================
# ============================================================================
# 渲染（契约 §5）
# ============================================================================
def render_sentences(card, entry):
    """`Sentence`：1 句的卡 = 原句 + 新句；已有 2 句的卡 = 原来那两句（绝不追加第三句）。"""
    if card['n_sent'] >= 2:
        return join_blocks(card.get('snapshot', {}).get(_ce().F_SENT, '')) or \
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
        return join_blocks(card.get('snapshot', {}).get(_ce().F_TRANS, '')) or \
            '<br><br>'.join(s['cn'] for s in card['sentences'] if s['cn'])
    orig = join_blocks(card.get('snapshot', {}).get(_ce().F_TRANS, ''))
    if not orig:
        orig = entry['cn1']
    return ('%s<br><br>%s' % (orig, entry['cn2'])) if orig else entry['cn2']


def tts_filename(note_id):
    return 'core6000-%d-sentence-2.mp3' % note_id


def render_audio(card):
    """`Sentence Audio`：1 句的卡 = 原来那条 + 新句 TTS（去重，绝不重复追加）。

    已有 2 句的卡 = 原样返回（音频早就齐了）。
    """
    orig = card.get('snapshot', {}).get(_ce().F_AUDIO, '')
    if card['n_sent'] >= 2:
        return orig
    names = dedupe(list(card['audio_files']) + [_CE().tts_filename(card['id'])])
    return ''.join('[sound:%s]' % f for f in names)


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
    orig = _CE().split_merged_body(sec['body'])[0] if sec else ''
    if canon == '中文翻译':
        return _CE().both(orig or entry['cn1'], entry['cn2'])
    if canon == '核心词汇':
        word, reading, meaning = card['word'], card['reading'], card['meaning']
        two = '<br>'.join(gloss_lines(word, reading, meaning, entry['new_word_gloss'],
                                      card['pos']))
        return _CE().both(orig or entry['core1'], two)
    if canon == '语法要点':
        return _CE().both(orig or entry['grammar1'], entry['grammar2'])
    if canon == '动词变形解析':
        return _CE().both(orig or entry['conjugation1'], entry['conjugation2'])
    if canon == '语境与表达风格':
        two = entry['context2']
        if entry['contrast']:
            two = (two + '<br>' if two else '') + '两句对比：' + entry['contrast']
        return _CE().both(orig or entry['context1'], two)
    return _CE().both(orig, '')


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
    known, _unknown = _CE().section_map(card['sections'])
    items, done = [], set()
    for sec in card['sections']:
        if not sec['canon']:
            items.append(sec['raw'])                 # 认不出的板块整块原样保留
            continue
        if sec['canon'] in done:                     # 同名板块重复 → 只渲染第一次
            continue
        done.add(sec['canon'])
        body = _CE().section_body_html(sec['canon'], card, entry, known)
        if body:
            items.append(_CE().render_section_item(card['layout'], sec['label'] or sec['canon'], body))
    for canon in _ce().CANON_ORDER:                        # 原卡缺的板块：只写 ②
        if canon in done:
            continue
        body = _CE().section_body_html(canon, card, entry, known)
        if body:
            items.append(_CE().render_section_item(card['layout'], canon, body))
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
        return list(_ce().TOUCH_FIELDS)        # 1 句 → 2 句：五个字段都还没到目标状态
    if card['need_ruby1'] or card['need_ruby2']:
        return [_ce().F_HTML]
    return []


def render_card(card, entry, current=None):
    """渲染 5 个字段，返回 {'fields': {...}, 'write': [...], 'warnings': [...]}。

    `current` = 从 Anki **现场读**的这 5 个字段现值（`live_values` 的结果）。给了就用它当
    「卡上现值」：既用来判 `write`（`field_defects`），也用来当渲染的原值（别拿扫描时的旧快照
    去覆盖人家刚改过的卡）。不给（探针脚本）就退回扫描快照。
    """
    if current:
        card['snapshot'] = dict(current)
    write = _CE().field_defects(card, current)
    fields = {
        _ce().F_SENT: _CE().render_sentences(card, entry),
        _ce().F_HTML: _CE().render_sentence_html(card, entry),
        _ce().F_NOTE: _CE().render_ainote(card, entry),
        _ce().F_TRANS: _CE().render_translation(card, entry),
        _ce().F_AUDIO: _CE().render_audio(card),
    }
    live = card.get('snapshot') or {}
    warnings = []
    if card['n_sent'] >= 2:
        if card['unmerged']:
            # AINote 里还没有 ①②、但这次不写它（见 field_defects）：不是「留个 ① 的坑」，
            # 是这张卡压根不走 not-merged（契约 §5.3），只补振假名，讲解保持原样。
            warnings.append('note_unmerged_untouched')
        if count_blocks(live.get(_ce().F_TRANS, '')) != 2:
            warnings.append('trans_missing_2nd')       # 旧句的译文缺块：脚本不代笔
        if len(card['audio_files']) != 2:
            warnings.append('audio_count_%d' % len(card['audio_files']))
    if card['n_sent'] >= 2 and flatten(entry['new_sentence']) != \
            flatten(card['sentences'][1]['jp']):
        warnings.append('sentence2_mismatch')
    if _ce().F_NOTE in write:                  # 只有真的要写 AINote 时，这些「板块」警告才有意义
        for canon in card['section_missing']:
            warnings.append('note_missing_section:' + canon)
        if card['section_unknown']:
            warnings.append('note_unknown_section:' + '/'.join(card['section_unknown']))
    if card['n_sent'] == 1 and len(card['trans_blocks']) > 1:
        warnings.append('trans_extra_blocks')
    return {'fields': fields, 'write': write, 'warnings': warnings}
