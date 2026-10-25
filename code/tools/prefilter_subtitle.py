#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""字幕筛选 · 机械预筛（把「看得见的错误」先判掉，只把灰区留给模型/人）

背景
----
`filter_subtitle.py` 的 keep/drop 是**不可逆**的：判弃的句子永远不会变成卡，
所以判据要「宁可放过、不可错杀」；但 1110 块全交模型逐条判既贵又慢，
而其中一大半是（戦う音）／うん／ハッ 这种确定性噪声。

做法（两遍，都是只读）
----
1) **规则层**（确定性、零风险）：音效/舞台指示、纯语气词/感叹、
   纯应答（はい／いいえ／うん…）、以及**残句且无任何学习点**者 → DROP。
2) **判据层**：拿 `pipeline.rebuild_known_index()` 的「已收录词汇全表」
   （考级词汇 + core6000，含活用形/假名↔片假名变体）做最长匹配，
   加上语法表 + 惯用表 + 长句/连体修饰规则 → 命中即为 KEEP 信号。

输出把每块分成五类，只有 GRAY 需要模型：
    NOISE      规则判弃（音效/语气词/应答）        —— 直接 DROP
    FRAG       短残句（<10 字）且无强信号          —— 直接 DROP
    NOVAL      无强信号、也不短                    —— 直接 DROP（几乎无可学）
    KEEP_SAFE  命中强信号、句子完整                —— 直接 KEEP（抽检）
    GRAY       命中强信号但句子可疑，或无强信号但不短 —— 交模型判

「强信号」只有四条（宁可漏、不可错杀）：
    W  **未收录词**（不在考级词汇+core6000 的任何写法里；长度≥2；排除纯假名寒暄碎片）
    G  命中 N3/N2/N1 或 ≥3 字句型（「ている/こと/という」这类 N5 常驻项不算）
    I  命中惯用搭配表
    L  长句（≥26 字）且同时含未收录词或强语法

用法
----
  python prefilter_subtitle.py index                      # 建/刷新已知词汇索引缓存
  python prefilter_subtitle.py scan  --src "<srt>" --ep <集名>
  python prefilter_subtitle.py report --ep <集名>          # 人工看判据分布与样例
  python prefilter_subtitle.py gray  --ep <集名>           # 导出灰区（分批发本地模型）
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'common'))
sys.path.insert(0, os.path.join(_HERE, '..', 'execution'))
import paths as WSP      # noqa: E402
import textio            # noqa: E402  UTF-8 stdio 唯一入口
import pipeline as P     # noqa: E402  判据/词表的唯一来源

INDEX = os.path.join(WSP.DATA, 'evidence', 'subtitle_index.json')
KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
# 字幕注音：漢字（かな）
ANN = re.compile(r'([\u4e00-\u9fff\u3005]+)[（(][\u3041-\u3096\u30a0-\u30ff\u30fc]+[）)]')
PARENS = re.compile(r'[（(][^）)]*[）)]')
BRACE = re.compile(r'\{[^}]*\}')

# 纯应答 / 寒暄（整块就这些）
REPLY = {'はい', 'いいえ', 'うん', 'ううん', 'ええ', 'いや', 'そう', 'なるほど', 'たしかに',
         '確かに', 'まあ', 'よし', 'では', 'じゃあ', 'はいはい', 'おう', 'ああ', 'ん'}
# 残句尾巴
FRAG_TAIL = ('て', 'で', 'が', 'を', 'に', 'は', 'の', 'と', 'も', 'けど', 'のに', 'って',
             'から', 'ので', 'たり', 'ながら', 'れば', 'し', 'や', 'へ')


def strip_ann(t):
    return ANN.sub(r'\1', t)


def body(t):
    """句子本体：去注音、去括号标记、去 {\an8}／〓／♪ 之类、去空白与标点。"""
    s = BRACE.sub('', t)
    s = s.replace('〓', ' ').replace('♪', ' ').replace('《', ' ').replace('》', ' ')
    s = strip_ann(s)
    s = PARENS.sub('', s)
    return s


def core(t):
    """判据用的紧致文本（去标点空白，保留汉字假名）。"""
    return P.PUNCT.sub('', body(t))


