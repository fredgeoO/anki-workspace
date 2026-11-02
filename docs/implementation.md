# 实现与内部机制（implementation）

> 状态：active ｜ 最后核实：2026-11-01

**这是什么**：从根 [README](../README.md) 迁出的实现细节——数据流、流水线各阶段、选词打分、
覆盖率口径、测试矩阵、仓库边界。README 只留使用者要的「怎么用」，想知道「它到底怎么算、产物落在哪、
改脚本前该看什么」，读这一页。
**什么时候读**：想核对某个数字的口径、排查产物不对、或准备改 `code/` 下的脚本时。
每一节都指向更权威的专项手册；两处冲突时以专项手册为准。

---

## 1. 数据流

```
Anki 收藏 ──复制──> data/snapshots/…                    （分析用只读快照）

pipeline.py（阶段 0-1）──> 判弃无学习内容的卡（prepare / triage）

episode.py ──> pipeline.py（阶段 2）──> mine.py（阶段 4）──> mine_audio.py（阶段 5）
                                   └──> data/pipeline/gen/     data/vocab/      output/audio/

proper.py         ──> data/vocab/proper/<作品>_<集>/（专名卡，不进队列）
today_new.py      ──> output/daily/{cards_*.json, lessons/*, lesson_*.md}（直连本地模型）
today_new_words   ──> data/daily_new/ + output/daily/today_new_words.md（每天 N 个「今天学习生词」）
core6000_example  ──> 5 个字段 + output/audio/core6000/*.mp3
ainote_enrich     ──> 只写 AINote（旧值备份 data/ainote/backup_*.json）
analysis/         ──> docs/reports/*.md、data/vocab_cover/*、output/vocab_cover/*.png
```

统一入口是 `code/cli.py`（组 → 脚本映射，不含业务逻辑）。代码分区、各脚本职责见
[architecture.md §1-2](architecture.md)。

## 2. 一集字幕的流水线：阶段与产物

一条每集流水线由下面几步组成：阶段 0–1 先单独跑（`prepare` / `triage`），
`cli.py episode` 负责阶段 2–5（`--commit` 才真写；不加则全链演练）：

| 阶段 | 谁跑 | 产物 |
|---|---|---|
| 0–1 预处理 + 清理 | `pipeline.py prepare` → `triage` | 判弃无学习内容的卡；可选先跑 `filter_subtitle.py` 筛字幕 |
| 2 生成 | `pipeline.py gen` | `data/pipeline/gen/{input,output,manifest}.json`；`AINote` + `Sentence HTML` |
| 4 素材生词 | `mine.py` | `data/vocab/{mine_candidates.json,gen_mine/*}` → `0-素材生词` |
| 5 配音 | `mine_audio.py` | `output/audio/*.mp3` → 上传 Anki 媒体库 |
| 改标签 | `episode.py retag` | 把导入时的 `待标记` 换成正式集标签 |

运行记录落在 `data/pipeline/runs/<时间戳>-<集>.json`。每步的判据、批次建议、失败重试见
[pipeline-guide.md](pipeline-guide.md)（60 KB，按节查，不必通读）；只想重跑某几步时用
`episode --phases stage2,mine,audio`。

## 3. 「今天学习生词」怎么选

给一集字幕或整部作品的目录，**四段分工**（2026-11-01 起；机械判断归代码、语义判断归模型）：

| 段 | 谁做 | 做什么 |
|---|---|---|
| 1 抽候选 | Sudachi + 词库索引 | 逐句分词 → 词典形 → 只在三个词汇牌组命中才算候选；复合词再拼查一次。**窗口 = 你指定的那一集**（默认只这一集，给目录或 `--season` 才整季） |
| 2 排除懂的 | 代码 | 按笔记判已学/挂起；只挡没有 JAR 排名（字段空 / 0 / 999999）；读音闸（卡片读音 ∩ 字幕读音） |
| 3 排序 | **本地模型，一集一次** | 读整集台词 + 本集候选，按「动漫对白实用度 > 学习/编卡价值 > 一般通用度」给有序名单；**各集并行**（端点开几个槽用几个）；模型钉 128K 的 `qwen3.8-flash-next-iq3_s`，换档要显式 `--model` |
| 4 兜底 | 公式 | 模型不可用 / `--no-llm-rank` / 候选为空时才定序 |

公式仍保留，但只做兜底与参考列：

```
S = ln(1+次数) + 0.30·ln(1+集数) + 0.30·ln(30000/JAR)
```

**次数翻一倍 ≈ JAR 排名前移 10 倍**（`2^(1/0.30)`）。`--mu` 管跨集加成、`--lam` 管词频权重。

