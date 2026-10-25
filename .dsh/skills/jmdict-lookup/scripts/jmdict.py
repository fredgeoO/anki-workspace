#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""jmdict-lookup 的查询入口：JMdict（日语→英语）只读查询。

定位
----
**这是「语义澄清器」，不是「讲解生成器」。** 模型对一个词拿不准——它到底有几个意思、
这个读音对应哪几个义项、词性是什么、是不是惯用句、是不是方言/古语/通常写假名——
就把那个词丢过来，读一遍命中条目，再自己下判断。

输出默认是**给模型读的紧凑文本**（中文标签 + 英文释义 + 词性/领域/限制），
`--json` 给机器读。stdout 只有结果，诊断信息全走 stderr。

设计约束（都是故意的）
----------------------
* **只做精确匹配**：`lookup` 走 kanji/假名精确索引，不做前缀/模糊匹配。
  查到的就是你给的那串字；查不到就明确报未命中（exit 1），不做"猜一个最像的"。
  唯一的自动兜底是**平假名⇄片假名互转**（同一串音，双向都试一次），以及 NFKC 归一。
* 不动网络：默认 `auto_update=False`。只有 `build` / `update` 子命令会联网。
* 不写任何东西：只读 SQLite。库在 `data/dict/jmdictpy/jmdict.db`。
* 释义是**英文**（JMdict 没有中文释义）。英文只是语义锚点，中文讲解仍由你写。

子命令
------
    status                     库在不在、多大、什么版本、多少条目
    build [--common] [--force] 首次建库/重建（联网下载 ~11MB，1–2 分钟）
    update [--check]           查新版（--check 只查不装）
    lookup 词…                 主查询：汉字或假名（+ 名字/单字兜底）
    reading 假名…              只按读音查
    meaning 英文…              按英文释义搜（FTS5）
    name 名字…                 JMnedict 人名/地名
    char 字…                   Kanjidic 单字（音读/训读/意思/年级）
    id 1358280…                按 JMdict 条目 ID 取

退出码
------
    0  有命中 / 命令成功
    1  未命中（查询本身合法，就是没查到）
    2  参数错误
    3  环境问题（jmdictpy 没装、库没建、下载失败）

用法
----
    PY="python"
    JD="$WS\\.dsh\\skills\\jmdict-lookup\\scripts\\jmdict.py"

    & $PY $JD lookup 食べる
    & $PY $JD lookup 上手 --senses 4
    & $PY $JD lookup やばい エグい --json
    & $PY $JD meaning "to eat" --limit 5 --short
    & $PY $JD char 食
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# 0. 定位工作区 → 把 code/common（textio）与 data/pylibs（jmdictpy）挂上 sys.path
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve()
SKILL_DIR = HERE.parent.parent                      # .dsh/skills/jmdict-lookup

EXIT_OK, EXIT_EMPTY, EXIT_USAGE, EXIT_ENV = 0, 1, 2, 3


def _find_workspace() -> Path | None:
    """向上找带 code/common/paths.py 的目录；找不到再退回脚本位置推 4 层。"""
    seeds = [os.environ.get('DSH_WORKSPACE'), os.environ.get('JMDICT_WORKSPACE'),
             str(Path.cwd()), str(HERE)]
    for seed in seeds:
        if not seed:
            continue
        cur = Path(seed).resolve()
        for _ in range(10):
            if (cur / 'code' / 'common' / 'paths.py').is_file():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
    guess = HERE.parents[4] if len(HERE.parents) > 4 else None
    return guess if guess and (guess / 'code').is_dir() else None


WS = _find_workspace()
if WS:
    for extra in (WS / 'code' / 'common', WS / 'data' / 'pylibs'):
        if extra.is_dir() and str(extra) not in sys.path:
            sys.path.insert(0, str(extra))

try:
    import textio  # noqa: E402  UTF-8 stdio 唯一入口（相对本工作区 script 位置）
except ImportError:  # pragma: no cover - 只会在把 skill 抠出工作区时发生
    sys.stderr.write(
        'jmdict-lookup 需要工作区的 code/common/textio.py（UTF-8 stdio）。\n'
        '本脚本应放在 <工作区>/.dsh/skills/jmdict-lookup/scripts/ 下，'
        '或设置 DSH_WORKSPACE 指向工作区根目录。\n')
    raise SystemExit(EXIT_ENV)

DEFAULT_DATA_DIR = (WS / 'data' / 'dict' / 'jmdictpy') if WS else (Path.home() / '.jmdictpy')


