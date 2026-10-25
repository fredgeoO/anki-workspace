# -*- coding: utf-8 -*-
"""JMdict 词典层（jmdict_check.py / today_new.py 预取缓存）回归测试。

跑法：`& $PY code\\tests\\test_lesson_dict.py`

挡的是「词典」这件事本身：
* 读音不在词典读音表 → **硬错**，并给出候选读音 / “读音本身是另一个词条”的提示；
* 词性与词典冲突 → 单条词条才自动给 `pos_fix`，同形多词条只提示、不擅改；
* 他动词 / 自动词标反 → 报出来；
* 词形查不到 → 只提示，不判错；
* 词典不可用 → 整层跳过，绝不挡住讲义；
* 接进渲染后：读音隐藏、词性按词典显示、`check_quality` 不重复报同一条读音错；
* **词典事实**（发给模型的义项/语域/适用限制）的形状与上限；
* **预取缓存**：首次查库并落盘，之后命中零查库；卡片/日期/版本变化才重查；
* 事实随卡进模型输入（`payload.cards[].dict`），只补跑时用最新事实覆盖。

测试用假词典（`FakeDict`）跑逻辑，不依赖 551 MB 的 `jmdict.db`；
最后的「真词典冒烟」在库存在时才跑，缺库自动跳过。
"""
import json
import os
import shutil
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_WS, 'code', 'execution'))
sys.path.insert(0, os.path.join(_WS, 'code', 'common'))

import jmdict_check as JC  # noqa: E402
import textio  # noqa: E402
import today_new as TN  # noqa: E402

TMP = os.path.join(_WS, 'temp', 'test_lesson_dict')
FAILED = []


def ok(cond, label):
    print('  [%s] %s' % ('OK' if cond else '!!', label))
    if not cond:
        FAILED.append(label)


def section(t):
    print('== %s ==' % t)


# ---------------------------------------------------------------------------
# 假词典：形状与 jmdictpy 压平后的一致
# ---------------------------------------------------------------------------
def entry(eid, kanji, kana, senses, common=True):
    """kana = [(写法, 是否常用)]；senses = [([pos 代码], [英文释义])]。"""
    return {
        'id': eid, 'common': common, 'kanji': list(kanji),
        'kana': [{'text': t, 'common': c} for t, c in kana],
        'senses': [{'pos': list(p), 'glosses': list(g)} for p, g in senses],
    }


class FakeDict:
    available = True
    reason = ''

    def __init__(self, table):
        self.table = table
        self.calls = 0

    def lookup(self, word):
        self.calls += 1
        return self.table.get(word, [])


def card(nid, word, reading='', pos='名', kind='vocab'):
    return {'id': nid, 'kind': kind, 'word': word, 'reading': reading, 'pos': pos,
            'meaning': '释义', 'level': 'N3', 'deck': '0-词汇::2-考级词汇',
            'deck_short': '0-词汇 / 2-考级词汇', 'model': 'test', 'queue_pos': nid,
            'audio': [], 'sentences': [], 'style': 'full', 'n_cards': 1}


DICT = {
    # 上手：两个词条，读音各一组
    '上手': [
        entry(1, ['上手'], [('じょうず', True), ('じょうて', False)],
              [(['adj-na', 'n'], ['skillful']), (['n'], ['flattery'])]),
        entry(2, ['上手'], [('うわて', False), ('かみて', False)],
              [(['adj-na', 'n'], ['upper part'])]),
    ],
    # あっ：单条词条，int
    'あっ': [entry(10, [], [('あっ', True), ('アッ', False)],
                  [(['int'], ['ah', 'oh'])])],
    # もん：同形多词条，全是名词（真正的句末 もん 不在 JMdict）
    'もん': [
        entry(20, ['者'], [('もの', True), ('もん', False)], [(['n'], ['person'])]),
        entry(21, ['門'], [('もん', True)], [(['n'], ['gate'])]),
    ],
    # こ：多个同形词条，读音都是 こ
    'こ': [
        entry(30, ['子'], [('こ', True)], [(['n'], ['child'])]),
        entry(31, ['個'], [('こ', True)], [(['ctr'], ['counter'])])],
    # あそこ：读音自己是一个独立词条
    'あそこ': [entry(32, ['彼処'], [('あそこ', True)], [(['pn'], ['there'])])],
    # 逃がす：五段他动
    '逃がす': [entry(40, ['逃がす'], [('にがす', True)], [(['v5s', 'vt'], ['let escape'])])],
    # 触れる：自他两用
    '触れる': [entry(41, ['触れる'], [('ふれる', True)],
                    [(['v1', 'vi', 'vt'], ['touch'])])],
}


