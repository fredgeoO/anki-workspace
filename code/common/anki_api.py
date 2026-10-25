# -*- coding: utf-8 -*-
r"""Anki 访问的唯一接口 —— AnkiConnect 传输 + 类型化读写 + 学习记录 + 离线快照。

为什么要有这个模块
------------------
2026-10-08 之前，「跟 Anki 说话」这件事在仓库里被抄了 **26 遍**：24 个脚本各自
`def anki(action, **params)`，再加 `.dsh/skills/jp-anki-pipeline/scripts/preflight.py`
与 `core6000-analysis/fetch.py`。抄走的不只是那 6 行 HTTP 样板，还有一整套**判断**：

* 超时该给多少（20 / 30 / 120 / 300 / 600 秒，五种）；
* URL 从哪来（写死；`ANKI_URL`；`ANKICONNECT_URL` —— 各认一个）；
* 出错是抛 `RuntimeError`、还是 `SystemExit('AnkiConnect 错误 [action]…')`、
  还是"连不上，请先启动 Anki"的人话；
* `notesInfo` / `cardsInfo` 一次问多少条（100 / 200 / 400 / 500）；
* 读回来的字段怎么拆（`{k: v['value']}` 抄了 8 遍）。

于是"改一处行为要改 26 个地方"，而且改漏了没人知道。本模块把这份判断收成一处，
其他脚本只表达**意图**：`AK.notes_map(ids)`、`AK.set_card_due(cid, due)`、
`AK.Snapshot.open(live_copy=True).reviewed_since(3)`。

约定（新代码请照做）
--------------------
1. **不要再写 `def anki()`**。要什么动作就用下面的类型化函数；
   没有对应函数的动作走 `AK.call('动作名', **参数)`。
   `python code/common/anki_api.py audit` 会扫出违反这条的文件。
2. **不要再自己 `sqlite3.connect` 快照**。离线读用 `AK.Snapshot`（只读、`mode=ro`、
   自带 `unicase` collation 与 `notetypes/fields` 解码）。
3. **改库只走 AnkiConnect**。`Snapshot` 没有任何写方法 —— 直连 sqlite 写 live 收藏
   有锁库/写坏的风险，本模块不开这个口子。
4. **模块 import 无副作用、无 I/O**：Anki 没开也能 `import anki_api`。

三条数据通道
------------
    AnkiConnect(127.0.0.1:8765)  ← 唯一写路径，也是在线读路径
    Snapshot(path 或 live 副本)   ← 离线只读读路径（学习记录/卡片资料）

快速上手
--------
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'common'))
    import anki_api as AK

    # 读卡片资料
    ids = AK.find_notes('deck:"0-日本语学习::2-例句" tag:动画::平家物语::第02集')
    by_id = AK.notes_map(ids)                      # {noteId: note}
    flds = AK.field_values(by_id[ids[0]])          # {字段名: 值}

    # 读学习记录（近 3 天答得不好的）
    nids = AK.find_notes(AK.rated_query(3, 'again'))
    rows = AK.card_reviews(nids)                   # AnkiConnect cardReviews
    snap = AK.Snapshot.open(live_copy=True)        # 或 open(path=...) 读固定快照
    for r in snap.reviewed_since(3, ease='again'):
        ...

    # 写卡片资料（各脚本自己的 --commit 闸门负责决定要不要走到这里）
    AK.update_note_fields(nid, {'AINote': html})
    AK.verify_note_fields({nid: {'AINote': html}})  # 写后回读，返回不一致的字段

    # CLI 脚本的失败观感：Anki 没开时给中文提示，而不是 traceback
    with AK.guard():
        ...

配置（都能不设）
----------------
    ANKI_URL / ANKICONNECT_URL      默认 http://127.0.0.1:8765（两个名字都认）
    ANKI_TIMEOUT                    默认 300 秒
    ANKI_CHUNK                      默认 200（notesInfo / cardsInfo 的批量）
    ANKI_PROFILE                    live 收藏夹所在资料夹（见 paths.LIVE_COLLECTION）

子命令
------
    python code/common/anki_api.py check [--json]        体检：版本/牌组/笔记类型/媒体数
    python code/common/anki_api.py count "<查询串>"       只数张数
    python code/common/anki_api.py tags                  列出所有标签
    python code/common/anki_api.py revlog --days 3 [--ease again] [--source anki|snapshot] [--json]
    python code/common/anki_api.py exec <动作> [--params '{"query":"deck:*"}']   逃生口
    python code/common/anki_api.py audit [--strict] [--all]   扫全仓重复客户端（防回退）
"""
import argparse
import contextlib
import json
import os
import random
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:                      # 让 `import anki_api` 从任何 cwd 都成立
    sys.path.insert(0, _HERE)
import paths as WSP  # noqa: E402
import textio  # noqa: E402  UTF-8 stdio 唯一入口（code/common/textio.py）

# ============================================================================
# 常量与配置
# ============================================================================
DEFAULT_URL = 'http://127.0.0.1:8765'
DEFAULT_TIMEOUT = 300          # 秒；与历史上多数脚本一致（20/30/600 的调用方显式传）
DEFAULT_CHUNK = 200            # notesInfo / cardsInfo 一次问多少条
API_VERSION = 6

# revlog.ease 的说法（Anki 的四个按钮）
EASE = {'again': 1, 'hard': 2, 'good': 3, 'easy': 4}
EASE_CN = {1: '重来', 2: '困难', 3: '良好', 4: '简单'}

# 字段值在 AnkiConnect 里是 {'value':…, 'order':…}；快照里是 \x1f 分隔的裸串
FLD_SEP = '\x1f'
DECK_SEP = '\x1f'              # decks.name 里的层级分隔符（读出来要换成 ::）


class AnkiError(RuntimeError):
    """本模块所有失败的基类。

    兼容性说明：历史脚本有的 `except RuntimeError`、有的 `except AnkiError`，
    继承 RuntimeError 让两种写法都还成立。
    """


class AnkiUnavailable(AnkiError):
    """连不上 AnkiConnect（Anki 没开 / 插件没装 / 端口被占 / 超时）。"""


class AnkiActionError(AnkiError):
    """AnkiConnect 收到了请求但回了 error。"""

    def __init__(self, action, error, url=None):
        self.action = action
        self.error = error
        self.url = url
        super(AnkiActionError, self).__init__(
            'AnkiConnect 错误 [%s]: %s' % (action, error))


class SnapshotError(AnkiError):
    """离线快照读不了（文件不存在 / 不是合法收藏库 / 被锁）。"""


