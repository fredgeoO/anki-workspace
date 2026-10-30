# Core6000 例句补全（例句② + 振假名 + 合并讲解 + 配音）设计契约

> 状态：active ｜ 最后核实：2026-10-30

本文件是 `code/execution/core6000_example.py` 与 `code/execution/core6000_example_prompt.md`
的**唯一接口契约**。实现者按本文件写代码，改接口先改本文件。

---

## 一、目标

> **用途定位：按需，不是全量补全。**
> 用户只对**自己记不住的**卡额外加一句例句来帮助记忆，并且**由用户逐次点名**要哪几个词。
> 所以这个能力的主入口是「给我点名的这些词/noteId 补第二条例句」，
> **不是**把 6000 张卡一次性刷成两句。`scan` 只是可选体检；
> 没有任何目标选择器时**默认拒绝全量跑**（要全量必须显式 `--all`）。

给 `0-日本语学习::0-词汇::1-高频日语单词 6000`（模型 `Japanese Vocabulary`，6000 张）
里**被点名的**卡补齐到「**两条例句**」的状态：

| 字段 | 目标状态 |
|---|---|
| `Sentence` | 两条例句，`原句<br><br>新句` |
| `Sentence HTML` | 两条例句的振假名 HTML，**每句每个汉字都要有 ruby** |
| `Sentence Translation` | 两条例句的中文，`原译<br><br>新译` |
| `AINote` | **保持该卡原有排版**，每个板块里变成 `① 原句相关内容` + `② 新句相关内容` |
| `Sentence Audio` | 原有音频 + 新句 TTS 音频（`[sound:core6000-<noteId>-sentence-2.mp3]`），共 2 条 |
| `Word` / `Transliteration` / `Meaning` / `Part of Speech` / `Index` / 音调字段 | **一个字都不动** |

**核心原则**：原句的信息一个字都不丢（技能规则 1/2）。原句相关的 ① 讲解
**直接沿用卡里已有的 AINote 文本**，不交给模型改写。

**新例句必须来自真实语料，不是模型造句**（2026-10-26 起）：`gen` 先用
`code/tools/jisho_example.py` 抓 jisho.org 的 Sentence 搜索结果（Tatoeba / Jreibun），
按「振假名结构合格 / 含目标词 / 长度 6–45 字 / 与第一句相似度 < 0.72」挑一条，
把 `jp` + `ruby` **钉死**写进 payload 的 `sentence_source`；模型只负责
`cn2` / `new_word_gloss` / `grammar2` / `conjugation2` / `context2` / `contrast`。
模型若改写了那句，脚本按 Jisho 原句写回并记 `sentence_overridden` 警告；
Jisho 零候选时**这张卡失败**（不退回造句；`--allow-model-sentence` 是显式降级开关）。

---

## 二、现状实测（2026-10-06，6000 张）

```
Sentence（例句块数）   1 块 3942 / 2 块 2057 / 3 块 1
Sentence Audio         1 条 3942 / 2 条 2057 / 3 条 1
Sentence HTML 外层包裹 <div> 889 / <p> 2640 / 裸 ruby 2471 / 空 0（没有空字段）
AINote                 6000 张全部非空；其中只有 2 张含 ①
```

即：**真正做过「①②合并」的只有这 2 张**，其余 5998 张的 `AINote` 都还是单句讲解的版式。
**上面的数字只是 2026-10-06 这一天的快照。** `scan` 每次都会重新读 Anki 现场重新统计
（句块数、版式族、缺什么、是否已合规），**不要把这些数字当常量**。

---

## 三、CLI 设计（与工作区既有脚本同风格）

```
$PY code/execution/core6000_example.py scan   [TARGET…] [--only SCOPE]
$PY code/execution/core6000_example.py gen    TARGET… [--restart] [--per-batch 1]
                                              [--refresh-jisho] [--allow-model-sentence]
$PY code/execution/core6000_example.py tts    TARGET… [--force]
$PY code/execution/core6000_example.py apply  TARGET… [--commit]
$PY code/execution/core6000_example.py revert --commit [--backup FILE]
$PY code/execution/core6000_example.py status
```

### 3.1 TARGET：点名要补哪几张卡（**主用法**）

