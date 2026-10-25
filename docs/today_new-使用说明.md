# 今日新卡 → 每日讲义（`today_new.py` 使用说明）

> 状态：active ｜ 最后核实：2026-10-25

**一句话**：每天早上学新卡**之前**，把「今日新卡」取出来，交给本地模型逐张写讲解，合并成一份带振假名的 Markdown 讲义。

**铁律**：这条链路**只读 Anki，从不写库**；唯一会写的目录是 `output/daily/`。做坏了删文件重跑即可。

**词典口径（2026-10-25 起）**：JMdict **只在 `plan` 里查一次**，结果（读音/词性/义项/语域）
挂到每张词汇卡的 `dict` 字段，并落盘 `lessons/dict_<日期>.json`；`gen` / `merge` / `apply`
**只读这份结果，不再打开词典库**。缓存按「日期 + 卡片指纹 + 词典版本 + 缓存版本」校验，
任一项不符才自动重查一次（`--refresh-dict` 强制重查）。

---

## 0. 最短路径（照这个跑，别自己发明流程）

```powershell
$WS = "<工作区根>"
$PY = "python"
$TN = "$WS\code\execution\today_new.py"

& $PY $TN stats      # ① 有卡才继续
& $PY $TN plan       # ② 取卡 + 预取 JMdict（事实挂到每张词汇卡；之后不再查库）
& $PY $TN check      # ③ 复核词典（默认复用预取结果；--refresh-dict 才重查）
& $PY $TN gen        # ④ 直连本地模型 → 闸门 → 写讲义（模型输入自带 dict 事实）
```

**四个检查点**（不满足就停或重跑 `gen`，不要改取卡口径）：

1. `stats` 里「新卡池」列至少一个非 0——全 0 说明今天没有新卡，收工。
2. `plan` 末行是「合计 N 张卡 / M 条讲解」且 N > 0；否则队列为空、不落盘。
   同时 `dict_<日期>.json` 应存在，`cards_<日期>.json` 的词汇卡应带 `dict` 字段。
3. `gen` 末行是 `merge：讲义已生成 → …\lesson_<日期>.md`；
   若看到「未通过闸门」，按 stderr 点名的 noteId 重跑 `gen`（只补缺的请求）。
4. `output\daily\lesson_latest.md` 存在且非空。

**`check` 的退出码就是结论**：`0` 全部对上 / `1` 有硬错（读音不在 JMdict 读音表）/
`2` 只有建议/提示 / `3` 词典不可用。它只读 Anki、不写库、不写讲义（只写 `dict_<日期>.json`）；
别名 `dict` 等价。默认复用当天预取结果，不查库。

---

## 1. 前置条件（两条缺一不可）

1. **Anki 开着**：AnkiConnect 在 `127.0.0.1:8765`。
2. **本地模型服务起着**：`http://127.0.0.1:8080/v1`（NInfer，脚本打 `/v1/responses`）。

端点相关：

```powershell
& $PY $TN models     # 列可用模型 + 是否已加载 + 验 api key
```

- api key 查找顺序（找到第一个就用）：`--api-key` → `$env:DSH_LOCAL_LLM_API_KEY` → `~/.dsh/local-llm.json`（全局正本；工作区 `.dsh/local-llm.json` 可选覆盖）。NInfer 默认不校验 key。
- `models` 里配置的模型若显示「已加载 = False」，用 `--model <已加载的模型 id>` 临时覆盖；**不要改配置文件**。
- key 只放 `~/.dsh/local-llm.json`（或环境变量），不要写进脚本或文档。

---

## 2. 「今天的新卡」到底怎么算（最容易误解，先读这段）

- **学习单元 = deck + 笔记模型**，共 5 个：

