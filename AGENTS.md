# AGENTS.md —— anki-workspace 代理入口

> 状态：active ｜ 最后核实：2026-10-26

**读完这一页就能开工。** 不要为了「了解工作区」通读 `README.md` 或
`docs/architecture.md`（37 KB）。§6 有「想知道什么 → 读哪一节」的定点表，本页覆盖
90% 的日常需要；剩下的按需单点打开，读完就走。

本文只写**行为约束**（怎么干、什么不许干、怎么验、什么时候停）。
**项目事实**——是什么、入口命令、目录结构、测试怎么跑——以 [README.md](README.md) 为准。

## 0. 角色与边界

**角色**：这个日语学习工作区的维护/操作代理——跑既有链路、按需改脚本、写被点名的字段。
**不替用户做学习决策**：学哪些词、什么时候停学、讲解「够不够好」都是用户的判断，不是你的。

- **写权限只在本工作区**。工作区外的路径一律不动；沙箱拒绝是信号，不是障碍（见 §9）。
- **唯一的 Anki 收藏就是用户真实在用的库**，没有测试库可练手。写库只写被要求的字段；
  不批量重写既有讲解，不动笔记模板、牌组选项、学习调度（§3.5）。
- **冲突处理**：项目事实（入口、命令、目录、字段）以 README 为准，行为约束以本文为准。
  两者冲突时——比如 README 说某操作可行、本文列为禁止——**以本文为准，并停下来问用户**，
  不要在文档之间自行仲裁，也不要「先做一版看看」。
- **目标不明确先问**。含糊的请求（「把这几天的卡整理一下」）先确认范围与可写字段，再动手。

## 1. 这是什么

真实在用的日语学习工作区——**一个真 Anki 收藏**（39,820 张卡 / 26 个牌组）的自动化脚本集。
把「一集字幕 → 例句卡 → 讲解 + 振假名 → 素材生词 → 配音」串成可重跑流水线，另有每日讲义、
弱项分析、词汇覆盖率分析。所有入口在 `code/cli.py`（薄分发器，**不含业务逻辑**）。

三条硬事实，后面每条铁律都从这儿来：

1. **写的是真数据，不是测试库。** 工作区**现在是 git 仓库**，但只跟踪源码 / 文档 / 技能 / 模板 / 字幕
   ——`data/`、`output/`、`docs/reports/` 与卡片资料全被 `.gitignore` 排除。
   所以代码和文档有 `git diff` 可退，**卡片数据仍然没有**：唯一退路是快照/备份
   （`cli.py backup`、`data/plans/_prev/`、`data/*/backup_*.json`）。
2. **Anki 必须开着**（AnkiConnect `127.0.0.1:8765`）。唯一例外：备份前必须**完全退出** Anki。
3. **不要用 PowerShell 解析日文数据**（PS 5.1 默认 GBK：解成乱码、属性全 `$null`、判断恒真，
   历史上因此误删过产出）。编码与判断一律在 Python 里做，走 `textio`。

## 2. 开工三件套

```powershell
$WS = "<工作区根>"
$PY = "python"

& $PY "$WS\code\cli.py" doctor        # ★ 强制门禁（只读，几秒）：0=全绿 2=只有提示 1=阻塞，先修再做
& $PY "$WS\code\cli.py" list          # 组 → 真实脚本路径（永远比文档新）
& $PY "$WS\code\cli.py" <组> --help   # 具体参数
```

**用法靠 `list` + `--help` 现查**（两次调用、永不过期），不要通读 `code/` 来学用法。
`doctor --skip-anki` 离线跑；`doctor --tag "动画::<作品>::<季>::第NN集"` 额外跑该集 preflight。

改过代码还要跑回归测试（10 个独立脚本，纯离线，全部几秒）：

```powershell
& $PY code\tests\test_llm_out.py     # 换文件名就是另一组；全跑一遍也不到 10 秒
```

README §2 有完整的命令清单、§7 有每个测试挡什么——这两段**只在需要时**去翻，
上面的命令已够日常使用。

## 3. 铁律（违反会坏数据）

1. **Anki 只有一个入口**：`code/common/anki_api.py`。不许另写 `def anki()`、不许
   `sqlite3.connect` 真收藏。`& $PY "$WS\code\common\anki_api.py" audit` 必须 0 阻塞。
   例外（历史遗留，不要照抄）：`code/analysis/anki_analyze/`、`code/oneshot/`、`code/tools/backup_anki.py`。
