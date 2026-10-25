# ADR：`JitenAnimeRank` 只作注解，队列顺序一律看 `cards.due`

> 状态：active ｜ 最后核实：2026-10-10 ｜ 日期：2026-10

## 背景

把 Jiten 词频排名写进笔记字段后，很容易产生一个误解：
「既然是排序字段，那把它改掉是不是就改了学习顺序？」

事实：Anki 新卡队列的顺序**只有一个来源** —— `cards.due`（= 位置）。
`Filtered.SearchTerm.Order` 与卡组的 `NewCardGatherPriority` / `NewCardSortOrder`
枚举里**都没有「按字段排」这一项**；手册对排序字段（Sort Field）只有一句
「show this field in the Sort Field column of the browser」，
并明确 `Reposition` 才是 "Change the order new cards will appear in"。

## 决定

1. `JitenAnimeRank` 定位为**注解**：`%06d` 补零（浏览器文本序 == 数值序），
   词表里查不到的写 `999999`（排最后）。
2. **决定学习顺序的是 `due`**：全局重排走 `make_activate_plan.py … --global` →
   `activate.py apply --global`（`python code/cli.py vocab reorder-jiten`）；
   每集插队走当集的 `activate.py`（不带 `--global`）。
3. 字段的两个合法用途：浏览器里按它排序/加列、模板里 `{{JitenAnimeRank}}` 显示、
   以及用 regex 搜字段（如「只学排名 < N」的筛选）。

## 理由

- 排序字段与调度位置是**两个不同的列**：前者是笔记字段（`notes.flds`），
  后者是卡片列（`cards.due`）。改字段不会移动卡片。
- 写 `due` 才能被卡组的位置升序收集顺序（`Ascending position`）读到；
  这也是「全局词频序」得以成立的机制（ADR-1）。

## 影响

- ⚠ **加字段的副作用**：Anki 会给该笔记类型的**全部**笔记补空字段 ——
  实测 17,633 个笔记里 16,649 个的 `flds`/`mod` 被改（11,990 写值 + 4,659 补空），
  下次同步要传这 16,649 个笔记（一次性大 delta）。
  **2026-10-10 已加护栏**：`freq_external.py field --all-notes` 演练/真写都打印
  同步影响行；`--commit` 前先确保写前快照（1 小时内可复用，否则现落
  `data/snapshots/pre_jiten_field_<时间戳>/`），写后 diff 受影响卡片的调度列并告警
  （见 [docs/architecture.md §9](../architecture.md)）。
- 新建卡（`mine.py write`）拿到的是随机位置，**不会**因为字段有值就自动归位：
  要归位必须重排。这是最容易误判的一点。
- 卡片调度列（`due/ivl/factor/reps/lapses/type/queue`）与字段写入**无关**：
  写字段前后逐字段 diff 过，已学卡调度列改动 0 张。

相关：[docs/architecture.md §5.3-5.4](../architecture.md)。

## 更新（2026-10-16）

* 本机这版 **AnkiConnect 写不了 `due`**：`setSpecificValueOfCard` 把 `due`/`type`/`queue`
  列为 protected（`compatibilityError`），`scheduling_setDueDate` 走 `col.sched.set_due_date`
  （对新卡＝转成复习卡，不是排位置）。所以 `code\execution\reposition.py --commit` **此路不通**，
  该工具只留 `--check` 只读体检（数 due 序 vs rank 序的逆序对）。
* 改 `due` 的入口换成**插件**：`jiten_reorder` 在 Anki 进程内用 `col.update_card()` 把
  `0-素材生词` 的**新卡** `due` 设成 `int(JitenAnimeRank)`（空/非数字 → `999999`），
  打开配置时静默跑 + 工具菜单手动跑。
  说明：[docs/jiten-reorder-使用说明.md](../jiten-reorder-使用说明.md)；
  源码/安装包：`data/anki_addon/jiten_reorder/` 与 `data/anki_addon/jiten_reorder.ankiaddon`。
* 上面第 2 条的 `activate.py apply --global` / `vocab reorder-jiten` **已退役**
  （阶段三 activate 2026-10-12 退役，见 [pipeline-guide.md](../pipeline-guide.md)）。
  **结论不变：队列顺序只看 `cards.due`，字段始终只是注解。**