优先级从高到低，给出第一个命中的就用它：

| 选择器 | 含义 |
|---|---|
| `--note-ids 1621392074520,1621392074521` | 直接点名 noteId |
| `--words "徹夜,あまり"` | 按 `Word` 字段匹配（退回 `Transliteration`），容忍空格/大小写 |
| `--from-file PATH` | 一行一个词或 noteId；`#` 注释与空行忽略 |
| `--from-weak --days N [--rating again\|hard\|both]` | **「只针对我记不住的」入口**：用同一个解释器跑 `code/analysis/today_weak.py --plain --days N`，取它 stdout 的单词名当 `--words` |
| `--query "<Anki 搜索式>"` | 任意 Anki 查询 |
| `--only SCOPE` | 按状态筛（见下）；范围限于 deck + 模型过滤 |
| `--all` | **显式**全量（6000 张）。不给任何一个选择器时**不默认全量**，而是打印选择器用法后退出 |

**幂等**：对已经有「② + 音频」的合规卡，重跑必须报 `already_ok` 并跳过，
**绝不重复追加第二句或第二个 `[sound:]`**；`--force` 才重做。

* `--only SCOPE`，可重复或逗号分隔，**实现默认是 `missing-sentence`、`missing-ruby`**（不是 `all`）：
  * `missing-sentence` —— `Sentence` 只有 1 块（从 **Jisho** 取真实新句，不是造句）
  * `missing-ruby` —— `Sentence HTML` 有汉字但没振假名 / 为空
  * `not-merged` —— 已有 2 句，但 AINote 里没有 ①② 合并（需要模型重写 ①，见 §5.3；**默认不参与**）
  * `all` = 上面三项的并集
* **为什么默认不是 `all`**：`not-merged` 默认关闭（提示词还不支持 ①，见 §5.3），
  而**已经有两句话的卡必须是 no-op** —— 不能因为「AINote 里没有 ①②」就再补一遍句子。
  所以默认只做「真的缺句 / 缺振假名」这两类；要三项并集请显式 `--only all`。
* 全局可覆盖项（都带默认值，默认值就是工作区的正确值）：
  `--system-prompt PATH`、`--base-url URL`、`--model NAME`、`--api-key KEY`
  （api key 的查找顺序照抄 `today_new.py::load_llm_config` 与 `~/.dsh/local-llm.json`）
* `gen` 默认 `--per-batch 1`（一次一张卡，和 `today_new.py` 一致：断点续跑粒度最小）
* `apply` 默认演练，只打印**将要写入的字段**（§5.4：通常 1 句的卡是 5 个、已有 2 句的卡只有
  `Sentence HTML`）的前后对照，并列出不写的字段；`--commit` 才 `updateNoteFields`
* `revert` 从 `data/core6000/backup_<批次>.json` 还原那批被改过的字段（只还原被备份的字段）

### 3.2 典型会话（用户点名的场景）

```powershell
# 用户：「这几个词我老记不住，给我各加一句例句」—— 直接点名
& $PY "$EXE\core6000_example.py" gen   --words "徹夜,適当,残り"
& $PY "$EXE\core6000_example.py" tts   --words "徹夜,適当,残り"
& $PY "$EXE\core6000_example.py" apply --words "徹夜,適当,残り"            # 演练：先看
& $PY "$EXE\core6000_example.py" apply --words "徹夜,適当,残り" --commit   # 真写（2026-10-06 起不再要求听音频确认）

# 用户：「今天答得不好的那些词，挑记不住的补一句」
& $PY "$EXE\core6000_example.py" gen --from-weak --days 3 --rating again
```

### 3.3 实现与本文档的偏差（实测，以本节为准）

1. **`--per-batch` 只接受 1。** 传 `--per-batch N`（N>1）会被**直接拒绝**并打印一段说明：
   本契约 §4.2 的响应按**单张卡**组织（`entries` 只有一个键），提示词也明说「你一次只处理一张卡」，
   一次塞多张只会漏卡 / 串卡。默认值就是 1；要省时间请用选择器缩小范围
   （`--words` / `--note-ids` / `--from-weak`）。
