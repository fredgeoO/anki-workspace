# -*- coding: utf-8 -*-
"""讲义的机械判定层：词形/读音/词性、内容问题、渲染后闸门。

从 ``execution/today_new.py`` 抽出（2026-11-01，阶段 4 第二刀）。这里只有
**能证伪的机械判断**：不吃 Anki、不吃 LLM、不写文件，输入是 manifest / lesson
字典，输出是人话问题清单。渲染（`render_lesson` / `render_light_card`）仍留在
`today_new`，因为它依赖排版细节与计数。

**口径来源**：判断"模型讲解够不够用"的规则在 docs/…；本模块只负责把规则写成代码，
模型不参与（铁律 6：机械判断交给代码）。
"""
import os
import re
import sys

# 系列子目录（issue #12）：单独 import 时自己挂上 code/common 与本系列目录。
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(os.path.dirname(os.path.dirname(_HERE)), 'common'), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ruby_text import KANJI
from lesson_text import grammar_structure, strip_ruby_readings

PLACEHOLDER = re.compile(r'\{\{[^{}]*\}\}')

TRAILING_KANA = re.compile(r'[\u3040-\u309f]+$')

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

# 「这个词在这句里真的用上了吗」——机械可查。
# 实测本地模型偶尔会造出不含目标词的例句（例：给「〜あまり」造了「節約しすぎて…」，
# 还自己加了一句「注：此句为错误用法示例」）。这类句子对学习者是干扰，必须报出来。
KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30a0-\u30ffー]+$')


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
