# 日语例句卡生成 · Agent 执行指令（调度与验收）

> 状态：active ｜ 最后核实：2026-11-09

**这是什么**：阶段二的执行规范 —— 输入/输出契约、写库方式、查重口径、闸门与汇报。
**讲解与振假名的内容规则不在这里**：正本已抽到 [`code/execution/card_rules.md`](../code/execution/card_rules.md)
（2026-11-08，git dd01388），阶段二 / 按张生成（`pipeline.py`、`cards.py gen`）与 core6000 补例句共用同一份；
装载器是 `code/common/card_prompt.py`。**改讲解/振假名规则只改正本，不要把规则抄回任何外壳或本文。**
**什么时候读**：要给例句卡生成这两个字段时 —— `cards.py gen` 的默认路径用它当规范；
本地模型不可用、要派子代理时也读它（`pipeline.py split --print-prompts` 打印的子代理提示词点名这份文档，
**子代理同时必须读正本 `code/execution/card_rules.md`**）。

> **相关文档**：[pipeline-guide.md](pipeline-guide.md)（阶段一/三/四的操作手册）、
> [mine-agent-instruction.md](mine-agent-instruction.md)（阶段四：从这些例句里挖**生词卡**的规范）。
> 本文件只管**整句**的讲解与振假名；挖单词是另一份规范、另一套字段。

---

## 0. 角色

你是一名精通日语的语言学教授，同时是一个能操作 Anki 的 agent。你自己取卡、自己生成、自己写库、自己自检，
不要求人类复制粘贴。内容规则（讲什么、怎么标 ruby）以正本 `card_rules.md` 为准。

## 1. 输入契约

从 Anki 读取，**只读不改**以下字段：

| 字段 | 用途 |
|---|---|
| `Sentence` | 主输入。待讲解的日语句子。可能含 `<br>`（字幕两行） |
| `Source` | 出处（文件名 + 时间码），用于判断语域（动画口语 / 新闻报道 / 纪录片旁白） |
| `Word` | 若已有值，说明该卡已指定重点词，**核心词汇必须以它为首条** |
| `Image` / `Sentence Audio` / `URL` | 仅供理解语境，不要写入 |

## 2. 输出契约与写库

只写两个字段，其余字段一律不动：

| 模型输出的键 | 写入字段名（注意大小写与空格） |
|---|---|
| `AINote` | `AINote` |
| `SentenceHTML` | `Sentence HTML` |

两条现行路径，**没有「把内容打印回聊天让人复制」的模式**（旧的分块文本格式已退场）：

1. **原子入口（默认）**：`cards.py gen --commit` 直连本地模型并写库；
   或现成 JSON 走 `cards.py write --file`，形状与 `gen --out` 相同：
   `[{"noteId": 123, "AINote": "<p>…</p>", "SentenceHTML": "<ruby>…</ruby>"}]`。
   写库只传这两个键（`writeback` / `updateNoteFields`），绝不整字段覆盖，绝不传其它字段；写完回读。
2. **子代理批处理（本地模型不可用时的备用路径）**：读 `data/pipeline/gen/input_NN.json`
   （每项 `{noteId, sentence, word, source}`），把结果写入同目录 `output_NN.json`：
   JSON 数组，每项 `{noteId, sentence(原样回填), AINote, SentenceHTML}`，覆盖每一条、数量与顺序一致。
   **禁止调用 AnkiConnect、禁止写库、禁止改输入文件**——校验与入库由 `pipeline.py write` 统一收口。

## 3. 内容规则 = 正本 `card_rules.md`

翻译、核心词汇、语法要点、动词变形解析、语境与表达风格的写法，振假名（ruby）全部规则
（送假名在 `<rt>` 外、敬语接头辞、熟字训、逐字一致……），以及标签白名单 / 无 LaTeX / 无半角引号等铁律，
**一律以 [`code/execution/card_rules.md`](../code/execution/card_rules.md) 为准**，本文不再复述。

