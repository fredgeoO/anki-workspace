---
name: jp-anki-jiten-rank
description: anki-workspace 的**词汇注解任务 · Jiten 排名回填**：把带待办 tag（`需更新JAR`，旧名 `需要更新jitenrank的卡片`）的笔记，按笔记里的词查 Jiten 动漫词频表，写进 `JitenAnimeRank`（%06d 补零），并把这批笔记的待办 tag 摘掉。只写这一个字段：不碰 due/ivl/type 等调度列、不改词字段、不加别的 tag。默认演练，显式 `--commit` 才真写。当用户说「这些卡的 jitenrank 补上」「需更新JAR 的卡处理掉」「JitenAnimeRank 是空的」时加载本技能。**不含**清理、生成、激活、挖生词、配音、讲义——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语 Anki · Jiten 排名回填（按 tag 补 `JitenAnimeRank`）

本技能覆盖**一件事**：把打了待办 tag 的笔记，按笔记里的词查 Jiten 词频表，写成 `JitenAnimeRank`，写完摘掉待办 tag。

## 一、边界（不可越线）

| 允许 | 不允许 |
|---|---|
| 写笔记字段 `JitenAnimeRank` | 写 `due` / `ivl` / `factor` / `type` / `queue` / `reps` / `lapses` |
| 从命中的笔记上摘掉**这一个**待办 tag | 加别的 tag、改 deck、动词字段（`Word` / `VocabKanji` …） |
| 只读词表 CSV | 联网重下词表（除非用户明确要求更新榜单） |

- 排序不归本技能管：新卡位置由插件 `jiten_reorder` 按 `JitenAnimeRank` 写 `due`
  （见 [docs/jiten-reorder-使用说明.md](../../../docs/jiten-reorder-使用说明.md)）。本技能**只管把字段补齐**。
- 值一样的笔记跳过（幂等、不动 `mod`）：同一批卡跑第二遍必然输出「无需变更」。

## 二、命令（`$WS` / `$PY` 先设好）

```powershell
$WS = "<工作区根>"
$PY = "python"
$FE = "$WS\code\analysis\vocab_cover\freq_external.py"
```

### 2.1 演练（默认，不写库）

```powershell
& $PY -X utf8 $FE field --tag "需更新JAR" --remove-tag
```

### 2.2 真写（演练看过样例再跑这条）

```powershell
& $PY -X utf8 $FE field --tag "需更新JAR" --remove-tag --commit
```

### 2.3 tag 有两个名字，都要跑

待办 tag 可能叫新名 `需更新JAR`，也可能还是旧名 `需要更新jitenrank的卡片`
（库里两批卡可能并存）。**依次跑两条命令**，没命中的那条会打印「下没有命中笔记」，这是正常结果，不是报错：

```powershell
& $PY -X utf8 $FE field --tag "需更新JAR"                    --remove-tag --commit
& $PY -X utf8 $FE field --tag "需要更新jitenrank的卡片"       --remove-tag --commit
```

> `--tag` 只给 tag 名，**不要**自己加 `tag:` 前缀（脚本自己拼查询）。

### 2.4 只查有几张、不写也不摘

```powershell
& $PY -X utf8 $FE field --tag "需更新JAR"
```
（不带 `--remove-tag` 就只演练字段写入，tag 原样留着。）

## 三、输出怎么读（逐行）

| 输出行 | 含义 | 正常值 |
|---|---|---|
| `Jiten 词表 …：N 个归一化键` | 词表载入成功 | 约 26 万 |
| `tag … 下命中 N 个笔记` | 本批规模 | 0 也算成功 |
| `需要写入/更新：N 个（值已正确的跳过 M 个，无词字段跳过 K 个）` | N 是要改的，M+K 是不用改的 | K 应为 0；不为 0 说明卡里没有词字段，那些卡的 tag 会保留 |
| `词表未命中（写 999999）：N 个：…` | 词表里真没有的词，写 `999999`（队尾） | 列出词名，人工扫一眼是不是旧字体/错字 |
| `摘 tag：从 N 个笔记移除「…」` | 打算摘的数量 | = 命中数 − 无词字段数 |
| `已写入 X / Y，失败 Z` | 实际写入 | Z 必须为 0 |
| `已从 N 个笔记摘掉 tag「…」；该 tag 下还剩 0 个` | 摘完回查 | 剩 0 |

