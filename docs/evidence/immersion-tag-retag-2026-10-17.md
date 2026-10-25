# 沉浸式::anime/drama 标签 → 中文名标签

> 状态：active ｜ 最后核实：2026-10-17 ｜ 日期：2026-10-17

**日期**：2026-10-17
**执行**：`code/oneshot/retag_immersion.py --commit`
**结果**：6556 个笔记改名，88 个旧标签清零，88 个新标签建立。回读 0 错误。

## 用户口径

> 「找到 `沉浸式::anime::xxx` 等有关的 tag，在网上找到对应的中文译名，把他们转变成之前的 tag 的格式。
> 可忽略集数的标记，可标记为 `动画::中文动画名称` 的格式。」

落成两条规则：

| 旧标签 | 新标签 | 数量 |
| --- | --- | --- |
| `沉浸式::anime::<英文 slug>` | `动画::<中文动画名>` | 80 个标签 / 6545 张 |
| `沉浸式::drama::<英文 slug>` | `日剧::<中文剧名>` | 8 个标签 / 11 张 |

* **整部，不带季/集** —— 这批卡是 ImmersionKit 按作品混着导入的，卡片字段里**没有集数信息**
  （只有 `Source` 里的 example id，形如 `ImmersionKit · <slug> · anime · anime_<slug>_<id>`），
  按集打会大面积出错。用户明确「可忽略集数的标记」。
* 旧标签**摘掉**（改名，不是并列保留）。
* 库中原本就有 `动画::七大罪::第一季::第01集`、`动画::水星领航员::第一季::第01集` 这类
  已有的带集数命名空间 —— 正是用户说的「之前的 tag 的格式」。本次不动它们。

## 为什么这个改名是安全的

盘点结论（`tag_shape.ps1`）：6545 张 anime 笔记里，**恰好挂 1 个** `沉浸式::anime::*` 子标签的
有 6545 张（`NOTES_WITH_1_ANIME_TAGS == DISTINCT_NOTES`）。没有一条挂两个，所以
AnkiConnect 的 `replaceTags`（摘旧+加新原子完成）不会误伤。脚本另加兜底：若两旧标签撞同一笔记就
`SystemExit` 而不是硬改。

## 映射表

`slug_map.yaml` —— 一行一个 `slug => 中文名`，段头 `anime:` / `drama:`。

* 88 个名字**全部在网上检索核实**（Bangumi `name_cn`、中文维基、百度百科、豆瓣、萌娘百科、Plex 简体页），
  由 5 个检索子代理分批核对，不是凭记忆。
* **取名口径**：优先**大陆网络/平台最通用**的名字，而不是 Bangumi 的正式条目名。
  例：`mononoke` 取《怪化猫》（豆瓣/维基简中/B站）而非 Bangumi 正式名《物怪》。
* 官方无通行中译的保留英文原名：`AngelBeats!`、`CLANNADAfterStory`、`GIRLSBANDCRY`、`NEWGAME!`。

### 检索纠正的 10 处初稿错误

| slug | 初稿（错） | 核实后 |
| --- | --- | --- |
| the_tunnel_to_summer__the_exit_of_goodbyes | 夏日大作战 | 通往夏天的隧道，再见的出口 |
| bunny_drop | 兔子扎堆 | 白兔糖 |
| fermat_kitchen | 费马厨房 | 费马的料理 |
| kokoro_connect | 心连情结 | 恋爱随意链接 |
| good_morning_call | 早安电话 | 爱情起床号 |
| i_am_mita__your_housekeeper | 我是三田，你的管家 | 家政妇三田 |
| i_m_taking_the_day_off | 我明天休息 | 今天不上班 |
| weakest_beast | 最强的野兽 | 无法成为野兽的我们 |
| the_tunnel_to_summer…（标点） | — | 官方名带逗号，保留 |
| （备选留档） | — | 命运之夜无限剑制 / Fate/stay night [UBW]；命运之夜前传 / Fate/Zero |

「夏日大作战」是细田守的 Summer Wars，与本片无关；「早安电话」「我明天休息」「我是三田，你的管家」
都是英文标题的字面直译，中文圈不用。

## ⚠ 两个踩过的坑（会静默错库，务必记住）

1. **标签名里不能有空格**。Anki 的标签按空格切分：
   `动画::命运之夜 无限剑制` 落到库里会变成 `动画::命运之夜` **+** `无限剑制` 两个标签
   （空间被吞、多出一个裸标签）。88 条里有 10 条名字带空格，已在 `slug_map.yaml` 里
   全部去掉空白。`retag_immersion.py` 的 `normalize()` + 硬断言负责兜底。
2. **`anki_api.replace_tags` 曾经是坏的**（2026-10-17 已修）。原实现传驼峰
   `tagToReplace` / `replaceWithTag`，而 AnkiConnect 要的是下划线
   `tag_to_replace` / `replace_with_tag`，导致每次调用都报
   `replaceTags() missing 2 required positional arguments`。
   本脚本改走 `AK.call('replaceTags', ..., tag_to_replace=..., replace_with_tag=...)`。
   `code/common/anki_api.py:589` 的包装也已一并修正（该函数当时全库无其他调用者，属死代码）。

另外：PowerShell 直连 AnkiConnect 时，中文查询串必须
`[Text.Encoding]::UTF8.GetBytes($json)` 当 body，否则字符丢失、查询恒返回 0。

## 验证（独立于写入脚本）

