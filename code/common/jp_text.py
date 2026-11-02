# -*- coding: utf-8 -*-
"""日语文本清洗与字符判定的**唯一家**（issue #5）。

`code/execution/` 的脚本过去互为依赖：6 个脚本从 `pipeline.py` 借纯文本 / 假名 /
CFG 类工具，改一个工具函数波及 6 个无关脚本。这批函数不碰 Anki、不读路径、不跑模型，
本来就该住在 `common/` —— 先例见 `jp_decks.py`（牌组名）。

**这里只放纯函数与字符判定**。判据是「无副作用、不读模块级状态」：
`fit_groups` 要 `(cfg, LLM)` 并调 `LLM.budget/estimate_tokens`，`rebuild_known_index`
读 `CFG['known_vocab_scopes']` 且直连 Anki，`jiten_rank` 在 `index=None` 时每次重读词表 ——
它们都不是文本层的东西，留在各自脚本里。

## 两套汉字口径，别混（issue #5 特别点名的坑）

* :data:`KANJI`（**含 CJK 扩展 A** `\u3400-\u4dbf`）—— 来自 `pipeline.py:130`，
  triage / mine / proper / activate 用它判「这个词/句子里有汉字吗」。
* :data:`ruby_text.KANJI`（**不含**扩展 A）—— 振假名解析的基底判定，口径更窄。

两者**不是重复实现**，合并会改变行为；所以本模块叫 `KANJI` 的那份保留 pipeline 口径，
窄口径仍以 `common/ruby_text.py` 为正本（那里还带 `々〆ヶ` 的辅助字符判断）。

## 功能词表为什么也在这里

`trim_functional` 原先住在 `mine.py`，`proper.py` 跨脚本借它 —— 而它只做一件事：
把助词/助动词从残差两端剥掉。功能词表（`FUNCTIONAL` / `FUNCTIONAL_SUFFIX`）随它一起搬，
`mine.py` 与 `proper.py` 现在都从这里 import，口径仍然只有一份。

词汇来源常量（`VOCAB_DECKS` 等）也在这里 —— 它们原先只写在 `pipeline.CFG`，
于是 activate / mine / immersionkit **为了一个牌组名或一个标签名要 import 整个流水线**
（issue #5 里 `CFG` 出现在 4 条借边上）。它们是「哪几套卡组算已有词汇」的口径，
不读配置、不连 Anki，属于可共享的声明；改收藏结构时只改这一处。

跑法（自检）：``& $PY code\\common\\jp_text.py``
"""
import html as _h
import re
import sys
import unicodedata

import jp_decks as JD
import textio  # noqa: E402  UTF-8 stdio 唯一入口（common）

# ── 字符判定（正则）───────────────────────────────────────────────────────
#: 含 CJK 扩展 A 的汉字集（pipeline 口径）。窄口径见 `ruby_text.KANJI`。
KANJI = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
#: 假名集（平 + 片，含浊音区）。`ruby_text.py` 里那份与此完全相同。
KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
#: 整个串都是片假名（外来语/专名的形状）
KATA_ONLY = re.compile(r'^[\u30a1-\u30f6\u30fc]+$')
#: 整个串都是平假名（`ー` 允许：长音符也出现在纯假名词尾）
KANA_ONLY = re.compile(r'^[\u3040-\u309f\u30fc]+$')
#: 片假名连续段（≥3），外来语堆叠的提示
KATA_RUN = re.compile(r'[\u30a1-\u30f6\u30fc]{3,}')
#: 标点/空白：`norm` 要删的东西，口径写在这里一次
PUNCT = re.compile(r'[、。！？!?「」『』（）()\[\]{}…‥・,.:：;；~〜\-－—–\s　]+')

