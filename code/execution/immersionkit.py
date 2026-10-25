# -*- coding: utf-8 -*-
"""ImmersionKit → 对白例句卡 + 素材生词卡（fetch → gen → write → verify）。

为什么有这个脚本
----------------
现有例句卡是「字幕 + 视频」pipeline 做出来的（code/execution/episode.py 等）。
ImmersionKit 把同一件事免费提供了：**原声** + **剧照** + **母语级振假名** + 英文译文，
而且可以**按词检索**。本脚本把「一个日语词表」直接变成有图有声的例句卡与素材生词卡。

四个子命令（默认全程演练，``--commit`` 才写库）
----------------------------------------------
    # 0. 词表：一行一个词（UTF-8；允许 ``#`` 注释与「词<TAB>条数」覆盖 --n）
    & $PY code\\cli.py immersion fetch  --words-file data\\immersion\\words.txt
    & $PY code\\cli.py immersion gen
    & $PY code\\cli.py immersion write  --to both              # 演练
    & $PY code\\cli.py immersion write  --to both --commit     # 真写
    & $PY code\\cli.py immersion verify

落点（**不是**网站原生卡片，用仓库现有模型）
--------------------------------------------
* 例句卡 → ``0-日本语学习::2-例句``，模型 ``Basic``
  （Sentence / Word / Sentence HTML / AINote / Image / Sentence Audio / Source / URL）——
  实测该牌组现有 467 张**全是**这个模型，它带 Image 字段，正好放剧照。
* 素材生词卡 → ``0-日本语学习::0-词汇::0-素材生词``，模型 ``Japanese Vocabulary``
  （14 字段）—— 与 core6000 / mine.py 同模板，JitenAnimeRank 排序与弱项分析通用。
* 库里那个空的 ``ImmersionKitCard``（0 张）**不碰**。

判据
----
* 剔掉已在 core6000 / 考级词汇里的词（``pipeline.rebuild_known_index()``，
  与 mine.py 同一套归一化，不另立口径）；
* 剔掉两个目标牌组里已有 ``Word`` 的词 —— **必须自己查**：``addNotes`` 的查重只看
  首字段，而 ``Index`` 每张新卡都唯一，等于没查重（见 mine.py:1350 的说明）；
* 其余按 ``JitenAnimeRank`` 升序（词表里没有的词写 999999，排最后）。

产物（``data/immersion/``）：``fetch_<时间戳>.json`` / ``plan_<时间戳>.json`` /
``plan_write_<时间戳>.json`` / ``written_<时间戳>.json`` / ``report_<时间戳>.md`` /
``latest.json``（后一步默认读它）/ ``cache/``（接口响应）/ ``media/``（--keep-media）。

依赖：AnkiConnect 127.0.0.1:8765（只经 code/common/anki_api.py）；
      ImmersionKit 只读接口见 code/common/immersion_api.py；
      本地模型见 code/common/local_llm.py（``--no-ainote`` 可跳过）。
"""
import argparse
import datetime as dt
import os
import re
import sys
import threading
import time
from urllib.parse import quote
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'common'))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'analysis', 'vocab_cover'))

import anki_api as AK          # noqa: E402  唯一的 Anki 访问点
import check_mine as CM        # noqa: E402  素材生词条目的唯一规则实现（含 llm_out 吸收层）
import immersion_api as IM     # noqa: E402  ImmersionKit 只读客户端 + 纯函数
import jp_decks as JD          # noqa: E402  牌组路径的唯一来源
import mine as M               # noqa: E402  jiten_rank / next_index / load_jiten_index
import paths as WSP            # noqa: E402  工作区路径的唯一来源
import pipeline as P           # noqa: E402  norm / strip_html / rebuild_known_index
import textio                  # noqa: E402  UTF-8 stdio 与文件读写唯一入口

DECK_EXAMPLE = JD.DECK_EXAMPLE                 # 0-日本语学习::2-例句
DECK_MINED = JD.DECK_MINED                     # 0-日本语学习::0-词汇::0-素材生词
MODEL_EXAMPLE = 'Basic'                        # 该 deck 现有 467 张全是它
MODEL_MINED = 'Japanese Vocabulary'            # 与 core6000 / mine.py 同模板
BASIC_FIELDS = ('Sentence', 'Word', 'Sentence HTML', 'AINote', 'Image',
                'Sentence Audio', 'Source', 'URL')
JVOCAB_FIELDS = ('Index', 'JitenAnimeRank', 'Word', 'Sentence', 'Sentence HTML',
                 'Transliteration', 'Meaning', 'Part of Speech', 'AINote',
                 'Sentence Translation', 'Word Audio', 'Sentence Audio',
                 'Pitch Accent URL', 'Pitch Accent')
WORD_FIELD = 'Word'
# 标签口径（用户 2026-10-17）：例句卡 = 动画::<中文名> / 日剧::<中文名>（整部一个标签），
# 素材卡 = 裸 素材生词。原来的 沉浸式::<类别>::<slug> 与 素材生词::<日期>/::IK-<slug>
# 已于当天全库改名/收敛（docs/evidence/immersion-tag-retag-2026-10-17.md），别再写回去。
TAG_NS_ANIME = '动画'
TAG_NS_DRAMA = '日剧'
SLUG_MAP = os.path.join(WSP.EVIDENCE, 'immersion_retag', 'slug_map.yaml')
RUBY_SPARE = 8                                 # 选句时多挑几条备用，优先振假名对得上
MIN_PICK_LEN = 8                               # 头一条短于这个长度时，尽量换长的那条
TOKEN_SCAN = 80                                # 一条真命中都没有时，再扫这么多条候选

DATA = WSP.DATA_IMMERSION
GEN_DIR = os.path.join(DATA, 'gen')
LATEST = os.path.join(DATA, 'latest.json')
MEDIA_FAILURES = []                            # 这一轮下不下来的媒体（供写库后汇报）
STEM_RE = re.compile(r'[^0-9A-Za-z_]')
RT_BLOCK = re.compile(r'<rt>.*?</rt>', re.S)


# ============================================================================
# 小工具
# ============================================================================
def stamp():
    return dt.datetime.now().strftime('%Y%m%d-%H%M%S')


def text_of(html):
    """与 ``code/common/check_cards.py`` 的 ``text_of`` 同口径：
    先删 ``<rt>…</rt>`` **整块**（读音不能算进正文），再剥其余标签。
    ``IM.plain()`` 是给「纯文本基」用的，直接喂 HTML 会把读音留在里面 —— 别混用。
    """
    return IM.strip_tags(RT_BLOCK.sub('', html or ''))


_SLUG_MAP = {}
CATEGORY_NS = {'anime': TAG_NS_ANIME, 'drama': TAG_NS_DRAMA,
               'games': '游戏', 'literature': '文学', 'news': '新闻'}