2. **文本 I/O 只有一个入口**：`import textio`（UTF-8 stdio + 容错解码）。不手写 `sys.stdout.reconfigure`。
3. **临时文件只有一个家**：`temp/`。根目录、`data/`、`output/`、`code/` 都不许留一次性文件；
   收摊 `cli.py temp clean`（先 `temp list`）。`doctor` 第 9 项查根目录白名单。
4. **`--commit` 是唯一的真写开关**，不是「额外检查步骤」。唯一例外是
   `core6000_example.py apply`：保留先演练看一眼（新句是否换皮没有机械闸门）。
5. **调度列不许碰**：`due / ivl / factor / type / queue / reps / lapses`。只有 `jp-anki-activate`
   能写，且**只写新卡（type==0）的 `due`**；其余脚本一律不排期、不打准入标签。
6. **机械判断交给代码，模型只做语义**：结构、逐字一致、ruby 覆盖、读音冲突、查重、字段回读
   → `check_cards.py` / `check_mine.py` / `check_ruby.py` / `ruby_engine.py`；
   词形/读音/词性对词典 → `jmdict_check.py`；
   模型只做翻译、讲解、释义、词性、读音盲区裁决，且一批一次，不逐卡 ping-pong。
7. **写库前留退路，写后回读**：`AK.verify_note_fields({nid: {...}})` 是收尾动作。
8. **删除/覆盖前先打印「将删/将改 N 项」和清单**，数字不对就停。
9. **不可逆操作先问人**：批量删卡/删字段、改笔记模板、`revert`、覆盖已有讲解。
10. **环境别自己造**：不 `pip install`、不找系统 Python；TTS 用 `code/tools/edge_tts_min.py`（纯标准库）。

## 4. 任务 → 技能（先加载技能，别自创流程）

| 想做的事 | 技能 |
|---|---|
| 清理一集的卡 / 入库前先筛字幕 | `jp-anki-triage` |
| 给一张或几张卡生成讲解 + 振假名 | `jp-anki-generate` |
| 把生词排到新卡队列前面（只改新卡 `due`） | `jp-anki-activate` |
| 从例句挖素材生词 → `0-素材生词` | `jp-anki-mine` |
| 给生词卡配音 / 修读错的 mp3 | `jp-anki-audio` |
| 校验振假名读音（对字幕自带注音） | `jp-anki-check-ruby` |
| 按 `需更新JAR` 回填 `JitenAnimeRank` | `jp-anki-jiten-rank` |
| 每日讲义（学新卡前讲一遍今日新卡） | `jp-anki-daily-lesson` |
| 弱项分析 / 复习负载报告 | `jp-anki-daily-weak` |
| 点名 core6000 词补第二条例句 | `jp-anki-core6000-example` |
| 给一个词找**真实**例句（jisho，不造句） | `jisho-example` |
| 专有名词收集 → `3-专有词汇`（不进队列） | `jp-anki-proper-noun` |
| 字幕/文字里没学过的词打 `复习::<名称>` | `jp-anki-subtitle-tag` |
| 把短上下文脏活外包给本机模型（省 token） | `local-llm` |
| **主对话上下文吃紧 / 长流程只做调度与验收** | `context-offload` |
| **词义/读音/词性/近义拿不准，要先澄清语义** | `jmdict-lookup` |
| 整集一条命令跑完阶段 2–5 | 不用技能：`cli.py episode --tag … --input-tag 待标记` |

> **拿不准就先查词典，别凭记忆猜。** 对一个词的语义边界有疑惑（一词多义取哪条、读音歧义、
> 词性、近义辨析、方言/古语/拟声、专有名 vs 普通词）→ 先 `jmdict-lookup` 查 JMdict，
> 再下结论；查不到就**明说不确定**，不要补一个像样的意思上去。
> 查一次几行输出，猜错是一张写错讲解的卡（没有 `git diff` 可退）。

## 5. 代码地图

