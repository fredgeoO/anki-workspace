# 架构与内部约定（architecture）

> 状态：active ｜ 最后核实：2026-10-29

**这是什么**：工作区的细节层 —— 代码怎么分区、六条约定怎么落地、各子系统的口径与踩坑。
**为什么存在**：根 README 只讲入口与规矩，[implementation.md](implementation.md) 收数据流与阶段/口径；改代码、加脚本、排查「为什么这样设计」时看这里。
**什么时候读**：写/改脚本前（§1-2）、动词频序或覆盖率分析前（§4-5）、碰到环境怪问题时（§6-7）。
退场的机制与历史只在 [deprecated.md](deprecated.md)。

---

## 1. 四个代码区 + 共享库

| 区 | 放什么 | 判断标准 | 目录 |
|---|---|---|---|
| ① 执行区 | **生成卡片这类任务**：字幕卡清理/生成、词汇卡激活、生词入库、挂音频、每日讲义 | 多步、可重复跑；通常要连 AnkiConnect 或派子代理 | `code/execution/` |
| ② 工具区 | **从 edge-TTS 取语音这类能力**：TTS 客户端、音频自检、产出审计、备份、开工体检 | 是「能力」而非「任务」；常被别的脚本 import 或反复调用 | `code/tools/` |
| ③ 分析区 | **回答学习水平与疑问、出报告**：自评校准、弱词、复习负载、配比方案、字幕覆盖率 | 只读数据源，产出结论/报告 | `code/analysis/` |
| ④ 单次执行区 | **跑一次就完成的活儿**：探针、快照刷新、一次性修复 | 用完即弃，没有上下游依赖 | `code/oneshot/` |
| ＋ 共享库 | 被多个区 import 的实现与**路径常量** | 只提供服务，不单独当任务跑 | `code/common/` |
| ＋ 一次性文件区 | **跑一次就该消失的东西**：临时脚本草稿、排查 dump、跑批日志、实验中间产出 | 不进代码库、不做长期依赖；做完一条命令清空 | `temp/` |

统一入口 `code/cli.py` 与开工体检 `code/tools/doctor.py` 是 2026-10-10 新增的
**门面**：`cli.py` 不含业务逻辑，只做「组 → 脚本」映射与参数透传。

各区现有脚本：

| 目录 | 脚本 |
|---|---|
| `code/`（根） | `cli.py` —— 统一入口（`python code/cli.py <组> <子命令>`；薄分发器 + `vocab reorder-jiten` preset） |
| `code/execution/` | `filter_subtitle.py`（入库前的字幕前置筛选）、`pipeline.py`（阶段 0-2）、`cards.py`（**按张**生成 AINote + Sentence HTML：单卡/数张也能跑，不依赖批次）、`activate.py`（阶段 3）、`mine.py`（阶段 4）、`proper.py`（**专有名词收集**：字幕 → `3-专有词汇`，含 `model/scan/split/gen/verify/write/audio/add`，**不进学习队列**，见 [proper-noun-使用说明](proper-noun-使用说明.md)）、`mine_audio.py`（阶段 5）、`today_new.py`（每日讲义：取 tag `今天学习生词` → 切批 → 合并讲解；没有 tag 不生成）、`core6000_example.py`（**按需**补例句②：给用户点名的 core6000 词补第二条例句 + 振假名 + 合并讲解 + edge-TTS 配音）、`ainote_enrich.py`（**高频**：加强某张词汇卡的 AINote 讲解 + 补「语感」，本地模型生成 6 节、只写 AINote、写前备份）、`immersionkit.py`（**按词表**从 ImmersionKit 抓对白例句：选词 → 选句 → 本地模型讲解 → 剧照/原声落地 → 例句卡 + 素材生词卡，默认全程演练） |
| `code/tools/` | `doctor.py`（**开工体检**：三件自审 + 废弃符号 + 快照卫生 + 文档状态行 + preflight）、`edge_tts_min.py`（纯标准库 TTS 客户端）、`check_audio.py`（音频自检）、`fix_word_audio.py`（**单词音频读错修复**：`Transliteration` + `Word Audio` 同名覆盖，带 ruby 比对/旧值断言，见 pipeline-guide §8.6）、`audit_mine_outputs.py`（独立复核）、`proper_extract.py`（**专有名词抽取的原子能力**：一段文字 + 背景 → 专名清单，Anki 无关、可单跑、`--no-model` 只跑预扫）、`review_shortlist.py`（判弃块复核短名单）、`backup_anki.py`（备份：工作区 + 收藏库 + 媒体 + 插件 → G: 盘，含校验与 manifest，见 [docs/backup-sop.md](backup-sop.md)）、`temp_clean.py`（`cli.py temp`：一次性文件区 `temp/` 的查看 / 清空，先打印清单再删） |
| `code/common/` | `anki_api.py`（**Anki 读写唯一接口**：AnkiConnect 传输 + 类型化读写 + 学习记录 + 离线快照 + 防回退自审）、`immersion_api.py`（**ImmersionKit 只读客户端**：搜索/媒体 + 例句清洗/筛选 + 振假名转 `Sentence HTML`，带磁盘缓存；不碰 Anki）、`paths.py`（路径唯一来源）、`check_cards.py`（例句卡自检）、`check_ruby.py`（振假名读音自检）、`check_mine.py`（生词卡自检）、`check_proper.py`（**专有名词卡自检**：判定产出 + 写入载荷两层，`Intro`/`Categories`/`Source` 的机械规则）、`textio.py`（**文本 I/O 与编码的唯一入口**：import 即接管 stdio 为 UTF-8、GBK/BOM/CP932 解码、JSON 安全读、子进程文本模式，含 `check` / `read` / `decode` / `audit` CLI）、`ps-utf8.ps1`（**PowerShell 侧补丁**，用法见 §6.5） |
| `code/analysis/` | `today_weak.py`（今天/近 N 天答得不好的卡 → 单词名/语法名）、`analyze_revlog.py`（自评按钮校准）、`weak_words_2d_live.py` + `make_weak_list.py`（弱词清单）、`anki_revlog_analysis.py`（每牌组复习量/单卡耗时）、`planning/`、`vocab_cover/`（字幕覆盖率与词汇量：§4；外部词频表排序：§5）、`anki_analyze/`（离线诊断孤岛，见 §7） |
| `code/oneshot/` | 一次性活儿（用完即弃，现役 21 个）：`install_workspace_wheels.py`（往 `data/pylibs` 装库，见 §6.4）、快照只读探针、残渣修复入口（`fix_bad_arrow` / `fix_text_wrap` / `verify_no_residue` / `fix_stray_rt`）、ImmersionKit 批处理、两个历史迁移（留作「默认演练」写法参考）。用完的挪 `archive/experiments/20261020-oneshot/` |

