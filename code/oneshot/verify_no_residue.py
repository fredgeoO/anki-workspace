# -*- coding: utf-8 -*-
"""审计/核验：扫 Anki 里「AI 生成讲解的 LaTeX 残渣 + 坏箭头」，报告是否归零。

覆盖的形态（都来自同一次事故：模型写 LaTeX，`\\r`/`\\t`/`\\d` 被当成转义吃掉）：
  * `$ightarrow$`  —— \\rightarrow 的 \\r 被吃
  * `$<TAB>ext{…}$` / `$<TAB>o$` / `$<TAB>ots$` / `$<TAB>imes$` —— 控制字符被吃
  * 任何字段里残留的制表符、反斜杠命令、`$…$`

正規入库路径（pipeline.py write / mine.py write）会用 check_cards.py / check_mine.py
把 `$` 与反斜杠判成 hard fail，理论上不会再产生；本脚本是给**历史批次**和
跳过过校验的卡做体检用的。

用法::

    python code/oneshot/verify_no_residue.py --all-decks
    python code/oneshot/verify_no_residue.py --query "deck:0-日本语学习::0-词汇::1-高频日语单词 6000"
    python code/oneshot/verify_no_residue.py --tag "动画::作品A::第一季::第01集"

命中后怎么修：
    python code/oneshot/fix_bad_arrow.py  --all-decks            # 坏箭头 → →
    python code/oneshot/fix_text_wrap.py  --all-decks            # $\\text{…}$ 等残骸
（两个脚本都默认演练，确认无误再加 --commit）
"""
import argparse
import collections
import re
import sys

sys.path.insert(0, r'<工作区根>\code\oneshot')

import fix_bad_arrow as FB  # noqa: E402
import os
_TEXTIO_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_TEXTIO_HERE, '..', 'common'))
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

CHECKS = {
    '坏箭头 $ightarrow$': re.compile(r'ightarrow'),
    '反斜杠命令': re.compile(r'\\+[a-zA-Z]{2,}'),
    '字段里的制表符': re.compile(r'\t'),
    '美元+控制字符残骸': re.compile(r'\$[\t\n]'),
    '美元对': re.compile(r'\$[^$\n]{1,60}\$'),
    '控制字符(任意)': re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]'),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--deck', default=FB.DEFAULT_DECK)
    ap.add_argument('--all-decks', action='store_true')
    ap.add_argument('--query', default=None, help='任意 Anki 查询，优先于 --deck')
    ap.add_argument('--tag', default=None, help='按标签筛（等价于 tag:<值>）')
    args = ap.parse_args()

    if args.query:
        scope = args.query
    elif args.tag:
        scope = 'tag:%s' % args.tag
    elif args.all_decks:
        scope = 'deck:*'
    else:
        scope = 'deck:"%s"' % args.deck
    ids = sorted(set(FB.invoke('findNotes', query=scope)))
    print('核验范围 %s，note %d 张' % (scope, len(ids)))

    counter = collections.Counter()
    samples = collections.defaultdict(list)
    for i in range(0, len(ids), 400):
        for info in FB.invoke('notesInfo', notes=ids[i:i + 400]):
            fields = info.get('fields', {})
            for name, fv in fields.items():
                val = fv.get('value', '') or ''
                for key, rx in CHECKS.items():
                    ms = rx.findall(val)
                    if not ms:
                        continue
                    counter[key] += len(ms)
                    if len(samples[key]) < 12:
                        m = rx.search(val)
                        a = max(0, m.start() - 45)
                        b = min(len(val), m.end() + 45)
                        samples[key].append(
                            'note %s [%s] …%s…' % (
                                info['noteId'], name,
                                val[a:b].replace('\t', '␉').replace('\n', '⏎')))

    print('\n== 计数 ==')
    for key in CHECKS:
        flag = 'OK ' if counter[key] == 0 else '⚠ '
        print('  %s%-18s %d' % (flag, key, counter[key]))
    for key in ('坏箭头 $ightarrow$', '反斜杠命令', '美元+控制字符残骸', '控制字符(任意)'):
        if counter[key]:
            print('\n-- %s 样本 --' % key)
            for s in samples[key]:
                print('   %s' % s)
    return 0


if __name__ == '__main__':
    sys.exit(main())
