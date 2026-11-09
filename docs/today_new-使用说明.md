# 今天学习生词 → 每日讲义（`today_new.py` 使用说明）

> 状态：active ｜ 最后核实：2026-11-09

**一句话**：每天早上学今天这批生词**之前**，把 tag `今天学习生词` 里的词取出来，交给本地模型逐张写讲解，合并成一份带振假名的 Markdown 讲义。

**选词不在这里**：哪天学哪些词由 `jp-anki-today-new`（`code\tools\today_new_words.py`）决定——
从当天字幕挑 N 个词、打 tag、全量替换；排序以本地模型精排为主，公式只兜底；没有 JAR 排名的词不进名单但登记
`data\daily_new\unranked.json`（JAR >30000 不再挡）。**这些口径的正本是技能 `jp-anki-today-new`，本文不复述。**
本脚本**只认这个 tag**：tag 里有词就讲，没有就什么都不生成。

**铁律**：这条链路**只读 Anki，从不写库**；唯一会写的目录是 `output/daily/`。做坏了删文件重跑即可。

**词典口径**：JMdict **只在 `plan` 里查一次**，事实（读音/词性/义项/语域）挂到每张词汇卡的 `dict` 字段并落盘
`lessons/dict_<日期>.json`；`gen` / `merge` / `apply` 只读这份结果，不再打开词典库（`--refresh-dict` 强制重查）。

**讲义流程与判定口径的正本是技能 `jp-anki-daily-lesson`**：闸门分两层、验收清单、已知卡片脏数据都在那里，本文只留命令与产出。

---

## 0. 最短路径（照这个跑，别自己发明流程）

```powershell
$WS = "<工作区根>"
$PY = "python"
$TN = "$WS\code\execution\today_new.py"

# 0) 选词（另一条日常任务）：从当天字幕挑 N 个词，打 tag「今天学习生词」
& $PY "$WS\code\tools\today_new_words.py" "字幕.srt" --n 30 --commit

& $PY $TN stats      # ① 看 tag 今天命中几个词；0 就收工
& $PY $TN plan       # ② 按 tag 取词 + 预取 JMdict（事实挂到每张词汇卡；之后不再查库）
& $PY $TN check      # ③ 复核词典（默认复用预取结果；--refresh-dict 才重查）
& $PY $TN gen        # ④ 直连本地模型 → 闸门 → 写讲义（默认结束自动 merge）
```

**四个检查点**（不满足就停或重跑 `gen`，不要改取词口径）：

1. `stats` 的「tag 命中」合计 > 0；全 0 说明今天还没选词，先去 `jp-anki-today-new`，不要拿新卡队列补。
2. `plan` 末行是「合计 N 个词」且 N > 0；同时 `dict_<日期>.json` 应存在，`cards_<日期>.json` 的词汇卡带 `dict` 字段。
3. `gen` 末行是 `merge：讲义已生成 → …\lesson_<日期>.md`；看到「未通过闸门」就按 stderr 点名的 noteId 重跑 `gen`。
4. `output\daily\lesson_latest.md` 存在且非空。

**`check`（别名 `dict`）的退出码就是结论**：`0` 全部对上 / `1` 有硬错（读音不在 JMdict 读音表）/
`2` 只有建议或提示 / `3` 词典不可用。它只读 Anki、不写库、不写讲义（只写 `dict_<日期>.json`）。

---

## 1. 前置条件与端点（两条缺一不可）

1. **Anki 开着**：AnkiConnect 在 `127.0.0.1:8765`。
2. **本地模型服务起着**：`http://127.0.0.1:8080/v1`（NInfer，脚本打 `/v1/responses`）。

```powershell
& $PY $TN models     # 列可用模型 + 是否已加载 + 验 api key
```

- api key 查找顺序（找到第一个就用）：`--api-key` → `$env:DSH_LOCAL_LLM_API_KEY` → `~/.dsh/local-llm.json`
  （全局正本；工作区 `.dsh/local-llm.json` 可选覆盖）。NInfer 默认不校验 key。**key 不要写进脚本或文档。**