def slug_map():
    """→ {slug: 中文名}，读 ``data/evidence/immersion_retag/slug_map.yaml``。

    那张表是 2026-10-17 逐条检索核实过的 88 个作品名；表里没有的作品本函数不猜，
    由 :func:`example_tag` 退回英文 slug，跑完再补表（改名是一次 ``replaceTags``）。
    """
    if not _SLUG_MAP:
        try:
            raw = textio.read_text(SLUG_MAP)
        except Exception:                       # noqa: BLE001  表不在就全用 slug
            raw = ''
        for line in raw.splitlines():
            line = line.split('#')[0].strip()
            if '=>' not in line:
                continue
            slug, name = [p.strip() for p in line.split('=>', 1)]
            name = re.sub(r'\s+', '', name)     # 标签里不能有空格（Anki 按空格切分）
            if slug and name:
                _SLUG_MAP[slug] = name
    return _SLUG_MAP


def example_tag(category, slug):
    """例句卡标签：``动画::<中文名>`` / ``日剧::<中文名>``；没映射就先用 slug 顶着。"""
    ns = CATEGORY_NS.get(category or '', TAG_NS_ANIME)
    name = slug_map().get(slug) or re.sub(r'\s+', '', slug or '')
    return '%s::%s' % (ns, name)


def rel(path):
    return os.path.relpath(path, WSP.ROOT)


def info(msg):
    print(msg)
    sys.stdout.flush()


def unrubied_kanji(html):
    """HTML 里**没有 ruby** 的汉字（check_cards 把这个当硬错）。空串 = 合格。"""
    outside = IM.strip_tags(re.sub(r'<ruby>.*?</ruby>', '', html or '', flags=re.S))
    return ''.join(IM.HAN_RE.findall(outside))


def media_stem(example_id):
    """媒体文件名主干：``ik_<id>``（id 全局唯一 → 天然去重、可重跑覆盖）。"""
    return 'ik_' + STEM_RE.sub('_', str(example_id))


def load_state(path):
    state = textio.load_json(path, default=None)
    if not isinstance(state, dict) or 'plan' not in state:
        raise SystemExit('❌ 读不到可用的计划文件：%s\n   先跑 immersion fetch（再跑 gen）。' % path)
    return state


def save_state(state, path, also_latest=True):
    textio.dump_json(state, path, indent=1)
    if also_latest and os.path.abspath(path) != os.path.abspath(LATEST):
        textio.dump_json(state, LATEST, indent=1)
    return path


def existing_words():
    """两个目标牌组里已有的 ``Word``（归一化）—— 新增卡的去重闸门。"""
    have = set()
    for deck in (DECK_EXAMPLE, DECK_MINED):
        for n in AK.notes_info(AK.find_notes('deck:"%s"' % deck)):
            w = P.norm((n.get('fields', {}).get(WORD_FIELD, {}) or {}).get('value', ''))
            if w:
                have.add(w)
    return have


def deck_identity():
    """两个目标牌组里已有的 ``(牌组, 归一化 Word, 归一化 Sentence)``。

    这就是新增卡的身份：``Word`` 单独不够（同一个词可以有多条例句），
    ``Index`` 更不行（每次都新分配，AnkiConnect 拿它当首字段查重等于没查）。
    """
    seen = set()
    for deck in (DECK_EXAMPLE, DECK_MINED):
        for n in AK.notes_info(AK.find_notes('deck:"%s"' % deck)):
            fields = n.get('fields', {})
            word = P.norm((fields.get(WORD_FIELD, {}) or {}).get('value', ''))
            sent = P.norm((fields.get('Sentence', {}) or {}).get('value', ''))
            if word and sent:
                seen.add((deck, word, sent))
    return seen


def jiten_ranks():
    jiten = M.load_jiten_index()
    return jiten, (lambda w: int(M.jiten_rank(w, jiten)))


def ensure_media(filename, url, keep=False, have=None):
    """把 CDN 上的剧照/原声弄进 collection.media；返回状态串。

    ``have`` 是调用方一次性取到的「媒体库已有文件名集合」。逐个文件调
    ``AK.media_names`` 会让每张卡多两次 AnkiConnect 往返（实测 ~1.4 s/文件），
    所以 write 循环里传一份共享集合进来。

    ``keep=True`` 且本地 staging 文件已存在时只做「本地 → Anki」的上传
    （见 :func:`prefetch_media`：并发下载比让 AnkiConnect 逐个拉 URL 快数倍）。
    CDN 上确实有下不下来的文件（2026-10-16 实测：Re:Zero 的
    ``A_ReZeroS01_E04_1_0.19.31.080-0.19.32.670.mp3``、Steins;Gate 的
    ``A_SteinsGateS01_E19_1_0.16.36.065.jpg%3E``（URL 里带了个 %3E）都返回 403），
    AnkiConnect 的 ``storeMediaFile`` 会整条报错。这里**不往外抛**：返回 ``failed``，
    让调用方把这两张卡跳过 —— 而不是让整块 300 条笔记全丢（第一版就是这么丢的）。
    """
    if not url:
        return 'no-url'
    have = set(AK.media_names(filename) or []) if have is None else have
    if filename in have:
        return 'cached'
    dest = os.path.join(IM.MEDIA_DIR, filename)
    try:
        if keep and os.path.exists(dest) and os.path.getsize(dest) > 0:
            AK.store_media_file(filename, path=dest, delete_existing=True)
        elif keep:
            IM.download(url, dest)
            AK.store_media_file(filename, path=dest, delete_existing=True)
        else:
            AK.store_media_file(filename, url=url, delete_existing=True)
    except Exception as exc:                       # noqa: BLE001
        MEDIA_FAILURES.append((filename, '%s: %s' % (type(exc).__name__, str(exc)[:90])))
        return 'failed'
    have.add(filename)
    return 'ok'


def prefetch_media(jobs, workers=8):
    """并发把媒体下到 ``data/immersion/media``（不碰 Anki）。

    AnkiConnect 的 ``storeMediaFile(url=…)`` 是**逐个串行**让 Anki 自己下载，
    实测 ~2.4 s/文件；本函数用线程池先下到本地，再让 write 走本地文件上传。
    """
    os.makedirs(IM.MEDIA_DIR, exist_ok=True)
    items = [(fn, url) for fn, url in jobs if url]
    if not items:
        return

    def one(item):
        fn, url = item
        dest = os.path.join(IM.MEDIA_DIR, fn)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return
        try:
            IM.download(url, dest)
        except Exception:                          # noqa: BLE001
            pass                                   # 失败留给 ensure_media 逐个报告

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, items))


# ============================================================================
# 阶段一：fetch —— 选词、选句、出计划
# ============================================================================
def annotate_ruby(picks):
    """给候选句算振假名 HTML；对不上的留空并记原因（写库时两边一起留空）。"""
    for pick in picks:
        html, ok = IM.furigana_to_html(pick['sentence'],
                                       pick.get('sentence_with_furigana'))
        bad = unrubied_kanji(html) if ok else ''
        pick['_ruby_ok'] = bool(ok and not bad)
        pick['_html'] = html if pick['_ruby_ok'] else ''
        pick['_ruby_note'] = '' if pick['_ruby_ok'] else (
            '振假名对不上，留空' if not ok else '有未注音汉字：%s' % bad)
        pick['_stem'] = media_stem(pick.get('id'))
        pick['_image_url'] = IM.media_url(pick, 'image')
        pick['_sound_url'] = IM.media_url(pick, 'sound')
    return picks


