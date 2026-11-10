# .dsh/skills/ —— 任务 → 技能路由

具体任务**先加载对应技能，再动手**，不要自创流程。技能正文在各子目录的 `SKILL.md`；
本页只做路由。同一件事有多个技能时，按「阶段」拆开：清理 → 生成 → 激活 → 挖词 → 配音。

| 想做的事 | 技能 |
|---|---|
| 清理一集的卡 / 入库前先筛字幕 | `jp-anki-triage` |
| 给一张或几张卡生成讲解 + 振假名 | `jp-anki-generate` |
| 处理 `tag:leech` 的难卡（诊断 + 改写卡背 + 记忆钩子） | `jp-anki-leech` |
| 把生词排到新卡队列前面（只改新卡 `due`） | `jp-anki-activate` |
| 从例句挖素材生词 → `0-素材生词` | `jp-anki-mine` |
| 给生词卡配音 / 修读错的 mp3 | `jp-anki-audio` |
| 校验振假名读音（对字幕自带注音） | `jp-anki-check-ruby` |
| 按 `需更新JAR` 回填 `JitenAnimeRank`；全量补 `JitenGlobalRank` | `jp-anki-jiten-rank` |
| 每日讲义（讲 tag `今天学习生词` 里的词；没有 tag 就不生成） | `jp-anki-daily-lesson` |
| 弱项分析 / 复习负载报告 | `jp-anki-daily-weak` |
| 库层面学习分析报告（留存 / 健康分 / 负荷 / 图表，R 包 ankiR） | `jp-anki-r-analysis` |
| 点名 core6000 词补第二条例句 | `jp-anki-core6000-example` |
| 给一个词找**真实**例句（jisho，不造句） | `jisho-example` |
| 专有名词收集 → `3-专有词汇`（不进队列） | `jp-anki-proper-noun` |
| 字幕/文字里没学过的词打 `复习::<名称>` | `jp-anki-subtitle-tag` |
| 每天从文字/字幕挑 N 个今天要学的生词（`今天学习生词`） | `jp-anki-today-new` |
| 从 jimaku 下载某集 Netflix 日文字幕 | `jimaku-subtitle` |
| 把短上下文脏活外包给本机模型（省 token） | `local-llm` |
| 主对话上下文吃紧 / 长流程只做调度与验收 | `context-offload` |
| 词义/读音/词性/近义拿不准，要先澄清语义 | `jmdict-lookup` |
| 整集一条命令跑完阶段 2–5 | 不用技能：`cli.py episode --tag … --input-tag 待标记` |

**默认口径**：写库技能一般默认演练、`--commit` 才真写；例外是 `core6000_example.py apply`
与 `today_new_words.py` 打标——按各自技能文档默认真写，用户点名「先演练」才演练。

**拿不准语义就先查词典**：一词多义取哪条、读音歧义、词性、近义辨析、方言/古语/拟声、
专有名 vs 普通词 → 先 `jmdict-lookup` 查 JMdict；查不到就明说不确定，不要补一个像样的意思。