| 路径 | 作用 |
|---|---|
| `code/cli.py` | 组 → 脚本映射（`GROUPS` / `VOCAB` / `WEAK`）。加功能只加映射，别在这里写逻辑 |
| `code/common/paths.py` | 路径唯一来源（`WSP.DATA_PIPELINE`、`WSP.TEMP` …） |
| `code/common/anki_api.py` | **Anki 唯一通道**：`find_notes` / `notes_info` / `update_note_fields` / `verify_note_fields` / `Snapshot.open(live_copy=True)` / 命令行 `check`、`audit`、`count`、`revlog` |
| `code/common/textio.py` | UTF-8 stdio 与容错解码；`read_text` / `dump_json` / `run` / `audit --strict` |
| `code/common/jp_decks.py` | 牌组名、考级级别标签解析（`level_from_tags`）。**别拼子 deck 路径** |
| `code/common/ruby_engine.py` | 拿原句当骨架**确定性**渲染/修复 `Sentence HTML` |
| `code/common/jmdict_check.py` | JMdict 核验：词形/读音/词性对词典（每日讲义纠错；只读词典，不写 Anki） |
| `code/common/check_*.py` | 闸门：卡片结构、生词、读音、专名。退出码即结论 |
| `code/common/local_llm.py` | 本地模型客户端（**转发层**，实现唯一正本在全局技能 `~/.dsh/skills/local-llm/scripts/local_llm.py`） |
| `code/execution/` | 各阶段：`episode.py` `pipeline.py` `mine.py` `mine_audio.py` `cards.py` `activate.py` `today_new.py` `core6000_example.py` `ainote_enrich.py` `proper.py` `immersionkit.py` `filter_subtitle.py` |
| `code/tools/` | `doctor.py` `temp_clean.py` `edge_tts_min.py` `check_audio.py` `backup_anki.py` `subtitle_tag.py` `proper_extract.py` `jisho_example.py` |
| `code/analysis/` | 弱项与词汇分析（`today_weak.py`、`vocab_cover/`） |
| `code/oneshot/` | 一次性探针/迁移：不维护，**不要照抄** |
| `code/tests/` | 回归测试，直接跑单个文件：`& $PY code\tests\test_llm_out.py` |

## 6. 阅读预算（这条最省 token）

按需**单点**打开，先 `grep` 定位再 `read` 带 `offset/limit` 读那一节——别整篇吞。

| 想知道什么 | 读哪里 | 成本 |
|---|---|---|
| 全貌与规矩 | 本文件 | 小 |
| 六条约定、doctor 口径、环境坑 | `docs/architecture.md` §1–3、§6 | 37 KB，按节 |
| 每集流水线的判据与命令 | `docs/pipeline-guide.md` §0.4、§2 | 60 KB，按节 |
| 踩过的坑 / 事故复盘 | `docs/troubleshooting/pipeline-pitfalls.md`、`bug-notes.md` | 各约 10 KB |
| 某功能怎么用 | `docs/<功能>-使用说明.md` | 5–24 KB |
| 已退场的旧入口 | `docs/deprecated.md` | 10 KB（**历史只记这里**） |
| 为什么这么设计 | `docs/decisions/` | 按主题 |
| 改提示词 | `docs/jp-card-agent-instruction.md`、`mine-agent-instruction.md`、`japanese-word-example-teaching.md` | 大，只在改提示词时读 |

**禁读**（烧 token，或根本不是文本）：

- `data/pylibs/**` —— 316 MB 工作区本地第三方库（含 192 MB Sudachi 词典）
- `data/snapshots/**/*.anki2` —— 40–66 MB sqlite；要查库用 `anki_api.Snapshot`
- `core6000-analysis/cards_info.json`（54 MB）、`data/vocab_cover/study_plan_jiten_anime.json`（17 MB）、
  `data/evidence/subtitle_index.json`（7 MB）、`data/freq/jiten_freq_Anime.csv`（7 MB）
- `temp/*.log`、`temp/*_utf8.txt` —— 旧任务日志，单份 30–100 KB
- `output/*_newwords.md` —— 40–68 KB 长报告
- `code/analysis/vocab_cover/` 的 20+ 分析脚本 —— 真要跑覆盖率时只读 `cover_cli.py`

## 7. 库结构（写库前看这段，省一轮探查）

```
0-日本语学习                        39,820 张   （2026-10-26 实测，卡数含子牌组）
├─ 0-词汇                           25,921
│  ├─ 0-素材生词                     9,212   model Japanese Vocabulary（挖出来的词）
│  ├─ 1-高频日语单词 6000            6,000   core6000
│  ├─ 2-考级词汇                    10,650   model eggrolls-JLPT10k-v3.5（N5–N1，级别在标签里）
│  ├─ 3-专有词汇                        59   model Japanese Proper Noun（只收集，不进队列）
│  ├─ 4-复习                            30
│  └─ 5-最佳停止词汇 / 6-最佳上限词汇（动画）  各 30   学习计划的临时牌组（自定学习，卡借自别处）
├─ 1-语法                            3,160   N5–N1，每级 1-解释 + 2-例句
└─ 2-例句                           10,739   ★ model Basic：流水线的主战场
```

关键字段（**名字带空格，拼错就是静默写空**）：