def load_config(**overrides):
    """URL / 超时 / 批量：overrides > 环境变量 > 默认值。

    两个 URL 环境变量都认 —— 历史上 `today_weak.py` 认 `ANKI_URL`，
    `vocab_cover/*` 认 `ANKICONNECT_URL`，收拢后不再挑。
    """
    cfg = {
        'url': (os.environ.get('ANKI_URL')
                or os.environ.get('ANKICONNECT_URL')
                or DEFAULT_URL),
        'timeout': DEFAULT_TIMEOUT,
        'chunk': DEFAULT_CHUNK,
    }
    for key, env in (('timeout', 'ANKI_TIMEOUT'), ('chunk', 'ANKI_CHUNK')):
        raw = os.environ.get(env)
        if raw:
            try:
                cfg[key] = int(raw)
            except ValueError:
                pass
    for key, val in overrides.items():
        if val is not None:
            cfg[key] = val
    cfg['url'] = str(cfg['url']).rstrip('/')
    cfg['timeout'] = int(cfg['timeout'])
    cfg['chunk'] = max(1, int(cfg['chunk']))
    return cfg


CONFIG = load_config()          # 进程启动时读一次；Client 可以单独给


# ============================================================================
# 小工具
# ============================================================================
def chunks(seq, n=None):
    """把序列切块（默认 CONFIG['chunk']）。

    ⚠ `notesInfo` / `cardsInfo` 的批量大小就在这里，别再各写各的 100/200/400/500。
    """
    n = max(1, int(n or CONFIG['chunk']))
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def dedupe_ids(ids):
    """int 化 + 去重 + 保持顺序。AnkiConnect 收到重复 id 会重复返回。"""
    out, seen = [], set()
    for raw in ids or ():
        try:
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val not in seen:
            seen.add(val)
            out.append(val)
    return out


def friendly(exc):
    """把异常翻成给用户看的中文（CLI 用）。

    `AnkiUnavailable` 的 message 本身就是可读的一句（脚本常常直接 `print(e)`），
    这里再补一行"离线段"的出路 —— 那是 CLI 才需要知道的。
    """
    if isinstance(exc, AnkiUnavailable):
        return '%s\n或用离线快照（--source snapshot / anki_api.Snapshot.open）。' % exc
    return str(exc)


def _unavailable(url, reason):
    """造一个自解释的"连不上"异常（message 单行，方便塞进表格里打印）。"""
    err = AnkiUnavailable(
        '连不上 AnkiConnect (%s)：%s。请确认 Anki 已启动、AnkiConnect 插件已启用。'
        % (url, reason))
    err.url = url
    return err


@contextlib.contextmanager
def guard():
    """CLI 用：把 AnkiError 变成 SystemExit(friendly)（不出 traceback）。

    历史上 activate / mine / mine_audio 用 `SystemExit('AnkiConnect 错误 [%s]: %s')`，
    today_weak 用带"请先启动 Anki"的 SystemExit；两者在这里统一。
    """
    try:
        yield
    except AnkiError as exc:            # noqa: BLE001
        raise SystemExit(friendly(exc))


# ============================================================================
# 传输层
# ============================================================================
class Client(object):
    """一个 AnkiConnect 端点。模块级函数用的是默认 client。"""

    def __init__(self, url=None, timeout=None, chunk=None):
        self.url = str(url or CONFIG['url']).rstrip('/')
        self.timeout = int(timeout or CONFIG['timeout'])
        self.chunk = int(chunk or CONFIG['chunk'])

    def __repr__(self):
        return 'Client(%s, timeout=%ss, chunk=%s)' % (self.url, self.timeout, self.chunk)

    def call(self, action, timeout=None, **params):
        """发一个 AnkiConnect 动作，返回 result。失败抛 AnkiUnavailable / AnkiActionError。"""
        body = json.dumps({'action': action, 'version': API_VERSION, 'params': params},
                          ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            self.url, data=body,
            headers={'Content-Type': 'application/json; charset=utf-8'})
        try:
            raw = urllib.request.urlopen(req, timeout=timeout or self.timeout).read()
        except urllib.error.HTTPError as exc:               # 端点活着但拒了
            detail = ''
            try:
                detail = exc.read().decode('utf-8', 'replace')[:200]
            except Exception:                               # noqa: BLE001
                pass
            raise _unavailable(self.url, 'HTTP %s %s' % (exc.code, detail)) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise _unavailable(self.url, '%s: %s' % (type(exc).__name__, exc)) from exc
        try:
            resp = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            raise _unavailable(self.url, '返回的不是合法 JSON：%s' % exc) from exc
        if isinstance(resp, dict) and resp.get('error'):
            raise AnkiActionError(action, resp['error'], self.url)
        if not isinstance(resp, dict) or 'result' not in resp:
            raise AnkiActionError(action, '响应里没有 result：%r' % (resp,), self.url)
        return resp['result']

    # ---- 体检 -------------------------------------------------------------
    def health(self):
        """不抛异常的健康检查，给"开工前体检"用。"""
        info = {'ok': False, 'url': self.url, 'version': None, 'error': None}
        try:
            info['version'] = self.call('version', timeout=min(self.timeout, 30))
            info['ok'] = True
        except AnkiError as exc:                            # noqa: BLE001
            info['error'] = friendly(exc)
        return info


_DEFAULT_CLIENT = None


def default_client():
    """模块级函数用的默认 client（首次调用才建，import 不发请求）。"""
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = Client()
    return _DEFAULT_CLIENT


def set_default_client(client):
    """测试/特殊场景换掉默认 client。"""
    global _DEFAULT_CLIENT
    _DEFAULT_CLIENT = client
    return client


def call(action, timeout=None, **params):
    """裸动作（没有类型化包装的动作走这里，例如非标准的 modelFieldAdd）。"""
    return default_client().call(action, timeout=timeout, **params)


def health():
    return default_client().health()


# ============================================================================
# 读：检索与批量取资料
# ============================================================================
def find_notes(query, limit=None):
    """Anki 查询串 → [noteId]。limit 在最后截断。"""
    ids = call('findNotes', query=query) or []
    return [int(i) for i in (ids[:limit] if limit else ids)]


def find_cards(query, limit=None):
    """Anki 查询串 → [cardId]。"""
    cids = call('findCards', query=query) or []
    return [int(i) for i in (cids[:limit] if limit else cids)]


def count(query):
    """只数张数（不把 id 拉回来）。体检脚本里用得最多。"""
    return len(find_notes(query))


