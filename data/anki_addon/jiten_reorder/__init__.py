# -*- coding: utf-8 -*-
"""素材生词新卡：把 ``due``（新卡队列位置）写成 ``JitenAnimeRank`` 的数字。

用户口径（2026-10-15/16）：数字越小＝动漫词频越高＝越早学到。

为什么非得在 Anki 内部做：AnkiConnect（这个分支）把 ``due``/``type``/``queue`` 列为
protected —— ``setSpecificValueOfCard`` 只允许 factor/ivl/reps/lapses/did/flags，
写 ``due`` 报 ``Use native scheduling commands for protected state``
（源码 ``legacy.py`` 的 ``expert_card`` 白名单）；而新版 Anki 的新卡队列又没有
「按字段排序」选项，只看位置。所以位置只能在这里（Anki 进程内）直接写。

行为
----
* 只动 ``is:new`` 的卡（新卡的 ``due`` 就是队列位置）；学习/复习中的卡一律不碰。
* 位置 = ``int(JitenAnimeRank 字段)``；字段空/非数字 → 999999（自然排最后）。
* 幂等：只改不一致的卡。
* 每次启动 Anki（profile 打开）静默跑一遍；也可用 工具 →「按 JitenAnimeRank 重排
  素材生词新卡」手动跑（会弹结果，含回读校验）。
* 改哪些牌组/字段、是否自动跑，见同目录 ``config.json``。

回退：位置只是排序键，改回去不影响任何学习进度；注意字段本身没被改动。
"""
from aqt import mw, gui_hooks
from aqt.qt import QAction
from aqt.utils import showInfo

DEFAULT_DECKS = ['0-日本语学习::0-词汇::0-素材生词']
DEFAULT_FIELD = 'JitenAnimeRank'
NO_RANK = 999999
MENU_LABEL = '按 JitenAnimeRank 重排素材生词新卡'


def _cfg():
    try:
        c = mw.addonManager.getConfig(__name__) or {}
    except Exception:                                   # noqa: BLE001
        c = {}
    decks = c.get('decks') or DEFAULT_DECKS
    if isinstance(decks, str):
        decks = [decks]
    return {'decks': list(decks),
            'field': c.get('field') or DEFAULT_FIELD,
            'autoRun': bool(c.get('autoRun', True))}


def _position(note, field):
    """这张笔记该排的位置＝字段数字；空/非数字 → 999999。"""
    try:
        raw = note[field]
    except Exception:                                   # noqa: BLE001
        return NO_RANK
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return NO_RANK


def _write(col, card, pos):
    """把新卡位置写进去；优先走 ORM，失败退回直接写 cards 表。"""
    card.due = pos
    try:
        col.update_card(card)
        return True
    except Exception:                                   # noqa: BLE001
        pass
    try:
        col.db.execute('update cards set due=? where id=?', pos, card.id)
        col.db.commit()
        return True
    except Exception:                                   # noqa: BLE001
        return False


def reorder(verbose=False):
    col = mw.col
    if col is None:
        return None
    cfg = _cfg()
    field = cfg['field']
    stats = {'total': 0, 'changed': 0, 'missing_decks': [], 'failed': 0,
             'verify_bad': 0, 'samples': []}
    touched = []
    for deck in cfg['decks']:
        try:
            d = col.decks.by_name(deck)
        except Exception:                               # noqa: BLE001
            d = None
        if not d:
            stats['missing_decks'].append(deck)
            continue
        try:
            cids = col.find_cards('did:%d is:new' % d['id'])
        except Exception as exc:                        # noqa: BLE001
            stats['missing_decks'].append('%s（查询失败 %s）' % (deck, exc))
            continue
        for cid in cids:
            card = col.get_card(cid)
            note = card.note()
            pos = _position(note, field)
            stats['total'] += 1
            if card.due == pos:
                continue
            if len(stats['samples']) < 5:
                stats['samples'].append((note.fields[2] if len(note.fields) > 2 else '',
                                         card.due, pos))
            if _write(col, card, pos):
                stats['changed'] += 1
                touched.append((cid, pos))
            else:
                stats['failed'] += 1
    # 回读校验（只查刚写过的）
    for cid, pos in touched[:200]:
        try:
            if col.get_card(cid).due != pos:
                stats['verify_bad'] += 1
        except Exception:                               # noqa: BLE001
            stats['verify_bad'] += 1
    if stats['changed']:
        try:
            mw.reset()
        except Exception:                               # noqa: BLE001
            pass
    if verbose:
        msg = ('新卡 %d 张：改了 %d 张位置（失败 %d，回读不符 %d）\n'
               % (stats['total'], stats['changed'], stats['failed'],
                  stats['verify_bad']))
        if stats['samples']:
            msg += '\n前几例（词 / 原位置 → 新位置）：\n'
            for w, old, new in stats['samples']:
                msg += '  %s  %s → %s\n' % (w or '(无名)', old, new)
        if stats['missing_decks']:
            msg += '\n找不到/查不了：%s\n' % '、'.join(stats['missing_decks'])
        showInfo(msg, title=MENU_LABEL)
    else:
        print('[jiten_reorder] 新卡 %d 张，改了 %d 张位置' % (stats['total'],
                                                       stats['changed']))
    return stats


def _auto():
    try:
        if _cfg()['autoRun']:
            reorder(verbose=False)
    except Exception as exc:                            # noqa: BLE001
        print('[jiten_reorder] 自动重排失败：%s: %s' % (type(exc).__name__, exc))


def _menu():
    a = QAction(MENU_LABEL, mw)
    a.triggered.connect(lambda: reorder(verbose=True))
    mw.form.menuTools.addAction(a)


_menu()
gui_hooks.profile_did_open.append(_auto)
