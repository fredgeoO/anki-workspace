# 按需补例句② · 使用说明（`core6000_example.py`）

> 状态：active ｜ 最后核实：2026-10-10

**这是什么**：给用户点名的 core6000 词补「第二条例句」的操作说明（`core6000_example.py`）。
**为什么存在**：卡上第一条例句记不住时，需要一条换语境的新句 + 振动假名 + 新音频，且只改 5 个字段。
**什么时候读**：用户说「这几个词我记不住，给我加一句例句」时。

给 `0-日本语学习::0-词汇::1-高频日语单词 6000` 里**用户点名的、自己记不住的**词，
补上**第二条例句**，并和卡上已有的讲解合成 ①② 两段，再给新句配 edge-TTS 音频。

```
gen → tts → apply（演练：看前后对照 + 听新音频）→ apply --commit
本地模型出新句+振假名+②讲解 ｜ edge-TTS 到 output/audio/core6000/ ｜ 不写库 ｜ 真写该写的那几个字段（写前落快照）
```

> ⚠️ **按需，不是全量补全。** 只做用户点名的词。6000 张卡里绝大多数一直是**单例句**，
> 这是正常状态，不要去"补齐"它。不给目标选择器时脚本会直接拒绝跑（要全库必须显式 `--all`，
> 或用 `--only SCOPE --limit N` 限定规模）。

- 代码：`code/execution/core6000_example.py`
- 模型侧规范：`code/execution/core6000_example_prompt.md`（要改模型的教学口径就改它）
- 设计契约：[core6000-example-design.md](core6000-example-design.md)
- 原始教学口径：[japanese-word-example-teaching.md](japanese-word-example-teaching.md)

---

## 一、环境前置

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$CE  = "$WS\code\execution\core6000_example.py"
```

1. **Anki 必须开着**（AnkiConnect `127.0.0.1:8765`）——`scan` / `gen` / `tts` / `apply` 都要读卡。
2. **本地模型服务必须起着**（NInfer，默认 `http://127.0.0.1:8080/v1`，走 Responses API `/v1/responses`）。api key 查找顺序
   同 `today_new.py`：`--api-key` → `$env:DSH_LOCAL_LLM_API_KEY` → `~/.dsh/local-llm.json`。**不要写进脚本或文档。**
3. 先看一眼进度（都只读）：

```powershell
& $PY $CE status                     # 牌组 / 模型 / 提示词 / 上一条计划 / 今日 token / 最近备份
& $PY $CE scan                       # 全库体检（≈6000 张）：多少卡缺句、缺振假名、已合规
& $PY $CE scan --words "徹夜,適当"   # 只看选中的卡
```

---

## 二、三条命令、目标选择器与典型会话

```powershell
& $PY $CE gen   --words "徹夜,適当,残り"     # 直连本地模型 → data/core6000/gen/<noteId>_out.json
& $PY $CE tts   --words "徹夜,適当,残り"     # edge-TTS → output/audio/core6000/（不碰 Anki）
& $PY $CE apply --words "徹夜,適当,残り"            # 演练：打印要写字段的前后对照 + 不写的字段清单
& $PY $CE apply --words "徹夜,適当,残り" --commit    # 真写（2026-10-06 起不再要求听音频确认）
& $PY $CE revert --commit                            # 反悔（默认也是演练，加 --commit 才写）
```

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
没合并）**当前故意未实现**——提示词还没有 ① 的那四个键，命中的卡会被整卡拦下并写明原因，
**不会硬编一份 ①**。`--only all` = 三项并集。

### 典型会话