2. **闸门 1/2 只针对「模型新造的句子」。** 原卡**已经有两条**例句时，输入里带
   `sentence2_is_existing`，模型必须把卡上第二句**逐字原样**交回来（只用来对齐振假名与 ② 讲解），
   闸门 1/2 对这张卡**跳过** —— 拿「必须含目标词」去卡一句本来就存在的句子属于误伤
   （例如 `する` 的第二句本来就不含「する」）。「原样交回」是**硬闸门**：交回的不是那一句就拦下
   （第二句缺振假名时）／记一条 `sentence2_mismatch` 警告（第二句已有合规振假名时）。
   第二句本身缺/坏振假名时，输入里带 `need_sentence2_ruby`，模型用 **`sentence2_ruby`**
   交回「同一句 + 振假名」，由**闸门 5b** 验（去 ruby 后与卡上第二句逐字一致 + 闸门 3/4 的 ruby 规则）；
   不合格**拒绝这张卡**，绝不把模型改写过的句子写进库。`apply` 写库前会再复核一遍 5b。
3. **3 句以上的卡跳过**（全库 1 张）：闸门 6 要求恰好 2 块，而脚本没有安全的自动处置方式，
   这类卡在报告里记作 `multi-sentence`，交人工处理。
4. **已有 ≥2 条例句的卡一律「只补振假名」**（契约 §5.4）：这类卡的 `Sentence` /
   `Sentence Translation` / `AINote` / `Sentence Audio` 目标状态**就是卡上现值**，
   一个字都不写（见 §5.4 的判定表）。所以 `apply` 演练里只看到 `Sentence HTML` 一个 `≠`。
   这是修 bug：早先这类卡会被整篇重渲染 —— `AINote` 里已有的 ①② 讲解变成
   `① 旧正文 + ② 新正文` 的冗余，`<ul><li>` 排版被换成 `<p>`，还套出 `<div><div>` / `<p><p>`。
5. **`gen` 的警告**（只进 `out.json` 的 `gate.warnings` / `meta` / 报告，**不拦卡**）：
   * `target_reading_mismatch`：新句里出现了目标词，而它在 `new_sentence_ruby` 里被注的读音
     和卡上 `reading` 对不上（抽不出读音就不报，宁可漏报）。
   * `target_gloss_missing`：`new_word_gloss` 里没有目标词那一行，② 的义项行只能用卡上
     `Meaning` 兜底、看不出新句实际用的义项。
   * `sentence_overridden`（2026-10-26 加）：模型改写了 `sentence_source` 给的 Jisho 句子，
     脚本已按 Jisho 原句写回。
   * `contrast_format`（2026-10-26 加）：`contrast` 没写成「①是…，②是…」。
     注意 `norm_entry` **不对 `contrast` 剥开头 ①②**（那是内容，剥了会变成「是礼貌体…」）。
6. **闸门 6–9 是字段级**：只检查这次真的要写的字段（§5.4）。已有 2 句的卡不写 `AINote`，
   所以闸门 7/8 对它不适用 —— 拿卡上**旧** AINote 去卡一张本来能修好振假名的卡是误伤。
   闸门 5b、1–5 的严格程度一个字没变。

### 落盘（全部在 `data/core6000/` 与 `output/`）

```
data/core6000/state.json            扫描结果：每张卡的状态 + 选定范围 + 字段快照
data/core6000/report_<日期>.md      人看的统计报告
data/core6000/plan_<日期>.json      本次要做的 noteId 清单（= 断点续跑清单）
data/core6000/gen/<noteId>_in.json  发给模型的那张卡（追溯）
data/core6000/gen/<noteId>_out.json 模型产出（**断点续跑的最小单位**）
data/core6000/gen/<noteId>_meta.json usage/耗时
data/core6000/metrics_<日期>.json   token 账本
data/core6000/backup_<时间戳>.json  apply --commit 前的字段快照（revert 的唯一依据）
output/audio/core6000/<file>.mp3    TTS 产物（同时 storeMediaFile 进 Anki）
```

---

## 四、模型接口契约

### 4.1 请求

system = `code/execution/core6000_example_prompt.md`（整个文件，一次发送，逐卡复用）。
user = 下面这个 JSON（`<noteId>_in.json` 的 `payload` 字段，原样发）：