| # | 单元（deck） | 笔记模型 | 上限来源 | 排序 | 调模型？ |
|---|---|---|---|---|---|
| 1 | `0-词汇::2-考级词汇` | `eggrolls-JLPT10k-v3.5` | 实读 `deckConfig` | `due`（队列位置） | 是 |
| 2 | `0-词汇::1-高频日语单词 6000` | `Japanese Vocabulary` | 实读 `deckConfig` | `due` | 是 |
| 3 | `0-词汇::0-素材生词` | `Japanese Vocabulary` | 实读 `deckConfig` | `due` | 是 |
| 4 | `1-语法`（整棵子树 = 1 个单元） | `どんなときどう使う日本語表現文型Note` | 实读（父 deck） | 牌组树 + 树内 `due` | 是（子 deck 名以「例句」结尾的卡只轻量呈现） |
| 5 | `2-例句` | `Basic` | 实读 `deckConfig` | `due` | 否（卡自带 AINote/CNote） |

- 查询串固定为 `deck:"<单元 deck>" is:new -is:suspended -is:buried`，有模型就再加 `note:"<模型>"`。
- **上限优先级**：`--limit` > `PER_DECK_LIMIT` > `getDeckConfig → new.perDay`（实读）> 代码里的 `per_day` 兜底。
  `stats` 的「上限来源」一列会写明这次用的是哪一档。
- **只取今天队列里的前 N 张，不是整个 deck**。素材生词有几千张新卡，每天也只取 `new.perDay` 张。
- **卡数 ≠ 讲解条数**：同一笔记的多张卡（语法例句模板 Card 02–05）只出 1 条讲解；讲义表头两个数都会打印。
- **语法整棵树算一个单元**：每棵子 deck 各按自己的日上限出卡，再由父 deck 上限截断——这样才和 Anki 首页显示的数字一致。
- 词汇/例句单元按 `card.due`（= Anki 里的队列位置）取卡，所以**讲义顺序 = 当天实际学习顺序**。
- 不按「AINote 非空」跳过卡（core6000 与素材生词的讲解就是每天现讲的，不是「已讲过」）。

---

## 3. 生成：直连本地模型（不派子代理）

- 规范本体 `code\execution\lesson_local_prompt.md` 作为 **instructions**，每个请求原样发送一次；每张卡的 JSON 作为 `input`。
- **词汇卡的 `input` 自带 `dict` 字段**：`plan` 阶段查好的 JMdict 事实（`readings` / `entries[].headword` / `pos` / `senses[].glosses` / `tags` / `applies` / `info`）。
  模型按它定读音与义项，不再自己猜；`gen` / `merge` 不会再去查词典。语法卡与例句卡没有 `dict`。
- 默认 `--per-batch 1`：输出最短、失败面最小、断点续跑最细（NInfer 按精确前缀复用缓存，调大只省重复前缀，但更容易截断）。
- 模型侧：`max_output_tokens = 4096`、关思考链（`reasoning.effort = none`）；**不发 `text.format`**（NInfer 不支持结构化输出，JSON 靠提示词 + 解析重试）。
- 每个请求的产出单独落盘 `lessons\cards\NN_out.json` —— 这是**断点续跑的最小单位**。
- 自动返工（都在 `gen` 里，不用干预）：

| 情况 | 处理 |
|---|---|
| 非法 JSON / 漏卡 / 被截断 | 带提示重问，并按卡降级切批（最小 1 张） |
| 例句没用上目标词 | 点名重问；最终仍不合格**只报告**，不拦讲义 |
| 端点 5xx / 429 / 连不上 | 指数退避重试 3 次 |
| 端点 400 / 401 / 403 / 404 | 直接报错，不重试 |

---

## 4. 断点续跑与局部返工

| 想做什么 | 命令 |
|---|---|
| 中断后接着做 | `gen`（卡集对得上的请求自动跳过） |
| 只重来某几张 | `gen --only-words "あまり,しかも" --restart` |
| 全部重来 | `gen --restart` |
| 只重新合并（手工改过 `NN_out.json`） | `merge` |
| 加一句今日总览 | `merge --intro "今天这批以接续词为主"` |

- `--only-words` 会**沿用原请求编号**，不动别人的 `NN_out.json`；但前提是 `split_<日期>.json` 里的卡集指纹对得上。
  改了 `--per-batch` 或卡集后请整批重跑，不要硬用 `--only-words`。