def notes_info(ids, chunk=None):
    """[noteId] → [note 对象]（分块，保持顺序；不存在的 id 会被 AnkiConnect 静默丢掉）。

    注意：调用方要按 `notes_map` / `_by_id` 判定"哪张没了"，别靠数组下标对齐。
    """
    out = []
    ids = dedupe_ids(ids)
    for part in chunks(ids, chunk):
        out.extend(call('notesInfo', notes=part) or [])
    return out


def notes_map(ids, chunk=None):
    """[noteId] → {noteId: note}。绝大多数调用方要的就是这个。"""
    return {int(n['noteId']): n for n in notes_info(ids, chunk=chunk)}


def cards_info(ids, chunk=None):
    """[cardId] → [card 对象]（分块，保持顺序）。"""
    out = []
    ids = dedupe_ids(ids)
    for part in chunks(ids, chunk):
        out.extend(call('cardsInfo', cards=part) or [])
    return out


def cards_map(ids, chunk=None):
    return {int(c['cardId']): c for c in cards_info(ids, chunk=chunk)}


def cards_of_notes(note_ids, chunk=100):
    """笔记 → 它的卡（分块拼 `nid:` 查询，避免一条几千 id 的巨串查询串）。"""
    out = []
    for part in chunks(dedupe_ids(note_ids), max(1, int(chunk))):
        q = 'nid:' + ','.join(str(i) for i in part)
        out.extend(find_cards(q))
    return dedupe_ids(out)


def field(note, name, default=''):
    """单个字段值（note 来自 notes_info / Snapshot.notes）。"""
    flds = (note or {}).get('fields') or {}
    got = flds.get(name)
    if isinstance(got, dict):
        return got.get('value', default)
    return got if got is not None else default


def field_values(note, names=None):
    """note → {字段名: 值}。names 给定时按该顺序输出（缺的补空串）。"""
    flds = (note or {}).get('fields') or {}
    if names:
        return {k: field(note, k) for k in names}
    return {k: (v or {}).get('value', '') if isinstance(v, dict) else (v or '')
            for k, v in flds.items()}


def note_values(ids, names=None, chunk=None):
    """[noteId] → {noteId: {字段名: 值}}（写库前"看真值"要用它）。"""
    out = {}
    for note in notes_info(ids, chunk=chunk):
        out[int(note['noteId'])] = field_values(note, names)
    return out


def deck_names():
    return call('deckNames') or []


def deck_names_and_ids():
    return call('deckNamesAndIds') or {}


def deck_config(deck):
    """某个牌组的配置（new.perDay = 每日新卡上限）。读不到返回 {}。"""
    try:
        return call('getDeckConfig', deck=deck) or {}
    except AnkiError:
        return {}


def deck_new_per_day(deck):
    """每日新卡上限；读不到或为 0 时返回 0（= 这个牌组不出新卡）。"""
    conf = deck_config(deck)
    try:
        return int((conf.get('new') or {}).get('perDay') or 0)
    except (TypeError, ValueError):
        return 0


def tags():
    return call('getTags') or []


def model_names():
    return call('modelNames') or []


def model_field_names(model):
    return call('modelFieldNames', modelName=model) or []


def model_templates(model):
    return call('modelTemplates', modelName=model) or {}


def media_names(pattern='*'):
    return call('getMediaFilesNames', pattern=pattern) or []


def cards_reviewed_by_day():
    return call('getNumCardsReviewedByDay') or []


# ---- 学习记录（在线） -------------------------------------------------------
def rated_query(days, ease=None, deck=None):
    """`rated:N[:R]` 查询串（N 天内有作答记录；R 是按钮）。

    ease 收 'again'/'hard'/'good'/'easy'，也收 1-4。
    """
    q = 'rated:%d' % int(days)
    if ease is not None:
        code = EASE.get(str(ease).lower(), ease)
        q += ':%s' % int(code)
    if deck:
        q = 'deck:"%s" %s' % (deck, q)
    return q


def reviewed_notes(days, ease=None, deck=None):
    """近 N 天有作答记录的笔记 id（在线；离线用 Snapshot.reviewed_since）。"""
    return find_notes(rated_query(days, ease=ease, deck=deck))


def answered_cards(days, deck=None):
    """近 N 天作答过的**卡**张数。"""
    return len(find_cards(rated_query(days, deck=deck)))


def card_reviews(card_ids=None, deck=None, start_id=0):
    """revlog 原始行（AnkiConnect cardReviews）。

    给了 card_ids 就逐张取；否则按牌组一次性取（deck 必给，AnkiConnect 要这个参数）。
    """
    rows = []
    if card_ids:
        for cid in dedupe_ids(card_ids):
            rows.extend(call('cardReviews', deck=deck or '', startID=int(start_id),
                             card=cid) or [])
        return _norm_reviews(rows)
    if not deck:
        raise AnkiError('card_reviews 需要 card_ids 或 deck 其中之一')
    rows = call('cardReviews', deck=deck, startID=int(start_id)) or []
    return _norm_reviews(rows)


def _norm_reviews(rows):
    """cardReviews 的行 → 统一口径的 dict（字段名与 revlog 列一一对应）。"""
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append({
                'revlogId': int(r.get('id') or 0),
                'cardId': int(r.get('cid') or 0),
                'ease': int(r.get('ease') or 0),
                'ivl': int(r.get('ivl') or 0),
                'lastIvl': int(r.get('lastIvl') or 0),
                'factor': int(r.get('factor') or 0),
                'timeMs': int(r.get('time') or 0),
                'type': int(r.get('type') or 0),
            })
    return out


# ============================================================================
# 写：字段 / 标签 / 媒体 / 牌组 / 队列
# ============================================================================
def new_note(deck, model, fields, tags=None, allow_duplicate=False,
             duplicate_scope='collection'):
    """addNotes 的载荷（形状与历史脚本一致，别在调用方手搭 dict）。"""
    return {
        'deckName': deck,
        'modelName': model,
        'fields': dict(fields or {}),
        'options': {'allowDuplicate': bool(allow_duplicate),
                    'duplicateScope': duplicate_scope},
        'tags': list(tags or []),
    }


def add_notes(notes, chunk=None):
    """批量入库 → [noteId 或 None]，**与输入等长**（None = 被拒，多半是查重）。

    chunk 给了才分批（默认一把提交，保持历史行为与返回顺序）。
    """
    notes = list(notes or [])
    if not notes:
        return []
    if not chunk:
        return list(call('addNotes', notes=notes) or [])
    out = []
    for part in chunks(notes, chunk):
        out.extend(call('addNotes', notes=part) or [])
    return out


