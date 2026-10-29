# anki-workspace

> 状态：active ｜ 最后核实：2026-10-30

一个「日语学习 × Anki」自动化工作区：把「看动画 → 做卡 → 复习 → 查漏」串成可重跑的脚本，
而不是每次手工整理。当前收藏 **39,820 张卡 / 26 个牌组**，所有入口都在 `code/cli.py`。

| 你想… | 从哪开始 |
|---|---|
| 直接拿它学日语 | §2 五分钟上手 → §3 每天怎么用 |
| 把一集新番字幕做成卡 | §4 新素材：一集字幕变卡 |
| 只想要牌组文件 | §11 整库下载 |
| 改脚本 / 核对某个数字怎么算 | [docs/implementation.md](docs/implementation.md) |
| 让 AI 代理替你操作 | [AGENTS.md](AGENTS.md)（行为契约） |

本文件面向**使用者**：是什么、怎么装、每天怎么用、出问题去哪看。实现方式与内部细节在
[docs/implementation.md](docs/implementation.md) 与各专项手册；Agent 的行为契约在
[AGENTS.md](AGENTS.md)。

---

## 1. 这是什么

**为「提升日语动画听力」而建**——目标是甩开字幕听懂对白，而不是应付考试。
打底是两套成熟考级牌组（`1-高频日语单词 6000`、`2-考级词汇` N5–N1）覆盖日常日语的骨架；
动画对白还有考级词表查不到的词汇面（拟声拟态、口语缩略、题材词、俚语），
于是第三个牌组 `0-素材生词`：从看过的字幕里挖「**考级牌组里没有、但 Jiten 动画词频里常见**」的词收进去——
**这是本工作区最主要的服务功能**。

| 主线 | 你给它 | 它给你 |
|---|---|---|
| 每集流水线 | 一集字幕（`.ass/.srt`） | 例句卡 → 清理 → 讲解 + 振假名 → 素材生词 → 配音 |
| 每日链路 | 当天字幕（自动选 30 个词） | tag `今天学习生词`、日语讲义、复习后的弱项报告 |
| 词汇分析 | 字幕语料 + 现有卡组 | 覆盖率、新词表、挖掘窗口建议、跨作品通用性判定 |
| 收集类 | 一段文字 / 一集字幕 | 专有名词卡（`3-专有词汇`，不进队列）、`复习::<名称>` 标签 |

它会替你做机械活，但**不替你做学习决策**，也不碰你的复习进度：

| 它会 | 它不会 |
|---|---|
| 清理无学习内容的卡、生成振假名与讲解、配音 | 决定你学哪些词、什么时候停学 |
| 按词频挑出今天该学的 30 个词 | 改 `due/ivl/factor/type` 等调度列、牌组选项、笔记模板 |
| 挖字幕生词、出覆盖率与弱项报告、一键备份 | 覆盖你已有的讲解（默认演练，`--commit` 才写） |

### 三个牌组，三种卡

三个牌组问的不是同一件事：素材生词练**听辨**（词音频先响，认词形与意思），考级词汇练**看字回想**
（只看词形，回想读音和释义），`2-例句` 练**整句**（画面 + 原声 → 句子和讲解）。下面三张都是翻面后的
答案面：

<table>
  <tr>
    <td align="center" width="33%"><img src="docs/images/card-1-listening.png" width="240" alt="0-素材生词：听辨卡"></td>
    <td align="center" width="33%"><img src="docs/images/card-2-recall.png" width="240" alt="2-考级词汇：看字回想卡"></td>
    <td align="center" width="33%"><img src="docs/images/card-3-sentence.png" width="240" alt="2-例句：例句卡"></td>
  </tr>
  <tr>
    <td align="center" valign="top"><b>听辨卡</b><br><code>0-素材生词</code></td>
    <td align="center" valign="top"><b>看字回想卡</b><br><code>2-考级词汇</code></td>
    <td align="center" valign="top"><b>例句卡</b><br><code>2-例句</code></td>
  </tr>
</table>

- **听辨卡（`0-素材生词`）**：正面只有词形和词性，词音频自动播放；翻面给读音、词性释义、
  挖出这个词的那句台词（带振假名）、动画画面和讲解。底部 `[动画-002505][全局-004673]` 是
  Jiten 词频——挖词时先按这个排名决定收不收、先不先学。