- 隔天重跑：先 `plan`（会自动清掉编号超出的旧 `NN_*.json`），再 `gen`。

---

## 5. 闸门（在 `merge` 里：硬错不写讲义，内容问题只标注）

**硬闸门：不过就不写讲义。**

| 检查 | 不通过时 |
|---|---|
| `entries` 逐张覆盖、不多不少 | **不写讲义**，点名缺哪几张卡的 noteId |
| `teach` 非空 | **不写讲义** |
| `date` 与当天一致 | **不写讲义** |
| 正文无 `{{占位符}}`、词形都出现 | **不写讲义** |

**内容层：只标注 + 报告，不拦讲义**（2026-10-24 起）。讲义正文里就地打 `⚠️`，
stderr 末尾再集中报一次（`check_quality`）：

| 检查 | 讲义里的表现 |
|---|---|
| 词形/读音对不上（`こ` / `あそこ`） | 读音显示 `—`，词条下 `⚠️ 卡片读音字段写…` |
| 语法接续是脏数据（`動どう 詞しのＮ`） | 接续显示 `—`，并提示补跑 `gen` |
| 讲解机械错（`大约…左右`、`比「X」更常用`、句子没写完、例句没用上目标词） | 不拦；stderr 点名 |
| 例句卡 AINote 错（核心词不在句中 / 要点没写完 / 觉得+一定） | 例句卡下 `⚠️` 行 |
| 同词形平/片假名重复、词性标错 | 直接合并/校正，并在文末「词性说明」交代 |

**JMdict 词典层（2026-10-25 起：一次预取，之后不查库）**

拿 `jmdict-lookup` 技能那把词典（`data\dict\jmdictpy\jmdict.db`）当**事实来源**：

1. `plan`（或手动 `check` / `dict`）把它**查一遍**：核验词形/读音/词性，并把义项、语域、
   适用限制整理成事实，挂到每张词汇卡的 `dict` 字段；明细落盘 `lessons/dict_<日期>.json`。
2. `gen` 把这些事实随卡发进模型输入；`merge` / `apply` 直接读同一份结果做纠错渲染。
   **三者都不再打开词典库**（stderr 会打印「📖 词典：复用 …（未查库）」）。
3. 缓存按「日期 + 卡片指纹（id/词形/读音/词性）+ 词典版本（`version.json` 的 tag）+ 缓存版本」校验；
   任一项不符才自动重查一次并写回。旧格式（无 `meta`）自动判失效。
4. `--refresh-dict` 强制重查；`--no-dict` 整层跳过（不预取、不带 `dict`、不做纠错）。

语法卡（句型不是词典词条）与例句卡不参与；词典能证伪的只有下面这几项：

| 词典判定 | 严重度 | 讲义 / 报告里的处理 |
|---|---|---|
| 读音不在该词形的读音表（`こ`/`あそこ`） | **硬错** | 隐藏读音；报告给出候选读音，读音本身是另一个词条时点明「あそこ＝彼処」 |
| 词性与词典冲突（`あっ` 标副词） | **建议** | 单条词条才自动改（→感叹词）；同形多词条只提示、不擅改 |
| 他动词 / 自动词标反 | **建议** | 讲义不改，报告点名 |
| 词形查不到 / 同形多词条 | **提示** | 拟声、口语、专有名词常见，不判错 |

- 自动改词性只发生在「词形唯一对应一个词条」时；`もん`（者/物/門/問…）这类
  假名同形多词条只提示，句末助词仍由渲染器的硬编码兜底。
- **词典只判词形-读音-词性，并提供义项/语域事实**；释义对不对、多义词取哪条、
  例句自不自然，仍由模型结合卡片自带例句判断。
- 词典不可用（`jmdictpy` 没装 / 库没建）时整层跳过，打印一行原因，不挡讲义；
  不想看这份报告就加 `--no-dict`。
- 明细落盘在 `output\daily\lessons\dict_<日期>.json`（每张卡一条，含词典条目 id 与 `facts`；
  顶层 `meta` 是缓存凭据）。