```powershell
# 「这几个词我老记不住，给我各加一句例句」—— 直接点名
& $PY $CE gen   --words "徹夜,適当,残り"
& $PY $CE tts   --words "徹夜,適当,残り"
& $PY $CE apply --words "徹夜,適当,残り"          # 看要写字段的前后对照（不必听音频）
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
| `Sentence` | `原句<br><br>新句`（恰好 2 块）|
| `Sentence HTML` | 两句的振假名（每个汉字都有 ruby），外层包裹沿用原卡（`<div>` / `<p>` / 裸 ruby）|
| `Sentence Translation` | `原译<br><br>新译` |
| `AINote` | **沿用原卡版式与板块标签文字**，每个板块变成 `① 原句相关` + `② 新句相关`；① 的正文**逐字沿用卡里已有文本**，不交给模型改写 |
| `Sentence Audio` | 原有 `[sound:…]` 原样保留 + `[sound:core6000-<noteId>-sentence-2.mp3]` |

**只写「真的坏了」的字段**（契约 §5.4）。渲染时顺手的空白/外壳归一化不算缺陷，不算要写：

* **单例句的卡（要造新句）**：上面五个字段都写（新句、它的振假名/译文、② 讲解、新句音频）。
* **本来就是两句话的卡**：第二句是卡里既有的，其余四个字段**没有新内容可写**，
  所以**只写 `Sentence HTML`**（把缺/坏的振假名补上），
  `Sentence`、`Sentence Translation`、`AINote`、`Sentence Audio` **逐字不动** ——
  卡上已有的 ①② 讲解、`<ul><li>` 排版都是原作者的版式，脚本不重排、不套 `<div><div>`。
  演练输出里会直接列出「不写的字段（保持卡上现值，逐字不动）」。

`Word` / `Transliteration` / `Meaning` / `Part of Speech` / `Index` / 音调字段**一个字都不动**，
也不加标签、不动 deck 与 `due`；已有振假名不会被模型重写。
**本来就是两句话的卡不会再补第三句**，也不会重复写同一个 `[sound:]`。
三句以上的卡、以及那四个字段自有别的毛病（音频条数不对、译文全空、AINote 没合并）的卡，
脚本**不代笔**，在报告里列出原因交人工 —— 不会靠「整篇重渲染」假装修好。

---

## 四、九道机械闸门

`gen` 只跑闸门 1–5（拿到模型产出就能判，不合格时带提示重问 `--retries` 次，默认 1 次）；
`apply` 跑 6–9（渲染后才能判）。任何一条不过，**这张卡就不写库**，并写进报告。

| # | 闸门 |
|---|---|
| 1 | 新句必须用上目标词 |
| 2 | 新句 6–45 字，且 ≠ 原句（**闸门 1/2 只管模型新造的句子**，已有两句的卡跳过）|
| 3 | 新句振假名去 `<rt>`、剥标签后与正文逐字一致 |
| 4 | 新句有汉字就必须有 `<ruby>`，每个 `<ruby>` 都有 `<rt>`，基底不得只含假名（敬语接头辞不包进基底）|
| 5 | 需要补原句振假名时，同样要过 3/4 |
| 6 | `Sentence`、`Sentence HTML` 恰好 2 块；`Sentence Audio` 恰好 2 个 `[sound:` |
| 7 | `AINote` 含 `中文翻译` + `核心词汇` + `语法要点`，且含 `①` 与 `②` |
| 8 | 原卡每个板块正文的前 12 字必须仍出现在新 `AINote` 里（防静默丢原文）|
| 9 | 这次**要写**的字段任何一个渲染后为空 ⇒ 拒绝（不写的字段保持卡上现值）|

修不了的卡（3 句以上，全库 1 张；提示词还不支持的 `not-merged`）只在报告里列出原因，不动它；已有两句但第二句缺振假名的卡**能修**（模型交回 `sentence2_ruby`，**闸门 5b** 验，不合格就拒绝）。

**闸门是字段级的**：6–9 只检查这次**真的要写**的字段（见第三节）。已有两句话、只补振假名的卡
不写 `AINote`，所以闸门 7/8 对它不适用 —— 拿卡上**旧** AINote 的形状去卡一张本来能修好的卡是误伤。
**闸门 5b 与写不写无关，永远照查**（严格程度未变）。

`gen` 另有两条**警告**（只进 `gen/<noteId>_out.json` 的 `gate.warnings`、`meta` 与报告，
**不拦卡**）：

| 警告 | 含义 |
|---|---|
| `target_reading_mismatch` | 新句里出现了目标词，而它在 `new_sentence_ruby` 里注的读音和卡上 `Transliteration` 不一致（同一张卡里出现了第二种读音）。抽不出读音就不报，宁可漏报 |
| `target_gloss_missing` | `new_word_gloss` 里没有目标词那一行 → ② 的义项行只能用卡上 `Meaning` 兜底，看不出新句实际用的义项 |

---

## 五、断点续跑、幂等与安全约定

- **每张卡一个产出文件**：`data/core6000/gen/<noteId>_out.json`（闸门 1–5 通过的才算数）。
  中断（Ctrl+C / 断电）后**直接重跑 `gen`**，已完成的自动跳过；`--restart` 才整张重生成。
- **already_ok**：已经有合规「② + 音频」的卡重跑报 `already_ok` 跳过，**绝不重复追加第二句**；
  `--force` 才重做。
- `scan` / `status` **只读**，不调模型、不写库；`tts` 只写本地磁盘，也不碰 Anki。

| 动作 | 默认 | 加参数 |
|---|---|---|
| `apply` | **演练**：打印**要写字段**的前后对照 + 「不写的字段（保持卡上现值，逐字不动）」+ `Sentence HTML`/`AINote` 预览，不写 Anki | `--commit` 真写 |
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

| 路径 | 内容 |
|---|---|
| `data/core6000/state.json` | 每张卡的状态（句块数 / 版式 / 缺什么 / 已合规）|
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

## 七、演练输出是唯一的人看闸门（2026-10-06 起不再要求听音频）

**机械闸门查不出"读得对不对"**：edge-TTS 同一文本两次合成的字节本来就不同，
mp3 里也查不到它实际读的文本。但 **2026-10-06 用户决定：不再就音频可用性做确认**——
`apply` 演练输出没问题就直接 `--commit`；事后发现读音/断句不对，用 `revert --commit` 回退
（脚本只报字节数与时长估算；想抽听就去 `output/audio/core6000/` 听）。

下面三项机械闸门同样拦不住，只能靠人看演练输出：

1. **新句可能是原句的"换皮"**——本地模型常只换主语/时间/地点，甚至照用原句的句型
   （实测：`どうせ` 卡的 `Sentence` 是「どうせ間に合わないならゆっくり行こう。」，
   新句又写成「どうせ食べるなら、好きなものを選ぼう。」）。规范要求换语境/语体/句型，
   但**没有任何机械闸门查得出换皮**（脚本也不会为它重问），`contrast` 里自己写「两者都用了
   同一个句型」就是这种信号。
   → 演练时盯着 `new_sentence` 看；不合意就 `gen --restart --words "<那个词>"` 重生成，
   或人工改 `<noteId>_out.json` 后重跑 `apply`。
2. **多汉字词可能被逐字标 ruby**（`<ruby>場<rt>ば</rt></ruby><ruby>所<rt>しょ</rt></ruby>`）——
   每个 `<ruby>` 都合规，闸门过得去，但不符合本 deck「一词一 ruby」（`<ruby>場所<rt>ばしょ</rt></ruby>`）
   的风格。→ 演练时看一眼 `Sentence HTML`（漏标生僻汉字同理）。
3. **义项/读音的一致性只有警告，没有闸门**：模型可能用别的义项而不在 ② 写明，或给目标词注
   第二种读音。`gen` 的 `target_reading_mismatch` / `target_gloss_missing` 警告只是提示；
   **演练时对着卡上 `Meaning` / `Transliteration` 看一眼 ② 的目标词那一行**。

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
| 模型输出非法 JSON / 被长度截断 | `gen` 会带提示重问（`--retries`，默认 1 次）；仍不行就报错，原因留在 `gen/<noteId>_meta.json`，重跑 `gen` 即可 |
| `--per-batch` 直接报错 | 它**只接受 1**（>1 会打印说明后退出）。要省时间请缩小选择器范围 |
| 卡被拦下怎么办 | 看 `data/core6000/report_<日期>.md` 的原因列：`multi-sentence`（3 句以上，人工处理）、`not-merged`（提示词还不支持 ①）、`already_ok`（已合规，不用管）|
| `tts` 报「缺模型产出」 | 那几张没跑成 `gen`（或闸门没过）→ 先 `gen` 再 `tts` |
| 选中的卡「没有待做的」 | 都 already_ok 或修不了 → 用 `scan --words "…"` 确认 |

**退路**：`gen` / `tts` 只写 `data/` 与 `output/`，不碰 Anki；`apply --commit` 写入前有 `backup_<时间戳>.json`，最坏情况 `revert --commit` 还原。