def do(word, reading='', pos='名'):
    return JC.check_card(card(1, word, reading, pos), FakeDict(DICT))


def issue(res, field=None, level=None):
    for i in res['issues']:
        if field and i['field'] != field:
            continue
        if level and i['level'] != level:
            continue
        return i
    return None


def main():
    section('1. 读音：能证伪的才是硬错')
    r = do('上手', 'じて', 'ナ形容词')
    err = issue(r, 'reading', 'error')
    ok(err is not None and r['status'] == 'error', '上手 / じて → 硬错')
    ok('じょうず' in (err or {}).get('message', ''), '报出候选读音（じょうず）')
    ok(do('上手', 'かみて', 'ナ形容词')['status'] == 'ok', '上手 / かみて → 词典认，不报错')
    ok(do('上手', 'ジョウズ', 'ナ形容词')['status'] == 'ok', '平/片假名差异不算读音错')
    r = do('こ', 'あそこ', '名词')
    ok(r['status'] == 'error' and issue(r, 'reading', 'error') is not None,
       'こ / あそこ → 硬错（复审第 1 条）')
    ok('独立词条' in issue(r, 'reading', 'error')['message'],
       '读音本身是另一个词条时给出提示（あそこ＝彼処）')
    ok(do('のじゃ', '', '助词')['status'] == 'info', '查不到的词只提示、不判错')

    section('2. 词性：单条词条才敢自动改')
    r = do('あっ', '', '副词')
    ok(r['status'] == 'warn' and r['pos_fix'] == '感叹词', 'あっ（副词）→ 词典判定感叹词')
    ok('id=10' in issue(r, 'pos')['message'], '报告里带词典条目 id，方便复核')
    r = do('もん', '', '惯用句')
    ok(r['status'] == 'info' and r['pos_fix'] == '',
       'もん：同形多词条 → 只提示，不自动改（否则会改成「名词」）')
    ok(do('上手', 'じょうず', 'ナ形容词')['status'] == 'ok', '词性对得上时不乱报')
    ok(do('あっ', '', '感叹词')['status'] == 'ok', '卡片本来就标对 → 不校正')

    section('3. 他动词 / 自动词')
    r = do('逃がす', 'にがす', '他动词')
    ok(r['status'] == 'ok', '逃がす（他動）→ 对得上')
    r = do('逃がす', 'にがす', '自动词')
    ok(issue(r, 'pos', 'warn') is not None, '逃がす 标成自动词 → 报出来')
    ok(do('触れる', 'ふれる', '自动词')['status'] == 'ok', '自他两用的词不误报')

    section('4. 词形表：不认识的不硬判')
    ok(JC.pos_family('v5s') == 'verb' and JC.pos_family('adj-na') == 'adj-na', '词性代码归类')
    ok('vt' in JC.card_families('他動2') and 'verb' in JC.card_families('他動2'),
       '他動2（旧标签）认得出是动词')
    ok(JC.card_families('') == set(), '空词性不参与冲突判断')
    ok(JC.kana_key('アー') == JC.kana_key('あー'), '假名归一')
    ok(JC.clean_word('〜あまり') == 'あまり', '词形去掉 〜 修饰')

    section('5. 整份 manifest：只查词汇卡')
    m = {'date': '2026-10-24', 'cards': [
        card(1, '上手', 'じて', 'ナ形容词'),
        card(2, 'につれて', '', '动词', kind='grammar'),
        card(3, 'あの子が…', '', '', kind='sentence'),
    ]}
    rep = JC.check_manifest(m, FakeDict(DICT))
    ok(rep['checked'] == 1 and len(rep['cards']) == 1, '只核验 1 张词汇卡')
    ok(rep['counts']['error'] == 1, '统计到 1 处硬错')
    lines = JC.format_report(rep)
    ok(any('✗' in x and '上手' in x for x in lines), '报告里点名卡片与严重度')

    section('6. 词典不可用：整层跳过')
    class NoDict:
        available = False
        reason = '词典库不存在'

        def lookup(self, word):
            raise AssertionError('不可用时不该查')

    rep = JC.check_manifest(m, NoDict())
    ok(rep['available'] is False and rep['counts']['error'] == 0, '不可用时不报错、不计数')
    ok('不可用' in JC.format_report(rep)[0], '报告说明为什么跳过')

    section('7. 接进讲义渲染：读音隐藏 / 词性按词典 / 不重复报')
    cards = [card(1, 'こ', 'あそこ', '名词'), card(2, 'あっ', '', '副词'),
             card(3, '程度', 'ていど', '名词')]
    DICT['程度'] = [entry(50, ['程度'], [('ていど', True)], [(['n'], ['degree'])])]
    manifest = {
        'version': 2, 'date': '2026-10-24', 'generated_at': '2026-10-24T06:00:00',
        'counts': {'total': 3, 'entries': 3, 'vocab': 3, 'grammar': 0, 'sentence': 0},
        'decks': [{'deck': '0-词汇::2-考级词汇', 'model': 'test', 'kind': 'vocab',
                   'taken': 3, 'taken_notes': 3, 'limit': 8, 'limit_source': 'test'}],
        'cards': cards,
    }
    lesson = {'date': '2026-10-24', 'intro': '', 'entries': {
        '1': {'teach': {'one_line': '那里。', 'core': '远指。', 'examples': [
            {'jp': 'あそこに木がある。', 'cn': '那边有棵树。'}]}},
        '2': {'teach': {'one_line': '啊。', 'core': '惊讶。', 'examples': [
            {'jp': 'あっ、忘れた。', 'cn': '啊，忘了。'}]}},
        '3': {'teach': {'one_line': '程度。', 'core': '书面。', 'examples': [
            {'jp': '百円程度で足りる。', 'cn': '一百日元左右就够。'}]}},
    }}
    fake = FakeDict(DICT)
    dinfo = JC.check_manifest(manifest, fake)['cards']
    text = TN.render_lesson(manifest, lesson, dinfo)
    ok('### こ　' in text and '（あそこ）' not in text, '读音被判错时标题不显示读音')
    ok('JMdict 判定' in text and '彼処' in text, '正文就地标注 JMdict 的判定与提示')
    ok('感叹词｜**释义**' in text, 'あっ 的词性按词典显示成感叹词')
    ok('由 JMdict 判定' in text, '词性说明交代哪些是词典校正的')
    ok(TN.check_render(text, manifest) == [], '带词典校正的渲染仍通过闸门')
    lines, n = TN.check_quality(manifest, lesson, dinfo)
    ok(not any(x.startswith('读音：') for x in lines),
       'JMdict 已判过的读音错，内容问题清单里不重复报')

    section('8. 词典事实：读音/义项/语域/适用限制（发给模型的那一份）')
    r = do('上手', 'じょうず', 'ナ形容词')
    f = r['facts']
    ok(bool(f) and f['readings'][0] == 'じょうず', '事实里的读音以卡片读音优先')
    ok(len(f['entries']) == 1 and f['entries'][0]['headword'] == '上手【じょうず】',
       '同形词条按卡片读音筛掉无关的（うわて 不进来）')
    ok('ナ形容词' in f['entries'][0]['pos'], '词性给中文（ナ形容词）')
    ok('skillful' in f['entries'][0]['senses'][0]['glosses'], '义项带英文释义边界')
    ok('同形 2' in (f.get('note') or ''), '同形多条时附一句说明')
    ok(do('のじゃ', '', '助词')['facts'] is None, '查不到的词不塞空事实')
    f2 = do('あっ', '', '副词')['facts']
    ok(f2['entries'][0]['senses'][0]['pos'] == '感叹词', '词性代码译成中文')

    tagged = {
        'id': 61, 'common': True, 'kanji': ['上'],
        'kana': [{'text': 'かみて', 'common': True}],
        'senses': [
            {'pos': ['n'], 'glosses': ['upper part', 'second', 'third'],
             'misc': ['arch'], 'fields': ['comp'], 'dialect': ['ksb'],
             'info': ['used as お〜'], 'applies_to_kanji': ['*'],
             'applies_to_kana': ['かみて']},
            {'pos': ['n'], 'glosses': ['g2']},
            {'pos': ['n'], 'glosses': ['g3']},
            {'pos': ['n'], 'glosses': ['g4']},
        ]}
    f3 = JC.card_facts([tagged], '上', 'かみて')
    s0 = f3['entries'][0]['senses'][0]
    ok(len(s0['glosses']) <= JC.FACT_MAX_GLOSSES, '释义条数受上限约束')
    ok(len(f3['entries'][0]['senses']) <= JC.FACT_MAX_SENSES, '义项条数受上限约束')
    ok('古语' in s0['tags'] and '计算机' in s0['tags'] and '关西' in s0['tags'],
       '语域/领域/方言标签译成中文')
    ok(s0['applies'] == '读音=かみて', '适用限制保留（读音=…）')
    ok(s0['info'].startswith('used as'), 'usage 说明保留')
    ok(sum(len(e['senses']) for e in f3['entries']) <= JC.FACT_MAX_SENSES_TOTAL,
       '多词条时义项总数受上限约束')

    section('9. 预取缓存：一次查库，之后复用')
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)
    cache = os.path.join(TMP, 'dict_2026-10-24.json')
    m = {'date': '2026-10-24', 'cards': [
        card(1, '上手', 'じょうず', 'ナ形容词'),
        card(2, 'あっ', '', '副词'),
        card(3, 'につれて', '', '动词', kind='grammar'),
    ]}
    args = types.SimpleNamespace(no_dict=False, refresh_dict=False)
    fake = FakeDict(DICT)
    dinfo, rep, computed = TN.ensure_dict(args, m, cache_path=cache, lookup=fake)
    ok(computed and os.path.exists(cache) and fake.calls > 0, '首次预取：查库并落盘')
    TN.attach_dict(m, rep)
    ok(m['cards'][0].get('dict') and 'dict' not in m['cards'][2],
       '事实只挂词汇卡（语法卡不挂）')
    before = fake.calls
    _d2, rep2, computed2 = TN.ensure_dict(args, m, cache_path=cache, lookup=fake)
    ok(not computed2 and fake.calls == before, '缓存命中：一次库都不查')
    ok(rep2['meta']['fingerprint'] == rep['meta']['fingerprint'], 'meta 里带卡片指纹')
    ok(rep2['meta']['cache_version'] == JC.CACHE_VERSION, 'meta 里带缓存版本')

    m['cards'][0]['reading'] = 'じて'
    _d3, _r3, computed3 = TN.ensure_dict(args, m, cache_path=cache, lookup=fake)
    ok(computed3 and fake.calls > before, '卡片读音变了 → 自动重查一次')

    # 旧格式（没有 meta）→ 判失效并重查，不需要手工迁移
    with open(cache, encoding='utf-8') as fh:
        fresh = json.load(fh)
    old = {k: v for k, v in fresh.items() if k != 'meta'}
    with open(cache, 'w', encoding='utf-8') as fh:
        json.dump(old, fh, ensure_ascii=False)
    ok(TN.ensure_dict(args, m, cache_path=cache, lookup=fake)[2] is True,
       '旧格式缓存 → 自动重查')

    args.no_dict = True
    before = fake.calls
    d4, r4, c4 = TN.ensure_dict(args, m, cache_path=cache, lookup=fake)
    ok(d4 is None and r4 is None and not c4 and fake.calls == before,
       '--no-dict：不查库、不返回事实')
    TN.attach_dict(m, None)
    ok('dict' not in m['cards'][0], '--no-dict 时清掉卡上残留的旧事实')
    args.no_dict = False

    before = fake.calls
    args.refresh_dict = True
    ok(TN.ensure_dict(args, m, cache_path=cache, lookup=fake)[2] and fake.calls > before,
       '--refresh-dict 强制重查')
    args.refresh_dict = False

    real_db_version = JC.db_version
    JC.db_version = lambda *a, **k: 'test-new-version'
    try:
        ok(TN.ensure_dict(args, m, cache_path=cache, lookup=fake)[2] is True,
           '词典版本变了 → 缓存在效')
    finally:
        JC.db_version = real_db_version

    section('10. 模型输入：事实随卡进请求')
    _d10, rep10, _c10 = TN.ensure_dict(args, m, cache_path=cache, lookup=fake)
    TN.attach_dict(m, rep10)
    payload_user = TN.build_messages(m, [m['cards'][0], m['cards'][2]], 'SYS')[1]['content']
    payload = json.loads(payload_user.split('```json')[1].split('```')[0])
    ok('dict' in payload['cards'][0] and payload['cards'][0]['dict']['readings'],
       '词汇卡 payload 带 dict')
    ok('dict' not in payload['cards'][1], '语法卡 payload 不带 dict')

    in_path = os.path.join(TMP, '01_in.json')
    stale = {k: v for k, v in m['cards'][0].items() if k != 'dict'}
    with open(in_path, 'w', encoding='utf-8') as fh:
        json.dump({'cards': [stale]}, fh, ensure_ascii=False)
    req = {'in': in_path, 'ids': [1]}
    ok(TN.load_req_cards(req, m)[0].get('dict'), '只补跑时 dict 用 manifest 最新事实覆盖')

    section('11. 真词典冒烟（库不在就跳过）')
    lk = JC.Lookup()
    try:
        if not lk.available:
            print('  [--] 跳过：%s' % lk.reason)
        else:
            r = JC.check_card(card(1, '上手', 'じて', 'ナ形容词'), lk)
            ok(r['status'] == 'error', '真词典：上手 / じて → 硬错')
            ok(all(x in r['readings'] for x in ('じょうず',)),
               '真词典：候选读音里有 じょうず')
            r = JC.check_card(card(2, 'こ', 'あそこ', '名词'), lk)
            ok('彼処' in (issue(r, 'reading', 'error') or {}).get('message', ''),
               '真词典：こ / あそこ 指向「彼処」')
            r = JC.check_card(card(3, '的', 'まと', '名词'), lk)
            ok(r['status'] == 'ok', '真词典：的 / まと 是合法读音，不误报')
            r = JC.check_card(card(4, '逃がす', 'にがす', '自动词'), lk)
            ok(issue(r, 'pos', 'warn') is not None, '真词典：逃がす 标自动词 → 报出来')
    finally:
        lk.close()

    print()
    if FAILED:
        print('✗ %d 项未通过：%s' % (len(FAILED), '；'.join(FAILED)))
        return 1
    print('✓ 全部通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
