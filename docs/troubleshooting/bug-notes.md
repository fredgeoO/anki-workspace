# Bug / 事故记录

> 状态：active ｜ 最后核实：2026-10-20

**这是什么**：阶段四（`mine.py`）本地模型链路上**真正让流程跑不动**的事故复盘。
**为什么存在**：同类错会复发。每条写清「现象 → 根因 → 修法 → 回归测试在哪」，改代码前先查。
**什么时候读**：改 `mine.py` 的 patch / 校验逻辑，或本地模型产出对不上时。

防错体系（五道防线 / 提示词约束 / 重试留证）见 [local-llm-guardrails.md](local-llm-guardrails.md)。
文中提到的一次性脚本大多已归档到
[archive/experiments/20261020-oneshot/](../../archive/experiments/20261020-oneshot/)，别照着重跑。

## [2026-10-12] ① `merge-fix` 前缀回退误伤同批其他词条（数据损坏）—— 已修复

**状态：已修复**。`code/execution/mine.py` `patch_outputs()`；回归测试
`code/tests/test_mine_patch.py` 第 1–5 组。

### 现象

对《七つの大罪》E01 跑 `mine.py merge-fix --file fix_output.json`，fix 文件只提交了 **1 条**
（word=`錆臭ぇ`，include=false），但脚本输出：

```
fix 文件 …\fix_output.json：并入 2 条（不合格 0 条）
```

「并入 2 条」即异常信号。事后检查 `output_01.json`：原本真实收录的 **`錆`** 条目
（include=true，本地模型正常判定）被整条替换成排除条目，文件出现两条 `錆臭ぇ`、
丢失 `錆` 卡，`write` 被「输出里重复出现」堵死。

### 根因

`patch_outputs(done)` 的前缀回退不检查记录是否为占位符：

```python
longer = sorted((k for k in done if k.startswith(key) and len(k) > len(key)), key=len)
if longer:
    v = done[longer[-1]]          # ← 前缀回退
```

前缀回退的本意是「fix 把残差补成词典形」（`ひきこ` → `ひきこもる`）。但本批真实词条
`錆` 恰好是 fix word `錆臭ぇ` 的前缀，于是 `錆` 被回退命中、整条覆盖。

触发条件：某批存在候选词 A，且同批失败占位词 B 满足 `B.startswith(A) and len(B) > len(A)`
（`剣`/`剣持…`、`錆`/`錆臭ぇ`）。

### 修法

1. 抽出常量 `MINE_PLACEHOLDER_REASON = '模型未能给出合格判定，留待人工'` + `is_placeholder(rec)`
   （`include=false` 且 reason 命中该文案）；`cmd_gen` 写占位条目也改用同一常量。
2. 前缀回退**只允许落在占位条目上**，且回退目标不能是本批另一条记录的原词（`exact` 集合）。
   精确命中仍可覆盖任何记录（人工复核修正就该覆盖）。
3. 完整性网：一条 fix 只改一条记录（命中第二条跳过并告警）；fix 一条都没落上会告警
   「没落到任何记录上」；每条并回打印明细「并回 X ← output_NN.json 第 N 条（精确/前缀匹配）」。
4. 同类加固 `judge_mine`：前缀回退排除「本组另一条候选的原词」，
   否则 `錆` 会拿到 `錆臭ぇ` 的答案。

### 连带发现（设计约束，非 bug）

`build_payload` 的 `same_origin` 要求输入残差与输出词互为子串（或变体命中 + 子串），
`P.norm` 只做去标签/去标点、**不做假名归一**。所以占位词 `錆臭ぇ` 无法补成词典形
`錆臭い`（互不为子串）；此类候选只能保留表层形（卡面写口语形、词典形写进讲解）
或判 exclude。E01 的 `錆臭ぇ` 判 exclude（〜い→〜ぇ 缩略，语义透明，同批已收录「錆」）；
E02 的 `食わして`（＝`食わす` 的て形）按同一约束**保留表层形收录**，词典形与
「食う→食わす→食わして」的活用链写进 `a_note`。

## [2026-10-12] ② `conjugation_variants` 的サ変動詞盲区 —— 已修复

**状态：已修复**。`code/execution/pipeline.py` `conjugation_variants()`；
回归测试第 8 组。

- **现象**：E01 `write` 报 `例句中找不到该词形 1 ['介抱する']`，而例句是「介抱していただいた…」。
- **根因**：函数按「尾假名＝词尾」推导，`介抱する` 的 stem 算成 `介抱す`，只产出
  `介抱すます` 之类废变体，**生成不出 `介抱し/介抱した/介抱して`**。
- **修法**：`w.endswith('する') and len(w) > 2` 时单独展开（`b`+し/した/して/しない/
  しなかった/します/しました/しよう/すれば/しろ/される/させる/せず/したい/しながら/
  している/していた/しておく/してしまう）并**提前返回**，不再产废变体。
- **影响面**：只被 `pipeline.rebuild_known_index`（变体表）与 `mine.build_payload`
  的例句定位使用；triage 不用它，既有口径（食べる→食べて、読む→読みます、高い→高く）
  已用第 8 组锁住。

## [2026-10-12] ③ `Index` 按笔记条数编号 → 整批 `addNotes` 被 Anki 查重拒绝 —— 已修复

**状态：已修复**。`code/execution/mine.py` 新增 `next_index()`，`cmd_write` 改用它。

- **现象**：E01 `write --commit` 整批被拒
  `AnkiConnect 错误 [addNotes]: ['cannot create note because it is a duplicate']`，
  而 6 条全新词条（闸门二已确认新牌组里没有同名卡、按 Word 全库查重也全无重复）一条都没进去。
