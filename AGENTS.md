# AGENTS.md —— anki-workspace 地图

> 状态：active ｜ 最后核实：2026-11-10

**这是工作区地图，不是手册。** 只写：这是什么、去哪找、什么不能碰。细节都在链接的文件里，
按需单点打开；不要为了「了解工作区」通读 README 或 architecture。

## 0. 这是什么（与硬约束）

真实在用的日语学习工作区：一集字幕 → 例句卡 → 讲解 + 振假名 → 素材生词 → 配音；另有每日讲义、
弱项分析与词汇覆盖率。统一入口 `code/cli.py`（薄分发器，不含业务逻辑）。

- **写的是真 Anki 收藏**（约 4 万张卡），没有测试库。卡片数据没有 git 可退，唯一退路是备份
  （`cli.py backup` 与写库脚本的 `backup_*.json`）；代码和文档有 `git diff`。
- **Anki 必须开着**（AnkiConnect `127.0.0.1:8765`）；唯一例外：备份前要**完全退出** Anki。
- **不替用户做学习决策**（学哪些词、何时停学、讲解够不够好）；**不碰调度列**
  `due / ivl / factor / type / queue / reps / lapses`。新卡 `due` 由 Anki 插件 `jiten_reorder`
  负责（打开自动重排 / 工具菜单手动），脚本一律不写。
- **不用 PowerShell 解析日文**（PS 5.1 默认 GBK：乱码、属性 `$null`、判断恒真）；编码与判断
  一律 Python + `textio`。
- 只写本工作区；不 `pip install`、不找系统 Python、不改系统配置。

## 1. 开工

```powershell
$WS = "<工作区根>"; $PY = "python"
& $PY "$WS\code\cli.py" doctor        # 0=全绿 2=提示 1=阻塞；先修再做
& $PY "$WS\code\cli.py" list          # 组 → 真实脚本（永远比文档新）
& $PY "$WS\code\cli.py" <组> --help   # 参数现查
& $PY "$WS\code\tests\test_llm_out.py"    # 回归：单文件直跑，全离线，几秒
```

用法永远用 `list` + `--help` 现查，不要通读 `code/` 学用法。改过代码就把 `code\tests\*.py`
全跑一遍。`doctor --skip-anki` 可离线；`doctor --tag "动画::<作品>::<季>::第NN集"` 加跑该集 preflight。

## 2. 地图

| 要找什么 | 去哪 |
|---|---|
| 命令、组、脚本的真实落点 | `code/cli.py`（`cli.py list`） |
| 代码结构、共享库、加新脚本的规矩 | [code/README.md](code/README.md) |
| Anki 库结构 / 笔记类型 / 字段名 / 标签口径 | [docs/anki-library.md](docs/anki-library.md) |
| 该读哪份文档、阅读预算、禁读清单 | [docs/README.md](docs/README.md) |
| 每集流水线的判据与命令 | [docs/pipeline-guide.md](docs/pipeline-guide.md) |
| 数据流 / 选词打分 / 覆盖率口径 / 测试矩阵 | [docs/implementation.md](docs/implementation.md) |
| 架构约定 / doctor 口径 / 环境坑 | [docs/architecture.md](docs/architecture.md) |
| 排障顺序与踩坑复盘 | [docs/troubleshooting/README.md](docs/troubleshooting/README.md) |
| 备份与恢复（唯一权威） | [docs/backup-sop.md](docs/backup-sop.md) |
| 任务 → 技能路由 | [.dsh/skills/README.md](.dsh/skills/README.md) |
| 字幕素材规范 | [subtitles/README.md](subtitles/README.md) |
| DSH 插件（面板与 Agent 工具） | [code/plugins/anki-workspace/README.md](code/plugins/anki-workspace/README.md) |
| 已退场的旧入口 | [docs/deprecated.md](docs/deprecated.md) |
| 改提示词 | `code/execution/card_rules.md`；其余见 [docs/README.md](docs/README.md) |

具体任务先加载匹配的技能（路由表见 [.dsh/skills/README.md](.dsh/skills/README.md)）；长流程、
上下文吃紧用 `context-offload`，语义拿不准用 `jmdict-lookup`。

**禁读**（烧 token 或不是文本）：`data/pylibs/**`、`data/snapshots/**/*.anki2`、
`core6000-analysis/cards_info.json`、`data/vocab_cover/study_plan_jiten_anime.json`、
`data/evidence/subtitle_index.json`、`data/freq/jiten_freq_Anime.csv`、`output/*_newwords.md`、
`temp/*.log`、`code/analysis/vocab_cover/`（只读 `cover_cli.py`）。完整清单见
[docs/README.md](docs/README.md)。

## 3. 写库与写码规则（违反会坏数据）

1. **唯一入口**：Anki 只经 `code/common/anki_api.py`；文本 I/O 只经 `textio`；一次性文件只进
   `temp/`。不另写 `def anki()`、不 `sqlite3.connect` 真收藏。
2. **`--commit` 是唯一真写开关**。默认演练；`core6000_example.py apply` 与 `today_new_words.py`
   打标按各自技能文档**默认真写**，用户点名「先演练」才演练。其余写库技能看各自技能文档。
3. **写前留退路，写后回读**：优先 `code/common/writeback.py`；手写路径必须
   `AK.verify_note_fields(...)` 收尾。删除/覆盖前先打印「将删/将改 N 项」和清单。
4. **机械判断交给代码，模型只做语义**：结构/逐字/ruby/查重/字段回读走 `check_*`、`ruby_engine`；
   词形/读音/词性对词典走 `jmdict_check.py`；模型只做翻译、讲解、释义与读音盲区裁决。
5. **不可逆动作先问**：批量删卡/删字段/删文件、改模板或牌组选项、`revert`、覆盖已有讲解。
   目标有歧义、范围不清，或 `doctor` 阻塞而原因不在工作区——先问，不要「先做一版看看」。
6. **拿不准语义先查词典**（`jmdict-lookup`），查不到就明说不确定，不要补一个像样的意思。

## 4. 收工

- 收摊：`cli.py temp clean`（先 `temp list`），再跑一次 `doctor`。
- 汇报四样：**跑了什么**（命令 + `--commit`）、**改了什么**（牌组/字段/张数 + 文件）、
  **怎么验证的**（doctor / 回读 / 测试退出码）、**怎么退回去**（备份或 `revert` 命令；写入库必须有）。
  结论在前，日志只贴要人看的那几行；失败说清卡在哪一步。

---

本文件只当地图：入口、目录、铁律一变就同步这里，并更新日期。根目录只允许白名单条目
（`doctor` 会查）；一次性文件放 `temp/`，`_tmp_*.py` 是历史遗留，别照抄。