历史残渣的只读审计入口（不是生成规则）：早期批次出过 `$\rightarrow$` 的 `\r`、`$\text{…}$` 的 `\t`
被转义吃掉的残骸，已批量清理；体检 `code/oneshot/verify_no_residue.py`（只读），
修复 `fix_bad_arrow.py` / `fix_text_wrap.py`（默认演练，`--commit` 才写库）。

## 4. 生成方式（固定的是方法，不是流程）

**没有规定的批次、顺序或流水线。** 一次处理一张、三张还是三十张，由调用方决定；
本规范只固定「输入什么、输出什么、怎么判合格」。

1. **取卡**：指定 noteId / 查询 / 文件，读 `Sentence` / `Word` / `Source` 三个字段。
   读什么由调用方点名，不要求先切批。
2. **产出两个字段值**：
   - 原子入口：`python code/execution/cards.py gen`（本地模型直连）或
     `cards.py write --file`（现成 JSON，同一套 repair + 闸门）。
     `Sentence HTML` 由 `ruby_engine` 拿**原始 `Sentence` 当骨架**重渲染，不依赖模型一次写对。
   - 整集批量：`pipeline.py split/gen/write` 或 `cli.py episode` 只是**调用方**；
     它们复用同一份提示词（规则正本 `card_rules.md`，由 `pipeline.LOCAL_INSTRUCTION` 经
     `card_prompt.pipeline_instruction()` 拼出）与同一套 repair/闸门，不构成本规范的额外步骤。
3. **写库**：只含 `AINote` 与 `Sentence HTML` 两个键；写完回读。
4. **报告**：输出 `成功 N / 跳过 M / 待人工 K`，并列出待人工的 noteId 与原因。

**幂等**：默认只处理 `AINote` 为空的卡；`AINote` 已有内容则跳过，除非人类明确说"覆盖"。
原子入口 `cards.py` 更保守：任一目标字段已非空就跳过（并打印是哪个字段），`--overwrite` 才重做。

## 5. 去重口径（查重用 `Sentence`，不用 `AINote`）

判断"这句例句是不是已经有过卡"时，**唯一依据是 `Sentence` 字段**，与 `AINote` 是否为空、内容写了什么**无关**。

- 比对前归一化：NFKC 统一全角/半角 → 整块删 `<rt>…</rt>` → 剥其余标签 → 去掉全部空白（含全角空格 `　`）。**标点保留**，`ありがとう` 与 `ありがとう！` 不算重复。
- 参照集合是 **本 deck（乃至全库）所有卡的 `Sentence`**，包含 `AINote` 尚为空的卡。
- 同一批里两张卡 `Sentence` 相同，同样算重复。
- ⚠️ 反面写法：用 `AINote:_*` 拉一批"已处理的卡"当参照系去查重。这会漏掉 `AINote` 还没生成的卡（未跑的批次、被 suspend 的弃用卡），把重复例句放进队列。

`AINote` 只有两个用途，都与查重无关：① 幂等判据（这张卡跑没跑过 prompt）；② 待办队列查询（`AINote:` / `AINote:_*` 见第 8 节）。

## 6. 异常处理与人工标记

判据的分界线是**残余部分还能不能讲**，不是"句子完不完整"。

| 情况 | 处理 |
|---|---|
| 只有**真正无法给出可靠讲解**时才算异常：文字明显错误或乱码、关键读音无法确定且无法回避、整句没有可解释的语义单位 | `AINote` 与 `Sentence HTML` **两个字段都留空**，不做任何写入，把 noteId 计入"已跳过"并汇报给人类。这样该卡仍留在"未处理"队列里，人类可以手动处置 |
| 句子被字幕切断、残余部分**仍有可讲内容**（例如结尾停在「って」「のに」「けど」） | **正常生成**，并在「语法要点」末尾注明"主句被字幕省略"。不要标记为异常 |
| 读音不确定 / 词性无法确定 | 按正本规则处理（不猜、该词不加 ruby 并列出；词性省略只写释义） |

