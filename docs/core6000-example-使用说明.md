# 按需补例句② · 使用说明（`core6000_example.py`）

> 状态：active ｜ 最后核实：2026-11-09

**这是什么**：给用户点名的 core6000 词补「第二条例句」的操作说明（`core6000_example.py`）。
**为什么存在**：卡上第一条例句记不住时，需要一条换语境的新句 + 振假名 + 新音频，且只改 5 个字段。
**什么时候读**：用户说「这几个词我记不住，给我加一句例句」时。

给 `0-日本语学习::0-词汇::1-高频日语单词 6000` 里**用户点名的、自己记不住的**词，
补上**第二条例句**，并和卡上已有的讲解合成 ①② 两段，再给新句配 edge-TTS 音频。

```
gen → tts → apply --commit（直接真写）
Jisho 取真实新句 + gen 闸门 1–4 ｜ 本地模型出中文翻译与 ② 讲解 ｜ edge-TTS 到 output/audio/core6000/ ｜ apply 写前自动落 backup_<时间戳>.json、写后逐卡回读
```

> ⚠️ **按需，不是全量补全。** 只做用户点名的词。6000 张卡里绝大多数一直是**单例句**，
> 这是正常状态，不要去"补齐"它。不给目标选择器时脚本会直接拒绝跑（要全库必须显式 `--all`，
> 或用 `--only SCOPE --limit N` 限定规模）。

- 代码：`code/execution/core6000/core6000_example.py`（入口也是 `cli.py core6000 …`）
- 模型侧规范：`code/execution/core6000/core6000_example_prompt.md`（要改模型的教学口径就改它）
- 设计契约：[core6000-example-design.md](core6000-example-design.md)
- 原始教学口径：[japanese-word-example-teaching.md](japanese-word-example-teaching.md)

---

## 一、环境前置

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$CE  = "$WS\code\execution\core6000\core6000_example.py"
```

1. **Anki 必须开着**（AnkiConnect `127.0.0.1:8765`）——`scan` / `gen` / `tts` / `apply` 都要读卡。
2. **本地模型服务必须起着**（NInfer，默认 `http://127.0.0.1:8080/v1`，走 Responses API `/v1/responses`）。api key 查找顺序
   同 `today_new.py`：`--api-key` → `$env:DSH_LOCAL_LLM_API_KEY` → `~/.dsh/local-llm.json`。**不要写进脚本或文档。**
3. **Jisho 要能访问**（新句一律从 jisho.org 的真实语料里挑，不是模型造句）。缓存与限速见第二节。
4. 先看一眼进度（都只读）：

```powershell
& $PY $CE status                     # 牌组 / 模型 / 提示词 / 上一条计划 / 今日 token / 最近备份
& $PY $CE scan                       # 全库体检（≈6000 张）：多少卡缺句、缺振假名、已合规
& $PY $CE scan --words "徹夜,適当"   # 只看选中的卡
```

---

## 二、三条命令、Jisho 例句源与典型会话

**新例句必须是真实语料。** `gen` 先用 `code/tools/jisho_example.py` 抓 jisho.org 的 Sentence
搜索结果（Tatoeba 日常口语 / Jreibun 教材书面），按四道机械闸门挑一条：振假名结构合格、
句子里真的含目标词、长度进闸门区间（6–45 字）、与卡上第一句的字符相似度 **< 0.72**
（挡住「只换主语/时间」的换皮句）。挑中的句子与振假名被钉死写进 payload，模型只写
`cn2`、`new_word_gloss`、`grammar2/conjugation2/context2/contrast`；模型若改写了那句，
脚本按 Jisho 原句写回并记一条 `sentence_overridden` 警告。

- **零候选 = 这张卡失败**：Jisho 没返回 / 过滤后 0 条 / 都不合格时，`gen` 不调模型、直接记失败。
  `--allow-model-sentence` 是显式降级开关，**默认关；要用先问用户**。
- **候选缓存**：`data/core6000/jisho/<noteId>.json`。Jisho 的 robots.txt 要求 crawl-delay 40s，
  所以一张卡只抓一页，重跑 gen / 重试都读缓存；`--refresh-jisho` 才重抓。

