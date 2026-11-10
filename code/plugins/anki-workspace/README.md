# @local/anki-workspace

把 anki-workspace 的六项常用能力装进 DeepSeek Harness（desktop profile）：
六个 Agent 工具、一条动态上下文注入，以及一个 Web 控制面板。

插件本身**不直接读写 Anki**：所有动作都通过工作区既有入口
（`code/cli.py`、`code/common/anki_api.py`）执行，因此沿用它们原有的
`--commit`、备份与回读闸门。

## 六项能力

| 工具 | 对应命令 | 写库 |
|---|---|---|
| `anki_status` | `python code/common/anki_api.py check` | 只读 |
| `anki_doctor` | `python code/cli.py doctor [--tag …]` | 只读 |
| `anki_add_example` | `core6000 gen` → `tts` → `apply` | **默认真写**（`apply --commit`）；显式 `commit=false` 才演练 |
| `anki_today_new` | `python code/cli.py today-new <input> --json` | 默认演练；`commit=true` 才加 `--commit` |
| `anki_vocab_cover` | `python code/cli.py vocab cover … --json` | 只读 |
| `anki_study_report` | `python code/cli.py r report --json --out …` | 只读 Anki；每月写一份报告文件 |

`anki_study_report` 默认每月一次：`output/reports/ankir/monthly-YYYY-MM.json`
已存在时直接跳过；`force=true` 才重建。

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
  - **3 补例句、4 今日选词、5 词汇覆盖率、6 每月报告**：合并成一个 tab 区
    （tab 顺序即 3→6），同一时间只显示一个；切换 tab 不丢表单和上次结果
    （四块保持挂载、只隐藏非活动块）。默认停在「今日选词」。
    关闭面板或切到别的 sidebar 页再点回来，当前 tab 和上次生成的结果仍然在
    （结果缓存在 Client 模块内；生成过程中切走，完成后也会写进缓存；刷新整个
    页面才清空）。
- 写库动作都有「真写」勾选框，默认演练。
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
- 面板通过 `POST /anki-workspace/api` 调用 Host 半；该路由只接受
  loopback 同源请求，并拒绝非 JSON Content-Type。除六个动作外还有两个
  只读方法：`browse`（入参 `{ path }`，省略即工作区根）给选择对话框列目录；
  `report`（入参 `{ month? }`）直接读取当月月度报告 JSON，供页面 6 在
  打开时和刷新后显示。

## 配置

`cordis.patch.yml` 的 `config`：

| 字段 | 默认 | 说明 |
|---|---|---|
| `workspaceRoot` | 本机 anki-workspace 绝对路径 | 上下文注入没有 Agent 作用域，必须显式指定工作区根 |
| `pythonPath` | `python` | 调 `cli.py` 的 Python |
| `timeZone` | `Asia/Shanghai` | 判断「本月」用 |
| `refreshMinutes` | `10` | 后台状态刷新间隔 |

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