def choose_picks(exs, word, opt, cats, decks, used):
    """选句：小窗口 → 残句换长句 → 振假名闸门 → 取前 n 条。

    两个坑（都是 2026-10-15 实测出来的）：

    * 注音串把 ``我々[われわれ]`` 整词标成一格时 ``furigana_to_html`` 认不出来，
      卡就只剩原句。所以一次多挑几条备用，**优先挑振假名对得上的**（不额外发请求）。
    * 服务端返回的例子是**按句长升序**（见 ``immersion_api.select_sentences`` 的
      文档串），所以窗口里前几条永远是最短的碎片（``…あっ``、``いいや``、``…めろ``，
      ``--min-len 3`` 拦不住）。头一条短于 ``MIN_PICK_LEN`` 时，重新按
      ``min_len=MIN_PICK_LEN`` 扫一遍全文候选 —— 升序之下第一条就是「够用的最短句」。
      探路用 ``used`` 的副本，只有真正选中的 id 才占位。
    """
    def window(lo, holders):
        return IM.select_sentences(exs, word, n=opt.n + RUBY_SPARE, categories=cats,
                                   decks=decks, min_len=lo, max_len=opt.max_len,
                                   used_ids=holders, speaker_max=opt.speaker_max)

    picks = window(opt.min_len, used)
    if picks and IM.text_len(picks[0]['sentence']) < MIN_PICK_LEN:
        wider = window(MIN_PICK_LEN, set(used))
        if wider:
            have = {p.get('id') for p in picks}
            picks = picks + [p for p in wider if p.get('id') not in have]
    if picks and not any(IM.is_token_hit(p, word) for p in picks):
        # 池子里全是「子串假命中」（单假名词容易被这种句子缠上）→ 再扫一遍找真命中。
        # 真命中哪怕句子短也认：宁要「てめっ」这种短句，也不要「ごめんください」。
        probe = IM.select_sentences(exs, word, n=TOKEN_SCAN, categories=cats,
                                    decks=decks, min_len=opt.min_len,
                                    max_len=opt.max_len, used_ids=set(used),
                                    speaker_max=opt.speaker_max)
        hits = [p for p in probe if IM.is_token_hit(p, word)]
        if hits:
            picks = hits + picks
    # 排序（稳定：同档内保持服务端「句长升序」）：
    #   1) 目标词**作为独立词元**出现（单假名词防「子串假命中」）
    #   2) 句子够长（`--min-len 3` 拦不住「…あっ」这种残句）
    picks.sort(key=lambda p: (0 if IM.is_token_hit(p, word) else 1,
                              0 if IM.text_len(p['sentence']) >= MIN_PICK_LEN else 1))
    annotate_ruby(picks)
    good = [p for p in picks if p['_ruby_ok']]
    out = (good or picks)[:opt.n]
    used.update(p.get('id') for p in out if p.get('id'))
    return out


def fetch_one(rec, opt, cats, decks, used, lock):
    """抓一个词的例句并选句（供串行/多线程共用）。

    返回 ``(kind, word, payload)``：
      * ``ok``   → payload ``(plan_rec, 例句条数, 首条 pick)``
      * ``skip`` → payload 是「无可用例句」的原因
      * ``error``→ payload 是「接口失败」的说明
    """
    word = rec['word']
    n = rec['n'] or opt.n
    try:
        data = IM.search(word, category=opt.category, refresh=opt.refresh,
                         delay=opt.delay)
    except IM.ImmersionAPIError as exc:
        return 'error', word, '接口失败：%s' % exc
    exs = data.get('examples') or []
    # choose_picks 会读/写 used（跨词去重同一句），并发时这一段必须串行
    with lock:
        picks = choose_picks(exs, word, opt, cats, decks, used)
    if not picks:
        return 'skip', word, '没有可用例句（共 %d 条）' % len(exs)
    return 'ok', word, ({
        'word': word, 'n': n, 'rank': rec.get('rank'),
        'entry': (data.get('dictionary_entries') or [None])[0],
        'examples_seen': len(exs),
        'picks': picks,
        'reading': picks[0].get('_reading') or '',
        'pos': '', 'meaning': '', 'a_note': '',
        'translation_cn': '', 'gen': '',
    }, len(exs), picks[0])


def cmd_fetch(a):
    WSP.ensure()
    words = IM.read_words_file(a.words_file)
    info('=' * 88)
    info('ImmersionKit fetch ｜ 词表 %s（%d 个词）' % (rel(a.words_file), len(words)))
    info('  筛选口径：剔 core6000/考级 与 目标牌组已有；其余按 JitenAnimeRank 升序')
    info('  选句口径：%s ｜ 每词 ≤%d 条 ｜ 句长 %d–%d ｜ 类别 %s'
         % ('exactMatch', a.n, a.min_len, a.max_len, a.category or '不限'))
    info('=' * 88)

    canon, variant = P.rebuild_known_index()
    have = existing_words()
    jiten, rank_of = jiten_ranks()
    todo, skipped = IM.filter_words(words, canon, variant, have,
                                    rank_of=rank_of, norm=P.norm,
                                    keep_known=a.keep_known)
    if a.keep_known:
        info('  ⚠ --keep-known：只抓 core6000/考级**已有**的词 → 建议配 '
             '`write --to example`，不要建素材生词卡')
    info('')
    info('过滤后待抓 %d 个词；剔除 %d 个' % (len(todo), len(skipped)))
    for w, why in skipped[:15]:
        info('   – %-14s %s' % (w, why))
    if len(skipped) > 15:
        info('   … 其余 %d 个见报告' % (len(skipped) - 15))
    if a.limit:
        todo = todo[:a.limit]
        info('  （--limit %d：只抓前 %d 个）' % (a.limit, len(todo)))
    if not todo:
        info('没有要抓的词。')
        return 0

    cats = [c.strip() for c in (a.category or '').split(',') if c.strip()]
    decks = [d.strip() for d in (a.deck or '').split(',') if d.strip()]
    used, plan = set(), []
    lock = threading.Lock()
    total = len(todo)
    workers = max(1, int(a.workers or 1))
    info('')
    info('  并发 %d 线程（--workers；1 = 串行，缓存命中的词不额外睡）' % workers)

    def run(item):
        i, rec = item
        kind, word, payload = fetch_one(rec, a, cats, decks, used, lock)
        with lock:
            if kind == 'ok':
                rec_out, nex, p0 = payload
                plan.append((i, rec_out))
                info('  [%d/%d] %-12s 排名 %-6s %3d 条 → 选 %d 条 ｜ %s ｜ %s'
                     % (i, total, word, rec.get('rank'), nex, len(rec_out['picks']),
                        p0['_category'], p0['sentence'][:26]))
            else:
                skipped.append((word, payload))
                info('  [%d/%d] %-12s ✗ %s' % (i, total, word, payload))

    if workers == 1:
        for item in enumerate(todo, 1):
            run(item)
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(run, enumerate(todo, 1)))
    plan.sort(key=lambda x: x[0])
    plan = [rec for _i, rec in plan]

    state = {'created': dt.datetime.now().isoformat(timespec='seconds'),
             'words_file': os.path.abspath(a.words_file),
             'options': {'n': a.n, 'min_len': a.min_len, 'max_len': a.max_len,
                         'category': a.category, 'deck': a.deck,
                         'speaker_max': a.speaker_max},
             'skipped': skipped, 'plan': plan}
    out = a.out or os.path.join(DATA, 'fetch_%s.json' % stamp())
    save_state(state, out)
    info('')
    info('计划落盘：%s（%d 个词 / %d 条例句）' % (rel(out), len(plan),
                                          sum(len(r['picks']) for r in plan)))
    write_report(state, 'fetch')
    info('下一步：& $PY code\\cli.py immersion gen')
    return 0


