# 废弃与退场记录（deprecated）

> 状态：active ｜ 最后核实：2026-10-23

**这是什么**：退场档案 —— 哪套机制/入口不用了、为什么、留下的数据在哪、想恢复要注意什么。
**为什么存在**：活跃文档只讲现在该怎么做；过去的事集中放这里，免得散落各处变成噪声。
**什么时候读**：翻到旧脚本/旧标签/旧计划文件想不起来是干什么的时候；**看这里的东西一律不要照着重跑**。
现状看 [README.md](../README.md) 与 [docs/architecture.md](architecture.md)。

`doctor` 第 4 项允许活跃代码/文档**指向**这里的旧入口（会放行带「已归档 / 已废弃 /
退场 / archive/ / docs/deprecated」字样的行），但不许再把它们当现役描述。

---

## 1. `gen_i1_prompt.py` —— i+1 短文提示词生成器

**废弃日期**：2026-10-06 ｜ **归档日期**：2026-10-10 ｜ **位置**：`archive/experiments/gen_i1_prompt/`

它回答「我接下来几天会学到哪些词」，用的是**位置前沿**口径：
`学习前沿 = 已学卡 due 的最大值`，再取 `due > 前沿` 的新卡 —— 它假设「已学卡位置在前、
新卡位置在后」。

**这个假设已经不成立**：2026-10-06 起三个词汇卡组的所有新卡被统一重排成**全局动漫词频序**
（`due` = 1…11990，来自 Jiten Anime 词表），新卡的 `due` 会落到已学卡位置**之前**。
实测（`…3-N3-N5-高频词汇::2-N2`）：已学 248 张 due∈[120, 225]，新卡 599 张 due∈[58, 11988]
→ 取 `due > 225` 只剩 590 张，**漏掉 9 个最高频的新词**。

**替代做法**：排序与「接下来该学哪些词」现在看笔记字段 **`JitenAnimeRank`**
（未学卡按它升序取前 N；它也是这两个笔记类型的排序字段），不要再用 `due` 猜前沿。
本集范围用 `activate.py` 的激活计划，每日范围用 `today_new.py` 的讲义。

- 代码：`archive/experiments/gen_i1_prompt/`（`gen_i1_prompt.py` + `test_i1_prompt.py`，原样保留）
- 说明：[docs/deprecated/gen_i1_prompt-使用说明.md](deprecated/gen_i1_prompt-使用说明.md)（路径已同步改到归档位置）
- 数据（**保留在原地，未删**）：`data/i1/gen_i1_cache.json`、`output/i1/`（含其内 `DEPRECATED.md`）

## 2. 「素材优先」准入标签 + 筛选牌组机制

**退场日期**：2026-10-06 ｜ **代码摘除日期**：2026-10-10

当时代的设计：大牌组（core6000/考级/素材生词）的 new/day = 0，**只做复习**；
新卡全部经由筛选牌组 **「素材优先」** 进来（搜索固定为 `is:new tag:素材优先`），
顺序由 `cards.due`（新卡位置）决定；任何新增素材卡的路径都必须打这个标签。

| 环节 | 当时代做法 | 现在 |
|---|---|---|
| 准入标签 | `素材优先`（唯一） | **不再使用**；标签已清零（12,064 个笔记 → 0） |
| 新卡入口 | 筛选牌组「素材优先」（每天 Rebuild） | 四个词汇选项组，`gather order = Ascending position`（`newGatherPriority = 1`），配合 `due` = Jiten 词频序 |
| 每日动作 | 打开筛选牌组 → Rebuild → 学完，毕业卡回原卡组 | 直接点学习；`new/day` 上限是各卡组自己的（2026-10-10 实读：core6000 = 15、考级 = 15、素材生词 = 20） |
| 溯源标签 | `素材激活::<集>`（阶段 3）、`素材生词::<日期>`（阶段 4） | **都保留**（它们从来不是为了准入） |

**为什么退场**：目标是「按动漫词频顺序学词汇」，而筛选牌组只能给一条独立的取卡队列，
和主卡组的顺序是两套东西；改成选项组后卡组自己就按全局词频发卡，跨子卡组也是同一个顺序。

**代码侧做了什么**（2026-10-10）：
- `activate.py`：不再写准入标签（`apply` 只打 `素材激活::<集>` 溯源标签）；
  旧的 `POOL_TAG` 常量改名 `LEGACY_POOL_TAG`，**只**供 `revert --unpool` 清理 2026-10-06 前的残留。
- `mine.py`：`write` 只打 `素材生词::<日期>`（+ 来源标签），不再写准入标签。
- `report`/`print` 里「会被筛选牌组自动收进新卡池」这类话一并删掉。
- `activate.py apply --global` 的说明从「筛选牌组（order=DUE）才拿到全局顺序」
  改成「大卡组按位置升序收集新卡时才会拿到同一个全局顺序」。

**恢复路径**（真要回到当时代）：标签移除清单在 `data/vocab_cover/pool_tag_removed.json`，
按它 `addTags` 即可补回；卡组选项的原配置备份在
`data/vocab_cover/deck_config_legacy_backup.json`（把 `newGatherPriority` 改回 `0`）。
一次性迁移脚本 `code/oneshot/migrate_pool_tag.py` 保留作历史参考。

> **注意别混**：`make_activate_plan.py --tag` 的默认值仍是 `素材优先`，那是
> **`素材激活::<tag>` 的溯源后缀**（生成 `plan_activate_素材优先.json`），
> 与退场的准入标签是两码事 —— 所以它没被改掉。

