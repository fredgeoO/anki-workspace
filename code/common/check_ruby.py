#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""振假名读音自检器 —— 拿**字幕自带的注音**校验生成的 `<ruby>` 读法。

为什么需要它
------------
`check_cards.py` 只查结构：文本是否逐字一致、标签是否白名单、ruby/rt 是否配对。
它**查不出一件事**：汉字标错读音。而 ABS Player 导入时会**剥掉字幕里的 `漢字(かな)` 注音**，
子代理看不到字幕作者的权威读音，只能自己猜 —— 猜错一分，卡面显示的就是错的读音，且没有任何闸门会报。

字幕本身带着答案：筛选后的 SRT 里每条 `漢字(かな)` 都是字幕作者给的读音。
本脚本把它与生成结果逐条对照，把「读音错误」变成**确定性的、可自动拦截**的问题。

实测（平家物語 S01E02）：33 处注音里抓出 6 处真实错读
（暇 ひま→いとま、美女 びじょ→びんじょう、祇女 ぎじょ→ぎにょ、蹴 け→く、
殿下乗合 でんか→てんがののりあい、一本葛 いっぽん/くず→ひもと/かずら）。

用法
----
  # 1) 校验子代理产出（阶段二 verify 之前）
  python check_ruby.py --plan data/evidence/heike_s1e02/plan.json --gen data/pipeline/gen
  python check_ruby.py --plan data/evidence/heike_s1e02/plan.json --json data/pipeline/gen/output_01.json

  # 2) 直接扫库里已入库的卡（回归用）
  python check_ruby.py --plan data/evidence/heike_s1e02/plan.json --anki "tag:动画::平家物语::第02集"

  # 3) 不想给 plan.json 时，直接指筛选后的 SRT
  python check_ruby.py --srt "subtitles/.../（制作anki卡牌用）.srt" --gen data/pipeline/gen

判定口径
--------
对每条字幕注音 `漢字(かな)`，在卡里找**覆盖这几个汉字**的 ruby（允许拆成多个 ruby、
也允许一个 ruby 覆盖更长的词），再看它的读法是否与字幕注音一致：

  OK       读法完全一致
  INFO     读法里**包含**字幕注音（例：字幕只注了 `仏(ほとけ)`，卡里是 `<ruby>仏御前<rt>ほとけごぜん</rt></ruby>`；
           或字幕 `一本葛(ひともとかずら)` 被拆成 `<ruby>一本<rt>ひもと</rt></ruby><ruby>葛<rt>かずら</rt></ruby>`）
  MISMATCH 读法对不上 —— `Sentence HTML` 里出现即**不合格**；只出现在 `AINote` 里算提醒

退出码：`Sentence HTML` 有 MISMATCH 时为 1，否则 0（可直接串进流水线做闸门）。

依赖：阶段二产物（`output_*.json`）或本机 AnkiConnect（`--anki` 模式）。
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import anki_api as AK  # noqa: E402  唯一的 Anki 访问点
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

# 默认参照 deck（与 pipeline.CFG['deck'] 一致）：用它已入库的卡建立「读音词典」。
# 同一汉字串在本 deck 里怎么读，是有先例的 —— 换集出现不一致时应当报警。
DEFAULT_LEXICON = 'deck:"0-日本语学习::2-例句"'

# 字幕里的 `漢字(かな)` 注音。假名范围含 ゐゑ 等历史假名。
ANN = re.compile(r'([\u4e00-\u9fff\u3005\u3400-\u4dbf]+)[（(]([\u3041-\u3096\u30a0-\u30ff\u30fc]+)[）)]')
RUBY = re.compile(r'<ruby>(.*?)<rt>(.*?)</rt></ruby>', re.S)
TAG = re.compile(r'<[^>]+>')

OK, INFO, BAD = 'OK', 'INFO', 'MISMATCH'


# ---------------------------------------------------------------- 基础设施

def parse_srt_text(text):
    """按空行切块；返回 [{idx, lines}]。"""
    norm = text.replace('\r\n', '\n').replace('\r', '\n')
    out = []
    for chunk in re.split(r'\n[ \t]*\n', norm.strip('\n')):
        lines = chunk.split('\n')
        while lines and lines[-1].strip() == '':
            lines.pop()
        if len(lines) < 3 or not re.match(r'^\d+$', lines[0].strip()):
            continue
        out.append({'idx': int(lines[0].strip()), 'lines': lines[2:]})
    return out