- **根因**：`Index` 是笔记类型 `Japanese Vocabulary` 的**首字段**，Anki 自带的查重只看首字段；
  而 `cmd_write` 把 Index 算成 `AK.count('note:"…"') + i + 1`。历史上有过删卡，
  `count=6099` 但最大 Index 已是 `6100`（＝目标 deck 里已有的「剣」）→ 第一条新卡就撞车。
- **排查**：`code/oneshot/probe_mine_dup.py`（按 Word 查重 → 6 个词全无重复）、
  `code/oneshot/probe_mine_dup_index.py`（按首字段 Index 查 → 确认 6100 被占）。
- **修法**：`next_index(model)` 取**模型内数字 Index 最大值 + 1**（一定空闲），
  `cmd_write` 用它在写前打印「Index 序号：6101…6106」。全库只有 `mine.py` 写 Index
  （`pipeline`/`activate`/`mine_audio` 都不写），修复点唯一。

## [2026-10-12] ④ 本地模型返回非字符串字段 → 整批 `gen` 崩掉 —— 已修复

**状态：已修复**。`code/common/check_mine.py`（`as_text`/`as_bool`）、
`code/execution/mine.py`（`judge_mine`/`cmd_gen`/`fix_failed`）、
`code/execution/pipeline.py` `strip_html()`；回归测试第 9–12 组。

- **现象**：E02 `gen` 直接崩栈退出，已判好的条目全废：
  `File "…/check_mine.py", line 48, in check → AttributeError: 'int' object has no attribute 'strip'`。
- **根因**：本地模型把字符串字段返回成了数字（本次是 `translation`），
  而 `check_mine.check` 里到处是 `(c.get(key) or '').strip()` —— 非零数字绕过 `or ''` 直接 `.strip()`。
  更深一层：单条畸形数据会把**整批** gen 带崩（异常没人兜）。
- **修法**（三层，任何一层单独都不够）：
  1. `check_mine.as_text(v)`：非字符串一律当空串，由 `check()` 报「XX 字段类型不是字符串」的
     **不合格**（走重问 / failed.json 流程），绝不抛异常；`TEXT_KEYS` 逐个查类型。
  2. `check_mine.as_bool(v)`：`include` 被写成 `"false"`/`0` 时归一为 False
     （`bool("false")` 是 True，不归一就会把**明确排除**的条目写进库）。`judge_mine`/`merge-fix` 同用。
  3. `cmd_gen`/`fix_failed` 的单组请求+判定包在 `try/except` 里：一组出意外只把这组标成
     「未判定」（下一轮逐条重问，最终落 failed.json），不再中断整批；
     `judge_mine` 对每条候选也各自兜异常（报「判定异常：…」）。
  4. `pipeline.strip_html()` 对非字符串先转文本（`unescape(5)` 会崩，`norm` 也走这里）。
- **顺带补上留证**：`cmd_gen`/`fix_failed` 在「这一组没判出来」时把模型**原始回复**
  落盘到 `data/vocab/gen_mine/raw/batch_NN_MM.txt`（新增 `dump_raw()`）。
  此前不落盘，2026-10-12 产出被写坏时无法回头看成模型到底回了什么。

## [2026-10-12] ⑤ `mine.py` 不写 `JitenAnimeRank` → 新卡该字段为空 —— 已修复

**状态：已修复**（`mine.py` 新增 `load_jiten_index()` / `jiten_rank()`，`cmd_write` 写入该字段
并纳入回读校验）+ 一次性回填 `code/oneshot/fix_jiten_rank.py`。

- **现象**：三集新入库的 23 张生词卡 `JitenAnimeRank` 全空，而牌组里原有 99 张都有值
  （`020686` / `999999` 这种 `%06d` 文本）。用户口径是「不排位置，排序只认 JitenAnimeRank」，
  空值等于这些卡在按词频筛/排序时全部落到最后。
- **根因**：`cmd_write` 的 `new_note` 字段表里没有 `JitenAnimeRank`
  （只有 `Index/Word/Sentence/Sentence HTML/Transliteration/Meaning/Part of Speech/AINote/Sentence Translation`）；
  这个字段原本靠 `episode.py` 的 `rank` 阶段（`freq_external.py field --all-notes`）事后统一补，
  手工按技能文档跑 `mine.py write` 时那一步不会自动发生。
- **修法**：入库时按 `_norm.norm_word(primary_form(word))` 查
  `data/vocab_cover/study_plan_jiten_anime.json`（267,257 个归一化键，与
  `freq_external.py` **同一份表、同一套归一化**），命中写 `%06d`，否则 `999999`；
  写前打印「词表命中 N / M」，写后回读比对。
- **历史数据**：已回填 23 张（词表命中 19 张，4 张 `999999`：介抱する/愚弄する/食わして +
  另 1），回读 0 不一致；牌组 122 张现在全部有值。
- **排查工具**：`code/oneshot/probe_jiten_rank.py`（看有没有空值）、
  `code/oneshot/fix_jiten_rank.py`（单牌组回填，默认演练）。

## 遗留（未修，仅记录）

- **来源例句卡振假名可能读错**：E02 例句卡 noteId=1791783308448 的 `Sentence HTML` 把
  「飯食わして」的「食」标成 `<rt>た</rt>`，而该词是 **食わす（くわす）**。
  `mine.py write` 按规则**原样沿用来源卡的 Sentence HTML**（stage 4 不重做振假名），
  所以生词卡「食わして」的例句 HTML 也带着这个 `た`。修它等于改 stage 2 的振假名，
  需用户确认后再动（改来源卡字段，或走 check_ruby 闸门重跑该集）。
- `mine.py gen` 的原始响应从本次起才落盘；更早批次（E01）无 raw 可查。
