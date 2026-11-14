# @local/anki-workspace

把 anki-workspace 的常用能力装进 DeepSeek Harness（desktop profile）：
十一个 Agent 工具、一条动态上下文注入，以及一个 Web 控制面板。

插件本身**不直接读写 Anki**：所有动作都通过工作区既有入口
（`code/cli.py`、`code/common/anki_api.py`）执行，因此沿用它们原有的
`--commit`、备份与回读闸门。

## 十一项能力

| 工具 | 对应命令 | 写库 |
|---|---|---|
| `anki_status` | `python code/common/anki_api.py check` | 只读 |
| `anki_doctor` | `python code/cli.py doctor [--tag …]` | 只读 |
| `anki_add_example` | `core6000 gen` → `tts` → `apply` | **默认真写**（`apply --commit`）；显式 `commit=false` 才演练 |
| `anki_jisho_list` | `core6000 gen --list-jisho` | 只读（列 Jisho 候选例句，不调模型不写库） |
| `anki_today_new` | `python code/cli.py today-new <input> --json` | **默认真写**（`--commit`）；显式 `commit=false` 才演练 |
| `anki_season_new` | `python code/cli.py season-new <目录> --json` | **默认只出清单**；`commit=true` 才写季标签 |
| `anki_vocab_cover` | `python code/cli.py vocab cover … --json` | 只读 |
| `anki_study_report` | `python code/cli.py r report --json --out …` | 只读 Anki；每月写一份报告文件 |
| `anki_word_audio` | `mine_audio.py plan/apply --query …` | **默认真写**（`apply --commit`）；显式 `commit=false` 才演练 |
| `anki_card_fix` | `note_regen.py gen`（AINote ①②）/ `cards.py gen --only html` | **默认真写**（`--overwrite --commit`）；显式 `commit=false` 才演练 |
| `anki_llm_models` | `python code/cli.py local-llm-models` | 只读（列端点模型 + profiles，不含 api_key） |

`anki_season_new` 给一季字幕目录（一个目录 = 一季）提取 **550–800 个该学的新词**：
先收 Jiten 动漫名次 ≤ 12000 且本季出现、还没学的通用词，再补 12001–24000 且本季
出现 ≥3 次的作品高频词。数量按候选自然落在区间内（**不硬性规定**）；候选不足时
逐级放宽（次数 3→2→1、Jiten 上限 24000→30000），放宽过程进报告。默认**只出清单**
（`output/daily/season_new_<目录名>.md` + `data/daily_new/season/<目录名>.json`），
勾选「写入季标签」或 `commit=true` 才给入选词打 `本季生词::<目录名>`（写前备份、
写后回读，`--revert --commit` 可退）。不碰调度列、不改字段。

`anki_study_report` 默认每月一次：`output/reports/ankir/monthly-YYYY-MM.json`
已存在时直接跳过；`force=true` 才重建。

`anki_word_audio` 给一个单词的素材生词卡挂 / 修 Word Audio（edge-TTS
`ja-JP-NanamiNeural` 读 `Transliteration` 假名）。`phase=plan`（默认）列出该词
所有候选卡及其音频现状；`phase=apply` + `noteIds` 真写指定卡的 Word Audio。
同词多卡时由调用方先 plan 再选 noteId。Sentence Audio 已有原声则保留不动。

`anki_card_fix` 按 noteId 给例句卡重新生成 `Sentence HTML` 或 `AINote` 中的一个字段
（`field: 'html' | 'ainote'`），**只写选中的那个字段**，另一字段原值不动：

- `field='ainote'` → `note_regen.py gen`：与「增加例句」**同一份提示词 / 渲染器 / 闸门**
  （`core6000_example_prompt.md` + `render_ainote`），把卡上现有的 ①/② 两句写成
  `① 句 + ② 句` 的讲解；不抓 Jisho、不加新句。
- `field='html'` → `cards.py gen --only html`：沿用 `ruby_engine` 确定性重渲染。

默认真写（`--commit`），显式 `commit=false` 才演练；写后回读校验。

## 本地模型选择（llmModel / llmProfile）

写库类能力里跑本地模型的步骤（`today-new` 的 LLM 精排、`core6000 gen` 的讲解
生成）支持指定档位，三层优先级从高到低：

1. **单次调用**：工具参数 `llmModel` / `llmProfile`（面板「本地模型」下拉同理）。
   - `llmProfile` → `--profile <name>`：用 `~/.dsh/local-llm.json` 里 `profiles`
     的那一档（ninfer / strata / strata_abl）；**换端点走这个**（与脚本 help 一致）。
   - `llmModel` → `--model <id>`：钉住端点 `/v1/models` 里的某个模型 id。Python 侧
     （`code/common/llm_client.py`）把显式 model 视为「人明确指定」，会**关掉 pin**
     （不再对齐 `/props` 当前在服务的模型）。
   - **显式 `--profile` 同样关 pin**（2026-11-14 修复）：点了档位就用该档的
     model/base_url。旧行为是 profile 只换 base_url、model 仍被 pin 对齐到端点当前
     模型——面板选了档位等于没选。拼错的档位名现在**直接报错**，不再静默滑回默认。
     空档位（如 `ninfer: {}`）语义仍是「跟随端点当前在用的模型」，行为不变。
