# -*- coding: utf-8 -*-
"""两个本地模型讲义产出的**机械可查项**对比（不含主观判断）。

读 output/cmp/<模型>/*_out.json，对每张卡做能自动判定的检查：

    1. JSON 合法 + 字段齐全（one_line / core / examples，examples 正好 2 条）
    2. one_line ≤40 字、core ≤45 字（规范硬指标）
    3. 每条例句**是否含目标词**（规范硬指标，最常翻车的一条）
    4. 每条例句**与卡片自带例句的相似度**（规范：禁止复制卡片自带例句）
    5. 例句是否被注音/括号污染（规范：干净日语）
    6. 例句长度 15–30 字（规范建议区间，宽松判）

4 的相似度只是**信号**：同一个语法点必然共享「てはいけない」这种片段。
所以脚本会把最像的那条卡片例句一并打出来，供人工判断是「同型照搬」还是「不可避免的共享」。

用法：
    python code/analysis/cmp_local_llm.py [日期] [目录名]

``目录名`` 默认 ``cmp``，即读 ``output/<目录名>/<模型>/*_out.json``。
2026-10-20 清理时把 2026-10-08～12 的 ``output/cmp{,2..6}/`` 一起删了；
要再用本脚本，先把对应的 ``*_out.json`` 与 ``mech_<日期>.json`` 重新生成到该路径下。
"""
import difflib
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, 'code', 'common'))

import anki_api as AK  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

# 卡片自带的例句字段（按 note 类型）
SENT_FIELDS = (
    ['SentKanji%d' % i for i in range(1, 5)]          # eggrolls-JLPT10k
    + ['Sentence']                                     # Japanese Vocabulary
    + ['Sentence%d' % i for i in range(1, 12)]         # どんなときどう使う
)
WORD_FIELDS = ['VocabKanji', 'Word', 'Card']
READ_FIELDS = ['VocabFurigana', 'Transliteration']
POS_FIELDS = ['VocabPoS', 'Part of Speech']
DEF_FIELDS = ['VocabDefSC', 'Meaning', 'MeaningCN']

KANJI = re.compile(r'[\u4e00-\u9fff々]')

GRAMMAR_MODEL = 'どんなときどう使う日本語表現文型Note'

_PUNCT = re.compile(r'[\s。、，,．.！!？?「」『』（）()\[\]<>〈〉・…ー〜～:：;；]+')


def strip_punct(s):
    return _PUNCT.sub('', s or '')