## 3. `code/tools/regress_pipeline.py` —— pipeline.classify 回归自检

**归档日期**：2026-10-10 ｜ **位置**：`archive/experiments/regress_pipeline/`

它自己的 docstring 已写明：**311 条基线无法逐条复现** —— 原因不是代码变了，而是语料变小了
（基线记于 2026-09 第 04 集跑通时，`2-例句` 有 311 张，现在只剩 227 张；参照系与查重基线都变了，
判定必然漂移）。实测逐条一致率 266/311（85.5%），**不能当验收标准**。
它推荐的确定性替代 `archive/experiments/activate_checks/prove_inert.py` **已不在盘上**
（那个子目录整体已清理），指针失效 —— 这正是它被移出活跃区的原因之一。

**现在用什么替代**：`pipeline.py triage` 演练 + 与上一份计划文件做 diff（只读）；
数据/接口健康则用 `python code/cli.py doctor`。
将来真要做回归，需要先**冻结 fixture**（verdict.csv 连同当时的卡组快照），
而不是拿活牌组当参照系（`data/evidence/ep04_backup/verdict.csv` 仍在原地，未删）。

## 4. 一次性临时探针

**归档日期**：2026-10-10 ｜ **位置**：`archive/experiments/tmp_probes/`

例：`_tmp_deckopts.py`（实测「首学 → 间隔首次 ≥21 天」的日历天数分布）。
这类脚本没有 `import textio`、也不是任何链路的一环，落在活跃区会被 `textio audit` 的 R2 卡住。
**以后再做临时验证，直接放 `temp/`（唯一的一次性文件区，做完 `python code/cli.py temp clean` 清空）；
要留档的才挪 `archive/experiments/tmp_probes/`。**

## 5. 不废弃、但停在原地的：`code/analysis/anki_analyze/`

**状态：standby（未废弃）** ｜ 详见 [docs/architecture.md §7](architecture.md)

18 个脚本的离线诊断孤岛，绝大部分读同目录的 `collection_snapshot.anki2`（当前不存在）。
要启用先跑 `python code/analysis/anki_analyze/introspect.py`（先从本地收藏复制一份快照，
**先关 Anki**）。它直连 `sqlite3`，是「唯一 Anki 访问点」的已知例外 ——
`anki_api.py audit` 把它与 `code/oneshot/` 一起列成**第二期待办**，不挡路。

## 6. 阶段三「词汇卡激活」（`activate.py` 的 `plan` / `apply`）

**退场日期**：2026-10-12

当时做法：把一集例句卡里出现、但词汇卡组还没学的词，提前排进新卡队列（改 `cards.due`），
并打 `素材激活::<集>` 溯源标签，让「这一集马上会碰到的词」先学。

现在：不排位置、不打准入/激活标签。「先学哪个词」只看笔记字段 **`JitenAnimeRank`**
（`%06d` 补零，`999999` = 词表里没有），由 `mine.py` 入库时与 `episode.py` 的 `rank` 阶段写。

`activate.py` 只为两件事保留：① `vocab reorder-jiten` preset 的全链重排（全局词频序，
见 [architecture §2.1](architecture.md)）；② `revert` 历史批次。
回退依据：`data/plans/plan_activate_*.json`（每张卡的 `due_before`），**别删**。

## 7. 关于 `docs/plans/` 与 `docs/reports/`

这两处是**史料**，不是指令：

- `docs/plans/` 是改动档案（立项时的计划 + 执行记录，如
  [2026-10-08-Anki接口统一-anki_api.md](plans/2026-10-08-Anki接口统一-anki_api.md)）。
  里面提到当时存在、现在已归档的脚本是正常的。
- `docs/reports/` 是日期化的分析产物（日期在文件名或正文里）；其中 `sample/` 是作者主动公开的
  脱敏样板（入库），其余不入库。

所以 `doctor` 第 4 项（废弃符号残留）**不扫**这两处，第 6 项（文档状态行）也不要求
`reports/` 每篇都加状态行。

## 8. `wordlist_due.py` / `subtitle_review.py` —— 字幕生词排期

**删除日期**：2026-10-23

当时做法：`subtitle_new_words.py` 挑出字幕里「Anki 已有、还没学」的词后，
`wordlist_due.py` 用 Anki 原生 `setDueDate` 把新卡设成明天到期（`type 0 → 2`），
并打 `字幕复习::<日期>` 标签（`--source` 时再打一条来源标签）；
`subtitle_review.py` 是「提取 → 排期」的一键包装。

**为什么退场**：不再需要把整集生词批量排进第二天；复习入口现在就是 `复习::<来源>` 标签
（见技能 `jp-anki-subtitle-tag`），在浏览器里 `tag:复习` 就能看到全部待复习词。
排期工具还会给词追加 `复习::<日期>` 标签，与「一个词只挂一个复习标签」的规则冲突。

**现在怎么做**：只打标签（`subtitle_tag.py`，只写 tags，不改 `due`）；
真要动新卡位置用 `jp-anki-activate` / `activate.py`（改 `cards.due`，不碰 ivl/type/queue）。

**恢复路径**：从工作区备份（`cli.py backup`）或 git 历史取回这两个文件；
注意它们的标签前缀当时是 `字幕复习`，恢复后要改成 `复习`。