# ---------------------------------------------------------------------------
# 1. 中文标签：JMdict 的代码是英文缩写，直接甩给模型会多一层解码成本
# ---------------------------------------------------------------------------
TAG_ZH = {
    # 词性
    'n': '名词', 'n-adv': '名词·副词', 'n-pref': '名词·接头', 'n-suf': '名词·接尾',
    'n-t': '名词(他动)', 'num': '数词', 'pn': '代词', 'prt': '助词', 'conj': '接续词',
    'int': '感叹词', 'exp': '惯用句', 'adv': '副词', 'adv-to': '副词(と)',
    'aux': '助动词', 'aux-v': '助动词', 'aux-adj': '补助形容词', 'cop': '系词',
    'ctr': '量词', 'pref': '接头词', 'suf': '接尾词',
    'vs': 'サ変', 'vs-i': 'サ変(する)', 'vs-s': 'サ変(特殊)',
    'v1': '一段', 'v1-s': '一段(スル)',
    'v5u': '五段·ウ', 'v5k': '五段·カ', 'v5g': '五段·ガ', 'v5s': '五段·サ',
    'v5t': '五段·タ', 'v5n': '五段·ナ', 'v5b': '五段·バ', 'v5m': '五段·マ',
    'v5r': '五段·ラ', 'v5r-i': '五段·ラ(特殊)', 'v5aru': '五段·ラ(特殊)',
    'v5k-s': '五段·カ(特殊)', 'v5u-s': '五段·ウ(特殊)', 'v5uru': '五段·ラ(特殊)',
    'vk': 'カ変', 'vz': 'ズ変', 'v-unspec': '动词(未分类)', 'vi': '自动', 'vt': '他动',
    'adj-i': 'イ形容词', 'adj-ix': 'イ形容词(特殊)', 'adj-na': 'ナ形容词',
    'adj-no': '连体词', 'adj-pn': '连体词', 'adj-f': '连体·名词',
    'adj-t': 'タル形容词', 'adj-kari': 'カリ形', 'adj-shiku': 'シク形', 'adj-nari': 'ナリ形',
    # 用法/语域
    'uk': '通常写假名', 'abbr': '略语', 'arch': '古语', 'obs': '废语', 'obsc': '罕见',
    'rare': '罕见', 'sl': '俚语', 'vulg': '粗俗', 'col': '口语', 'fam': '亲昵',
    'pol': '敬语', 'hon': '尊敬语', 'hum': '谦让语', 'derog': '轻蔑', 'joc': '戏谑',
    'sens': '敏感', 'dated': '过时', 'male': '男性用语', 'female': '女性用语',
    'chn': '儿童用语', 'm-sl': '漫画俚语', 'net-sl': '网络俚语', 'euph': '委婉',
    # 表记
    'ik': '不规则假名', 'ok': '不规则汉字', 'sk': '罕用汉字', 'ateji': '当て字',
    'gikun': '义训', 'jukujikun': '熟字训', 'yoji': '四字熟语',
    'on-mim': '拟声拟态', 'proverb': '谚语', 'quote': '引用',
    # 领域
    'comp': '计算机', 'math': '数学', 'med': '医学', 'chem': '化学', 'biol': '生物',
    'phys': '物理', 'law': '法律', 'mil': '军事', 'econ': '经济', 'ling': '语言学',
    'music': '音乐', 'sports': '体育', 'sumo': '相扑', 'buddh': '佛教', 'shinto': '神道',
    'food': '食物', 'cloth': '服饰', 'archit': '建筑', 'geol': '地质', 'astron': '天文',
    'fin': '金融', 'bus': '商务', 'mahj': '麻将', 'shogi': '将棋', 'go': '围棋',
    'gramm': '语法', 'elec': '电力', 'mech': '机械', 'photo': '摄影', 'telec': '通信',
    'Christn': '基督教', 'myth': '神话', 'fict': '虚构', 'game': '游戏',
    # 名字类别
    'surname': '姓', 'given': '名', 'place': '地名', 'person': '人名',
    'company': '公司名', 'product': '产品名', 'work': '作品名', 'char': '角色名',
    'creat': '创作', 'organization': '组织名', 'group': '团体名',
    # 方言
    'ksb': '关西', 'ktb': '九州', 'rkb': '琉球', 'thb': '东北', 'tsb': '土佐',
    'hob': '北陆', 'nag': '长野', 'kyb': '京都', 'osb': '大阪', 'kyu': '旧语',
}