- **模型默认沿用端点当时在用的那个**（配置里 `pin_active: true`）：`gen` 发请求前先问一次 `/props` 把 model 对齐过去——
  讲义是卡片类任务，同一批词要用同一个模型讲完。`models` 报「配置的模型不在列表里」通常什么都不用改。
- **不要为了换模型给 `--model`**（那等于绕过对齐中途换模型，同一天的讲义会混两种风格）；真要换端点用
  `--profile ninfer|strata`（或 `$env:DSH_LOCAL_LLM_PROFILE`），那是用户决定的事。临时关掉对齐：`$env:DSH_LOCAL_LLM_PIN='0'`。

---

## 2. 「今天的词」怎么算（口径正本在 `jp-anki-daily-lesson` §1.3）

**只有一条：全库 tag `今天学习生词` 命中的词汇笔记**（三个词汇卡组各查一次笔记，实现见 `today_new.py::query_for`）。
不按 `is:new`、不按 `new.perDay`、不按 `card.due` 再筛；一个笔记 = 一条讲义条目；不截断、不补位。
顺序读当天 `data\daily_new\<日期>\picked.json` 的 `picked[]`（= 选词顺序），没有这份记录时按「级别 → 牌组 → 词形」兜底。

- **语法 / 例句单元已移出每日讲义**（2026-10-28）：渲染层保留旧分支，`merge --date <旧日期>` 还能渲染旧 manifest；新讲义只有词汇一节。
- **没有 tag 就不生成**：`plan` 落一份空清单并退出 0；`gen` / `merge` / `check` 看到空清单直接跳过。
- **隔天保护**：`gen`/`merge`/`check` 默认只认今天的 `cards_latest.json`，是昨天那份就报错退出（重看旧日期要显式 `--date`）。
- **tag 换批保护**：`gen` 开跑前核对清单里的词是否还带着 tag；中途又跑了 `today-new` 就拒绝拿旧清单生成（`--allow-stale-tag` 可放行）。

想换一批词 / 清空今天的词：走 `jp-anki-today-new`（`--clear --commit` / `--revert --commit`），然后重跑 `plan`。
不要手改讲义、不要手删 tag。

---

## 3. 生成与返工

规范本体 `code\execution\lesson\lesson_local_prompt.md` 作为 **instructions**，每张卡的 JSON（含 `dict` 事实）作为 `input`，
直连 `/v1/responses`；默认 `--per-batch 1`。每个请求的产出单独落盘 `lessons\cards\NN_out.json`——断点续跑的最小单位。
闸门与重试都在脚本里（非法 JSON / 漏卡 / 截断带提示重问；端点 5xx/429 指数退避，401/403/404 直接报错），不用干预。

| 想做什么 | 命令 |
|---|---|
| 中断后接着做 | `gen`（卡集对得上的请求自动跳过） |
| 只重来某几张 | `gen --only-words "あまり,しかも" --restart` |
| 全部重来 | `gen --restart` |
| 只重新合并（手工改过 `NN_out.json`） | `merge` |
| 加一句今日总览 | `merge --intro "今天这批以接续词为主"` |

- `--only-words` 沿用原请求编号，不动别人的 `NN_out.json`；前提是 `split_<日期>.json` 的卡集指纹对得上——改了 `--per-batch` 或卡集就整批重跑。
- 隔天重跑：先 `plan`（自动清掉编号超出的旧 `NN_*.json`），再 `gen`。

**闸门两层**（详见技能 §1.2）：硬错（逐张覆盖 / `teach` 非空 / date 一致 / 无占位符且词形在正文）**不写讲义**并点名 noteId；
内容层问题（读音对不上、讲解机械错、例句没用上目标词）**只标注**——讲义照出，正文就地打 `⚠️`，stderr 末尾集中报一次，报告必须转述。

---

## 4. 子命令与常用参数