# ============================================================================
# 阶段二：gen —— 本地模型出 读音/词性/释义/翻译/讲解
# ============================================================================
GEN_SYSTEM = '你是日语教学助手，只输出严格 JSON，不要任何解释文字。'


def build_gen_messages(batch):
    lines = []
    for i, rec in enumerate(batch, 1):
        pick = rec['picks'][0]
        lines.append('%d. 目标词：%s\n   例句：%s\n   英文译文：%s'
                     % (i, rec['word'], pick['sentence'], pick['translation']))
    user = (
        '下面是 %d 个日语词条，请逐条给出读音、词性、中文简释、整句中文翻译与 HTML 讲解。\n\n'
        '%s\n\n'
        '只输出 JSON，形状：\n'
        '{"entries":[{"word":"…","reading":"…","pos":"…","meaning":"…",'
        '"translation":"…","a_note":"…"}]}\n'
        '规则：\n'
        '* word：原样抄回目标词\n'
        '* reading：目标词的平假名读音（不要罗马字）\n'
        '* pos：只能取 名词/他动词/自动词/イ形容词/ナ形容词/副词/外来语/惯用句 之一\n'
        '* meaning：中文简释，不超过 25 字，多义用「；」分隔，不要英文\n'
        '* translation：整句自然中文翻译（保留说话人语气）\n'
        '* a_note：HTML，固定三段 —— '
        '<p><b>中文翻译：</b>…</p><p><b>核心词汇：</b><br>词：词性。释义与用法</p>'
        '<p><b>语法要点：</b><br>这句的关键语法或口语缩约</p>；只用 p/b/br 标签\n'
        '* entries 与输入**顺序一致、条数一致**\n'
        % (len(batch), '\n'.join(lines)))
    return [{'role': 'system', 'content': GEN_SYSTEM},
            {'role': 'user', 'content': user}]


def fallback_text(rec):
    """本地模型给不出时的兜底：JMdict 英文释义 + 词性标签。"""
    entry = rec.get('entry') or {}
    meaning = '；'.join(entry.get('glossary_list') or [])[:40]
    return meaning, (entry.get('tags') or ''), (entry.get('reading') or '')


def cmd_gen(a):
    WSP.ensure()
    state = load_state(a.inp)
    plan = state['plan']
    todo = [r for r in plan if r.get('gen') != 'ok']
    if a.limit:
        todo = todo[:a.limit]
    info('=' * 88)
    info('ImmersionKit gen ｜ 待生成 %d 条（计划共 %d 条）' % (len(todo), len(plan)))
    if a.no_ainote:
        info('  --no-ainote：跳过模型，只用 JMdict 释义；AINote 与 Sentence HTML 一起留空')
    info('=' * 88)
    if not todo:
        info('没有要生成的条目。')
        return 0

    LLM = None
    cfg = None
    if not a.no_ainote:
        try:
            import local_llm as LLM  # noqa: F811
        except ImportError as exc:
            raise SystemExit('❌ 找不到本地模型客户端 code/common/local_llm.py：%s' % exc)
        cfg = LLM.load_config()
        info('本地模型：%s ｜ %s' % (cfg.get('model'), cfg.get('base_url')))

    done = 0
    for batch in AK.chunks(todo, a.batch):
        if a.no_ainote:
            for rec in batch:
                meaning, pos, reading = fallback_text(rec)
                rec['meaning'], rec['pos'] = meaning, pos
                rec['reading'] = rec.get('reading') or reading
                rec['translation_cn'] = (rec['picks'][0].get('translation') or '')
                rec['a_note'] = ''
                rec['gen'] = 'fallback'
                done += 1
            continue
        got, res, problems = LLM.call_json(cfg, build_gen_messages(batch),
                                           require='entries', json_mode=True,
                                           quiet=a.quiet)
        by_word = {}
        if isinstance(got, dict):
            for e in got.get('entries') or []:
                if isinstance(e, dict) and e.get('word'):
                    by_word[str(e['word']).strip()] = e
        elif got is not None:
            problems = list(problems) + ['顶层不是对象']
        for rec in batch:
            e = by_word.get(rec['word'])
            if not e:
                meaning, pos, reading = fallback_text(rec)
                rec.update(meaning=meaning, pos=pos,
                           reading=rec.get('reading') or reading,
                           a_note='', gen='fallback')
                if not meaning:
                    rec['gen'] = 'failed'
                continue
            rec['reading'] = str(e.get('reading') or rec.get('reading') or '').strip()
            rec['pos'] = str(e.get('pos') or '').strip()
            rec['meaning'] = str(e.get('meaning') or '').strip()
            rec['translation_cn'] = str(e.get('translation') or '').strip()
            rec['a_note'] = str(e.get('a_note') or '').strip()
            rec['gen'] = 'ok' if rec['meaning'] and rec['a_note'] else 'fallback'
            done += 1
        info('  本批 %d 条 → 命中 %d ｜ 累计 %d/%d'
             % (len(batch), len(by_word), done, len(todo)))
        if problems:
            info('    ⚠ %s' % '；'.join(problems)[:160])

    out = os.path.join(DATA, 'plan_%s.json' % stamp())
    save_state(state, out)
    ok = sum(1 for r in plan if r.get('gen') == 'ok')
    fb = sum(1 for r in plan if r.get('gen') == 'fallback')
    bad = sum(1 for r in plan if r.get('gen') in ('', 'failed'))
    info('')
    info('生成结果：ok %d ｜ fallback %d ｜ 未完成 %d ｜ 落盘 %s' % (ok, fb, bad, rel(out)))
    info('下一步：& $PY code\\cli.py immersion write --to both          # 演练')
    return 0


# ============================================================================
# 阶段 2b：merge —— 把**子代理/云端模型**的产出并回计划（不调本地模型）
# ============================================================================
RUBY_PAIR = re.compile(r'<ruby>(.*?)<rt>(.*?)</rt></ruby>', re.S)