2. **插件 Config 默认**：`llmProfile` / `llmModel`（见下表），经环境变量
   `DSH_LOCAL_LLM_PROFILE` / `DSH_LOCAL_LLM_MODEL` 注入所有子进程，兜底生效。
3. **留空** = 什么都不注入：跟随 `local-llm.json` 的 `profile` + `pin_active`，
   与命令行不加旗标完全同口径（默认行为不变）。

面板下拉的清单来自只读脚本 `python code/cli.py local-llm-models`（端点
`/v1/models` + `/props` 当前在服务 + 配置文件 profiles；**绝不输出 api_key**），
对应工具 `anki_llm_models`。面板打开时拉一次并缓存，点「刷新」重拉。

## 上下文注入

插件在每轮系统提示里注入一段 `<anki-workspace>`：

```
根目录：…
AnkiConnect：在线（v6，25 个牌组，… ms）
doctor：提示（exit 2；通过 6 / 提示 8 / 阻塞 0）；✓ 可开工…
检测时间：…
```

- 状态每 10 分钟后台刷新一次（`refreshMinutes`），也会在 `agent/created`
  后按 60 秒节流刷新。
- 工具调用会顺带更新缓存，所以 `anki_status` / `anki_doctor` 的结果马上
  进入下一轮上下文。

## Web 面板

- 侧边栏增加一个面板图标（`sidebar.panellist`，id `anki-workspace`，
  order 20），主区对应 `main` key `anki-workspace`。
- 六个能力不再各占一张大卡：
  - **1 Anki 在线状态、2 doctor 结论**：收成右上角两枚小状态按钮（绿/黄/红点 +
    状态短词）。点开是浮动详情，含完整信息与「立即检测 / 跑 doctor」；
    点空白处或再点按钮关闭。
  - **3 补例句、4 今日选词、5 词汇覆盖率、6 每月报告、7 卡片修正**：合并成一个 tab 区
    （tab 顺序即 3→7），同一时间只显示一个；切换 tab 不丢表单和上次结果
    （五块保持挂载、只隐藏非活动块）。默认停在「今日选词」。
    关闭面板或切到别的 sidebar 页再点回来，当前 tab 和上次生成的结果仍然在
    （结果缓存在 Client 模块内；生成过程中切走，完成后也会写进缓存；刷新整个
    页面才清空）。
- 写库动作都有「真写」勾选框，默认真写（取消勾选才演练）。
- **今日选词** tab 底部还有「每季生词（选目录）」区：选一个字幕目录（= 一季），
  用 checkbox / textbox 调筛选条件，默认值来自 2026-11-13 的实测结论——
  通用层 Jiten ≤ `12000`、作品层 Jiten ≤ `24000`、作品层最少出现 `3` 次、
  每季下限 `550` / 上限 `800`；另有「保留专有名词」「写入季标签」两个勾选和标签名
  输入（空 = `本季生词::<目录名>`）。点「提取每季生词」出清单；**默认不写库**，
  勾选「写入季标签」才写。结果区显示通用层/作品层 KPI、前 20 个词（可展开）、
  放宽记录、标签差集与清单路径。
- 「今日选词」「增加例句」卡里各有一个**本地模型下拉**（两个 tab 共享同一个
  选择）：默认项 = 跟随配置/端点 pin；分组列出 `profiles` 与端点模型。清单由
  Host 半的 `llm-models` API 提供（只读，见上节）。
- **增加例句** tab 有 Jisho 候选例句选择区：填词 → 点「列 Jisho 候选」（走
  `jisho-list`，即 `core6000 gen --list-jisho`，只读、不调模型）→ 面板列出该词的
  Jisho 真实例句（编号 / 字数 / 来源 Tatoeba·Jreibun / 句子原文，振假名不合格的
  会标 ⚠️）→ 点某条选中（或不选 = 自动挑选）→ 点「跑三步」时把选中编号作为
  `jishoPick` 透传给 `add-example`，按这条句子生成音频 + AINote 讲解并覆写卡片资料
  （Sentence / Sentence HTML / Sentence Translation / AINote / Sentence Audio）。
  **手动选择优先**：这张卡上次已有合格产出、但用的是别的 Jisho 句子时，`gen`
  会重新生成，不会拿「已有产出」跳过用户这次的选择；「与第一句太像」这条偏好
  闸门也不再拦手动选中的句子（振假名结构 / 真含目标词仍照查，避免写坏卡）。
  对应工具 `anki_jisho_list`（先 list 看编号）+ `anki_add_example` 的 `jishoPick`
  （再 pick 指定）。
