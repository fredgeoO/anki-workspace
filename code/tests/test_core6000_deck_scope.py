# -*- coding: utf-8 -*-
"""回归测试：补例句的目标选择要能自动命中素材生词卡组（不只 core6000）。

钉住 2026-11-09 的坑：アップ 只在 0-素材生词，旧版 base_query() 写死 core6000
牌组导致 --words アップ 选中 0 张。不碰 Anki：只比对查询串文本。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_CODE, 'execution', 'core6000'))
sys.path.insert(0, os.path.join(_CODE, 'common'))

import textio                  # noqa: E402,F401  stdio 统一走 textio（audit R2）
import core6000_example as CE  # noqa: E402
import jp_decks as JD          # noqa: E402

fails = []


def check(name, ok, detail=''):
    print(('PASS' if ok else 'FAIL'), name, detail)
    if not ok:
        fails.append(name)


check('搜索范围含素材生词', JD.DECK_MINED in CE.SEARCH_DECKS, str(CE.SEARCH_DECKS))
q = CE.base_query()
check('base_query 覆盖 core6000', '高频日语单词 6000' in q, q)
check('base_query 覆盖素材生词', '0-素材生词' in q, q)
check('base_query 仍限模型', 'note:"Japanese Vocabulary"' in q, q)

q2 = CE.query_with_defaults('tag:待补例句')
check('--query 缺 deck 时补两牌组 OR', '高频日语单词 6000' in q2 and '0-素材生词' in q2, q2)
q3 = CE.query_with_defaults('deck:"别的牌组" tag:x')
check('--query 自带 deck: 不越权加过滤',
      q3.count('高频日语单词') == 0 and q3.startswith('deck:"别的牌组"'), q3)

print('\n%s' % ('全部通过' if not fails else '失败：%s' % '、'.join(fails)))
sys.exit(1 if fails else 0)