def update_note_fields(note_id, fields):
    """写字段。⚠ Anki 浏览器开着看那张卡时可能不生效 —— 写完用 verify_note_fields 回读。"""
    return call('updateNoteFields', note={'id': int(note_id), 'fields': dict(fields or {})})


def delete_notes(note_ids):
    """删除笔记（连同它的卡）。**不可撤销**：调用前自己打印将删清单并核对。"""
    ids = dedupe_ids(note_ids)
    if not ids:
        return None
    return call('deleteNotes', notes=ids)


def update_notes(pairs):
    """[(noteId, fields), …] → [(noteId, 是否成功)]。"""
    out = []
    for note_id, fields in pairs:
        try:
            update_note_fields(note_id, fields)
            out.append((int(note_id), True))
        except AnkiActionError:
            out.append((int(note_id), False))
    return out


def verify_note_fields(ids, expected=None, settle=0.5, chunk=None):
    """写后回读：返回 {noteId: [有问题的字段名, …]}（空 dict = 全部一致）。

    不查这一条，`updateNoteFields` 静默失败（浏览器开着那类）会被当成写成功。
    笔记不存在时给哨兵 `'<noteId 不存在>'`。

    ★ 两种调用方式都认：`(expected)` 与 `(ids, expected)`。历史上两种写法都有
    （`cards.py`/`attach_audio` 传一个参数、`fix_word_audio.py` 传两个），
    而旧签名只认两个 —— 单参数调用时 `expected` 被当成 None，**静默返回空字典**，
    等于回读校验根本没跑。2026-10-22 修。
    """
    if expected is None:
        expected = ids
    if settle:
        time.sleep(settle)
    want = {int(k): dict(v or {}) for k, v in (expected or {}).items()}
    live = note_values(list(want), chunk=chunk)
    bad = {}
    for nid, fields in want.items():
        got = live.get(nid)
        if got is None:
            bad[nid] = ['<noteId 不存在>']
            continue
        wrong = [k for k, v in fields.items() if got.get(k, '') != v]
        if wrong:
            bad[nid] = wrong
    return bad


def add_tags(note_ids, tags):
    return call('addTags', notes=dedupe_ids(note_ids), tags=_tag_str(tags))


def remove_tags(note_ids, tags):
    return call('removeTags', notes=dedupe_ids(note_ids), tags=_tag_str(tags))


def replace_tags(note_ids, old, new):
    # AnkiConnect 的参数名是下划线（tag_to_replace / replace_with_tag）。
    # 2026-10-17 修：原先传驼峰 tagToReplace / replaceWithTag，AnkiConnect 认不出，
    # 每次都报 `replaceTags() missing 2 required positional arguments` —— 一个都用不了。
    return call('replaceTags', notes=dedupe_ids(note_ids),
                tag_to_replace=old, replace_with_tag=new)


def _tag_str(tags):
    if isinstance(tags, (list, tuple, set)):
        return ' '.join(str(t) for t in tags if str(t).strip())
    return str(tags or '')


def store_media_file(filename, path=None, url=None, data=None, delete_existing=True):
    """上传媒体。path/url/data 三选一。"""
    params = {'filename': filename, 'deleteExisting': bool(delete_existing)}
    if path is not None:
        params['path'] = os.path.abspath(path)
    elif url is not None:
        params['url'] = url
    elif data is not None:
        params['data'] = data
    else:
        raise AnkiError('store_media_file 需要 path / url / data 之一')
    return call('storeMediaFile', **params)


def attach_audio(note_id, field_name, filename, path=None, url=None, verify=True,
                 settle=0.5):
    """挂音频：上传（可选）→ 字段写 `[sound:文件名]` → 回读确认。

    mine_audio.py / core6000_example.py 各抄了一遍的流程。
    """
    if path is not None or url is not None:
        store_media_file(filename, path=path, url=url, delete_existing=True)
    value = '[sound:%s]' % filename
    update_note_fields(note_id, {field_name: value})
    if verify:
        still = media_names(filename)
        problems = []
        if filename not in set(still or []):
            problems.append('媒体库里没有 %s' % filename)
        bad = verify_note_fields({note_id: {field_name: value}}, settle=settle)
        problems.extend('%s 回读不一致' % f for f in bad.get(int(note_id), []))
        return problems
    return []


def delete_media_file(filename):
    return call('deleteMediaFile', filename=filename)


def create_deck(deck):
    return call('createDeck', deck=deck)


def model_exists(model):
    """笔记类型是否已存在（`createModel` 不是幂等的，建之前必须先问）。"""
    return model in (model_names() or [])


def create_model(model, fields, templates, css=''):
    """新建笔记类型 → 模型名。

    * `fields` 顺序 = 卡面字段顺序，**首字段就是 Anki 的查重字段**；
    * `templates` = [{'Name': …, 'Front': …, 'Back': …}]；
    * 已存在时不覆盖（Anki 会直接报错），所以调用前用 `model_exists()` 判一次。
      改现有模板走 `update_model_templates` / `update_model_styling`，别重建。
    """
    tpl = [{'Name': t['Name'], 'Front': t['Front'], 'Back': t['Back']} for t in templates]
    return call('createModel', modelName=model, inOrderFields=list(fields),
                css=css or '', isCloze=False, cardTemplates=tpl)


def update_model_templates(model, templates):
    """改现有笔记类型的卡面模板（只在显式要求时用）。"""
    tpl = {t['Name']: {'Front': t['Front'], 'Back': t['Back']} for t in templates}
    return call('updateModelTemplates', model={'name': model, 'templates': tpl})


def update_model_styling(model, css):
    return call('updateModelStyling', model={'name': model, 'css': css})


def model_css(model):
    try:
        return (call('modelStyling', modelName=model) or {}).get('css', '')
    except AnkiError:
        return ''


def change_deck(card_ids, deck):
    return call('changeDeck', cards=dedupe_ids(card_ids), deck=deck)


def suspend(card_ids):
    return call('suspend', cards=dedupe_ids(card_ids))


def unsuspend(card_ids):
    return call('unsuspend', cards=dedupe_ids(card_ids))


def are_suspended(card_ids):
    return call('areSuspended', cards=dedupe_ids(card_ids))


def forget_cards(card_ids):
    return call('forgetCards', cards=dedupe_ids(card_ids))


def set_card_values(card_id, **values):
    """写卡的底层列（due / type / …）。keys 与 newValues 必须等长。"""
    keys = list(values)
    return call('setSpecificValueOfCard', card=int(card_id), keys=keys,
                newValues=[values[k] for k in keys])