```powershell
& $PY $CE gen   --words "徹夜,適当,残り"              # Jisho 取句 → 本地模型写 ② → data/core6000/gen/<noteId>_out.json
& $PY $CE tts   --words "徹夜,適当,残り"              # edge-TTS → output/audio/core6000/（不碰 Anki）
& $PY $CE apply --words "徹夜,適当,残り" --commit     # 真写（2026-11-09 起不再先演练，直接带 --commit）
& $PY $CE revert --commit                              # 反悔（默认演练，加 --commit 才还原）
```

> **现行规矩（用户 2026-11-09 定）：`apply` 直接带 `--commit` 真写，不再先演练一轮。**
> 例句来源与换皮判断已由 gen 阶段的闸门兜住；`--commit` 仍是唯一的真写开关——
> 不带它仍会只打印前后对照不写库（留着排错用），但日常流程里不要先跑一遍无 `--commit` 的 apply。

**三步必须用同一套选择器**：`tts` 读 `gen` 的产出合成音频，`apply` 又按同一套选择器重新挑卡。

| 选择器 | 含义 |
|---|---|
| `--note-ids 1621392074520,1621392074521` | 直接点名 noteId |
| `--words "徹夜,あまり"` | 比 `Word` 字段（退回 `Transliteration`），忽略大小写与空格 |
| `--from-file data\core6000\my_words.txt` | 一行一个词或 noteId（`#` 注释、空行忽略）|
| `--from-weak --days 3 --rating again` | **「只针对我记不住的」入口**：内部跑 `today_weak.py --plain`，取今天/近 N 天的弱项词（`--days` 默认 1；`--rating` 可选 `again` / `hard` / `both`）|
| `--query 'tag:待补例句'` | 任意 Anki 查询（默认只加 deck + 模型过滤）|
| `--all` | 显式全库（≈6000 张）|
| `--only SCOPE` / `--limit N` | 范围过滤 / 最多做几张（都作用在「待做卡」上）|

`--only` 的实现默认是 **`missing-sentence`、`missing-ruby`**；`not-merged`（已有两句话但 AINote
没合并）**显式给出才跑**：提示词现在会产出 ① 的四个键（`core1` 等），命中卡会重写 `AINote`
（① 也由模型产出），其余字段不动。默认范围仍不含它——已有两句、AINote 已合并的卡必须是
no-op。`--only all` = 三项并集。

### Jisho 相关开关（只在 gen 上）

| 参数 | 作用 |
|---|---|
| `--refresh-jisho` | 忽略缓存重新抓 Jisho 一页 |
| `--jisho-timeout` | Jisho HTTP 超时秒数（默认 30）|
| `--no-dict` | 振假名渲染时不拿 JMdict 否决 Jisho 被截断的读音（一般不用）|
| `--allow-model-sentence` | ★ 降级开关：Jisho 零候选时允许退回模型造句。**默认关；要用先问用户** |

### 典型会话

```powershell
# 「这几个词我老记不住，给我各加一句例句」—— 直接点名
& $PY $CE gen   --words "徹夜,適当,残り"
& $PY $CE tts   --words "徹夜,適当,残り"
& $PY $CE apply --words "徹夜,適当,残り" --commit

# 「把今天答得不好的词挑几个补一句」
& $PY $CE gen --from-weak --days 3 --rating again  # 先看它选中了哪些词；不满意就改用 --words 点名

# 只看进度（只读）
& $PY $CE status
```

---

## 三、这些字段会变成什么（**只写该改的字段**）

| 字段 | 变成 |
|---|---|
| `Sentence` | `原句<br><br>新句`（恰好 2 块；**新句逐字来自 Jisho**）|
| `Sentence HTML` | 两句的振假名（每个汉字都有 ruby），多句用单个 `<br>` 分隔；每句内部的字幕换行 `<br>` 原样保留（新句振假名来自 Jisho，不是模型渲染）|
| `Sentence Translation` | `原译<br><br>新译` |
| `AINote` | **沿用原卡版式与板块标签文字**，每个板块变成 `① 原句相关` + `② 新句相关`；① 的正文**逐字沿用卡里已有文本**，不交给模型改写 |
| `Sentence Audio` | 原有 `[sound:…]` 原样保留 + `[sound:core6000-<noteId>-sentence-2.mp3]` |