- 需要选文件 / 目录的输入（今日选词的「字幕文件或作品目录」、词汇覆盖率的
  文件列表）都是**只读显示 + 「浏览…」按钮**，点击弹出应用内选择对话框：
  面包屑导航、上一级、按名称过滤、目录优先排序；今日选词可挑一个文件或
  直接「选择此目录」，词汇覆盖率可一次勾选多个文件。对话框里的路径全部
  是**相对工作区根**的写法，与 `today-new` / `vocab cover` 的解析口径一致；
  浏览范围被限制在 `workspaceRoot` 内，不会列出或返回工作区外的路径。
- 中英文界面文案走 Client locale；`locale` 是插件的硬依赖（`inject: ['slots', 'locale']`），
  因为 locale 服务在异步 bootstrap 之后才 provide，按可选项读取会让整个面板显示翻译键；
  颜色只用 `--dsw-alias-*` 主题变量。
- 「今日选词」「词汇覆盖率」「每月报告」都只读 Python 生成的结构化 JSON，
  不重新解析人类可读日志：
  - 今日选词：候选/入选/笔记 KPI、排序来源、词卡（词形/读音/词性/牌组/JAR/
    次数/集数/公式分与分数条/模型理由/首句）、标签计划、义项修复与被剔清单、
    现场复核剔除、跳过统计、产物路径；
  - 词汇覆盖率：可懂度 headline、卡组/已学/严格三条覆盖率条、含语法词/词汇词/
    需背实词三套分母对比表、句子级理解度、反向触达、卡组外新词与待激活词 chips，
    勾选「筛选新词」时再显示内容词候选与模型理由；
  - 每月报告：直接读 `output/reports/ankir/monthly-YYYY-MM.json`（即
    `cli.py r report --json --out` 落盘的同一个文件），渲染留存率 headline、
    卡片/笔记/牌组/复习/天数/日均/连续/时长 KPI、成熟卡与年轻卡比例条、
    新卡/复习卡/学习中/挂起/埋藏构成，以及首次/最近复习日期；原始 JSON
    折叠在「原始 JSON」里。**本月报告已存在、生成动作被跳过时也会读回
    这份 JSON 并显示**，不再只显示一句「跳过」。
  - 今日选词 / 词汇覆盖率两份为 `schema: 1`；月度报告是 ankiR
    `anki_report` 的原始 JSON（没有额外 schema 包装）。
- **卡片修正** tab（原「单词配音」，宽按钮）：**一个单词输入框**驱动三种目标——
  勾选「单词音频 / Sentence HTML / AINote」后点唯一的「重新生成」按钮。**三个目标
  默认都不勾**（用户 2026-11-13 定：先想清楚要重做哪个字段，一个都没勾时按钮是灰的），
  每个 checkbox 和按钮都有 mouseover tooltip 说明。
  - 单词音频：查素材生词卡，列出 Word Audio / Sentence Audio 现状；同词多张时
    勾选要更新的卡，再点一次「重新生成」。Host 半跑
    `mine_audio.py plan --query "note:<word>"`（人读表格）和
    `anki_api.py find "note:<word>" --json`（机器读 noteId），按索引对齐后把
    noteId 附到候选卡上；apply 阶段直接传真实 noteId，走
    `mine_audio.py apply --query "nid:…" [--commit] [--force]`。
  - 字段重新生成：按 `Word` 字段在**整个收藏**里查卡（`Word:"…"`，再按 `Word`
    字段精确相等 + 「带 Sentence / AINote / Sentence HTML 三个字段」过滤，见
    `cardLookupCards`），列出 Sentence / AINote / Sentence HTML 现状，并标出每张卡
    的**牌组与笔记类型**。**四个 deck 都算**：`2-例句`（Basic）＋ `0-素材生词` /
    `1-高频日语单词 6000` / `2-考级词汇`（都是 `Japanese Vocabulary`）。一个词常常
    同时挂在多张卡上（張る → 例句卡「電線を引っ張る」＋ 高频卡「肩が張る」），
    所有能改的卡都会列出来，由用户选；**命中多张时默认一张都不勾**（旧版会预选
    全部，点第二次就把每张都覆盖了）。两个字段分别走 `card-fix` + `field:'html'` /
    `field:'ainote'`，**只写选中字段**、另一字段原值不动：
    AINote 走 `note_regen.py`（与「增加例句」同一份 core6000 提示词 + `render_ainote`，
    按卡上现有 ①② 两句重写讲解）；Sentence HTML 走 `cards.py gen --only html`
    （`ruby_engine` 确定性重渲染）。两处都不新增提示词。
  - 整库只有一张可改的卡时第一次点击就直接执行；多张时第一次点击只列候选、
    默认全不勾，勾选后再点同一个按钮（一张没勾时按钮置灰并提示先勾卡）。**默认真写**
    （勾选「真写库」= `--commit`），取消勾选即 `commit=false` 演练。生成结果按目标
    显示，脚本原始输出折叠在「脚本原始输出」里。