def set_card_due(card_id, due):
    """改新卡队列位置（due 是排序键）。返回 True = Anki 确认写入。

    ⚠ AnkiConnect 对 due **必须**是 int —— 传字符串会静默不生效（activate.py 踩过）。
    """
    r = call('setSpecificValueOfCard', card=int(card_id), keys=['due'],
             newValues=[int(due)])
    return r == [True] or r is True


# ============================================================================
# 离线快照（只读）
# ============================================================================
def _unicase(a, b):
    """Anki 的 notetypes/fields 等表的 name 列带 COLLATE unicase —— 不注册就
    `no query solution`。每个连接都要注册。"""
    return (a > b) - (a < b)


def _deck_name(raw):
    return (raw or '').replace(DECK_SEP, '::')


def unique_dir(parent, prefix='tmp-', tries=100):
    """在 parent 下建一个唯一目录，**刻意不用 `tempfile.mkdtemp`**。

    2026-10-08 实测：本工作区在 DSH 文件沙箱（workspace-write）下运行时，
    `tempfile.mkdtemp` 建出来的目录带一个"拒绝"的 DACL —— 连进程自己往里写文件都报
    `PermissionError`（`icacls` 看它干脆是 Access is denied），而 `os.makedirs` 建的
    同级目录正常继承父目录 ACL。所以这里用 makedirs + 随机后缀自己拼唯一名。
    """
    parent = os.path.abspath(parent)
    os.makedirs(parent, exist_ok=True)
    for _ in range(int(tries)):
        cand = os.path.join(parent, '%s%d-%08x' % (prefix, os.getpid(),
                                                   random.getrandbits(32)))
        if os.path.exists(cand):
            continue
        try:
            os.makedirs(cand)                       # exist_ok=False：抢到就是我的
            return cand
        except FileExistsError:
            continue
        except OSError as exc:
            raise SnapshotError('建不出临时目录 %s：%s' % (cand, exc)) from exc
    raise SnapshotError('建不出临时目录（%s 下试了 %d 次）' % (parent, tries))


