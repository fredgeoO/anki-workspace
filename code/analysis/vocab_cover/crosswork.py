# -*- coding: utf-8 -*-
"""★ 跨作品通用性判定：把新词分成「值得挖 / 看情况 / 别挖」。

为什么需要
----------
``newwords.py`` 只看「卡组里有没有这张卡」，于是宫廷/奇幻这类**题材通用词**
（殿下・令嬢・公爵・王位・離宮…）和平家物语式的专有名词混在一起，看着都像噪声。
但换个同题材作品还会碰到它们 —— 值得做卡。真正该排除的是：

* **作品独有概念**（例：HUNTER×HUNTER 的「念能力」）—— 换作品就没用了；
* **语法性功能词**（こと・もの・や・みたい）—— 不是词汇量问题；
* **拟声/感叹碎片**（フッ・チッ・ハァハァ）—— 属听力反应，Sudachi 常切成副詞躲过 interj 档；
* **人名/造语**（ユフィリア・レイニ）。

判据（按优先级，全部可配置）
----------------------------
===== ============================================ ==========================
档     含义                                          默认
===== ============================================ ==========================
work   作品专有词表 ``work_concepts.json`` 命中        ❌ 不做卡
function 不挖词表 ``not_vocab.json``（语法词/拟声）命中  ❌ 不做卡
genre  题材通用词表 ``genre_lexicon.json`` 命中        ✅ 挖（带题材名）
common Jiten 排名 ≤ ``common_max``（默认 5000）        ✅ 挖（跨作品高频）
rare   Jiten 有排名但很深（> common_max）              ✅ 挖（低频但通用）
unlisted Jiten 没有排名                                ❓ 看情况
===== ============================================ ==========================

两条附带标记：

* ``suspect_name``：**全片假名** 且（无排名 或 排名 > ``name_rank``）—— 多半是人名/造语/拟声，
  默认不挖（ユフィリア #无 ・レイニ #134561 ・マゼンタ #69633 都落在这里）。
* ``mine``：上面全部权衡后的结论 —— ``count >= 1`` 且 cross ∈ {common, genre, rare}
  且不是 work / 不挖词表 / 疑似人名。``newwords.py --mine-only`` 就用它。

为什么 Jiten 排名能当「跨作品」证据
-----------------------------------
Jiten Anime 词表建在 3,762 部动画字幕上，**按「出现在多少部不同作品里」排**，
不按单部里的重复次数排（见 docs/architecture.md §5）。所以「表里有这个排名」本身就意味着
这个词在别的作品里也出现过；排名深浅只反映广度。宫廷/奇幻题材词普遍落在
8000~60000 名 —— 通用，但不属于日常高频，这正是 ``genre`` + ``rare`` 两档要留下的东西。

数据文件（都可手改，不用改代码）
--------------------------------
* ``data/vocab_cover/genre_lexicon.json``  题材通用词（宫廷/奇幻/军事/神话/学园・社会）
* ``data/vocab_cover/work_concepts.json``  作品专有概念/人名
* ``data/vocab_cover/not_vocab.json``      语法性功能词 + 拟声/感叹
"""
from __future__ import annotations

import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _deps import WSP  # noqa: E402
from _norm import norm_word  # noqa: E402

VC_DATA = os.path.join(WSP.DATA, 'vocab_cover')
GENRE_JSON = os.path.join(VC_DATA, 'genre_lexicon.json')
WORK_JSON = os.path.join(VC_DATA, 'work_concepts.json')
NOT_VOCAB_JSON = os.path.join(VC_DATA, 'not_vocab.json')

CROSS_ORDER = ('common', 'genre', 'rare', 'unlisted', 'inflection', 'function',
               'ignored', 'work')
CROSS_LABELS = {
    'common': '通用',
    'genre': '题材',
    'rare': '低频通用',
    'unlisted': '未收录',
    'inflection': '活用形碎片',
    'function': '功能词/拟声',
    'ignored': '已判·不挖',
    'work': '作品专有',
}

KATAKANA_RE = re.compile(r'^[\u30a1-\u30fa\u30fc\u30fd\u30feー]+$')


def _load_json(path: str) -> dict:
    """读 JSON；文件不在或坏了就返回空 dict（功能自动降级，绝不让工具挂掉）。"""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as exc:                                  # noqa: BLE001
        print(f'[提示] 词表 {os.path.basename(path)} 读不了（{exc}），跳过。', file=sys.stderr)
        return {}


