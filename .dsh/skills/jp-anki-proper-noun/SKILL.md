---
name: jp-anki-proper-noun
description: anki-workspace 的**专有名词收集**（`0-日本语学习::0-词汇::3-专有词汇`）。两层：① 原子能力 `proper_extract.py` —— 一段日文文字 + 背景 → 专有名词清单（人名/地名/组织/概念/技能/种族/称号/作品名，可多类别），不碰 Anki；② 管线 `proper.py` —— 扫一集字幕 → 候选 → 本地模型写成卡片内容 → 校验 → 写入专用笔记类型 `Japanese Proper Noun`（正面只有词形，背面读音 + 读法音频 + 中文意思 + 日语介绍句 + 出处与背景）。卡片**只收集，不进学习队列**（不 suspend、不改牌组选项，何时停学由用户控制）。当用户说「这集的名词收一下」「把专有名词建成卡」「从这段文字里抽专有名词」时加载本技能。**不含**生词挖掘（`jp-anki-mine`）、清理、生成例句卡、配音（`jp-anki-audio`）。仅适用于 anki-workspace。
---

# 专有名词收集（proper noun collection）

本技能只做一件事：**把专有名词收集成卡片**。它**不改**生词挖掘的判据 ——
`jp-anki-mine` 里「专有名词 → `include=false`」仍然正确，那边挖的是要背的词；
这边收的是「认得就行」的名字与设定。

## 一、原子能力（先能单跑，再谈字幕）

`code/tools/proper_extract.py`：**输入一段文字 + 背景，输出专名清单**。不读 Anki、不写库，
所以出问题能拿一句话复现。

```powershell
$WS = "<工作区根>"
$PY = "python"

& $PY "$WS\code\tools\proper_extract.py" --text "気持ちを届けるのはシルフさんたちのお仕事" `
    --background "作品=水星领航员 第01集" --json
& $PY "$WS\code\tools\proper_extract.py" --file temp\scene.txt --background "平家物语 第02集"
Get-Content temp\cue.txt | & $PY "$WS\code\tools\proper_extract.py" --stdin --background "…" --json
& $PY "$WS\code\tools\proper_extract.py" --text "…" --no-model      # 只跑确定性预扫
```

输出每条：`word`（必须在原文里逐字出现）/ `categories`（1..n）/ `reading`（平假名）/
`gloss` / `why` / `evidence`。

**两层召回**：Sudachi `固有名詞` + 片假名长串只当**提示**（`メリオダス`/`シルフ` 这类
会被 Sudachi 判成普通名词）；判定的主力是本地模型读「文字 + 背景」。所有输出都过同一道机械闸门
（原文子串 + 类别枚举 + 读音纯假名），所以模型改写词形/幻觉词会当场被拦。

## 二、每集收集（一集一条命令）

```powershell
$EXE = "$WS\code\execution"

& $PY "$WS\code\cli.py" doctor                     # 必须 0
& $PY "$EXE\proper.py" model --check                # 笔记类型是否就绪（卡面在代码里）
& $PY "$EXE\proper.py" model --commit               # 缺了就建（幂等；已存在只校验不覆盖）

# 1) 只读：字幕 → 候选（每集或一次多集）
& $PY "$EXE\proper.py" scan "subtitles\ARIA The ANIMATION\Aria The Animation 04.jp.srt" --work 水星领航员
& $PY "$EXE\proper.py" scan <01.srt> <02.srt> <03.srt> <04.srt> --work 水星领航员 --window 8

# 2) 切批 + 本地模型写成卡片内容
& $PY "$EXE\proper.py" split --batches 4
& $PY "$EXE\proper.py" gen

# 3) 写库前唯一一道校验（不过就不许写）
& $PY "$EXE\proper.py" verify

# 4) 入库（默认演练；--commit 真写）
& $PY "$EXE\proper.py" write
& $PY "$EXE\proper.py" write --commit

# 5) 读法音频（单独一步：edge-TTS 读 Reading 假名，不读词形）
& $PY "$EXE\proper.py" audio --commit
```

- `scan` 产出 `data/vocab/proper/<作品>_<集>/candidates.json` + `report.md`；
  `latest.json` 指向最新一次，其余子命令默认操作它（`--run <目录名>` 切换）。
- 出处 `--work` 必须与库里 `动画::<作品>` 的**作品段**一致（例：`水星领航员`）。
  对不上时 report 会列出现有标签供选。
- 背景信息：`--work` + 集数 + `data/vocab/proper_works.json` 里的一句话作品背景（可选）。
- 判据：`core6000` + `考级词汇` + **`素材生词`** 里已有的**不收**（`--include-known` 可关掉）。
  被跳过的会列在 report 的「可强收」清单里 —— `シングル`/`プリマ` 这类称号常落这里。
  名字后面的敬称会去掉（`晃さん`→`晃`、`アイちゃん`→`アイ`）；`アリア社長` 这种职务不动。
- 失败级联与 `mine.py` 同构：`gen` 判不出的进 `gen/failed.json` → `gen --fix-failed`
  逐条重问 → 仍剩的让强模型出 `fix_output.json` → `merge-fix --file …`。

## 三、手动补一张（不在字幕里的）

```powershell
& $PY "$EXE\proper.py" add --word メリオダス --reading めりおだす `
    --source 亚瑟王传说 --text "アーサー王伝説の騎士メリオダス。" --commit
```