def read_srt(path):
    with open(path, 'rb') as f:
        raw = f.read()
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    return parse_srt_text(raw.decode('utf-8'))


def deannotate(s):
    """去掉 `漢字(かな)` 里的 (かな)，只留汉字 —— 用来跟卡面文本对上。"""
    return ANN.sub(r'\1', s)


def rubies_of(html):
    """按出现顺序取 [(base, reading)]，base 里的嵌套标签一并剥掉。"""
    return [(TAG.sub('', m.group(1)), m.group(2)) for m in RUBY.finditer(html or '')]


def covering_readings(rubies, kanji, max_extra=4):
    """找出所有「base 覆盖了这几个汉字」的读法。允许拆成连续多个 ruby。

    - `max_extra` 限制 base 比目标汉字多出的字数，否则从 AINote 开头累积
      会拼出「蝸牛馬子牛子舞蹴→…」这种荒唐候选。
    - 结果按「base 是否恰好等于目标 > base 更短 > 用的 ruby 更少」排序，取最优的那个。
    """
    cands, n = [], len(rubies)
    for i in range(n):
        base = ''
        for j in range(i, n):
            base += rubies[j][0]
            if len(base) > len(kanji) + max_extra:
                break
            if kanji in base:
                cands.append((base, ''.join(r for _, r in rubies[i:j + 1]), j - i + 1))
                break
    cands.sort(key=lambda x: (x[0] != kanji, len(x[0]), x[2]))
    return [(b, r) for b, r, _ in cands]


def judge(kanji, want, html, field, strict_missing=True):
    """返回 (等级, 说明)。

    `strict_missing=False` 用于 `AINote`：中文解释里出现同一个汉字串是正常的
    （「基房」在中文翻译里就是中文），**不能**因为「没标 ruby」就报错，
    只有「标了 ruby 但读法不对」才算问题。
    """
    if kanji not in TAG.sub('', html):
        return None, ''                      # 这块内容不在该字段里（如删掉的行），跳过
    cands = covering_readings(rubies_of(html), kanji)
    if not cands:
        if not strict_missing:
            return None, ''
        return BAD, '%s：字幕注音 %s(=%s)，但该字段里找不到覆盖它的 ruby' % (field, kanji, want)
    if any(r == want for _, r in cands):
        return OK, ''
    for base, r in cands:
        if want in r:
            return INFO, ('%s：字幕只注了 %s(%s)，卡里是 %s(%s) —— 读法包含，属合成/拆分写法'
                          % (field, kanji, want, base, r))
    return BAD, ('%s：%s 字幕注音是 %s，卡里标成了 %s'
                 % (field, kanji, want, ' / '.join('%s→%s' % (b, r) for b, r in cands[:4])))


# ---------------------------------------------------------------- 取卡

def cards_from_json(paths):
    cards = []
    for p in paths:
        cards.extend(json.load(open(p, encoding='utf-8')))
    return cards


def cards_from_anki(query):
    cards = []
    for n in AK.notes_info(AK.find_notes(query)):
        f = AK.field_values(n)
        cards.append({'noteId': n['noteId'],
                      'sentence': f.get('Sentence', ''),
                      'SentenceHTML': f.get('Sentence HTML', ''),
                      'AINote': f.get('AINote', '')})
    return cards