**判定完成**：`失败 0` + 摘完剩 `0 个`。再跑一次 2.1 应得到 `需要写入/更新：0 个` + `无需变更。`

## 四、机械规则（脚本已经做了，别在提示词里重算）

- 字段值 = `%06d` 补零（`3476` → `003476`）：浏览器按字段排序是**文本序**，补零后文本序＝数值序。
- 词表里查不到 → `999999`（文本序排最后）；`--no-rank` 可改这个值。
- 查表键：词字段 → NFKC → 去注音括号 → 片假名转平假名；Jiten 的 `Word`（汉字形）与
  `Form`（假名形）两把键都收。
- 旧字体回退：`剝げる` 这类旧字体查不到时，按 `KYUJITAI` 表（目前只有 `剝→剥`）换新字体再查一次，
  所以 `剝げる` 得 `052906`（= Jiten 的 `剥げる`），**不是** `999999`。新遇到旧字体就往那张表里加。
- 词字段按笔记类型取：`Japanese Vocabulary` → `Word`；`eggrolls-JLPT10k-v3.5` → `VocabKanji`；
  其它类型按 `Word` / `VocabKanji` / `Expression` / `Front` / `Vocabulary` / `単語` 取第一个非空。
- 改过查表逻辑就跑一次回归测试（不碰 Anki、不读 data/）：
  `& $PY code\tests\test_jiten_rank.py` → 末行应为 `✓ 全部通过`。

## 五、失败处理

| 现象 | 动作 |
|---|---|
| `AnkiConnect 错误 [updateNoteFields]: Close the affected editor` | 那张卡正在 Anki 编辑器里开着。**让用户关掉那个编辑窗口**，再重跑 2.2（幂等，已写好的会跳过） |
| `已写入 X / Y，失败 N` 里 N ≥ 1 + 上面那条 | 同上；这次**不会摘 tag**（有失败就整批不摘），关编辑器后重跑 2.2 |
| `找不到 data\freq\jiten_freq_Anime.csv` | 用户明确要更新榜单时才跑：`& $PY -X utf8 $FE download --media Anime`（加 `--force` 重下）。否则停手问用户 |
| `tag … 下没有命中笔记` | 正常：这批已经处理完，换另一个 tag 名继续 |
| `✗ 查询 tag … 失败` | Anki 没开或 AnkiConnect 不通：让用户开 Anki，重跑 |

**不要**为了绕过「编辑器开着」去改词表、改字段名、或用 `sqlite3` 直连库——工作区的 Anki 读写只走
`code/common/anki_api.py`。

## 六、收工汇报（给用户）

1. 两个 tag 名各命中多少、写了多少、失败多少；
2. 词表未命中的词（写 `999999` 的那几个）逐个列出；
3. 特殊处理（旧字体 `剝げる → 052906` 这类）说明了原因；
4. 排名分布：≤10000 几个、最大值/最小值（= 哪些词会最先被学到）；
5. tag 是否已摘干净（回查剩 0）。

## 七、与其它技能的边界

- 清理（阶段 1）→ `jp-anki-triage`；生成（阶段 2）→ `jp-anki-generate`；激活（阶段 3）→ `jp-anki-activate`；
  挖生词（阶段 4）→ `jp-anki-mine`；配音（阶段 5）→ `jp-anki-audio`；振假名读音 → `jp-anki-check-ruby`。
- 每日讲义 → `jp-anki-daily-lesson`；弱项 → `jp-anki-daily-weak`；core6000 补例句 → `jp-anki-core6000-example`。
- 本技能**只补 `JitenAnimeRank` 一个字段**，别的阶段要动卡请加载对应技能。
