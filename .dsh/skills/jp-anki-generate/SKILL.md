---
name: jp-anki-generate
description: anki-workspace 的**原子生成能力**：给**一张或几张**例句卡生成 `AINote`（讲解）与 `Sentence HTML`（振假名），默认只打印、`--commit` 才写这两个字段。**不切批、不排队、不规定流程**——要生成哪几张就点名哪几张。固定的是方法：本地模型按 `LOCAL_INSTRUCTION` 产出讲解 → `ruby_engine` 拿原始 `Sentence` 当骨架确定性重渲染 HTML（逐字一致是构造出来的）→ `check_cards` 一次闸门 → 只写两个字段并回读。当用户说「给这几张卡生成讲解/振假名」「这张卡的 AINote 空着，补一下」「这句要标假名」「Sentence HTML 重渲染」时加载本技能。**不含**清理、激活、挖生词、配音——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语例句卡 · 生成 AINote + Sentence HTML（单卡 / 数张）

本技能覆盖**一件事**：输入一张或几张例句卡，输出 `AINote` + `Sentence HTML`。

没有「阶段」，没有固定批数，也**不要求**先切批再生成再写库。有时只需要给三张卡补讲解，
这三张就是全部任务；流程怎么编排由调用方决定，本技能不预设。

## 一、边界

| | |
|---|---|
| **输入** | noteId / Anki 查询 / JSON 文件 / 一句原文（`--sentence`） |
| **输出** | `AINote`（讲解）与 `Sentence HTML`（振假名）。默认只打印；`--commit` 才写库 |
| **数量** | 1 张也行，几十张也行；每次调用独立，不依赖上一次的产出或批次号 |
| **只碰** | 这两个字段。`Sentence` / `Word` / `Source` / 音频 / 图片 / 标签 / deck / due 一个字不动 |
| **不做** | 切批、manifest、排队、整集编排；清理 / 激活 / 挖生词 / 配音也不在这里 |

“流程”指：跑几批、先跑哪一集、什么时候切批、失败怎么排队。**这些都不在本技能里写死。**
本技能只回答一个问题：**给定这几张卡，两个字段怎么产出来。**

## 二、环境与入口

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$EXE = "$WS\code\execution"
```

```powershell
# 一张 / 几张（点名的卡；--note-id 可重复或逗号分隔）
& $PY "$EXE\cards.py" gen --note-id 1791727898061
& $PY "$EXE\cards.py" gen --note-id 1791727898061,1791727898062 --per-request 2

# 一个查询命中的卡（--limit 防手滑扫全 deck）
& $PY "$EXE\cards.py" gen --query "tag:动画::<作品名>::<季>::第01集 AINote:" --limit 5

# 不读 Anki，只给一句（草稿 / 试提示词；不能 --commit）
& $PY "$EXE\cards.py" gen --sentence "郵便局に戻った時に調べてみるよ" --word ""

# 自己列一批句子/noteId（gen 吃 [{noteId?, sentence, word, source}]）
& $PY "$EXE\cards.py" gen --file temp\cards.json --per-request 3

# 确认后真写（只写 AINote / Sentence HTML；写后回读）
& $PY "$EXE\cards.py" gen --note-id 1791727898061 --commit

# 目标字段已有内容 → 默认跳过；确实要重做才加 --overwrite
& $PY "$EXE\cards.py" gen --note-id 1791727898061 --overwrite --commit