# ── 惯用句表（判据①的补充：这些不是单词，但值得算「已学过」）──────────────
# 从 pipeline.py 上提：mine.py 建候选时要拿它压掉「気を使う」这类成组表达，
# 原先只能 `import pipeline as P` 去借（issue #5）。纯数据，无副作用。
IDIOMS = [
    '気を使', '気を遣', '気が付', '気にする', '気になる', '気に入', '気が済', '気を抜',
    '気が抜', '気が遠く', '手を貸', '手が出', '手に入', '手を出', '手を焼', '目を通',
    '目が届', '目を離', '目に留', '口を出', '口が堅', '顔を出', '顔が広', '足を運',
    '足が出', '胸を張', '胸が痛', '骨が折', '骨を折', '力を貸', '力になる', '役に立',
    '世話になる', '水を差', '水に流', '火が付', '拍車をかけ', '目処が立', '筋が通',
    '話が違', '音を立て', '息を切', '息を吐', '肩を落', '肩の荷', '腰を据', '首をかしげ',
    '首を振', '眉をひそ', '腹を立', '腹が減', '涙を流', '声を上げ', '声をかけ', '声を潜',
    '腕を振る', '腕によりをかけ', '頭ごなし', 'にも程がある', '途方に暮', '折り合いをつけ',
    '気をつけ', 'お世話にな', '当たり前', '思いがけな', '思い切って', '言うまでもな',
    '立場にな', '身につけ', '目を向け', '耳を傾け', '道に迷', '邪魔をす', '迷惑をかけ',
    '面倒を見', '相談に乗', '相手にす', '覚悟を決', '決心をつけ', '心を込め', '心がけ',
]

# ── 活用展开（「这个词是不是已经存在」的反向判定用）────────────────────────
# 从 pipeline.py 上提：mine.py 定位例句、proper.py 判已知词都要用它，原先同样只能借 pipeline。
_CONJ_TAILS = ['', 'る', 'た', 'て', 'ます', 'ました', 'ません', 'なかった', 'ない', 'ぬ', 'ず',
               'れる', 'られる', 'せる', 'させる', 'たい', 'そう', 'よう', 'ば', 'たら', 'たり',
               'ながら', 'なさい', 'ろ', 'ずに', 'なくて', 'ちゃう', 'ちゃった', 'てる', 'てた',
               'ている', 'ていた', 'ておく', 'てしまう', 'すぎる', 'やすい', 'にくい', 'たい',
               'い', 'く', 'かった', 'ければ', 'さ', 'み', 'げ', 'め', 'わ', 'おう', 'よう']
# 五十音 5 段（用于生成「未然/連用/仮定」形），行 = 段
_GODAN = {
    'う': 'わいうえお', 'く': 'かきくけこ', 'ぐ': 'がぎぐげご', 'す': 'さしすせそ',
    'つ': 'たちつてと', 'ぬ': 'なにぬねの', 'ぶ': 'ばびぶべぼ', 'む': 'まみむめも',
    'る': 'らりるれろ',
}

# ── 功能词表（切词边界用）──────────────────────────────────────────────────
# 必须一起参与「最长匹配覆盖」，否则 `が`/`を`/`の` 这种单字助词不被覆盖，
# 残差会变成 `が広がってます` 这样的整段，而不是干净的词。
# 这份表**只用于切词边界**，不参与「是否已存在于已有牌组」的判定。
FUNCTIONAL = """
は が を に で と も の や か ね よ な さ し て ば げ へ ぞ ぜ わ い ん っ り る た だ を
から まで より なら しか こそ さえ すら ほど くらい ぐらい まま ところ だけ ばかり のに ので けど けれど
では には とは って でも ても とも からは からも までは にまで
です ます でした ました ません ましょう でしょう でしょうね ですね ますね ますよ
だ た て で ない なく なかっ なけれ ず ぬ ずに なくて なかった
ある あり いる い いた おる おります なる なり なっ する し した して します しよう すれ される された
いう いっ いわ いえ いうこと という といった として にとって について によって において に関して に対して
れる られる れた られた せる させる せた させた たい たく たかっ たけれ
そう よう らしい みたい っぽい かもしれ かも かしら かな だろう でしょう
ている ています ていた てます てる てた ておく ておい ておき てしまう てしまっ ちゃう ちゃっ じゃう
てくれ てくだ てくださ てもら ていただ てあげ てみる てみ てくる てき てきた ていく ていっ
ながら たり だり つつ れば たら なら と ったら だったら んだったら
こと もの わけ はず つもり ほう ため よう そう らしい べき かどうか
お ご すぎ 過ぎ きる 切る だす 出す こむ 込む あう 合う なおす 直す かける 続ける 始める 終わる 終える 終わる
""".split()

