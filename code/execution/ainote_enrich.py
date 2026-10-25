# -*- coding: utf-8 -*-
"""按需加强某张卡的 AINote 讲解（含「语感」一节）。

这是一条**高频**操作：用户看到某张卡的讲解太薄，常说
「把这张卡的 AINote 讲透一点，加一段语感」——以前每次都在对话里手写 HTML，
现在固化成命令，本地模型生成 + 机械闸门 + 可回退。

用法::

    python code/cli.py ainote show   --id 1792084330990     # 只看卡上现值
    python code/cli.py ainote gen    --word 分際            # 生成（落盘，不写库）
    python code/cli.py ainote apply  --word 分際            # 演练：打印前后对照
    python code/cli.py ainote apply  --word 分際 --commit   # 真写（写前备份）
    python code/cli.py ainote enrich --word 分際 --commit   # gen + apply 一条命令
    python code/cli.py ainote revert --commit               # 按最近一次备份还原

设计口径
--------
* **只写 AINote 一个字段**：Word / Sentence / 译文 / 振假名 / 音频 / 标签 / deck / due
  一个字不动。这是「教学文案」操作，不是修卡。
* 「1. 中文翻译」直接取卡的 ``Sentence Translation``，**不让模型改写**（原句信息不丢）。
  模型只写其余 5 节：核心词汇 / 语法要点 / 动词变形解析 / 语境与表达风格 / 语感。
* 生成结果落 ``data/ainote/gen/<noteId>_out.json``；``apply`` **只读这个文件**，
  所以模型产出不满意时可以直接改 JSON 里的文字，再 apply（不必重跑模型）。
* 机械闸门：每节非空、目标词出现在核心词汇、语感要真的在讲语域/褒贬/场合
  （至少命中 2 个语感词）、标签白名单、ruby 配对、无占位符；不合格带反馈重问一次。
* 写库前把旧 AINote 备份到 ``data/ainote/backup_<时间戳>.json``；``revert`` 按它还原。
* 模型产出与卡上内容对不上（Word/Sentence/译文/AINote 改过）时，``apply`` 拒绝，
  要求重跑 ``gen``——除非显式 ``--force``。
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_CODE, 'common'))
import anki_api as AK         # noqa: E402  唯一的 Anki 访问点
import paths as WSP           # noqa: E402
import textio                 # noqa: E402  UTF-8 stdio 唯一入口（import 即生效）

NOTE_MODEL = 'Japanese Vocabulary'
F_NOTE = 'AINote'
CARD_FIELDS = ('Word', 'Transliteration', 'Part of Speech', 'Meaning',
               'Sentence', 'Sentence Translation', F_NOTE)
# 模型要写的 5 节（顺序 = 渲染顺序；「中文翻译」不在里面，直接取字段）
SECTIONS = ('核心词汇', '语法要点', '动词变形解析', '语境与表达风格', '语感')

DATA_DIR = os.path.join(WSP.DATA, 'ainote')
GEN_DIR = os.path.join(DATA_DIR, 'gen')
BACKUP_GLOB = os.path.join(DATA_DIR, 'backup_*.json')

# 闸门：HTML 只允许这些标签（p 是渲染器自己的，模型不要用）
ALLOWED_TAGS = {'p', 'b', 'strong', 'br', 'ruby', 'rt', 'i', 'em', 'ul', 'li', 'div'}
# 「语感」节必须真的在谈这些东西（至少命中 2 个），否则视为没写语感
NUANCE_WORDS = ('语域', '语气', '口语', '书面', '正式', '随意', '粗俗', '粗鲁', '轻蔑',
                '贬义', '褒义', '中性', '礼貌', '亲昵', '自嘲', '生硬', '柔和', '强硬',
                '男性', '女性', '孩子', '上司', '朋友', '场合', '场景', '相当于', '换成',
                '居高临下', '挑衅', '责备', '冒犯')
PLACEHOLDERS = ('TODO', '待补', '待写', '（略）', 'XXX', 'xxx', '示例文本')

RE_BR = re.compile(r'<br\s*/?>', re.I)
RE_TAG = re.compile(r'<\s*/?\s*([a-zA-Z][\w-]*)')
RE_DANGER = re.compile(r'<\s*(script|style|iframe|object|embed)\b.*?<\s*/\s*\1\s*>',
                       re.S | re.I)
RE_ATTR_ON = re.compile(r'\s+on\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.I)
RE_JS = re.compile(r'javascript\s*:', re.I)
RE_WS = re.compile(r'[ \t\u3000]+')
RE_MANY_BR = re.compile(r'(?:\s*<br\s*/?>\s*){3,}', re.I)

GEN_SYSTEM = ('你是日语教学作者。你只输出严格 JSON，不要任何解释文字、不要 Markdown 围栏。')


# ============================================================================
# 小工具
# ============================================================================
def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1))


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def field(note, name, default=''):
    return ((note.get('fields') or {}).get(name) or {}).get('value', default) or ''


def plain(html):
    """去标签的纯文本（<br>、</li> 当换行），用于长度闸门与展示。"""
    s = re.sub(r'</li\s*>', '\n', html or '', flags=re.I)
    s = RE_BR.sub('\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return s.strip()


def one_line(text, limit=80):
    s = RE_WS.sub(' ', plain(text).replace('\n', ' ⏎ ')).strip()
    return s if len(s) <= limit else s[:limit] + '…'


def gen_path(note_id):
    return os.path.join(GEN_DIR, '%d_out.json' % int(note_id))


def input_hash(card):
    """生成依据的指纹。**不含 AINote**：AINote 正是本命令要改的字段，
    把它算进去会让「写完一次」之后永远对不上，apply 就再也过不了。"""
    raw = '\x1f'.join([card['word'], card['reading'], card['pos'], card['meaning'],
                       card['sentence'], card['translation']])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def sanitize_fragment(raw):
    """清掉模型可能夹带的危险标签/属性/<p> 外壳；只保留版式需要的标签。"""
    s = str(raw or '')
    s = RE_DANGER.sub('', s)
    s = RE_ATTR_ON.sub('', s)
    s = RE_JS.sub('', s)
    # 模型爱把每节包成 <p>：<p> 去掉、</p> 变 <br>，版式统一由渲染器给
    s = re.sub(r'<\s*p\b[^>]*>', '', s, flags=re.I)
    s = re.sub(r'<\s*/\s*p\s*>', '<br>', s, flags=re.I)
    s = re.sub(r'<\s*div\b[^>]*>', '', s, flags=re.I)
    s = re.sub(r'<\s*/\s*div\s*>', '<br>', s, flags=re.I)
    s = RE_MANY_BR.sub('<br><br>', s)
    s = re.sub(r'(?:\s*<br\s*/?>\s*)+$', '', s).strip()
    return s


# ============================================================================
# 选卡
# ============================================================================
def _split_csv(values):
    out = []
    for v in values or []:
        for part in str(v).replace('，', ',').split(','):
            part = part.strip()
            if part:
                out.append(part)
    return out


def resolve(args):
    """--id / --index / --word / --query → note 列表（去重、保持顺序）。"""
    ids = []

    def add(found):
        for nid in found:
            nid = int(nid)
            if nid not in ids:
                ids.append(nid)

    for raw in _split_csv(args.id):
        if not raw.isdigit():
            raise SystemExit('--id 只收数字 noteId：%r' % raw)
        add([raw])
    for raw in _split_csv(args.index):
        if not raw.isdigit():
            raise SystemExit('--index 只收数字（卡上的 Index 字段）：%r' % raw)
        add(AK.find_notes('Index:%s' % raw))
    for word in _split_csv(args.word):
        found = AK.find_notes('Word:%s' % word)
        # Anki 的 Word: 是分词/前缀匹配，可能带回别的词；这里只留字段精确相等、
        # 且模型是词汇卡的（同一个词常另有 Basic 例句卡，不能一起写）
        matched, other = 0, 0
        for note in AK.notes_info(found):
            if field(note, 'Word').strip() != word:
                continue
            if note.get('modelName') != NOTE_MODEL:
                other += 1
                continue
            add([note['noteId']])
            matched += 1
        if not matched:
            print('⚠️ 没找到 Word 精确等于「%s」的词汇卡（Anki 匹配到 %d 张近似卡，'
                  '其中非词汇卡 %d 张，已忽略）' % (word, len(found), other), file=sys.stderr)
    if args.query:
        q = args.query
        if 'note:' not in q:
            q = '(%s) note:"%s"' % (q, NOTE_MODEL)
        add(AK.find_notes(q))
    if not ids:
        raise SystemExit('没有选中任何卡：至少给一个 --id / --index / --word / --query。')
    notes = AK.notes_info(ids)
    if len(notes) != len(ids):
        got = {n['noteId'] for n in notes}
        raise SystemExit('有 noteId 在 Anki 里不存在：%s'
                         % '、'.join(str(i) for i in ids if i not in got))
    return notes


def card_of(note):
    word = field(note, 'Word').strip()
    card = {
        'id': int(note['noteId']),
        'model': note.get('modelName', ''),
        'tags': note.get('tags') or [],
        'word': word,
        'reading': field(note, 'Transliteration').strip(),
        'pos': field(note, 'Part of Speech').strip(),
        'meaning': field(note, 'Meaning').strip(),
        'sentence': field(note, 'Sentence').strip(),
        'translation': field(note, 'Sentence Translation').strip(),
        'ainote': field(note, F_NOTE).strip(),
    }
    if card['model'] != NOTE_MODEL:
        raise SystemExit('卡 %d 的模型是「%s」，不是「%s」；本命令只处理词汇卡。'
                         % (card['id'], card['model'], NOTE_MODEL))
    if not card['word']:
        raise SystemExit('卡 %d 的 Word 字段是空的，没法写讲解。' % card['id'])
    if not card['sentence']:
        raise SystemExit('卡 %d 的 Sentence 字段是空的，没法写讲解。' % card['id'])
    card['input_hash'] = input_hash(card)
    return card


# ============================================================================
# 生成
# ============================================================================
def build_messages(card, feedback=None):
    payload = {
        'word': card['word'],
        'reading': card['reading'],
        'pos': card['pos'],
        'meaning': card['meaning'],
        'sentence': card['sentence'],
        'translation': card['translation'],
        'current_ainote': card['ainote'],
        'tags': card['tags'],
    }
    rules = (
        '任务：为下面这张日语生词卡重写 AINote 讲解。读者是中文母语的中级日语学习者。\n'
        '不是改写例句，而是把这张卡的讲解**讲透**，并补一节「语感」。\n\n'
        '输入（JSON）：\n%s\n\n'
        '输出：严格 JSON，5 个键，值为 HTML 片段（不要 Markdown、不要解释文字）：\n'
        '{"核心词汇":"…","语法要点":"…","动词变形解析":"…","语境与表达风格":"…","语感":"…"}\n\n'
        '每一节的要求：\n'
        '* 核心词汇：目标词必须是第一条，写全「读音（平假名）·词性·本义·引申义/惯用·常见搭配」；'
        '再列句中其他实词 2-5 个。有把握时写出与近义词的差别（例：分際 / 身分 / 立場 / 身の程）。\n'
        '* 语法要点：逐个讲句中的关键语法、助词、句型；惯用句型要给接续和褒贬色彩。\n'
        '* 动词变形解析：写出句中动词/形容词的原形 → 活用形与步骤；本句没有变形就明确写'
        '「本句没有动词变形」并说明原因。\n'
        '* 语境与表达风格：这句是谁对谁说、什么场合、礼貌度、书面还是口语。\n'
        '* 语感：**必写**。说明这个词/句型听起来是什么感觉——语域（粗俗/随意/中性/正式/书面）、'
        '说话人姿态（轻蔑、居高临下、自嘲、亲昵、客观）、褒贬、中文里大致对应什么说法；'
        '并和近义词对比「换成 X 会怎样」。要给出可操作判断，例如「能不能对上司说」。\n\n'
        '格式与事实：\n'
        '* 全部用中文解释；日语词例的汉字标 <ruby>漢字<rt>かな</rt></ruby>。\n'
        '* 只用 <br> <b> <strong> <ruby> <rt> <ul> <li>；不要 <p>、<div>、标题行、序号。\n'
        '* 每节 2-6 行，短句，具体，不写空话套话。\n'
        '* 保留原讲解里正确的信息点；原讲解有错就改正，不要照抄错误。\n'
        '* 不要编造读音、词源、用法；不确定就不写。\n'
        % json.dumps(payload, ensure_ascii=False, indent=1)
    )
    msgs = [{'role': 'system', 'content': GEN_SYSTEM},
            {'role': 'user', 'content': rules}]
    if feedback:
        msgs.append({'role': 'assistant', 'content': '（上一版不合格）'})
        msgs.append({'role': 'user', 'content':
                     '上一版有这些问题：%s\n请重写一版，只输出符合要求的 JSON。'
                     % '；'.join(feedback)})
    return msgs


def gate_entry(card, entry):
    """逐节机械闸门。返回问题列表（空 = 通过）。"""
    problems = []
    for key in SECTIONS:
        body = str(entry.get(key) or '').strip()
        if not body:
            problems.append('「%s」是空的' % key)
            continue
        text = plain(body)
        floor = {'核心词汇': 40, '语法要点': 30, '动词变形解析': 15,
                 '语境与表达风格': 30, '语感': 60}.get(key, 20)
        if len(text) < floor:
            problems.append('「%s」太短（%d 字，至少 %d）' % (key, len(text), floor))
        for bad in PLACEHOLDERS:
            if bad in body:
                problems.append('「%s」里有占位符「%s」' % (key, bad))
        if '<ruby' in body.lower() and body.lower().count('<ruby') != body.lower().count('</ruby>'):
            problems.append('「%s」的 <ruby> 没有配对' % key)
        bad_tags = sorted({t.lower() for t in RE_TAG.findall(body)} - {t.lower() for t in ALLOWED_TAGS})
        if bad_tags:
            problems.append('「%s」用了不允许的标签：%s' % (key, '、'.join(bad_tags)))
    target = card['word']
    core = str(entry.get('核心词汇') or '')
    if target and target not in plain(core):
        reading = card['reading']
        if not (reading and reading in plain(core)):
            problems.append('「核心词汇」里没有目标词「%s」' % target)
    nuance = str(entry.get('语感') or '')
    hits = [w for w in NUANCE_WORDS if w in nuance]
    if len(hits) < 2:
        problems.append('「语感」不像在讲语感（只命中 %d 个关键词：%s）'
                        % (len(hits), '、'.join(hits) or '无'))
    return problems


def gen_one(card, cfg, restart=False, force_llm=False):
    """生成一张卡的 5 节讲解，落盘并返回 entry（失败返回 None）。"""
    path = gen_path(card['id'])
    if os.path.exists(path) and not restart:
        old = read_json(path)
        if old.get('input_hash') == card['input_hash']:
            print('  已有产出且卡没变：%s（--restart 重生成）'
                  % os.path.relpath(path, WSP.ROOT))
            return old.get('entry') or {}
        print('  卡上内容变了（input_hash 不一致），重新生成。')

    import local_llm as LLM
    print('  本地模型：%s ｜ %s' % (cfg.get('model'), cfg.get('base_url')))
    entry, problems, last_raw = {}, [], ''
    for attempt in range(1, 3):
        msgs = build_messages(card, feedback=problems or None)
        obj, res, shape = LLM.call_json(cfg, msgs,
                                        require=','.join(SECTIONS),
                                        max_tokens=4600,
                                        temperature=0.35 if attempt == 1 else 0.25)
        if res is not None:
            print('    %s' % res.summary())
        if obj is None:
            problems = shape or ['模型没有给出合法 JSON']
            last_raw = (res.content if res is not None else '') or ''
            print('    ⚠️ 第 %d 次生成不合格：%s' % (attempt, '；'.join(problems)[:160]))
            continue
        entry = {k: sanitize_fragment(obj.get(k)) for k in SECTIONS}
        problems = gate_entry(card, entry)
        if not problems:
            break
        last_raw = res.content if res is not None else ''
        print('    ⚠️ 第 %d 次生成过不了闸门：%s' % (attempt, '；'.join(problems)[:200]))

    if problems:
        os.makedirs(GEN_DIR, exist_ok=True)
        reject = os.path.join(GEN_DIR, '%d_rejected.json' % card['id'])
        write_json(reject, {'note_id': card['id'], 'word': card['word'],
                            'created_at': dt.datetime.now().isoformat(timespec='seconds'),
                            'problems': problems, 'entry': entry, 'raw': last_raw})
        print('❌ 两次生成都没过闸门；产出留在 %s（可以手改后 apply）'
              % os.path.relpath(reject, WSP.ROOT), file=sys.stderr)
        return None

    os.makedirs(GEN_DIR, exist_ok=True)
    write_json(path, {
        'note_id': card['id'],
        'word': card['word'],
        'created_at': dt.datetime.now().isoformat(timespec='seconds'),
        'model': cfg.get('model'),
        'input_hash': card['input_hash'],
        'entry': entry,
    })
    print('  ✓ 已落盘：%s' % os.path.relpath(path, WSP.ROOT))
    return entry


# ============================================================================
# 渲染 / 展示
# ============================================================================
def render_note(card, entry):
    """5 节渲染成 AINote。第 1 节「中文翻译」直接取卡上字段，模型不参与。"""
    trans = card['translation'].strip() or '（译文为空）'
    parts = ['<div>',
             '<p><b>1. 中文翻译</b></p>',
             '<p>%s</p>' % trans]
    for i, key in enumerate(SECTIONS, start=2):
        parts.append('<p><b>%d. %s</b></p>' % (i, key))
        body = entry[key].strip()
        # <p> 里不能嵌 <ul>：块级片段直接放，行内片段才包 <p>（否则浏览器会补出空段落）
        if re.match(r'<\s*(ul|ol|li|div|table)\b', body, re.I):
            parts.append(body)
        else:
            parts.append('<p>%s</p>' % body)
    parts.append('</div>')
    return '\n'.join(parts)


def show_diff(card, rendered):
    print('  旧 AINote（纯文本）：')
    old = plain(card['ainote']) or '（空）'
    for line in old.splitlines():
        print('    │ %s' % line)
    print('  新 AINote（完整 HTML）：')
    for line in rendered.splitlines():
        print('    │ %s' % line)
    print('  新 AINote（纯文本预览）：')
    for line in plain(rendered).splitlines():
        print('    · %s' % line)


# ============================================================================
# 命令
# ============================================================================
def cmd_show(args):
    notes = resolve(args)
    for note in notes:
        card = card_of(note)
        print('=' * 88)
        print('noteId %d ｜ %s ｜ 读音 %s ｜ 词性 %s'
              % (card['id'], card['word'], card['reading'] or '—', card['pos'] or '—'))
        print('例句：%s' % card['sentence'])
        print('译文：%s' % (card['translation'] or '（空）'))
        print('释义：%s' % (card['meaning'] or '（空）'))
        print('AINote：%s' % (card['ainote'] or '（空）'))
        print()
    return 0


def _llm_cfg(args):
    import local_llm as LLM
    return LLM.load_config(model=getattr(args, 'model', None))


def cmd_gen(args):
    notes = resolve(args)
    cfg = _llm_cfg(args)
    failed = []
    for note in notes:
        card = card_of(note)
        print('--- %s（noteId %d）' % (card['word'], card['id']))
        if not gen_one(card, cfg, restart=args.restart):
            failed.append(card['word'])
    print()
    if failed:
        print('❌ 有 %d 张没过闸门：%s' % (len(failed), '、'.join(failed)), file=sys.stderr)
        return 1
    print('全部生成完成。下一步：apply（演练）或 enrich --commit（一条命令真写）。')
    return 0


def cmd_apply(args):
    notes = resolve(args)
    rows, bad = [], []
    for note in notes:
        card = card_of(note)
        path = gen_path(card['id'])
        if not os.path.exists(path):
            bad.append((card, ['还没有产出：先跑 gen（%s）' % os.path.relpath(path, WSP.ROOT)]))
            continue
        gen = read_json(path)
        if gen.get('input_hash') != card['input_hash'] and not args.force:
            bad.append((card, ['卡上内容与生成时不一致（--force 可强行套用）']))
            continue
        entry = gen.get('entry') or {}
        problems = gate_entry(card, entry)
        rendered = render_note(card, entry) if not problems else ''
        if problems:
            bad.append((card, problems))
            continue
        rows.append((card, entry, rendered))

    for card, entry, rendered in rows:
        print('=' * 88)
        print('%s（noteId %d）｜ %s ｜ %s'
              % (card['word'], card['id'], card['reading'] or '—', card['pos'] or '—'))
        print('例句：%s　→　%s' % (card['sentence'], card['translation'] or '（译文空）'))
        show_diff(card, rendered)
        print('  闸门：通过（5 节齐全 + 目标词在核心词汇 + 语感命中 %d 个关键词）'
              % len([w for w in NUANCE_WORDS if w in entry.get('语感', '')]))

    if bad:
        print()
        print('不合格 %d 张（不写库）：' % len(bad), file=sys.stderr)
        for card, problems in bad:
            print('  %s（%d）→ %s'
                  % (card['word'], card['id'], '；'.join(problems[:3])), file=sys.stderr)
        return 1
    if not rows:
        print('没有可写的卡。')
        return 1

    print()
    if not args.commit:
        print('演练结束，没有写 Anki。确认上面文案无误后，加 --commit 重跑同一条命令。')
        return 0
    return do_commit(rows)


def do_commit(rows):
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = os.path.join(DATA_DIR, 'backup_%s.json' % stamp)
    notes_backup = {str(card['id']): {F_NOTE: card['ainote']}
                    for card, _e, _r in rows}
    write_json(backup_path, {
        'created_at': dt.datetime.now().isoformat(timespec='seconds'),
        'field': F_NOTE,
        'note': '还原 ainote enrich 改过的 AINote（其它字段本来就没动）',
        'notes': notes_backup,
    })
    print('已备份 %d 张卡的旧 AINote → %s'
          % (len(notes_backup), os.path.relpath(backup_path, WSP.ROOT)))

    print()
    print('写 %d 张卡的 AINote…' % len(rows))
    for card, _entry, rendered in rows:
        AK.update_note_fields(card['id'], {F_NOTE: rendered})
        print('  ✓ %s（%d）' % (card['word'], card['id']))

    live = AK.note_values([card['id'] for card, _e, _r in rows], names=(F_NOTE,))
    bad = [(card['word'],) for card, _e, rendered in rows
           if (live.get(card['id']) or {}).get(F_NOTE, '') != rendered]
    print()
    if bad:
        print('⚠️ 回读校验不一致 %d 张（Anki 浏览器开着没刷新？）：%s'
              % (len(bad), '、'.join(w for (w,) in bad)))
        return 1
    print('★ 回读校验通过：%d 张卡的 AINote 与写入值逐字一致。' % len(rows))
    print('退路：python code/cli.py ainote revert --commit --backup %s' % backup_path)
    return 0


def cmd_enrich(args):
    """gen（缺产出或卡变了才跑）+ apply 一条命令。"""
    notes = resolve(args)
    cfg = _llm_cfg(args)
    for note in notes:
        card = card_of(note)
        need = args.restart or not os.path.exists(gen_path(card['id']))
        if not need:
            need = read_json(gen_path(card['id'])).get('input_hash') != card['input_hash']
        if need:
            print('--- 生成 %s（noteId %d）' % (card['word'], card['id']))
            gen_one(card, cfg, restart=args.restart)
    return cmd_apply(args)


def cmd_revert(args):
    path = args.backup
    if not path:
        cands = sorted(glob.glob(BACKUP_GLOB))
        if not cands:
            raise SystemExit('没有备份文件（%s）；revert 没有依据。' % BACKUP_GLOB)
        path = cands[-1]
    obj = read_json(path)
    notes = obj.get('notes')
    if not isinstance(notes, dict) or not notes:
        raise SystemExit('备份文件读不出来或没有 notes：%s' % path)
    print('备份：%s（%s，%d 张卡）'
          % (os.path.relpath(path, WSP.ROOT), obj.get('created_at', '?'), len(notes)))
    print('模式：%s' % ('★ 真写库' if args.commit else '演练（不写 Anki）'))
    if not args.commit:
        for nid, fields in list(notes.items())[:10]:
            print('  %s ← %s' % (nid, '、'.join('%s=%s' % (k, one_line(v, 60))
                                               for k, v in fields.items())))
        print('（演练结束；加 --commit 才真的还原）')
        return 0
    live = AK.note_values([int(n) for n in notes], names=(F_NOTE,))
    done = 0
    for nid, fields in notes.items():
        old = (fields or {}).get(F_NOTE, '')
        if (live.get(int(nid)) or {}).get(F_NOTE, '') == old:
            continue
        AK.update_note_fields(int(nid), {F_NOTE: old})
        done += 1
    print('已还原 %d 张卡的 AINote。' % done)
    return 0


# ============================================================================
# CLI
# ============================================================================
def add_target_args(sp):
    g = sp.add_argument_group('选卡（至少给一个）')
    g.add_argument('--id', action='append', help='noteId，可逗号分隔/重复')
    g.add_argument('--index', action='append', help='卡上的 Index 字段，可逗号分隔/重复')
    g.add_argument('--word', action='append', help='Word 字段精确匹配，可逗号分隔/重复')
    g.add_argument('--query', help='Anki 搜索语法（自动限定词汇卡模型）')


def add_llm_args(sp):
    sp.add_argument('--model', help='本地模型名（默认读 .dsh/local-llm.json）')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog='ainote_enrich.py',
        description='按需加强某张词汇卡的 AINote 讲解（核心词汇/语法/变形/语境 + 语感）。')
    sub = ap.add_subparsers(dest='cmd')

    sp = sub.add_parser('show', help='只看卡上现值（只读）')
    add_target_args(sp)
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser('gen', help='本地模型生成 5 节讲解（落盘，不写库）')
    add_target_args(sp)
    add_llm_args(sp)
    sp.add_argument('--restart', action='store_true', help='忽略已有产出，重新生成')
    sp.set_defaults(func=cmd_gen)

    sp = sub.add_parser('apply', help='把 gen 产出写进 AINote（默认演练）')
    add_target_args(sp)
    sp.add_argument('--commit', action='store_true', help='真写库（写前自动备份）')
    sp.add_argument('--force', action='store_true',
                    help='卡上内容与生成时不一致也强行套用（一般别用）')
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser('enrich', help='gen（缺产出或卡变了）+ apply 一条命令')
    add_target_args(sp)
    add_llm_args(sp)
    sp.add_argument('--commit', action='store_true', help='真写库（写前自动备份）')
    sp.add_argument('--restart', action='store_true', help='强制重新生成')
    sp.add_argument('--force', action='store_true',
                    help='卡上内容与生成时不一致也强行套用')
    sp.set_defaults(func=cmd_enrich)

    sp = sub.add_parser('revert', help='按备份还原 AINote（默认演练）')
    sp.add_argument('--commit', action='store_true', help='真写库')
    sp.add_argument('--backup', help='指定备份文件（默认用最近一份）')
    sp.set_defaults(func=cmd_revert)

    args = ap.parse_args(argv)
    if not getattr(args, 'func', None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