def is_frag(t):
    s = body(t)
    tight = re.sub(r'[\s…。！？!?、]', '', s)
    if '…' in s or '‥' in s:
        return True
    return bool(tight) and tight.endswith(FRAG_TAIL)


def looks_noise(t):
    """确定性噪声：音效/舞台指示、纯语气词、纯应答。返回理由或 ''。"""
    raw = BRACE.sub('', t).strip()
    if not raw:
        return '音效/舞台指示'
    # 整块只有一个括号内容
    stripped = PARENS.sub('', strip_ann(raw)).strip(' 　♪…‥・、。！？!?')
    if not stripped:
        return '音效/舞台指示'
    if '♪' in raw and len(KANJI.findall(stripped)) == 0 and len(stripped) <= 4:
        return '音效/舞台指示'
    flat = re.sub(r'[\s…‥、。！？!?っー～♪・]', '', stripped)
    if not flat:
        return '音效/舞台指示'
    if KANJI.search(flat):
        return ''
    if flat in REPLY and len(flat) <= 6:
        return '纯应答/寒暄'
    if len(flat) <= 5:
        return '纯语气词/感叹'
    if len(flat) <= 8 and re.match(r'^(あ|う|え|お|は|ふ|へ|ん|や|わ|よ|こ|そ|ど|な|ま|い)+$', flat):
        return '纯语气词/感叹'
    # 无汉字、无实词，整块是语气词/笑声/喊叫的堆叠（`ぬうううおお！んっ？`、`ハハッ。は？はあ？`）
    # 只吃**很短**的块（≤14 字），且剥掉语气词后几乎不剩什么
    if len(flat) <= 14 and KANA_ONLY.match(flat) and len(_strip_interj(flat)) <= 2:
        return '纯语气词/感叹'
    return ''


def _strip_interj(s):
    """剥掉语气词/笑声常用字，看还剩什么。"""
    return re.sub(r'[あいうえおはひふへほんやゆよわをかきくけこさしすせそたちつてと'
                  r'なにぬねのまみむめもらりるれろがぎぐげござじずぜぞだぢづでど'
                  r'ばびぶべぼぱぴぷぺぽっーゅょゃ]', '', s)


COMMON_PATH = os.path.join(WSP.DATA, 'evidence', 'subtitle_common.json')
COMMON = set()


def _load_common():
    if os.path.exists(COMMON_PATH):
        with open(COMMON_PATH, encoding='utf-8') as f:
            return set(json.load(f)['common'])
    return set()


def load_index():
    if not os.path.exists(INDEX):
        raise SystemExit('缺少已知词汇索引 %s，先跑：prefilter_subtitle.py index' % INDEX)
    with open(INDEX, encoding='utf-8') as f:
        d = json.load(f)
    return d['canonical'], d['variant2c']


_PAT = {'re': None, 'keys': None}


def build_matcher(variant2c):
    """把全部写法编译成**一条正则**（长的在前 → 同一位置优先匹配最长写法）。"""
    keys = sorted(variant2c, key=len, reverse=True)
    try:
        _PAT['re'] = re.compile('|'.join(re.escape(k) for k in keys))
    except (re.error, OverflowError, MemoryError) as e:   # 回退：逐个 find
        print('  正则编译失败（%s），回退逐词 find' % e)
        _PAT['re'] = None
        _PAT['keys'] = keys
    return _PAT['re']


def match_words(tight, variant2c, canonical):
    """最长匹配扫出句中的**已收录词**，剩下的连续汉字/假名片段即「疑似未收录」。"""
    covered = [False] * len(tight)
    hits = []
    pat = _PAT['re']
    if pat is not None:
        for m in pat.finditer(tight):
            if any(covered[m.start():m.end()]):
                continue
            for j in range(m.start(), m.end()):
                covered[j] = True
            hits.append(canonical.get(variant2c[m.group(0)], m.group(0)))
    else:
        for k in _PAT['keys']:
            start = 0
            while True:
                i = tight.find(k, start)
                if i < 0:
                    break
                if not any(covered[i:i + len(k)]):
                    for j in range(i, i + len(k)):
                        covered[j] = True
                    hits.append(canonical.get(variant2c[k], k))
                start = i + 1
    resid = []
    cur = ''
    for ch, cov in zip(tight, covered):
        if not cov and (KANJI.match(ch) or KANA.match(ch)):
            cur += ch
        else:
            if cur:
                resid.append(cur)
            cur = ''
    if cur:
        resid.append(cur)
    return hits, resid