def zh_tags(codes, jmd=None) -> str:
    """代码 → 中文；认不出的保留原码（能拿到 JMdict 的英文说明就附在括号里）。"""
    out = []
    for code in codes:
        if not code or code == '*':
            continue
        if code in TAG_ZH:
            out.append(TAG_ZH[code])
            continue
        desc = ''
        try:
            desc = (jmd.tags or {}).get(code, '') if jmd is not None else ''
        except Exception:  # noqa: BLE001
            desc = ''
        out.append('%s(%s)' % (code, desc) if desc else code)
    # 去重且保序
    seen, uniq = set(), []
    for item in out:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return '·'.join(uniq)


# ---------------------------------------------------------------------------
# 2. 文本归一化：全角/半角、平假名⇄片假名
# ---------------------------------------------------------------------------
def normalize(query: str) -> str:
    q = unicodedata.normalize('NFKC', query or '').strip()
    q = q.strip('\u3000').strip()
    return q


def kata2hira(s: str) -> str:
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in s)


def hira2kata(s: str) -> str:
    return ''.join(chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c for c in s)


def _kana_variants(q: str) -> list[str]:
    """同一串音的另一套假名（去重、只留真正不同的）。"""
    out = []
    for cand in (kata2hira(q), hira2kata(q)):
        if cand != q and cand not in out:
            out.append(cand)
    return out


# ---------------------------------------------------------------------------
# 3. 输出格式化
# ---------------------------------------------------------------------------
def _forms(items, mark_common=True) -> str:
    parts = []
    for it in items:
        s = it.text + ('★' if (mark_common and it.common) else '')
        if getattr(it, 'applies_to_kanji', None) and it.applies_to_kanji not in (['*'], []):
            s += '→' + '/'.join(it.applies_to_kanji)
        parts.append(s)
    return '、'.join(parts)


def _xref(items) -> str:
    """交叉引用格式化。

    JMdict 把「第几个义项」塞在假名后面（``[["下手","へた・1",1]]``），
    jmdictpy 的 ``Xref.__str__`` 会拼成 ``下手・へた・1・[1]`` 这种鬼东西，所以自己拼。
    """
    out = []
    for x in items or []:
        k = getattr(x, 'kanji', None) or ''
        n = getattr(x, 'kana', None) or ''
        si = getattr(x, 'sense_index', None)
        m = re.match(r'^(.*?)・(\d+)$', n)
        if m:
            n = m.group(1)
            si = si or m.group(2)
        s = k
        if n:
            s += '【%s】' % n
        if si:
            s += '[义项%s]' % si
        if s:
            out.append(s)
    return '、'.join(out)


def fmt_entry(e, jmd=None, max_senses=6, max_glosses=4, head='') -> str:
    kanji = _forms(e.kanji)
    kana = _forms(e.kana)
    name = e.primary_kanji or e.primary_kana or '?'
    reading = ''
    if e.primary_kanji and e.primary_kana:
        reading = '【%s】' % e.primary_kana
    star = '★常用 ' if e.is_common else ''
    lines = ['%s%s%s %sid=%s' % (head, name, reading, star, e.id)]
    if len(e.kanji) > 1:
        lines.append('   笔形: ' + kanji)
    if len(e.kana) > 1:
        lines.append('   读音: ' + kana)
    senses = e.senses[:max_senses]
    for i, s in enumerate(senses, 1):
        pos = zh_tags(s.part_of_speech, jmd)
        glosses = [g.text for g in s.glosses if g.lang in ('eng', 'en')][:max_glosses]
        extra = [g.text for g in s.glosses if g.lang not in ('eng', 'en')][:max_glosses]
        line = '   %d) %s｜%s' % (i, pos or '—', '; '.join(glosses) or '（无英文释义）')
        if extra:
            line += '  [%s]' % '; '.join(extra)
        tags = zh_tags(list(s.misc) + list(s.fields) + list(s.dialect), jmd)
        if tags:
            line += '  〔%s〕' % tags
        lines.append(line)
        info = [x for x in (s.info or []) if x]
        if info:
            lines.append('      说明: ' + ' / '.join(info[:2]))
        limits = []
        if s.applies_to_kanji not in (['*'], [], None):
            limits.append('笔形=' + '/'.join(s.applies_to_kanji))
        if s.applies_to_kana not in (['*'], [], None):
            limits.append('读音=' + '/'.join(s.applies_to_kana))
        if limits:
            lines.append('      适用: ' + '；'.join(limits))
        rel, ant = _xref(s.related), _xref(s.antonym)
        if rel:
            lines.append('      参考: ' + rel)
        if ant:
            lines.append('      反义: ' + ant)
        src = ['%s:%s' % (ls.lang, ls.text or '') for ls in (s.language_source or [])]
        if src:
            lines.append('      语源: ' + '、'.join(src))
    if len(e.senses) > len(senses):
        lines.append('   …另有 %d 个义项（--senses N 调大）' % (len(e.senses) - len(senses)))
    return '\n'.join(lines)