**只写「真的坏了」的字段**（契约 §5.4）。渲染时顺手的空白/外壳归一化不算缺陷，不算要写：

* **单例句的卡（要从 Jisho 取新句）**：上面五个字段都写（新句、它的振假名/译文、② 讲解、新句音频）。
* **本来就是两句话的卡**：第二句是卡里既有的，其余四个字段**没有新内容可写**，
  所以**只写 `Sentence HTML`**（把缺/坏的振假名补上），
  `Sentence`、`Sentence Translation`、`AINote`、`Sentence Audio` **逐字不动** ——
  卡上已有的 ①② 讲解、`<ul><li>` 排版都是原作者的版式，脚本不重排、不套 `<div><div>`。
  `apply --commit` 的输出里会列出「不写的字段（保持卡上现值，逐字不动）」。

`Word` / `Transliteration` / `Meaning` / `Part of Speech` / `Index` / 音调字段**一个字都不动**，
也不加标签、不动 deck 与 `due`；已有振假名不会被模型重写。
**本来就是两句话的卡不会再补第三句**，也不会重复写同一个 `[sound:]`。
三句以上的卡、以及那四个字段自有别的毛病（音频条数不对、译文全空）的卡，
脚本**不代笔**，在报告里列出原因交人工 —— 不会靠「整篇重渲染」假装修好。
AINote 没合并的卡要重写讲解时，显式 `--only not-merged`（① 由模型产出，只写 AINote）；
插件【卡片修正】的 AINote 目标走同一套渲染（`note_regen.py`）。

---

## 四、机械闸门

gen 阶段有两套判定，编号不同、别混：

- **Jisho 选句四道筛**（`pick_jisho`，在 `gen` 里挑句时判，不合格的句子直接不进模型）：
  ① 振假名结构合格；② 句子里真的含目标词（不是 Jisho 的模糊命中）；③ 长度 6–45 字；
  ④ 与卡上第一句的字符相似度 **< 0.72**，再像就是换皮，换下一条。
- **机械闸门 1–9**：`gen` 跑 1–5（拿到模型产出就能判）；`apply` 跑 6–9（渲染后才能判）。

任何一条不过，**这张卡就不写库**，并写进报告。

| # | 闸门 |
|---|---|
| 1 | 新句必须用上目标词（**闸门 1/2 只管模型新造的句子**，已有两句的卡跳过）|
| 2 | 新句 6–45 字，且 ≠ 原句 |
| 3 | 新句振假名去 `<rt>`、剥标签后与正文逐字一致 |
| 4 | 新句有汉字就必须有 `<ruby>`，每个 `<ruby>` 都有 `<rt>`，基底不得只含假名（敬语接头辞不包进基底）|
| 5 | 需要补原句振假名时，同样要过 3/4 |
| 6 | `Sentence` / `Sentence Translation` 恰好 2 块；`Sentence HTML` 是「原句 ruby + `<br>` + 新句 ruby」（句内换行 `<br>` 不算第三句）；`Sentence Audio` 恰好 2 个 `[sound:` |
| 7 | `AINote` 含 `中文翻译` + `核心词汇` + `语法要点`，且含 `①` 与 `②` |
| 8 | 原卡每个板块正文的前 12 字必须仍出现在新 `AINote` 里（防静默丢原文）|
| 9 | 这次**要写**的字段任何一个渲染后为空 ⇒ 拒绝（不写的字段保持卡上现值）|

> **换皮句在选句阶段就被 Jisho 第④道筛（相似度 ≥0.72 直接换下一条）判掉了**——例句取自 Jisho
> 真实语料，「模型只换主语/时间」这种问题不再依赖人看演练输出兜底。

修不了的卡（3 句以上，全库 1 张）只在报告里列出原因，不动它；已有两句但第二句缺振假名的卡
**能修**（模型交回 `sentence2_ruby`，**闸门 5b** 验，不合格就拒绝）；`not-merged` 需显式
`--only not-merged` 才重写 AINote（① 也由模型产出）。

