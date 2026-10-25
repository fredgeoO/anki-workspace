# -*- coding: utf-8 -*-
"""素材生词卡自检器 —— mine.py 阶段的硬性规则，与 check_cards.py 同一套口径。

用法：
  python check_mine.py gen_mine/output_01.json
  python check_mine.py gen_mine/output_*.json --quiet

输入 JSON 格式（mine.py split 规定的子代理产出）：
  [{"word":"突如","reading":"とつじょ","pos":"副词","meaning":"突然",
    "translation":"突然警报响起。","a_note":"<p>…</p>","include":true,"reason":""}, ...]

只校验 include=true 的条目；include=false 的必须有 reason。
退出码：0 = 全部合格；1 = 有不合格。
"""
import json
import re
import sys

sys.path.insert(0, __file__.rsplit('\\', 1)[0])
import check_cards as C  # noqa: E402  复用 ruby / 标签白名单 / 非法字符的实现
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）
from llm_out import as_bool, as_text, is_boolish  # noqa: E402,F401  「模型产出吸收层」的唯一实现

KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30fc\u30fb]+$')
POS_OK = {'名词', 'イ形容词', 'ナ形容词', '自动词', '他动词', '副词', '接续词',
          '外来语', '惯用句', '形容动词', '连体词', '接尾', '接头', '代词', '数词'}
SECTIONS = ('中文翻译', '核心词汇', '语法要点')
TEXT_KEYS = ('word', 'reading', 'pos', 'meaning', 'translation', 'a_note', 'reason')

# as_text / as_bool 的**实现**已移到 `llm_out.py`（阶段二也要用同一份），这里只做再导出，
# 让历史调用点（`CM.as_text(...)`）和新代码共用一套规则，避免两份口径漂移：
#   * as_text：非字符串一律当空串（数字/列表/字典/布尔都算"没这个字段"）
#   * as_bool：认识 "false"/"0"/"否" 这些写错的布尔


def check(c):
    hard, soft = [], []
    if not isinstance(c, dict):
        return ['条目不是对象：%r' % (c,)], soft
    for key in TEXT_KEYS:
        v = c.get(key)
        if v is not None and not isinstance(v, str):
            hard.append('%s 字段类型不是字符串：%s %r' % (key, type(v).__name__, v))
    w = as_text(c.get('word')).strip()
    if not w:
        return (['word 为空'] if not hard else hard), soft
    if not is_boolish(c.get('include')):
        hard.append('include 不是布尔值：%r（要 JSON 的 true / false，'
                    '写字符串 "true"/"false" 也能认）' % (c.get('include'),))
    if not (KANJI.search(w) or KANA.search(w)):
        hard.append('word 不含日文字符：%r' % w)
    if re.search(r'[A-Za-z0-9]', w):
        hard.append('word 含拉丁/数字字符：%r' % w)
    if '<' in w or '>' in w:
        hard.append('word 含 HTML 标签')
    if not as_bool(c.get('include')):
        if not as_text(c.get('reason')).strip():
            hard.append('include=false 但没有 reason')
        return hard, soft

    for key in ('reading', 'pos', 'meaning', 'translation', 'a_note'):
        if not as_text(c.get(key)).strip():
            hard.append('include=true 但 %s 为空' % key)
    if hard:
        return hard, soft

    if as_text(c.get('pos')) not in POS_OK:
        hard.append('pos 不在允许集合：%r' % c.get('pos'))
    for key in ('reading', 'meaning', 'pos', 'word'):
        v = as_text(c.get(key))
        if '<' in v or '>' in v:
            hard.append('%s 里混入了 HTML 标签' % key)
    if not KANA_ONLY.match(as_text(c.get('reading'))):
        hard.append('reading 不是纯假名：%r' % c.get('reading'))

    a = as_text(c.get('a_note'))
    # 与例句卡同一套标签/字符校验
    for field, val in (('a_note', a),):
        if '\\' in val:
            hard.append('%s 含反斜杠' % field)
        if '$' in val:
            hard.append('%s 含 $' % field)
        if '```' in val or '**' in val:
            hard.append('%s 含 Markdown 标记' % field)
        if '"' in val:
            hard.append('%s 含半角双引号' % field)
        for m in re.finditer(r'<\s*/?\s*([a-zA-Z0-9]+)', val):
            if m.group(1).lower() not in C.WHITELIST:
                hard.append('%s 用了白名单外标签 <%s>' % (field, m.group(1)))
        if re.search(r'(class|style)\s*=', val):
            hard.append('%s 含 class/style 属性' % field)
        if val.count('<ruby>') != val.count('</ruby>') or val.count('<rt>') != val.count('</rt>'):
            hard.append('%s 的 ruby/rt 标签不配对' % field)
        for frag in C.stray_rt(val):
            hard.append('%s 有 <ruby> 之外的 <rt>：%s' % (field, frag))
        if val.count('<p>') != val.count('</p>'):
            hard.append('%s 的 <p> 标签不配对' % field)

    for key in SECTIONS:
        if '<b>%s：</b>' % key not in a:
            hard.append('a_note 缺少段落：%s' % key)
    if not a.strip().startswith('<p>'):
        hard.append('a_note 必须以 <p> 开头')

    # 词条头的 ruby 覆盖（软性）
    for seg in re.split(r'<br>', a):
        if '：' not in seg:
            continue
        head = seg.split('：')[0]
        if head.startswith('<p><b>') or head.startswith('<b>'):
            continue
        if KANJI.search(C.outside_ruby(head)):
            soft.append('a_note 词条头可能有未标 ruby 的汉字：%s' % C.outside_ruby(head))
    return hard, soft


def main():
    args = sys.argv[1:]
    quiet = '--quiet' in args
    args = [a for a in args if a != '--quiet']
    if not args:
        print('用法：python check_mine.py gen_mine/output_01.json [--quiet]')
        raise SystemExit(2)

    cards, bad_total = [], 0
    for p in args:
        try:
            cards.extend(json.load(open(p, encoding='utf-8')))
        except Exception as e:
            print('读不了 %s：%s' % (p, e))
            raise SystemExit(2)

    bad = []
    for c in cards:
        hard, soft = check(c)
        if hard:
            bad.append(((c or {}).get('word') if isinstance(c, dict) else c, hard, soft))
    n_inc = sum(1 for c in cards if isinstance(c, dict) and as_bool(c.get('include')))
    if not quiet:
        for w, hard, soft in bad:
            print('★ %s' % w)
            for m in hard:
                print('    [不合格] %s' % m)
            for m in soft:
                print('    [提醒]   %s' % m)
    print('=' * 70)
    print('总计 %d 条（收录 %d / 排除 %d）—— 合格 %d / 不合格 %d'
          % (len(cards), n_inc, len(cards) - n_inc, len(cards) - len(bad), len(bad)))
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