def ruby_map(html):
    """→ {汉字串: 读音}。只用来和例句的权威注音对一下，不参与结构校验。"""
    out = {}
    for kanji, reading in RUBY_PAIR.findall(html or ''):
        k = IM.strip_tags(kanji).strip()
        if k:
            out.setdefault(k, reading.strip())
    return out


def cmd_merge(a):
    """把云端产出的 ``{entries:[…]}`` 并回 fetch 计划，交给 write。

    与 ``gen`` 的分工：``gen`` 直连本地模型；本命令只做**吸收 + 校验 + 落盘**，
    模型是谁产的不管（子代理、别的 API 都行）。字段口径与 check_mine 完全一致 ——
    校验规则只有一份（``code/common/check_mine.py``），这里不再抄一遍。
    """
    WSP.ensure()
    state = load_state(a.inp)
    plan = state.get('plan') or []
    raw = textio.load_json(a.file, default=None)
    if raw is None:
        raise SystemExit('读不了产出文件：%s' % a.file)
    items = raw.get('entries') if isinstance(raw, dict) else raw
    by_word = {}
    for e in items or []:
        if not isinstance(e, dict):
            continue
        w = P.norm(str(e.get('word') or ''))
        if w:
            by_word[w] = e
    info('=' * 88)
    info('ImmersionKit merge ｜ 计划 %d 条 ｜ 产出 %d 条 ｜ 来源 %s'
         % (len(plan), len(by_word), rel(a.file)))
    info('=' * 88)

    ok = skipped = bad = missing = 0
    problems, near_miss, ruby_bad = [], [], []
    for rec in plan:
        key = P.norm(rec['word'])
        e = by_word.get(key)
        if e is None:
            missing += 1
            near_miss.append(rec['word'])
            continue
        if not CM.as_bool(e.get('include')):
            rec['gen'] = 'skip'
            rec['judge_reason'] = str(e.get('reason') or '').strip()
            skipped += 1
            continue
        entry = {'word': e.get('word'), 'reading': e.get('reading'),
                 'pos': e.get('pos'), 'meaning': e.get('meaning'),
                 'translation': e.get('translation'), 'a_note': e.get('a_note'),
                 'include': True, 'reason': ''}
        hard, soft = CM.check(entry)
        if P.norm(str(entry['word'] or '')) != key:
            hard.append('word 与计划的词不一致：%r' % (entry['word'],))
        if hard:
            bad += 1
            problems.append((rec['word'], hard))
            continue
        rec['reading'] = entry['reading'].strip()
        rec['pos'] = entry['pos'].strip()
        rec['meaning'] = entry['meaning'].strip()
        rec['translation_cn'] = entry['translation'].strip()
        rec['a_note'] = entry['a_note'].strip()
        rec['gen'] = 'ok'
        rec['judge_reason'] = ''
        ok += 1
        # 读音安全网（软提醒）：讲解里引用了例句中的词，就把 ruby 与例句的权威注音对一下
        ref = ruby_map((rec.get('picks') or [{}])[0].get('_html') or '')
        for k, r in ruby_map(rec['a_note']).items():
            if k in ref and ref[k] != r:
                ruby_bad.append((rec['word'], k, r, ref[k]))

    info('  收录 %d ｜ 判弃 %d ｜ 不合格 %d ｜ 产出缺这条 %d'
         % (ok, skipped, bad, missing))
    for w, hard in problems[:12]:
        info('    ✗ %-12s %s' % (w, '；'.join(hard)[:150]))
    if near_miss:
        info('    （缺产出：%s）' % '、'.join(near_miss[:12]))
    if ruby_bad:
        info('  ⚠ 讲解里的 ruby 与例句权威注音不一致 %d 处（建议人工看一眼）：' % len(ruby_bad))
        for w, k, got, want in ruby_bad[:10]:
            info('    %-10s %s 写成 %s ｜ 例句是 %s' % (w, k, got, want))
    extra = [w for w in by_word if w not in {P.norm(r['word']) for r in plan}]
    if extra:
        info('  产出里有 %d 条不在计划中（忽略）：%s' % (len(extra), '、'.join(extra[:8])))

    out = a.out or os.path.join(DATA, 'plan_%s.json' % stamp())
    save_state(state, out)
    info('')
    info('计划落盘：%s（gen=ok %d）' % (rel(out), ok))
    info('下一步：& $PY code\\cli.py immersion write --to mined          # 演练')
    return 0 if not bad else 1


# ============================================================================
# 阶段三：write —— 落地媒体 + 建卡（默认演练）
# ============================================================================
def build_payloads(state, to, no_ainote, start_index):
    """→ [(deck, model, fields, tags, rec, pick, media)]，Index 连续分配。"""
    out, idx = [], start_index
    for rec in state['plan']:
        if rec.get('gen') not in ('ok', 'fallback'):
            continue
        word = rec['word']
        ainote = '' if no_ainote else (rec.get('a_note') or '')
        rank = rec.get('rank')
        jiten_field = ('%06d' % rank) if isinstance(rank, int) else M.JITEN_NO_RANK
        for k, pick in enumerate(rec['picks']):
            html = pick.get('_html') or ''
            # 仓库约定：Sentence HTML 与 AINote 同空同有。三种情况两边一起留空：
            # ``--no-ainote``、模型没给出 AINote、以及振假名这条实在对不上
            # （fetch 已经优先换过句子）—— 只留一边会让 `immersion verify` 判成硬错。
            if no_ainote or not ainote:
                html = ''
            note = ainote if html else ''
            media = [(pick['_stem'] + '.jpg', pick['_image_url']),
                     (pick['_stem'] + '.mp3', pick['_sound_url'])]
            if to in ('example', 'both'):
                tags = [example_tag(pick['_category'], pick['title'])]
                out.append((DECK_EXAMPLE, MODEL_EXAMPLE, {
                    'Sentence': pick['sentence'],
                    'Word': word,
                    'Sentence HTML': html,
                    'AINote': note,
                    'Image': '<img src="%s.jpg" width="700">' % pick['_stem'],
                    'Sentence Audio': '[sound:%s.mp3]' % pick['_stem'],
                    'Source': 'ImmersionKit · %s · %s · %s'
                              % (pick['title'], pick['_category'], pick['id']),
                    'URL': 'https://www.immersionkit.com/dictionary?keyword=' + quote(word),
                }, tags, rec, pick, media))
            if to in ('mined', 'both') and k == 0:
                meaning = rec.get('meaning') or ''
                if pick['_image_url']:          # 现有素材卡就有把配图塞进 Meaning 的先例
                    meaning = '%s<br><br><img src="%s.jpg" width="700">' % (
                        meaning, pick['_stem'])
                out.append((DECK_MINED, MODEL_MINED, {
                    'Index': str(idx),
                    'JitenAnimeRank': jiten_field,
                    'Word': word,
                    'Sentence': pick['sentence'],
                    'Sentence HTML': html,
                    'Transliteration': rec.get('reading') or '',
                    'Meaning': meaning,
                    'Part of Speech': rec.get('pos') or '',
                    'AINote': note,
                    'Sentence Translation': (rec.get('translation_cn')
                                             or pick.get('translation') or ''),
                    'Sentence Audio': '[sound:%s.mp3]' % pick['_stem'],
                    'Word Audio': '',
                    'Pitch Accent URL': '',
                    'Pitch Accent': '',
                }, [P.CFG['mine_tag_prefix']],
                    rec, pick, media))
                idx += 1
    return out