```json
{
  "id": 1621392074520,
  "word": "適当",
  "reading": "てきとう",
  "pos": "Adjectival Noun",
  "meaning": "合适的",
  "existing_sentences": [
    {"jp": "その質問の適当な答えが見つかりません。",
     "cn": "我找不到这个问题的合适答案。",
     "ruby": "その<ruby>質問<rt>しつもん</rt></ruby>の…"}
  ],
  "need_sentence1_ruby": false,
  "sentence_source": {
    "jp": "ここは初心者が練習するのに適当な場所だ。",
    "ruby": "ここは<ruby>初心者<rt>しょしんしゃ</rt></ruby>が<ruby>練習<rt>れんしゅう</rt></ruby>するのに<ruby>適当<rt>てきとう</rt></ruby>な<ruby>場所<rt>ばしょ</rt></ruby>だ。",
    "en": "This is a suitable place for beginners to practice.",
    "source": "Tatoeba",
    "url": "https://jisho.org/sentences/…",
    "note": "这一句是从 jisho.org 的真人语料里取来的，只能逐字使用，不许改写。"
  },
  "existing_note": {
    "中文翻译": "找不到那个问题的合适答案。",
    "核心词汇": "<ruby>質問<rt>しつもん</rt></ruby> (名词)：问题。<br>…",
    "语法要点": "1. 「～が見つからない」：…",
    "动词变形解析": "原形 <ruby>見<rt>み</rt></ruby>つかる…",
    "语境与表达风格": "该句使用了礼貌体…"
  }
}
```

* `existing_sentences` 只放已有的例句（通常 1 条）。
* **`sentence_source`（2026-10-26 起，`missing-sentence` 范围必有）**：脚本从 Jisho 挑定的
  真实例句。`jp` / `ruby` 是硬给定的，模型只许**逐字照抄**；`en` 仅供理解参考；
  `source` / `url` 是语料出处（Tatoeba / Jreibun + Jisho 句子详情页），写进
  `<noteId>_in.json` 供追溯，也用于报告。模型交回的 `new_sentence` 若与 `jp` 不一致，
  脚本**按 `jp` 覆盖**并记 `sentence_overridden` 警告。
* `need_sentence1_ruby=true` 时，`existing_sentences[0].ruby` 为空/不可用，
  模型必须补出 `sentence1_ruby`。
* 原卡**已有两条例句**时，payload 额外带两个键：`sentence2_is_existing`（恒为 `true`，
  告诉模型「第二句是卡上既有的，照抄，不要另造第三句」）与 `need_sentence2_ruby`
  （`true` = 第二句缺/坏振假名，模型必须用 `sentence2_ruby` 交回该句的振假名，见 §4.2）。
* `existing_note` 的键是该卡 AINote 里**实际出现的板块名**（已归一化到 5 个规范名，
  见 §5.2）。值是**去掉标签嫌疑后的可读文本**（可以带 `<ruby>`，不带 `<p>/<b>/<ul>`）。

### 4.2 响应（模型必须只输出这个 JSON）

```json
{
  "entries": {
    "1621392074520": {
      "new_sentence": "ここは初心者が練習するのに適当な場所だ。",
      "new_sentence_ruby": "ここは<ruby>初心者<rt>しょしんしゃ</rt></ruby>が<ruby>練習<rt>れんしゅう</rt></ruby>するのに<ruby>適当<rt>てきとう</rt></ruby>な<ruby>場所<rt>ばしょ</rt></ruby>だ。",
      "sentence1_ruby": "",
      "sentence2_ruby": "",
      "cn1": "",
      "cn2": "这里是适合初学者练习的地方。",
      "new_word_gloss": [
        {"w": "適当", "r": "てきとう", "pos": "な形容词", "mean": "合适的（本句用的就是这个义项）"},
        {"w": "初心者", "r": "しょしんしゃ", "pos": "名词", "mean": "初学者"},
        {"w": "練習", "r": "れんしゅう", "pos": "名词", "mean": "练习"},
        {"w": "場所", "r": "ばしょ", "pos": "名词", "mean": "地方、场所"}
      ],
      "grammar2": "・「～のに適当な」：…",
      "conjugation2": "目标词「適当」是な形容词，以「適当な」作定语，本句没有词形变化。…",
      "context2": "普通体口语，评价某处的条件合适。",
      "contrast": "①是礼貌体的客观陈述——找不到「合适的」答案；②是普通体的评价——这里做练习「合适」。义项相同，差在语体、句型与语气。"
    }
  }
}
```

