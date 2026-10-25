---
name: jp-anki-triage
description: anki-workspace 的**阶段 1 · 清理**：把一集字幕/对白导入的例句卡里无学习内容的卡挑出来。可选前置：字幕层筛选（filter_subtitle），在入库前就把不值得做成例句卡的片段删掉，降低后续 triage 和生成的人工量。当用户说「这集的卡要先清理」「判一下哪些卡不学」「字幕要先筛一遍再导卡」时加载本技能。**不含**生成、激活、挖生词、配音——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语 Anki 阶段 1 · 清理（triage）

本技能覆盖**一件事**：把导入的例句卡里**无学习内容**的卡挑出来，产出判据报告 + 执行计划。

## 一、入口与命令

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$EXE = "$WS\code\execution"
```

### 1.1 阶段 1 · 清理（出报告 → 人工确认 → 执行）

```powershell
# 只出报告，不改库
& $PY "$EXE\pipeline.py" triage --query "tag:待标记"

# 看报告确认后执行：对 plan.json 的弃用集，加标签 待标记::弃 + suspend
& $PY "$EXE\pipeline.py" apply
```

产出：`data/pipeline/drop_candidates.md` / `keep_list.md` / `plan.json`。

**停下来人工过一遍报告**，重点看判据的已知盲区（手册 §1.3）：纯假名副词（`おそらく`）、可能形（`乗れる`）、派生名词（`優しさ`）、熟语只有 80 条。

回退：浏览器搜 `deck:0-日本语学习::2-例句 is:suspended` → 取消暂停 → 移除 `待标记::弃`。

> ⚠️ **`apply` 不会摘掉集标签**，而 `split` 的查询是 `tag:<集标签> AINote:`——不含 `is:suspended`，也不排除判弃卡。也就是说刚被判弃的卡（集标签还在、`AINote` 还是空的）会被 `split` 一起拿去生成。若这一集确实要判弃，**在 split 之前**先在浏览器里把集标签从判弃卡上摘掉（搜 `tag:<集标签> tag:待标记::弃` → 移除集标签）。`preflight.py` 会把这个冲突直接报出来。

### 1.2 可选前置 · 字幕层筛选（比入库后再清理更省事）

想连导卡的人工一起省掉，就先把字幕筛一遍，再拿筛选后的 SRT 导卡；这样阶段 1 基本无事可做。

```powershell
& $PY "$EXE\filter_subtitle.py" probe  --src "<原始 srt>"
& $PY "$EXE\filter_subtitle.py" apply  --plan "data/evidence/<集>/plan.json"
& $PY "$EXE\filter_subtitle.py" verify --plan "data/evidence/<集>/plan.json"
```

判据与阶段 1 一致，额外要求句子完整、脱离上下文也能读懂。证据落在 `data/evidence/<集>/`。

判弃是**不可逆**的（漏掉的句子永远不会变成卡），所以判弃块要用复核短名单压一压：

```powershell
& $PY "$WS\code\tools\review_shortlist.py" --verdict "data/evidence/<集>/verdict.csv"
```

## 二、收工汇报

- 本集标签、导入张数 → 判弃/保留张数；
- 落盘路径（`data/pipeline/drop_candidates.md`、`keep_list.md`、`plan.json`）；
- 需要用户人工确认的点（报告里标出的已知盲区）。

---

**本技能只做清理。** 生成（阶段 2）→ `jp-anki-generate`；激活（阶段 3）→ `jp-anki-activate`；挖生词（阶段 4）→ `jp-anki-mine`；配音（阶段 5）→ `jp-anki-audio`。