#: 功能词的活用尾（动词/形容词词干后常见）
FUNCTIONAL_SUFFIX = """
ます ました ません ませんでした ている ています ていた てます てる てた ておく てしまう
ちゃう ちゃった じゃう てくれ てください てもらう ていただく てあげる てみる てくる ていく
たい たかった たくない たければ そう よう らしい みたい ので のに けど けれど から まで
ば たら なら ても でも ながら たり だり ずに なくて ない なかった ぬ れる られる せる させる
""".split()

#: 单字助词兜底（`の`/`が` 之类可能被夹在中间）
_PARTICLE_TAIL = 'はがをにでとものやかねよなへ'


# ── 词汇来源（判据①「单词」的来源）───────────────────────────────────────
# 原先写在 pipeline.CFG，activate / mine / immersionkit 为了一个 deck 名或标签名
# 就要 import 整个流水线（issue #5）。这些是纯声明：哪些卡组算「已有词汇」、
# 词形写在哪个字段、素材生词牌组与标签叫什么。改收藏结构只改这一处。
#: 考级词汇：四元组 (级别, deck, 词形字段, 级别标签)；标签为 None 表示整个 deck 一个级别。
#: ⚠ 考级词汇**已扁平化**（见 jp_decks），级别与频段由 eggrolls 笔记标签区分。
VOCAB_DECKS = [
    (lv, JD.DECK_KAOKYU, JD.KAOKYU_FIELD, JD.level_tag(lv, band))
    for lv, band in JD.KAOKYU_UNITS
]
#: 按词频分段（而非 JLPT 级别）标注的词汇 deck：(名称, deck, 字段, 频段→级别)
VOCAB_BAND_DECKS = [
    ('jp-core', JD.DECK_CORE6000, 'Word',
     {1: 'N5', 2: 'N5', 3: 'N4', 4: 'N4', 5: 'N3', 6: 'N3'}),
]
#: 另有标签形式收录的词汇（拟声拟态词、片假名外来语）：(名称, 完整标签)
VOCAB_TAGS = [
    ('オノマトペ', JD.KAOKYU_MODEL + '::オノマトペ'),
    ('カタカナ語', JD.KAOKYU_MODEL + '::カタカナ語'),
]
#: 「已知词汇」的参照系：已有全部词汇 deck 的**父级前缀**（deck:"X" 连带所有子 deck）。
#: 顺序 = 收词优先级：先娘家的（考级词汇→core6000）级别更可靠。
KNOWN_VOCAB_SCOPES = [
    {'deck': JD.DECK_KAOKYU, 'field': JD.KAOKYU_FIELD, 'lv': '考级'},
    {'deck': JD.DECK_CORE6000, 'field': 'Word', 'lv': 'Core6000'},
]
#: 素材生词牌组与笔记模板（mine.py / immersionkit.py / mine_audio.py 共用）
MINE_DECK = JD.DECK_MINED
MINE_MODEL = 'Japanese Vocabulary'      # 与 core6000 同模板，复用其字段
#: 素材生词的根标签名；每集/每个来源挂在它下面一层（`素材生词::<来源>`）。
#: 正本在 jp_decks（库结构常量那一层）；这里只转发，避免出现第二个字面量。
MINE_TAG_PREFIX = JD.mined_tag_prefix()

#: 例句牌组（整条流水线的主战场）。原先只写在 pipeline.CFG['deck']，activate / mine
#: 为了拼一条查询就要 import 整个流水线；牌组名属于收藏结构，和上面几组放一起。
EXAMPLE_DECK = '0-日本语学习::2-例句'


# ============================================================================
# 纯文本清洗
# ============================================================================
def strip_html(s):
    """去 HTML 标签（``<br>`` 换空格），并 unescape 实体；非字符串一律转文本。"""
    if not isinstance(s, str):
        # 模型/外部数据偶尔给数字、布尔甚至 None（2026-10-12 实测：
        # 本地模型把字符串字段返回成 int，`unescape(5)` 直接崩）—— 一律转成文本。
        s = '' if s is None else str(s)
    s = _h.unescape(s or '')
    return re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', ' ', s, flags=re.I))


def norm(s):
    """比较/查重用的归一化文本：剥标签 + 去标点空白。**不用于展示**。"""
    return PUNCT.sub('', strip_html(s))