* 这个例子里目标词的义项与卡上 `meaning`（「合适的」）一致；真要换义项，就必须在
  `new_word_gloss` 的目标词那一行写明（如「此处是「敷衍、随便」的意思」），
  不然 ② 的义项行会和卡上 `Meaning` 自相矛盾。

* `word` 必须是**目标词本身**在 `new_sentence` 里出现（机械闸门 §6）。
* `cn1` 只在原卡没有中文翻译时才需要（此时填原句翻译）；否则留空字符串。
* `sentence1_ruby` 只在 `need_sentence1_ruby=true` 时必填；否则留空字符串。
* `sentence2_ruby` 只在 `need_sentence2_ruby=true` 时必填（原卡已有两条例句、且第二句缺/坏振假名）：
  它与该句的 `new_sentence_ruby` 内容相同，去 ruby 后必须与卡上第二句**逐字一致**（闸门 5b）。
* `new_word_gloss`：新例句里值得讲的词（最多 4 个；**第一行固定是目标词本身**，见 §5.2 的 ②
  渲染；目标词那一行的 `mean` 要写明新句**实际用的义项**，用来交代义项是否与卡上 `Meaning` 一致）。
* **不要输出 `例句` 板块**：例句本身在 `Sentence` / `Sentence HTML` 字段里，AINote 不重复。
* 提示词里另有两条**警告级**（不是闸门）要求：新句的义项以卡上 `meaning` 为准（换义项必须在
  ② 的目标词那一行写明）、目标词在新句里的读音必须等于卡上 `reading`。脚本在 `gen` 里做两个
  便宜检查并记进 `out.json` / 报告的警告列，见 §3.3 第 5 条。

---

## 五、渲染规则（脚本侧，确定性）

### 5.1 `Sentence` / `Sentence HTML` / `Sentence Translation` / `Sentence Audio`

```
Sentence            = 原句 + '<br><br>' + new_sentence
Sentence HTML       = 按版式渲染（见 §5.2 的 html_wrap）
Sentence Translation= 原译 + '<br><br>' + cn2
Sentence Audio      = 原有 [sound:...] 原样保留 + '[sound:core6000-<noteId>-sentence-2.mp3]'
```

* `Sentence HTML` 的**内容**永远是「原句 ruby `<br><br>` 新句 ruby」；
  外层包裹沿用该卡原来的形态，机械判定：
  * 原来是 `<p>…</p><p>…</p>` → 继续用 `<p>` 包裹；
  * 原来是 `<div class="example">` / `<div style=…>` → 继续用同样的 `<div>`；
  * 原来是裸 ruby 或空 → 不加包裹，只写「原句 ruby`<br><br>`新句 ruby」。
* 原句 ruby 的取值优先级：卡里已有的 `Sentence HTML` 分段解析结果 > 模型给的 `sentence1_ruby`。
  只有解析失败才用模型值。**绝不用模型重写已有振假名。**
  * `Sentence HTML` 的分段：按 `<br><br>` / `</p>\s*<p>` 切成块，逐块去包裹取内层 HTML。
  * 若切不出与原句数量相等的块（例如 2 句但 HTML 只有 1 块）→ 视为不可用，走模型值。
* 已有 `Sentence HTML` 里出现 `<ruby>` 嵌套畸形（`<ruby><br>…`）→ 先按
  `today_new.py::sentence_html_line` 的做法清掉 base 里的 `<br>`。

### 5.2 `AINote` 版式（**沿用原卡版式**）

先判定原卡的版式族（`layout`），再按族渲染：

| layout | 判定 | 渲染 |
|---|---|---|
| `h3` | AINote 含 `<h3` | `<div>` + 每板块 `<h3>标签</h3><p>正文</p>` |
| `p-b` | AINote 含 `<p><b>` 或 `<b>标签</b>` | `<div>` + 每板块 `<p><b>标签</b><br>正文</p>` |
| `ul` | AINote 含 `<ul>` 且不含 `<p><b>`/`<h3>` | `<div>` + `<p><b>标签</b></p><ul><li>行1</li>…</ul>` |
| `plain` | 其它 | 同 `p-b` |