---

## 2. 统一入口 `ws`（`code/cli.py`）

```powershell
& $PY "$WS\code\cli.py" doctor                 # 开工体检（强制门禁，见 §3）
& $PY "$WS\code\cli.py" daily stats            # 今日讲义链路
& $PY "$WS\code\cli.py" pipeline triage --query "tag:待标记"
& $PY "$WS\code\cli.py" mine scan --tag "动画::<作品名>::<季>::第NN集"
& $PY "$WS\code\cli.py" audio plan
& $PY "$WS\code\cli.py" core6000 gen --words "徹夜,適当"
& $PY "$WS\code\cli.py" ainote enrich --word 分際 --commit   # 加强 AINote 讲解 + 语感
& $PY "$WS\code\cli.py" vocab cover            # 只暴露 4 个分析入口
& $PY "$WS\code\cli.py" weak today --days 3 --plain
& $PY "$WS\code\cli.py" backup --dest <备份盘>:\anki-backup-<日期>
& $PY "$WS\code\cli.py" list                   # 列出全部入口与实际脚本路径
```

**组 → 脚本**：`daily`=`today_new.py`、`pipeline`=`pipeline.py`、`cards`=`cards.py`
（按张生成 AINote + Sentence HTML，原子入口：`cards.py gen/write`）、
`activate`=`activate.py`
（只给 `vocab reorder-jiten` 与历史批次 `revert` 用）、`mine`=`mine.py`、`audio`=`mine_audio.py`、
`core6000`=`core6000_example.py`、`ainote`=`ainote_enrich.py`（加强某张卡的 AINote 讲解 + 语感）、
`immersion`=`immersionkit.py`（按词表从 ImmersionKit 抓对白例句 → 例句卡 + 素材生词卡）、
`doctor`=`tools/doctor.py`、`temp`=`tools/temp_clean.py`、`backup`=`tools/backup_anki.py`。

**vocab 只暴露 4 个入口**（`cover` / `newwords` / `report` / `mine_window`）；
`vocab_cover/` 里其余约 20 个脚本（`corpus.py`、`metrics.py`、`collect_vocab.py`、
`freq_external.py` …）保持直接调用，不走 CLI —— 它们是数据链的零件，不是日常入口。

**weak 四件套**：`today`=`today_weak.py`、`revlog`=`analyze_revlog.py`、
`pace`=`anki_revlog_analysis.py`、`build-list`=`weak_words_2d_live.py` → `make_weak_list.py`（两步链）。

**参数一律原样透传**：`cli.py` 不解析子命令的参数，`--` 之后的内容也不再被它处理。
给子脚本的帮助：`python code/cli.py <组> --help`。

### 2.1 preset：`vocab reorder-jiten`（包死三个必选开关）

全局「按动漫词频学词汇」的重排链，默认**全链演练**，`--commit` 才真写：

```powershell
& $PY "$WS\code\cli.py" vocab reorder-jiten            # 演练：build → plan → apply → field
& $PY "$WS\code\cli.py" vocab reorder-jiten --commit   # 真写（位置 + 字段）
& $PY "$WS\code\cli.py" vocab reorder-jiten --skip-build        # 复用现有词表
& $PY "$WS\code\cli.py" vocab reorder-jiten --skip-field        # 只重排位置，不写字段
```

四步：`freq_external.py build --media Anime` → `make_activate_plan.py --words-file
data/vocab_cover/study_plan_jiten_anime.json --tag jiten --all-cards --exclude-decks
"0-日本语学习::2-例句"` → `activate.py apply --plan data/plans/plan_activate_jiten.json
--global`（`--commit` 时加 `--commit`）→ `freq_external.py field --plan …`。
这三个开关为什么必须（§5.2）和 deck 名一样硬编码在 `cli.py` 顶部的常量块里，
deck 改名时只改那一处。

---

## 3. 开工体检 `doctor`（强制门禁）

```powershell
& $PY "$WS\code\cli.py" doctor                        # 全套（Anki 开着）
& $PY "$WS\code\cli.py" doctor --skip-anki            # 离线
& $PY "$WS\code\cli.py" doctor --tag "动画::…::第NN集" # 并入每集 preflight
& $PY "$WS\code\cli.py" doctor --quiet --all          # 只看 fail/warn，明细全展开
```