`--source` 是**出处标签**（作品名 / 亚瑟王传说 / 现实 / 史实）。同名词不同出处 = 不同的卡，
重复跑会报「已存在」。

## 四、卡片与标签

笔记类型 **`Japanese Proper Noun`**（字段顺序即卡面顺序，**首字段 `Index` 是 Anki 的查重字段**，
所以同名不同作品能共存）：

| 字段 | 内容 |
|---|---|
| `Index` | 全局唯一序号（最大+1；卡面不显示） |
| `Word` | 专名本体（`メリオダス` / `シルフ`） |
| `Reading` | 平假名读音（`めりおだす`） |
| `Meaning` | 一句话中文意思 |
| `Categories` | 卡面显示的类别（`人名 / 称号`） |
| `Intro` | **日语介绍句**（带 `ruby`，由 `ruby_engine` 确定性渲染） |
| `Intro Translation` | 介绍句中文翻译 |
| `AINote` | 中文讲解：`词条` + `出处与背景` |
| `Source` | `出自「作品」第NN集｜原句：…`（追溯用，卡背底部小字） |
| `Word Audio` | `[sound:proper-<词>-<hash>.mp3]`（edge-TTS 读 `Reading`） |

正面**只有 `Word`**（否则读音/意思被剧透）；背面才给读音、自动发音、类别、意思、介绍句、讲解、出处。

**标签：类别扁平、出处继承动画作品标签**（一个专名可能同时是「人名」和「称号」）：

```
专有名词                         必有
人名 / 称号 / 种族 / …            1..n（与 Categories 字段同一份数据，扁平）
动画::水星领航员                 出处：继承库里现有的动画作品标签，**两层，不带季度/集数**
专有名词-批次-<YYYYMMDD>          溯源与回滚
```

`--work 水星领航员` 会自动解析成 `动画::水星领航员`（库里存在该动画标签时）；
非动画出处（`--source 亚瑟王传说`）就是裸标签；也可以直接写 `--source "动画::七大罪"`。

「关联/原型」（`related`，例：亚瑟王传说）**不进标签**，写进 `AINote` 的「关联：」段 ——
实测模型会把同作品的其他角色也塞进 related（`晃`→`蓝华`），当标签用就是噪声。

`Reading` 以 `Intro` 的振假名为准：ruby 是 `ruby_engine` 渲的，模型给的读音常错
（`藍華` 读成 らんか、`火の番人` 读成 かんじん）。脚本会把整词在 ruby 里的读音拼出来覆盖 `Reading`，
TTS 也读这个字段。

## 五、铁律

1. **只收集，不进学习队列**：本技能不写 `due`/`type`/`queue`、**不 suspend、不改牌组选项**。
   `write` 收工会打印该牌组当前 `new/day`，要停学由用户自己在 Anki 里决定
   （牌组选项 → 新卡/天 = 0，或浏览器全选挂起）。
2. **不改 `jp-anki-mine` 的判据/提示词**；不改现有三个笔记类型。
3. **不回溯旧例句卡**：提取源是字幕文件（按集手动跑），不是历史卡片。
4. **不进 `episode.py` / `cli.py episode` 默认链路**，也不进每日讲义（`today_new.STUDY_UNITS`）。
5. 卡面以代码为准：模板/CSS 在 `proper.py` 的 `MODEL_SPEC` 常量里，
   `model --check` 报漂移时默认**只报告不覆盖**，要覆盖必须 `--force-templates`。
6. 同一件事只校验一次：`verify` 是唯一校验点，`write` 复用 `verified.json`。
7. **重跑幂等**：`write` 在写库那一刻会再查一遍「目标牌组里有没有同 `(词形, 出处标签)`」，
   已存在就跳过 —— 重跑 `write --commit` 不会重复建卡；`audio` 同样跳过已有音频。
8. **不写批次/日期标签**（用户口径：没必要）：回滚按「牌组 + 出处标签」或浏览器 `Added` 列。
9. 文本 I/O 一律 `import textio`；Anki 一律走 `anki_api.py`。

## 六、收工汇报（固定四项）

- 候选数 → 入库张数（`include=false` 多少；词表拦下多少、`already` 跳过多少）；
- 类别分布与**人工该看的点**（`report.md` 的「可强收」清单、`concept` 类抽检）；
- 音频：配了几张、几张因 `Reading` 不合格跳过；
- 落盘路径（`data/vocab/proper/<slug>/candidates.json`、`report.md`、`gen/verified.json`）
  与回滚范围（`deck:"…3-专有词汇" tag:"动画::<作品>"`）。

---

**本技能只做专有名词收集。** 生词 → `jp-anki-mine`；清理 → `jp-anki-triage`；
例句卡生成 → `jp-anki-generate`；生词配音 → `jp-anki-audio`。