def fmt_entry_short(e, jmd=None) -> str:
    reading = ''
    if e.primary_kanji and e.primary_kana:
        reading = '【%s】' % e.primary_kana
    first = ''
    if e.senses:
        s = e.senses[0]
        pos = zh_tags(s.part_of_speech, jmd)
        g = [x.text for x in s.glosses if x.lang in ('eng', 'en')][:3]
        first = '%s｜%s' % (pos or '—', '; '.join(g) or '（无英文释义）')
    star = '★' if e.is_common else ''
    return '%s%s%s %s %s' % (e.primary_kanji or e.primary_kana or '?', reading, star, first, e.id)


def fmt_name(n, jmd=None) -> str:
    forms = []
    if n.primary_kanji:
        forms.append(n.primary_kanji)
    if n.primary_kana:
        forms.append('【%s】' % n.primary_kana)
    head = ''.join(forms) or '?'
    romaji = n.romaji
    types = zh_tags(n.name_types, jmd)
    return '  %s%s%s %s' % (head, ' ' + romaji if romaji else '',
                            ' 〔%s〕' % types if types else '', n.id)


def fmt_char(c, jmd=None) -> str:
    parts = ['  %s' % c.literal]
    if c.readings_on:
        parts.append('音读: ' + '、'.join(c.readings_on))
    if c.readings_kun:
        parts.append('训读: ' + '、'.join(c.readings_kun))
    if c.meanings:
        parts.append('义: ' + '; '.join(c.meanings[:5]))
    if c.grade:
        parts.append('学年: %d' % c.grade)
    if c.stroke_count:
        parts.append('笔画: %d' % c.stroke_count)
    if c.jlpt_level:
        parts.append('JLPT: N%d' % c.jlpt_level)
    if c.frequency:
        parts.append('频率: %d' % c.frequency)
    return ' ｜ '.join(parts)


# ---------------------------------------------------------------------------
# 4. JSON 输出（给程序/需要精确字段时用）
# ---------------------------------------------------------------------------
def entry_dict(e) -> dict:
    return {
        'id': e.id,
        'common': e.is_common,
        'kanji': [{'text': k.text, 'common': k.common} for k in e.kanji],
        'kana': [{'text': k.text, 'common': k.common,
                  'applies_to_kanji': k.applies_to_kanji} for k in e.kana],
        'senses': [{
            'pos': list(s.part_of_speech),
            'pos_zh': zh_tags(s.part_of_speech) or '',
            'glosses': [g.text for g in s.glosses if g.lang in ('eng', 'en')],
            'other_glosses': [{'lang': g.lang, 'text': g.text}
                              for g in s.glosses if g.lang not in ('eng', 'en')],
            'misc': list(s.misc), 'fields': list(s.fields), 'dialect': list(s.dialect),
            'info': list(s.info),
            'applies_to_kanji': list(s.applies_to_kanji),
            'applies_to_kana': list(s.applies_to_kana),
            'related': [str(x) for x in s.related if str(x)],
            'antonym': [str(x) for x in s.antonym if str(x)],
        } for s in e.senses],
    }


# ---------------------------------------------------------------------------
# 5. 打开词典
# ---------------------------------------------------------------------------
def data_dir(args) -> Path:
    return Path(args.data_dir).expanduser().resolve() if args.data_dir else DEFAULT_DATA_DIR


def open_dict(args, need_db=True):
    """→ (JMDict 实例, db 路径)。auto_update 永远关（离线优先）。"""
    ddir = data_dir(args)
    db = ddir / 'jmdict.db'
    os.environ['JMDICTPY_DATA_DIR'] = str(ddir)      # jmdictpy.config 在 import 时读一次
    try:
        from jmdictpy import JMDict
    except ImportError:
        sys.stderr.write(
            'jmdictpy 没装。本工作区的装法（不进系统环境）：\n'
            '  & $PY code\\oneshot\\install_workspace_wheels.py jmdictpy\n')
        raise SystemExit(EXIT_ENV)
    if need_db and not db.is_file():
        sys.stderr.write(
            '词典库还没建：%s\n首次建库（联网下载 ~11MB，1–2 分钟）：\n'
            '  & $PY %s build\n' % (db, HERE))
        raise SystemExit(EXIT_ENV)
    return JMDict(db_path=db, auto_update=False), db