* **标签文字沿用原卡**（例如原卡写 `<b>1. 中文翻译</b>` 就继续写 `1. 中文翻译`，
  写 `<h3>词形解析</h3>` 就继续写「词形解析」）。
  归一化只用于**内部对齐**：
  * `中文翻译` ← 中文翻译 / 翻译 / 例句翻译
  * `核心词汇` ← 核心词汇 / 重要词汇 / 单词
  * `语法要点` ← 语法要点 / 语法 / 语法解析
  * `动词变形解析` ← 动词变形解析 / 词形解析 / 变形解析 / 活用
  * `语境与表达风格` ← 语境与表达风格 / 语境 / 表达风格
  * 归一化后仍无法归类的板块 → **整块原样保留，追加在新句板块之前**（不丢信息）。
* 板块正文的拼装：
  * `中文翻译`：`① <原译>` + `<br>` + `② <cn2>`
  * `核心词汇`：`① <原卡该板块正文>` + `<br>` + `② <目标词本身>（词性）：释义` + 每个 `new_word_gloss` 一行
  * `语法要点` / `动词变形解析` / `语境与表达风格`：`① <原卡该板块正文>` + `<br>` + `② <模型对应字段>`
  * `语境与表达风格` 末尾再加一行 `两句对比：<contrast>`
  * 原卡缺某个板块 → 该板块只写 ②（并在报告里记一条 `note_missing_section`）
  * `ul` 版式下，正文按 `<br>` 拆成 `<li>`。
* **② 的词表行文与 ① 一致**（`gloss_lines`）：`<ruby>漢字<rt>かな</rt></ruby>（词性）：释义`，
  只给汉字注音、假名词不加 ruby。目标词那一行用 `new_word_gloss` 里那一条（`mean` 写的是
  新句实际用的义项）；模型没给就回退到卡上的 `Meaning` + `Part of Speech`。词性英文（卡上
  `Part of Speech`）按 `POS_CN` 映射成中文。**① 的正文不经过这个函数**，改行文不动 ①。
* **清洗原卡正文**：删掉 `<p>/<b>/<strong>/<h3>/<h4>/<ul>/<li>/<div>` 等外壳标签，
  保留 `<ruby>`、`<br>`、正文文字。原卡正文里的 `1.` `2.` 序号行保留（属于内容）。

### 5.3 `not-merged` 范围（已有 2 句、AINote 未合并）—— **当前故意未实现**

设计意图：该范围下 ① 和 ② **都由模型产出**（因为原 AINote 无法可靠切分），
响应里额外给 `core1` / `grammar1` / `conjugation1` / `context1`。

**实现现状（以此为准）**：`code/execution/core6000_example_prompt.md` 现在只要求模型输出 10 个键，
**没有这四个键**。所以脚本在真正调模型之前先检测提示词
（`capabilities()`：文件正文里是否出现这四个键名），一旦这个范围被显式打开
（`--only not-merged`），命中的卡会被**整卡拦下**并写进报告，原因写明「缺 ①、做不了」——
状态表里是 `blocked`，既不调模型也不写库。
**绝不让模型在拿不到 ① 的情况下凭空编一份 ①**：那会把原卡已有的讲解丢掉，
直接违反「原句信息一个字都不丢」的核心原则。

**要真正启用这个范围**，只需给 `core6000_example_prompt.md` 加一节，
要求模型在响应里同时输出 `core1` / `grammar1` / `conjugation1` / `context1`（① 的四个板块）。
脚本侧的闸门（`unmerged` 卡必须给齐这四个键）与渲染分支（`both(原卡正文 or entry['core1'], ②)`）
都已就位，`capabilities()` 会自动放行。启用后一次别跑太多，先人工看 3 张确认 ① 没退化。

### 5.4 只写「真的坏了」的字段（`field_defects`）

