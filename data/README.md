# data/ —— 运行时数据（绝大部分不进 git）

> 状态：active ｜ 最后核实：2026-10-26

这里是脚本的**工作数据**：缓存、中间产物、快照、第三方词典、分析结果。
原则上**全目录不入库**，只有两样是「源码级」的、进 git 才有意义：

| 入库 | 说明 |
|---|---|
| `card_templates/*.html` | 笔记模板的 HTML 源码（卡片长什么样由它决定） |
| `anki_addon/` 源码 | `jiten_reorder` 插件源码（`.ankiaddon` 是打包产物，不入库） |

其余全部由 `.gitignore` 排除——它们要么能重跑出来，要么就是卡片资料本身
（`data/snapshots/` 里是整份收藏的拷贝，`data/immersion/` 里是抓下来的例句库）。

## 目录一览

| 目录 | 大约 | 是什么 | 能否重建 |
|---|---|---|---|
| `snapshots/` | 490 MB | Anki 收藏快照（`*.anki2` / `.db`），每份登记在 `README.json` | 要 Anki 在线，`cli.py backup` 或 `anki_api.Snapshot` 重拍 |
| `pylibs/` | 320 MB | 工作区本地第三方库（SudachiPy + 词典 + matplotlib） | 删目录即卸载，重装 `code/oneshot/install_workspace_wheels.py` |
| `dict/` | 550 MB | JMdict SQLite（`jmdictpy/jmdict.db`），`jmdict-lookup` 用 | 重装 jmdictpy 依赖即可 |
| `immersion/` | 1.1 GB | ImmersionKit 抓下来的例句缓存 | `cli.py immersion fetch` 重抓 |
| `vocab_cover/` | 75 MB | 词汇覆盖率分析的中间产物 / 计划表 | `cli.py vocab cover` 重算 |
| `evidence/` | 73 MB | 字幕索引等证据链数据 | 重扫字幕生成 |
| `subtitle_review/` | 18 MB | 字幕打标（`复习::<名称>`）的报告与词表 | `cli.py subtitle-tag` 重跑 |
| `plans/` | 9 MB | 激活计划（`plan_activate_*.json`）与 `_prev/` 回滚备份 | `cli.py activate plan` 重出 |
| `freq/` | 7 MB | Jiten 动漫词频 CSV | 重新下载 |
| `pipeline/`、`vocab/`、`core6000/`、`ainote/`、`ruby/`、`weak/`、`i1/` | KB 级 | 每集/每次运行的中间产物、缓存、`backup_*.json` 回滚点 | 重跑对应阶段 |
| `card_templates/` | 230 KB | 笔记模板 HTML + `applied_templates.json` | **入库**（`applied_templates.json` 除外） |
| `anki_addon/` | 10 KB | 插件源码 | **入库**（`.ankiaddon` 除外） |
| `piptmp/` | 0 | 空目录，流水线临时落点 | — |
| `pylibs.lock.json` | KB 级 | 本地库版本锁 | `install_workspace_wheels.py` 重生成 |

## 为什么不入库

- **体积**：`dict` + `immersion` + `snapshots` + `pylibs` 就占了 2.4 GB。
- **是卡片资料**：快照、`notes_dump`、词表都是整个收藏的转储，等价于把学习库打包分发。
- **会过期**：中间产物和缓存重跑一次就变，进 git 只会制造噪声；以 live 收藏为准。

新克隆的仓库跑 `cli.py doctor`，会告出哪些数据/依赖缺、该怎么补。