# ---------------------------------------------------------------------------
# 6. 子命令
# ---------------------------------------------------------------------------
def cmd_status(args):
    ddir = data_dir(args)
    db = ddir / 'jmdict.db'
    ver = ddir / 'version.json'
    print('词典库 : %s' % db)
    print('数据目录: %s' % ddir)
    try:
        import jmdictpy
        print('jmdictpy: %s (%s)' % (getattr(jmdictpy, '__version__', '?'),
                                     Path(jmdictpy.__file__).parent))
    except ImportError:
        print('jmdictpy: 未安装 ✗  → & $PY code\\oneshot\\install_workspace_wheels.py jmdictpy')
        if not db.is_file():
            return EXIT_ENV
    if not db.is_file():
        print('db     : 不存在 ✗  → & $PY %s build' % HERE)
        return EXIT_ENV
    print('db 大小: %.1f MB' % (db.stat().st_size / 1048576))
    info = {}
    if ver.is_file():
        try:
            info = json.loads(ver.read_text(encoding='utf-8'))
        except Exception:  # noqa: BLE001
            info = {}
    print('版本   : %s（dictDate %s，%s）' % (
        info.get('tag', '?'), info.get('dict_date', '?'),
        '仅常用词' if info.get('common_only') else '全量'))
    # 计数走 jmdictpy 自己的连接（不自建 sqlite3 客户端——本工作区对「另开 Anki 客户端」
    # 有机械自审，虽然这里连的是词典库不是收藏库，也别给审计留噪声）
    from jmdictpy.database import Database
    dbh = Database(db)
    try:
        for tbl, label in (('entries', 'JMdict 条目'), ('names', 'JMnedict 名字'),
                           ('characters', 'Kanjidic 汉字')):
            try:
                n = dbh.conn.execute('SELECT count(*) FROM %s' % tbl).fetchone()[0]
                print('%-12s %d' % (label, n))
            except Exception:  # noqa: BLE001
                print('%-12s 缺表 ✗（换 --common / 重建）' % label)
    finally:
        dbh.close()
    print('调用开销: 单次约 0.5–0.8s（Python 启动 + 开库占大头）；一次传多个词只付一次')
    return EXIT_OK


def _release_urls(language='eng', common_only=False) -> tuple:
    """自己挑 GitHub Release 资产。

    为什么不用 ``VersionManager.get_download_urls``：jmdictpy 0.1.1 用
    ``name.startswith("jmdict-eng")`` 匹配，而 ``jmdict-eng-common-…`` 也命中同一个前缀，
    **永远装成常词库**（22,647 条，而不是 21 万条全量）。这里用 ``jmdict-eng-<数字>``
    精确排除 ``-common``。
    """
    from jmdictpy.version import VersionManager
    vm = VersionManager()
    rel = vm.get_remote_release()
    if not rel:
        raise RuntimeError('拿不到 GitHub Release（网络或 GitHub 不可达）')
    urls = {}
    for a in rel.get('assets', []):
        name, url = a.get('name', ''), a.get('browser_download_url', '')
        if not name.endswith('.json.zip'):
            continue
        if common_only:
            if name.startswith('jmdict-%s-common-' % language):
                urls['jmdict'] = url
        elif re.match(r'^jmdict-%s-\d' % re.escape(language), name):
            urls['jmdict'] = url
        if name.startswith('jmnedict-all-'):
            urls['jmnedict'] = url
        if name.startswith('kanjidic2-en-'):
            urls['kanjidic'] = url
    return vm, rel, urls