def dupkey(s):
    """查重键：只取 Sentence 本身，与 AINote 无关。

    口径：NFKC 统一全角/半角 → 整块删 `<rt>…</rt>`（万一 Sentence 里混进了振假名 HTML）
    → 剥其余标签 → 去掉全部空白（含全角空格 U+3000）。
    **标点保留**：`ありがとう` 与 `ありがとう！` 是两种语气，不算重复（只做全角/半角统一）。
    """
    s = unicodedata.normalize('NFKC', s or '')
    s = re.sub(r'<rt>.*?</rt>', '', s, flags=re.I | re.S)
    return re.sub(r'\s+', '', strip_html(s), flags=re.UNICODE)


def hira2kata(s):
    """平假名 → 片假名（只动 \u3041-\u3096，其余原样）。"""
    return ''.join(chr(ord(c) + 0x60) if '\u3041' <= c <= '\u3096' else c for c in s)


def kata2hira(s):
    """片假名 → 平假名（只动 \u30a1-\u30f6，其余原样）。"""
    return ''.join(chr(ord(c) - 0x60) if '\u30a1' <= c <= '\u30f6' else c for c in s)


def vocab_guard(w):
    """长度守卫：纯假名词必须 >=3 字，否则子串匹配会大量误命中
    （2 字的「だめ」「やあ」会在「いやあった」里命中「やあ」）"""
    if KANJI.search(w):
        return len(w) >= 2
    if KATA_ONLY.match(w):
        return len(w) >= 2
    if KANA_ONLY.match(w):
        return len(w) >= 3
    return len(w) >= 2


