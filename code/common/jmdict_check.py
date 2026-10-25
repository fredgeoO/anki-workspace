# -*- coding: utf-8 -*-
"""JMdict 词典层：拿词典当**事实来源**，给卡片的词形 / 读音 / 词性纠错，并产出词典事实。

定位
----
`jmdict-lookup` 技能回答「这个词到底是什么」；本模块把同一本词典接进
每日讲义链路（`today_new.py`），在**调模型之前**把卡片数据里机械可判的错挑出来：

* 读音不在 JMdict 的读音表里（`こ` 配 `あそこ`、`逃がす` 配 `にぐす`）；
* 词性跟词典冲突（`あっ` 标成副词、`ん` 标成惯用句）；
* 他动词 / 自动词标反；
* 词形在词典里根本不存在（拟声/口语词常见，只提示不判错）。

同时把讲词义用得上的**词典事实**（`facts`）压成紧凑结构：读音候选、表记、
中文词性、义项（英文 gloss）、语域标签、适用限制、用法说明。每日讲义把它挂到
每张词汇卡的 `dict` 字段上，模型不必自己猜；缓存/复用的判断由 `today_new.py` 负责。

只做**能证伪**的判断：释义对不对、例句自不自然、多义词取哪条——这些词典
不负责，仍然交给模型和用户。本模块只读词典、**不写 Anki**。

三条设计约束
------------
1. **宁可漏，不可误报**：同形多词条时（`もん` 同时是 者/物/門…）不自动改词性，
   只报「多词条」；单条词条才给 `pos_fix`。
2. **降级不阻断**：`jmdictpy` 没装或词典库没建时 `Lookup.available == False`，
   调用方跳过即可，绝不因为查词典失败挡住讲义。
3. **可注入**：`check_card()` 只依赖 `lookup(word)` 这个方法，测试可以塞假词典，
   不需要 551 MB 的 `jmdict.db`。

用法
----
    import jmdict_check as JC
    lk = JC.Lookup()                       # 不可用时 available=False
    rep = JC.check_manifest(manifest, lk)  # {'cards': {id: 结果}, 'counts': {...}}
    print('\n'.join(JC.format_report(rep)))

    # 单条快速查（排查用）
    python code\\common\\jmdict_check.py こ あそこ 上手
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio（import 即接管）

DEFAULT_DB = os.path.join(WSP.DATA, 'dict', 'jmdictpy', 'jmdict.db')
PYLIBS = os.path.join(WSP.DATA, 'pylibs')


def db_version(db_path=None):
    """词典库版本（version.json 的 tag）。读不到返回 ''，**不打开** 551 MB 的库。"""
    path = os.path.join(os.path.dirname(db_path or DEFAULT_DB), VERSION_FILE)
    try:
        with open(path, encoding='utf-8') as fh:
            return str((json.load(fh) or {}).get('tag') or '')
    except (OSError, ValueError):
        return ''


SEVERITY = {'error': 3, 'warn': 2, 'info': 1}
LEVEL_LABEL = {'error': '硬错', 'warn': '建议', 'info': '提示'}
FIELD_LABEL = {'reading': '读音', 'pos': '词性', 'word': '词形'}

# 事实/核验形状变了就 +1：每日讲义据此判断 dict_<日期>.json 还能不能复用
CACHE_VERSION = 2
VERSION_FILE = 'version.json'

# 发给模型的事实上限（每张词汇卡 +约 60–120 token）
FACT_MAX_ENTRIES = 2
FACT_MAX_SENSES = 3
FACT_MAX_SENSES_TOTAL = 4
FACT_MAX_GLOSSES = 2
FACT_MAX_TAGS = 4
FACT_GLOSS_CHARS = 90
FACT_INFO_CHARS = 60

# ---------------------------------------------------------------------------
# 1. 词性：JMdict 代码 → 中文；再归成「粗类」用于冲突判断
# ---------------------------------------------------------------------------
POS_ZH = {
    'n': '名词', 'n-adv': '名词·副词', 'n-suf': '名词·接尾', 'n-pref': '名词·接头',
    'n-t': '名词(他动)', 'num': '数词', 'pn': '代词', 'prt': '助词', 'conj': '接续词',
    'int': '感叹词', 'exp': '惯用句', 'adv': '副词', 'adv-to': '副词(と)',
    'aux': '助动词', 'aux-v': '助动词', 'aux-adj': '补助形容词', 'cop': '系词',
    'ctr': '量词', 'pref': '接头词', 'suf': '接尾词',
    'vs': 'サ变', 'vs-i': 'サ变', 'vs-s': 'サ变',
    'v1': '一段动词', 'v1-s': '一段动词', 'vk': 'カ变动词', 'vz': 'ズ变动词',
    'v-unspec': '动词', 'vi': '自动词', 'vt': '他动词',
    'adj-i': 'イ形容词', 'adj-ix': 'イ形容词', 'adj-na': 'ナ形容词',
    'adj-no': '连体词', 'adj-pn': '连体词', 'adj-f': '连体词',
    'adj-t': 'タル形容词', 'adj-kari': '形容词', 'adj-shiku': '形容词',
    'adj-nari': 'ナリ形容词', 'adj-ku': '形容词',
}
for _v in ('v5u', 'v5k', 'v5g', 'v5s', 'v5t', 'v5n', 'v5b', 'v5m', 'v5r',
           'v5r-i', 'v5aru', 'v5k-s', 'v5u-s', 'v5uru'):
    POS_ZH[_v] = '五段动词'

# 语域 / 领域 / 方言：JMdict 的 misc / fields / dialect 代码 → 中文。
# 与 .dsh/skills/jmdict-lookup/scripts/jmdict.py 的 TAG_ZH 同源；那边是技能脚本，
# 这边是 daily-lesson 进程，各自留一份，改词表时两边一起改。
TAG_ZH = {
    'uk': '通常写假名', 'abbr': '略语', 'arch': '古语', 'obs': '废语', 'obsc': '罕见',
    'rare': '罕见', 'sl': '俚语', 'vulg': '粗俗', 'col': '口语', 'fam': '亲昵',
    'pol': '敬语', 'hon': '尊敬语', 'hum': '谦让语', 'derog': '轻蔑', 'joc': '戏谑',
    'sens': '敏感', 'dated': '过时', 'male': '男性用语', 'female': '女性用语',
    'chn': '儿童用语', 'm-sl': '漫画俚语', 'net-sl': '网络俚语', 'euph': '委婉',
    'ik': '不规则假名', 'ok': '不规则汉字', 'sk': '罕用汉字', 'ateji': '当て字',
    'gikun': '义训', 'jukujikun': '熟字训', 'yoji': '四字熟语',
    'on-mim': '拟声拟态', 'proverb': '谚语', 'quote': '引用',
    'comp': '计算机', 'math': '数学', 'med': '医学', 'chem': '化学', 'biol': '生物',
    'phys': '物理', 'law': '法律', 'mil': '军事', 'econ': '经济', 'ling': '语言学',
    'music': '音乐', 'sports': '体育', 'sumo': '相扑', 'buddh': '佛教', 'shinto': '神道',
    'food': '食物', 'cloth': '服饰', 'archit': '建筑', 'geol': '地质', 'astron': '天文',
    'fin': '金融', 'bus': '商务', 'mahj': '麻将', 'shogi': '将棋', 'go': '围棋',
    'gramm': '语法', 'elec': '电力', 'mech': '机械', 'photo': '摄影', 'telec': '通信',
    'Christn': '基督教', 'myth': '神话', 'fict': '虚构', 'game': '游戏',
    'ksb': '关西', 'ktb': '九州', 'rkb': '琉球', 'thb': '东北', 'tsb': '土佐',
    'hob': '北陆', 'nag': '长野', 'kyb': '京都', 'osb': '大阪', 'kyu': '旧语',
}


def tag_zh(code):
    """词性 / 语域代码 → 中文；认不出的保留原码。"""
    code = (code or '').strip()
    if not code or code == '*':
        return ''
    return POS_ZH.get(code) or TAG_ZH.get(code) or code


# 粗类 → 讲义里显示的规范中文（自动纠词性时用）
FAMILY_ZH = {
    'noun': '名词', 'verb': '动词', 'adj-i': 'イ形容词', 'adj-na': 'ナ形容词',
    'adj-no': '连体词', 'adv': '副词', 'prt': '助词', 'conj': '接续词',
    'int': '感叹词', 'exp': '惯用句', 'aux': '助动词',
}
FUNCTION_FAMILIES = {'int', 'prt', 'conj', 'exp', 'aux'}

_VERB_CODES = {'v1', 'v1-s', 'vk', 'vz', 'vs', 'vs-i', 'vs-s', 'v-unspec'}


def pos_family(code):
    """JMdict 词性代码 → 粗类；认不出返回 ''。"""
    code = (code or '').strip()
    if not code:
        return ''
    if code in _VERB_CODES or code.startswith('v5') or code in ('vi', 'vt'):
        return 'verb'
    if code in ('adj-i', 'adj-ix', 'adj-kari', 'adj-shiku', 'adj-ku'):
        return 'adj-i'
    if code in ('adj-na', 'adj-t', 'adj-nari'):
        return 'adj-na'
    if code.startswith('adj-'):
        return 'adj-no'
    if code in ('n', 'n-adv', 'n-suf', 'n-pref', 'n-t', 'num', 'pn', 'ctr', 'pref', 'suf'):
        return 'noun'
    if code in ('adv', 'adv-to'):
        return 'adv'
    if code in ('prt', 'conj', 'int', 'exp'):
        return code
    if code in ('aux', 'aux-v', 'aux-adj', 'cop'):
        return 'aux'
    return ''


# 卡片词性（Anki 字段）→ 可接受的粗类集合。中文/英文/日文写法都认。
CARD_POS_RULES = (
    ('终助词', ('prt',)), ('終助詞', ('prt',)), ('助词', ('prt',)), ('助詞', ('prt',)),
    ('感叹词', ('int',)), ('感動詞', ('int',)), ('感嘆詞', ('int',)),
    ('接续词', ('conj',)), ('接続詞', ('conj',)),
    ('惯用句', ('exp',)), ('慣用句', ('exp',)), ('惯用语', ('exp',)),
    ('ナ形容词', ('adj-na',)), ('ナ形', ('adj-na',)), ('形容动词', ('adj-na',)),
    ('イ形容词', ('adj-i',)), ('イ形', ('adj-i',)),
    ('形容词', ('adj-i', 'adj-na')),
    ('他动词', ('verb', 'vt')), ('他動詞', ('verb', 'vt')), ('他动', ('verb', 'vt')),
    ('他動', ('verb', 'vt')),
    ('自动词', ('verb', 'vi')), ('自動詞', ('verb', 'vi')), ('自动', ('verb', 'vi')),
    ('自動', ('verb', 'vi')),
    ('动词', ('verb',)), ('動詞', ('verb',)), ('verb', ('verb',)),
    ('名词', ('noun',)), ('名詞', ('noun',)), ('noun', ('noun',)),
    ('副词', ('adv',)), ('副詞', ('adv',)), ('adv', ('adv',)),
    ('数词', ('noun',)), ('代词', ('noun',)), ('量词', ('noun',)),
    ('连体词', ('adj-no',)),
    ('名', ('noun',)), ('副', ('adv',)), ('形', ('adj-i', 'adj-na')),
)

CARD_TRANS_RULES = (
    ('他动词', 'vt'), ('他動詞', 'vt'), ('他动', 'vt'), ('他動', 'vt'),
    ('自动词', 'vi'), ('自動詞', 'vi'), ('自动', 'vi'), ('自動', 'vi'),
)


def card_families(pos_raw):
    """卡片词性字段 → 可接受粗类集合（空集 = 判断不了，不参与冲突检查）。"""
    text = (pos_raw or '').strip()
    if not text:
        return set()
    fams = set()
    low = text.lower()
    for token, mapped in CARD_POS_RULES:
        if token in text or token.lower() in low:
            fams.update(mapped)
    return fams


def card_transitivity(pos_raw):
    """卡片词性里的他动/自动标记；没有就返回 ''。"""
    text = (pos_raw or '').strip()
    for token, tag in CARD_TRANS_RULES:
        if token in text:
            return tag
    return ''


# ---------------------------------------------------------------------------
# 2. 假名归一（只用于比较，不用于显示）
# ---------------------------------------------------------------------------
_KATA = re.compile(r'[\u30a1-\u30f6]')
_TRIM = re.compile(r'[\s\u3000（）()\[\]【】「」『』・、。,.!?！？〜～~:：/／]')


def kata2hira(text):
    return _KATA.sub(lambda m: chr(ord(m.group(0)) - 0x60), text or '')


def kana_key(text):
    """平/片假名、空格、标点、浊音差异都不算区别。"""
    t = _TRIM.sub('', kata2hira(text))
    return t.replace('ぢ', 'じ').replace('づ', 'ず').replace('を', 'お').replace('ゔ', 'ぶ')


def is_kana_only(text):
    t = (text or '').strip()
    return bool(t) and not re.search(r'[^\u3040-\u309f\u30a0-\u30ffー]', t)


def clean_word(text):
    """去掉卡片词形里常见的修饰记号：`〜あまり`、`する[+名]` 之类。"""
    t = (text or '').strip()
    t = re.sub(r'\[[^\]]*\]', '', t)
    t = re.sub(r'^[〜～~\-—–]+', '', t).strip()
    return t


# ---------------------------------------------------------------------------
# 3. 词典封装（jmdictpy → 本模块的稳定形状）
# ---------------------------------------------------------------------------
class Lookup:
    """jmdictpy 的薄封装。不可用时 `available=False`，`lookup()` 恒返回 []。

    只用 jmdictpy 的 `lookup(word, limit=...)`；返回的条目被压成普通 dict，
    这样调用方与测试都不必依赖 jmdictpy 的对象模型。
    """

    def __init__(self, db_path=None):
        self.path = db_path or DEFAULT_DB
        self.jmd = None
        self.reason = ''
        # jmdictpy.config 在 import 时读一次数据目录；必须先设环境变量再 import，
        # 否则它会去 ~/.jmdictpy 建库（沙箱下直接 Access Denied）。
        os.environ['JMDICTPY_DATA_DIR'] = os.path.dirname(self.path)
        try:
            if PYLIBS not in sys.path:
                sys.path.append(PYLIBS)
            from jmdictpy import JMDict  # noqa: F401
        except ImportError:
            self.reason = ('jmdictpy 未安装（& $PY code\\oneshot\\install_workspace_wheels.py '
                           'jmdictpy）')
            return
        if not os.path.isfile(self.path):
            self.reason = '词典库不存在（%s）；先跑 jmdict-lookup 的 build' % self.path
            return
        try:
            from pathlib import Path
            self.jmd = JMDict(db_path=Path(self.path), auto_update=False)
        except Exception as e:  # noqa: BLE001  词典坏了也不能挡住讲义
            self.reason = '词典打不开：%s' % e
            self.jmd = None

    @property
    def available(self):
        return self.jmd is not None

    def lookup(self, word):
        if not self.jmd or not word:
            return []
        try:
            res = self.jmd.lookup(word, limit=12)
        except Exception:  # noqa: BLE001
            return []
        return [_entry(e) for e in (getattr(res, 'entries', None) or [])]

    def close(self):
        if self.jmd is not None:
            try:
                self.jmd.close()
            finally:
                self.jmd = None


def _entry(e):
    """jmdictpy Entry → 普通 dict（核验与「词典事实」共用同一份）。"""
    def kana(k):
        return {'text': k.text, 'common': bool(getattr(k, 'common', False))}

    kana_list = [kana(k) for k in (getattr(e, 'kana', None) or [])]
    kanji_list = [k.text for k in (getattr(e, 'kanji', None) or [])]
    return {
        'id': getattr(e, 'id', 0),
        # Entry 本身没有 is_common；有任一常用表记就算常用
        'common': bool(any(k['common'] for k in kana_list)
                       or any(bool(getattr(k, 'common', False))
                              for k in (getattr(e, 'kanji', None) or []))),
        'kanji': kanji_list,
        'kana': kana_list,
        'senses': [{
            'pos': list(getattr(s, 'part_of_speech', None) or []),
            'glosses': [g.text for g in (getattr(s, 'glosses', None) or [])
                        if getattr(g, 'lang', 'eng') in ('eng', 'en')],
            'misc': list(getattr(s, 'misc', None) or []),
            'fields': list(getattr(s, 'fields', None) or []),
            'dialect': list(getattr(s, 'dialect', None) or []),
            'info': list(getattr(s, 'info', None) or []),
            'applies_to_kanji': list(getattr(s, 'applies_to_kanji', None) or []),
            'applies_to_kana': list(getattr(s, 'applies_to_kana', None) or []),
        } for s in (getattr(e, 'senses', None) or [])],
    }


def match_entries(entries, word):
    """只留「词形真的对得上」的词条：汉字词比汉字表记，假名词比假名表记。"""
    w = kana_key(clean_word(word))
    if not w:
        return []
    kana_word = is_kana_only(clean_word(word))
    out = []
    for e in entries:
        if any(kana_key(k) == w for k in e['kanji']):
            out.append(e)
        elif kana_word and any(kana_key(k['text']) == w for k in e['kana']):
            out.append(e)
    return out


def entry_families(entry):
    fams = set()
    for s in entry['senses']:
        for code in s['pos']:
            f = pos_family(code)
            if f:
                fams.add(f)
    return fams


def candidate_readings(matched, limit=4):
    """词条的候选读音：**被越多同形词条共用**的读音越靠前，再按常用标记。

    `こ` 会命中 子/個/粉/娘… 共 8 条词条，只有「こ」是它们共同的读音，
    所以排第一；粉的「こな」只属于一条词条，排在后面（只是提示，不是建议）。
    """
    count, info, order = {}, {}, []
    for e in matched:
        for k in e['kana']:
            key = kana_key(k['text'])
            if not key:
                continue
            count[key] = count.get(key, 0) + 1
            if key not in info:
                info[key] = [k['text'], bool(k['common'])]
                order.append(key)
            elif k['common']:
                info[key][1] = True
    ranked = sorted(order, key=lambda k: (-count[k], not info[k][1], order.index(k)))
    return [info[k][0] for k in ranked][:limit]


def _gloss(entry, limit=2):
    for s in entry['senses']:
        if s['glosses']:
            return '；'.join(s['glosses'][:limit])
    return ''


# ---------------------------------------------------------------------------
# 3b. 词典事实（发给写讲解的模型；只保留讲词义用得上的部分）
# ---------------------------------------------------------------------------
def _trim(text, n):
    text = re.sub(r'\s+', ' ', (text or '')).strip()
    return text if len(text) <= n else text[:n - 1] + '…'


def _uniq(items):
    out = []
    for x in items:
        if x and x not in out:
            out.append(x)
    return out


def _headword(entry):
    """`上手【じょうず】` / `あっ`：主笔形 + 主读音（常用优先）。"""
    kanji = entry.get('kanji') or []
    kana = entry.get('kana') or []
    prim_kanji = kanji[0] if kanji else ''
    common = [k['text'] for k in kana if k.get('common')]
    prim_kana = (common or [k['text'] for k in kana])[:1]
    prim_kana = prim_kana[0] if prim_kana else ''
    if prim_kanji and prim_kana:
        return '%s【%s】' % (prim_kanji, prim_kana)
    return prim_kanji or prim_kana


def entry_facts(entry, max_senses=FACT_MAX_SENSES):
    """一个 JMdict 词条 → 紧凑事实：id / 表记 / 词性 / 义项（英文释义 + 语域 + 适用限制）。"""
    senses = []
    for s in entry.get('senses') or []:
        if len(senses) >= max_senses:
            break
        glosses = [_trim(g, FACT_GLOSS_CHARS) for g in (s.get('glosses') or [])[:FACT_MAX_GLOSSES]]
        pos = '・'.join(_uniq(tag_zh(c) for c in (s.get('pos') or [])))
        tags = _uniq(tag_zh(c) for c in
                     list(s.get('misc') or []) + list(s.get('fields') or [])
                     + list(s.get('dialect') or []))[:FACT_MAX_TAGS]
        applies = []
        if s.get('applies_to_kanji') not in (['*'], [], None):
            applies.append('笔形=' + '/'.join(s['applies_to_kanji']))
        if s.get('applies_to_kana') not in (['*'], [], None):
            applies.append('读音=' + '/'.join(s['applies_to_kana']))
        info = [x for x in (s.get('info') or []) if x][:1]
        item = {}
        if pos:
            item['pos'] = pos
        if glosses:
            item['glosses'] = glosses
        if tags:
            item['tags'] = tags
        if applies:
            item['applies'] = '；'.join(applies)
        if info:
            item['info'] = _trim(info[0], FACT_INFO_CHARS)
        if item:
            senses.append(item)
    pos_all = '／'.join(_uniq(tag_zh(c) for s in (entry.get('senses') or [])
                             for c in (s.get('pos') or [])))
    return {
        'id': entry.get('id'),
        'headword': _headword(entry),
        'common': bool(entry.get('common')),
        'pos': pos_all,
        'senses': senses,
    }


def card_facts(matched, word, reading=''):
    """匹配到的词条们 → 一张卡的事实块（多同形词条时并列，附一句 note）。

    取舍顺序：卡片读音能对上的词条 → 该读音被标常用的词条 → 整体常用的词条。
    `こ` 这种假名词会命中 8 条（海鼠 的罕见读法也是 こ），按这个序才轮得到 子/個。
    查不到 / 没有义项时返回 None（模型按卡片数据讲，不硬塞空事实）。
    """
    if not matched:
        return None
    want = kana_key(reading)

    def _rank(e):
        kana_hit_common = any(k.get('common') and kana_key(k['text']) == want
                              for k in (e.get('kana') or []))
        return (not kana_hit_common, not e.get('common'))

    preferred = [e for e in matched
                 if want and any(kana_key(k['text']) == want for k in e['kana'])]
    pool = sorted(preferred or matched, key=_rank)[:FACT_MAX_ENTRIES]
    entries, picked, total = [], [], 0
    for e in pool:
        facts = entry_facts(e, max_senses=max(0, min(FACT_MAX_SENSES,
                                                    FACT_MAX_SENSES_TOTAL - total)))
        if not facts['senses']:
            continue
        entries.append(facts)
        picked.append(e)
        total += len(facts['senses'])
    if not entries:
        return None
    cand = []
    for e in picked:
        for k in sorted(e.get('kana') or [], key=lambda k: not k.get('common')):
            # ヶ/ヵ 是量词后缀（一ヶ月），不是这个词本身的读音
            if k['text'] in ('ヶ', 'ヵ'):
                continue
            if k['text'] not in cand:
                cand.append(k['text'])
    out = {
        'readings': cand[:3],
        'common': any(e['common'] for e in entries),
        'entries': entries,
    }
    if len(matched) > 1:
        out['note'] = ('同形 %d 条词条：结合卡片自带例句判断这里取哪一条'
                       % len(matched))
    return out


def _issue(field, level, message, suggest=''):
    return {'field': field, 'level': level, 'message': message, 'suggest': suggest}


# ---------------------------------------------------------------------------
# 4. 单卡核验
# ---------------------------------------------------------------------------
def check_card(card, lk):
    """核验一张词汇卡。返回可 JSON 化的 dict（见文件头）。

    `lk` 只需要有 `.lookup(word)`；`.available` 可选（默认视为可用）。
    """
    word = clean_word(card.get('word') or '')
    reading = (card.get('reading') or '').strip()
    pos_raw = (card.get('pos') or '').strip()
    out = {
        'id': card.get('id'), 'word': word, 'reading': reading, 'pos': pos_raw,
        'entries': 0, 'readings': [], 'pos_zh': '', 'pos_fix': '',
        'issues': [], 'status': 'ok', 'facts': None,
    }
    if getattr(lk, 'available', True) is False:
        out['status'] = 'skip'
        return out
    if not word:
        out['status'] = 'skip'
        return out

    entries = lk.lookup(word) or []
    matched = match_entries(entries, word)
    out['entries'] = len(matched)
    out['readings'] = candidate_readings(matched)
    # 事实与核验同源：用的是上面这一次 lookup 的结果，不额外查库
    out['facts'] = card_facts(matched, word, reading)

    if not matched:
        out['issues'].append(_issue(
            'word', 'info',
            'JMdict 没有与词形「%s」对得上的词条（拟声词、口语词、专有名词常见，不一定是错）' % word))
        return _finish(out)

    # ---- 读音 ----
    valid = {kana_key(k['text']) for e in matched for k in e['kana']}
    if reading and kana_key(reading) not in valid:
        suggest = '／'.join(out['readings']) if out['readings'] else '（词典里没有读音候选）'
        if len(matched) > 1:
            msg = ('读音「%s」不是 JMdict 里「%s」的读音（同形 %d 个词条，靠前的读音：%s）'
                   % (reading, word, len(matched), suggest))
        else:
            msg = ('读音「%s」不是 JMdict 里「%s」的读音（词典读音：%s）'
                   % (reading, word, suggest))
        hint = _reading_headword_hint(lk, reading, word)
        if hint:
            msg += '；' + hint
        out['issues'].append(_issue('reading', 'error', msg, suggest=out['readings']))

    # ---- 词性 ----
    fams = card_families(pos_raw)
    entry_fams = set()
    for e in matched:
        entry_fams |= entry_families(e)
    if fams and entry_fams and not (fams & entry_fams):
        same_shape = len({tuple(sorted(entry_families(e))) for e in matched}) == 1
        # 只有「词形唯一对应一个词条」才敢自动改；假名词同形多词条（もん 同时是
        # 者/物/門…）必须留给人判断，否则会把句末助词 もん 改成「名词」。
        fix_family = _pick_family(entry_fams)
        if fix_family and (len(matched) == 1 or (same_shape and not is_kana_only(word))):
            out['pos_fix'] = FAMILY_ZH.get(fix_family, fix_family)
            out['pos_zh'] = out['pos_fix']
            out['issues'].append(_issue(
                'pos', 'warn',
                '卡片词性「%s」与 JMdict 冲突，词典给的是「%s」（id=%s）；讲义按词典校正'
                % (pos_raw, out['pos_zh'], matched[0]['id']),
                suggest=out['pos_zh']))
        else:
            out['pos_zh'] = '／'.join(sorted(FAMILY_ZH.get(f, f) for f in entry_fams))
            out['issues'].append(_issue(
                'pos', 'info',
                '卡片词性「%s」不在 JMdict 的词性里（词典：%s；同形词条 %d 条，不自动改）'
                % (pos_raw, out['pos_zh'] or '—', len(matched))))

    # ---- 他动词 / 自动词 ----
    trans = card_transitivity(pos_raw)
    if trans and 'verb' in fams:
        entry_trans = {c for e in matched for s in e['senses'] for c in s['pos']
                       if c in ('vi', 'vt')}
        if entry_trans and trans not in entry_trans:
            out['issues'].append(_issue(
                'pos', 'warn',
                '卡片标「%s」，但 JMdict 该词条只有%s用法（id=%s）'
                % ('他动词' if trans == 'vt' else '自动词',
                   '自动词' if entry_trans == {'vi'} else '他动词',
                   matched[0]['id'])))
    return _finish(out)


def _pick_family(entry_fams):
    """冲突时显示哪一个词典词性：功能词优先，其次实词。"""
    for f in ('int', 'prt', 'conj', 'exp', 'aux', 'adv', 'adj-i', 'adj-na', 'adj-no',
              'verb', 'noun'):
        if f in entry_fams:
            return f
    return ''


def _reading_headword_hint(lk, reading, word):
    """读音本身是不是另一个词条（`こ` 配 `あそこ` → あそこ 是「那里」）。"""
    try:
        hits = lk.lookup(reading) or []
    except Exception:  # noqa: BLE001
        return ''
    for e in hits:
        if kana_key(word) in {kana_key(k) for k in e['kanji']}:
            continue
        forms = '/'.join(e['kanji'][:2]) or '/'.join(k['text'] for k in e['kana'][:1])
        gloss = _gloss(e)
        if forms and gloss:
            return '读音「%s」在 JMdict 里是独立词条（%s）：%s' % (reading, forms, gloss)
    return ''


def _finish(out):
    best = 'ok'
    for iss in out['issues']:
        if SEVERITY[iss['level']] > SEVERITY.get(best, 0):
            best = iss['level']
    out['status'] = best
    return out


# ---------------------------------------------------------------------------
# 5. 整份 manifest
# ---------------------------------------------------------------------------
def check_manifest(manifest, lk, kinds=('vocab',)):
    """核验 manifest 里所有词汇卡（语法/例句卡不适用 JMdict 词条核对）。"""
    cards = [c for c in manifest.get('cards') or [] if c.get('kind') in kinds]
    rep = {
        'date': manifest.get('date'),
        'available': bool(getattr(lk, 'available', True)),
        'reason': getattr(lk, 'reason', '') or '',
        'total_cards': len(manifest.get('cards') or []),
        'checked': len(cards),
        'counts': {'error': 0, 'warn': 0, 'info': 0},
        'cards': {},
    }
    if not rep['available']:
        return rep
    for c in cards:
        res = check_card(c, lk)
        rep['cards'][str(c.get('id'))] = res
        for iss in res['issues']:
            if iss['level'] in rep['counts']:
                rep['counts'][iss['level']] += 1
    return rep


def issues_of(rep, level=None):
    """按严重度从高到低展开成 [(卡片结果, issue)]，方便打印或断言。"""
    rows = []
    for res in rep.get('cards', {}).values():
        for iss in res['issues']:
            if level and iss['level'] != level:
                continue
            rows.append((res, iss))
    rows.sort(key=lambda r: (-SEVERITY[r[1]['level']], str(r[0]['word'])))
    return rows


def format_report(rep, limit=14, title='JMdict 核验'):
    """给 stderr / CLI 读的紧凑报告（明细超长时只留前 limit 条）。"""
    if not rep.get('available'):
        return ['📖 JMdict 不可用：%s（本次跳过词形/读音/词性核验）' % (rep.get('reason') or '原因不明')]
    c = rep['counts']
    head = ('📖 %s：%d 张词汇卡 → %d 处硬错 · %d 处建议 · %d 条提示'
            % (title, rep['checked'], c['error'], c['warn'], c['info']))
    if not (c['error'] or c['warn'] or c['info']):
        return [head + '（词形/读音/词性全部对上）']
    lines = [head]
    shown = 0
    for res, iss in issues_of(rep):
        mark = {'error': '✗', 'warn': '⚠', 'info': 'ℹ'}[iss['level']]
        lines.append('  %s %s %s：%s' % (mark, FIELD_LABEL.get(iss['field'], iss['field']),
                                         res['word'], iss['message']))
        shown += 1
        if shown >= limit:
            rest = sum(len(r['issues']) for r in rep['cards'].values()) - shown
            if rest > 0:
                lines.append('  …… 另外 %d 条（明细见 dict_<日期>.json）' % rest)
            break
    return lines


# ---------------------------------------------------------------------------
# 6. 命令行：临时查一批卡 / 一批词
# ---------------------------------------------------------------------------
def _print_card(res):
    print('── %s（%s）' % (res['word'], res['reading'] or '—'))
    if not res['issues']:
        print('   OK：词典里有 %d 条同形词条' % res['entries'])
    for iss in res['issues']:
        print('   %s %s' % (LEVEL_LABEL.get(iss['level'], iss['level']),
                            iss['message']))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    lk = Lookup()
    if not lk.available:
        print('词典不可用：%s' % lk.reason, file=sys.stderr)
        return 3
    if not args:
        print('用法：python code\\common\\jmdict_check.py <词> [词…]')
        print('      python code\\common\\jmdict_check.py --cards <cards_*.json>')
        return 2
    if args[0] in ('--cards', '-c'):
        if len(args) < 2:
            print('缺 cards_*.json 路径', file=sys.stderr)
            return 2
        with open(args[1], encoding='utf-8') as fh:
            manifest = json.load(fh)
        rep = check_manifest(manifest, lk)
        print('\n'.join(format_report(rep, limit=999)))
        return 1 if rep['counts']['error'] else (2 if rep['counts']['warn'] else 0)
    for word in args:
        card = {'id': word, 'word': word, 'reading': '', 'pos': ''}
        res = check_card(card, lk)
        _print_card(res)
        print('   读音候选：%s' % ('／'.join(res['readings']) or '—'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