def _download_and_build(ddir: Path, common=False, names=True) -> dict:
    """下载 release 资产 → 建 SQLite → 写 version.json。返回摘要。"""
    ddir.mkdir(parents=True, exist_ok=True)
    db = ddir / 'jmdict.db'
    os.environ['JMDICTPY_DATA_DIR'] = str(ddir)
    import logging
    logging.basicConfig(level=logging.WARNING)
    from jmdictpy.config import ensure_data_dir
    from jmdictpy.database import DatabaseBuilder
    from jmdictpy.downloader import DownloadManager
    from jmdictpy.version import VersionInfo
    ensure_data_dir()

    vm, rel, urls = _release_urls('eng', common)
    if 'jmdict' not in urls:
        raise RuntimeError('release 里没有找到 jmdict 资产（语言 eng / common=%s）' % common)
    dm = DownloadManager()
    data = {}
    order = [('jmdict', 'JMdict'), ('jmnedict', 'JMnedict'), ('kanjidic', 'Kanjidic')]
    for key, label in order:
        if key == 'jmnedict' and not names:
            continue
        if key not in urls:
            continue
        print('  下载 %s …' % label, flush=True)
        data[key] = dm.download_and_extract_json(urls[key])

    print('  建 SQLite（%s）…' % db, flush=True)
    tags = data['jmdict'].get('tags', {})
    DatabaseBuilder(db).build(data, tags)
    vm.save_local_version(VersionInfo(
        tag=rel.get('tag_name', 'unknown'),
        published_at=rel.get('published_at'),
        dict_date=data['jmdict'].get('dictDate'),
        languages=data['jmdict'].get('languages', ['eng']),
        common_only=common,
    ))
    return {'db': db, 'tag': rel.get('tag_name'), 'size': db.stat().st_size,
            'entries': len(data['jmdict'].get('words', [])),
            'names': len(data.get('jmnedict', {}).get('words', []))}


def cmd_build(args):
    ddir = data_dir(args)
    db = ddir / 'jmdict.db'
    if db.is_file() and not args.force:
        print('已存在：%s（%.1f MB）。要重建加 --force。' % (db, db.stat().st_size / 1048576))
        return EXIT_OK
    print('开始建库：%s%s' % (ddir, '（仅常用词）' if args.common else '（全量）'))
    print('  jmdict-eng%s + jmnedict-all + kanjidic2-en，压缩包约 11–25 MB；建库 1–3 分钟…'
          % ('-common' if args.common else ''), flush=True)
    try:
        got = _download_and_build(ddir, common=args.common, names=not args.no_names)
    except Exception as exc:  # noqa: BLE001  网络/磁盘问题要给人话
        sys.stderr.write('建库失败：%s: %s\n' % (type(exc).__name__, exc))
        return EXIT_ENV
    print('建库完成：%d 条 JMdict / %d 条名字，版本 %s，%.1f MB'
          % (got['entries'], got['names'], got['tag'], got['size'] / 1048576))
    return EXIT_OK


