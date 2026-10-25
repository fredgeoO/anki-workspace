# ImmersionKit 10k–20k 批次：两个口径缺口（rank 字段借用 & 假名同音词）

> 状态：active ｜ 最后核实：2026-10-17 ｜ 日期：2026-10-17

## 结论

**1. `JitenAnimeRank` 会「借用」同读音汉字词的排名**（不是本批引入，是旧代码的一致行为）

字段按 Jiten 表的 `Form`（读音）查，不是按词表里选中的那一行查：

| 词表选中的写法 | 该行在 Jiten 表里的 rank | 词表范围 | 写进字段的值 | 来源 |
| --- | --- | --- | --- | --- |
| `とめる` | 10071 | 10000–20000 ✓ | **352** | 同读音汉字词 `止める`（Jiten rank 352） |
| `ばん` | 10162 | ✓ | 815 | `番` |
| `あずかる` | 10245 | ✓ | 1516 | `預かる` |
| `かわる` | （同表另一行） | ✓ | 266 | `変わる` |

* 实测：本批素材卡 **4,096 张里 193 张（4.7%）** 的字段落在 10000–20000 之外，最低 **9**（中途 1,155 张时是 69 张，比例一致）。
* `fetch` 阶段的日志同一行也显示「排名 352」，即挑选与写字段共用同一个按读音查的排名函数。
* **影响**：`jiten_reorder` 插件把 `cards.due` 设成 `int(JitenAnimeRank)`
  （见 [jiten-reorder 使用说明](../jiten-reorder-使用说明.md)），所以这 ~6% 的卡会排到整批最前面
  （due=352 早于 due=10000+）。同读音词确实高频，排前面说得通，但与「本批是 10000–20000」的口径不一致。

**可逆修法**：把这些卡的字段改回 `data/immersion/candidates_10k20k.tsv` 里那一行的 rank
（严格口径）；或原样保留。两种都只是一次 `updateNoteFields`。

**2. 58 个词属「考级词族已有」**（用户口径是「core6000 和考级**词族**都没有」）

清单：`data/immersion/redundant_kana_words.txt`（假名写法 `<TAB>` 已收录的汉字同音词 `<TAB>` 该词 rank）

```
とめる  止める  352        かわる  変わる  266
はなす  話す    256        わたしたち 私たち 254
やわらかい 柔らかい 4051   あずかる 預かる 1516
```

* 成因：词表生成器的「假名写法而正字已收」规则靠 `pipeline.build_variants()` 的变体索引，
  而形态分析器（Sudachi）把 `とめる` 与 `止める` 当**两个词条**，变体索引连不起来。
* 影响：本批会为这 58 个词各建 1 张素材卡（+ 1 张例句卡），其中 ~1.3% 的素材卡与已有词汇卡重复。
* 处理与否由用户定：保留（可用作读音训练）／删除这两类卡（删除不可逆，需显式确认）。

## 复现

```powershell
# 1) 已写卡片里字段超范围的数量（按本批 written_20261017-*.json 统计）
# 2) 58 个重复词（重算，用于核对 redundant_kana_words.txt）
& $PY -X utf8 -c "import sys; sys.path.insert(0,r'code/execution'); sys.path.insert(0,r'code/common'); import pipeline as P, textio; ..."
```

脚本化的口径在 `code/oneshot/immersion_jiten_wordlist.py`（选词）与
`code/execution/immersionkit.py`（`M.jiten_rank` 查字段）——两者用的是**不同**的查表方式，
本文件记录的就是这个差。