> 为什么跳过时两个字段都留空、而不是写一个「待人工处理」标记：留空能让该卡继续被 `AINote:` 这类查询命中，不会被误当成已完成；写标记则会让它从待办队列里消失。
> 若确实要写显式标记（例如交给别人处理），`AINote` 写 `<p><b>待人工处理：</b>原因</p>` 且 `Sentence HTML` 留空——校验器 `check_cards.py` 对这一组合是豁免的。

## 7. 验收：闸门只做一次，且由脚本做

- `cards.py` / `pipeline.py gen` 内部用 `check_cards.py` 机械判一次（结构、标签白名单、逐字一致等）。
  `AINote` 侧不合格**只重问那一轮**；`Sentence HTML` 侧的机械问题**不重问**，
  交给 `ruby_engine.repair` 重渲染。仍不合格的按第 6 节两个字段留空。
- **生成方不要自己跑自检脚本、更不要"跑到 0 不合格"** —— 那是把同一份校验算两遍，
  还会把一批 14 张拖成小时级返工。改不掉的（例如读音确实定不下来）留着、在汇报里列出即可。
- 内容层面的规则（ruby 覆盖是否语义正确、讲解质量）脚本只能查结构；
  可自动化程度与实现见 `code/common/check_cards.py`。输出前的逐张核对清单在正本第十节。

## 8. 批量参数（本副牌组实测可用）

安主题 `0-日本语学习::2-例句`，模型 `Basic`，字段顺序：
`Sentence(0) / Word(1) / Sentence HTML(2) / AINote(3) / Image(4) / Sentence Audio(5) / Source(6) / URL(7)`

> ⚠️ **`Sentence HTML` 会被阶段四复用**（[mine.py](../code/execution/mine.py) 把它原样拷进生词卡的例句字段）。
> 所以这一列不只是"给本卡显示用"：它同时是素材生词卡的例句来源。
> 生成时务必保证它含完整的 `<ruby>` —— 一个没有振假名的 `Sentence HTML` 会让生词卡的例句也失去振假名。

```
# 未跑过 prompt 的卡（本集全部）
tag:动画::<作品名>::<季>::第NN集 AINote:

# 全 deck 范围内字段为空的卡
deck:0-日本语学习::2-例句 AINote:

# 含空格的字段名要连冒号一起加引号
deck:0-日本语学习::2-例句 "Sentence HTML:"

# 反查：非空（已处理）
deck:0-日本语学习::2-例句 AINote:_*
```

## 9. 两个入口的关系（规则正本：`code/execution/card_rules.md`）

阶段二与 core6000 补例句**共用同一份规则正本**（2026-11-08 起）。
两个入口只在「输入是什么、输出成什么键」上有外壳差异：

| 入口 | 外壳（规则正本在此展开） | 模型输出 |
|---|---|---|
| 阶段二 / 按张：`pipeline.py` 的 `LOCAL_INSTRUCTION`（`cards.py gen` 直接复用） | `code/common/card_prompt.py` 里的 pipeline 外壳 | `{"cards":[{"noteId":…,"AINote":…,"SentenceHTML":…}]}` |
| core6000 补第二条例句 / 重写整张卡：`core6000_example.py gen`、`note_regen.py gen` | `code/execution/core6000/core6000_example_prompt.md`（`{{RULES}}` 处展开正本） | `{"entries":{…}}` 的 15 个结构化键（②/通用 11 + ① 4），由脚本合成 ①② |

**改讲解/振假名规则只改 `card_rules.md`**：两个入口加载时自动带上，不要把规则再抄回外壳或本文。

本地端点没起时：

- **按张**：我（agent）按正本写好 `[{"noteId":…,"AINote":"…","SentenceHTML":"…"}]`，再跑
  `cards.py write --file …`，由同一套 repair + 闸门收口；
- **整集**：`pipeline.py split --print-prompts` 打印子代理提示词（会花云端 token），
  子代理按第 2 节路径 ② 读写 `input_NN.json` / `output_NN.json`。
