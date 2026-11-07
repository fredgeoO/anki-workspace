# -*- coding: utf-8 -*-
"""回归测试：anki_api 的只读 CLI（find / notes）。

挡四件事：
1. find 的 stdout 只有 id（条数走 stderr），--json 是合法 JSON；
2. notes 的 --fields / --ids / --cards 各走对分支（给 --ids 时不该再查 find_notes）；
3. 缺失的 noteId 要报到 stderr，不能静默当成"没有这张卡"；
4. 这两个子命令是**只读**的：源码里不许出现任何写库/改调度调用。

纯离线：AK 的 find_notes / notes_info / cards_info 全部换成假函数。
跑法：& $PY code\\tests\\test_anki_api_cli.py
"""
import contextlib
import inspect
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
import textio  # noqa: E402  stdio 唯一入口
import anki_api as AK  # noqa: E402

FAIL = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                       '' if cond else '  ← %s' % detail))
    if not cond:
        FAIL.append(name)


@contextlib.contextmanager
def patched(**fns):
    old = {k: getattr(AK, k) for k in fns}
    for k, v in fns.items():
        setattr(AK, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(AK, k, v)


def run(argv):
    """跑一次 CLI，返回 (exit, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = AK.main(argv)
    return code, out.getvalue(), err.getvalue()


def fake_note(nid, word='くず', meaning='垃圾', cards=(11,)):
    return {'noteId': nid, 'modelName': 'Japanese Vocabulary',
            'tags': ['jp-core::5k'], 'cards': list(cards),
            'fields': {'Word': {'value': word, 'order': 0},
                       'Meaning': {'value': meaning, 'order': 1}}}


CARD = {'cardId': 11, 'note': 1, 'deckName': '0-日本语学习::0-词汇::1-高频日语单词 6000',
        'queue': 1, 'type': 1, 'due': 1794008460, 'interval': 3}


print('== find ==')
calls = []


def boom(*a, **k):
    raise AssertionError('只读命令不许碰写接口')


with patched(find_notes=lambda q, limit=None: (calls.append((q, limit)) or [1, 2, 3])):
    code, out, err = run(['find', 'Word:くず'])
    check('find 退出码 0', code == 0, code)
    check('find stdout 每行一个 id', out.split() == ['1', '2', '3'], repr(out))
    check('find 条数在 stderr', '共 3 个笔记' in err, repr(err))
    check('find 把查询串原样传给 find_notes', calls[-1] == ('Word:くず', None), calls)
    code, out, err = run(['find', 'deck:x', '--limit', '2', '--json'])
    check('find --json 是合法 JSON 列表', json.loads(out) == [1, 2, 3], repr(out))
    check('find --limit 透传', calls[-1] == ('deck:x', 2), calls)

    code, out, err = run(['find', '--query', 'Word:くず'])
    check('find 也认 --query（上次踩的就是这个写法）',
          code == 0 and out.split() == ['1', '2', '3'], repr(out) + repr(err))
    check('find --query 把查询串原样传下去', calls[-1] == ('Word:くず', None), calls)

with patched(find_notes=boom):
    code, out, err = run(['find'])
    check('find 无查询串 → 退出码 2 且不查库', code == 2, code)
    check('find 无查询串给出人话提示', '需要查询串' in err, err)

print('== notes ==')
seen = []


def notes_info(ids, chunk=None):
    seen.append(list(ids))
    return [fake_note(1)] if 1 in ids else []


with patched(find_notes=boom, notes_info=notes_info, cards_info=lambda ids, chunk=None: [CARD]):
    code, out, err = run(['notes', '--ids', '1,2'])
    check('notes --ids 退出码 0', code == 0, code)
    check('notes --ids 不再调 find_notes', seen == [[1, 2]], seen)
    check('notes 打印 noteId/model', 'noteId 1' in out and 'Japanese Vocabulary' in out, out)
    check('notes 打印全部字段', '-- Word --' in out and '-- Meaning --' in out, out)
    check('缺失 noteId 报到 stderr', '缺失 noteId' in err and '2' in err, err)

    code, out, err = run(['notes', '--ids', '1', '--fields', 'Word, Meaning'])
    check('--fields 只给选定字段（顺序保留）',
          out.index('-- Word --') < out.index('-- Meaning --')
          and 'tags:' in out and 'Word' in out, out)

    code, out, err = run(['notes', '--ids', '1', '--cards'])
    check('--cards 打印牌组与卡状态', '高频日语单词' in out and 'due 1794008460' in out, out)

    code, out, err = run(['notes', '--ids', '1', '--cards', '--json'])
    rows = json.loads(out)
    check('notes --json 结构', rows[0]['noteId'] == 1
          and rows[0]['fields'] == {'Word': 'くず', 'Meaning': '垃圾'}
          and rows[0]['cards'][0]['deckName'].endswith('6000'), repr(rows)[:200])

with patched(find_notes=lambda q, limit=None: [1], notes_info=notes_info,
             cards_info=lambda ids, chunk=None: [CARD]):
    code, out, err = run(['notes', 'Word:くず'])
    check('notes <查询串> 走 find_notes', code == 0 and 'noteId 1' in out, out)

with patched(find_notes=boom, notes_info=notes_info):
    code, out, err = run(['notes'])
    check('notes 无参数 → 退出码 2', code == 2, code)
    check('notes 无参数给出人话提示', '至少给一个查询串' in err, err)

print('== 只读保证（源码级） ==')
src = inspect.getsource(AK.cmd_find) + inspect.getsource(AK.cmd_notes)
WRITES = ('update_note_fields', 'update_notes', 'add_tags', 'remove_tags', 'replace_tags',
          'store_media_file', 'delete_media_file', 'delete_notes', 'add_notes',
          'set_card_due', 'set_card_values', 'forget_cards', 'suspend', 'unsuspend')
hits = [w for w in WRITES if w in src]
check('find/notes 源码里没有写接口', not hits, '、'.join(hits))

print()
if FAIL:
    print('FAILED：%d 项' % len(FAIL))
    for name in FAIL:
        print('  - %s' % name)
    sys.exit(1)
print('全部通过')
