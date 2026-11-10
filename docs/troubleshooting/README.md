# troubleshooting —— 排障与犯错经验（与工作文档分开）

> 状态：active ｜ 最后核实：2026-11-10

**这是什么**：这个工作区里出过的错、踩过的坑，以及各自怎么判、怎么修、怎么防。
**为什么存在**：操作手册只讲“该怎么做”，但真正让人返工的是“哪里会悄悄坏”。
把这些从手册里拆出来，手册才能保持短；出问题时又有地方可查。
**什么时候读**：脚本出怪结果、写库前后对不上、模型产出可疑时先翻这里；
开工前扫一眼各篇的「坑」表，比事后救火便宜。

## 先按这个顺序排障

1. `doctor` 退出 1 → 修完再动手，不要绕。
2. 产出怪、字段没写进去 → 先看 [pipeline-pitfalls.md](pipeline-pitfalls.md) 对应阶段。
3. 「库里和脚本说的不一致」→ 以 **live 收藏**为准；`data/snapshots/` 会过期。
4. 空产出 / 乱码 → 编码没走 `textio`，或日文参数被 shell 编码吃掉（见
   [../architecture.md §6](../architecture.md)）。
5. 本地模型 401/403 → key 查找顺序：`--api-key` → `$env:DSH_LOCAL_LLM_API_KEY` →
   `~/.dsh/local-llm.json`（全局正本；工作区 `.dsh/local-llm.json` 可选覆盖）。
   **不要把 key 写进代码或文档。**
6. 收摊：`cli.py temp clean`（先 `temp list`），再跑一次 `doctor`。

排障到要动不可逆操作、或成因不在本工作区（Anki 没开、端点挂掉、权限问题）——**停下来问用户**。

| 文件 | 讲什么 |
|---|---|
| [pipeline-pitfalls.md](pipeline-pitfalls.md) | 字幕卡流水线（阶段 0-6）踩过的坑：编码、AnkiConnect、ruby、匹配、TTS |
| [bug-notes.md](bug-notes.md) | 事故复盘：现象 → 根因 → 修法 → 回归测试在哪（阶段四本地模型链路为主） |
| [local-llm-guardrails.md](local-llm-guardrails.md) | 本地模型链路的防错体系：五道防线、提示词硬约束、重试与留证 |

**不在这里**：当前该怎么做看 [../pipeline-guide.md](../pipeline-guide.md)；
已退场的机制看 [../deprecated.md](../deprecated.md)；环境本身的限制（PowerShell/GBK、
沙箱、pip）见 [../architecture.md §6](../architecture.md)。