**退出码**：`0` 全绿；`2` 只有提示（可开工，但看一眼）；`1` 有阻塞项 —— 先修再动手。
它**只读**，一次跑完九项：

| # | 检查 | 来源 | 判定 |
|---|---|---|---|
| 1 | AnkiConnect 健康（版本/牌组/笔记类型/媒体数） | `anki_api.py check` | 连不上 = fail（`--skip-anki` 跳过） |
| 2 | Anki 访问点自审（不许出现第二份客户端） | `anki_api.py audit` | 阻塞项 > 0 = fail；第二期待办只报告 |
| 3 | 编码 / stdio 自审（R1-R5） | `textio.py audit --strict` | 任一命中 = fail |
| 4 | 废弃符号残留（doctor 独有） | 本仓库活跃区扫描 | 命中 = fail |
| 5 | 快照卫生（manifest / probe 临时目录 / 快照是否过期） | doctor 独有 | 只 warn |
| 6 | 文档状态行（`docs/**` 头部有「状态：」） | doctor 独有 | 只 warn（`reports/` 除外） |
| 7 | 每集 preflight（待生成/判弃张数、建议 `--batches`、可用标签、孤儿产出） | skill 的 `preflight.py` | 退出码 + `[!]` 提示 → warn |
| 8 | 环境与依赖（Python 版本、`data/pylibs` 条目、`pylibs.lock`） | doctor 独有 | 只 warn |
| 9 | 工作区卫生（根目录白名单、`temp/` 里还有多少待清） | doctor 独有 | 只 warn |

**为什么不重复实现**：第 1-3 项是既有自审，第 7 项是既有 preflight —— doctor 只做编排与
汇总，不另写一套规则（否则「同一件事只校验一次」这条约定自己先破了）。
第 4-6、8-9 项是原来**没有任何脚本在查**的东西，这才放在 doctor 里。

**第 4 项的口径**（避免误报）：
- 只扫「给当前指令」的文件：`code/execution|analysis|tools`、`.dsh/skills`、`README.md`、
  `docs/` 顶层（`docs/reports`、`docs/plans` 是史料，`docs/deprecated` 是废弃档案，都不扫）。
- 命中的行如果自带「已归档 / 已废弃 / 退场 / archive/ / docs/deprecated」字样，
  视为**有意保留的指引**，放行（所以废弃说明里可以点名旧入口）。
- doctor 自己会跳过自己（它的模式表里就写着这些名字）。

---

## 4. 字幕覆盖率与词汇量（`code/analysis/vocab_cover/`）

回答三个问题：**一集字幕覆盖了我 core6000 / 考级词汇的多少？我的卡组到底能听懂多少？
还要看（并学）多少部动画？**
完整结论见报告 `docs/reports/字幕覆盖率与词汇量报告.md`（个人分析产物，本地保留、未入库）。

