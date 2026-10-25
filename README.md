# anki-workspace

> 状态：active ｜ 最后核实：2026-10-26

一个「日语学习 × Anki」自动化工作区：把「看动画 → 做卡 → 复习 → 查漏」串成可重跑的脚本，
而不是每次手工整理。当前收藏约 **3.7 万张卡 / 25 个牌组**，所有入口都在 `code/cli.py`。

本文件是**项目说明书**：是什么、怎么跑、怎么测、目录长什么样、改动时守什么规矩。
**Agent 的行为契约在 [AGENTS.md](AGENTS.md)**——角色与边界、硬性禁令、验证命令、失败与求助条件
都在那边，两者冲突时以 AGENTS.md 为准（见 §10）。详细架构见 [docs/architecture.md](docs/architecture.md)。

---

## 1. 它做什么

**这个工作区为「提升日语动画听力」而建**——目标是甩开字幕听懂对白，而不是应付考试。
所以工具链围着「看过的动画」转：字幕进，例句卡和素材生词出。

打底用的是两套成熟的考级牌组：`1-高频日语单词 6000`（Japanese Core 6000）与
`2-考级词汇`（eggrolls-JLPT10k-v3.5，N5–N1）。它们覆盖日常日语的骨架，但动画对白有自己的词汇面——
拟声拟态、口语缩略、题材词、俚语，这些在考级词表里查不到，却在动画里反复出现。
于是再建第三个词汇牌组 `0-素材生词`：从看过的字幕里把「**考级牌组里没有、但 Jiten 动画词频里常见**」
的词挖出来收进去，补上考级词表与真实对白之间那道缝。**这是本工作区最主要的服务功能。**

| 主线 | 输入 | 产出 |
|---|---|---|
| 每集流水线 | 一集字幕（`.ass/.srt`） | 例句卡 → 清理 → 讲解 + 振假名 → 素材生词 → 配音 |
| 每日链路 | 当天到期的「新卡」 | 日语讲义（`output/daily/lesson_latest.md`）、复习后弱项报告 |
| 词汇分析 | 字幕语料 + 现有卡组 | 覆盖率、新词表、挖掘窗口建议、跨作品通用性判定 |
| 收集类 | 一段文字 / 一集字幕 | 专有名词卡（`3-专有词汇`，不进队列）、`复习::<名称>` 标签 |

三条贯穿全项目的原则：

- **流水线不碰学习调度**：新卡学哪张、先学哪张由笔记字段 `JitenAnimeRank` 和 `cards.due` 决定，
  阶段脚本不写 `due / ivl / factor / type / queue / reps / lapses`。
- **机械判断归代码，语义判断归模型**：结构、逐字一致、振假名覆盖、读音冲突、查重、字段回读
  由 `code/common/` 的检查器判；模型只做翻译、讲解、释义、词性、读音盲区裁决。
- **默认直连本地模型**：阶段二/四的生成与每日讲义都走本机 OpenAI Responses 端点，
  派子代理只是端点不可用时的备用路径（省云端 token）。

## 2. 快速开始

```powershell
$WS = "<工作区根>"
$PY = "python"
```

> `<工作区根>` 与 `python` 是占位符：前者换成这个目录的绝对路径，后者换成任意 Python 3 解释器。
> 文档与代码里不写本机的用户名、盘符和解释器路径。

**前置**：Anki 打开（AnkiConnect `127.0.0.1:8765`）。唯一例外是备份——那时必须**完全退出** Anki。
第一次进工作区先跑体检：`& $PY "$WS\code\cli.py" doctor`。

| 想做什么 | 命令 |
|---|---|
| 开工体检（只读门禁） | `cli.py doctor` ／ 离线 `doctor --skip-anki` ／ 查某集 `doctor --tag "动画::…"` |
| 每集主线一条命令（阶段 2–5） | `cli.py episode --tag "动画::<作品>::<季>::第NN集" --input-tag 待标记 [--commit]` |
| 每日讲义 | `cli.py daily stats` → `daily plan` → `daily check` → `daily gen` |
| 复习后弱项 | `cli.py weak today --days 3 --plain`（另有 `revlog` / `pace` / `build-list`） |
| 点名 core6000 词补第二条例句 | `cli.py core6000 gen --words "徹夜,適当"` → `tts` → `apply`（先演练再看 `--commit`） |
| 给一个词找真实例句（jisho，不造句） | `cli.py jisho --word "徹夜" --reading "てつや"`（只读） |
| 加强某张卡的讲解与语感 | `cli.py ainote enrich --word 分際 --commit` |
| ImmersionKit 按词表抓例句卡 | `cli.py immersion fetch` → `gen` → `write --to both --commit` → `verify` |
| 词汇覆盖率 / 新词表 / 挖掘窗口 | `cli.py vocab cover` ／ `newwords` ／ `report` ／ `mine_window --k 3` |
| 全局 Jiten 词频序重排 | `cli.py vocab reorder-jiten [--commit]`（默认演练） |
| 收摊：清一次性文件 | `cli.py temp list` → `temp clean` |
| 备份到 G: 盘 | `cli.py backup --dest <备份盘>:\anki-backup-<日期>`（先退出 Anki） |