- **看字回想卡（`2-考级词汇`）**：正面给词形和原句音频，读音与释义要自己先想；翻面才给读音、
  音调、词性、中文释义与例句。底部同样是 Jiten 词频。
- **例句卡（`2-例句`）**：正片画面 + 原声提问，翻面是带振假名的整句、中文翻译、核心词汇与语法要点
  ——就是上面第三张图；**画面与字幕是素材，讲解文字才是工作区生成的**。

> **听辨卡不止一个牌组**：`0-素材生词` 和 `1-高频日语单词 6000`（core6000）共用同一个笔记类型
> `Japanese Vocabulary` 与同一个模板（`Word → Meaning`），卡面完全一样——区别只在词的来源：
> 一个从看过的字幕里挖，一个来自 Core 6000 词表。

---

## 2. 五分钟上手

### 2.1 三样东西

| 需要 | 为什么 | 怎么准备 |
|---|---|---|
| **Anki + AnkiConnect** | 脚本通过 `127.0.0.1:8765` 读写收藏 | 装 Anki 2.1.x，再装插件 AnkiConnect（代码 `2055492159`）；用的时候保持 Anki 打开 |
| **Python 3** | 跑 `code/` 下的脚本 | 装 Python 3（建议 3.10+）；第三方库放在工作区 `data/pylibs/`，不污染系统环境 |
| **本地模型**（可选） | 生成讲解、挖词、选词时的义项判定 | OpenAI 兼容端点 `http://127.0.0.1:8080/v1`；不跑模型时，体检 / 覆盖率 / 弱项 / 找例句等只读命令照常可用 |

> 唯一的例外：跑**备份**前要**完全退出** Anki（见 §8）。

### 2.2 三步跑起来

```powershell
$WS = "<工作区根>"      # 换成这个目录的绝对路径
$PY = "python"          # 换成你的 Python 3

& $PY "$WS\code\cli.py" doctor          # ① 体检：0=全绿 2=只有提示 1=有阻塞
& $PY "$WS\code\cli.py" list            # ② 看有哪些入口（永远比文档新）
& $PY "$WS\code\cli.py" <组> --help     # ③ 查具体参数
```

`doctor` 一次跑完九项：AnkiConnect、Anki 访问点自审、`textio` 编码自审、废弃符号、快照卫生、
文档状态行、每集 preflight、环境与依赖、工作区卫生；**退出码 1 就先修再动手**。各项口径见
[architecture §3](docs/architecture.md)。

**没有现成收藏？** 先下 §11 的三个 `.apkg` 导入 Anki。**已有自己的库？** 直接导入同一套牌组即可；
工作区按牌组名、笔记类型和字段名取数据（写死在 `code/common/jp_decks.py` 与各脚本里），
结构不同的库需要先改这些常量。缺依赖时 `doctor` 会提示，装库入口是
`code\oneshot\install_workspace_wheels.py`。

---

## 3. 每天怎么用

一天的典型节奏：

| 时间 | 做什么 | 命令 |
|---|---|---|
| 早上 | 选今天学的 30 个词 | `cli.py today-new "subtitles\<作品>" --commit` |
| 早上 | 生成讲义 | `cli.py daily stats` → `plan` → `check` → `gen` |
| 白天 | 打开 Anki 学 | — |
| 晚上 | 看今天答得不好的词 | `cli.py weak today --days 3 --plain` |
| 周末 | 出库层面分析 | `cli.py r report` |

### 3.1 早上：今天学哪些词

给一集字幕或整部作品的目录，脚本扫**整部作品**（同目录所有集），按「本作出现次数 + 跨集数 +
Jiten 动画词频」打分，挑出 30 个**已有卡、还没学**的词，打上 tag `今天学习生词`：

```powershell
& $PY "$WS\code\cli.py" today-new "subtitles\Yani Neko"            # 演练，只打印名单
& $PY "$WS\code\cli.py" today-new "subtitles\Yani Neko" --commit   # 真写标签
& $PY "$WS\code\cli.py" today-new --revert --commit                # 撤销上一次
```