```powershell
$VC = "$WS\code\analysis\vocab_cover"

# ★ 最常用：给任意一篇日语文字/一集字幕，出覆盖率 + 新词表 + 理解度
& $PY "$VC\cover_cli.py" "subtitles\Yani Neko\ヤニねこ.S01E01.ニャーがヤニねこにゃ.WEBRip.Netflix.ja[cc].srt"
& $PY "$VC\cover_cli.py" --text "日本語の文章…"          # 或 --stdin / 传文件路径
& $PY "$VC\cover_cli.py" ep.srt --json --oov-out data\vocab_cover\oov_ep01.json

# ★ 新词清单：把文章/字幕里「我还不认识的词」全量列出来（词形·原形·读音·词性·次数·首例句·档位）
& $PY "$VC\newwords.py" "subtitles\転生王女と天才令嬢の魔法革命"   # 目录递归，12 集合并统计
& $PY "$VC\newwords.py" ep.srt --sort jiten                    # 按动画真实词频排（挖词首选）
& $PY "$VC\newwords.py" ep.srt --cat oov --min-count 2         # 只看真的没卡的词、至少出现 2 次
& $PY "$VC\newwords.py" ep.srt --per-file --top 20             # 每集单独一张表
& $PY "$VC\newwords.py" ep.srt --format tsv --out data\vocab_cover\newwords_ep01.tsv
#   默认列出两类：卡组外·要背（真新词）+ 卡组内·有卡没学过；专名/感动词/数词/已学需显式加
#   （--with-proper / --with-known，或 --cat oov,untackled,proper）。--sort jiten 需要
#   data\freq\jiten_freq_Anime.csv（没有就自动退化成不显示 Jiten 列）。

# ★ 跨作品通用性判定：只留「值得挖」的（题材通用 + 跨作品高频 + 低频通用）
& $PY "$VC\newwords.py" ep.srt --sort jiten --mine-only        # 去掉作品专有/功能词/拟声/疑似人名
& $PY "$VC\newwords.py" ep.srt --cross genre                   # 只看题材通用词（宫廷/奇幻/军事/神话/学园）
& $PY "$VC\newwords.py" ep.srt --cross work,unlisted           # 看被排除的（专有/未收录）
& $PY "$VC\newwords.py" ep.srt --cross genre --common-max 5000 # 调「通用」的门槛
#   判据在 code\analysis\vocab_cover\crosswork.py，三个词表都是可手改的 JSON：
#     data\vocab_cover\genre_lexicon.json  题材通用词（宫廷/奇幻/军事/神话/学园・社会）
#     data\vocab_cover\work_concepts.json  作品专有概念/人名（键用会出现在来源路径里的字符串）
#     data\vocab_cover\not_vocab.json      语法性功能词 + 拟声/感叹
#   核心口径：Jiten 表按「出现在多少部不同作品里」排 → 表里有排名 = 跨作品出现过（深浅只反映广度），
#   所以宫廷/奇幻那类排在 8000~60000 名的词是「通用但低频」，算「值得挖」；
#   只有作品独有概念（例：HUNTER×HUNTER 的「念能力」）和纯人名才排除。

# ★ 生词报告：一条命令出「学习用」报告（Markdown + JSON），报告只讲学习相关的
& $PY "$VC\newword_report.py" "subtitles\転生王女と天才令嬢の魔法革命\... - 01 (AT-X).srt"   # 单集
& $PY "$VC\newword_report.py" "subtitles\転生王女と天才令嬢の魔法革命"                        # 整部：汇总 + 分集速览
& $PY "$VC\newword_report.py" subtitles                          # 多部作品：每部各一份
& $PY "$VC\newword_report.py" article.txt --no-example            # 文章
#   产物：docs\reports\<slug>_生词报告.md + data\vocab_cover\<slug>_生词.json
#   章节固定：一句话结论 → 规模与掌握 → 生词分档 → 题材通用词 → 值得挖的生词 → 不用记的生词（附原因）
#   工具细节（判定规则/复现命令/跨剧对比）不写进报告；要看就翻本节和 crosswork.py 的 docstring。

# 代理只参与「未收录 + 词表没覆盖」的词（其余全自动）
& $PY "$VC\newword_report.py" "<集.srt>"          # 跑完会生 pending_<slug>.json（没有则说明不用判）
#   → 需要时派一个代理（或本地模型，见 local-llm 技能）读 pending，把结论填进 decisions：
#     {"髪色": {"kind":"genre","category":"学园・社会"},     # 跨作品通用词 → 值得挖
#      "ユフィリア": {"kind":"work","reason":"人名（女主角）"}, # 作品专有 → 不挖
#      "ニュッ": {"kind":"not_vocab","group":"onomatopoeia"},  # 功能词/拟声 → 不挖
#      "思春": {"kind":"ignore"}}                             # 判过但不挖 → 进 not_vocab 的 ignored 组
#   四种结论都会落盘，同一个词不会被问第二遍；回写后重跑，待判定数应归零。
& $PY "$VC\newword_report.py" --apply-decisions data\vocab_cover\pending_<slug>.json
& $PY "$VC\newword_report.py" "<集.srt>"          # 重跑：同类词以后全自动（待判定数应显著下降）

# ★ 挖掘窗口：只挖前 N 集，能覆盖整季多少生词（值不值得）
& $PY "$VC\mine_window.py" --k 3                      # 全部作品：前 3 集 → 覆盖整季生词的 %、效率
& $PY "$VC\mine_window.py" "subtitles\転生王女と天才令嬢の魔法革命" --k 2
& $PY "$VC\mine_window.py" --md-out docs\reports\挖掘窗口分析.md --json-out data\vocab_cover\mine_window.json
#   口径：「覆盖」= 前 k 集挖到的词在**整季**里出现过的次数 ÷ 全季生词总次数（按次数比按词种更贴近听感）；
#   「效率」= 覆盖占比 ÷ 挖的词种占比（>1 = 这个窗口的词更值钱）；「边际效率」跌破 1.0 的那一集起不划算。
#   报告里还会给「窗口外的高价值词」（前 k 集没挖到、后面出现且 Jiten 靠前），照它补挖即可。
#   配合「只挖窗口」的生词报告：& $PY "$VC\newword_report.py" "subtitles\<作品>" --first-k 3

# 数据链（一条命令，自动按需重算；加了字幕或卡组变了直接重跑这一条）
& $PY "$VC\report_build.py"     # 自动刷新 -> 图表 PNG + Markdown 报告
                                #   默认 --refresh auto：Anki 开着就重取卡组快照（指纹没变则不落盘，
                                #   缓存继续有效）-> 字幕集数/集号或词表指纹变了才重算 corpus_tokens.json
                                #   -> 语料或卡组变了才重算 metrics.json -> 重画图 + 重写报告。
                                #   加一集字幕：只重算那一集（内容哈希缓存），指标/图表/报告自动更新；
                                #   core6000 / 考级词汇是固定词表，增长的只有素材生词（挖生词 + 例句）。
                                #   选项：--refresh {auto,always,never}、--anki {auto,always,never}、
                                #        --force（强制全量）、--prune、--no-charts、--verbose。
#
# 手动逐步重跑（想单独看中间产物时用）：
& $PY "$VC\collect_vocab.py"    # AnkiConnect -> data\vocab_cover\vocab_state.json
& $PY "$VC\corpus.py"           # subtitles/   -> data\vocab_cover\corpus_tokens.json
                                #   按内容哈希缓存每集结果（corpus_cache/）：改一集只重算那一集；
                                #   卡组一变（vocab_state 变了）自动全量重算。
                                #   实测 48 集：全量约 4 秒，缓存全命中约 0.5 秒。
& $PY "$VC\metrics.py"          # 语料级指标   -> data\vocab_cover\metrics.json
& $PY "$VC\report_build.py" --refresh never   # 只重画图 + 重写报告
```