| 命令 | 作用 | 调模型 |
|---|---|---|
| `stats` | 只看库存：tag「今天学习生词」在各词汇卡组命中多少条笔记 | 否 |
| `plan` | 按 tag 取今天要讲的词 + **预取 JMdict 事实** → `cards_*.json`（词汇卡带 `dict`）+ `split_*.json`；没有 tag 就落空清单 | 否 |
| `check` / `dict` | **复核 JMdict**：词形/读音/词性 + 义项/语域 → `dict_*.json`（默认复用缓存） | 否 |
| `gen` | **生成 → 闸门 → 渲染讲义**（默认结束自动 `merge`）；空清单直接跳过 | **是** |
| `merge` | 合并已有 `NN_out.json` → 闸门 → 渲染 | 否 |
| `apply` | 用一整份 `lessons/lesson_*.json` 渲染（人工贴模型那条路） | 否 |
| `models` | 探端点：api key / 模型 id / 是否已加载 | 否 |
| `prompt` | 打印**真正会发给模型的消息**（排查提示词） | 否 |

常用参数：

| 参数 | 用在 | 说明 |
|---|---|---|
| `--dry-run` | `plan` | 只打印取到哪些词，不落盘 |
| `--deck "0-素材生词"` | `plan` | 只取匹配的词汇卡组（从头前缀匹配，逗号分隔） |
| `--per-batch N` | `plan` / `gen` | 每请求几张卡（默认 1；`0` = 一次全给） |
| `--only-words "词,词"` | `gen` | 只处理这些卡（词形或 note id） |
| `--restart[=词,词]` | `gen` | 全部 / 只这些词重来 |
| `--allow-stale-tag` | `gen` | 明知 tag 已换批仍照旧清单生成 |
| `--model` / `--base-url` / `--api-key` | `gen` / `models` | 临时覆盖端点配置。**卡片任务别给 `--model`**（绕过模型对齐） |
| `--profile ninfer\|strata` | `gen` / `models` | 用 `~/.dsh/local-llm.json` 里 profiles 的哪一项（也可 `$env:DSH_LOCAL_LLM_PROFILE`）；换端点走这个 |
| `--no-json-mode` / `--no-stream` | `gen` | 端点不认 JSON 模式 / 关流式（默认流式） |
| `--retries-per-card N` | `gen` | 每张卡最多重生成几次（默认 2） |
| `--system-prompt <路径>` | `gen` / `prompt` | 换一份教学规范 |
| `--date 2026-10-21` | 全部 | 把这天当「今天」（文件名/manifest 用） |
| `--no-dict` | `plan` / `check` / `gen` / `merge` / `apply` / `prompt` | 跳过 JMdict 词典层（不预取、不带事实、不做纠错） |
| `--refresh-dict` | 同上 | 忽略已预取结果，强制重新查一遍词典 |
| `--quiet` | 全部 | 不打印「读取卡片数据…」与首字延迟 |

---

## 5. 产出文件

| 文件 | 内容 |
|---|---|
| `output\daily\cards_<日期>.json` | 当天这批词的原始数据（manifest，含 `mode: tag`、`tag`、query、每张卡字段；**词汇卡带 `dict` 词典事实**；没有 tag 时是一份空清单） |
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

