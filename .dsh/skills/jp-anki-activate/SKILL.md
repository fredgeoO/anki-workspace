---
name: jp-anki-activate
description: anki-workspace 的**阶段 3 · 激活**：把例句卡里遇到、但词汇卡组里**还没学过**的词，提前排进学习队列。只碰 type == 0（新卡），只写 cards.due（新卡的位置），绝不写 ivl / factor / type / queue / reps / lapses。apply 默认演练，必须显式 --commit 才真写。当用户说「把这集里的生词优先排到前面学」「新卡位置要重排」「这批词我要先学」时加载本技能。**不含**清理、生成、挖生词、配音——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语 Anki 阶段 3 · 激活（素材驱动激活）

本技能覆盖**一件事**：把例句卡里遇到、但词汇卡组里**还没学过**的词，提前排进学习队列。

## 一、设计约束（不可违背）

1. 只碰 type == 0（新卡）。学习中(1)/复习(2)/重学(3) 一律不动——不重置任何已学进度。
2. 只写 `cards.due`（新卡的位置），绝不写 `ivl` / `factor` / `type` / `queue` / `reps` / `lapses`。
3. plan 阶段只读，不写库。
4. apply 默认演练；必须显式 `--commit` 才真写。
5. apply 前逐卡从 live Anki 重读状态，已不是新卡的直接跳过并列出。

## 二、命令

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$EXE = "$WS\code\execution"
```

### 3.1 报告（只读，不写库）

```powershell
& $PY "$EXE\activate.py" plan --tag "动画::<作品名>::<季>::第NN集"
```

`--tag` 传本集例句卡的标签，与具体作品无关。三处的字符串必须逐字一致（与 `split --tag` / `mine.py scan --tag` 对应）。

### 3.2 演练（读库、算好新位置，但不写）

```powershell
& $PY "$EXE\activate.py" apply --plan plan_activate.json
```

### 3.3 真写

```powershell
& $PY "$EXE\activate.py" apply --plan plan_activate.json --commit
```

## 三、为什么用 due

Anki 新卡队列按 `cards.due`（即"位置"）排序取卡，所以把位置调到最前面 = 让这些卡优先进入学习队列。卡的 1 分钟/10 分钟 学习步、毕业间隔全部保留，和 Anki 自带的「浏览器 → 重新定位」是同一个动作。

## 四、已验证的坑

- AnkiConnect 的 `setSpecificValueOfCard` 对数值列**必须传整数**。传字符串（`newValues=['13924']`）会被静默忽略、不报错。
- **不排新卡位置**：排序只看 `JitenAnimeRank`。本阶段没有动作——新卡由 `addNotes` 拿随机位置，**不用** Reposition、**不要**跑 `make_activate_plan.py --all-cards …` 全局重排（一次会动上万张新卡的 `due`）。
- 生词卡由 `mine.py` 入库时写好，例句卡由 `episode.py` 的 `rank` 阶段写。字段空了或要批量补 → 技能 `jp-anki-jiten-rank`（只补字段、不排位置）。
- 新卡怎么发仍由卡组选项决定（`gather order = Ascending position`，各卡组的新卡日限额以选项实值为准）。

## 五、收工汇报

- 计划文件路径、可激活词数（被排除多少）；
- 是否 `--commit` 真写；
- `backup_<时间戳>.json` 路径（若需要回退）。

---

**本技能只做激活。** 清理（阶段 1）→ `jp-anki-triage`；生成（阶段 2）→ `jp-anki-generate`；挖生词（阶段 4）→ `jp-anki-mine`；配音（阶段 5）→ `jp-anki-audio`。
