# Bug / 事故记录

> 状态：active ｜ 最后核实：2026-11-13

**这是什么**：阶段四（`mine.py`）本地模型链路上**真正让流程跑不动**的事故复盘。
**为什么存在**：同类错会复发。每条写清「现象 → 根因 → 修法 → 回归测试在哪」，改代码前先查。
**什么时候读**：改 `mine.py` 的 patch / 校验逻辑，或本地模型产出对不上时。

防错体系（五道防线 / 提示词约束 / 重试留证）见 [local-llm-guardrails.md](local-llm-guardrails.md)。
文中提到的一次性脚本大多已归档到
[archive/experiments/20261020-oneshot/](../../archive/experiments/20261020-oneshot/)，别照着重跑。

## [2026-10-12] ① `merge-fix` 前缀回退误伤同批其他词条（数据损坏）—— 已修复

**状态：已修复**。`patch_outputs` 骨架现收敛在 `code/common/batchjob.py`（2026-11-02 issue #3），
`mine.py` / `pipeline.py` / `proper.py` 共用；占位判定常量 `MINE_PLACEHOLDER_REASON` 在 `mine.py`。
回归测试 `code/tests/test_mine_patch.py` 第 1–5 组 + `test_batchjob_patch.py`。

- **教训（现行操作仍要守）**：merge-fix 的前缀回退**只允许落在占位条目上**，且不能命中本批另一条记录的原词；
  一条 fix 只改一条记录，没落上任何记录要告警——这些判定都已在 batchjob 骨架里锁死，改收尾层时别绕开。

### 连带发现（设计约束，非 bug）

`build_payload` 的 `same_origin` 要求输入残差与输出词互为子串（或变体命中 + 子串），
`P.norm` 只做去标签/去标点、**不做假名归一**。所以占位词 `錆臭ぇ` 无法补成词典形
`錆臭い`（互不为子串）；此类候选只能保留表层形（卡面写口语形、词典形写进讲解）
或判 exclude。E01 的 `錆臭ぇ` 判 exclude（〜い→〜ぇ 缩略，语义透明，同批已收录「錆」）；
E02 的 `食わして`（＝`食わす` 的て形）按同一约束**保留表层形收录**，词典形与
「食う→食わす→食わして」的活用链写进 `a_note`。

## [2026-10-12] ② `conjugation_variants` 的サ変動詞盲区 —— 已修复

**状态：已修复**。`conjugation_variants()` 已上提到 `code/common/jp_text.py`（issue #10 B1），
`pipeline.py` 再导出；回归测试 `test_mine_patch.py` 第 8 组。

- **教训**：サ変動詞（`〜する`）要单独展开成 し/した/して… 系列并提前返回，按「尾假名＝词尾」
  推导会只产出废变体；影响面是 `pipeline.rebuild_known_index` 变体表与 `mine.build_payload` 例句定位。

## [2026-10-12] ③ `Index` 按笔记条数编号 → 整批 `addNotes` 被 Anki 查重拒绝 —— 已修复

**状态：已修复**。`code/execution/mine.py` `next_index()`（取模型内数字 Index 最大值 + 1），
`cmd_write` / `immersionkit` / `proper` 都走它。

- **教训**：`Index` 是 `Japanese Vocabulary` 的首字段，Anki 查重只看首字段；历史删过卡后
  `count()` 会小于最大 Index，**新卡序号一律取最大值 + 1，不许拿 count 当序号**。

## [2026-10-12] ④ 本地模型返回非字符串字段 → 整批 `gen` 崩掉 —— 已修复

**状态：已修复**。吸收层正本在 `code/common/llm_out.py`（`as_text`/`as_bool`/`dump_raw`），
`check_mine.py` 再导出，cards/pipeline/proper 共用；单组 try/except 在 `mine.py`。
回归测试 `test_llm_out.py` + `test_mine_patch.py` 第 9–12 组。

- **教训**：模型产出的字符串字段一律过 `as_text`、布尔一律过 `as_bool`（`bool("false")` 是 True）；
  单组请求要包异常，一组出意外只标「未判定」不中断整批；没判出来的原始回复必须 `dump_raw` 落盘。

## [2026-10-12] ⑤ `mine.py` 不写 `JitenAnimeRank` → 新卡该字段为空 —— 已修复

**状态：已修复**。`mine.py` `load_jiten_index()` / `jiten_rank()`，`cmd_write` 写入并纳入回读校验；
与 `freq_external.py field --all-notes` 同一份词表、同一套归一化。历史 23 张空值当时已回填。

- **教训**：给词汇卡建卡时 `JitenAnimeRank` 必须在入库时就写（命中 `%06d`，否则 `999999`），
  不能指望 `episode.py rank` 阶段事后补——手工跑 write 时那一步不会自动发生。

## [2026-11-13] ⑥ 卡片修正面板按单词查卡只查例句 deck → 写进了另一张卡 —— 已修复

**现象**：面板输入「張る」勾上 AINote + Sentence HTML 点「重新生成」，写的是例句卡
`1792114947226`（電線を引っ張る…）；用户要看的是同词的另一张 `Japanese Vocabulary` 卡
`1621392101953`（疲れて肩が張っています…，在 `0-日本语学习::0-词汇::1-高频日语单词 6000`），
它一个字段都没变。

**根因**：`cardLookup` 把 `Word:"…"` 限定在 `deck:"0-日本语学习::2-例句"`，代码注释还假设
「Sentence / Sentence HTML / AINote 只在例句卡上」——词汇卡（`Japanese Vocabulary`）也有
这三个字段。词汇卡被过滤掉后候选只剩一张，面板按「只有一张卡就直接执行」真写；而多卡
时又默认全选，再点一次会把每张都覆盖，等于两次都选错。

**修法**：查询不再限定 deck。`cardLookupCards`（纯函数）按 `Word` 精确相等 +
「Sentence / AINote / Sentence HTML 三个字段齐备」过滤，带上牌组名与笔记类型、例句 deck
优先排序；面板把每张候选的牌组与笔记类型都显示出来，**多张时默认一张都不勾**（没勾时
「重新生成」置灰），只写用户勾的那张。同时把三个目标 checkbox（单词音频 / Sentence HTML /
AINote）也改成**默认不勾**——先勾要重做的字段，才谈得上选卡，避免一点就把整张卡重做。

**回归测试**：`code/plugins/anki-workspace/test/logic.test.mjs` 的
`cardLookupCards keeps every writable card of the word…` 与 `…drops cards that cannot be
regenerated or are not the exact word`。

- **教训**：`Word:"…"` 是**全库**字段搜索，任何按词找卡的代码都必须自己决定「要不要限定
  deck」并写清理由；「只有一张卡就直接写库」这类自动动作，前提必须是「整库只有一张」。

## 遗留（未修，仅记录）

- **来源例句卡振假名可能读错**：E02 例句卡 noteId=1791783308448 的 `Sentence HTML` 把
  「飯食わして」的「食」标成 `<rt>た</rt>`，而该词是 **食わす（くわす）**。
  `mine.py write` 按规则**原样沿用来源卡的 Sentence HTML**（stage 4 不重做振假名），
  所以生词卡「食わして」的例句 HTML 也带着这个 `た`。修它等于改 stage 2 的振假名，
  需用户确认后再动（改来源卡字段，或走 check_ruby 闸门重跑该集）。
