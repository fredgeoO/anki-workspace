---
name: jp-anki-mine
description: anki-workspace 的**阶段 4 · 素材生词**：从例句里挖出 core6000/考级词汇都没有的词，建第三个词汇牌组 `0-日本语学习::0-词汇::0-素材生词`。五个子命令（与 pipeline.py 的 split/gen/write 同构）：scan → split → gen → write → verify。判定由本地模型负责语义（「是不是一个词、词典形是什么」），脚本负责确定性部分（切词边界、查重、校验、写库）。当用户说「挖这一集的生词」「例句里出现的新词要建卡」「素材生词牌组要补完」时加载本技能。**不含**清理、生成、激活、配音——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语 Anki 阶段 4 · 素材生词（mine）

本技能覆盖**一件事**：从例句里挖素材生词，建第三个词汇牌组。

## 一、收录判据（用户定义）

**只收录「不存在于已有两组词汇牌组中的词」**：
- `0-词汇::2-考级词汇`（10,609 张，字段 `VocabKanji`）
- `0-词汇::1-高频日语单词 6000`（6,000 张，字段 `Word`）
- = 11,728 个词典形 / 229,007 个可识别写法。

**词形比对口径**：去掉 `〜`、NFKC 统一全半角、再去掉空白后逐字比对；活用形（食べた→食べる）、平假名↔片假名变体、活用词干都算**同一个词**。因此 `漕い` 会因 `漕ぐ`（在 jp-core 里）被判为「已存在」。

词汇来源是 `0-日本语学习::2-例句` 里**最终保留**的字幕例句（弃用卡不算）。

## 二、五个子命令

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$EXE = "$WS\code\execution"
```

### 4.1 只读扫描（出报告 + plan_mine.json，不写库）

```powershell
& $PY "$EXE\mine.py" scan
& $PY "$EXE\mine.py" scan --tag "动画::<作品名>::<季>::第NN集" --limit 200
```

产出：`data/vocab/mine_candidates.json`（机器读）+ `mine_report.md`（人看）。

### 4.2 切批 + 本地模型判定（2026-10-11 起不派子代理；本地模型读不了文件，规范压进脚本里的 `MINE_INSTRUCTION`）

```powershell
& $PY "$EXE\mine.py" split --batches 8
& $PY "$EXE\mine.py" gen
```

产出：`data/vocab/gen_mine/output_NN.json`。

### 4.3 入库（默认演练；--commit 才真写）

```powershell
& $PY "$EXE\mine.py" write
& $PY "$EXE\mine.py" write --commit
```

`write` 会自己先校验一遍（含"是否真的不在已有牌组里"），校验通过的载荷存成 `verified.json`；紧接着的 `--commit` 直接复用，不再校验第二遍。

写入的每条 note 会打：`素材生词::<日期>`（溯源）＋ `素材生词::<来源>`（如有）；**当场写好 `Index`**（首字段，必须取「已有最大序号 + 1」，否则 Anki 按首字段查重会整批拒绝）与 `JitenAnimeRank`（排序口径，`%06d`；词表里没有的写 `999999`）。

新卡位置是随机的——**不用管**（只看 `JitenAnimeRank`）。

### 4.4 只看校验报告、先不入库

```powershell
& $PY "$EXE\mine.py" verify
```

## 三、候选来源与判定

**候选有两个来源**（2026-10-11 起）：
1. **残差法**：脚本用已知词表最长匹配后的剩余片段。结构性盲区：最长匹配会把多字词吃掉一半（`王女`→`王`+`女`、`魔道具`→`魔`+`道具`），剩下的单字残差被丢掉，这类词**扫不出来**。
2. **例句卡的 `Word` 字段**（人工指定的重点词）→ 直接补成候选。实测第 01 集 53 张里 29 张有 Word，其中 20 个词是残差法一个都没扫出来的。词在例句里定位不到的（`化す`）会在 scan 时列出并跳过。`--no-word-field` 可关掉这条通路。

**判定是三级级联**（与阶段二一致）：本地模型 `gen` → 没判出来的写进 `data/vocab/gen_mine/failed.json` → `gen --fix-failed` 逐条再试 → 仍剩的交给强模型出 `fix_output.json` → `merge-fix` 并回。**同一条候选判不出来时按"不收"处理**（不建卡），绝不为了凑数硬收。

## 四、收工汇报

- 候选数 → 入库张数（`include=false` 多少）；
- `word` 列人工修正了哪几条（模型容易把残差原样交回来，要的是词典形——这是纯语义判断，脚本查不出）；
- `JitenAnimeRank` 词表命中多少（其余 `999999`）；
- 落盘路径（`data/vocab/mine_candidates.json`、`mine_report.md`、`data/vocab/gen_mine/output_*.json`）。

---

**本技能只做挖生词。** 清理（阶段 1）→ `jp-anki-triage`；生成（阶段 2）→ `jp-anki-generate`；激活（阶段 3）→ `jp-anki-activate`；配音（阶段 5）→ `jp-anki-audio`。
