# Anki 库结构（写库前先看这一页）

> 状态：active ｜ 最后核实：2026-11-10

**这是什么**：真实收藏的牌组树、笔记类型与字段名、标签写法。写库、拼查询串、改字段前看这里，
能省一轮探查。**数量是某一时点的实测**（2026-10-26，含子牌组），会随学习变化；以 live 收藏为准。

| 想知道 | 怎么查（只读） |
|---|---|
| 牌组与数量 | `python code\common\anki_api.py check`，或 `exec deckNames` |
| 某查询命中多少 | `python code\common\anki_api.py count --query "tag:…"` |
| 某笔记的字段/标签 | `python code\common\anki_api.py notes --ids <noteId>` |
| 库里现有标签 | `python code\common\anki_api.py tags`（或 `AK.tags()`） |

## 牌组树

```
0-日本语学习                        39,820 张
├─ 0-词汇                           25,921
│  ├─ 0-素材生词                     9,212   model Japanese Vocabulary（从字幕挖的词）
│  ├─ 1-高频日语单词 6000            6,000   core6000
│  ├─ 2-考级词汇                    10,650   model eggrolls-JLPT10k-v3.5（N5–N1，级别在标签里）
│  ├─ 3-专有词汇                        59   model Japanese Proper Noun（只收集，不进队列）
│  ├─ 4-复习                            30
│  └─ 5-最佳停止词汇 / 6-最佳上限词汇（动画）  各 30   学习计划临时牌组（卡借自别处）
├─ 1-语法                            3,160   N5–N1，每级 1-解释 + 2-例句
└─ 2-例句                           10,739   ★ model Basic：流水线主战场
```

牌组名常量在 `code/common/jp_decks.py`；**别自己拼子 deck 路径**，用那里的解析。

## 笔记类型与关键字段

字段名**带空格，拼错就是静默写空**，所以一律用常量/既有代码里的写法。

- **`2-例句`（Basic）**：`Sentence` `Word` `Sentence HTML` `AINote` `Image` `Sentence Audio` `Source` `URL`
- **词汇（Japanese Vocabulary）**：`Word` `Sentence` `Sentence HTML` `Transliteration` `Meaning`
  `Part of Speech` `AINote` `JitenAnimeRank` `JitenGlobalRank` `Word Audio` `Sentence Audio` `Index`
- **考级（eggrolls）**：词形是 `VocabKanji`，读音 `VocabFurigana`，级别由标签还原；
  同样带 `JitenAnimeRank` / `JitenGlobalRank`（注解，不参与排序）

`0-素材生词` 与 `1-高频日语单词 6000` 共用 `Japanese Vocabulary` 笔记类型与同一模板；
区别只在词源。`3-专有词汇` 用独立的 `Japanese Proper Noun` 类型。

## 标签口径

- 例句卡集标签的标准写法：`动画::<作品>::<季>::第NN集`。历史导入还有 `动画::平家物语::第01集`
  （无季）、整部一个 `动画::<作品>` 等写法 → **拼查询串前先查库里现有标签**，别猜。
- `待标记`：导入时挂的，流水线末尾换成正式集标签。
- `复习::<名称>`：`jp-anki-subtitle-tag` 打的字幕复习标签。
- `需更新JAR`：`jp-anki-jiten-rank` 的待办；处理完摘掉。
- `今天学习生词`：`jp-anki-today-new` 每天全量替换；`jp-anki-daily-lesson` 只认这个 tag。
- `leech`：Anki 自动挂的难卡标记，`jp-anki-leech` 处理。

## 写库时的边界

- 只写被点名的字段；不批量重写既有讲解，不动笔记模板、牌组选项、学习调度。
- 调度列 `due / ivl / factor / type / queue / reps / lapses` 脚本一律不写。新卡（`type == 0`）的
  `due` 由 Anki 插件 `jiten_reorder` 负责（打开自动重排 / 工具菜单手动），见
  [jiten-reorder-使用说明](jiten-reorder-使用说明.md)。
- 写前备份、写后 `AK.verify_note_fields(...)` 回读；细节走 `code/common/writeback.py`。