def cmd_update(args):
    jmd, db = open_dict(args)
    try:
        local, remote, avail = jmd.check_for_updates()
    finally:
        jmd.close()
    print('本地: %s' % (local or '?'))
    print('远端: %s' % (remote or '（拿不到，检查网络/GitHub）'))
    if not avail:
        print('结论：已是最新（或远端不可达）。')
        return EXIT_OK
    print('结论：有新版本。')
    if args.check:
        print('（--check：只查不装）')
        return EXIT_OK
    ddir = data_dir(args)
    info = {}
    try:
        info = json.loads((ddir / 'version.json').read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        info = {}
    common = bool(info.get('common_only'))
    print('正在更新（common=%s）…' % common, flush=True)
    try:
        got = _download_and_build(ddir, common=common)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write('更新失败：%s: %s\n' % (type(exc).__name__, exc))
        return EXIT_ENV
    print('更新完成：%d 条，版本 %s，%.1f MB'
          % (got['entries'], got['tag'], got['size'] / 1048576))
    return EXIT_OK


def cmd_lookup(args, as_json=False):
    jmd, _ = open_dict(args)
    rows = []
    try:
        for raw in args.words:
            q = normalize(raw)
            hit = jmd.lookup(q, limit=args.limit)
            tried = [q]
            if not hit:
                for variant in _kana_variants(q):
                    tried.append(variant)
                    hit = jmd.lookup(variant, limit=args.limit)
                    if hit:
                        break
            rows.append({'query': raw, 'tried': tried, 'hit': hit})
        if as_json:
            payload = []
            for row in rows:
                hit = row['hit']
                payload.append({
                    'query': row['query'], 'tried': row['tried'], 'hit': bool(hit),
                    'entries': [entry_dict(e) for e in hit.entries],
                    'names': [{'id': n.id, 'kanji': n.primary_kanji, 'kana': n.primary_kana,
                               'romaji': n.romaji, 'types': n.name_types}
                              for n in hit.names],
                    'characters': [{'literal': c.literal, 'on': c.readings_on,
                                    'kun': c.readings_kun, 'meanings': c.meanings,
                                    'grade': c.grade, 'strokes': c.stroke_count}
                                   for c in hit.characters],
                })
            print(json.dumps(payload if len(payload) > 1 else payload[0],
                             ensure_ascii=False, separators=(',', ':')))
        else:
            for row in rows:
                raw, tried, hit = row['query'], row['tried'], row['hit']
                print('── %s ──' % raw)
                if not hit:
                    print('  未命中。只做精确匹配：查词典形（食べる 而非 食べた）、'
                          '换假名/汉字写法、或改用 meaning / char 子命令。')
                    print('  试过: ' + '、'.join(tried))
                    continue
                for i, e in enumerate(hit.entries, 1):
                    print(fmt_entry(e, jmd, max_senses=args.senses, max_glosses=args.glosses,
                                    head='%d. ' % i))
                if hit.names:
                    print('  名字（JMnedict）:')
                    for n in hit.names:
                        print(fmt_name(n, jmd))
                for c in hit.characters:
                    print(fmt_char(c, jmd))
                print()
    finally:
        jmd.close()
    return EXIT_OK if any(bool(r['hit']) for r in rows) else EXIT_EMPTY


def cmd_reading(args):
    jmd, _ = open_dict(args)
    empty = True
    try:
        for raw in args.kana:
            q = normalize(raw)
            entries = jmd.lookup_by_reading(q)
            tried = [q]
            if not entries:
                for variant in _kana_variants(q):
                    tried.append(variant)
                    entries = jmd.lookup_by_reading(variant)
                    if entries:
                        break
            print('── 读音: %s ──' % raw)
            if not entries:
                print('  未命中（试过 %s）。读音索引只认假名；汉字请用 lookup。' % '、'.join(tried))
                continue
            empty = False
            for i, e in enumerate(entries, 1):
                print(fmt_entry(e, jmd, max_senses=args.senses, max_glosses=args.glosses,
                                head='%d. ' % i))
            print()
    finally:
        jmd.close()
    return EXIT_OK if not empty else EXIT_EMPTY


def _fts_query(text: str) -> str:
    """把自由文本变成安全的 FTS5 查询：逐词加引号，词间 AND。"""
    tokens = [t for t in re.split(r'\s+', text.strip()) if t]
    return ' AND '.join('"%s"' % t.replace('"', '""') for t in tokens)


def _rank_entries(entries, raw: str, limit: int) -> list:
    """FTS 结果没有排序（jmdictpy 直接 LIMIT，顺序是随机的），这里补一个有意义的排序：

    释义**完全等于**查询词 > 以查询词**开头** > 常用词 > 释义条数少（更专指）。
    """
    q = raw.strip().lower()

    def key(e):
        texts = [g.text.lower() for s in e.senses for g in s.glosses
                 if g.lang in ('eng', 'en')]
        exact = 0 if q in texts else 1
        prefix = 0 if any(t.startswith(q) for t in texts) else 1
        common = 0 if e.is_common else 1
        return (exact, prefix, common, len(texts), e.id)

    return sorted(entries, key=key)[:limit]


def cmd_meaning(args):
    jmd, _ = open_dict(args)
    empty = True
    try:
        for raw in args.text:
            query = raw if args.fts else _fts_query(raw)
            pool = max(args.limit * 25, 250)
            found = jmd.search(query, limit=pool)
            entries = _rank_entries(found, raw, args.limit) if found else []
            print('── 释义: %s ──%s' % (
                raw, '（共 %d 条，显示 %d）' % (len(found), len(entries)) if found else ''))
            if not entries:
                print('  未命中。FTS 只索引**英文**释义；中文请先把关键词译成英文短词'
                      '（如 吃 → eat）。原始 FTS 语法用 --fts。')
                continue
            empty = False
            for i, e in enumerate(entries, 1):
                if args.short:
                    print('  %2d. %s' % (i, fmt_entry_short(e, jmd)))
                else:
                    print(fmt_entry(e, jmd, max_senses=args.senses, max_glosses=args.glosses,
                                    head='%d. ' % i))
            print()
    finally:
        jmd.close()
    return EXIT_OK if not empty else EXIT_EMPTY


def cmd_name(args):
    jmd, _ = open_dict(args)
    empty = True
    try:
        for raw in args.text:
            q = normalize(raw)
            names = jmd.lookup_name(q, limit=args.limit)
            # 中文汉字简繁/异体不在 JMnedict 里，直接如实报告
            print('── 名字: %s ──' % raw)
            if not names:
                print('  未命中（JMnedict 没有这个写法；网络新词/作品造语多半查不到）。')
                continue
            empty = False
            for n in names:
                print(fmt_name(n, jmd))
            print()
    finally:
        jmd.close()
    return EXIT_OK if not empty else EXIT_EMPTY


def cmd_char(args):
    jmd, _ = open_dict(args)
    empty = True
    try:
        for raw in args.chars:
            q = normalize(raw)
            print('── 汉字: %s ──' % raw)
            if len(q) != 1:
                print('  只接受单个汉字。')
                continue
            c = jmd.lookup_character(q)
            if not c:
                print('  未命中（Kanjidic 没收这个字）。')
                continue
            empty = False
            print(fmt_char(c, jmd))
            print()
    finally:
        jmd.close()
    return EXIT_OK if not empty else EXIT_EMPTY


def cmd_id(args):
    jmd, _ = open_dict(args)
    empty = True
    try:
        for raw in args.ids:
            e = jmd.lookup_by_id(raw.strip())
            print('── id: %s ──' % raw)
            if not e:
                print('  未命中。')
                continue
            empty = False
            print(fmt_entry(e, jmd, max_senses=args.senses, max_glosses=args.glosses))
            print()
    finally:
        jmd.close()
    return EXIT_OK if not empty else EXIT_EMPTY


# ---------------------------------------------------------------------------
# 7. CLI
# ---------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        prog='jmdict.py', description='JMdict（jmdictpy）只读查询 —— 语义澄清用',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='例：jmdict.py lookup 食べる / meaning "to eat" --short / char 食')
    ap.add_argument('--data-dir', help='词典库目录（默认 <工作区>/data/dict/jmdictpy）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('status', help='库状态：在不在、多大、版本、条目数')
    p.set_defaults(func=cmd_status)

    p = sub.add_parser('build', help='首次建库 / 重建（联网）')
    p.add_argument('--common', action='store_true', help='只建常用词库（小很多，覆盖差，不推荐）')
    p.add_argument('--no-names', action='store_true', help='不装 JMnedict（省 ~300MB，name 子命令失效）')
    p.add_argument('--force', action='store_true', help='已有库也重建')
    p.set_defaults(func=cmd_build)

    p = sub.add_parser('update', help='检查/安装新版本')
    p.add_argument('--check', action='store_true', help='只查不装')
    p.set_defaults(func=cmd_update)

    def detail(p, senses=6, glosses=4):
        p.add_argument('--senses', type=int, default=senses, help='每个条目最多几个义项（默认 %d）' % senses)
        p.add_argument('--glosses', type=int, default=glosses, help='每个义项最多几条英文释义（默认 %d）' % glosses)
        return p

    p = detail(sub.add_parser('lookup', help='主查询：汉字/假名精确匹配'))
    p.add_argument('words', nargs='+', help='词形或读音，可多个')
    p.add_argument('--limit', type=int, default=8, help='最多几个条目（默认 8）')
    p.add_argument('--json', action='store_true', help='输出 JSON（单行紧凑）')
    p.set_defaults(func=cmd_lookup)

    p = detail(sub.add_parser('reading', help='只按读音（假名）查'))
    p.add_argument('kana', nargs='+')
    p.set_defaults(func=cmd_reading)

    p = detail(sub.add_parser('meaning', help='按英文释义全文搜索（FTS5）'))
    p.add_argument('text', nargs='+')
    p.add_argument('--limit', type=int, default=10)
    p.add_argument('--short', action='store_true', help='每个条目只打一行（扫候选时用）')
    p.add_argument('--fts', action='store_true', help='原样当 FTS5 查询串（"eat*" AND "food"）')
    p.set_defaults(func=cmd_meaning)

    p = sub.add_parser('name', help='JMnedict 人名/地名')
    p.add_argument('text', nargs='+')
    p.add_argument('--limit', type=int, default=10)
    p.set_defaults(func=cmd_name)

    p = sub.add_parser('char', help='Kanjidic 单字')
    p.add_argument('chars', nargs='+')
    p.set_defaults(func=cmd_char)

    p = detail(sub.add_parser('id', help='按 JMdict id 取条目'))
    p.add_argument('ids', nargs='+')
    p.set_defaults(func=cmd_id)

    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd == 'lookup' and getattr(args, 'json', False):
        return cmd_lookup(args, as_json=True)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