class Snapshot(object):
    """`collection.anki2` 的**只读**读取器（固定快照文件，或 live 收藏的临时副本）。

        snap = Snapshot.open()                     # paths.SNAP_ANKI_SNAP
        snap = Snapshot.open(path='data/snapshots/.../c.anki2')
        snap = Snapshot.open(live_copy=True)       # 复制 live 收藏（含 -wal/-shm）到临时目录
        with Snapshot.open(live_copy=True) as s:
            rows = s.reviewed_since(3, ease='again')

    ★ 没有任何写方法。改库只走 AnkiConnect（见模块头"约定"3）。
    """

    def __init__(self, path, con, tmpdir=None):
        self.path = path
        self.con = con
        self._tmpdir = tmpdir
        self._nt_cache = None

    # ---- 打开 / 关闭 ------------------------------------------------------
    @classmethod
    def open(cls, path=None, live_copy=False, copy_to=None):
        tmpdir = None
        if live_copy:
            src = WSP.LIVE_COLLECTION
            if not os.path.exists(src):
                raise SnapshotError('找不到 live 收藏：%s（ANKI_PROFILE 设对了吗？）' % src)
            # 副本放在 data/snapshots/ 下（工作区惯例：anki_revlog_analysis.py 也这么干）。
            # 不往系统 temp 里丢：沙箱下那里可能不可写，而且 42MB 的库放临时目录没意义。
            tmpdir = copy_to or unique_dir(WSP.SNAPSHOTS, 'live-')
            for suf in ('', '-wal', '-shm'):
                s = src + suf
                if os.path.exists(s):
                    shutil.copy2(s, os.path.join(tmpdir, 'c.anki2' + suf))
            path = os.path.join(tmpdir, 'c.anki2')
        else:
            path = path or WSP.SNAP_ANKI_SNAP
        if not os.path.exists(path):
            raise SnapshotError('快照不存在：%s' % path)
        try:
            con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
            con.create_collation('unicase', _unicase)
            con.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise SnapshotError('打不开快照 %s：%s' % (path, exc)) from exc
        return cls(path, con, tmpdir)

    def close(self):
        try:
            self.con.close()
        except sqlite3.Error:
            pass
        if self._tmpdir and os.path.isdir(self._tmpdir):
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # ---- 元数据 ----------------------------------------------------------
    def decks(self):
        """{deckId: 牌组名}（层级分隔符换成 `::`）。"""
        return {int(r['id']): _deck_name(r['name'])
                for r in self.con.execute('SELECT id, name FROM decks')}

    def deck_id(self, name):
        """牌组名（或它的父名）→ [deckId]，含所有子牌组。"""
        hits = []
        for did, dname in self.decks().items():
            if dname == name or dname.startswith(name + '::'):
                hits.append(did)
        return hits

    def notetype_map(self):
        """{noteTypeId: (名字, [字段名按 ord 排序])}。

        ⚠ 这里刻意**一条 SQL 取完再分组**：历史实现把 `notetypes` 的游标借给内层
        `fields` 查询复用，外层循环就只剩最后一行，于是 96% 的笔记解不出模型名
        （`model='?'`、名字退化成"(无名字)"）。2026-10-08 修。
        """
        if self._nt_cache is not None:
            return self._nt_cache
        names = {int(r['id']): r['name'] for r in
                 self.con.execute('SELECT id, name FROM notetypes')}
        cols = {}
        for r in self.con.execute('SELECT ntid, ord, name FROM fields ORDER BY ntid, ord'):
            cols.setdefault(int(r['ntid']), []).append(r['name'])
        self._nt_cache = {mid: (name, cols.get(mid, [])) for mid, name in names.items()}
        return self._nt_cache

    def notetype(self, mid):
        return self.notetype_map().get(int(mid), ('?', []))

    def split_fields(self, mid, flds):
        """`flds`（\\x1f 分隔）→ {字段名: 值}，字段名来自 note type 定义。"""
        _name, order = self.notetype(mid)
        vals = (flds or '').split(FLD_SEP)
        return {order[i]: vals[i] for i in range(min(len(order), len(vals)))}

    # ---- 学习记录 --------------------------------------------------------
    def revlog(self, since_ms=None, ease=None, limit=None, card_ids=None):
        """revlog 原始行：{revlogId, cardId, ease, ivl, lastIvl, factor, timeMs, type}。"""
        sql = ('SELECT id, cid, ease, ivl, lastIvl, factor, time, type FROM revlog')
        where, args = [], []
        if since_ms is not None:
            where.append('id >= ?')
            args.append(int(since_ms))
        codes = _ease_codes(ease)
        if codes:
            where.append('ease IN (%s)' % ','.join('?' * len(codes)))
            args.extend(codes)
        ids = dedupe_ids(card_ids or [])
        if ids:
            where.append('cid IN (%s)' % ','.join('?' * len(ids)))
            args.extend(ids)
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY id'
        if limit:
            sql += ' LIMIT %d' % int(limit)
        return [{
            'revlogId': int(r['id']),
            'cardId': int(r['cid']),
            'ease': int(r['ease']),
            'ivl': int(r['ivl']),
            'lastIvl': int(r['lastIvl']),
            'factor': int(r['factor']),
            'timeMs': int(r['time']),
            'type': int(r['type']),
        } for r in self.con.execute(sql, args)]

    def reviewed_rows(self, days=None, since_ms=None, ease=None):
        """revlog ⨝ cards ⨝ notes ⨝ decks —— 「今天/近 N 天答得不好的卡」的原始行。

        返回 [{cid, ease, nid, did, mid, flds, deck}]；`deck` 已把 \\x1f 换成 `::`。
        days 与 since_ms 二选一（days = 本地 0 点往前推 days-1 天，近似 Anki 换日）。
        """
        if days is not None and since_ms is None:
            since_ms = start_of_window_ms(days)
        sql = ('''SELECT r.cid, r.ease, c.nid, c.did, n.mid, n.flds, d.name AS deck
                  FROM revlog r
                  JOIN cards c ON c.id = r.cid
                  JOIN notes n ON n.id = c.nid
                  JOIN decks d ON d.id = c.did''')
        where, args = [], []
        if since_ms is not None:
            where.append('r.id >= ?')
            args.append(int(since_ms))
        codes = _ease_codes(ease)
        if codes:
            where.append('r.ease IN (%s)' % ','.join('?' * len(codes)))
            args.extend(codes)
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        return [{
            'cid': int(r['cid']), 'ease': int(r['ease']), 'nid': int(r['nid']),
            'did': int(r['did']), 'mid': int(r['mid']), 'flds': r['flds'] or '',
            'deck': _deck_name(r['deck']),
        } for r in self.con.execute(sql, args)]

    def reviewed_since(self, days, ease=None):
        """`reviewed_rows(days=…)` 的别名（口语化写法）。"""
        return self.reviewed_rows(days=days, ease=ease)

    def reviewed_card_count(self, days=None, since_ms=None):
        """窗口内**去重后**作答过的卡数（"同期作答卡片 N 张"那一项）。"""
        if days is not None and since_ms is None:
            since_ms = start_of_window_ms(days)
        sql = 'SELECT COUNT(DISTINCT cid) FROM revlog'
        args = []
        if since_ms is not None:
            sql += ' WHERE id >= ?'
            args.append(int(since_ms))
        return int(self.con.execute(sql, args).fetchone()[0])

    # ---- 卡片资料 --------------------------------------------------------
    def notes(self, ids=None, deck=None, limit=None):
        """[noteId] → [{noteId, modelName, tags, fields, mid}]（已解好字段名与标签）。

        deck 给定时取该牌组（含子牌组）里的笔记。ids 与 deck 都不给 = 全库（小心）。
        """
        sql = ('SELECT n.id AS nid, n.mid AS mid, n.tags AS tags, n.flds AS flds '
               'FROM notes n')
        where, args = [], []
        nids = dedupe_ids(ids or [])
        if nids:
            where.append('n.id IN (%s)' % ','.join('?' * len(nids)))
            args.extend(nids)
        if deck:
            dids = self.deck_id(deck)
            if not dids:
                return []
            where.append('EXISTS (SELECT 1 FROM cards c WHERE c.nid = n.id AND c.did IN (%s))'
                         % ','.join('?' * len(dids)))
            args.extend(dids)
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY n.id'
        if limit:
            sql += ' LIMIT %d' % int(limit)
        out = []
        for r in self.con.execute(sql, args):
            name, _order = self.notetype(r['mid'])
            out.append({
                'noteId': int(r['nid']),
                'mid': int(r['mid']),
                'modelName': name,
                'tags': (r['tags'] or '').split(),
                'fields': self.split_fields(r['mid'], r['flds']),
            })
        return out

    def notes_map(self, ids=None, deck=None, limit=None):
        return {n['noteId']: n for n in self.notes(ids=ids, deck=deck, limit=limit)}

    def cards(self, ids=None, note_ids=None, deck=None, limit=None, card_type=None,
              order=None):
        """[cardId] 或 [noteId] 或 deck → [{cardId, noteId, deckName, ord, type, queue,
        due, ivl, factor, reps, lapses, left}]。"""
        sql = ('''SELECT c.id AS cid, c.nid AS nid, c.did AS did, c.ord AS ord,
                         c.type AS type, c.queue AS queue, c.due AS due, c.ivl AS ivl,
                         c.factor AS factor, c.reps AS reps, c.lapses AS lapses,
                         c.left AS left, d.name AS deck
                  FROM cards c JOIN decks d ON d.id = c.did''')
        where, args = [], []
        cids = dedupe_ids(ids or [])
        if cids:
            where.append('c.id IN (%s)' % ','.join('?' * len(cids)))
            args.extend(cids)
        nids = dedupe_ids(note_ids or [])
        if nids:
            where.append('c.nid IN (%s)' % ','.join('?' * len(nids)))
            args.extend(nids)
        if deck:
            dids = self.deck_id(deck)
            if not dids:
                return []
            where.append('c.did IN (%s)' % ','.join('?' * len(dids)))
            args.extend(dids)
        if card_type is not None:
            where.append('c.type = ?')
            args.append(int(card_type))
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY ' + (order or 'c.due, c.id')
        if limit:
            sql += ' LIMIT %d' % int(limit)
        return [{
            'cardId': int(r['cid']), 'noteId': int(r['nid']), 'deckId': int(r['did']),
            'deckName': _deck_name(r['deck']), 'ord': int(r['ord']),
            'type': int(r['type']), 'queue': int(r['queue']), 'due': int(r['due']),
            'ivl': int(r['ivl']), 'factor': int(r['factor']), 'reps': int(r['reps']),
            'lapses': int(r['lapses']), 'left': int(r['left']),
        } for r in self.con.execute(sql, args)]

    def new_cards(self, deck=None, limit=None):
        """新卡（type=0），按队列位置 due 排序 —— 体检"激活的卡是不是排在最前"用。"""
        return self.cards(deck=deck, card_type=0, limit=limit)