def sim(a, b):
    """去标点后的相似度。"""
    a, b = strip_punct(a), strip_punct(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def contains_word(jp, word, reading=''):
    """例句里是否出现目标词（含动词/形容词活用形）。"""
    hay = strip_punct(jp)
    cores = set()
    for raw in (word, reading):
        if not raw:
            continue
        cores.add(strip_punct(raw))
        c = word_core(raw)
        if c:
            cores.add(c)
    for c in cores:
        if c and c in hay:
            return True
    # 活用形：词干 + 假名（許す -> 許さない／連れる -> 連れて）
    for c in cores:
        if len(c) >= 2:
            stem = c[:-1]
            for m in re.finditer(re.escape(stem), hay):
                nxt = hay[m.end():m.end() + 1]
                if nxt and not KANJI.match(nxt):
                    return True
    return False


def word_core(raw):
    """从「前〜」「より(副)」「〜さ」里剥出核心词形。"""
    core = re.sub(r'[（(].*?[)）]', '', raw or '')
    return core.replace('〜', '').replace('～', '').strip()


def suspect_reason(jp, word, pos):
    """粗判目标词是否只是更长词的一部分（子串误用的典型形态）。

    能抓到：責任**者**（前面粘汉字）、**まあ****まあ**（叠词）、**日**々。
    抓不到读音歧义（上=じょう/かみ/うえ），那只能人工看。
    接尾/接頭辞相邻粘汉字是正常用法，不报。
    """
    core = word_core(word)
    if not core:
        return None
    hay = strip_punct(jp)
    is_suffix = '接尾' in (pos or '') or (word or '').startswith('〜')
    is_prefix = '接頭' in (pos or '') or (word or '').endswith('〜')
    i = hay.find(core)
    if i < 0:
        return None
    before = hay[i - 1] if i > 0 else ''
    rest = hay[i + len(core):]
    after = rest[:1]
    if rest.startswith(core):                      # まあ -> まあまあ
        return '叠词：%s%s（疑为另一个词）' % (core, rest[:len(core)])
    if after == '々':                              # 日 -> 日々
        return '叠字：%s々（读音多半不是 %s）' % (core, core)
    if KANJI.match(core[:1]) and len(core) == 1:
        # 只对**单个汉字**的词报粘字：上質/上級 也算正确用法，所以这只是"待人工确认"
        if before and KANJI.match(before) and not is_suffix:
            return '前粘汉字：%s%s（待确认是否同一词）' % (before, core)
        if after and KANJI.match(after) and not is_prefix:
            return '后粘汉字：%s%s（待确认是否同一词）' % (core, after)
    return None


def check_example(jp, word, reading, card_sents, pos=''):
    """返回单条例句的检查结果。"""
    best = 0.0
    best_sent = ''
    for s in card_sents:
        r = sim(jp, s)
        if r > best:
            best, best_sent = r, s
    n = len(strip_punct(jp))
    return {
        'has_word': contains_word(jp, word, reading),
        'dup_sim': round(best, 3),
        'dup_best': best_sent,
        'suspect': suspect_reason(jp, word, pos),
        'dirty': bool(re.search(r'<ruby|\[|\]|<|>', jp)),
        'len': n,
        'len_ok': 15 <= n <= 30,
    }


def load_model_dir(path):
    out = {}
    if not os.path.isdir(path):
        return out
    for fn in sorted(os.listdir(path)):
        if not fn.endswith('_out.json'):
            continue
        with open(os.path.join(path, fn), encoding='utf-8') as f:
            data = json.load(f)
        no = int(fn[:2])
        out[no] = data
    return out


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else '2026-10-08'
    base = sys.argv[2] if len(sys.argv) > 2 else 'cmp'
    split_p = os.path.join(_ROOT, 'output', 'daily', 'lessons', 'split_%s.json' % date)
    with open(split_p, encoding='utf-8') as f:
        split = json.load(f)

    nids = [r['ids'][0] for r in split['reqs']]
    notes = AK.notes_map(nids)

    dirs = {}
    for name in ('qwen', 'gemma'):
        d = os.path.join(_ROOT, 'output', base, name)
        dirs[name] = load_model_dir(d)
    labels = {'qwen': 'Qwen3.8-27B', 'gemma': 'Gemma-4-31B'}

    rows = []
    for req in split['reqs']:
        no, nid, word = req['no'], req['ids'][0], req['words'][0]
        note = notes.get(nid) or {}
        f = note.get('fields') or {}
        kind = 'grammar' if note.get('modelName') == GRAMMAR_MODEL else 'vocab'
        reading = AK.field(note, READ_FIELDS[0]) or AK.field(note, READ_FIELDS[1]) or ''
        pos = ''
        for k in POS_FIELDS:
            if AK.field(note, k):
                pos = AK.field(note, k)
                break
        meaning = ''
        for k in DEF_FIELDS:
            if AK.field(note, k):
                meaning = AK.field(note, k)
                break
        card_sents = [AK.field(note, k) for k in SENT_FIELDS if AK.field(note, k)]
        card_sents = [strip_punct(s) for s in card_sents if s]

        row = {'no': no, 'word': word, 'kind': kind, 'meaning': meaning,
               'reading': reading, 'pos': pos, 'card_sents': card_sents, 'models': {}}
        for name, store in dirs.items():
            data = store.get(no)
            res = {'present': data is not None, 'issues': [], 'warns': []}
            if data is None:
                res['issues'].append('缺产出')
                row['models'][name] = res
                continue
            entries = data.get('entries') or {}
            ent = entries.get(str(nid))
            if not ent:
                res['issues'].append('entries 里没有这张卡')
                row['models'][name] = res
                continue
            teach = ent.get('teach') or {}
            if kind == 'vocab':
                ol, co = teach.get('one_line', ''), teach.get('core', '')
                exs = teach.get('examples') or []
                res['one_line'] = ol
                res['core'] = co
                res['one_line_len'] = len(ol)
                res['core_len'] = len(co)
                if not ol:
                    res['issues'].append('缺 one_line')
                elif len(ol) > 40:
                    res['issues'].append('one_line 超 40 字 (%d)' % len(ol))
                if not co:
                    res['issues'].append('缺 core')
                elif len(co) > 45:
                    res['issues'].append('core 超 45 字 (%d)' % len(co))
                if len(exs) != 2:
                    res['issues'].append('examples %d 条（应为 2）' % len(exs))
                res['ex'] = []
                for e in exs:
                    c = check_example(e.get('jp', ''), word, reading, card_sents, pos)
                    c['jp'] = e.get('jp', '')
                    c['cn'] = e.get('cn', '')
                    res['ex'].append(c)
                    if not c['has_word']:
                        res['issues'].append('例句不含目标词: %s' % c['jp'])
                    if c['dirty']:
                        res['issues'].append('例句有注音/括号: %s' % c['jp'])
                    if c['dup_sim'] >= 0.6:
                        res['issues'].append('例句像卡片例句(%.2f): %s' % (c['dup_sim'], c['jp']))
                    if c['suspect']:
                        res.setdefault('warns', []).append('%s ← %s' % (c['jp'], c['suspect']))
                    cn = (e.get('cn') or '').strip()
                    if not cn:
                        res['issues'].append('例句缺中文翻译: %s' % c['jp'])
                    elif not re.search(r'[\u4e00-\u9fff]', cn):
                        res['issues'].append('中文翻译不含汉字(疑为脏数据): %r ← %s' % (cn, c['jp']))
            else:
                res['one_line'] = teach.get('one_line', '')
                res['structure'] = teach.get('structure', '')
                res['uses'] = teach.get('uses') or []
                res['contrast'] = teach.get('contrast', '')
                res['pitfall'] = teach.get('pitfall', '')
                res['ex'] = teach.get('examples') or []
                for k in ('one_line', 'structure', 'core', 'uses', 'examples',
                          'contrast', 'pitfall'):
                    if not teach.get(k):
                        res['issues'].append('语法卡缺 %s' % k)
                for e in res['ex']:
                    if not contains_word(e.get('jp', ''), word, reading):
                        res['issues'].append('例句不含目标词: %s' % e.get('jp', ''))
            row['models'][name] = res
        rows.append(row)

    # ---- 汇总 ----
    print('=' * 100)
    print('机械校验：%s（%d 张卡）' % (date, len(rows)))
    print('=' * 100)

    for name in ('qwen', 'gemma'):
        lab = labels[name]
        bad = [r for r in rows if r['models'][name]['issues']]
        print('\n### %s —— %d/%d 张卡有机械问题' % (lab, len(bad), len(rows)))
        if not bad:
            print('    （无）')
        for r in bad:
            print('  [%02d] %s（%s）' % (r['no'], r['word'], r['kind']))
            for i in r['models'][name]['issues']:
                print('        - %s' % i)

    print('\n' + '=' * 100)
    print('【待人工确认】目标词粘字 / 叠词（不是硬性违规，可能是正确用法）')
    print('=' * 100)
    for name in ('qwen', 'gemma'):
        lab = labels[name]
        print('\n### %s' % lab)
        any_w = False
        for r in rows:
            w = r['models'][name].get('warns') or []
            if w:
                any_w = True
                print('  [%02d] %s：%s' % (r['no'], r['word'], ' ; '.join(w)))
        if not any_w:
            print('    （无）')

    print('\n' + '=' * 100)
    print('逐卡明细：例句相似度 / 长度 / 含词')
    print('=' * 100)
    hdr = '%-4s %-8s %-6s | %-28s | %-28s'
    print(hdr % ('no', 'word', 'kind', 'Qwen3.8-27B', 'Gemma-4-31B'))
    print('-' * 100)
    for r in rows:
        cells = []
        for name in ('qwen', 'gemma'):
            m = r['models'][name]
            if not m.get('ex'):
                cells.append('--')
                continue
            parts = []
            for e in m['ex'][:2]:
                if 'has_word' in e:
                    parts.append('%s L%d sim%.2f' % ('ok ' if e['has_word'] else 'MISS',
                                                     e['len'], e['dup_sim']))
                else:
                    parts.append('ex')
            cells.append(' | '.join(parts))
        print('%-4s %-8s %-6s | %-28s | %-28s'
              % (r['no'], r['word'][:8], r['kind'][:6], cells[0][:28], cells[1][:28]))

    # 存一份全量 JSON 供后续人工评分
    dump = os.path.join(_ROOT, 'output', base, 'mech_%s.json' % date)
    with open(dump, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print('\n明细已存：%s' % dump)


if __name__ == '__main__':
    main()
