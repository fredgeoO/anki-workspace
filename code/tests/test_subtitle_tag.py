# -*- coding: utf-8 -*-
"""回归测试：`subtitle_tag`（字幕/文字生词打标的纯逻辑）

挡四件事：
1. 标签拼错：`--name ヤニねこ` 必须得到 `复习::ヤニねこ`（用户点名的标签串）。
2. 层级名被 slug 毁掉：`七大罪::第一季` / `七大罪/第一季` 要保留成三层。
3. 打标对象选错：非新卡（type != 0）跳过、卡不存在跳过、同词多卡只取一张。
4. 重复打标：同词已带 `复习` / `复习::*`（不论哪个来源、也不论挂在同词哪张笔记上）
   一律跳过——一个词只挂一个复习标签。

跑法（不碰 Anki、不读 data/）：
  & $PY code\\tests\\test_subtitle_tag.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'tools'))
import textio  # noqa: E402
import subtitle_tag as ST  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


def test_tag_for():
    check('普通名称', ST.tag_for('ヤニねこ') == '复习::ヤニねこ', ST.tag_for('ヤニねこ'))
    check(':: 保留层级', ST.tag_for('七大罪::第一季') == '复习::七大罪::第一季',
          ST.tag_for('七大罪::第一季'))
    check('/ 也当层级', ST.tag_for('七大罪/第一季') == '复习::七大罪::第一季',
          ST.tag_for('七大罪/第一季'))
    check('首尾分隔符不产生空层', ST.tag_for('::ヤニねこ::') == '复习::ヤニねこ',
          ST.tag_for('::ヤニねこ::'))
    check('空格转下划线', ST.tag_for('青空 文庫') == '复习::青空_文庫',
          ST.tag_for('青空 文庫'))
    try:
        ST.tag_for('   ')
        check('空名必须报错', False, '没有抛 SystemExit')
    except SystemExit:
        check('空名必须报错', True)


def test_family_tag():
    check('裸标签命中', ST.family_tag(['复习']) == '复习', ST.family_tag(['复习']))
    check('子标签命中', ST.family_tag(['动画::X', '复习::ヤニねこ']) == '复习::ヤニねこ',
          ST.family_tag(['动画::X', '复习::ヤニねこ']))
    check('别名不算', ST.family_tag(['复习用::x']) is None, ST.family_tag(['复习用::x']))
    check('空列表', ST.family_tag([]) is None)


def _w(word, note, card, deck='0-日本语学习::0-词汇::2-考级词汇'):
    return {'word': word, 'deck': deck, 'noteId': note, 'cardId': card}


def test_pick_items():
    words = [_w('隙間', 1, 11), _w('隙間', 1, 11), _w('汁', 2, 22), _w('ウンコ', 3, 33)]
    items = ST.pick_items(words)
    check('同 noteId 去重', [it['noteId'] for it in items] == [1, 2, 3],
          [it['noteId'] for it in items])
    items = ST.pick_items(words, exclude=['ウンコ'])
    check('--exclude 按词剔除', [it['word'] for it in items] == ['隙間', '汁'],
          [it['word'] for it in items])
    items = ST.pick_items(words, exclude=['', '  '])
    check('空 exclude 不误伤', len(items) == 3, len(items))
    check('保留 cardId 供 live 复核', items[0]['cardId'] == 11, items[0])


def test_plan_apply():
    tag = '复习::ヤニねこ'
    items = [{'word': '新卡', 'deck': 'd', 'noteId': 1, 'cardId': 11},
             {'word': '已标过', 'deck': 'd', 'noteId': 2, 'cardId': 22},
             {'word': '别的集标过', 'deck': 'd', 'noteId': 3, 'cardId': 33},
             {'word': '学过了', 'deck': 'd', 'noteId': 4, 'cardId': 44},
             {'word': '卡没了', 'deck': 'd', 'noteId': 5, 'cardId': 55}]
    live_cards = {11: {'type': 0}, 22: {'type': 0}, 33: {'type': 0},
                  44: {'type': 2}}
    live_tags = {1: [], 2: [tag], 3: ['复习::別集'], 4: [], 5: []}
    # 同词的另一张笔记带日期标签（word_tags 覆盖整词）
    word_tags = {'新卡': [], '已标过': [tag], '别的集标过': ['复习::別集'],
                 '学过了': [], '卡没了': []}
    todo, already, skipped = ST.plan_apply(items, live_cards, live_tags, tag,
                                           word_tags=word_tags)
    check('type==0 且无 tag → 打', [it['word'] for it in todo] == ['新卡'],
          [it['word'] for it in todo])
    check('已带本来源 tag → 跳过', '已标过' in [it['word'] for it in already])
    check('别的来源已标过 → 跳过', '别的集标过' in [it['word'] for it in already])
    why = {it['word']: r for it, r in skipped}
    check('type!=0 → 跳过', '学过了' in why, list(why))
    check('卡不存在 → 跳过', '卡没了' in why, list(why))
    check('跳过原因可读', 'type=2' in why.get('学过了', ''), why.get('学过了'))

    # 不带 word_tags（旧调用方式）：只按本笔记标签判定
    todo2, already2, _ = ST.plan_apply(items, live_cards, live_tags, tag)
    check('word_tags 缺省时本笔记 tag 仍跳过',
          [it['word'] for it in already2] == ['已标过', '别的集标过'],
          [it['word'] for it in already2])


def test_state_shape():
    """--revert 靠 tags_applied.json 的 tag + note_ids；字段缺一不可。"""
    st = {'tag': '复习::ヤニねこ', 'note_ids': [1, 2], 'source': 'x.srt'}
    check('回退记录含 tag', st.get('tag') == '复习::ヤニねこ', st.get('tag'))
    check('回退记录含 note_ids', st.get('note_ids') == [1, 2], st.get('note_ids'))


def main():
    for fn in (test_tag_for, test_family_tag, test_pick_items, test_plan_apply,
               test_state_shape):
        print(fn.__name__)
        fn()
    print()
    if FAIL:
        print('✗ %d 项失败：%s' % (len(FAIL), FAIL))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