**闸门是字段级的**：6–9 只检查这次**真的要写**的字段（见第三节）。已有两句话、只补振假名的卡
不写 `AINote`，所以闸门 7/8 对它不适用 —— 拿卡上**旧** AINote 的形状去卡一张本来能修好的卡是误伤。
**闸门 5b 与写不写无关，永远照查**（严格程度未变）。

`gen` 另有几条**警告**（只进 `gen/<noteId>_out.json` 的 `gate.warnings`、`meta` 与报告，
**不拦卡**）：

| 警告 | 含义 |
|---|---|
| `sentence_overridden` | 模型改写了 Jisho 原句 → 脚本按 Jisho 原句写回（库里不会出现模型编的第 2 句）|
| `target_reading_mismatch` | 新句里出现了目标词，而它的读音和卡上 `Transliteration` 不一致（同一张卡里出现了第二种读音）。抽不出读音就不报，宁可漏报 |
| `target_gloss_missing` | `new_word_gloss` 里没有目标词那一行 → ② 的义项行只能用卡上 `Meaning` 兜底，看不出新句实际用的义项 |

---

## 五、断点续跑、幂等与安全约定

- **每张卡一个产出文件**：`data/core6000/gen/<noteId>_out.json`（gen 闸门通过的才算数）。
  中断（Ctrl+C / 断电）后**直接重跑 `gen`**，已完成的自动跳过；`--restart` 才整张重生成。
- **already_ok**：已经有合规「② + 音频」的卡重跑报 `already_ok` 跳过，**绝不重复追加第二句**；
  `--force` 才重做。
- `scan` / `status` **只读**，不调模型、不写库；`tts` 只写本地磁盘，也不碰 Anki。

| 动作 | 默认 | 现行用法 |
|---|---|---|
| `apply` | 不带 `--commit` 是演练（打印要写字段的前后对照 + 「不写的字段」清单，不写 Anki），留给排错 | **直接带 `--commit` 真写**（2026-11-09 起不再先演练）|
| `revert` | 演练：只打印将要还原什么 | `--commit` 真还原 |
| `tts` | 真合成 mp3（但不碰 Anki）| `--force` 重做已存在的 |

- `apply --commit` 写库**之前**先把每条卡**要写且真的会变**的旧字段值存进
  `data/core6000/backup_<时间戳>.json`——这是 revert 的唯一依据，**别删**。
- 媒体上传后用 `getMediaFilesNames` 回读确认，写完**逐卡回读**校验：写过的字段必须等于写入值，
  **没写的字段必须仍等于写库前的现值**（两条都过才打印「回读校验通过」）。
- `revert` 只还原备份里那几个字段，**媒体文件不删**（留在媒体库里无害；要清理去 Anki「工具 → 检查媒体」）。
- 写库时不要在 Anki 浏览器里开着这些卡（界面不刷新，看着像没写进去）。

---

## 六、产出路径

> 完整落盘表（含 `gen/`、`tts/`、备份文件）以
> [core6000-example-design.md](core6000-example-design.md) 的「落盘」一节为准；这里只列常用项。

| 路径 | 内容 |
|---|---|
| `data/core6000/state.json` | 每张卡的状态（句块数 / 版式 / 缺什么 / 已合规）|
| `data/core6000/jisho/<noteId>.json` | Jisho 候选缓存（一张卡只抓一页；`--refresh-jisho` 才重抓）|
| `data/core6000/plan_<日期>.json` | 本次清单 + 渲染明细（**断点续跑清单**）|
| `data/core6000/report_<日期>.md` | 人看的报告（含被拦下的卡与原因）|
| `data/core6000/word_index.json` | 词形索引缓存（`--words` / `--from-weak` 用）|
| `data/core6000/gen/<noteId>_in.json` | 发给模型的那张卡（追溯）|
| `data/core6000/gen/<noteId>_out.json` | 模型产出（**断点续跑的最小单位**）|
| `data/core6000/gen/<noteId>_meta.json` | usage / 耗时 / 每次尝试的闸门结论 |
| `data/core6000/metrics_<日期>.json` | token 账本 |
| `data/core6000/backup_<时间戳>.json` | `apply --commit` 前的字段快照（revert 的唯一依据）|
| `output/audio/core6000/core6000-<noteId>-sentence-2.mp3` | 新句 TTS（`apply --commit` 时才上传进媒体库）|