- 面板通过 `POST /anki-workspace/api` 调用 Host 半；该路由只接受
  loopback 同源请求，并拒绝非 JSON Content-Type。除写库/生成动作外还有三个
  只读方法：`browse`（入参 `{ path }`，省略即工作区根）给选择对话框列目录；
  `report`（入参 `{ month? }`）直接读取当月月度报告 JSON，供页面 6 在
  打开时和刷新后显示；`llm-models`（无入参）返回本地模型档位清单。
  `season-new`（入参同 `anki_season_new`：`input` + 五个筛选值 + `tag` +
  `commit`）跑每季生词提取；**默认只出清单**，`commit: true` 才写季标签。
- API 方法中与卡片修正相关的两个：`card-lookup`（入参 `{ word }` 或 `{ ids }`，
  只读；`word` 路径在**整个收藏**里按 `Word:"…"` 字段搜索，再由 `cardLookupCards`
  按词形精确相等 + 三个字段齐备过滤，经 `anki_api.py notes --json --cards` 读回
  Sentence / Word / AINote / Sentence HTML 以及牌组名 / 笔记类型，供面板区分
  例句卡与词汇卡）；`card-fix`（入参 `{ noteIds, field:
  'html'|'ainote', commit }`：`ainote` 跑 `note_regen.py gen`，`html` 跑
  `cards.py gen --only html`，都带 `--overwrite [--commit]`，默认真写）。

## 配置

`cordis.patch.yml` 的 `config`：

| 字段 | 默认 | 说明 |
|---|---|---|
| `workspaceRoot` | 本机 anki-workspace 绝对路径 | 上下文注入没有 Agent 作用域，必须显式指定工作区根 |
| `pythonPath` | `python` | 调 `cli.py` 的 Python |
| `timeZone` | `Asia/Shanghai` | 判断「本月」用 |
| `refreshMinutes` | `10` | 后台状态刷新间隔 |
| `llmProfile` | 空 | 本地模型默认档位（`local-llm.json` profiles 的哪一项）；空 = 跟随配置文件 |
| `llmModel` | 空 | 钉住端点上某个模型 id（会关 pin）；空 = 不指定 |

改 `workspaceRoot` 后需要重新加载插件（`plugin_manager` 关/开一次，或重启
Harness）才会生效。改了 `index.js` / `lib/core.js` / `client.js` 这类 JS 代码
则要 `remove_bundle` → `install_bundle`（或重启 Harness）才会换成新模块；
单纯 `set_plugin` 关/开不会重新 import 已缓存的 Host 模块。

## 安装与回退

安装（已执行）：

```text
plugin_manager install_bundle
  target: C:\Users\zgw31\Documents\deepseek-harness\anki-workspace\code\plugins\anki-workspace
```

回退：

```text
plugin_manager remove_bundle  target: @local/anki-workspace
```

回退只移除 Harness 插件；工作区 `output/` 里已生成的报告、缓存文件不会删。
写库动作的回退仍由工作区脚本自己的备份负责（例如 core6000 的
`data/core6000/backup_*.json` 与 `core6000 revert`）。

## 开发自检

```powershell
node --check code\plugins\anki-workspace\index.js
node --check code\plugins\anki-workspace\client.js
node --check code\plugins\anki-workspace\lib\core.js
node --test --test-isolation=none code\plugins\anki-workspace\test\logic.test.mjs
node --test --test-isolation=none code\plugins\anki-workspace\test\render.test.mjs
node --test --test-isolation=none code\plugins\anki-workspace\test\locale.test.mjs
python code\tests\test_cards_only.py
python code\tests\test_note_regen.py
python code\tests\test_season_new_words.py
```

> Windows + DSH 沙箱下 `node --test` 默认会 spawn 子进程并触发 EPERM；
> 用 `--test-isolation=none` 在单进程内跑。

## 已知限制

- 面板视觉未做浏览器自动化验证；当前验证到 Client slot 已注册且 active。
- 选择对话框只在 `workspaceRoot` 子树内浏览（不列盘符、不跳出工作区），
  这样返回的路径一定能被 `cli.py` 直接消费；要选工作区外的字幕，得先拷进
  `subtitles/`。
- `workspaceRoot` 是行配置里的绝对路径；换工作区要改 `cordis.patch.yml`。
- `anki_add_example` 的 `gen` 依赖本机模型端点与 jisho，失败时链会在该步
  停止并原样返回退出码与输出尾部。