每次运行会先把全库旧标签摘掉，所以这个 tag 永远只代表「今天这一批」；**只写标签**，不动
`due/ivl/type`。名单落在 `output/daily/today_new_words.md`，分数与义项判定在
`data/daily_new/<日期>/picked.json`。想调权重用 `--mu`（跨集加成）/ `--lam`（词频权重）；
打分公式、读音与义项两道闸门见 [implementation §3](docs/implementation.md)。

### 3.2 早上：把词变成讲义

```powershell
& $PY "$WS\code\cli.py" daily stats     # tag 今天命中几个词；0 就收工
& $PY "$WS\code\cli.py" daily plan      # 取词 + 查 JMdict（读音 / 词性 / 义项事实）
& $PY "$WS\code\cli.py" daily check     # 复核词典；退出码 0/1/2/3
& $PY "$WS\code\cli.py" daily gen       # 本地模型生成讲义
```

产物是 `output/daily/lesson_latest.md`（当天讲义）与 `lesson_<日期>.md`。
**这条链只读 Anki、不写库**，做坏了删文件重跑即可；没有 tag 就什么都不生成。细则见
[today_new-使用说明](docs/today_new-使用说明.md)。

### 3.3 晚上：看今天哪里没记住

```powershell
& $PY "$WS\code\cli.py" weak today --days 3 --plain   # 今天 / 近三天答得不好的词与语法
```

`weak` 还有 `revlog`（自评按钮校准）、`pace`（每牌组复习量与单卡耗时）、`build-list`（弱词清单）。
默认读 AnkiConnect 实时数据，加 `--source snapshot` 可离线跑（但快照可能过期）。

### 3.4 想系统地看一眼

```powershell
& $PY "$WS\code\cli.py" r summary     # 留存 / 健康分 / 负荷概览（R 包 ankiR，只读）
& $PY "$WS\code\cli.py" r due         # 按 Anki 口径重算的到期与未来负荷
& $PY "$WS\code\cli.py" r report      # 完整分析报告
```

`r` 这组命令只读，需要本机装 R 与 `ankiR`；数据默认取 live 收藏，报告会写明「数据截至」。
词汇覆盖率与学习计划另有 §5 那套 Python 链路。

---

## 4. 新素材：一集字幕变卡

以 asbplayer 导入 Anki、挂 `待标记` 标签的例句卡为起点。先清理，再一条命令跑完剩下的阶段：

```powershell
# ① 清理：判掉没有学习内容的卡；只想筛字幕可先跑 filter_subtitle
& $PY "$WS\code\cli.py" pipeline prepare
& $PY "$WS\code\cli.py" pipeline triage --query "tag:待标记"

# ② 阶段 2–5 一条命令（默认全链演练，只打印不写库）
& $PY "$WS\code\cli.py" episode --tag "动画::<作品>::<季>::第NN集" --input-tag 待标记

# ③ 看过演练结果再真写
& $PY "$WS\code\cli.py" episode --tag "动画::<作品>::<季>::第NN集" --input-tag 待标记 --commit
```

- 阶段 2 生成 `AINote` + 振假名，阶段 4 挖素材生词，阶段 5 给生词配音，最后把 `待标记` 换成正式集标签。
- 只跑某几步：`--phases ruby,rank`；字幕自带注音是读音的权威来源，有 `.srt` 时用 `--srt` 传进去。
- 产物与断点续跑在 `data/pipeline/`、`data/vocab/`、`output/audio/`；每步的判据与失败重试见
  [pipeline-guide](docs/pipeline-guide.md)（60 KB，按节查即可）。

**换新作品**：字幕目录命名与 `anki/` 子目录约定见 [subtitles/README.md](subtitles/README.md)。
集标签一般是 `动画::<作品>::<季>::第NN集`，但历史导入还有 `动画::<作品>::第01集`（无季）、
整部一个 `动画::<作品>` 等写法——拼查询串前先看库里现有标签。

---

## 5. 量一量：我认识多少、还差哪些词

输入任意 `.srt/.ass/.vtt`、`.txt`、一段话或标准输入，就能回答「这段文字我懂多少」：