`cli.py list` 与 `cli.py <组> --help` 是**权威用法来源**——比任何文档都新。
未纳入统一入口的脚本（如 `vocab_cover/` 里另外 20 个数据链脚本）直接调用，
见 [docs/architecture.md §4-5](docs/architecture.md)。

## 3. 开工体检 `doctor`（只读，几秒）

一次跑完九项：① AnkiConnect ② Anki 访问点自审 ③ `textio` 编码自审 `--strict` ④ 废弃符号残留
⑤ 快照卫生 ⑥ 文档状态行 ⑦ 每集 preflight（待生成/判弃张数、建议 `--batches`、孤儿产出）
⑧ 环境与依赖（Python、`data/pylibs`、`pylibs.lock`）⑨ 工作区卫生（根目录白名单、`temp/` 待清量）。

**退出码**：`0` 全绿；`2` 只有提示；`1` 有阻塞项——**先修再动手**。判定口径见
[docs/architecture.md §3](docs/architecture.md)。

## 4. 目录结构

```
anki-workspace/
├─ README.md                本文件：项目说明书
├─ AGENTS.md                ★ Agent 行为契约（边界 / 禁令 / 验证 / 求助）
├─ code/                    可复用代码
│  ├─ cli.py                统一入口（组 → 脚本映射 + preset，不含业务逻辑）
│  ├─ common/               共享库：paths（路径唯一来源）、anki_api（Anki 读写唯一接口）、
│  │                        textio（文本 I/O 与编码唯一入口）、check_*（自检器）、ruby_engine
│  ├─ execution/            执行区：episode / pipeline / mine / mine_audio / today_new /
│  │                        cards / activate / core6000_example / ainote_enrich /
│  │                        proper / immersionkit / filter_subtitle
│  ├─ tools/                工具区：doctor、temp 清理、edge-TTS、音频自检、备份、字幕打标、jisho 例句
│  ├─ analysis/             分析区：today_weak、weak_*、vocab_cover/、anki_analyze/（离线孤岛）
│  ├─ tests/                回归测试（10 个独立脚本，见 §7）
│  └─ oneshot/              单次执行区：用完即弃的探针与一次性修复，不维护
├─ docs/                    手册与档案（architecture / pipeline-guide / deprecated / decisions / reports）
├─ data/                    输入与中间产物（snapshots、pipeline、vocab、core6000、immersion、
│                           vocab_cover、pylibs≈316 MB、freq、plans、evidence、dict/JMdict≈552 MB）
├─ output/                  生成物（daily 讲义、audio、vocab_cover、i1）
├─ subtitles/               原始字幕素材（vocab_cover 的输入）
├─ core6000-analysis/       独立子项目：core6000 听辨卡分析（自带脚本与 docx 报告）
├─ temp/                    ★ 唯一的一次性文件区（临时脚本 / dump / 日志）
├─ archive/experiments/     一次性的实验与旧证据（见其 README.md）
└─ .dsh/skills/             技能（一技能一任务：triage / generate / activate / mine / audio /
                            check-ruby / jiten-rank / proper-noun / subtitle-tag / daily-lesson /
                            daily-weak / core6000-example / jisho-example / jmdict-lookup / local-llm）
```

## 5. 一次字幕流水线

`cli.py episode` 把下面几步串起来（`--commit` 才真写；不加则全链演练）：

| 阶段 | 谁跑 | 产物 |
|---|---|---|
| 0–1 预处理 + 清理 | `pipeline.py prepare` → `triage` | 判弃无学习内容的卡；可选先跑 `filter_subtitle.py` 筛字幕 |
| 2 生成 | `pipeline.py gen` | `data/pipeline/gen/{input,output,manifest}.json`；`AINote` + `Sentence HTML` |
| 4 素材生词 | `mine.py` | `data/vocab/{mine_candidates.json,gen_mine/*}` → `0-素材生词` |
| 5 配音 | `mine_audio.py` | `output/audio/*.mp3` → 上传 Anki 媒体库 |
| 改标签 | `episode.py retag` | 把导入时的 `待标记` 换成正式集标签 |

运行记录落在 `data/pipeline/runs/<时间戳>-<集>.json`。每步的判据、批次建议、失败重试
见 [docs/pipeline-guide.md](docs/pipeline-guide.md)（60 KB，按节查，不必通读）。