# 已经是现成 JSON（我 / 强模型 / 人工写的）→ 同一套 repair + 闸门 + 写库
& $PY "$EXE\cards.py" write --file fix.json --commit
```

常用开关：

- `--out PATH`：把结果落成 JSON（形状同 `write --file`），便于先看、改、再写。
- `--quiet`：不逐张打印两个字段全文（只要汇总）。
- `--per-request N`：本地模型首轮每次几张（默认 3；不合格的重问**逐张发**）。
- `--srt` / `--plan`：给字幕自带注音当权威读音来源（有就传，读音更准）。
- `--no-deck-lexicon`：不读本 deck 已有读音（离线 / 提速，读音来源变少）。

退出码：`0` = 选中的卡都处理完（含有意跳过）；`1` = 有卡没做出来 / 回读不一致。

## 三、固定生成方法（这部分不要自创）

### 3.1 输入契约

从 Anki 只读三个字段：

| 字段 | 用途 |
|---|---|
| `Sentence` | **唯一骨架**。可能含 `<br>`（字幕两行）、全角空格、`〓` 等噪声，一律原样 |
| `Word` | 非空时是这张卡指定的重点词，**核心词汇第一条必须是它** |
| `Source` | 只用来判断语域（动画口语 / 新闻 / 旁白），**不写进结果** |

### 3.2 `AINote` 的形状

固定三段、每段一个 `<p>`；动词变形段**按需**出现（全句没有活用就整段省略）：

```html
<p><b>中文翻译：</b>自然流畅、符合语境的中文翻译。</p>
<p><b>核心词汇：</b><br><ruby>漢字<rt>かな</rt></ruby>：词性。中文释义。<br>…</p>
<p><b>语法要点：</b><br>句型：含义 + 接续 + 在句中的功能<br>…</p>
<p><b>动词变形解析：</b><br>原形 → 变形（名称） → 变形（名称）＋辅助词<br>…</p>
```

- 核心词汇只列**句中出现过**的词，2–5 个；优先级：`Word` ＞ 惯用搭配 ＞ オノマトペ ＞
  片假名外来语 ＞ 一般实词。词性只用：名词／イ形容词／ナ形容词／自动词／他动词／副词／
  接续词／惯用句（拿不准就省词性，只写释义）。
- 整段控制在 400 字以内。这是复习卡，不是词条页。
- 只允许 `<p> <br> <b> <ruby> <rt>`；禁止 `div/span/style/class`、LaTeX、`\`、`$`、
  Markdown 围栏与 `**` 加粗、半角双引号 `"`（需要引号用「」）。

### 3.3 `Sentence HTML` 的形状

**只含例句本身**：给日语汉字标 ruby，不加翻译、不加解释、不用 `<p>` 包裹、
不改任何空格与标点、`<br>` 原位置保留**单个**。

- 送假名放在 `<rt>` 之外：`<ruby>食<rt>た</rt></ruby>べる`；
  熟字训整体标：`<ruby>今日<rt>きょう</rt></ruby>`；
  敬语接头辞在 ruby 外：`お<ruby>墓<rt>はか</rt></ruby>`。
- 纯假名不标 ruby；**中文汉字绝不标**（中文翻译/释义里的字都不标）。
- 判定“对不对”的唯一口径：**先整块删掉 `<rt>…</rt>`，再剥其余标签，必须与 `Sentence`
  逐字相同**（含空格、全角空格、原标点、`<br>` 数量）。
- 读音吃不准的人名/生僻字：**不猜**，该词不加 ruby，其余照常，在汇报里列出。

### 3.4 HTML 由引擎生成，不靠模型“一次写对”

`cards.py` 在拿到模型输出后，一律用 `ruby_engine.repair(mode='fix')` **拿原始 `Sentence`
当骨架重渲染**。逐字一致是构造出来的，不是校验出来的。缺的读音按优先级补：

1. 人工例外表 `data/ruby/readings.json`（确定值）
2. 字幕自带注音（`--srt` / `--plan` 给了才有）
3. 本 deck 已有卡的读音（有先例）
4. Sudachi 词典（兜底，多音词可能错）

模型给的读法只在没有更权威来源时保留；权威来源说错的会被改正（报告里打印
`读音按权威来源改正`）。只有 Sudachi 一家有意见的，只报“待复核”，不改。

### 3.5 闸门只跑一次

`check_cards.check()` 同时查 `AINote` 结构与 `Sentence HTML` 机械规则。按字段归属分开处置：

- **`AINote` 侧不合格**（缺段、非法字符、两个字段一个空一个非空）→ 逐张重问，默认 1 轮；
  仍不合格 → 这张不写，列出 noteId。