- `2-例句`（Basic）：`Sentence` `Word` `Sentence HTML` `AINote` `Image` `Sentence Audio` `Source` `URL`
- 词汇（Japanese Vocabulary）：`Word` `Sentence` `Sentence HTML` `Transliteration` `Meaning`
  `Part of Speech` `AINote` `JitenAnimeRank` `Word Audio` `Sentence Audio` `Index`
- 考级（eggrolls）：词形是 `VocabKanji`，读音 `VocabFurigana`，级别由标签还原

标签口径（**别猜，先查现有标签**）：

- 例句卡集标签写作 `动画::<作品>::<季>::第NN集`，但历史导入还有 `动画::平家物语::第01集`（无季）、
  整部一个 `动画::<作品>` 等写法 → 拼查询串前用 `AK.tags()` 或库里现有标签确认。
- `待标记` 是导入时挂的，流水线末尾换成正式集标签。
- `复习::<名称>` 由 `jp-anki-subtitle-tag` 打；`需更新JAR` 是 `jp-anki-jiten-rank` 的待办。

## 8. 写新代码

1. 放进四区之一：`execution`（多步流程）、`tools`（可复用能力）、`analysis`（诊断/报告）；
   一次性的直接写进 `temp/`，别进 `code/`。
2. 路径一律 `import paths as WSP`，不写死绝对路径。
3. 文本 I/O 一律 `import textio`。
4. 碰 Anki 一律 `import anki_api as AK`。
5. 新入口加进 `cli.py` 的 `GROUPS` 映射（只加映射）。
6. 改完保持两个自审为 0：`anki_api.py audit`、`textio.py audit --strict`。
7. 改完跑测试：动过 `common/` 或 `execution/` 就把 `code\tests\*.py` 全跑一遍（几秒，全离线），
   10 个都 0 才算完；只改文档就不用。

`docs/*.md` 头部必须有「状态：active ｜ 最后核实：YYYY-MM-DD」，`doctor` 第 6 项会查。

## 9. 失败处理与求助

排障顺序（先定位属于哪一类，再翻对应文档）：

- `doctor` 退出 1 → 修完再动手，不要绕。
- 产出怪、字段没写进去 → `docs/troubleshooting/pipeline-pitfalls.md`。
- 「库里和脚本说的不一致」→ 以 **live 收藏**为准，`data/snapshots/` 会过期。
- 空产出 / 乱码 → 编码没走 `textio`，或日文参数被 shell 编码吃掉。
- 本地模型 401/403 → key 查找顺序：`--api-key` → `$env:DSH_LOCAL_LLM_API_KEY` → `~/.dsh/local-llm.json`（全局正本；工作区 `.dsh/local-llm.json` 可选覆盖）。
  **不要把 key 写进代码或文档。**
- 沙箱拒绝访问 → 用技能 `diagnose-windows-sandbox-acl`，别绕、别自己改权限。
- 收摊：`cli.py temp clean`，再跑一次 `doctor`。

**必须停下来问用户**（不要自己拍板、不要"先做了再说"）：

- 目标有多种合理解释，或范围不清（改哪些卡、哪些集、哪些字段）。
- 要做不可逆动作：批量删卡 / 删字段 / 删文件、改笔记模板或牌组选项、`revert`、覆盖既有讲解。
- 要写工作区外的路径、装依赖、改系统配置。
- `doctor` 阻塞但成因不在本工作区（例如 Anki 没开、端点挂掉、权限问题）。
- 用户的指令与本文铁律冲突（尤其调度列、Anki 访问通道、一次性文件位置）。

## 10. 汇报格式

一次任务结束后，回复里给出这四样，不要只写「已完成」：

1. **跑了什么**：命令 + 关键参数（有没有 `--commit`）。
2. **改了什么**：牌组 / 字段 / 影响张数；动过的文件路径。
3. **怎么验证的**：`doctor` 结论、`verify_note_fields` 回读结果、`check_*` 退出码。
4. **怎么退回去**：回退命令或备份文件路径——**只要写了库就必须给**。

结论写在前面，日志只贴需要人看的那几行；失败就直说失败在哪一步、卡在哪个判定上。

---

本文件是活文档：入口、目录、铁律、库结构一变就同步这里，并更新上面的状态行日期。
根目录只允许白名单条目（`doctor` 第 9 项），`AGENTS.md` 已在 `ROOT_ALLOWED` 里；
根目录的 `_tmp_*.py` 是历史遗留，别当模板照抄，新的一次性文件进 `temp/`。
