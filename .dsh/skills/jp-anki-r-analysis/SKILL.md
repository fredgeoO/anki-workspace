---
name: jp-anki-r-analysis
description: anki-workspace 的**学习分析报告**入口：用 R 包 ankiR（0.6.0，137 个函数，只读）出留存率、健康分（0-100）、弱项标签/牌组、复习负荷与预测、时间分配、间隔/时段分布图和遗忘曲线，并据此写分析报告。当用户说「用 ankiR 分析一下」「出个学习分析报告 / 健康分 / 留存报告」「复习负荷和未来几周预测怎么样」「画复习热力图 / 间隔分布 / 时段分布」「换个统计角度看这个库」「和 Python 弱项分析对一下」时加载。**只读**：不写 Anki、不改 due/ivl、不生成讲解。**数据一律取当前 live 收藏（真实数据，Anki 可开着）**，每次运行打印「最新复习时间 + Anki 在线对账」，报告必须写明「数据截至」；`data/snapshots` 的旧快照只在显式 `--db` 时用于复现历史，不允许拿来出当期报告。**到期/负荷用 Anki 口径重算（`ankir.py due`）：ankiR 自带的 `Due today`/overdue/forecast 在本库全错。**与 `jp-anki-daily-weak` 的分工：那个出「今天/近三天答错的词名」，本技能出「库层面的统计、趋势、图表 + 报告」。仅适用于 anki-workspace。
---

# ankiR 学习分析（R 包 · 只读 · 出报告）

本技能覆盖**一件事**：把 ankiR 的统计/图表跑出来，写成一份有出处、能复核的分析报告。

**它不替代任何卡技能**：要找「哪个词答错了」→ `jp-anki-daily-weak`；要讲词、改卡、排期 →
各自的 `jp-anki-*` 技能。ankiR 只看聚合数字，**不看卡片内容语义**。

## 一、环境（已装好，别重装）

| 东西 | 位置 | 说明 |
|---|---|---|
| R 4.6.1 | `data\r-env\R`（`bin\Rscript.exe`） | 便携安装，**不在 PATH**，不写注册表；删目录即卸载 |
| R 包库 | `data\r-env\R\library` | ankiR 0.6.0 + 依赖 + dplyr、ggplot2 |
| 桥 | `code\analysis\ankir_bridge.R` | Python 写请求 → R 调函数 → UTF-8 JSON 回来 |
| 入口 | `code\analysis\ankir.py` | 也是 `python code\cli.py r …` |

`data\` 整体在 `.gitignore` 里，所以 R 环境不进 git；换机重装见 §八。

**自检**（1 秒，不碰收藏）：

```powershell
$WS = "<工作区根>"; $PY = "python"
& $PY "$WS\code\analysis\ankir.py" list --grep summary    # 应该列出 anki_quick_summary / anki_summary
```

## 二、命令

```powershell
$WS = "<工作区根>"; $PY = "python"; $AN = "$WS\code\analysis"

# 函数目录（137 个，带标题）
& $PY "$AN\ankir.py" list
& $PY "$AN\ankir.py" list --grep leech

# 一行总览：卡数 / 到期 / 连续天数 / 7 日留存
& $PY "$AN\ankir.py" summary

# ★ 到期与负荷（Anki 口径，不调 R）：今天待复习 / 逾期>7天 / 学习中 / 未来 14 天
& $PY "$AN\ankir.py" due
& $PY "$AN\ankir.py" due --days 30 --json

# 综合报告（卡量、成熟度、复习量、留存、连续天数）
& $PY "$AN\ankir.py" report

# 健康分 0-100 + 扣分项（⚠ 其中 overdue 一项要用 `due` 的真值覆盖）
& $PY "$AN\ankir.py" health

# 弱项（按标签/牌组，默认全部历史；--arg days=30 收窗口）
& $PY "$AN\ankir.py" weak
& $PY "$AN\ankir.py" weak --arg days=30 --head 10

# 留存率（可 --arg days=30 / --arg by_deck=TRUE）
& $PY "$AN\ankir.py" retention --arg days=30 --json