- **`Sentence HTML` 侧不合格**（字符漂移、漏 ruby、`<br>` 数不对）→ **不重问模型**。
  再问一次既修不好（它上一轮就是这么标的），还会把合格的讲解一起丢掉。`repair` 修完再判一次即可。
- **两个字段都空** = 模型判定“无法给出可靠讲解”，按规范**有意跳过**，不写库，也不算失败。

### 3.6 写库

只写 `AINote` / `Sentence HTML` 两个字段，写完 `verify_note_fields` 回读。
目标字段已有内容默认**拒绝覆盖**（`--overwrite` 明确要求才写）。
注意“只有 `Sentence HTML` 有内容、`AINote` 还空着”的卡也算已有内容（工具会打印是哪个字段）；
确认要连 HTML 一起重做时加 `--overwrite`。
Anki 浏览器正开着看那张卡时，写入可能不刷新——切走再切回，或关掉浏览器。

## 四、按场景选入口

| 场景 | 用什么 |
|---|---|
| 常规：让本地模型生成 | `cards.py gen …`（默认演练） |
| 本地模型不可用 / 要更强的模型 / 我先自己写 | 按上面的规范写 `[{noteId, AINote, SentenceHTML}]`，再 `cards.py write --file …` |
| 卡上已有内容，只是想修 HTML / 错读 | 不是本技能：`ruby_engine.py apply`（见 `jp-anki-check-ruby`） |
| 整集批量 | 也不是本技能：`cli.py episode` / `pipeline.py` 是批量调用方，它们复用的还是这里的方法 |

`write` 路径同样会做确定性 repair 与闸门，`Sentence` 也仍然以 **Anki 里的值为准**，
不会拿 JSON 里带的句子当骨架。

`write --file` 与 `gen --out` 用同一份形状：

```json
[{"noteId": 123, "AINote": "<p>…</p>", "SentenceHTML": "<ruby>…</ruby>"}]
```

## 五、收工汇报

- 选了几张、合格 / 有意跳过 / 未完成各几张；
- 未完成的 noteId 与原因（模型没返回、`AINote` 缺段、HTML 修完仍缺读音……）；
- 读音待复核 / 无来源的清单（让强模型或人裁决，不要自己猜）；
- 写库了没有、回读是否一致；`--out` 的落盘路径（如有）。

## 六、实测坑

1. **`Sentence HTML` 的机械问题不要重问模型**——2026-10-11 实测：本地模型 17 张里 11 张不合格，
   全是字符漂移 / 漏标 ruby，`repair` 后只剩“模型没返回”的才需要强模型。
2. **不要用模型回传的句子当骨架**：它会顺手改标点、吞空格、把 `〓` 洗掉。
3. **`Word` 非空时核心词汇第一条必须是它**，否则这张卡的“重点词”白设了。
4. **长句**：`fit_groups` 会按真实请求正文估算 token，自动拆请求；不要为了“一次跑完”硬塞。
5. **草稿不能写库**：`--sentence` 和 `--file` 里没有 noteId 的条目只用来试提示词/看效果；
   它们用负数占位，`--commit` 会直接拒绝。要写先落到 Anki 卡上。
6. **半角双引号**是最常见的打回项：`"..."` 一律换「」；`\` 与 `$` 同理。
7. **纯假名加 ruby** 是软提醒（不拦），但会制造噪声，不要写。

## 七、相关文件（改规则时只改这些地方）

- 规范正文：`docs/jp-card-agent-instruction.md`
- 提示词正本：`code/execution/pipeline.py` 的 `LOCAL_INSTRUCTION`（**只此一份**）
- 生成 / 写入入口：`code/execution/cards.py`
- 确定性振假名：`code/common/ruby_engine.py`
- 结构闸门：`code/common/check_cards.py`

---

**本技能只做这两个字段。** 清理（阶段 1）→ `jp-anki-triage`；激活 → `jp-anki-activate`；
挖生词 → `jp-anki-mine`；配音 → `jp-anki-audio`；整集编排 → `jp-anki-pipeline` / `cli.py episode`。