```powershell
& $PY "$WS\code\cli.py" vocab cover "subtitles\Yani Neko\ヤニねこ.S01E01.ニャーがヤニねこにゃ.WEBRip.Netflix.ja[cc].srt"
& $PY "$WS\code\cli.py" vocab newwords "subtitles\Yani Neko" --mine-only
& $PY "$WS\code\cli.py" vocab report "subtitles\Yani Neko"              # 学习用生词报告
& $PY "$WS\code\cli.py" vocab mine_window --k 3                         # 只挖前 N 集值不值
```

词汇状态来自 AnkiConnect 现场快照，换素材不用动卡组。**报告里会写清三个分母**——含语法词 /
词汇词 / 需背实词，「已学」= 刷过至少一次，「已成熟」= 复习卡且间隔 ≥ 21 天；Jiten 名次按
「出现在多少部作品里」排，不按单部重复次数。完整命令矩阵与口径见
[implementation §4](docs/implementation.md)，字段和算法见 [architecture §4-5](docs/architecture.md)。

---

## 6. 其它常用能力

| 想做什么 | 命令 | 写库？ |
|---|---|---|
| 给 core6000 词补第二条例句 | `cli.py core6000 gen --words "徹夜,適当"` → `tts` → `apply --commit` | 是（演练默认） |
| 给一个词找**真实**例句（不造句） | `cli.py jisho --word "徹夜" --reading "てつや"` | 只读 |
| 加强某张词汇卡的讲解与语感 | `cli.py ainote enrich --word 分際 --commit` | 是（只写 `AINote`） |
| 按词表抓 ImmersionKit 对白例句 | `cli.py immersion fetch` → `gen` → `write --to both --commit` → `verify` | 是（演练默认） |
| 收集一集的专有名词 | `cli.py proper scan/gen/verify/write`（只收集，不进队列） | 是（演练默认） |
| 给字幕里的生词打 `复习::<名称>` | `python code\tools\subtitle_tag.py <字幕> --name <名称> --commit` | 只写 tags |
| 回填 Jiten 词频字段 | `python code\analysis\vocab_cover\freq_external.py field --tag "需更新JAR" --remove-tag` | 是（演练默认） |
| 按 Jiten 名次重排新卡顺序 | Anki 插件 `jiten_reorder`，见 [docs](docs/jiten-reorder-使用说明.md) | 只改新卡 `due` |
| 收摊：清一次性文件 | `cli.py temp list` → `temp clean` | 删 `temp/` |

`cli.py list` 是**权威用法来源**；每个命令的参数用 `cli.py <组> --help` 现查。未纳入统一入口的脚本
（如 `vocab_cover/` 里的数据链零件）直接调用，见 [architecture §2](docs/architecture.md)。

---

## 7. 目录结构

```
anki-workspace/
├─ README.md                本文件：给使用者的说明书
├─ AGENTS.md                ★ Agent 行为契约（边界 / 禁令 / 验证 / 求助）
├─ code/                    可复用代码：cli.py（统一入口，薄分发器）
│                            + common / execution / tools / analysis / tests / oneshot
├─ docs/                    手册与档案（implementation / architecture / pipeline-guide /
│                            decisions / troubleshooting / images / reports）
├─ data/                    输入与中间产物（snapshots、pipeline、vocab、pylibs、freq、plans、dict）
├─ output/                  生成物（daily 讲义、audio、vocab_cover）
├─ subtitles/               原始字幕素材（vocab_cover 的输入）
├─ core6000-analysis/       独立子项目：core6000 听辨卡分析（本地生成，未入库）
├─ temp/                    ★ 唯一的一次性文件区（临时脚本 / dump / 日志）
├─ archive/experiments/     一次性的实验与旧证据（未入库）
└─ .dsh/skills/             技能（一技能一任务；任务 → 技能路由表在 AGENTS.md §4）
```

代码地图与每个脚本的职责见 [AGENTS.md §5](AGENTS.md) 和 [architecture §1](docs/architecture.md)。

---

## 8. 备份与恢复

```powershell
& $PY "$WS\code\cli.py" backup --dest <备份盘>:\anki-backup-<日期>
```