def cmd_prewarm(a):
    """只把计划里的媒体先抓进 collection.media（**不建卡、不调模型**）。

    给「媒体下载 ∥ 本地模型注解」并行用（用户 2026-10-16 要求：下载不要跟生成串着等）。
    fetch 出来的计划里就已经有 `_image_url` / `_sound_url`，媒体不必等 gen 完成。
    写库时 `ensure_media` 命中 `cached`，write 阶段就只剩 addNotes 了。
    """
    WSP.ensure()
    state = load_state(a.inp)
    jobs = {}
    for rec in state.get('plan') or []:
        for pick in rec.get('picks') or []:
            stem = pick.get('_stem') or media_stem(pick.get('id'))
            if pick.get('_image_url'):
                jobs.setdefault(stem + '.jpg', pick['_image_url'])
            if pick.get('_sound_url'):
                jobs.setdefault(stem + '.mp3', pick['_sound_url'])
    info('=' * 88)
    info('ImmersionKit prewarm ｜ 只预下媒体（不建卡、不调模型）｜ %d 个文件' % len(jobs))
    info('=' * 88)
    if not jobs:
        info('这份计划里没有媒体 URL（先跑 fetch）。')
        return 0
    tally = {}
    bad = []
    for i, (filename, url) in enumerate(jobs.items(), 1):
        status = ensure_media(filename, url, keep=a.keep_media)
        tally[status] = tally.get(status, 0) + 1
        if status in ('missing', 'no-url', 'failed'):
            bad.append((filename, status))
        if i % 25 == 0 or i == len(jobs):
            info('   %d/%d ｜ 命中 %d ｜ 新下 %d ｜ 失败 %d'
                 % (i, len(jobs), tally.get('cached', 0), tally.get('ok', 0),
                    len(bad)))
    info('prewarm 完成：%s'
         % ' ｜ '.join('%s %d' % (k, v) for k, v in sorted(tally.items())))
    if bad:
        info('   ⚠ 有问题 %d 个（写库时这些卡会被跳过）：%s'
             % (len(bad), '、'.join(f for f, _s in bad[:6])))
    return 0


def cmd_write(a):
    WSP.ensure()
    state = load_state(a.inp)
    to = a.to
    start = M.next_index(MODEL_MINED)
    items = build_payloads(state, to, a.no_ainote, start)
    info('=' * 88)
    info('ImmersionKit write ｜ 模式：%s ｜ 目标：%s'
         % ('★ 真写库' if a.commit else '演练（不写库）', to))
    info('  模型：例句卡 %s ｜ 素材卡 %s' % (MODEL_EXAMPLE, MODEL_MINED))
    info('  Index 从 %d 起（模型内最大序号 + 1）' % start)
    info('=' * 88)
    if not items:
        info('没有可写的条目（先跑 gen 吧）。')
        return 0

    # 没进映射表（slug_map.yaml）的作品：标签先拿英文 slug 顶着，并记成待办清单，
    # 跑完补上中文名再统一改名（口径同 2026-10-17 那次：整部一个标签）。
    todo_slugs = sorted({(p['_category'], p['title']) for _d, _m, _f, _t, _r, p, _md in items
                         if p['title'] not in slug_map()})
    if todo_slugs:
        todo = os.path.join(DATA, 'unmapped_slugs.txt')
        try:
            old = textio.read_text(todo)
        except Exception:                       # noqa: BLE001  第一次跑还没有这个文件
            old = ''
        have = {ln.split('\t')[-1].strip() for ln in old.splitlines() if ln.strip()}
        fresh = [(c, s) for c, s in todo_slugs if s not in have]
        if fresh:
            textio.write_text(todo, old + ''.join('%s\t%s\n' % c for c in fresh))
        info('  未映射作品 %d 个（标签暂用英文 slug；清单 %s）'
             % (len(todo_slugs), rel(todo)))

    # 身份闸门：`addNotes` 的查重只看**首字段** —— 例句卡是 Sentence（能挡住重复），
    # 素材卡却是每次都不同的 Index（挡不住！）。2026-10-15 实测：复跑同一份计划，
    # 3 张素材卡带着新 Index 又写了一遍。所以同词同句必须自己查。
    seen = deck_identity()
    fresh, dupes = [], []
    for item in items:
        key = (item[0], P.norm(item[4]['word']), P.norm(item[5]['sentence']))
        (dupes if key in seen else fresh).append(item)
    if dupes:
        info('牌组里已有同词同句，跳过 %d 条（重复写只会多出带新 Index 的副本）：'
             % len(dupes))
        for deck, _m, _f, _t, rec, pick, _md in dupes[:8]:
            info('   = %-9s %-12s %s' % (deck.split('::')[-1], rec['word'],
                                         pick['sentence'][:28]))
    items = fresh
    if not items:
        info('没有新条目要写（其余都已存在）。')
        return 0

    media_jobs = {}
    for _deck, _model, _fields, _tags, _rec, _pick, media in items:
        for filename, url in media:
            media_jobs.setdefault(filename, url)
    ruby_empty = sum(1 for it in items if it[2].get('Sentence HTML') == ''
                     and P.KANJI.search(P.strip_html(it[2].get('Sentence', ''))))
    info('将要创建 %d 条笔记；媒体 %d 个；振假名留空（含汉字）%d 条'
         % (len(items), len(media_jobs), ruby_empty))
    for deck, model, fields, _t, rec, pick, _m in items[:12]:
        info('   %-9s %-12s %-14s %s' % (deck.split('::')[-1], model, rec['word'],
                                         pick['sentence'][:30]))
    if len(items) > 12:
        info('   … 其余 %d 条见 plan_write' % (len(items) - 12))

    if not a.commit:
        dump = os.path.join(DATA, 'plan_write_%s.json' % stamp())
        textio.dump_json([{'deck': d, 'model': m, 'fields': f, 'tags': t}
                          for d, m, f, t, _r, _p, _md in items], dump, indent=1)
        info('')
        info('演练结束，未写任何数据。载荷已存：%s' % rel(dump))
        info('确认无误后加 --commit 重跑。')
        return 0

    AK.create_deck(DECK_MINED)
    info('')
    info('预下载媒体（并发 8，下载到 data\\immersion\\media）…')
    prefetch_media(media_jobs.items(), workers=8)
    info('落地媒体…')
    media_have = set(AK.media_names() or [])
    bad_media = []
    for i, (filename, url) in enumerate(media_jobs.items(), 1):
        status = ensure_media(filename, url, keep=True, have=media_have)
        if status in ('missing', 'no-url', 'failed'):
            bad_media.append((filename, status))
        if i % 25 == 0 or i == len(media_jobs):
            info('   %d/%d' % (i, len(media_jobs)))
    if bad_media:
        info('   ⚠ 媒体有问题 %d 个（这些卡不写）：%s'
             % (len(bad_media), '、'.join(f for f, _s in bad_media[:6])))
        for fname, why in bad_media[:6]:
            hit = [r for n, r in MEDIA_FAILURES if n == fname]
            if hit:
                info('        %s ← %s' % (fname, hit[0]))

    skip_stems = {os.path.splitext(f)[0] for f, _s in bad_media}
    notes, keep = [], []
    for deck, model, fields, tags, rec, pick, media in items:
        if pick['_stem'] in skip_stems:
            continue
        notes.append(AK.new_note(deck, model, fields=fields, tags=tags,
                                 allow_duplicate=False, duplicate_scope='collection'))
        keep.append((deck, model, fields, tags, rec, pick))
    info('')
    info('写入中…（一次 addNotes 提交 %d 条）' % len(notes))
    t0 = time.time()
    try:
        res = AK.add_notes(notes)
    except AK.AnkiActionError as exc:
        # 这个 AnkiConnect 版本查重时是**整批报错**（不是逐条给 None）：
        # 复跑同一份计划就会走到这里。逐条重试，把真能进的留下、重复的记成 None。
        info('  整批被拒（%s）→ 逐条重试' % str(exc)[:90])
        res = []
        for one in notes:
            try:
                got = AK.add_notes([one])
                res.append(got[0] if got else None)
            except AK.AnkiActionError:
                res.append(None)
    ok = [(keep[i], int(r)) for i, r in enumerate(res) if r]
    null = [keep[i][4]['word'] for i, r in enumerate(res) if not r]
    info('  addNotes 成功 %d / %d  (%.1fs)' % (len(ok), len(notes), time.time() - t0))
    for w in null[:20]:
        info('    ✗ 被拒（多半是查重）：%s' % w)

    expected = {nid: fields for (_d, _m, fields, _t, _r, _p), nid in ok}
    bad = AK.verify_note_fields(list(expected), expected) if expected else {}
    if bad:
        info('  ⚠ 回读不一致 %d 条：%s' % (len(bad), list(bad.items())[:3]))
    else:
        info('  回读逐字段一致：%d / %d' % (len(expected), len(expected)))

    # 新素材卡的位置（due）＝ JitenAnimeRank 的数字：词频越高越早学到
    # （用户口径 2026-10-15）。只动刚写的这些新卡，学习/复习中的卡一律不碰。
    if not a.no_order and to in ('mined', 'both'):
        nids = [nid for (_d, model, _f, _t, _r, _p), nid in ok if model == MODEL_MINED]
        if nids:
            info('')
            try:
                import reposition as RP
                st = RP.reposition(DECK_MINED, notes=nids, commit=True, top=5)
                info('  素材卡位置已按 JitenAnimeRank 排好：%d 张（失败 %d）'
                     % (st['ok'], len(st['bad']) + len(st.get('bad_read') or [])))
            except Exception as exc:            # noqa: BLE001
                info('  ⚠ 位置重排失败（卡已写入，不影响内容）：%s: %s'
                     % (type(exc).__name__, exc))

    out = os.path.join(DATA, 'written_%s.json' % stamp())
    textio.dump_json({'created': dt.datetime.now().isoformat(timespec='seconds'),
                      'to': to, 'notes': [
                          {'noteId': nid, 'deck': deck, 'model': model,
                           'word': rec['word'], 'fields': fields, 'tags': tags}
                          for (deck, model, fields, tags, rec, _pick), nid in ok]},
                     out, indent=1)
    info('')
    info('写完：%d 条 ｜ 明细 %s' % (len(ok), rel(out)))
    info('下一步：& $PY code\\cli.py immersion verify --written %s' % rel(out))
    return 0 if not bad else 1