脚本职责：`_norm.py`（词形归一唯一实现）、`collect_vocab.py`、`jp_tok.py`（Sudachi 分词+匹配+
覆盖率核心库）、`srt.py`、`corpus.py`、`metrics.py`、`report_build.py`、`cover_cli.py`（覆盖率体检）、
`newwords.py`（**新词清单**：全量列出新词，带读音/原形/词性/次数/首例句/档位，可导出 TSV/CSV/MD/JSON）、
`crosswork.py`（**跨作品通用性判定**：值得挖 / 看情况 / 别挖）、`newword_report.py`（**生词报告**）、
`mine_window.py`（**挖掘窗口分析**）。
另有 `freq_external.py`（外部词频表当排序源，§5）与 `study_plan.py` / `make_activate_plan.py`
（把词表转成激活计划）。
三个分母（全部词元 / 词汇词 / 需背实词）与已学、成熟两种掌握判定都在 `jp_tok.Coverage.summary()` 里，
报告与 CLI 共用同一份实现。

依赖装在**工作区内**的 `data/pylibs`（SudachiPy + SudachiDict Core、matplotlib），
不污染系统环境，卸载就是删目录；重装见 §6.4。

---

## 5. 外部词频表当排序源（`freq_external.py`）

### 5.1 为什么换成外部词表