## 6. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| `连不上 AnkiConnect` | Anki 没开或 AnkiConnect 插件没启用 |
| `今天没有 tag:「今天学习生词」的词 → 不生成讲义` | 今天还没选词（或 tag 被清空）。先跑 `jp-anki-today-new … --commit` 再 `plan` |
| `卡片数据是 2026-… 的，不是今天（2026-…）` | `cards_latest.json` 是上一天的。重跑 `plan`；要重看旧日期就显式 `--date` |
| `卡片数据里有 N 个词已不在 tag:「今天学习生词」里` | 选完词后 tag 被换批/清空了。重跑 `plan`；确要照旧清单生成就加 `gen --allow-stale-tag` |
| `连不上端点 http://127.0.0.1:8080/v1` | 本地推理服务没起。起 NInfer 后 `models` 再试 |
| `端点返回 HTTP 401/403` | api key 不对或没提供。检查 `~/.dsh/local-llm.json`（NInfer 默认不校验） |
| `端点返回 HTTP 404` | `base_url` / 模型名 / 路由不对（脚本打 `<base_url>/responses`） |
| `端点返回 HTTP 400` | 若是 `No input provided` → 发成了 chat 形状；若 JSON 模式不认 → 加 `--no-json-mode` |
| `配置的模型不在列表里` | **一般不用管**：脚本会自动沿用端点当前在服务的模型。只有显式指定档位时才给 `--model`；换端点用 `--profile` |
| `没探到端点当前在服务的模型（/props 拿不到）` | 端点没暴露 llama.cpp 兼容的 `/props`。按配置里的 model 跑；先 `models` 看一眼，必要时 `--profile` 选对档位 |
| `merge` 报「还有 N 个请求没有产出」 | 那几个请求没跑成。**重跑 `gen` 就只补它们** |
| `merge` 报「有 N 张卡没有讲解」 | 某张卡最终没拿到讲解。`gen --only-words "<那个词>" --restart` |
| `merge` 报「多出 N 个不属于今天的 id」 | 隔天剩下的 `NN_out.json`。`plan` 会自动清，手动删也行 |
| `lesson 的 date=… 不一致` | 模型写错日期。改 `NN_out.json` 的 `date` 再 `merge` |
| `⚠️ 有 N 条例句没用上目标词` | 模型造了不含目标词的例句。`gen --only-words "<词>" --restart`；或手改 `NN_out.json` 的 `examples` 再 `merge` |
| `⚠️ 讲义里有 N 条内容问题` | 内容层问题清单。讲解问题 `gen --only-words … --restart`；卡片数据问题回 Anki 改字段 |
| 讲义里读音显示 `—`、带 `⚠️ 卡片读音字段` | 卡片的 `Word` 与 `Transliteration` 对不上（如 `こ` / `あそこ`）。**改 Anki 字段**；`check` 会报硬错并给出词典读音，脚本只隐藏不写库 |
| `📖 词典：复用 …（未查库）` | 正常：`gen`/`merge` 在用 `plan` 的预取结果，没有第二次查库 |
| `📖 词典：… → 已预取 N 张词汇卡` | 缓存缺失/失效，自动重查了一次并写回；括号里是原因（卡片变了/版本变了/`--refresh-dict`） |
| `📖 JMdict 不可用：…` | `jmdictpy` 没装或词典库没建。装法见 `jmdict-lookup` 技能；不影响讲义 |
| `check` 退出码 1 / 2 | 1 = 有硬错（读音），2 = 只有建议/提示。按报告回 Anki 改字段，或 `--no-dict` 跳过 |
| 讲义里词性被改写成「感叹词／终助词」 | 卡片 `Part of Speech` 标错了。讲义按语言事实显示，建议回改卡片 |
| 讲义里出现 `## 语法` / `## 例句卡` 节 | 渲染的是旧版 manifest（`--date` 指错了）。重跑 `plan` |

---

## 7. 与其它链路的关系

- **选词**：`jp-anki-today-new`（`code\tools\today_new_words.py`）负责挑词、打 tag（全量替换）、待建卡清单
  `data\daily_new\unranked.json`；讲义只消费这个 tag，两条任务各管一半，不要互相兜底。
- **代码在哪**：入口 `code\execution\today_new.py`；讲义的机械判定与渲染已抽到 `code\execution\lesson\`——
  `lesson_text.py`（teach 整形 / 接续清洗 / Markdown 片段）、`lesson_check.py`（词形/读音/词性、内容问题、渲染后闸门）、
  `lesson_paths.py`（落盘路径与原子写，`today_new` 与 `lesson_render` 共用）、`lesson_render.py`（manifest + 模型产出 → Markdown，只吃数据）。
  改讲义口径去这四份文件；选词的精排在 `code\tools\rank_gate.py`、待建卡清单在 `code\tools\unranked.py`。
- 与 `pipeline.py`（一集素材 → 例句卡）共用同一套 deck 结构；改 deck 时两处都要同步
  （`today_new.py` 的 `DECKS` 与 `pipeline.py` 的 `CFG`）。
- **素材生词**由 `mine.py` 挖掘入库；本链路只负责讲 tag 选中的那部分。不想要某张卡就在 Anki 里 suspend/删除，不要改脚本口径。
- 弱项分析用 `code\analysis\today_weak.py`，不在这条链路里。