---

## 七、写完之后看什么

现行流程不再先演练，也没有「听音频确认」环节（用户 2026-10-06 起不再要求；
2026-11-09 起连演练也免了）。`apply --commit` 跑完对两样东西即可：

1. 输出里的 **「Jisho 新句（来源）」行**——句子、语料来源与详情链接，确认取的是真实例句；
2. **逐卡回读校验结论**——写过的字段等于写入值、没写的字段仍是原值，两条都过才算成。

机械闸门查不出的残余问题（仍要留意，但不必事前拦）：

1. **多汉字词可能被逐字标 ruby**（`<ruby>場<rt>ば</rt></ruby><ruby>所<rt>しょ</rt></ruby>`）——
   每个 `<ruby>` 都合规，闸门过得去，但不符合本 deck「一词一 ruby」（`<ruby>場所<rt>ばしょ</rt></ruby>`）
   的风格。→ 报告里发现就 `gen --restart --words "<那个词>"` 重生成，或人工改 `<noteId>_out.json` 后重跑。
2. **义项/读音的一致性只有警告，没有闸门**：`target_reading_mismatch` / `target_gloss_missing`
   只是提示；对某张卡不放心时，对着卡上 `Meaning` / `Transliteration` 看一眼 ② 的目标词那一行。
3. 事后发现音频读音/断句不对：`revert --commit` 回退（脚本只报字节数与时长估算；
   想抽听去 `output/audio/core6000/`）。

> **和既有流程的关系**：这条能力**不动**主线流水线（`pipeline.py` 阶段 0–2）与每日讲义链路
> （`today_new.py`），三套代码共用同一份 deck 结构；补过例句的词第二天会自然出现在讲义里
> （`Sentence` 按句展开，逐句配译文与音频），**不需要改讲义链路**。

---

## 八、常见问题排查

| 现象 | 原因 / 处理 |
|---|---|
| `连不上 AnkiConnect` | Anki 没开或 AnkiConnect 插件没装。开启后重试；`status` 会打印它要连的地址 |
| `端点返回 HTTP 401/403` | api key 不对或没提供。检查 `--api-key` / `$env:DSH_LOCAL_LLM_API_KEY` / `~/.dsh/local-llm.json`（NInfer 默认不校验） |
| `端点返回 HTTP 404` | `base_url`、模型名或路由不对（脚本打 `<base_url>/responses`）。用 `today_new.py models` 看真实模型 id，再用 `--model` 覆盖 |
| `jisho 零候选` | Jisho 没返回 / 过滤后 0 条 / 都不合格 → 这张卡失败。换词，或显式 `--allow-model-sentence`（**先问用户**）；被 robots.txt 限速时等一会再 `--refresh-jisho` |
| 模型输出非法 JSON / 被长度截断 | `gen` 会带提示重问（`--retries`，默认 1 次）；仍不行就报错，原因留在 `gen/<noteId>_meta.json`，重跑 `gen` 即可 |
| `--per-batch` 直接报错 | 它**只接受 1**（>1 会打印说明后退出）。要省时间请缩小选择器范围 |
| 卡被拦下怎么办 | 看 `data/core6000/report_<日期>.md` 的原因列：`multi-sentence`（3 句以上，人工处理）、`already_ok`（已合规，不用管）；`not-merged` 要重写 AINote 时显式 `--only not-merged`（① 也由模型产出）|
| `tts` 报「缺模型产出」 | 那几张没跑成 `gen`（或闸门没过）→ 先 `gen` 再 `tts` |
| 选中的卡「没有待做的」 | 都 already_ok 或修不了 → 用 `scan --words "…"` 确认 |

**退路**：`gen` / `tts` 只写 `data/` 与 `output/`，不碰 Anki；`apply --commit` 写入前有 `backup_<时间戳>.json`，最坏情况 `revert --commit` 还原。
