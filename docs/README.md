# docs/ —— 文档索引与阅读预算

> 状态：active ｜ 最后核实：2026-11-10

**这是什么**：工作区所有手册、设计与历史的入口。**先在这里定位，再单点打开**：`grep` 找关键词，
`read` 带 `offset/limit` 只读那一节，不要整篇吞。历史与已退场机制只记 [deprecated.md](deprecated.md)。

## 想知道什么 → 读哪里

| 想知道什么 | 读哪里 | 成本 |
|---|---|---|
| Agent 的角色、地图与硬规则 | [../AGENTS.md](../AGENTS.md) | 小 |
| 代码结构、共享库、加脚本的规矩 | [../code/README.md](../code/README.md) | 小 |
| 牌组树、笔记类型、字段名、标签口径 | [anki-library.md](anki-library.md) | 小 |
| 数据流 / 流水线阶段 / 选词打分 / 覆盖率口径 / 测试矩阵 | [implementation.md](implementation.md) | 17 KB |
| 架构约定、代码分区、doctor 口径、环境坑 | [architecture.md](architecture.md) §1–3、§6 | 39 KB，按节 |
| 每集流水线的判据与命令 | [pipeline-guide.md](pipeline-guide.md) §0.4、§2 | 55 KB，按节 |
| 备份 / 恢复（唯一权威） | [backup-sop.md](backup-sop.md) | 18 KB |
| 排障顺序、踩坑与事故复盘 | [troubleshooting/README.md](troubleshooting/README.md) | 小，再进各篇 |
| 某功能怎么用 | `today_new-使用说明.md`、`core6000-example-使用说明.md`、`proper-noun-使用说明.md`、`immersionkit-使用说明.md`、`ainote-enrich-使用说明.md`、`jiten-reorder-使用说明.md` | 5–24 KB |
| 为什么这么设计 | [decisions/](decisions/README.md) | 按主题 |
| 改提示词 / 讲解规则 | [../code/execution/card_rules.md](../code/execution/card_rules.md)（正本）、[jp-card-agent-instruction.md](jp-card-agent-instruction.md)、[mine-agent-instruction.md](mine-agent-instruction.md)、[japanese-word-example-teaching.md](japanese-word-example-teaching.md)、[daily-lesson-agent-instruction.md](daily-lesson-agent-instruction.md) | 大，只在改提示词时读 |
| 已退场的旧入口 | [deprecated.md](deprecated.md) | 18 KB |
| 报告样板 | [reports/sample/](reports/sample/README.md) | 按需 |

`plans/`、`evidence/`、`reports/` 是历史档案，只用于追溯，不当现行说明；`reports/` 里除
`sample/` 外不入 git。

## 禁读（烧 token，或根本不是文本）

- `data/pylibs/**` —— 约 316 MB 工作区本地第三方库（含 Sudachi 词典）。
- `data/snapshots/**/*.anki2` —— 40–66 MB sqlite；查库用 `anki_api.Snapshot`。
- `core6000-analysis/cards_info.json`（54 MB）、`data/vocab_cover/study_plan_jiten_anime.json`（17 MB）、
  `data/evidence/subtitle_index.json`（7 MB）、`data/freq/jiten_freq_Anime.csv`（7 MB）。
- `temp/*.log`、`temp/*_utf8.txt` —— 旧任务日志，单份 30–100 KB。
- `output/*_newwords.md` —— 40–68 KB 长报告。
- `code/analysis/vocab_cover/` 的 20+ 分析脚本 —— 真要跑覆盖率时只读 `cover_cli.py`。

## 写文档的规矩

- `docs/**/*.md` 头部必须有「状态：active ｜ 最后核实：YYYY-MM-DD」；`doctor` 第 6 项会查。
- 新的「怎么做」写进对应专项手册；事故与坑写进 [troubleshooting/](troubleshooting/README.md)；
  退场机制写进 [deprecated.md](deprecated.md)，不要留在现行手册里。