# ============================================================================
# 阶段四：verify —— 只读闸门
# ============================================================================
def cmd_verify(a):
    path = a.written
    if not path:
        cands = sorted(f for f in os.listdir(DATA) if f.startswith('written_'))
        if not cands:
            raise SystemExit('❌ %s 下没有 written_*.json，先用 --written 指定。' % rel(DATA))
        path = os.path.join(DATA, cands[-1])
    rec = textio.load_json(path, default=None) or {}
    notes = rec.get('notes') or []
    info('=' * 88)
    info('ImmersionKit verify ｜ %s（%d 条）' % (rel(path), len(notes)))
    info('=' * 88)
    if not notes:
        info('没有可校验的笔记。')
        return 0
    live = AK.notes_map([int(n['noteId']) for n in notes])
    problems, checked = [], 0
    media_names = set(AK.media_names('*') or [])
    for item in notes:
        nid = int(item['noteId'])
        note = live.get(nid)
        if note is None:
            problems.append((nid, item['word'], 'noteId 查不到'))
            continue
        checked += 1
        fields = {k: (v or {}).get('value', '') for k, v in note['fields'].items()}
        if note.get('modelName') != item['model']:
            problems.append((nid, item['word'], '模型不是 %s' % item['model']))
        for name, want in item['fields'].items():
            if fields.get(name, '') != want:
                problems.append((nid, item['word'], '字段 %s 与写入值不一致' % name))
        html = fields.get('Sentence HTML', '')
        ainote = fields.get('AINote', '')
        if bool(html) != bool(ainote):
            problems.append((nid, item['word'], 'AINote 与 Sentence HTML 未同空同有'))
        left = unrubied_kanji(html)
        if left:
            problems.append((nid, item['word'], 'Sentence HTML 有未注音汉字：%s' % left))
        if html and text_of(html) != text_of(fields.get('Sentence', '')):
            problems.append((nid, item['word'], 'Sentence HTML 与原句逐字不一致'))
        for fname in ('Sentence Audio',):
            m = re.search(r'\[sound:([^\]]+)\]', fields.get(fname, ''))
            if m and m.group(1) not in media_names:
                problems.append((nid, item['word'], '媒体库里没有 %s' % m.group(1)))
        m = re.search(r'<img src="([^"]+)"', fields.get('Image', '')
                      + fields.get('Meaning', ''))
        if m and m.group(1) not in media_names:
            problems.append((nid, item['word'], '媒体库里没有 %s' % m.group(1)))
    info('逐条检查 %d 条，问题 %d 个' % (checked, len(problems)))
    for nid, word, why in problems[:40]:
        info('   ✗ %-12s %s（noteId %s）' % (word, why, nid))
    if len(problems) > 40:
        info('   … 其余 %d 个见报告' % (len(problems) - 40))
    if not problems:
        info('全部通过 ✅（AINote/Sentence HTML 配对、振假名无漏标、媒体存在、字段一致）')
    md = ['# ImmersionKit 校验报告',
          '',
          '> 生成时间 %s · 明细 `%s` · 检查 %d 条 · 问题 %d 个'
          % (dt.datetime.now().isoformat(timespec='seconds'), rel(path), checked, len(problems)),
          '']
    if problems:
        md += ['| noteId | 词 | 问题 |', '| --- | --- | --- |']
        md += ['| %s | %s | %s |' % (nid, w, why.replace('|', '\\|'))
               for nid, w, why in problems]
    else:
        md.append('全部通过。')
    out = os.path.join(DATA, 'report_verify_%s.md' % stamp())
    textio.write_text(out, '\n'.join(md) + '\n')
    info('报告：%s' % rel(out))
    return 1 if problems else 0


