---
name: jp-anki-pipeline
description: anki-workspace 的**每集素材主线元技能**：本技能已拆分为 7 个独立的单任务技能，每个技能只负责一件事。本文档作为元索引，按需加载相应的单任务技能：

- `jp-anki-triage` —— 阶段 1 · 清理（含可选前置字幕层筛选 filter_subtitle）
- `jp-anki-generate` —— 生成 AINote + Sentence HTML（单卡/数张的原子能力；流程不写死，`cards.py gen/write`）
- `jp-anki-activate` —— 阶段 3 · 激活（把例句卡里的新词排进学习队列）
- `jp-anki-mine` —— 阶段 4 · 素材生词（挖词、建第三个词汇牌组）
- `jp-anki-audio` —— 阶段 5 · 生词配音（Word Audio / Sentence Audio + fix_word_audio 读错修复）
- `jp-anki-check-ruby` —— 振假名读音自检（拿字幕注音校验生成的 <ruby> 读法）

当用户说「按以往 pipeline 做这一集」时，按顺序加载上述技能，逐步执行；或使用 `code/cli.py episode …` 一条命令跑完阶段 2–5。**不含**每日讲义、弱项分析、core6000 补例句、加强 AINote 讲解——那四件在 `jp-anki-daily-*` 技能里。仅适用于 anki-workspace。
---

# 日语 Anki 每集素材主线（元索引：已拆分为单任务技能）

本技能已于 2026-10-20 拆分。原 `jp-anki-pipeline` 覆盖阶段 0–5 的多件事，现已拆分为 7 个独立的单任务技能，**每个技能只负责一件事**。按需加载相应技能，不再使用单一技能跑全流水线。

## 技能拆分清单

| 阶段 | 技能名 | 职责 | 关联脚本 |
|---|---|---|---|
| 0 | `jp-anki-triage` | 判据 + 清理（triage/apply） | `code/execution/pipeline.py` |
| 1（可选前置） | `jp-anki-triage` | 字幕层筛选 | `code/execution/filter_subtitle.py` |
| 2 | `jp-anki-generate` | 按张生成 AINote + Sentence HTML（原子能力；不规定流程） | `code/execution/cards.py` + `code/common/ruby_engine.py` |
| 3 | `jp-anki-activate` | 词汇卡激活 | `code/execution/activate.py` |
| 4 | `jp-anki-mine` | 素材生词挖掘 | `code/execution/mine.py` |
| 5 | `jp-anki-audio` | 生词配音 + 读错修复 | `code/execution/mine_audio.py` + `code/tools/fix_word_audio.py` |
| 闸门 | `jp-anki-check-ruby` | 振假名读音自检 | `code/common/check_ruby.py` |

## 推荐入口（未变）

```powershell
# 演练（阶段 2–5，不写库）
& $PY "$WS\code\cli.py" episode --tag "动画::<作品名>::<季>::第NN集" `
    --input-tag 待标记 --plan "data/evidence/<集>/plan.json"

# 真写
& $PY "$WS\code\cli.py" episode --tag "动画::…::第NN集" --input-tag 待标记 --commit

# 只跑某几步
& $PY "$WS\code\cli.py" episode --tag "动画::…::第NN集" --phases ruby,rank
```

`code/execution/episode.py` 把分支、重试、闸门、报告全放进代码，作为各单任务技能的编排器。各单任务技能仍可独立加载，按需单步执行。

## 迁移指南

| 旧用法 | 新用法 |
|---|---|
| 加载 `jp-anki-pipeline` 跑全流程 | 加载 `jp-anki-triage` → `jp-anki-generate` → `jp-anki-activate` → `jp-anki-mine` → `jp-anki-audio`，按需单步执行 |
| 只跑某一阶段 | 直接加载对应单任务技能 |
| `cli.py episode` 一条命令 | 保持不变，作为编排器 |

## 共同铁律（与各单任务技能共用）

见各单任务技能 SKILL.md 第一节。跨技能的共同铁律（默认演练、能可逆就可逆、不要 pip install、Anki 浏览器里开着卡写字段不会刷新、api key 查找顺序、同一件事只查一次、一切文本 I/O 走 textio.py）保持不变。

---

**本技能为元索引，不包含可执行逻辑。** 实际执行由各单任务技能负责。每集素材的 triage/生成/激活/挖生词/配音不在本技能（见各单任务技能）。仅适用于 anki-workspace。
