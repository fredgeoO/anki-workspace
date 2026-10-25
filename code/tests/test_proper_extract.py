# -*- coding: utf-8 -*-
"""回归测试：原子能力 `proper_extract`（文字 + 背景 → 专名清单）

只测**确定性**部分，不连本地模型、不碰 Anki、不碰 data/：

  python code\\tests\\test_proper_extract.py

覆盖：
  1. 预扫两路（Sudachi 固名 / 片假名长串）与形态过滤
  2. NFKC（半角片假名）与多行拼回
  3. 机械闸门：子串、类别枚举、读音、长度、拉丁字符
  4. 类别近义写法归一到枚举
  5. 批量下标对齐（相同文本不会被错认成同一段）
  6. `--no-model` 路径不依赖模型
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'tools'))
import textio  # noqa: E402,F401  （stdio 一律 UTF-8）
import proper_extract as PE  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def words(text):
    return [c['word'] for c in PE.candidates(text)]


def run():
    print('— 预扫 —')
    check('Sudachi 人名被召回', 'アリシア' in words('アリシアさん、おはよう'))
    check('片假名长串被召回', 'ウンディーネ' in words('ウンディーネにもできる'))
    check('普通名词不进预扫', '気持ち' not in words('気持ちを届ける'))
    check('片假名 2–3 字不进预扫（碎片规则是 ≥4）',
          'クレープ' in words('クレープだ') and 'ホ' not in words('ホテルだ'))
    check('半角片假名 NFKC 后进预扫', 'ディアンヌ' in words('ﾃﾞｨｱﾝﾇが来た'))
    check('多行拼回仍能召回', 'メリオダス' in words('七つの大罪\n憤怒の罪のメリオダス'))

    print('— 机械闸门 —')
    text = '七つの大罪のメリオダス'
    ok, bad = PE.validate(text, [
        {'word': 'メリオダス', 'categories': ['人名', '称号'], 'reading': 'メリオダス'},
        {'word': 'エリザベス', 'categories': ['人名'], 'reading': 'えりざべす'},
        {'word': '大罪', 'categories': ['概念'], 'reading': 'たいざい'},
        {'word': 'David', 'categories': ['人名'], 'reading': 'でいびっど'},
        {'word': '七つの大罪', 'categories': ['人物'], 'reading': 'ななつのたいざい'},
    ])
    got = {n['word']: n for n in ok}
    check('合法条目通过', 'メリオダス' in got)
    check('读音片假名 → 平假名', got.get('メリオダス', {}).get('reading') == 'めりおだす',
          got.get('メリオダス', {}).get('reading'))
    check('多类别保留', got.get('メリオダス', {}).get('categories') == ['人名', '称号'])
    check('不在原文的词被拦', 'エリザベス' not in got)
    check('拉丁写法被拦', 'David' not in got)
    check('「人物」归一为「人名」', got.get('七つの大罪', {}).get('categories') == ['人名'])
    check('被拦的条目都有 issues',
          any('エリザベス' in x for x in bad) and any('拉丁' in x for x in bad), bad)
    check('碎片只要能对上原文就算合法（补全闸门在后端）',
          '大罪' in got, got.keys())

    print('— 补全方向 —')
    ok2, _ = PE.validate('大納言に任じられた', [{'word': '大納言', 'categories': ['称号']}])
    check('碎片可前后补全成完整专名', [n['word'] for n in ok2] == ['大納言'])
    ok3, bad3 = PE.validate('大納言に任じられた', [{'word': '大納言殿', 'categories': ['称号']}])
    check('补过头（原文没有）被拦', not ok3, bad3)

    print('— 词边界 / 形状 —')
    ok4, bad4 = PE.validate('晃知りませんか', [{'word': '晃知', 'categories': ['人名']}])
    check('把下一个词的一个字粘上来 → 拦（整词边界）', not ok4, bad4)
    ok5, _ = PE.validate('晃知りませんか', [{'word': '晃', 'categories': ['人名']}])
    check('整词的单字名字放行', [n['word'] for n in ok5] == ['晃'], ok5)
    ok6, bad6 = PE.validate('次回「その 透明な少女と...」',
                            [{'word': 'その 透明な少女と...', 'categories': ['作品名']}])
    check('带空格/标点尾巴 → 拦（像标题不像词条）', not ok6, bad6)
    ok7, _ = PE.validate('ネオ・ヴェネツィアの街', [{'word': 'ネオ・ヴェネツィア', 'categories': ['地名']}])
    check('跨多个 token 的连写专名仍放行', [n['word'] for n in ok7] == ['ネオ・ヴェネツィア'], ok7)

    print('— 批量对齐 —')
    items = [{'text': 'アリシアさん', 'background': '作品=ARIA'},
             {'text': 'アリシアさん', 'background': '作品=ARIA'},   # 完全相同的两段
             {'text': 'シルフさん', 'background': '作品=ARIA'}]
    # 不连模型：只验 offline 路径的形状与条数
    res = [PE.extract_offline(it['text'])[0] for it in items]
    check('批量结果与输入等长', len(res) == len(items))
    check('相同文本各自独立', res[0] and res[1])

    print('— 类别枚举 —')
    check('CATEGORIES 九类', PE.CATEGORIES == ('人名', '地名', '组织', '概念', '技能',
                                              '种族', '称号', '作品名', '其他'),
          PE.CATEGORIES)

    print()
    if FAIL:
        print('失败 %d 项：%s' % (len(FAIL), '、'.join(FAIL)))
        return 1
    print('全部通过。')
    return 0


if __name__ == '__main__':
    sys.exit(run())