硬规则：备份收藏库前**完全退出 Anki**；新备份校验通过后才删旧的。备份包含工作区、收藏库、
媒体与插件，校验与恢复流程见 [docs/backup-sop.md](docs/backup-sop.md)（唯一权威版）。

> 为什么必须备份：git 只跟踪源码与文档，**卡片数据没有 git 可退**（见
> [implementation §6](docs/implementation.md)）。

---

## 9. 测试

12 个回归测试都是**独立脚本、纯离线**（不连网、不碰 Anki 写接口），秒级返回：

```powershell
& $PY "$WS\code\tests\test_llm_out.py"     # 换一个文件名就是另一组
```

改过 `code/common/` 或 `code/execution/` 就把 `code\tests\*.py` 全跑一遍，12 个都 0 才算完；
只改文档不用跑。每个测试挡什么见 [implementation §5](docs/implementation.md)。

---

## 10. 常见问题

| 现象 | 原因 / 怎么办 |
|---|---|
| `doctor` 报 AnkiConnect 连不上 | Anki 没开、AnkiConnect 没装，或 8765 被占用。打开 Anki 后重跑；备份时反过来要退出 Anki |
| 命令跑完什么也没变 | 多数写库命令**默认演练**，确认输出无误后再加 `--commit` |
| 日文乱码 / 字段判断恒真 | 不要用 PowerShell 解析日文文本；脚本的文本 I/O 一律走 `textio`。数据异常用 Python 脚本查 |
| 今天没选出让想要的词 | 选词只统计**库里已有卡**的词；没有卡的词（如 `かしら`、`ニコチン`）进不了候选。可 `--particles` 给语气词留名额 |
| 想换一批今天的词 | `cli.py today-new --revert --commit` 撤销上一批，再重新选；不要手删 tag |
| 分析数字和 Anki 里对不上 | 离线分析可能读的是旧快照；以 live 收藏为准，或重跑 `collect_vocab.py` 刷新 |
| 我的复习进度会被覆盖吗 | 不会。工作区脚本不写调度列；导出的 `.apkg` 也不带复习历史（`includeSched=false`） |
| 本地模型 401/403 | key 查找顺序：`--api-key` → `$env:DSH_LOCAL_LLM_API_KEY` → `~/.dsh/local-llm.json`；别把 key 写进代码或文档 |
| 改坏了怎么退 | 代码 / 文档用 `git diff`；卡片数据用备份（§8）或写库脚本留下的 `backup_*.json` |

更多排障见 [docs/troubleshooting/](docs/troubleshooting/README.md) 与
[docs/architecture.md §6](docs/architecture.md)。

---

## 11. 整库下载

完整收藏打包成 `.apkg` 放在 Release 里——**`.apkg` 不进 git 历史**（单个 1.6 GB，远超仓库的文件上限）：

