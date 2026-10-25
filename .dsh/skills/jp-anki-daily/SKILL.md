---
name: jp-anki-daily
description: anki-workspace 的**日常学习链路元技能**：本技能已拆分为 3 个独立的单任务技能，每个技能只负责一件事。本文档作为元索引，按需加载相应的单任务技能：

- `jp-anki-daily-lesson` —— 每天早上学新卡前把「今日新卡」变成一份日语讲义（today_new.py，直连本地模型 /v1/responses，不派子代理）
- `jp-anki-daily-weak` —— 复习后的弱项分析（today_weak.py：今天/近三天答得不好的词与语法、复习负载与报告）
- `jp-anki-core6000-example` —— 按需给用户点名的 core6000 词补第二条例句（core6000_example.py：新句 + 振假名 + 合并讲解 + edge-TTS 配音，固定 gen → tts → apply）

当用户说「跑今天的讲义 / 每日任务」「早上学新卡前先讲一遍」时加载 `jp-anki-daily-lesson`；说「跑一下今天弱项 / 弱词 / 出个报告」时加载 `jp-anki-daily-weak`；说「这几个词我记不住，给我加一句例句」「把今天答得不好的词挑几个补一句例句」时加载 `jp-anki-core6000-example`。**不含**每集素材的 triage/生成/挖生词/配音——那四件在 `jp-anki-pipeline-*` 技能里。仅适用于 anki-workspace。
---

# 日语 Anki 日常链路（元索引：已拆分为单任务技能）

本技能已于 2026-10-20 拆分。原 `jp-anki-daily` 覆盖每日讲义、弱项分析、核心6000 补例句三件事，现已拆分为 3 个独立的单任务技能，**每个技能只负责一件事**。按需加载相应技能，不再使用单一技能跑全链路。

## 技能拆分清单

| 任务 | 技能名 | 职责 | 关联脚本 |
|---|---|---|---|
| ① | `jp-anki-daily-lesson` | 每日讲义（今日新卡 → 讲义） | `code/execution/today_new.py` |
| ② | `jp-anki-daily-weak` | 弱项分析（今天/近三天答得不好的词与语法） | `code/analysis/today_weak.py` |
| ③ | `jp-anki-core6000-example` | 按需补例句（核心6000 词 + 第二条例句 + 配音） | `code/execution/core6000_example.py` |

## 入口映射（未变）

| 用户话术 | 加载的技能 |
|---|---|
| 「跑今天的讲义 / 每日任务 / 早上学新卡前先讲一遍」 | `jp-anki-daily-lesson` |
| 「跑一下今天弱项 / 弱词 / 出个报告」 | `jp-anki-daily-weak` |
| 「这几个词我记不住，给我加一句例句」 | `jp-anki-core6000-example` |
| 「把今天答得不好的词挑几个补一句例句」 | `jp-anki-core6000-example`（--from-weak） |
| 「这张卡的讲解太薄，帮我讲透 / 加一段语感」 | `jp-anki-core6000-example`（含 ainote_enrich） |

## 共同铁律（与各单任务技能共用）

见各单任务技能 SKILL.md 第一节。跨技能的共同铁律（默认演练、能可逆就可逆、不要 pip install、Anki 浏览器里开着卡写字段不会刷新、api key 查找顺序、同一件事只查一次、一切文本 I/O 走 textio.py、机械判断不进语言模型）保持不变。

---

**本技能为元索引，不包含可执行逻辑。** 实际执行由各单任务技能负责。每集素材的 triage/生成/挖生词/配音不在本技能（见 `jp-anki-pipeline-*` 技能）。仅适用于 anki-workspace。