# ============================================================================
# 报告
# ============================================================================
def write_report(state, kind):
    plan, skipped = state.get('plan') or [], state.get('skipped') or []
    lines = ['# ImmersionKit %s 报告' % kind, '',
             '> 生成时间 %s · 词表 `%s`'
             % (state.get('created', ''),
                rel(state['words_file']) if state.get('words_file') else '—'),
             '> 入选 %d 个词 / %d 条例句 · 剔除 %d 个词'
             % (len(plan), sum(len(r['picks']) for r in plan), len(skipped)), '']
    if plan:
        lines += ['## 入选', '',
                  '| 词 | JitenAnimeRank | 出处 | 类别 | 句长 | 振假名 | 例句 |',
                  '| --- | --- | --- | --- | --- | --- | --- |']
        for r in plan:
            for pick in r['picks']:
                lines.append('| %s | %s | %s | %s | %d | %s | %s |'
                             % (r['word'], r.get('rank') or '—', pick['title'],
                                pick['_category'], IM.text_len(pick['sentence']),
                                'ok' if pick.get('_ruby_ok') else (pick.get('_ruby_note') or ''),
                                pick['sentence'].replace('|', '\\|')))
    if skipped:
        lines += ['', '## 剔除', '', '| 词 | 原因 |', '| --- | --- |']
        lines += ['| %s | %s |' % (w, why.replace('|', '\\|')) for w, why in skipped]
    out = os.path.join(DATA, 'report_%s_%s.md' % (kind, stamp()))
    textio.write_text(out, '\n'.join(lines) + '\n')
    return out


# ============================================================================
# CLI
# ============================================================================
def build_parser():
    ap = argparse.ArgumentParser(
        prog='immersionkit.py',
        description='ImmersionKit → 例句卡（Basic/2-例句）+ 素材生词卡（Japanese Vocabulary）')
    sub = ap.add_subparsers(dest='cmd')

    def common(p, need_words=False):
        if need_words:
            p.add_argument('--words-file', default=os.path.join(DATA, 'words.txt'),
                           help='词表：一行一个词（默认 data/immersion/words.txt）')
        p.add_argument('--in', dest='inp', default=LATEST,
                       help='读哪份计划（默认 data/immersion/latest.json）')

    f = sub.add_parser('fetch', help='选词 + 选句，出计划（不写库）')
    common(f, need_words=True)
    f.add_argument('--n', type=int, default=1, help='每个词最多几条例句（1–3，默认 1）')
    f.add_argument('--category', default='anime,drama',
                   help='类别白名单（anime,drama,games；空=不限）')
    f.add_argument('--deck', default='', help='只取这些 deck slug（逗号分隔，空=不限）')
    f.add_argument('--min-len', type=int, default=3, help='句长下限（默认 3）')
    f.add_argument('--max-len', type=int, default=40, help='句长上限（默认 40）')
    f.add_argument('--speaker-max', type=float, default=0.6,
                   help='括号内（说话人标记）占比上限（默认 0.6）')
    f.add_argument('--delay', type=float, default=0.5, help='每次真上网间隔秒数')
    f.add_argument('--workers', type=int, default=4,
                   help='并发抓取线程数（默认 4；1 = 串行。缓存命中的词不受影响）')
    f.add_argument('--refresh', action='store_true', help='忽略缓存重新抓')
    f.add_argument('--limit', type=int, default=0, help='只处理前 N 个词（试跑用）')
    f.add_argument('--out', default='',
                   help='计划落盘路径（默认 data/immersion/fetch_<时间戳>.json；分块流水线用）')
    f.add_argument('--keep-known', action='store_true',
                   help='反过来：只抓 core6000/考级**已有**的词（补例句卡、不建素材卡）')
    f.set_defaults(func=cmd_fetch)

    g = sub.add_parser('gen', help='本地模型出 读音/词性/释义/翻译/讲解')
    common(g)
    g.add_argument('--batch', type=int, default=6, help='每批几个词（默认 6）')
    g.add_argument('--no-ainote', action='store_true',
                   help='不调模型：只用 JMdict 释义，AINote 与 Sentence HTML 一起留空')
    g.add_argument('--quiet', action='store_true', help='不打印模型流式输出')
    g.add_argument('--limit', type=int, default=0, help='只处理前 N 条（试跑用）')
    g.set_defaults(func=cmd_gen)

    m = sub.add_parser('merge', help='把子代理/云端模型的产出并回计划（不调本地模型）')
    common(m)
    m.add_argument('--file', required=True,
                   help='模型产出 JSON（{entries:[…]} 或纯数组），字段见 check_mine.py')
    m.add_argument('--out', default='',
                   help='计划落盘路径（默认 data/immersion/plan_<时间戳>.json；分块流水线用）')
    m.set_defaults(func=cmd_merge)

    w = sub.add_parser('write', help='落地媒体 + 建卡（默认演练，--commit 真写）')
    common(w)
    w.add_argument('--to', choices=('example', 'mined', 'both'), default='both',
                   help='写到哪个牌组（默认 both）')
    w.add_argument('--commit', action='store_true', help='真写库')
    w.add_argument('--keep-media', action='store_true',
                   help='媒体先下载到 data/immersion/media 再上传（便于复查）')
    w.add_argument('--no-ainote', action='store_true',
                   help='强制 AINote 与 Sentence HTML 留空（只写句子/音频/图）')
    w.add_argument('--no-order', action='store_true',
                   help='不把新素材卡的位置（due）按 JitenAnimeRank 重排')
    w.set_defaults(func=cmd_write)

    pw = sub.add_parser('prewarm', help='只预下媒体（不建卡、不调模型）：与 gen 并行用')
    common(pw)
    pw.add_argument('--keep-media', action='store_true',
                    help='先下载到 data/immersion/media 再上传')
    pw.set_defaults(func=cmd_prewarm)

    v = sub.add_parser('verify', help='只读校验：字段/振假名/媒体')
    v.add_argument('--written', default='', help='written_*.json（默认取最新一份）')
    v.set_defaults(func=cmd_verify)
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if not getattr(a, 'func', None):
        ap.print_help()
        return 0
    with AK.guard():
        return a.func(a)


if __name__ == '__main__':
    sys.exit(main())