§4 那些清单的排序来自本工作区自己的 36 集字幕（8.2 小时）——最高频词只有 196 次，
第 50 名往后就掉到个位数，排名基本是噪声，而且被单部作品污染（`大家` 26 次排前面、
Jiten 排名却是 #20,089；`琵琶` #46,461、`棟梁` #44,068 同理）。换成建在 **3,762 部动画字幕**
上的 [Jiten](https://jiten.moe/frequency-dictionaries) Anime 词表，排序深度和泛化性都好得多；
它按「出现在多少部不同作品里」排、不按单部里的重复次数排，正好抵消这种单集噪声。

**最硬的一条理由**：现在可发的 live 新卡（9,986 个不同的词 / 11,990 张卡）里，只有 **1,949** 个
词在那 36 集里出现过 —— 本地清单能排的就这些，其余次数一律为 0、**完全排不了先后**。
Jiten 能给其中 **96.0%** 排上名。完整对比见
`docs/reports/外部词表排序对比.md`（本地报告，未入库）。

```powershell
$FE = "$WS\code\analysis\vocab_cover\freq_external.py"

& $PY $FE download --media Anime      # → data/freq/jiten_freq_Anime.csv（CC BY-SA 4.0）
& $PY $FE build    --media Anime      # → data/vocab_cover/study_plan_jiten_anime.json
& $PY $FE compare  --media Anime      # 只读对比：覆盖率 / 秩相关 / 长尾队列 → 报告
& $PY $FE field    --plan data/plans/plan_activate_jiten.json --add-field            # 演练：只写池子里的 11,990 个笔记
& $PY $FE field    --plan data/plans/plan_activate_jiten.json --add-field --commit   # 真写
& $PY $FE field    --plan data/plans/plan_activate_jiten.json --all-notes --commit   # 连已学过的旧卡一起写（16,649 个笔记）
```

> **日常别手敲这一串**：用 preset `python code/cli.py vocab reorder-jiten`（§2.1），
> 它把这四个开关包死了，并且默认演练。

```powershell
# 接既有链路（三个开关必须一起给，见 §5.2）
& $PY "$VC\make_activate_plan.py" --words-file "$WS\data\vocab_cover\study_plan_jiten_anime.json" `
      --tag jiten --all-cards --exclude-decks "0-日本语学习::2-例句"
& $PY "$EXE\activate.py" apply  --plan "$WS\data\plans\plan_activate_jiten.json" --global            # 演练
& $PY "$EXE\activate.py" apply  --plan "$WS\data\plans\plan_activate_jiten.json" --global --commit   # 真写
& $PY "$EXE\activate.py" revert --plan "$WS\data\plans\plan_activate_jiten.json" --commit            # 回退
```

### 5.2 三个开关都是必须的（每一个漏了都会破坏全局顺序，都是踩出来的）

| 开关 | 不写会怎样 |
|---|---|
| `--all-cards` | 只排「一个词一张卡」，**同一个词的其余新卡保留原来的随机插队位置**（1、3、4…），插到排好的队列**前面**去。实测有 **2,326 张**这种卡。 |
| `--exclude-decks "0-日本语学习::2-例句"` | 例句卡会被算进来（231 张），但例句卡有自己的激活路径，不该混进词汇词频队列 —— 不排它们，计划覆盖的卡才是「词汇卡」这一批。 |
| `--global` | `activate.py` 默认把位置**按卡组分开**编号（每个牌组各从 1 排起），跨卡组的 `due` 大量并列，全局顺序就散了。 |

**词表里查不到的卡**（实测 **101** 张：`自然に`/`必死に` 这类带助词的词条、`剝げる` 这类异体字、
以及 Jiten 动画表里确实没有的词）统一排到**队尾**（`freq_rank: null`），不会被留在原来的随机位置。

实测结果（2026-10-06）：计划 **11,990** 张（= 覆盖到的全部新卡）；`due` 取值 1…11990 **全部唯一**；
有排名的 11,889 张排名**单调不减**（28 → 176,614），101 张无排名的全在尾部。前 20 个：
`でも(28) 私(29) ああ(35) お前(64) 俺(69) さ(87) 前(95) 前(95) より(107) 中(116) かえる(119) なの(134) まあ(156) ただ(159) まさか(162) ごめん(188) こいつ(214) バカ(255) 許す(275) 日(276)`。

**2026-10-10 复跑**：计划变成 **11,907** 张（少 83 张 —— 已有卡毕业离开新卡池，属正常漂移），
`data/plans/plan_activate_jiten.json` 已按当天状态重新生成；
上一份（11,990 张、含各卡 `due_before` 的回退依据）备份在
`data/plans/_prev/plan_activate_jiten.prev-<时间戳>.json` —— preset 每次覆盖前都会这样留一份
（备份放 `_prev/` 子目录，`activate.py:latest_plan()` 只 glob 本层，不会误取）。

### 5.3 排名字段 `JitenAnimeRank`（注解，不参与排序）

`freq_external.py field` 把排名写成笔记字段：**`%06d` 补零**（浏览器按字段排序是文本序，
补零后文本序 == 数值序），词表里查不到的写 `999999`（文本序排最后）。
两个范围：默认只写池子里那 **11,990** 个笔记；加 `--all-notes` 连**已学过的旧卡**一起写 ——
旧卡不在 plan 里，改按「笔记里的词 → 词表排名」重新查，实测共 **16,649** 个笔记
（`Japanese Vocabulary` 6,040 + `eggrolls-JLPT10k-v3.5` 10,609，含 106 个 `999999`）。

写回值可信度有一步自检：`--all-notes` 那条推导路与 plan 的值**逐条对照，不一致 0 个**
（说明 plan 的 `freq_rank` 与字段写回同源）。抽样：`する`→`000013`、`これ`→`000023`、
`私`→`000029`、`行く`→`000041`、`見る`→`000050`、`でも`→`000028`、`随想`→`176614`。
**重跑幂等**：值对了就跳过、不动 `mod`（实测第二次「需要写入/更新：0 个」）。

**它决定不了学习顺序**，别指望它替代 `due`：Anki 新卡队列的顺序只有一个来源 —— `cards.due`
（= 位置）。`Filtered.SearchTerm.Order` 和卡组的 `NewCardGatherPriority` /
`NewCardSortOrder` 枚举里**都没有「按字段排」这一项**，手册也写明 `Reposition` 才是
"Change the order new cards will appear in"。字段的价值是：复习/浏览时看得见排名、
可以建「只学排名 < N」的筛选牌组（regex 搜字段）、排序依据留在库里不依赖工作区脚本。
想在卡片上直接看到：给模板加一行 `{{JitenAnimeRank}}`，或先把它在浏览器加成列。

⚠ **加字段的副作用**：Anki 会给这两个笔记类型的**全部**笔记补一个空字段 —— 实测 17,633 个
笔记里 **16,649 个**的 `flds`/`mod` 被改（11,990 写值 + 4,659 自动补空，后来那 4,659 也用
`--all-notes` 补上了值）。所以下次同步要传这 16,649 个笔记（一次性大 delta，多设备建议先同步再动）。
**卡片调度列（`due/ivl/factor/reps/lapses/type/queue`）零改动** —— 写库前后逐字段 diff 过两次：
写库前已学的 6,227 张卡**调度列改动 0 张**，新卡只有 `due` 那 11,990 张。

> `--all-notes` 自带护栏：演练/真写都打印「改 N 个笔记 → 下次同步要传 N 个」；`--commit` 前落
> 写前快照（1 小时内的直接复用），写后用快照 diff 调度列，非零就告警。

**`JitenGlobalRank`（2026-10-29 加）** —— 同一套实作逻辑，换一把尺子：词表用 Jiten 的
**Global**（全媒介合并，460,896 行 / 554,660 个归一化键），写 `JitenGlobalRank`，覆盖两类
词汇卡的**全部**笔记（`Japanese Vocabulary` 15,212 + `eggrolls-JLPT10k-v3.5` 10,650 =
25,862 张）：

```powershell
& $PY -X utf8 code\analysis\vocab_cover\freq_external.py field `
    --models vocab --media Global --field JitenGlobalRank --add-field --commit
```

`--models` 是「按笔记类型全量回填」入口：不需要 plan、不需要待办 tag、不摘任何 tag；
护栏与 `--all-notes` 相同（同步影响行、写前快照、写后调度列 diff），另加写后
`verify_note_fields` 回读。**它同样只是注解**：`jiten_reorder` 与 `activate.py` 仍只认
`JitenAnimeRank`（Global 与 Anime 是两套排名，换尺子要先改配置、并想清楚后果）。
查不到的词仍写 `999999`；实测查不到 60 个（`似ている`、`介抱する`、`でかくて` 这类活用形/
词组条目），它们在 Anime 表里同样是 `999999` —— 两条路的分歧只来自词表本身。

### 5.4 顺序为什么会生效

* 新卡队列的顺序**只有一个来源**：`cards.due`（= 位置）。选项组的
  `gather = Ascending position`（`newGatherPriority = 1`）—— proto 里它的定义是**不分牌组**的
  （`ASCENDING POSITION ... Ascending position`，对比 `DECK` 的 "Decks in alphabetical
  order (preorder), then ascending position"）。所以**卡组自己就按全局词频序发卡**。
  选项组是三个词汇卡组：`单词（Core 6000）` / `单词（JLPT）` / `素材生词`（父卡组 `0-词汇`
  是 `单词`，gather 为 `DECK`）；`new/day` 上限仍是各牌组自己的，**以卡组选项里的实值为准**
  （实读 `getDeckConfig`：core6000 = 10、考级词汇 = 20、素材生词 = 20，父卡组 `0-词汇` = 30）。
  原配置备份在 `data/vocab_cover/deck_config_legacy_backup.json`（改回 `newGatherPriority: 0` 即还原；
  那份备份是更早一版，里面的 `perDay` **别拿来当现在的上限**）。
* ⚠ 用 `Set Due Date` 提前复习只对**已学过的卡**用 —— 对**新卡**用它会把卡变成复习卡
  （manual: "Turns cards into review cards if they are new"）；新卡的「提前」= 改位置。
* **2026-10 起考级词汇已扁平化**：12 个按级别/频段切分的子 deck 合并成
  `0-日本语学习::0-词汇::2-考级词汇` 一层（10,609 张）。级别与频段没有丢，改由 eggrolls
  笔记标签区分（`eggrolls-JLPT10k-v3.5::4-N2::N2高频` 等，见 `code/common/jp_decks.py`）。
  影响：① 跨子卡组的「牌组树顺序」不存在了，考级词汇是一条混合级别的队；
  ② 依赖子 deck 名的脚本一律改读标签（`pipeline.py` 的判据①、`activate.py`、
  `anki_revlog_analysis.py`、planning 与 anki_analyze 系列）。
* 与 `JitenAnimeRank` 字段的分工：**字段是注解**（浏览器排序、看得见排名、便于手动重排），
  **`due` 才是队列顺序**。排序字段改掉不会改变取卡顺序 —— Anki 手册对它只有一句
  「show this field in the Sort Field column of the browser」。
* **第四个词汇牌组 `3-专有词汇` 是收集品，不进学习队列**（[ADR](decisions/2026-10-22-专有词汇牌组与扁平标签.md)）：
  笔记类型 `Japanese Proper Noun`（首字段 `Index`，所以同名不同作品能共存）；
  **类别标签扁平**（一个专名可同时是「人名」+「称号」），**出处标签继承 `动画::<作品>` 两层**
  （不带季度/集数，所以 `tag:动画::水星领航员` 同时搜到例句卡与专名卡）；
  脚本不写 `due`/不 suspend/不改牌组选项。
  `today_new.py` 的 `STUDY_UNITS`、`collect_vocab.py` 的 `DECK_SPECS`、`jiten_reorder` 的 `decks`
  都没有它 → 讲义、覆盖率、词频序自动看不见它（这是刻意的）。
* ⚠ **顺序会自己漂移**：新加入的卡拿的是**随机位置**（`new_card_insert_order = RANDOM`），
  会随机插进排好的队列中间。加了一批词之后要重排：脚本走
  `python code/cli.py vocab reorder-jiten --commit`（= §5.2 那条链）；
  手动则是浏览器按 **Sort Field 列**（现在就是 `JitenAnimeRank`）排序 → 全选 → Cards → Reposition。

### 5.5 只动没学过的卡（三重保证 + 实测，2026-10-06 核实）

① 计划生成时只查 `is:new`；② `activate.py apply` 写库前**逐张从 live 重读**，
`type != 0`（学习中/复习/重学）一律剔除并打印「⛔ 已不是新卡」；③ `revert` 也只还原
`type == 0` 的卡。已学卡的位置、ease、interval 都不会被碰。
写库前后拿快照逐字段 diff（`data/snapshots/pre_freq_reorder/`，
`type,due,ivl,factor,reps,lapses,queue` 七列全比）：**6,227 张已学卡改动 0 张**；
11,990 张新卡只改了 `due` 一列，其余六列零改动。

### 5.6 它换不掉什么（别混）

* **挖词照旧**：外部词表只能给**已有卡**排序，补不了卡组外的缺口。
* 词表 CSV 只有 Rank 没有次数，所以写出的 `corpus_count` 是 `10**6 // rank` 的**合成值**
  （**真排名看 `freq_rank`**）；plan 里的 `occurrences` 对外部词表同样是合成值。
* 词表格式是 `Word,Form,Rank`，汉字形与假名形**两把键都收**，所以卡组里写「言う」或
  「いう」都能查到（实测覆盖现有词表的 97.3%）。

---

## 6. 环境与踩坑

### 6.1 本机 shell 是 PowerShell 5.1，默认编码 ANSI=GBK

`Get-Content` / `Import-Csv` / `Out-File` 的默认编码是 ANSI=GBK，而工作区文本几乎都是 UTF-8。
**2026-10-08 的事故**：用 `Get-Content cmp_out.json -Raw | ConvertFrom-Json` 读 UTF-8 产出，
`ConvertFrom-Json` 直接报「传入的对象无效」，`$o` 为 `$null`，于是「字段为空就删」的判断对
**每一个**文件都成立 —— 误删了 `output/cmp4` 里 39 个产出（回归结果丢失，只能重跑）。

两半解法：Python 侧 `code/common/textio.py`（import 即接管）；PowerShell 侧
`code/common/ps-utf8.ps1`。**加载方式有实测结论**：DSH 的 shell 是受限令牌，`.ps1` 文件
**跑不了** —— Restricted / AllSigned / RemoteSigned 都拦（"is not digitally signed"），
`Unrestricted` 报 `AuthorizationManager check failed`，只有 `Bypass` 能跑；而且这个 shell
**不加载 `$PROFILE`**。所以 DSH 会话里只有两条路：
`iex ([IO.File]::ReadAllText("$WS\code\common\ps-utf8.ps1", [Text.Encoding]::UTF8))`，
或 `Set-ExecutionPolicy -Scope Process Bypass -Force` 之后再 dot-source；
ad-hoc 的 python 一行加 `-X utf8`。
`$PROFILE`（UTF-8 带 BOM）2026-10-08 已装好，**对你自己开的 PowerShell 窗口生效**，
沙箱会话吃不到。迁移前的完整备份在 `data/evidence/textio_migration_backup/`；
档案见 [docs/plans/2026-10-08-编码统一-textio.md](plans/2026-10-08-编码统一-textio.md)。

### 6.2 删除 / 覆盖前先打印「将删 N 个」

这条是从上面那起事故里长出来的：**任何删除或覆盖前，先打印将被删/改的清单与计数，
数字与预期不符就 abort**。`code/oneshot/migrate_textio.py` 是这种默认演练的写法。
原因很直白：一旦 PowerShell 把日文解成乱码，按日文字段名取的属性全 `$null`，
`if (-not $x.字段)` 就对每一个文件成立 —— 打印计数是唯一能在动手前看出来的信号。

一次性文件区的清理就是这个模式的**现役实现**（2026-10-20 起）：`temp_clean.py` 先打印
「将删 N 个文件 / X MB」与按顶层条目的汇总，再动手；`--dry-run` 只看不删。

### 6.3 快照现状（`data/snapshots/`）

分析用只读快照都在这里；**临时快照也放这里**，别复制到工作区根目录。
每个快照在 `data/snapshots/README.json` 里登记用途、消费者、何时可删
（`doctor` 第 5 项按它检查：没登记的会报，疑似 probe 目录会点名）。

离线读快照的入口：`anki_api.Snapshot.open(...)`（`--source snapshot`）、
`today_weak.py --source snapshot`、`weak_words_2d_live.py`（位置参数给快照路径）。
⚠ **快照会过期**：`doctor` 会对比快照与 live 收藏库的 mtime，差得太多就提醒 ——
离线分析看到的可能是旧数据。

`data/snapshots/pre_jiten_field_<时间戳>/` 是 `freq_external.py field --all-notes --commit`
的**写前基准**（diff 完不删，留档）；1 小时内的快照会被复用，不会每次落新副本。

### 6.4 `data/pylibs/`（约 316 MB，工作区本地第三方库）

SudachiPy + SudachiDict Core（日语形态素分析，词典解包后是大头）+ matplotlib，
供 `vocab_cover` 用。脚本通过 `_deps.add_pylibs()` 把它 append 到 `sys.path`，
**不进系统环境**，删目录即卸载。
重装：`python code/oneshot/install_workspace_wheels.py`（默认装 sudachipy、
sudachidict_core、matplotlib；版本锁在 `data/pylibs.lock.json`）。

**为什么需要这个绕路**：当前沙箱下 pip 有两个坑 ——
① `tempfile.mkdtemp` 建的 0o700 目录对受限令牌不可写，pip 的临时目录恰好全是 0o700；
② pip 的 PEP 517 子进程（构建 sdist 用）没有 `os.mkdir` 补丁，会在管道通信上挂死。
所以那个脚本打了 `os.mkdir` 补丁并强制 `--only-binary :all:`（只用预编译 wheel，
unidic-lite / ipadic 没有 wheel，故改用带 wheel 的 SudachiDict Core）。

### 6.5 两个自成一块的区域

`subtitles/` 是原始字幕素材（3 部作品、36 集 + 2 个「制作卡牌用」裁剪版，裁剪版被
`vocab_cover` 主动跳过），是 §4 分析区的输入；`core6000-analysis/` 是 core6000 听辨卡的
专项分析子项目，自带 `analyze*.py` / `build_report.py` / 图表 / docx 报告，
与 `code/` 各脚本互不依赖。两者都保持原地不动。

---

## 7. 已知例外与孤岛

- **`code/analysis/anki_analyze/`**（18 个脚本）是一个**离线诊断孤岛**：绝大多数脚本读同目录的
  `collection_snapshot.anki2`，该文件当前不存在。要启用先跑
  `python code/analysis/anki_analyze/introspect.py` —— 它把 `%APPDATA%\Anki2\账户 1\collection.anki2`
  复制成本地快照（**先关 Anki**，否则副本可能不一致）并打印表结构。
  它直接用 `sqlite3` 读库，是「唯一 Anki 访问点」约定的**已知例外**（与 `code/oneshot/` 同级）：
  `anki_api.py audit` 把它们列成**第二期待办**，不挡路。
- **`code/oneshot/`**：探针与一次性修复，用完即弃（现役 21 个，见 §1 表）；它是
  「唯一 Anki 访问点」的已知例外之一。用完的脚本挪 `archive/experiments/`。
- **`code/tools/backup_anki.py`** 是**文件级**例外：备份必须在 **Anki 完全关闭**时跑，
  那时 AnkiConnect 不可用 —— 它直连 8765 探「Anki 还开着吗」，并用 `sqlite3` 核对备份副本。
- **`archive/experiments/`**：探索期产物，只作参考、不保证能跑，
  见 [archive/experiments/README.md](../archive/experiments/README.md)。

---

## 8. 待办（已立项、未做）

- **每集流水线的 `state.json` 状态机**（阶段 0-5 断点恢复）：只留设计备忘，
  见 [docs/plans/](plans/)。