def build_lexicon(query, exclude_ids):
    """用 deck 里**已入库**的卡建立「汉字串 → 读音」词典。

    只收「多字（≥2 且含汉字）」且**读法唯一**的基底：
      - 单字基底（来・日・人）在不同词里读音不同，收了必然误报
      - deck 里出现两种读法的（半人前 はんにんまえ/はんじんまえ、明日 あす/あした）属于真歧义，跳过
    """
    try:
        notes = AK.notes_info(AK.find_notes(query))
    except Exception as e:                     # Anki 没开时不要让整个校验失败
        print('  （读音词典跳过：%s）' % e)
        return {}
    lex = {}
    seen = {}
    for n in notes:
        if int(n['noteId']) in exclude_ids:
            continue
        for base, reading in rubies_of(AK.field(n, 'Sentence HTML')):
            if len(base) < 2 or not re.search(r'[\u4e00-\u9fff]', base):
                continue
            seen.setdefault(base, set()).add(reading)
    for base, readings in seen.items():
        if len(readings) == 1:
            lex[base] = next(iter(readings))
    return lex


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description='用字幕自带注音校验振假名读音')
    ap.add_argument('--plan', help='filter_subtitle.py 的 plan.json（自动取 source/output）')
    ap.add_argument('--srt', help='带注音的筛选后 SRT（与 --plan 二选一）')
    ap.add_argument('--gen', default=WSP.DATA_PIPELINE and os.path.join(WSP.DATA_PIPELINE, 'gen'),
                    help='阶段二工作目录（读 output_*.json）')
    ap.add_argument('--json', nargs='*', default=None, help='直接指定产出 JSON 文件')
    ap.add_argument('--anki', help='改为扫库：Anki 查询串，如 "tag:动画::..."')
    ap.add_argument('--lexicon', default=DEFAULT_LEXICON,
                    help='读音词典的参照 deck 查询（默认 %s）' % DEFAULT_LEXICON)
    ap.add_argument('--no-lexicon', action='store_true', help='跳过跨卡读音一致性检查')
    ap.add_argument('--strict-lexicon', action='store_true',
                    help='把跨卡读音不一致也算作不合格（默认只提醒）')
    ap.add_argument('--blind-out', help='把「两道闸门都盖不到的读音」写成 markdown，供人工/强模型只过这一小份')
    a = ap.parse_args()

    srt = a.srt
    if a.plan:
        plan = json.load(open(a.plan, encoding='utf-8'))
        srt = srt or plan['output']
    if not srt:
        raise SystemExit('需要 --plan 或 --srt（提供带注音的字幕）')

    # 字幕块 → 注音表（键 = 去掉注音后的整块文本）；另记全部块文本用于区分「没注音」与「对不上块」
    annos, all_texts = {}, set()
    for b in read_srt(srt):
        txt = ''.join(deannotate(x) for x in b['lines'])
        all_texts.add(txt)
        found = {}
        for line in b['lines']:
            for m in ANN.finditer(line):
                found[m.group(1)] = m.group(2)
        if found:
            annos[txt] = (b['idx'], found)
    print('带注音的字幕块：%d 个   注音来源：%s' % (len(annos), srt))

    if a.anki:
        cards = cards_from_anki(a.anki)
        label = 'Anki 查询：%s' % a.anki
    else:
        paths = a.json if a.json else sorted(glob.glob(os.path.join(a.gen, 'output_*.json')))
        if not paths:
            raise SystemExit('没找到产出文件：%s/output_*.json' % a.gen)
        cards = cards_from_json(paths)
        label = '文件：%s' % '、'.join(os.path.basename(p) for p in paths)
    print('%s   共 %d 张' % (label, len(cards)))

    # 跨卡读音一致性：同一汉字串在本 deck 已入库的卡里怎么读，是有先例的
    lex, incons = {}, []
    if not a.no_lexicon:
        lex = build_lexicon(a.lexicon, {int(c['noteId']) for c in cards if c.get('noteId')})
        print('读音词典（%s，排除本批）：%d 个多字词条' % (a.lexicon, len(lex)))
        for c in cards:
            for base, reading in rubies_of(c.get('SentenceHTML') or ''):
                if base in lex and lex[base] != reading:
                    incons.append((c.get('noteId'), base, reading, lex[base]))

    n_checked = n_ok = 0
    infos, bads, warns, noanno, unmatched = [], [], [], 0, []
    for c in cards:
        txt = (c.get('sentence') or '').replace('<br>', '')
        hit = annos.get(txt)
        if not hit:
            if txt in all_texts:
                noanno += 1          # 该块本来就没有注音，无从对照
            else:
                unmatched.append(c.get('noteId'))
            continue
        idx, found = hit
        for kanji, want in found.items():
            n_checked += 1
            html_lv, html_msg = judge(kanji, want, c.get('SentenceHTML') or '', 'Sentence HTML')
            an_lv, an_msg = judge(kanji, want, c.get('AINote') or '', 'AINote', strict_missing=False)
            if html_lv == BAD:
                bads.append((c.get('noteId'), idx, html_msg))
            elif html_lv == INFO:
                infos.append((c.get('noteId'), idx, html_msg))
            if an_lv == BAD:
                warns.append((c.get('noteId'), idx, an_msg))
            if html_lv in (OK, None) and an_lv in (None, OK):
                n_ok += 1

    print()
    print('=' * 78)
    print('对照 %d 处注音：一致 %d / 写法差异 %d / **Sentence HTML 错读 %d** / AINote 错读 %d'
          % (n_checked, n_ok, len(infos), len(bads), len(warns)))
    for nid, idx, msg in bads:
        print('  ✗ noteId %s（字幕块 %s） %s' % (nid, idx, msg))
    if incons:
        tag = '✗' if a.strict_lexicon else '⚠'
        print('  %s 跨卡读音不一致 %d 处（同一个词在别的卡里不是这么读的）%s：'
              % (tag, len(incons), '' if a.strict_lexicon else '　默认只提醒，加 --strict-lexicon 才算不合格'))
        for nid, base, got, want in incons:
            print('      noteId %s：%s 标的 %s，本 deck 里是 %s' % (nid, base, got, want))
        print('      （注意：明日 あす/あした 这类词本身就有两种读法，属于正常歧义）')
    for nid, idx, msg in warns:
        print('  ⚠ noteId %s（字幕块 %s） %s（AINote 不计入退出码）' % (nid, idx, msg))
    if infos:
        print('  · 以下只是「一个 ruby 覆盖更长的词 / 拆成多个 ruby」，读音本身对得上：')
        for nid, idx, msg in infos[:12]:
            print('      noteId %s（块 %s） %s' % (nid, idx, msg))
        if len(infos) > 12:
            print('      … 其余 %d 处' % (len(infos) - 12))
    print('  另：%d 张卡的块本来就没有注音（跳过）；%d 张卡对不上任何字幕块' % (noanno, len(unmatched)))
    if unmatched:
        print('      对不上的：%s' % unmatched[:8])

    # 「裸奔面」：这份卡面读音既没有字幕注音、也没有 deck 先例可依 —— 只能靠语言知识判断。
    # 把它单独列出来，就是为了让强模型/人只审这一小份，而不是重读全部讲解。
    ann_kanji = {k for _, found in annos.values() for k in found}
    base_cnt = {}
    for c in cards:
        for base, _r in rubies_of(c.get('SentenceHTML') or ''):
            if re.search(r'[\u4e00-\u9fff]', base):
                base_cnt[base] = base_cnt.get(base, 0) + 1
    blind = [b for b in base_cnt
             if b not in lex and not any(b in k or k in b for k in ann_kanji)]
    print('  读音覆盖：字幕注音 %d 个基底 / deck 词典 %d 个 / **两道都盖不到 %d 个**'
          % (sum(1 for b in base_cnt if any(b in k or k in b for k in ann_kanji)),
             sum(1 for b in base_cnt if b in lex),
             len(blind)))
    if a.blind_out:
        blind.sort(key=lambda x: (-base_cnt[x], x))
        with open(a.blind_out, 'w', encoding='utf-8') as f:
            f.write('# 读音「裸奔面」清单（%d 个基底，%d 次出现）\n\n' % (len(blind), sum(base_cnt[b] for b in blind)))
            f.write('> 这些读音既没有字幕自带注音、也没有本 deck 已入库卡片的先例，\n')
            f.write('> 只能靠语言知识判断。强模型/人只需过这一份，不必重读全部讲解。\n\n')
            for b in blind:
                f.write('- `%s` ×%d\n' % (b, base_cnt[b]))
        print('  裸奔面清单已写出：%s' % a.blind_out)
    if not bads and not (incons and a.strict_lexicon):
        print('  Sentence HTML 读音全部通过 ✅')
    print('=' * 78)
    sys.exit(1 if (bads or (incons and a.strict_lexicon)) else 0)


if __name__ == '__main__':
    with AK.guard():          # Anki 没开时给中文提示，不出 traceback
        main()