class CrossWork:
    """跨作品通用性判定器。构造后就固定，``classify()`` 逐词调用。"""

    def __init__(self, genre_path: str = GENRE_JSON, work_path: str = WORK_JSON,
                 not_vocab_path: str = NOT_VOCAB_JSON, common_max: int = 5000,
                 name_rank: int = 20000, enabled: bool = True):
        self.enabled = enabled
        self.common_max = common_max
        self.name_rank = name_rank
        self.genre_words = {}       # 归一词形 -> 题材名
        self.genre_kanji = []       # [(汉字, 题材名)]
        self.genre_cats = []
        self.not_vocab = {}         # 归一词形 -> grammar / onomatopoeia
        self.work_scopes = []       # [(作品键, {归一词形: 原因})]
        if enabled:
            self._load_genre(genre_path)
            self._load_not_vocab(not_vocab_path)
            self._load_work(work_path)

    # -- 装载 ---------------------------------------------------------------
    def _load_genre(self, path: str) -> None:
        for cat, spec in (_load_json(path).get('categories') or {}).items():
            self.genre_cats.append(cat)
            for k in spec.get('kanji') or []:
                self.genre_kanji.append((k, cat))
            for w in spec.get('words') or []:
                key = norm_word(w)
                if key:
                    self.genre_words.setdefault(key, cat)

    def _load_not_vocab(self, path: str) -> None:
        data = _load_json(path)
        for kind in ('grammar', 'onomatopoeia', 'ignored'):
            for w in data.get(kind) or []:
                key = norm_word(w)
                if key:
                    self.not_vocab.setdefault(key, kind)

    def _load_work(self, path: str) -> None:
        for work, mapping in (_load_json(path).get('works') or {}).items():
            norm = {}
            for w, why in (mapping or {}).items():
                key = norm_word(w)
                if key:
                    norm[key] = why or '作品专有'
            if norm:
                self.work_scopes.append((work, norm))

    # -- 判定 ---------------------------------------------------------------
    def scope_for(self, label: str) -> dict:
        """来源路径 -> 该作品的黑名单（作品名出现在路径里就算命中）。"""
        if not label:
            return {}
        merged = {}
        for work, mapping in self.work_scopes:
            if work and work in label:
                merged.update(mapping)
        return merged

    def classify(self, key: str, surface: str, lemma: str, jiten_rank, scope: dict,
                 hints: dict = None) -> dict:
        """-> {cross, cross_note, not_vocab, suspect_name, mine, rank_from_lemma}

        ``hints``（由 ``newwords.finalize`` 给）描述「原形」在卡组/词频表里的情况，
        用来处理 Sudachi A 单位切出来的活用形（放っ / 繰り / 語ら…）：

        * 原形**已有卡** → ``inflection``（碎片，不用管：原形在队列里）
        * 原形没卡但**词频表里有** → 按原形的排名判档（值得挖的是原形，不是碎片）
        * 原形两处都没有 → 仍然 ``unlisted``（交给人/代理判）
        """
        hints = hints or {}
        forms = [f for f in (key, surface, lemma) if f]
        normed = [norm_word(f) for f in forms]
        katakana_only = bool(forms) and all(KATAKANA_RE.match(f) for f in forms)

        # 1. 作品专有
        for f in normed:
            if f in scope:
                return self._result('work', scope[f], '', katakana_only, False)
        # 2. 不挖词（语法性功能词 / 拟声 / 已判不挖）
        for f in normed:
            kind = self.not_vocab.get(f)
            if kind:
                note = {'grammar': '语法性功能词',
                        'onomatopoeia': '拟声/感叹',
                        'ignored': '已判·不挖（切分碎片/生造词）'}[kind]
                return self._result('ignored' if kind == 'ignored' else 'function',
                                    note, kind, katakana_only, False)
        # 3. 题材通用词
        cat = self._genre_of(normed, forms)
        if cat:
            return self._result('genre', cat, '', katakana_only, True)
        # 4. 活用形：原形已有卡（学过或没学过都算有卡）→ 碎片，不用管
        if (not jiten_rank and hints.get('lemma_key')
                and hints.get('lemma_in_deck')):
            return self._result('inflection', f"活用形（原形 {lemma} 已有卡）",
                                '', katakana_only, False)
        # 5. 原形没卡但词频表里有 → 按原形的排名判档
        from_lemma = False
        if not jiten_rank and hints.get('lemma_key') and hints.get('lemma_rank'):
            jiten_rank = hints['lemma_rank']
            from_lemma = True
        # 6. Jiten 排名
        if jiten_rank:
            cross = 'common' if jiten_rank <= self.common_max else 'rare'
            suspect = katakana_only and jiten_rank > self.name_rank
            res = self._result(cross, '疑似人名/造语' if suspect else '',
                               '', katakana_only, not suspect)
            res['rank_from_lemma'] = from_lemma
            return res
        # 7. 没排名
        suspect = katakana_only
        return self._result('unlisted', '疑似人名/造语' if suspect else '词典/词频表都没收',
                            '', katakana_only, False)

    def _genre_of(self, normed: list, forms: list) -> str:
        for f in normed:
            cat = self.genre_words.get(f)
            if cat:
                return cat
        for f in forms:
            for kanji, cat in self.genre_kanji:
                if kanji in f:
                    return cat
        return ''

    def _result(self, cross: str, note: str, not_vocab: str,
                katakana_only: bool, mine: bool) -> dict:
        suspect = bool(katakana_only and cross in ('rare', 'unlisted') and not mine)
        return {'cross': cross, 'cross_note': note, 'not_vocab': not_vocab,
                'suspect_name': suspect or (note == '疑似人名/造语'),
                'mine': bool(mine), 'rank_from_lemma': False}

    # -- 渲染 ---------------------------------------------------------------
    @staticmethod
    def label(w: dict) -> str:
        """人类可读的一格：专有 / 功能词 / 拟声 / 活用形 / 题材:宫廷 / 通用 / 低频通用 / 未收录。"""
        if w.get('not_vocab') == 'grammar':
            return '功能词'
        if w.get('not_vocab') == 'onomatopoeia':
            return '拟声'
        if w.get('not_vocab') == 'ignored':
            return '已判不挖'
        cross = w.get('cross')
        if cross == 'work':
            return '专有'
        if cross == 'genre':
            return f"题材:{w.get('cross_note') or '?'}"
        if cross == 'inflection':
            return '活用形'
        if w.get('suspect_name'):
            return '疑似人名'
        return CROSS_LABELS.get(cross, '—')

    def counts(self, words: list) -> dict:
        """-> {'挖': n, '通用': n, '题材': n, ...}，给汇总行用。"""
        out = {}
        for w in words:
            lab = self.label(w)
            out[lab] = out.get(lab, 0) + 1
        out['可挖'] = sum(1 for w in words if w.get('mine'))
        return out