**[deck-2026-10-29](https://github.com/fredgeoO/anki-workspace/releases/tag/deck-2026-10-29)**

| 附件 | 内容 | 卡数 | 大小 |
|---|---|---|---|
| `anki-workspace-deck-1-vocab.apkg` | `0-词汇`（素材生词 / 高频 6000 / 考级 / 专有 / 今天词汇） | 25,921 | 1.60 GiB |
| `anki-workspace-deck-2-grammar.apkg` | `1-语法`（N5–N1，每级 解释 + 例句） | 3,160 | 0.21 GiB |
| `anki-workspace-deck-3-examples.apkg` | `2-例句`（动画例句卡） | 10,739 | 0.92 GiB |

三个包各导一次即可：牌组名带完整路径（`0-日本语学习::0-词汇` …），导入后自动挂回 `0-日本语学习` 下。

**不含复习历史**：导出时 `includeSched=false`，`due / ivl / factor / type / queue / reps / lapses`
全部清零、`revlog` 为空，所有卡按新卡导入——既不会覆盖你自己的进度，也不暴露作者的学习记录。
音频（`Word Audio` / `Sentence Audio`）随包导入媒体库。

要重新打一份（改过卡之后）：Anki 开着，用 AnkiConnect `exportPackage` 按三个子牌组拆包、
`includeSched=false`（命令与三个牌组的对应关系见 [backup-sop §9](docs/backup-sop.md)）。
Release 单个附件上限 2 GiB，所以按三个分支拆包；媒体继续长就继续按子牌组拆。

---

## 12. 牌组版权与署名（第三方牌组）

### `2-考级词汇` —— 【egg rolls】JLPT N1–N5 一万词 v3.5

- 原作者：**egg rolls**（仓库 [5mdld/anki-jlpt-decks](https://github.com/5mdld/anki-jlpt-decks)）。
- 许可：**[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/deed.zh-hans)**。

### `1-高频日语单词 6000` —— Japanese Core 6000

- 来源：Japanese Core 6000 词表（公开资源），本工作区据此建卡。
- 若对外分发含此牌组的收藏，请同样保留词表出处与原始许可声明。

> 字幕、动画画面等素材的版权另见 [subtitles/README.md](subtitles/README.md)；Jiten 动画词频表为
> CC BY-SA 4.0（见 [data/freq/README.md](data/freq/README.md)）。

---

## 13. 文档索引

| 文档 | 讲什么 |
|---|---|
| [AGENTS.md](AGENTS.md) | **Agent 行为契约**：边界、铁律、技能路由、阅读预算、验证与求助 |
| [docs/implementation.md](docs/implementation.md) | 本 README 的细节层：数据流 / 流水线阶段 / 选词打分 / 覆盖率口径 / 测试矩阵 |
| [docs/architecture.md](docs/architecture.md) | 代码分区、统一入口、doctor、vocab_cover、Jiten 词频序、环境踩坑 |
| [docs/pipeline-guide.md](docs/pipeline-guide.md) | 字幕卡流水线操作手册（阶段 0-2、4-5 的判据与命令） |
| [docs/today_new-使用说明.md](docs/today_new-使用说明.md) | 每日讲义 |
| [docs/core6000-example-使用说明.md](docs/core6000-example-使用说明.md) / [design](docs/core6000-example-design.md) | 按需补例句 |
| [docs/ainote-enrich-使用说明.md](docs/ainote-enrich-使用说明.md) | 加强某张卡的 AINote 讲解 + 语感 |
| [docs/immersionkit-使用说明.md](docs/immersionkit-使用说明.md) | ImmersionKit 按词表抓例句卡 / 素材卡 |
| [docs/proper-noun-使用说明.md](docs/proper-noun-使用说明.md) | 专有名词收集（`3-专有词汇`，不进队列） |
| [docs/jiten-reorder-使用说明.md](docs/jiten-reorder-使用说明.md) | 插件 `jiten_reorder`：新卡按 `JitenAnimeRank` 排位 |
| [docs/backup-sop.md](docs/backup-sop.md) | 备份 / 恢复 SOP（唯一权威流程） |
| [docs/decisions/](docs/decisions/) | 关键决策 ADR |
| [docs/troubleshooting/](docs/troubleshooting/README.md) | 排障与犯错经验（流水线坑表、事故复盘） |
| [docs/deprecated.md](docs/deprecated.md) | 已退场的机制与入口（**历史只记在这里**） |
| [docs/jp-card-agent-instruction.md](docs/jp-card-agent-instruction.md) / [mine-agent-instruction.md](docs/mine-agent-instruction.md) / [japanese-word-example-teaching.md](docs/japanese-word-example-teaching.md) | 阶段二 / 阶段四 / 单词例句的提示词规范 |
| `docs/reports/` | 分析报告（含个人学习数据，**本地保留、未入库**） |
| [subtitles/README.md](subtitles/README.md) / [data/README.md](data/README.md) | 素材命名约定 / `data/` 各目录说明 |

---

## 14. 与 Agent 的边界

[AGENTS.md](AGENTS.md) 是**代理的行为契约**（角色边界、禁令、验证命令、失败处理与求助条件），
本文件是**人的项目说明书**（是什么、怎么跑、怎么测、目录）。两者互相引用、**不互相复制**：
项目事实以本文件为准，行为约束以 AGENTS.md 为准。**若两者冲突**（例如本文件描述某操作可行、
AGENTS.md 列为禁止），以 AGENTS.md 为准，代理应**停下询问用户**，不要在文档之间自行仲裁。
技能路由表在 AGENTS.md §4，技能本体在 `.dsh/skills/`。
