---
name: jp-anki-core6000-example
description: anki-workspace 的**日常任务 ③ · 按需补例句**：给用户点名的 core6000 词补第二条例句（新句 + 振假名 + 合并讲解 + edge-TTS 配音），固定 gen → tts → apply 流程。**这是「按需」能力，不是全量补全。** 用户对自己记不住的 core6000 词点名要一句不同语境的例句，脚本给这些卡补上第二条例句，并把它和已有讲解合成 ①②两段。当用户说「这几个词我记不住，给我加一句例句」「把今天答得不好的词挑几个补一句例句」「这个 core6000 词要补例句」时加载本技能。**不含**每日讲义、弱项分析、每集素材流水线——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语 Anki 日常链路 ③ · 按需补例句（core6000 ②）

本技能覆盖**一件事**：给用户点名的 core6000 词补第二条例句 + 振假名 + 合并讲解 + 配音。

## 一、核心契约

**这是「按需」能力，不是全量补全。** 用户对自己**记不住的** core6000 词，额外要一句**不同语境**的例句来帮助记忆。6000 张里绝大多数一直是**单例句**，这是正常状态，**不要去"补齐"它**。脚本在没有目标选择器时也会拒绝全量跑（要全量必须显式 `--all`）。

它只碰这 5 个字段，而且只写「真的坏了」的那几个（`Word` / `Transliteration` / `Meaning` / `Part of Speech` / `Index` / 音调字段一个字不动，也不加标签、不动 deck 与 `due`）：

| 字段 | 变成 |
|---|---|
| `Sentence` | `原句<br><br>新句`（两句） |
| `Sentence HTML` | 两句的振假名（**每个汉字都有 ruby**），外层包裹沿用原卡形态 |
| `Sentence Translation` | `原译<br><br>新译` |
| `AINote` | 沿用原卡版式，每个板块变成 `① 原句` + `② 新句`（原句讲解**逐字保留**） |
| `Sentence Audio` | 原有音频 + `[sound:core6000-<noteId>-sentence-2.mp3]`（新句的 edge-TTS） |

> **已有两句话的卡只补振假名**：第二句是卡里既有的，其余 4 个字段没有新内容可写，一律**逐字不动**（卡上原有的 ①② 讲解、`<ul><li>` 排版都是原作者的版式，脚本不重排）。

## 二、固定流程：gen → tts → apply

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$EXE = "$WS\code\execution"
```

### 3.1 三步固定顺序，每步都带上同一套选择器

```powershell
# 直连本地模型 → data/core6000/gen/<noteId>_out.json
& $PY "$EXE\core6000_example.py" gen   --words "徹夜,適当,残り"

# edge-TTS → output/audio/core6000/（不碰 Anki）
& $PY "$EXE\core6000_example.py" tts   --words "徹夜,適当,残り"

# 演练：打印 5 个字段前后对照
& $PY "$EXE\core6000_example.py" apply --words "徹夜,適当,残り"
#   ★ 唯一的人看闸门：演练输出的前后对照 + Sentence HTML（2026-10-06 起不再要求听音频确认）

# 真写（写前自动落 backup_<时间戳>.json）
& $PY "$EXE\core6000_example.py" apply --words "徹夜,適当,残り" --commit

# 反悔：按 backup 逐条还原那 5 个字段（媒体不删）
& $PY "$EXE\core6000_example.py" revert --commit
```

### 3.2 「只针对我记不住的」入口：直接吃今天/近几天的弱项

```powershell
& $PY "$EXE\core6000_example.py" gen --from-weak --days 3 --rating again
#   内部跑 code/analysis/today_weak.py --plain --days 3 --rating again，取它的 stdout 词表
```

## 三、目标选择器（按优先级取**第一个**给出的；gen/tts/apply 必须有其一）

| 选择器 | 说明 |
|---|---|
| `--note-ids` | Anki 的 noteId |
| `--words` | 比 Word 字段（退回 Transliteration），忽略大小写与空格 |
| `--from-file` | 一行一个词或 noteId（# 注释与空行忽略） |
| `--from-weak` | 今天/近几天的弱项词（跑 today_weak.py 取词表） |
| `--query` | 任意 Anki 查询，如 `tag:待补例句`；默认只加 deck+模型过滤 |
| `--all` | 显式全库（≈6000 张，只读体检/批量补时才用） |
| `--only` + `--limit` | 范围过滤 + 最多做几张 |

没有目标选择器时：`gen/tts/apply` 直接拒绝并打印选择器清单（不默认全量；要全量必须显式 `--all`，或用 `--only SCOPE --limit N` 限定规模）。只有 `scan`（体检）和 `status`（看进度）能不带选择器跑。

## 四、范围 `--only`（默认**不含** not-merged）

| 范围 | 说明 |
|---|---|
| `missing-sentence` | `Sentence` 只有 1 块 → 模型造第 2 句 |
| `missing-ruby` | `Sentence HTML` 有汉字但没有振假名 / 为空 → 模型补振假名 |
| `not-merged` | 已有 2 句但 AINote 里没有 ①② 合并 → 契约 §5.3 要求**① 也由模型产出** |

> ⚠️ 当前 `core6000_example_prompt.md` 只让模型输出 10 个键、没有这四个，所以这个范围会被**提前拦下**并在报告里写明原因（要跑它先给提示词加那一节）。

## 五、规范与契约文档

- 契约文档（唯一接口契约，改接口先改它）：`docs/core6000-example-design.md`
- 模型侧规范（另一个文件，本脚本只读）：`code/execution/core6000_example_prompt.md`
- 用户的原始教学规范：`docs/japanese-word-example-teaching.md`

## 六、与每日讲义的关系

`today_new.py` 会把 core6000 卡的例句照 `Sentence` 字段展开进讲义（两句就显示两句）。所以补过例句的词，第二天讲义的例句栏自然就是两句，**不需要为它改讲义链路**。

## 七、收工汇报

- 点名的词 → 每张卡 `gen` 与闸门结果 → `apply` 演练看到了什么（尤其 `Sentence HTML` 与换皮判断）→ 是否 `--commit` → `backup_<时间戳>.json` 路径。
- 若这次补例句的词来自弱项，注明是 `--from-weak` 选出来的（弱项 → 补例句 的联动）。

---

**本技能只做核心6000 补例句。** 每日讲义 → `jp-anki-daily-lesson`；弱项分析 → `jp-anki-daily-weak`；每集素材流水线 → `jp-anki-triage` / `jp-anki-generate` / `jp-anki-activate` / `jp-anki-mine` / `jp-anki-audio`。