> 为什么不再用公式主排：`梅`（人名）、`たん`（后缀）、`え`/`うっ`（语气词）靠出现次数
> 排进前几，`生徒会`/`校則`/`違反` 这类真正该学的词被挤掉。次数只说明「本作里常见」，
> 不说明「值得学」。实测一集 462 句：Sudachi 命中 597 个库内词、模型只看回 516 个，
> 但模型漏掉的多是 `こと`/`する` 这类功能词与语气词——正是该排后的；（顺带修掉一个
> 真 bug：Sudachi 把な形容词标成 `形状詞`，而白名单里写的是 `形容動詞`，整类被丢）。

选出来的词还要过两道闸，否则今天学的就是错的义项：

| 闸 | 判据 | 挡掉的例子 |
|---|---|---|
| **读音**（机械，免费） | 卡片读音 vs 字幕里该词的词典形读音 | `頭` 名下 `あたま`（头）和 `かしら`（首领）两张卡，只标对得上的那张 |
| **义项**（本地模型） | 字幕句里的义项 vs 卡片释义 | `空`（卡片「空的」/ 字幕「空の下」＝天空）、`吐く`（「呕吐」/ 吸烟语境＝呼气） |

助词、感动词、角色语尾（`かしら`、`〜にゃ`）直接影响对白语气，**单独给 2 个名额**
（`--particles`），不跟内容词抢；格助词/系助词/接续助词（が・で・を・は）作为语法胶水排除。

**没有 JAR 排名**（字段空、0、999999）的词不进今天名单，但登记到
`data/daily_new/unranked.json`；`doctor` 非空就报**提示**（退出码 2），留待用户建卡或补 JAR。
补上 JAR 的词在下次 `--commit` 运行时自动出清。

**JAR > 30000 不再是门槛**（2026-11-01 去掉）：有排名就进候选，重要性交给模型精排；
公式里的频率项对 ≥30000 一律记 0 分（夹在 1–30000），不会爆分也不会算出负数。

**只写 `tags`**，不碰 `due/ivl/factor/type/queue`；每次运行先把全库旧标签摘掉，所以这个标签
永远只代表「今天这一批」。产物：`output/daily/today_new_words.md`（名单 + 模型理由）、
`data/daily_new/<日期>/picked.json`（模型名次 / 理由 / 分数拆解 / noteId）、
`data/daily_new/state.json`（回退记录）、`data/daily_new/unranked.json`（待建卡清单）、
`data/daily_new/rank_cache.json`（精排缓存）、`data/daily_new/sense_cache.json`（义项判定缓存）。
**2026-11-02 起义项闸判 false 的词默认先修再剔**：`sense_repair.py` 给原卡补真实例句 +
重写 `Meaning`（只写白名单字段，走 writeback 备份/回读，同样受 `--commit` 管），
重判通过按原名次回插；`--no-sense-repair` 退回只剔不修。讲义侧怎么消费这个 tag 见
[today_new-使用说明.md](today_new-使用说明.md)；打分与义项核验的取舍见
[ADR 2026-10-29](decisions/2026-10-29-今日选词打分与义项核验.md)。

## 4. 任意文本/字幕的覆盖率与生词分析

流水线之外的一条**随时可跑的体检链**：输入任意 `.srt/.ass/.vtt`、`.txt`、一段话或标准输入，
回答「这段文字我认识多少、还差哪些词」。词汇状态来自 AnkiConnect 现场快照
（`collect_vocab.py` 抽成 `data/vocab_cover/vocab_state.json`），换素材不用动卡组。

| 想知道什么 | 命令 | 产物 |
|---|---|---|
| 这段文字我懂多少 | `cli.py vocab cover <文件>`（也吃 `--text` / `--stdin`） | 三个分母的覆盖率、句子级可懂度、新词预览 |
| 新词具体是哪些 | `cli.py vocab newwords <文件或目录> --mine-only` | 读音 / 词性 / 首例句 / Jiten 档位，可导 TSV、Markdown、JSON |
| 出一份学习用生词报告 | `cli.py vocab report <文件或目录>` | 固定章节的 Markdown + JSON（规模 / 分档 / 题材词 / 值得挖 / 不用记） |
| 每季只挖前 N 集值不值 | `cli.py vocab mine_window --k 3` | 覆盖占比、效率、边际效率、窗口外高价值词 |
| 全部字幕的整体水位 | `python code\analysis\vocab_cover\report_build.py` | 自动刷新快照 + `metrics.json` + 5 张图 + Markdown |
| 卡组贴不贴动漫词频榜 | `jiten_fit.py` / `rank_buckets.py`（`vocab_cover` 下） | 榜→卡组覆盖、卡组→榜名次、每千词已学占比 |
| 学哪些、还差多少、每天放几张 | `study_plan.py` / `mature_eta.py` / `study_time_budget.py` | 学习顺序收益、全成熟 ETA、新卡时间预算 |