def _ease_codes(ease):
    """'again'/1 → [1]；'again,hard'/[1,2] → [1,2]；None → []。"""
    if ease is None:
        return []
    items = ease if isinstance(ease, (list, tuple, set)) else [ease]
    out = []
    for it in items:
        if isinstance(it, str) and ',' in it:
            out.extend(_ease_codes([x for x in it.split(',') if x.strip()]))
            continue
        code = EASE.get(str(it).lower(), it)
        try:
            val = int(code)
        except (TypeError, ValueError):
            continue
        if 1 <= val <= 4 and val not in out:
            out.append(val)
    return out


def start_of_window_ms(days, now=None):
    """近 N 天的起点（本地 0 点，近似 Anki 的换日），毫秒时间戳。"""
    import datetime as dt
    today = (now or dt.datetime.now()).date()
    start = dt.datetime.combine(today - dt.timedelta(days=max(1, int(days)) - 1), dt.time())
    return int(start.timestamp() * 1000)


# ============================================================================
# 体检 / 自审（防回退）
# ============================================================================
# audit 的判定：这些前缀属于"常跑链路"，出现重复客户端就是**阻塞项**；
# 其余是第二期待办（先只报出来，不挡路）。
AUDIT_BLOCKING = ('code/common', 'code/execution', 'code/tools',
                  os.path.join('code', 'analysis', 'today_weak.py'),
                  '.dsh/skills')
AUDIT_PENDING = ('code/analysis', 'code/oneshot', 'core6000-analysis')
AUDIT_ALLOW = (os.path.join('code', 'analysis', 'anki_analyze'), 'archive',
               'data', '.tmp', 'temp', '.git', '__pycache__', 'node_modules')
# 文件级例外（AUDIT_ALLOW 只剪目录，这里按相对路径放行单个文件）。
#   backup_anki.py：备份按 SOP 必须在 **Anki 完全关闭**时跑，那时 AnkiConnect 根本不可用 ——
#   它必须 ①直连 127.0.0.1:8765 探一下"Anki 还开着吗"（开着就拒做收藏库副本），
#   ②用 sqlite3 打开**备份出来的副本**做 integrity_check 与计数核对。
#   两件事都不能也不该走 anki_api（那是给 live Anki 用的）。2026-10-10 登记。
AUDIT_ALLOW_FILES = (os.path.join('code', 'tools', 'backup_anki.py'),)
# 自己写 AnkiConnect 客户端的函数名（历史上出现的那些）
CLIENT_FUNC_NAMES = ('anki', 'invoke', 'ac')
# AnkiConnect 的动作名：客户端无论如何都得把动作名发出去，所以「raw HTTP + 这些动作名」
# 就是"自己写了一份客户端"的确定证据（比"用了 urllib"精确得多 —— 本地模型与 TTS
# 客户端也用 urllib，但它们不会发这些动作）。
ANKI_ACTIONS = (
    'findNotes', 'notesInfo', 'findCards', 'cardsInfo', 'addNotes', 'addNote',
    'updateNoteFields', 'addTags', 'removeTags', 'replaceTags', 'clearUnusedTags',
    'deleteNotes',
    'storeMediaFile', 'retrieveMediaFile', 'getMediaFilesNames', 'deleteMediaFile',
    'createDeck', 'changeDeck', 'getDeckConfig', 'saveDeckConfig', 'deckNames',
    'deckNamesAndIds', 'getTags', 'modelNames', 'modelFieldNames', 'modelTemplates',
    'createModel', 'updateModelTemplates', 'updateModelStyling', 'modelFieldAdd',
    'modelStyling', 'deleteModel',
    'suspend', 'unsuspend', 'areSuspended', 'forgetCards', 'setSpecificValueOfCard',
    'cardReviews', 'getReviewsOfCards', 'getNumCardsReviewedByDay',
)


def _literal_str(raw):
    """Python 字符串字面量 → 它的值（不是字面量就返回 ''）。"""
    import ast
    try:
        val = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return ''
    return val if isinstance(val, str) else ''


def scan_anki_access(path):
    """扫一个 .py 文件，返回它自己碰 Anki 的证据（**只看代码，注释/docstring 不算**）。

    为什么要走 tokenize：绝大多数脚本的 docstring 里都写着"依赖：AnkiConnect 在
    127.0.0.1:8765"这类说明。按字符串 grep 会把它们全算成重复客户端，噪声淹掉信号。
    """
    import tokenize
    hits = set()
    try:
        with open(path, 'rb') as fh:
            toks = [t for t in tokenize.tokenize(fh.readline)
                    if t.type not in (tokenize.COMMENT, tokenize.NL,
                                      tokenize.INDENT, tokenize.DEDENT,
                                      tokenize.ENCODING, tokenize.ENDMARKER)]
    except (tokenize.TokenError, SyntaxError, OSError, ValueError):
        return hits

    def is_docstring(i):
        """语句位置的字符串 = docstring（或裸字符串），不算代码。"""
        if i == 0:
            return True
        return toks[i - 1].type == tokenize.NEWLINE

    has_urlopen = False
    actions = set()
    for i, tok in enumerate(toks):
        if tok.type == tokenize.STRING:
            if is_docstring(i):
                continue
            val = _literal_str(tok.string)
            low = val.lower()
            if '127.0.0.1:8765' in low or 'localhost:8765' in low:
                hits.add('写死 AnkiConnect 地址')
            # 整串比对：`'-is:suspended'` 里的 "suspend" 不算动作名
            if val in ANKI_ACTIONS:
                actions.add(val)
            continue
        if tok.type != tokenize.NAME:
            continue
        prev = [t for t in toks[max(0, i - 3):i] if t.type == tokenize.NAME]
        nxt = ''.join(t.string for t in toks[i + 1:i + 6])
        if tok.string in CLIENT_FUNC_NAMES and prev and prev[-1].string == 'def':
            hits.add('def %s(' % tok.string)
        elif tok.string == 'sqlite3' and nxt.startswith('.connect'):
            hits.add('sqlite3.connect')
        elif tok.string in ('urllib', 'requests') and ('urlopen' in nxt or 'post' in nxt):
            has_urlopen = True
    if has_urlopen and actions:
        hits.add('自己发 AnkiConnect 动作（raw HTTP）')
    return hits