> 口径：开头「N 张卡 / M 条讲解」和各节小标题、来源表合计都由**同一份分组**派生；
> 同词形的纯假名条目（`うっ`/`ウッ`）合并后，讲解条数会比笔记数少。



---

## 6. 子命令与常用参数

| 命令 | 作用 | 调模型 |
|---|---|---|
| `stats` | 只看库存：各单元新卡池、上限、上限来源 | 否 |
| `plan` | 取今日新卡 + **预取 JMdict 事实** → 落盘 `cards_*.json`（词汇卡带 `dict`）+ `split_*.json` | 否 |
| `check` / `dict` | **预取/复核 JMdict**：词形/读音/词性 + 义项/语域 → `dict_*.json`（默认复用缓存） | 否 |
| `gen` | **生成 → 闸门 → 渲染讲义**（默认结束自动 `merge`） | **是** |
| `merge` | 合并已有 `NN_out.json` → 闸门 → 渲染 | 否 |
| `apply` | 用一整份 `lessons/lesson_*.json` 渲染（人工贴模型那条路） | 否 |
| `models` | 探端点：api key / 模型 id / 是否已加载 | 否 |
| `prompt` | 打印**真正会发给模型的消息**（排查提示词） | 否 |

常用参数：

| 参数 | 用在 | 说明 |
|---|---|---|
| `--dry-run` | `plan` | 只打印取到哪些卡，不落盘 |
| `--limit N` | `plan` / `stats` | 每个单元最多取 N 张（覆盖实读上限） |
| `--only vocab` / `--only grammar` | `plan` | 只取一类卡 |
| `--deck "1-语法"` | `plan` | 只取匹配单元（从头前缀匹配，逗号分隔） |
| `--per-batch N` | `plan` / `gen` | 每请求几张卡（默认 1；`0` = 一次全给） |
| `--only-words "词,词"` | `gen` | 只处理这些卡（词形或 note id） |
| `--restart[=词,词]` | `gen` | 全部 / 只这些词重来 |
| `--model` / `--base-url` / `--api-key` | `gen` / `models` | 临时覆盖端点配置 |
| `--no-json-mode` | `gen` | 端点不认 JSON 模式时用 |
| `--no-stream` | `gen` | 关流式（默认流式） |
| `--retries-per-card N` | `gen` | 每张卡最多重生成几次（默认 2） |
| `--system-prompt <路径>` | `gen` / `prompt` | 换一份教学规范 |
| `--date 2026-10-21` | 全部 | 把这天当「今天」（文件名/manifest 用） |
| `--no-dict` | `plan` / `check` / `gen` / `merge` / `apply` / `prompt` | 跳过 JMdict 词典层（不预取、不带事实、不做纠错） |
| `--refresh-dict` | 同上 | 忽略已预取结果，强制重新查一遍词典 |
| `--quiet` | 全部 | 不打印「读取卡片数据…」与首字延迟 |

---

## 7. 产出文件

| 文件 | 内容 |
|---|---|
| `output\daily\cards_<日期>.json` | 当天这批卡的原始数据（manifest，含 query、上限来源、每张卡字段；**词汇卡带 `dict` 词典事实**） |
| `output\daily\cards_latest.json` | 同上的最近一次副本 |
| `output\daily\lessons\split_<日期>.json` | 请求清单（请求号、卡 id、路径、指纹、模型名） |
| `output\daily\lessons\dict_<日期>.json` | **JMdict 预取结果**：每张词汇卡的读音候选/词性/问题清单/`facts`，顶层 `meta`（指纹/词典版本/缓存版本）是复用凭据 |
| `output\daily\lessons\cards\NN_in.json` | 第 NN 个请求**实际发出去的卡片数据**（含 `dict`，可单独交接给子代理/别的模型） |
| `output\daily\lessons\cards\NN_out.json` | 第 NN 个请求的产出（**断点续跑的最小单位**） |
| `output\daily\lessons\metrics_<日期>.json` | **token 账本**（每次请求的 prompt / completion / 耗时；多次跑会累加） |
| `output\daily\lessons\lesson_<日期>.json` | 合并后的整份 lesson JSON（可手工修） |
| `output\daily\lesson_<日期>.md` | **最终讲义** |
| `output\daily\lesson_latest.md` | 最近一次的副本，每天早上读这份 |