**口径**：三个分母差别很大，报告里必须写清——**含语法词**（全部词元，助词/助动词按「你懂」计）、
**词汇词**（去掉语法词与符号）、**需背实词**（再去掉专有名词、感动词、数词，这才是词汇量的分母）。
「已学」= 刷过至少 1 次，「已成熟」= 复习卡且间隔 ≥ 21 天；分词走 SudachiPy，Jiten 名次按
「出现在多少部作品里」排，不按单部重复次数。新词也分两档：卡组外的 `oov` 与有卡没学的 `untackled`。

产物落在 `docs/reports/`（除 `sample/` 里已脱敏的样板外，本地产物不入库），图表在 `output/vocab_cover/`——
`字幕覆盖率与词汇量报告.md`、`挖掘窗口分析.md`、`Jiten动漫词库贴合度.md`、`词汇三卡组配比.md`
都是这条链跑出来的。报告数字随快照漂移，引用时以文件头的生成时间为准。
字段级口径与数据链细节见 [architecture.md §4-5](architecture.md)。

## 5. 测试矩阵

19 个回归测试都是**独立脚本、纯离线**（不连网、不碰 Anki 写接口），秒级返回；
2026-11-01 复核全部通过。跑法：

```powershell
& $PY "$WS\code\tests\test_llm_out.py"     # 换一个文件名就是另一组
```

| 测试 | 挡什么 |
|---|---|
| `test_llm_out.py` | 本地模型产出吸收层：畸形 JSON、字段类型错、整组超预算、漏卡重问 |
| `test_mine_patch.py` | 阶段四 `merge-fix` 的前缀回退（2026-10-12 事故） |
| `test_immersionkit.py` | ImmersionKit 抓句链路纯函数：振假名对齐、标签、字段一致性、gen 并回与并发顺序 |
| `test_jisho_example.py` | Jisho 例句解析、token 边界匹配（体中/ヤニ）、注音对不齐兜底 |
| `test_core6000_jisho.py` | core6000 补例句的「新句来自 Jisho」：书写骨架偏好、四道候选闸门、模型改写被覆盖 |
| `test_jiten_rank.py` | `JitenAnimeRank`/`JitenGlobalRank` 查表、词字段推导与 6 位补零（文本序 = 数值序）、三条写库路径交给 writeback 的载荷形状（2026-11-01 实测扁平值会炸 `--commit`） |
| `test_proper_extract.py` / `test_proper_patch.py` | 专名抽取的确定性部分、专名卡字段规则 |
| `test_subtitle_tag.py` | 字幕打标的纯逻辑：跳过已复习词、只写 tags |
| `test_today_new_words.py` | 每日生词挑选：打分公式、只挡无 JAR 排名（有排名 >30000 照收）、读音闸、名额、标签差集 |
| `test_lesson_render.py` | 每日讲义口径：词形/读音、词性校正、同词合并、接续脏数据、计数自洽、讲解机械错 |
| `test_lesson_dict.py` | 每日讲义的 JMdict 纠错：读音不在词典读音表、词性冲突、他动/自动、词典不可用降级、渲染校正 |
| `test_writeback.py` | 写库事务：演练不写、提交备份、回读失败上报、分块/quiet、调度接口不出现 |
| `test_batchjob.py` | 批处理清单：分批/manifest、同源跳过、`--force`、failed 形状与清理 |
| `test_episode_retag.py` | 编排 retag：走 `write_tags` 双向回读、演练不写 |
| `test_episode_scripts.py` | 编排脚本表存在性 + `rank` 进程内调用 |
| `test_cli_entries.py` | cli 入口表存在性、`list --check`、`resolve` 路径 |
| `test_ruby_wrap.py` | `<ruby>` 构造唯一：wrap / to_ruby / ruby_word / ruby_text |
| `test_core6000_text.py` | core6000 ② 的纯渲染：词性中文化、注音、词表目标行/去重，且只实现一份 |

跑完会在 `temp/test_*` 留下产物，属于正常（`temp/` 就是一次性文件区）。动过 `common/` 或
`execution/` 就把 `code\tests\*.py` 全跑一遍，19 个都 0 才算完；只改文档不用跑。

## 6. 仓库边界与数据安全

- git 只跟踪「源码 / 文档 / 技能 / 模板 / 字幕」；`data/`、`output/`、`docs/reports/`（`sample/` 除外）
  都不入库——**卡片资料没有 git 可退，唯一退路是备份**。清单见 [data/README.md](../data/README.md)。
- 写库脚本一律「默认演练、`--commit` 才真写」；改动前打印数量与清单，写后回读
  `AK.verify_note_fields`。工程约定见 [AGENTS.md §8](../AGENTS.md)。
- 备份收藏库前**完全退出 Anki**；新备份校验通过后才删旧的。唯一权威流程见
  [backup-sop.md](backup-sop.md)。
- 离线分析（`weak build-list`、`--source snapshot`）读 `data/snapshots/`，可能比 live 库
  差几天；判断冲突时以 live 收藏为准。