def _audit_hits(root=None):
    """返回 (blocking, pending, other)：[(相对路径, [命中的模式]), …]。"""
    root = root or WSP.ROOT
    blocking, pending, other = [], [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not any(a in os.path.join(dirpath, d) for a in AUDIT_ALLOW)]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            rel_fwd = rel.replace('\\', '/')
            if rel_fwd.endswith('code/common/anki_api.py'):
                continue
            if any(rel_fwd == f.replace('\\', '/') for f in AUDIT_ALLOW_FILES):
                continue
            hits = scan_anki_access(full)
            if not hits:
                continue
            rec = (rel, sorted(hits))
            if any(rel.startswith(b) for b in ('.dsh',)) or \
                    any(rel.replace('\\', '/').startswith(b.replace('\\', '/'))
                        for b in AUDIT_BLOCKING):
                blocking.append(rec)
            elif any(rel.replace('\\', '/').startswith(b.replace('\\', '/'))
                     for b in AUDIT_PENDING):
                pending.append(rec)
            else:
                other.append(rec)
    return blocking, pending, other


def cmd_check(args):
    cli = Client()
    info = cli.health()
    report = {'url': cli.url, 'reachable': info['ok'], 'version': info['version'],
              'error': info['error'], 'decks': None, 'models': None, 'media': None}
    if info['ok']:
        try:
            report['decks'] = len(deck_names())
            report['models'] = len(model_names())
            report['media'] = len(media_names('*'))
        except AnkiError as exc:                        # noqa: BLE001
            report['error'] = friendly(exc)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print('AnkiConnect   %s' % cli.url)
        if report['reachable']:
            print('  版本        %s' % report['version'])
            print('  牌组        %s 个' % report['decks'])
            print('  笔记类型    %s 个' % report['models'])
            print('  媒体文件    %s 个' % report['media'])
        else:
            print('  ✗ %s' % report['error'])
    return 0 if report['reachable'] else 1


def cmd_count(args):
    print(count(args.query))
    return 0


def cmd_tags(args):
    got = sorted(tags())
    if args.json:
        print(json.dumps(got, ensure_ascii=False, indent=1))
    else:
        for t in got:
            print(t)
    return 0


def cmd_revlog(args):
    ease = args.ease
    if args.source == 'snapshot':
        with Snapshot.open(path=args.snapshot, live_copy=args.live_copy) as snap:
            rows = snap.revlog(since_ms=start_of_window_ms(args.days), ease=ease,
                               card_ids=args.card_ids, limit=args.limit)
    else:
        rows = card_reviews(card_ids=args.card_ids, deck=args.deck, start_id=0)
        if args.days or ease:
            cut = start_of_window_ms(args.days or 1)
            codes = _ease_codes(ease)
            rows = [r for r in rows if r['revlogId'] >= cut
                    and (not codes or r['ease'] in codes)]
        if args.limit:
            rows = rows[:args.limit]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        by_ease = {}
        for r in rows:
            by_ease[r['ease']] = by_ease.get(r['ease'], 0) + 1
        print('来源 %s ｜ %d 条' % (args.source, len(rows)))
        for code in sorted(by_ease):
            print('  %s(%d)  %d 条' % (EASE_CN.get(code, '?'), code, by_ease[code]))
        for r in rows[:20]:
            print('  %s  card=%-14s ease=%s ivl=%-4s %sms'
                  % (time.strftime('%m-%d %H:%M', time.localtime(r['revlogId'] / 1000)),
                     r['cardId'], r['ease'], r['ivl'], r['timeMs']))
    return 0


def cmd_exec(args):
    params = json.loads(args.params) if args.params else {}
    result = call(args.action, **params)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


def cmd_audit(args):
    blocking, pending, other = _audit_hits()
    print('== Anki 访问自审 ==')
    print('阻塞项（常跑链路里残留的重复客户端）：%d' % len(blocking))
    for rel, hits in blocking:
        print('  ✗ %s  ← %s' % (rel, '、'.join(hits)))
    print('第二期待办（analysis / oneshot / core6000-analysis）：%d' % len(pending))
    if args.all:
        for rel, hits in pending:
            print('  · %s  ← %s' % (rel, '、'.join(hits)))
    if other:
        print('其它（新增的 Anki 访问代码？请确认应该走 anki_api）：%d' % len(other))
        for rel, hits in other:
            print('  ? %s  ← %s' % (rel, '、'.join(hits)))
    if not blocking and not other and not pending:
        print('★ 全仓只有 anki_api.py 一个 Anki 访问点。')
    if blocking or other:
        return 1
    if args.strict and pending:
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='Anki 访问的唯一接口（AnkiConnect + 离线快照）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('check', help='体检：AnkiConnect 是否通 + 版本/牌组/笔记类型/媒体数')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_check)

    p = sub.add_parser('count', help='数一个查询串命中的笔记数')
    p.add_argument('query')
    p.set_defaults(func=cmd_count)

    p = sub.add_parser('tags', help='列出所有标签')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_tags)

    p = sub.add_parser('revlog', help='读学习记录（在线 cardReviews 或离线快照 revlog）')
    p.add_argument('--days', type=int, default=1, help='近 N 天，默认 1')
    p.add_argument('--ease', help="again/hard/good/easy 或 1-4，可逗号分隔")
    p.add_argument('--deck', help='在线模式：cardReviews 需要的牌组名')
    p.add_argument('--card-ids', help='只取这些卡（逗号/空格分隔）')
    p.add_argument('--source', default='anki', choices=('anki', 'snapshot'))
    p.add_argument('--snapshot', help='快照路径，默认 %s' % WSP.SNAP_ANKI_SNAP)
    p.add_argument('--live-copy', action='store_true', help='用 live 收藏的临时副本（快照模式）')
    p.add_argument('--limit', type=int)
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_revlog)

    p = sub.add_parser('exec', help='逃生口：直接发一个 AnkiConnect 动作')
    p.add_argument('action')
    p.add_argument('--params', help="JSON 参数，例如 '{\"query\":\"deck:*\"}'")
    p.set_defaults(func=cmd_exec)

    p = sub.add_parser('audit', help='扫全仓重复的 Anki 客户端（防回退）')
    p.add_argument('--strict', action='store_true', help='第二期待办也算失败')
    p.add_argument('--all', action='store_true', help='列出第二期待办的每个文件')
    p.set_defaults(func=cmd_audit)

    args = ap.parse_args(argv)
    if args.cmd == 'revlog' and args.card_ids:
        args.card_ids = [x for x in args.card_ids.replace(',', ' ').split() if x]
    try:
        return args.func(args)
    except AnkiError as exc:                            # noqa: BLE001
        print(friendly(exc), file=sys.stderr)
        return 1
    except SnapshotError as exc:                        # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