**规则**：五个字段各有自己的目标状态（§5.1 / §5.2），`apply` 只写**卡上现值没达到目标、
且这次确实有新内容可写**的字段。**不是**「渲染结果与现值逐字不同就写」—— 渲染时顺手的
空白 / 外壳归一化不算缺陷，写了就是对用户内容的无谓改写。

| 字段 | 目标状态 | 1 句的卡 | 已有 2 句的卡 |
|---|---|---|---|
| `Sentence` | 两条例句（`<br><br>`） | 写（补第 2 块） | **不写** |
| `Sentence HTML` | 每句的汉字都有合规振假名 | 写（新句振假名） | 有句子缺/坏振假名才写 |
| `Sentence Translation` | 两条例句的中文 | 写（补新句译文） | **不写** |
| `AINote` | 每板块 `① 原句` + `② 新句` | 写（补 ②） | **不写** |
| `Sentence Audio` | 两条 `[sound:]` | 写（加新句 TTS） | **不写** |

* **已有 ≥2 条例句时，那 4 个字段的目标状态就是「卡上现值」**：第二句不是这次新造的，
  `Sentence` / `Sentence Translation` / `AINote` / `Sentence Audio` 对它没有新内容可写，
  所以只补振假名，其余 4 个字段**逐字不动**（原有 ①② 讲解、`<ul><li>` 排版都是原作者的版式）。
  这和「已有 2 句的卡重跑必须是 no-op」（§3.1）是同一件事。
* 那 4 个字段**另有**的缺陷（`audio-count` / `translation-empty` / `not-merged`）由 §6 的
  `blocked` 路径报给人，**不靠重渲染来假装修好**。
* `n_sent > 2`（3 句以上）一个字段都不写（闸门 6 会拦；渲染只会截断）。
* 由此派生：
  * `apply` 演练只打印**要写字段**的前后对照，并列出「不写的字段（保持卡上现值，逐字不动）」；
  * `backup_<时间戳>.json` 只备份**要写且真的会变**的字段（revert 仍然只还原被备份的字段）；
  * 写库后的回读校验分两半：写过的字段必须等于目标值，**没写的字段必须仍等于写库前的现值**
    （后者不查，「其余字段逐字未变」就只是口头承诺）；
  * 没有任何字段要写（例如 `--force` 重新点名一张已合规的 2 句卡）→ 报 `无需写字段`，不写库。

---

## 六、机械闸门（写库前，不合格 → 不写这张卡，写进报告）

1. `new_sentence` 去标签后**包含目标词**：`Word` 原文、或 `Transliteration` 读音、
   或 `Word` 的汉字/假名主干部（至少 1 个汉字字符序列）命中其一。
   纯假名词再加**活用形**（`kana_conjugations()`：五段行 + て/た 音便，
   `しゃがむ` → `しゃがんだ`/`しゃがんで`/`しゃがみます`…）：假名动词在真实语料里
   几乎只以活用形出现，只比词典形会把 Jisho 的正确候选判成 no-target（2026-10-30 加）。
   （闸门 1/2 只对**模型新造**的句子生效；已有两句话的卡见 §3.3）
2. `new_sentence` 长度 6–45 字符（去空白），且 **≠ 原句**。
3. `new_sentence_ruby` 去 ruby 后与 `new_sentence` 一致（`<rt>` 内容整块删掉、剥标签后比较，
   空白归一化）。
4. `new_sentence` 含汉字 ⇒ `new_sentence_ruby` 必须含 `<ruby>`，且每个 `<ruby>` 都有 `<rt>`；
   `<ruby>` 基底不得只含假名（敬语接头辞 `お`/`ご` 不得进基底，见手册坑表）。
5. `need_sentence1_ruby=true` 时 `sentence1_ruby` 必须合规（同 3/4）。
5b. `need_sentence2_ruby=true` 时 `sentence2_ruby` 必须合规：去 ruby 后与卡上**第二句**逐字一致，
   且每个 `<ruby>` 都有 `<rt>`、基底不得只含假名、ruby 之外不得再有汉字（同 3/4 的口径）。
   这条在 `gen` 与 `apply` 各查一遍（`apply` 那次是防 `out.json` 被手改）。