def cmd_index(_a):
    print('拉取「已收录词汇」全表…')
    canonical, variant2c = P.rebuild_known_index()
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, 'w', encoding='utf-8') as f:
        json.dump({'canonical': canonical, 'variant2c': variant2c}, f, ensure_ascii=False)
    print('词典形 %d 个 / 可识别写法 %d 个 → %s' % (len(canonical), len(variant2c), INDEX))


def useful_resid(resid):
    """未收录残差里真正像「词」的那些。

    抠掉三类已知的机械噪声，否则 HIT 会泛滥成 74%：
      1. 首尾功能词/语尾（`めに`、`から`、`もっ`、`ていうか`、`なんで別の`）——
         剥掉后再看剩下什么，剩下的短于 2 字就整条丢弃；
      2. 纯假名 1–2 字碎片；
      3. 单独的人名标记（`嬢`、`殿下`、`姫様`）—— 专有名词不算学习点。
    """
    out = []
    for r in resid:
        c = _trim_wrap(r)
        if len(c) < 2:
            continue
        if not KANJI.search(c):
            if len(c) < 3 or not _is_content_kana(c):
                continue
        if c in NAME_MARK or (len(c) <= 3 and any(c in m for m in NAME_MARK)):
            continue
        out.append(c)
    return list(dict.fromkeys(out))


def _trim_wrap(w):
    """反复剥掉首尾的助词/语尾/长音促音，露出里面可能的词。"""
    prev = None
    while prev != w:
        prev = w
        for pat, rep in WRAP:
            w = re.sub(pat, rep, w)
    return w.strip('ー〜～っッん')


# 首尾功能词（剥掉后剩下的才是候选词）；顺序有意义：先剥长的
WRAP = [
    (r'^(っていう|ていう|って|という|なんて|なんか|なんで|どうせ|やっぱ|やっぱり|ちょっと)', ''),
    (r'^(だと|でも|では|のに|ので|から|まで|けど|けれど|なら|しか|ばかり|ほど|くらい|ぐらい|だけ)', ''),
    (r'^(には|とは|とも|にも|のは|のが|のを|こと|もの|わけ|はず|つもり)', ''),
    (r'^(こそあど|そりゃ|ありゃ|こりゃ|わか)', ''),
    (r'(ていうか|っつう|っす|っけ|だろ|でしょ|じゃん|かよ|だぜ|だぞ|わよ|のよ|のね|よね|んだよ|んだよね)$', ''),
    (r'(けども|けど|けれど|のに|ので|から|まで|なら|たら|ってば|ってさ|っての|では|には|とは)$', ''),
    (r'(です|ます|でした|ました|ですよ|ますよ|ですな|ますな|だな|だよ|だね|かな|かも)$', ''),
    (r'(ている|てる|ておる|ておき|とく|ちゃう|じゃう|なさい|ください)$', ''),
    # 口语习语尾巴：剩下的部分才是实词（`そんなことない` → 空）
    (r'(ことない|ことはない|ことがない|ものじゃない|もんじゃない|しかない|わけない|はずない)$', ''),
    (r'(なんて|なんか|ほど|くらい|ぐらい|ばかり|だけ|しか)$', ''),
    (r'^[はがをにへとでのもやかねよなさぞぜわを]', ''),
    (r'[はがをにへとでのもやかねよなさぞぜわを]$', ''),
]

# 单独出现也不算学习点的泛用词/语气词（残差里高频冒出来）
STOPWORD = set("""こと もの わけ はず つもり ところ ほう ため よう そう どう こんな そんな あんな
なに 何 誰 どこ いつ なぜ みんな たち かた 方 さん ちゃん くん 様 殿
おー オー オッケー オーケー ホント ほんと マジ まじ ウソ うそ ヤバ やば
はい いいえ うん そう ええ いや まあ よし では じゃあ ども どうも すみません ごめん""".split())



