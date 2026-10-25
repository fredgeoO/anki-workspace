# -*- coding: utf-8 -*-
"""通用能力：字幕/文字 → 三个词汇卡组里「还没学、也没被复习标过」的生词，打一个来源标签。

做的事情只有一件：给这些词对应的笔记加上 ``复习::<名称>``。
**不写** ``due`` / ``ivl`` / ``factor`` / ``type`` / ``queue`` / ``reps`` / ``lapses``，
不改任何字段、不加日期标签、不碰 ``3-专有词汇``。只打标签，不排期（新卡排期看 ``jp-anki-activate``）。

用法
----
::

    # 真写（默认动作；工具本身仍是「演练默认、--commit 才写」）
    $PY code\\tools\\subtitle_tag.py "字幕.srt" --name ヤニねこ --commit

    # 先看名单（不写库）
    $PY code\\tools\\subtitle_tag.py "字幕.srt" --name ヤニねこ

    # 纯文本 / 粘贴文字（stdin）
    $PY code\\tools\\subtitle_tag.py "note.txt" --name 青空文庫 --commit
    Get-Content draft.txt -Encoding UTF8 | & $PY code\\tools\\subtitle_tag.py - --name 随笔 --commit

    # 回退：按 tags_applied.json 摘掉这一个标签
    $PY code\\tools\\subtitle_tag.py "字幕.srt" --revert --commit

判定口径（与 ``subtitle_new_words.py`` 一致）
--------------------------------------------
* 范围：``0-素材生词`` / ``1-高频日语单词 6000`` / ``2-考级词汇``（``jp_decks`` 常量）；
* 「还没学」＝该词**所有**卡都是新卡（``type == 0``）；
* **一个词只挂一个复习标签**：词（任一笔记，含 `0-词汇` 下别的子牌组）已经带
  ``复习`` 或 ``复习::*`` 就不标——不管那个标签来自哪一集；这样重复出现的生词不会被第二次打标；
* 挂起的新词（``queue == -1``）不标；埋藏的新卡照标（打 tag 不解除埋藏）；
* 同词多卡只标一张（``subtitle_new_words`` 按卡组优先级选定的那张）。

产物
----
* ``data/subtitle_review/<输入名>/words.json`` / ``words.tsv`` / ``report.md``（复用提取产物）
* ``data/subtitle_review/<输入名>/tags_applied.json``（本次打过的 noteId，供 ``--revert``）
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, _HERE)

import textio                    # noqa: E402  UTF-8 stdio 唯一入口
import anki_api as AK            # noqa: E402
import jp_decks as JD            # noqa: E402
import subtitle_new_words as SW  # noqa: E402

# 三个词汇卡组（不含 3-专有词汇）。改卡组名只改 jp_decks.py，这里跟着走。
SCOPES = (JD.DECK_MINED, JD.DECK_CORE6000, JD.DECK_KAOKYU)
TAG_PREFIX = '复习'              # 标签家族前缀；子标签为 复习::<来源>
STATE_NAME = 'tags_applied.json'


# ============================================================================
# 纯函数（不碰 Anki，测试直接喂）
# ============================================================================
def tag_for(name):
    """``ヤニねこ`` → ``复习::ヤニねこ``；``::`` 或 ``/`` 视为层级分隔。"""
    parts = [p for p in re.split(r'::|/', name or '') if p.strip()]
    if not parts:
        raise SystemExit('--name 不能为空（示例：--name ヤニねこ）')
    return TAG_PREFIX + '::' + '::'.join(SW._slug(p, 40) for p in parts)


def pick_items(words, exclude=()):
    """词表 → 待处理项（按 noteId 去重；``exclude`` 按词剔除）。"""
    ex = {str(x).strip() for x in exclude if str(x).strip()}
    seen, items = set(), []
    for w in words:
        if w['word'] in ex:
            continue
        nid = int(w['noteId'])
        if nid in seen:
            continue
        seen.add(nid)
        items.append({'word': w['word'], 'deck': w['deck'], 'noteId': nid,
                      'cardId': int(w['cardId'])})
    return items


def family_tag(tags, prefix=TAG_PREFIX):
    """→ tags 里第一个本家族标签（裸 ``复习`` 或 ``复习::*``）；没有则 None。

    「一个词只挂一个复习标签」靠它判定：不管标签来自哪一集，只要命中家族就跳过。
    """
    for t in tags or ():
        if t == prefix or t.startswith(prefix + '::'):
            return t
    return None


def plan_apply(items, live_cards, live_tags, tag, word_tags=None):
    """(todo, already, skipped)。

    ``live_cards``: {cardId: card}；``live_tags``: {noteId: [tags]}（现场读）；
    ``word_tags``: {word: [tags]}——该词**所有**笔记的标签（快照读）。
    判定顺序：先看词有没有复习家族标签（同词别处标过也算），再看卡是不是新卡。
    """
    todo, already, skipped = [], [], []
    for it in items:
        fam = family_tag(live_tags.get(it['noteId']) or [])
        if not fam and word_tags:
            fam = family_tag(word_tags.get(it['word']) or [])
        if fam:
            already.append(it)
            continue
        c = live_cards.get(it['cardId'])
        if c is None:
            skipped.append((it, '卡已不存在'))
        elif int(c['type']) != 0:
            skipped.append((it, '已不是新卡（type=%s）' % c['type']))
        else:
            todo.append(it)
    return todo, already, skipped


def _source_name(src):
    return 'stdin' if src == '-' else os.path.splitext(os.path.basename(src))[0]


def _out_dir(src, out_root=None):
    return os.path.join(out_root or SW.DEFAULT_OUT_ROOT, SW._slug(_source_name(src)))


# ============================================================================
# 主流程
# ============================================================================
def _print_by_deck(items, title):
    if not items:
        return
    print(title)
    for it in sorted(items, key=lambda x: x['deck']):
        print('  %-18s %s' % (it['deck'].split('::')[-1], it['word']))


def do_revert(a):
    out_dir = _out_dir(a.input, a.out)
    state_path = os.path.join(out_dir, STATE_NAME)
    if not os.path.exists(state_path):
        raise SystemExit('找不到回退记录 %s（先确认这张字幕/文字确实打过标签）' % state_path)
    st = textio.load_json(state_path)
    tag = st.get('tag') or ''
    nids = [int(x) for x in (st.get('note_ids') or [])]
    if not tag or not nids:
        raise SystemExit('回退记录不完整：%s' % state_path)
    print('回退：从 %d 个笔记上摘掉 %s' % (len(nids), tag))
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才摘）'))
    if not a.commit:
        return 0
    AK.remove_tags(nids, [tag])
    tags = {n['noteId']: (n.get('tags') or []) for n in AK.notes_info(nids)}
    left = [nid for nid in nids if tag in tags.get(nid, [])]
    print('已摘除 %d 个；残留 %d 个%s'
          % (len(nids) - len(left), len(left), ('：' + str(left[:10])) if left else ''))
    return 1 if left else 0


def do_tag(a):
    tag = tag_for(a.name)
    index = SW.VocabIndex.load(scopes=SCOPES)
    # 词级「是否已标过」要看过整个 0-词汇（含 4-复习 等子牌组）的笔记标签；
    # 取词仍只认三个词卡组，所以标签检查单独建一份只读索引。
    tag_index = SW.VocabIndex.load(scopes=(JD.DECK_VOCAB,))
    result = SW.extract(a.input, scopes=SCOPES, out_root=a.out,
                        min_occ=a.min_occ, include_names=a.include_names,
                        include_phrases=a.include_phrases, index=index)
    out_dir = result['meta']['out_dir']
    words = result['words']
    old = os.path.join(out_dir, 'words.json')
    if not words and os.path.exists(old):
        # 全部已学完再跑：别拿空列表覆盖上一次的完整提取结果。
        print('')
        print('⚠ 本次没有新的可标记词；保留上一次的提取结果：%s' % old)
        return 0
    if not a.no_write:
        paths = SW.write_outputs(
            result, out_dir,
            next_hint='> 回退：`python code\\tools\\subtitle_tag.py "%s" --revert --commit`'
                      % a.input)
        print('')
        print('已写出：')
        for p in paths:
            print('  %s' % p)

    # ---- --limit 只截断「这次打标」的词，产物仍写全量 ----
    tag_words = words[:a.limit] if a.limit and a.limit > 0 else words
    items = pick_items(tag_words,
                       exclude=[x for x in (a.exclude or '').split(',') if x.strip()])
    if not items:
        print('')
        print('这次没有可标记的词（词表被 --exclude 剔空了，或字幕没命中）。')
        return 0

    # ---- 现场读：已有标签 + 卡状态（快照之后被学过的剔除）----
    live_tags = {n['noteId']: (n.get('tags') or [])
                 for n in AK.notes_info([it['noteId'] for it in items])}
    live_cards = {c['cardId']: c
                  for c in AK.cards_info([it['cardId'] for it in items])}
    # 同词可能在多个牌组各有一张笔记：把该词所有笔记的标签都取来，
    # 只要任意一张已经带 复习::*，这个词就算「标过」，不再二次打标。
    word_tags = {}
    for it in items:
        ts = word_tags.setdefault(it['word'], set())
        for e in tag_index.entries.get(it['word'], ()):
            ts.update(e.tags or ())
    word_tags = {w: sorted(ts) for w, ts in word_tags.items()}
    todo, already, skipped = plan_apply(items, live_cards, live_tags, tag,
                                        word_tags=word_tags)

    print('')
    print('标签：%s' % tag)
    print('模式：%s' % ('★ 真写库' if a.commit else '演练（不写库，加 --commit 才写）'))
    print('可标记 %d 个词；已带复习标签 %d 个；本次要打 %d 个'
          % (len(items), len(already), len(todo)))
    _print_by_deck(todo, '')
    if already:
        names = [it['word'] for it in already]
        shown = '、'.join(names[:20])
        if len(names) > 20:
            shown += ' …（共 %d 个）' % len(names)
        print('（已带复习标签，跳过）：' + shown)
    for it, why in skipped:
        print('  ⛔ %-18s %s  %s' % (it['deck'].split('::')[-1], it['word'], why))

    if not todo:
        print('')
        print('无需变更。')
        return 0
    if not a.commit:
        print('')
        print('演练结束，未写库。确认无误后加 --commit。')
        print('（回退记录会写到 %s）' % os.path.join(out_dir, STATE_NAME))
        return 0

    AK.add_tags([it['noteId'] for it in todo], [tag])
    tags = {n['noteId']: (n.get('tags') or [])
            for n in AK.notes_info([it['noteId'] for it in todo])}
    bad = [it['word'] for it in todo if tag not in tags.get(it['noteId'], [])]
    textio.dump_json({
        'tag': tag,
        'source': a.input,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'note_ids': [it['noteId'] for it in todo],
        'words': [{'word': it['word'], 'deck': it['deck'], 'noteId': it['noteId']}
                  for it in todo],
    }, os.path.join(out_dir, STATE_NAME))

    print('')
    print('=' * 88)
    print('写入结果')
    print('=' * 88)
    print('  已打标签 %d 个；回读校验%s'
          % (len(todo), '通过' if not bad else ('失败：' + '、'.join(bad))))
    if bad:
        print('  ⚠ 校验失败的词，请立即跑 --revert 回退，并把上述词报给用户。')
    print('')
    print('回退记录：%s' % os.path.join(out_dir, STATE_NAME))
    print('Anki 浏览器搜索：tag:"%s"' % tag)
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='字幕/文字 → 三个词汇卡组里还没学、也没被复习标过的词，打 复习::<名称>（只打标签，不改 due）')
    ap.add_argument('input', help='字幕（.srt/.vtt/.ass/.txt）或 - 读 stdin')
    ap.add_argument('--name', default=None,
                    help='来源名（如 ヤニねこ）→ 标签 复习::<名称>；--revert 时可省')
    ap.add_argument('--out', default=None, help='产物目录（默认 data/subtitle_review/<输入名>）')
    ap.add_argument('--min-occ', type=int, default=1, help='至少出现 N 次（默认 1）')
    ap.add_argument('--limit', type=int, default=0, help='只取前 N 个词（0=全部）')
    ap.add_argument('--exclude', default=None, help='逗号分隔，剔除这些词（如 ウンコ,まつ）')
    ap.add_argument('--include-names', action='store_true', help='保留人名/专名')
    ap.add_argument('--include-phrases', action='store_true', help='保留惯用句/语气词')
    ap.add_argument('--no-write', action='store_true', help='只打印，不写提取产物')
    ap.add_argument('--revert', action='store_true', help='按 tags_applied.json 摘掉本标签')
    ap.add_argument('--commit', action='store_true', help='真写库（不加则只演练）')
    a = ap.parse_args(argv)
    if not a.revert and not a.name:
        ap.error('打标签需要 --name（示例：--name ヤニねこ）；回退才可省略')
    with AK.guard():
        if a.revert:
            return do_revert(a)
        return do_tag(a)


if __name__ == '__main__':
    raise SystemExit(main())