## 6. 数据流

```
Anki 收藏 ──复制──> data/snapshots/…                    （分析用只读快照）

episode.py ──> pipeline.py（阶段 0-2）──> mine.py（阶段 4）──> mine_audio.py（阶段 5）
                                    └──> data/pipeline/gen/     data/vocab/      output/audio/

proper.py        ──> data/vocab/proper/<作品>_<集>/（专名卡，不进队列）
today_new.py     ──> output/daily/{cards_*.json, lessons/*, lesson_*.md}（直连本地模型）
core6000_example ──> 5 个字段 + output/audio/core6000/*.mp3
ainote_enrich    ──> 只写 AINote（旧值备份 data/ainote/backup_*.json）
analysis/        ──> docs/reports/*.md、data/vocab_cover/*、output/vocab_cover/*.png
```

## 7. 测试

10 个回归测试都是**独立脚本、纯离线**（不连网、不碰 Anki 写接口），秒级返回；
2026-10-26 复核全部通过。跑法：

```powershell
& $PY "$WS\code\tests\test_llm_out.py"     # 换一个文件名就是另一组
```

| 测试 | 挡什么 |
|---|---|
| `test_llm_out.py` | 本地模型产出吸收层：畸形 JSON、字段类型错、整组超预算、漏卡重问 |
| `test_mine_patch.py` | 阶段四 `merge-fix` 的前缀回退（2026-10-12 事故） |
| `test_immersionkit.py` | ImmersionKit 抓句链路纯函数：振假名对齐、标签、字段一致性 |
| `test_jisho_example.py` | Jisho 例句解析、token 边界匹配（体中/ヤニ）、注音对不齐兜底 |
| `test_jiten_rank.py` | `JitenAnimeRank` 查表与 6 位补零（文本序 = 数值序） |
| `test_proper_extract.py` / `test_proper_patch.py` | 专名抽取的确定性部分、专名卡字段规则 |
| `test_subtitle_tag.py` | 字幕打标的纯逻辑：跳过已复习词、只写 tags |
| `test_lesson_render.py` | 每日讲义口径：词形/读音、词性校正、同词合并、接续脏数据、计数自洽、讲解机械错 |
| `test_lesson_dict.py` | 每日讲义的 JMdict 纠错：读音不在词典读音表、词性冲突、他动/自动、词典不可用降级、渲染校正 |

跑完会在 `temp/test_*` 留下产物，属于正常（`temp/` 就是一次性文件区）。

## 8. 维护约定

以下是工作区的工程约定，人和代理都照此写代码。**给代理的硬性禁令、验证流程与求助条件
见 [AGENTS.md](AGENTS.md) §3 / §8**——两者冲突时以那里为准。

1. **代码放四区之一**：多步流程放 `execution/`，可复用能力放 `tools/`，诊断与报告放 `analysis/`；
   要被多处 import 的实现才放 `common/`。一次性的直接进 `temp/`。
2. **不写死路径**：用 `import paths as WSP`（`WSP.DATA_PIPELINE`、`WSP.TEMP` …）。
3. **一切文本 I/O 走 `textio`**：`import textio` 即接管 stdio 为 UTF-8；不手写 `sys.stdout.reconfigure`。
4. **碰 Anki 一律走 `code/common/anki_api.py`**：不允许第二份客户端、不允许直接
   `sqlite3.connect` live 收藏。自审：`& $PY "$WS\code\common\anki_api.py" audit`（0 = 干净）。
   例外仅 `code/analysis/anki_analyze/`、`code/oneshot/`、`code/tools/backup_anki.py`。
5. **一次性文件只有一个家**：`temp/`。任务做完 `cli.py temp clean`；长期产物写 `data/`（中间）
   或 `output/`（成品）。`doctor` 第 9 项会查根目录白名单与 `temp/` 积压。
6. **改行为前先体检**：`doctor` 退出码非 0 先修；改完保持 `anki_api.py audit` 与
   `textio.py audit --strict` 为 0。`docs/*.md` 头部必须有「状态：active ｜ 最后核实：YYYY-MM-DD」。

## 9. 备份与恢复

```powershell
& $PY "$WS\code\cli.py" backup --dest <备份盘>:\anki-backup-<日期>
```

硬规则：备份收藏库前**完全退出 Anki**；新备份校验通过后才删旧的。校验与恢复流程见
[docs/backup-sop.md](docs/backup-sop.md)（唯一权威版）。

## 10. 与 Agent 的边界