def as_int(value, default=0):
    """把端点/模型/Anki 给的「数字」压成 int；转不了就用 default。

    Anki 字段与 usage 里都出现过字符串数字、None、缺字段（2026-10 实测），
    调用方不该各写一遍 try/except。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def functional_words():
    """功能词表（含活用尾）。"""
    s = set(FUNCTIONAL) | set(FUNCTIONAL_SUFFIX)
    return {w for w in s if w}


def trim_functional(s):
    """把功能词从残差两端剥掉（`が広がっ` → `広がっ`）。剥不动就原样返回。"""
    func = functional_words()
    words = sorted(func, key=len, reverse=True)
    changed = True
    while changed and s:
        changed = False
        for w in words:
            if len(w) < len(s) and s.startswith(w):
                s = s[len(w):]
                changed = True
                break
            if len(w) < len(s) and s.endswith(w):
                s = s[:-len(w)]
                changed = True
                break
    # 单字助词兜底（`の`/`が` 之类可能被夹在中间）
    while len(s) > 1 and s[0] in _PARTICLE_TAIL:
        s = s[1:]
    return s


def conjugation_variants(w):
    """把词典形展开成常见活用形，用于「这个词是不是已经存在」的判定。

    挖掘（mine.py）是**反向**用途：已知词的变体越多，越不会把
    「漕い」当成 Plan B 的新词收进来（漕ぐ 已在 core6000 里）。
    triage 的参照系判定不用这个函数，以免动到它已固化的回归基线。

    纯字符串运算：不读配置、不查库，所以能从 pipeline 搬到这里。
    """
    out = {w}
    if len(w) < 2 or KANJI.search(w[-1]):
        return out
    if w.endswith('する') and len(w) > 2:
        # サ変動詞（介抱する・愚弄する・確認する）单独处理并直接返回：
        # 词干是「介抱」而不是「介抱す」，下面那套「尾假名＝词尾」的规则会算出
        # 「介抱すます／介抱すた」这类废变体，而真正要用的「介抱し／介抱した／
        # 介抱して」一个都生成不出来 —— mine.py 定位例句时就会判 notfound
        # （2026-10-12 第 01 集「介抱する」实测：例句是「介抱していただいた」）。
        b = w[:-2]
        out.update({b, b + 'し', b + 'した', b + 'して', b + 'しない', b + 'しなかった',
                    b + 'します', b + 'しました', b + 'しよう', b + 'すれば', b + 'しろ',
                    b + 'される', b + 'させる', b + 'せず', b + 'したい', b + 'しながら',
                    b + 'している', b + 'していた', b + 'しておく', b + 'してしまう'})
        return {v for v in out if len(v) >= 2}
    stem = w[:-1]
    if w[-1] == 'る':                      # 一段 / 五段る
        out.add(stem + 'ます')
        out.add(stem + 'た')
        out.add(stem + 'て')
        out.add(stem + 'ない')
        out.add(stem + 'なかった')
        out.add(stem + 'よう')
        out.add(stem + 'ろ')
        out.add(stem + 'ず')
    row = _GODAN.get(w[-1])
    if row:                                # 五段
        a, i, u, e, o = row
        out.add(stem + a + 'ない')
        out.add(stem + i + 'ます')
        out.add(stem + i + 'たい')
        out.add(stem + i + 'た')
        out.add(stem + i + 'て')
        out.add(stem + i + 'そう')
        out.add(stem + e + 'ば')
        out.add(stem + e + 'る')
        out.add(stem + o + 'う')
    if w[-1] == 'い':                      # イ形容词
        out.add(stem + 'く')
        out.add(stem + 'かった')
        out.add(stem + 'さ')
        out.add(stem + 'ければ')
    for t in _CONJ_TAILS:                  # 通用尾缀
        if t:
            out.add(stem + t)
    return {v for v in out if len(v) >= 2}


# ============================================================================
# 自检：python code\common\jp_text.py
# ============================================================================
def _selfcheck():
    """口径锁：两套汉字口径必须不同；纯函数不许读模块状态。"""
    import ruby_text as RT
    bad = []

    def ck(name, cond, detail=''):
        print('%s %s%s' % ('  [OK]  ' if cond else '  [FAIL]', name,
                           '' if cond else '  ← %s' % detail))
        if not cond:
            bad.append(name)

    # 两套汉字口径（issue #5：同名不同义，不许合并）
    ck('KANJI 认扩展 A 字', KANJI.search('\u3400') is not None, 'jp_text.KANJI')
    ck('ruby_text.KANJI 不认扩展 A 字', RT.KANJI.search('\u3400') is None, '口径必须更窄')
    # 纯函数行为
    ck('strip_html 去标签 + <br> 换空格', strip_html('a<br/>b<c>') == 'a b', repr(strip_html('a<br/>b<c>')))
    ck('strip_html 非字符串不崩', strip_html(5) == '5' and strip_html(None) == '', '')
    ck('norm 去标点', norm('ありがとう！') == 'ありがとう', repr(norm('ありがとう！')))
    # NFKC 会把全角标点折成半角（`ありがとう！` → `ありがとう!`），这是 dupkey 的既有口径，
    # 断言按实际行为写，不要改成「保留原样」。
    ck('dupkey NFKC 折全角标点', dupkey('ありがとう！') == 'ありがとう!', repr(dupkey('ありがとう！')))
    ck('dupkey 删振假名块 + 去空白',
       dupkey('愛<ruby>愛<rt>あい</rt></ruby>') == '愛愛', repr(dupkey('愛<ruby>愛<rt>あい</rt></ruby>')))
    ck('hira2kata / kata2hira 互逆', kata2hira(hira2kata('でも')) == 'でも', '')
    ck('vocab_guard 纯假名要 3 字', not vocab_guard('やあ') and vocab_guard('やります'), '')
    # 逐字符口径锁：功能词表搬过来后一个词都不许多不许少，所以钉死具体输出
    ck('trim_functional 剥助词/活用尾', trim_functional('が広がってます') == '広',
       repr(trim_functional('が広がってます')))
    ck('trim_functional 单字残差不再剥（防过度裁剪）', trim_functional('が') == 'が',
       repr(trim_functional('が')))
    ck('trim_functional 空串', trim_functional('') == '', repr(trim_functional('')))
    # 词汇来源常量：必须与 jp_decks 的牌组名同源（issue #5：原先藏在 pipeline.CFG）
    ck('MINE_DECK 就是素材生词牌组', MINE_DECK == JD.DECK_MINED, repr(MINE_DECK))
    ck('VOCAB_DECKS 覆盖全部考级单元', len(VOCAB_DECKS) == len(JD.KAOKYU_UNITS),
       '%d vs %d' % (len(VOCAB_DECKS), len(JD.KAOKYU_UNITS)))
    ck('已知词汇参照系 = 考级 + core6000',
       [s['deck'] for s in KNOWN_VOCAB_SCOPES] == [JD.DECK_KAOKYU, JD.DECK_CORE6000], '')
    return bad


def main():
    bad = _selfcheck()
    if bad:
        print('结论：%d 项失败' % len(bad), file=sys.stderr)
        return 1
    print('结论：jp_text 口径自检通过（两套汉字口径仍在，纯函数无状态）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