6. `Sentence` / `Sentence HTML` 渲染后必须恰好 **2 块**；`Sentence Audio` 恰好 **2 个** `[sound:`。
7. `AINote` 渲染后必须含 `中文翻译`、`核心词汇`、`语法要点` 三段，且含 `①` 与 `②`。
8. 原有 `AINote` 的**每个板块正文的非空字符长度**，必须出现在新 AINote 里
   （口径：把新 AINote 去标签、去空白后，要求原正文第一句的前 12 个字符是子串）
   —— 防模型/渲染静默丢原文。
9. 渲染后**要写的**字段任何一个为空 ⇒ 拒绝（不写的字段保持卡上现值）。

**闸门是字段级的**（§5.4）：闸门 6/9 只查 `write` 里的字段，闸门 7/8（AINote 的板块与
原文保全）只在真的要写 `AINote` 时才跑 —— 它们保护的是「别把原卡的讲解写坏」，
不写 `AINote` 的卡没有这个风险，也不该被卡上**旧** AINote 的形状拦下。
闸门 5b 与写不写无关，**永远照查**（严格程度未变）。

`gen` 阶段只跑闸门 1–5（含 5b；能提前发现就带提示重问一次，`--retries N`，默认 1 次），
`apply` 阶段跑 6–9 + 5b 的复核（渲染后才能判 6–9）。`gen` 另有两条**警告**
（`target_reading_mismatch` / `target_gloss_missing`，见 §3.3 第 5 条）：只记进产出的
`gate.warnings`、`meta` 与报告，**不拦卡**。

---

## 七、TTS

* 复用 `code/tools/edge_tts_min.py::synth()`，纯标准库，`voice='ja-JP-NanamiNeural'`。
* 文本 = 新例句**去 ruby、去标签**的纯日语（`strip_ruby_base` 同款口径）。
* 文件：`output/audio/core6000/core6000-<noteId>-sentence-2.mp3`。
* `tts` **只合成到本地磁盘，不碰 Anki**（这样 `tts` 可以随时重跑）。
  默认跳过已存在且 >1KB 的文件；`--force` 重做。
* `storeMediaFile` 统一放在 `apply --commit` 里（写字段之前），用 `getMediaFilesNames`
  回读确认；缺文件就拒绝写这张卡的 `Sentence Audio`。
  演练（不加 `--commit`）时只报告「将上传 N 个媒体文件」。
* 音频长度不做机械校验（无法离线判对错），但要在报告里列出字节数与时长估算，
  2026-10-06 起不再要求听音频确认：演练输出没问题就直接 `--commit`，事后发现读错用 `revert` 回退。

---

## 八、安全与回退

* `apply` 默认演练；`--commit` 前把每条卡**要写且真的会变**的旧字段值写进
  `data/core6000/backup_<时间戳>.json`（含 noteId + 字段旧值）。
* `revert --commit --backup <文件>` 逐条还原；媒体文件**不删**。
* 全程**只碰上述 5 个字段，而且只写其中「真的坏了」的那几个**（§5.4），
  不碰 `Word/Transliteration/Meaning/Part of Speech/Index/音调`，
  不碰 `cards.due`，不加标签，不动 deck。
* `apply --commit` 时不要有人在 Anki 浏览器里开着这些卡（字段不刷新）。

---

## 九、依赖与约束

* Python：`python`
* **只用标准库**（+ 复用工作区既有模块），不要 `pip install`（沙箱会拒）。
* 复用而不是重写：
  * `code/common/paths.py`（`ROOT` / `OUTPUT` / `DATA`）—— 先读它确认常量名
  * `code/execution/today_new.py` 的 `anki()` / `_split_ruby` / `to_ruby` /
    `strip_ruby_base` / `strip_tags` / `sentence_html_line` / LLM 客户端 / `extract_json`
    —— **直接 import 或按同口径复制**，不要另写一套
  * `code/tools/edge_tts_min.py::synth`
  * `code/execution/mine_audio.py` 的「合成 → storeMediaFile → 写 `[sound:]` → 回读校验」流程
* AnkiConnect 必须开着（`127.0.0.1:8765`）。本地模型端点默认 `http://127.0.0.1:8080/v1`（NInfer；Responses API：脚本打 `/v1/responses`）。
* 路径常量写死工作区绝对路径（同既有脚本风格）。