# 只在本作登场的人名/设定名标记（整块就是这些词时不算学习点）
NAME_MARK = ('嬢', '殿下', '姫様', '王女様', '令嬢', '様', '陛下', '王子', '侯爵', '伯爵', '公爵',
             'ユフィリア', 'アニスフィア', 'オルファンス', 'グランツ', 'イルシア', 'ティルティ',
             'アルガルド', 'マローダー', 'プリンセス', 'レヴィ', 'ラヴィ')
# 有实义的三字以上纯假名（拟声拟态词里也有能学的，交给模型看）
KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30a0-\u30ff\u30fc]+$')


def _is_content_kana(r):
    """三字以上纯假名 —— 拟态词、外来语、方言都可能有学习点，保守留下。"""
    return len(r) >= 3 and not re.match(r'^(.)\1*$', r)


def cmd_freq(a):
    """把各集残差汇总成「跨集常见碎片」表 —— 只剩一两次的多半是真词。"""
    from collections import Counter
    c = Counter()
    for ep in a.ep:
        for r in _load_csv(os.path.join(WSP.EVIDENCE, ep, 'prefilter.csv')):
            for w in (r.get('resid') or '').split(';'):
                if w:
                    c[w] += 1
    common = sorted(w for w, n in c.items() if n >= a.min)
    p = os.path.join(WSP.DATA, 'evidence', 'subtitle_common.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'common': common, 'counts': dict(c)}, f, ensure_ascii=False)
    print('残差 %d 种 → 跨集出现 ≥%d 次者 %d 种（视为机械碎片）→ %s'
          % (len(c), a.min, len(common), p))


def cmd_scan(a):
    text, _, _ = _read(a.src)
    blocks = _parse(text)
    cache = P.load_cache()
    grammar = cache['grammar']
    gpat = sorted(grammar, key=len, reverse=True)
    canonical, variant2c = load_index()
    build_matcher(variant2c)
    ipat = sorted(set(P.IDIOMS), key=len, reverse=True)
    global COMMON
    COMMON = _load_common()

    rows = []
    for b in blocks:
        t = ' / '.join(b['lines'])
        tight = core(t)
        noise = looks_noise(t)
        _, resid = match_words(tight, variant2c, canonical)
        resid_use = [c for c in useful_resid(resid) if c not in COMMON and c not in STOPWORD]
        g = [p for p in gpat if p in tight]
        strong_g = [p for p in g if len(p) >= 3 or grammar[p] in ('N3', 'N2', 'N1')]
        idi = [p for p in ipat if p in tight]
        sig = []
        if resid_use:
            sig.append('W')
        if strong_g:
            sig.append('G')
        if idi:
            sig.append('I')
        if len(tight) >= 26 and (resid_use or strong_g):
            sig.append('L')
        sigtxt = '/'.join(
            ([('未收录:' + '/'.join(resid_use[:4]))] if resid_use else []) +
            ([('语法:' + '/'.join(strong_g[:3]))] if strong_g else []) +
            ([('惯用:' + '/'.join(idi[:2]))] if idi else []))
        frag = is_frag(t)
        if noise:
            cat, why = 'NOISE', noise
        elif not sig:
            # 无强信号 —— 实测这类里仍有可讲的长句（`異常が出たらすぐに…`），
            # 所以不直接判弃，降级为「低优先灰区」，由模型/人过一遍。
            cat = 'GRAY_LO' if len(tight) >= 10 else 'GRAY_FRAG'
            why = ''
        else:
            risky = frag or len(tight) < 8 or _ctx_dependent(tight)
            cat = 'GRAY' if risky else 'KEEP_SAFE'
            why = sigtxt + ('｜可疑:残句' if frag else '') + \
                           ('｜可疑:太短' if len(tight) < 8 else '') + \
                           ('｜可疑:疑上下文依赖' if _ctx_dependent(tight) else '')
        rows.append({'idx': b['idx'], 'time': b['time'], 'text': t, 'cat': cat,
                     'sig': ''.join(sig), 'why': why, 'len': len(tight),
                     'resid': ';'.join(resid_use[:6])})

    ev = os.path.join(WSP.EVIDENCE, a.ep)
    os.makedirs(ev, exist_ok=True)
    out = os.path.join(ev, 'prefilter.csv')
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['idx', 'cat', 'sig', 'why', 'len', 'time', 'text',
                                          'resid'])
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    c = Counter(r['cat'] for r in rows)
    print('块数 %d' % len(rows))
    for k in ('NOISE', 'GRAY_FRAG', 'GRAY_LO', 'GRAY', 'KEEP_SAFE'):
        print('  %-10s %4d' % (k, c.get(k, 0)))
    print('→ %s' % out)
    print('不需要模型（直接判弃）= NOISE %d 块；待模型 %d 块'
          % (c.get('NOISE', 0), len(rows) - c.get('NOISE', 0)))