---

## 8. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| `连不上 AnkiConnect` | Anki 没开或 AnkiConnect 插件没启用 |
| `今天没有可讲的新卡…不落盘` | 新卡都学完了。用 `stats` 确认 |
| `连不上端点 http://127.0.0.1:8080/v1` | 本地推理服务没起。起 NInfer 后 `models` 再试 |
| `端点返回 HTTP 401/403` | api key 不对或没提供。检查 `~/.dsh/local-llm.json`（NInfer 默认不校验） |
| `端点返回 HTTP 404` | `base_url` / 模型名 / 路由不对（脚本打 `<base_url>/responses`） |
| `端点返回 HTTP 400` | 若是 `No input provided` → 发成了 chat 形状；若 JSON 模式不认 → 加 `--no-json-mode` |
| `配置的模型不在列表里` | 用 `--model` 换一个已加载的 |
| `merge` 报「还有 N 个请求没有产出」 | 那几个请求没跑成。**重跑 `gen` 就只补它们** |
| `merge` 报「有 N 张卡没有讲解」 | 某张卡最终没拿到讲解。`gen --only-words "<那个词>" --restart` |
| `merge` 报「多出 N 个不属于今天的 id」 | 隔天剩下的 `NN_out.json`。`plan` 会自动清，手动删也行 |
| `lesson 的 date=… 不一致` | 模型写错日期。改 `NN_out.json` 的 `date` 再 `merge` |
| `⚠️ 有 N 条例句没用上目标词` | 模型造了不含目标词的例句。`gen --only-words "<词>" --restart`；或手改 `NN_out.json` 的 `examples` 再 `merge` |
| `⚠️ 讲义里有 N 条内容问题` | 内容层问题清单（含上面这类）。讲解问题 `gen --only-words … --restart`；卡片数据问题回 Anki 改字段 |
| 讲义里读音显示 `—`、带 `⚠️ 卡片读音字段` | 卡片的 `Word` 与 `Transliteration` 对不上（如 `こ` / `あそこ`）。**改 Anki 字段**；`check` 会报硬错并给出词典读音，脚本只隐藏不写库 |
| `📖 词典：复用 …（未查库）` | 正常：`gen`/`merge` 在用 `plan` 的预取结果，没有第二次查库 |
| `📖 词典：… → 已预取 N 张词汇卡` | 缓存缺失/失效，自动重查了一次并写回 `dict_<日期>.json`；括号里是原因（卡片变了/版本变了/`--refresh-dict`） |
| `📖 JMdict 不可用：…` | `jmdictpy` 没装或词典库没建。装法见 `jmdict-lookup` 技能（`install_workspace_wheels.py jmdictpy` → `jmdict.py build`）；不影响讲义 |
| `check` 退出码 1 / 2 | 1 = 有硬错（读音），2 = 只有建议/提示。按报告回 Anki 改字段，或 `--no-dict` 跳过 |
| 讲义里词性被改写成「感叹词／终助词」 | 卡片 `Part of Speech` 标错了。讲义按语言事实显示，建议回改卡片 |
| 语法接续显示 `—` | 该卡的接续字段是脏数据（汉字夹注音）。`gen --only-words "<句型>" --restart` 让模型重写 `structure` |

---

## 9. 与其它链路的关系

- 与 `pipeline.py`（一集素材 → 例句卡）共用同一套 deck 结构；改 deck 时两处都要同步
  （`today_new.py` 的 `DECKS` 与 `pipeline.py` 的 `CFG`）。
- **素材生词**由 `mine.py` 挖掘入库（`0-素材生词`，与 core6000 同模板）；本链路只负责把
  它**今天队列里的那部分**讲成讲义。卡片质量取决于挖掘结果；不想要某张卡就在 Anki 里 suspend/删除，不要改脚本口径。
- 弱项分析用 `code\analysis\today_weak.py`，不在这条链路里。