# 任意函数（先 list 查名字；参数用 --arg k=v，可重复）
& $PY "$AN\ankir.py" call anki_retention_by_type --head 12
& $PY "$AN\ankir.py" call anki_weak_areas --args '{"days":30,"n":15}' --json --out "$WS\temp\weak30.json"

# 画图（默认落到 output\reports\ankir\<函数名>.png）
& $PY "$AN\ankir.py" plot anki_plot_retention
& $PY "$AN\ankir.py" plot anki_plot_intervals --width 10 --height 6
```

约定：**结果走 stdout，进度/警告走 stderr**；`--json` 出机器可读的原始返回，`--out` 落文件。

## 三、数据源（报告一律用真实数据）

| 用法 | 含义 | 什么时候用 |
|---|---|---|
| 默认（`--source live`） | 把**当前**收藏（含 `-wal/-shm`）复制成只读副本交给 R，跑完即删。**这是真实数据** | 所有报告、所有「现在怎么样」 |
| `--db <路径>` | 指定历史快照或备份副本（只读） | 只用于复现旧报告 / 对比两个时点 |
| `--source snapshot` | 必须并列 `--db`；不给就直接报错 | 同 `--db`，只是口径写得更明确 |

**`data\snapshots\_anki_snap\` 是旧货（实测比 live 旧约 3 天：54,360 次复习 vs 55,712），
不要拿它出当期报告。** 代码里已堵死「不给 `--db` 就用它」的静默路径。

每次运行都会打印时效三行（stderr），**报告里的「数据截至」就抄第一行**：

```
[数据] live 收藏（现在） · 最新复习 2026-10-29 15:49 · 39,820 张 / 55,712 次复习
[数据] 磁盘落盘时间 2026-10-30 04:46
[数据] Anki 在线校验通过：今日复习 0 次，副本一致
```

- 第三行是拿 AnkiConnect 的「今日复习次数」跟副本对账：如果 Anki 里的数更大，会打
  `[!] 副本落后 … 重跑一次`，那就重跑，别拿落后副本写报告。
- Anki 没开时第三行会说明「读的是磁盘上的收藏」——**仍然真实**（Anki 关闭时磁盘就是全量），
  但报告里要注明「Anki 未开，离线读盘」。

R 侧只读；桥脚本**没有任何写库路径**。跑完 `temp\ankir_tmp\` 与 `temp\ankir\run-*` 自动清，
设 `$env:ANKIR_KEEP='1'` 才保留（排障用）。

## 四、⚠ 到期/预测口径：ankiR 是错的，必须用 `due`

Anki 的复习卡 `due` 是**「距收藏创建日 `col.crt` 的天数」**，不是 1970 起的绝对天数。
本库 `crt = 2026-06-09`，今天第 143 天，复习卡 due 落在 143–1280。
ankiR 拿它跟绝对日数（≈20,756）比，于是：

| ankiR 说 | 真实（Anki 口径） | 影响 |
|---|---|---|
| `Due today: 7,105` | **310** | 全部 7,105 张复习卡都被当成到期 |
| 「7,105 cards overdue >1 week」 | **逾期 0** | 健康分被冤枉扣分 |
| 蒙特卡洛预测 341/天 | 明天 248、未来两周日均 **135** | 负荷预测虚高 2–3 倍 |

**所以：报告里所有到期/负荷数字只认 `ankir.py due`**（按 crt 重算，且与 Anki 牌组列表核对过）。
`summary` 会把 ankiR 那行的 `Due today` 自动换成真值并在 stderr 标 `[修正]`；
`health` 的 `many_overdue` 与所有 forecast 类函数**不要引用**。

```powershell
& $PY "$AN\ankir.py" due          # 今天 310 / 逾期 0 / 未来 14 天 248·217·183…
& $PY "$AN\ankir.py" due --json
```

## 五、在这套库上验证过的函数（2026-10-30，39,820 张卡实测）

**直接可用（报告主力）**

| 函数 | 出什么（本库实测口径） |
|---|---|
| `anki_quick_summary` | 一行：39,820 张 / 到期 310（ankiR 原始报 7,105，入口已自动修正）/ 连续 143 天 / 7 日留存 85% |
| `anki_report` | 综合：37,292 笔记 / 25 牌组 / 55,712 次复习 / 成熟卡 81.9% / 82.2% 留存 / 314.9 小时 |
| `anki_health_check` | 健康分 79（GOOD）+ 4 条 warning（如 1,041 张笔记 >5000 字符）；⚠ 其中 overdue 一项是错的（见 §四） |
| `anki_weak_areas` | 按标签的弱项（近 30 日示例）：`leech` 60.3%、`复习::平家物语` 62.8%、`jp-core::6k` 67.1% |
| `anki_retention_rate` | 留存（可 `days`、`by_deck`），返回 retention/total_reviews/again/passed |
| `anki_retention_by_type` | 按笔记类型/长度/媒体分组的复习时长；**按长度/note type 的留存有效**，Cloze/媒体那几栏多为 NA |
| `anki_today` `anki_streak` `anki_stats_deck` `anki_tag_analysis` `anki_leeches` | 今日明细、连续天数、分牌组统计、标签用量、leech 列表 |
| `anki_learning_efficiency` `anki_roi_analysis` | 单位时间收益、知识半衰期 |
| `anki_best_review_times` `anki_burnout_detection` | 最佳时段、疲劳信号 |
| `anki_fit_forgetting_curve` `anki_retention_stability` | 个人遗忘曲线拟合、留存稳定性 |
| `fsrs_get_parameters` `fsrs_memory_states` `fsrs_current_retrievability` | FSRS 参数、记忆状态、当前可提取率 |
| `anki_plot_retention` `anki_plot_intervals` `anki_plot_difficulty` `anki_plot_hours` | 已实测出图（见 §六） |

**别用 / 有坑**

| 函数 | 情况 |
|---|---|
| `anki_forecast_monte_carlo` `anki_forecast_enhanced` `anki_workload_projection` `anki_backlog_calculator` `anki_forecast` | **全部受 due 口径 bug 影响**（预测 341/天 vs 真实 135/天），负荷一律用 `ankir.py due` |
| `anki_health_check` 的 `many_overdue` | 同理：报 7,105 逾期，真实 0；引用健康分时要注明这一项无效 |
| `anki_interference_analysis` | 在本库跑 >3 分钟未出结果（两两比较 O(n²)），**不要跑** |
| `anki_session_analysis` | 报 dplyr 兼容错（`cumsum(session_start)`），改用 `anki_session_stats` |
| `anki_plot_heatmap` | 出图但**是空的**（365 行被当缺失值丢弃）；要看复习节律用 `anki_plot_hours` / `anki_plot_weekdays` |
| `anki_plot_forgetting_curve` | 必须先 `anki_fit_forgetting_curve()` 再画；单独画会报错 |
| `anki_retention_by_type` 的 Cloze/媒体栏 | 返回 NA（本库几乎全是非 Cloze、全带音频），别拿它下结论 |
| `*_export*` / `anki_to_*` / `anki_dashboard` / `anki_progress_report` | 导出与交互面板，不属于「写报告」链路，非必要不用 |

## 六、写报告的口径（这条最容易被写错）

1. **数字只能来自命令输出**。先跑、再抄；模型不许「估一个大概」，也不许拿 `data\snapshots` 的旧数凑。
2. 报告开头写清四件事：**数据截至**（抄 `[数据] 最新复习 …` 那一行）、**数据源**（live 收藏 / 哪个 `--db`）、
   **统计窗口**（7 日 / 30 日 / 全历史）、**口径**（留存 = 非 Again 的复习占比，含学习卡）。
3. 图表放 `output\reports\ankir\`，正文用 Markdown 引用相对路径；报告本身写 `docs\reports\`，
   命名沿用既有风格（如 `anki学习报告-YYYY-MM-DD.md`）。
4. 结论要能回到数字：不说「最近状态不好」，说「近 30 日留存 80.5%，`leech` 组 60.3%，比全库低 20 个点」。
   现成样例：`docs\reports\2026-10-30-ankiR-学习分析.md`（照它的章节与口径写）。
   **到期/负荷只抄 `ankir.py due`**：今天待复习、逾期、未来 14 天；不要抄 ankiR 的 `Due today`/overdue/forecast（见 §四）。
5. **跨技能核对**：词级结论（哪几个词、哪几集）用 `jp-anki-daily-weak` / `anki_api` 取，
   别指望 ankiR；两边数字不一致时，先查窗口与数据源，再决定写哪个。
6. 报告是个人学习数据，`docs\reports\` 不进 git（`.gitignore` 已排除），别贴到外部。

## 七、边界（违反会坏数据）

- **只读**。不 `anki_to_*` 回写、不 `update_note_fields`、不碰 `due/ivl/factor/type/queue/reps/lapses`。
- 不拿 `--db` 指向 live 收藏本体（`%APPDATA%\Anki2\…\collection.anki2`）；要「现在」就用默认 live 副本。
- 不 `install.packages` 到系统库、不改 PATH、不装 Rtools；新包只进 `data\r-env\R\library`，且先问用户。
- ankiR 的牌组/标签名会带 `::` 与日文，**在 Python 里读写**，不要用 PowerShell 解析。

## 八、排障

| 现象 | 原因 / 处理 |
|---|---|
| `找不到 Rscript：…data\r-env\R\bin\Rscript.exe` | R 环境被删/换机 → 按 §九 重装 |
| `Fatal error: cannot create 'R_TempDir'` | TEMP 不可写。入口已把 TEMP 钉到 `temp\ankir_tmp`；手跑 Rscript 时要自己设 |
| 输出里日文变 `?` | 没走入口（缺 `LC_ALL=Japanese_Japan.utf8`）→ 用 `ankir.py`，别直接 `Rscript -e` |
| `Column 'sfld': mixed type …` warning | ankiR 读 notes 的固有 warning，**无害**，报告里不必提 |
| 函数返回一大坨 `$a $b $c` 列表 | 加 `--json` 或 `--head N`；文本模式默认只渲染前 20 行 |
| `ankiR 报错：…` | 先 `list` 确认函数名/参数，再看是不是 §四「别用」里的坑 |
| `--source snapshot 只用于复现历史，必须同时给 --db` | 这是故意的：不给 `--db` 就会退回 3 天前的 `_anki_snap`。要当期报告就**去掉** `--source`，用默认 live |
| `[!] 副本落后：Anki 今天已复习 N 次…` | 复制副本时 Anki 又写了新复习 → 重跑同一条命令 |
| 跑完 CPU 一直占着 | 手跑 `Rscript` 超时只杀了外壳，`R.exe` 会留成孤儿：`Stop-Process -Name Rscript,R -Force`（走 `ankir.py` 不会有这问题，它杀整棵进程树） |

## 九、重装（换机 / 环境损坏时，需用户批准联网）

```powershell
$WS = "<工作区根>"; $R = "$WS\data\r-env\R\bin\Rscript.exe"
# 1) R 4.6.1 便携安装：CRAN 的 R-4.6.1-win.exe，静默装到 data\r-env\R
#    Start-Process R-4.6.1-win.exe -ArgumentList '/VERYSILENT','/NORESTART',"/DIR=$WS\data\r-env\R" -Wait
# 2) 包（TEMP 必须指到工作区，否则 R 起不来）
$env:TEMP = "$WS\temp\rtmp"; $env:TMP = $env:TEMP; $env:TMPDIR = $env:TEMP
& $R -e "options(repos=c(ankiR='https://cran.r-universe.dev', CRAN='https://cloud.r-project.org')); install.packages(c('ankiR','dplyr','ggplot2'))"
& $R -e "library(ankiR); cat(as.character(packageVersion('ankiR')), '\n')"   # 应输出 0.6.0
```

## 十、收工汇报

四件套：**跑了什么**（命令 + 参数 + 数据源）→ **关键数字**（摘要 3–5 条，直接贴）→
**产出**（报告路径 + 图表路径）→ **没写库**（本技能只读，无需回退；如做过其它写操作另说）。
用户问「今天学得怎么样」时，至少给 `summary` + `weak` 两个数，别只报「已完成」。
