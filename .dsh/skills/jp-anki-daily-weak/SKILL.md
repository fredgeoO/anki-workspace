---
name: jp-anki-daily-weak
description: anki-workspace 的**日常任务 ② · 弱项分析**：复习后的弱项分析，今天/近三天答得不好的词与语法、复习负载与报告。`today_weak.py` 数据默认来自 AnkiConnect（Anki 需开着，永远是实时数据）；加 ``--source snapshot`` 则直读收藏快照文件，不需要 Anki 在运行。名字走 stdout，统计信息走 stderr，所以 ``--plain`` 的输出可以直接重定向到文件或喂给别的脚本。当用户说「跑一下今天弱项 / 弱词 / 出个报告」「最近几天答得不好的词有哪些」「复习负载怎么样」时加载本技能。**不含**每日讲义、核心6000 补例句、每集素材流水线——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语 Anki 日常链路 ② · 弱项分析（今天/近几天答得不好的卡）

本技能覆盖**一件事**：列出「最近 N 天答得不好的卡」的名字——只要单词名 / 语法名。

## 一、命令

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$AN  = "$WS\code\analysis"
$DAT = "$WS\data"
```

### 2.1 基础用法

```powershell
# 今天（重来+困难）
& $PY "$AN\today_weak.py"

# 只看「重来」
& $PY "$AN\today_weak.py" --rating again

# 只看「困难」
& $PY "$AN\today_weak.py" --rating hard

# 近三天
& $PY "$AN\today_weak.py" --days 3

# 纯名字，一行一个（好复制/管道）
& $PY "$AN\today_weak.py" --plain --days 3

# 附读音、释义
& $PY "$AN\today_weak.py" --plain --days 3 -v

# 只看语法
& $PY "$AN\today_weak.py" --kind grammar

# 限定牌组
& $PY "$AN\today_weak.py" --deck "日语::N3"

# 机器可读
& $PY "$AN\today_weak.py" --json

# 输出到文件
& $PY "$AN\today_weak.py" --json --out "$DAT\weak\today_weak.json"
```

约定：**名字走 stdout，统计信息走 stderr**，所以 ``--plain`` 的输出可以直接重定向到文件或喂给别的脚本。

## 二、用户说"跑一下今天弱项"时

默认把结果**直接贴在回复里**（`--plain` 或默认表格），不要只报"已完成"。

## 三、其余入口（同一技能下的相关工具，但不属于本技能核心流程）

- `code\analysis\analyze_revlog.py`、`weak_words_2d_live.py`、`make_weak_list.py` —— 复习日志与弱词分析。
- `code\analysis\planning\anki_plan.py` —— 学习量/配比模拟。
- 报告写进 `docs/reports/`，命名沿用既有风格（如 `日语学习诊断报告.md`、`anki学习报告-YYYY-MM-DD.md`）。
- `code\analysis\anki_analyze\` 是个离线工具岛：18 个脚本读同目录的 `collection_snapshot.anki2`，该文件**当前不存在**；要启用先跑 `& $PY "$AN\anki_analyze\introspect.py"` —— 它把 `%APPDATA%\Anki2\账户 1\collection.anki2` 复制成本地快照（**先关 Anki**，否则副本可能不一致），并打印表结构。这是「唯一 Anki 访问点」约定的**已知例外**（与 `oneshot/` 同级）。

## 四、收工汇报

- 直接把弱项词表**贴在回复里**（不要只报"已完成"），有报告就附路径。

---

**本技能只做弱项分析。** 每日讲义 → `jp-anki-daily-lesson`；核心6000 补例句 → `jp-anki-core6000-example`；每集素材流水线 → `jp-anki-triage` / `jp-anki-generate` / `jp-anki-activate` / `jp-anki-mine` / `jp-anki-audio`。