def _ctx_dependent(tight):
    """一眼就像「脱离上下文读不懂」的：整句只有称呼/应答+助词。"""
    t = re.sub(r'[私僕俺あなた君お前]', '', tight)
    return len(t) <= 4


def cmd_report(a):
    ev = os.path.join(WSP.EVIDENCE, a.ep)
    rows = _load_csv(os.path.join(ev, 'prefilter.csv'))
    for cat in ('GRAY', 'KEEP_SAFE', 'NOVAL', 'FRAG'):
        sel = [r for r in rows if r['cat'] == cat]
        print('\n=== %s（%d 块）' % (cat, len(sel)))
        sel.sort(key=lambda r: -int(r['len']))
        for r in sel[:a.show]:
            print('  #%-4s %-3s %s' % (r['idx'], r['sig'], r['text'][:70]))
            if r['why']:
                print('        %s' % r['why'][:100])
        if len(sel) > a.show:
            print('  …另 %d 块' % (len(sel) - a.show))


def cmd_gray(a):
    """只导出灰区，按 --batch 切分，供本地模型分批判定。"""
    ev = os.path.join(WSP.EVIDENCE, a.ep)
    rows = _load_csv(os.path.join(ev, 'prefilter.csv'))
    sel = [r for r in rows if r['cat'] == 'GRAY']
    outdir = os.path.join(ev, 'gray')
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for i in range(0, len(sel), a.batch):
        n += 1
        part = sel[i:i + a.batch]
        p = os.path.join(outdir, 'gray_%02d.csv' % n)
        with open(p, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(['idx', 'text'])
            for r in part:
                w.writerow([r['idx'], r['text']])
    print('灰区 %d 块 → %d 批（每批 %d）@ %s' % (len(sel), n, a.batch, outdir))



def _load_csv(p):
    with open(p, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def _read(path):
    with open(path, 'rb') as f:
        raw = f.read()
    bom = raw.startswith(b'\xef\xbb\xbf')
    if bom:
        raw = raw[3:]
    newline = '\r\n' if b'\r\n' in raw else '\n'
    return textio.decode(raw, encodings=('utf-8',), errors='strict')[0], bom, newline


def _parse(text):
    norm = text.replace('\r\n', '\n').replace('\r', '\n')
    out = []
    for chunk in re.split(r'\n[ \t]*\n', norm.strip('\n')):
        lines = chunk.split('\n')
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
        out.append({'idx': int(lines[0].strip()), 'time': lines[1].strip(), 'lines': lines[2:]})
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('index').set_defaults(func=cmd_index)
    p = sub.add_parser('scan')
    p.add_argument('--src', required=True)
    p.add_argument('--ep', required=True)
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser('report')
    p.add_argument('--ep', required=True)
    p.add_argument('--show', type=int, default=12)
    p.set_defaults(func=cmd_report)
    p = sub.add_parser('gray')
    p.add_argument('--ep', required=True)
    p.add_argument('--batch', type=int, default=30)
    p.set_defaults(func=cmd_gray)
    p = sub.add_parser('freq')
    p.add_argument('--ep', nargs='+', required=True)
    p.add_argument('--min', type=int, default=2)
    p.set_defaults(func=cmd_freq)
    a = ap.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