```
沉浸式::anime::*  残留 = 0
沉浸式::drama::*  残留 = 0
动画::           102 个标签（新 80 + 原有 22 个带集/其他）
日剧::             8 个标签
标签总数          248   （改动前 252：−92 个孤儿旧标签 + 88 个新标签）
```

旧标签名会**留在 Anki 的标签清单里当孤儿**（0 个笔记，但名字仍注册），
所以最后跑了 AnkiConnect `clearUnusedTags`：一次清掉 92 个孤儿（+1 个探针留下的 TEST 标签）。
这已经是全库仅有的未使用标签 —— 清之前逐一确认过个个 0 笔记，没有误删存量标签。

新标签张数与原分布逐一对应（例：全职猎人 663、小魔女学园 391、妖精的尾巴 313）。

## 回退

`retag_state.json` 记了 noteId → (旧标签, 新标签) 全量映射：

```
python code/oneshot/retag_immersion.py --revert --commit
```

## 相关文件

* `code/oneshot/retag_immersion.py` —— 演练/写库/回退三合一（默认演练）
* `data/evidence/immersion_retag/slug_map.yaml` —— 88 条映射表（改名字只需改这里）
* `data/evidence/immersion_retag/normalize_map.py` —— 去空白归一器
* `data/evidence/immersion_retag/retag_state.json` —— 回退凭据
* `data/evidence/immersion_retag/tag_inventory.ps1` / `tag_shape.ps1` —— 盘点脚本

## 未纳入本次范围

`素材生词::IK-<slug>`（约 60 个 tag）当时不在其中 —— 用户问的是 `沉浸式::anime` 等。
**当日稍后用户追加要求，已单独收敛，见下一节。**

另外 `沉浸式::anime` 这个**裸父标签实际没有笔记**（`findNotes` 返回 0），
用通配 `tag:沉浸式::anime::*` 直连 AnkiConnect 会被当成无效查询而静默返回全库，
算出来的「每个 tag 的笔记数」全是错的 —— PowerShell 盘点必须用**精确 tag**逐个查。

---

# 追加：`素材生词::*` 子标签收敛为裸 `素材生词`

**日期**：2026-10-17（同日追加）
**执行**：`code/oneshot/flatten_pool_tag.py --commit`
**用户口径**：
> 「素材生词 不需要子 tag，可以删除 保持 素材生词 这个tag就行」

## 结果

| | 操作前 | 操作后 |
| --- | --- | --- |
| 带 `素材生词`（裸）的笔记 | **0** | 2031 |
| 带 `素材生词::*` 的笔记 | 2031 | **0** |
| 子标签名字 | 98 | **0** |
| 标签总数 | 250 | 151 |

笔记总数 26300 未变；回读「应补未补 0 / 应摘未摘 0」；逐笔记核对 2031 张全部达标。

## ⚠ 关键：必须「先补后删」

全库**没有任何笔记**独立挂着裸 `素材生词`（`notes_info` 里一条都看不到）——
2031 张卡全都只挂子标签。**直接删子标签 = 2031 张卡变成无标签卡**，
而且 `素材生词` 这个名字会变成孤儿。

探针实测（笔记 `1790891591425`）：`addTags('素材生词')` 之后两个标签**并存**，
`notes_info` 里能同时看到 `['素材生词', '素材生词::Aria_The_Animation_01']` ——
说明 Anki 允许父子标签共存，所以「先补父、再摘子」是安全的。
摘掉子标签后 `findNotes('tag:素材生词')` 仍命中，标签名依然有效。

## 子标签构成（98 个名字 / 4026 个「笔记×子标签」对）

* `IK-<英文slug>`（约 80 个）—— 与上一步 anime 改名同源
* `<日期>`（`20261011`…`20261016`，5 个）—— 导入批次号
* `Aria_The_Animation_*`、`Nanatsu_no_Taizai`、`Tensei_Oujo_to_Tensai_Re`、
  `平家物語_S01E01_…` —— 早期手工来源名

每个笔记挂 1~2 个：36 张挂 1 个，1995 张挂 2 个（通常是「日期批次 + IK slug」两个维度）。

## 踩到的坑：Anki 编辑器开着会拦住一切写入

第一次 `--commit` 在补到 ~1000 张时被 AnkiConnect 拒绝：

```
AnkiConnect 错误 [addTags]: Close the affected editor before this API write, even if its content is saved.
```

原因是前面的探针调用 `guiSelectedNotes` 时 Anki 的 Browser/编辑器窗口开着。
清掉编辑器后重跑，脚本**幂等自愈**（重新扫描 → 只补还缺的 1032 张）。
顺带一提：当时用 `guiUndo` 关编辑器，它把上一批 200 张的 addTags 撤销了，
正是靠重扫才发现并补回来的 —— 这类脚本一律要按「重新扫描」而不是「从上一次断点续跑」写。

后续凡是要写库，先确认 Anki 没有开着的编辑器/Browser 窗口。

## 收尾

`clearUnusedTags` 清掉 98 个孤儿子标签名 + 1 个探针残留名（`__probe_close__`）。
清之前逐一确认过个个 0 笔记；清之后全库 **0 个僵尸标签**（151 个标签全部至少挂在 1 张笔记上）。

## 回退

`data/evidence/immersion_retag/pool_tag_flatten_state.json` 存了 2031 张笔记的**原始标签快照**：

```
python code/oneshot/flatten_pool_tag.py --revert --commit
```

还原是逐笔记恢复快照（连裸 `素材生词` 也一并还原），不是简单的逆操作。