| | 本文件（README） | [AGENTS.md](AGENTS.md) |
|---|---|---|
| 读者 | 人 | 代理 |
| 内容 | 项目事实：是什么、怎么跑、怎么测、目录、维护约定 | 行为契约：角色与边界、禁令、验证命令、失败处理、求助条件、输出格式 |
| 语气 | 说明性 | 可执行（有命令、有退出码、有「必须先问」的清单） |

两者互相引用、**不互相复制**：项目事实以本文件为准，行为约束以 AGENTS.md 为准。
**若两者冲突**（例如本文件描述某操作可行、AGENTS.md 列为禁止），以 AGENTS.md 为准；
代理应**停止并询问用户**，不要在文档之间自行仲裁。

技能的清单与「哪个任务加载哪个技能」在 AGENTS.md §4；技能本体在 `.dsh/skills/`。

## 11. 已知事项

- **`data/pylibs/`（约 316 MB）**：工作区本地第三方库（SudachiPy + 词典 + matplotlib），
  删目录即卸载；重装 `code/oneshot/install_workspace_wheels.py`。
- **快照会过期**：`data/snapshots/` 每份登记在 `README.json`（用途/消费者/何时可删）。
  离线分析（`weak build-list`、`--source snapshot`）读的是快照，可能与 live 库差几天。
- **`code/analysis/anki_analyze/`**：离线诊断孤岛，需自备快照（先关 Anki 跑 `introspect.py`），
  见 [architecture §7](docs/architecture.md)。
- **`code/oneshot/`**：一次性脚本的历史堆积，不维护、不要照抄。
- **根目录 `_tmp_*.py`**：历史遗留的一次性脚本，`doctor` 会提示；新的一次性文件请进 `temp/`。
- **仓库边界**：`.gitignore` 只放行「源码 / 文档 / 技能 / 模板 / 字幕」。`data/`（除 `card_templates/` 与
  `anki_addon/`）、`output/`、`core6000-analysis/`、`archive/`、`temp/`、`docs/reports/` 都不进 git——
  前几项是卡片资料或可重跑的产物，`docs/reports/` 含个人学习数据。清单见 [data/README.md](data/README.md)。

## 12. 文档索引

| 文档 | 讲什么 |
|---|---|
| [AGENTS.md](AGENTS.md) | **Agent 行为契约**：边界、铁律、技能路由、阅读预算、验证与求助 |
| [docs/architecture.md](docs/architecture.md) | 代码分区、六条约定、doctor、vocab_cover、Jiten 词频序、环境踩坑 |
| [docs/pipeline-guide.md](docs/pipeline-guide.md) | 字幕卡流水线操作手册（阶段 0-2、4-5 的判据与命令） |
| [docs/deprecated.md](docs/deprecated.md) | 已退场的机制与入口、恢复路径（**历史只记在这里**） |
| [docs/decisions/](docs/decisions/) | 关键决策 ADR |
| [docs/today_new-使用说明.md](docs/today_new-使用说明.md) | 每日讲义 |
| [docs/core6000-example-使用说明.md](docs/core6000-example-使用说明.md) / [design](docs/core6000-example-design.md) | 按需补例句 |
| [docs/ainote-enrich-使用说明.md](docs/ainote-enrich-使用说明.md) | 加强某张卡的 AINote 讲解 + 语感 |
| [docs/immersionkit-使用说明.md](docs/immersionkit-使用说明.md) | ImmersionKit 按词表抓例句卡/素材卡 |
| [docs/jiten-reorder-使用说明.md](docs/jiten-reorder-使用说明.md) | 插件 `jiten_reorder`：新卡按 JitenAnimeRank 排位 |
| [docs/proper-noun-使用说明.md](docs/proper-noun-使用说明.md) | 专有名词收集：原子能力 + `3-专有词汇` + 扁平标签 + 读法音频 |
| [docs/backup-sop.md](docs/backup-sop.md) | 备份 / 恢复 SOP（唯一权威流程） |
| [docs/jp-card-agent-instruction.md](docs/jp-card-agent-instruction.md) / [mine-agent-instruction.md](docs/mine-agent-instruction.md) | 阶段二 / 阶段四的提示词规范 |
| [docs/japanese-word-example-teaching.md](docs/japanese-word-example-teaching.md) | 单词例句教学口径（提示词来源） |
| [docs/troubleshooting/](docs/troubleshooting/README.md) | 排障与犯错经验：流水线坑表、事故复盘、本地模型防错 |
| `docs/reports/` | 分析报告（含个人学习数据，**本地保留、未入库**） |
| [archive/experiments/README.md](archive/experiments/README.md) | 归档实验索引（**未入库**） |
| [subtitles/README.md](subtitles/README.md) | 字幕目录的命名约定与 `anki/` 子目录说明 |
| [data/README.md](data/README.md) | `data/` 各子目录是什么、哪些能重建、为什么不入库 |
