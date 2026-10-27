---
name: jp-anki-leech
description: anki-workspace 的**难卡（leech）修复**：把 `tag:leech` 的卡按 Anki 官方四种病因（信息过载 / 措辞模糊 / 缺乏理解 / 记忆干扰，尤其是数词/助数词、日期、月份这类成组干扰）诊断，只改写卡背白名单字段（`AINote` / `Meaning` / `VocabDefSC` / `VocabPlus` / `Sentence Translation` / `SentDefSC1-4`），把答案收敛到一个可验证的考点，并按需加记忆钩子。默认只出计划、`--commit` 才写；写前备份、写后回读，成功后默认摘 `leech` 标签。不碰 due/ivl 等调度列、不 suspend/unsuspend、不建卡/删卡/改模板；拆分与暂停只给建议，由用户决定。当用户说「处理 leech 卡片」「这张卡总记不住」「反复答错的卡」「数词/助数词总混」「难卡润色」「给难卡加记忆钩子」时加载本技能。**不含**清理、生成、激活、挖生词、配音、每日讲义——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语 Anki · 难卡（leech）修复：诊断 → 改写卡背 → 记忆钩子

本技能覆盖**一件事**：把 `tag:leech` 的卡按病因诊断，改写卡背里**能改的**字段，
让下一轮复习只考一个明确、可验证的点。它不是“再讲一遍”，也不是“重置进度”。

## 一、边界（先读）

| 允许 | 不允许 |
|---|---|
| 读 `tag:leech` / 指定 noteId / `prop:lapses>=8` | 写 `due` / `ivl` / `factor` / `type` / `queue` / `reps` / `lapses` |
| 写白名单字段（见 §6） | 写 `Sentence` / `Word` / 读音 / 词性 / 音频 / 图片 / `Sentence HTML` |
| 写成功后摘掉 `leech` 标签（`--keep-leech` 保留） | 建卡、删卡、改笔记模板、改牌组选项、改 deck |
| 写前备份到 `data/leech/backup_*.json`，写后回读 | suspend / unsuspend / forget / 重置进度 |
| 在计划里写拆分/暂停**建议** | 自动执行拆分、自动暂停、自动改到期 |

- **不替用户做学习决策**：`understanding` 不硬改；`interference` 只建议暂停哪张；
  `overload` 只出拆分方案。学哪些、停哪些、拆不拆，都由用户拍板。
- **默认演练**：`apply` 不加 `--commit` 只打印 diff。覆盖已有 `AINote` 属于内容改写
  （AGENTS §3.9），**必须先把演练摘要给用户看，得到明确同意后才 commit**。
- **默认摘 `leech`**：这是本技能唯一会写的 tag；摘掉不等于“学会了”，只是把这张卡
  移出待处理队列。Anki 在再次达到阈值时会重新打上；`prop:lapses>=8` 也能找回。

### 为什么不能“重写问题”

正面由模板固定，字段改不了模板：

- `Basic`（`2-例句`）：正面只有音频 + 图片；
- `Japanese Vocabulary`：正面只有音频 + 词性；
- `eggrolls-JLPT10k-v3.5`：正面是词形 + 最多 4 条例句。

所以官方说的“重写问题”在本工作区落地为：**把卡背收敛到一个考点**，并让答案可验证。
不要去动 `Sentence` / `Word` / 模板来“改题面”——那些不在本技能边界内。

## 二、官方诊断 → 本工作区落地

| 病因 | 官方判据 | 本库证据 | 处方 | 写哪里 |
|---|---|---|---|---|
| **信息过载** | 一张卡同时问定义、机制、例子，背面要一整段 | `AINote` 可见 > 400 字；义项 ≥ 4；eggrolls 4 条例句同屏；句长 > 60 | `trim`：只留一个考点；义项按场景编号；其余进 `split` 建议（**不建卡**） | `AINote` / `VocabDefSC` |
| **措辞模糊** | “为什么重要”“如何运作”这类没有明确指向的假问题 | 答案列了 3+ 义项却没有语境指向；核心词汇堆 5+ 条；`Meaning` 是词典义项直贴 | `reword`：第一行写清“本卡考点”，用句子语境锁定一个义项；查 JMdict 确认 | `AINote` / `Meaning` / `VocabDefSC` |
| **缺乏理解** | 还不能用自己的话解释，反复看卡帮助不大 | `AINote` 只是词典义项堆叠；句子语法明显高于当前水平；用户说“看不懂” | `study`：**不改卡**；列出要回看的材料、语法点、台词时间 | 不写（plan 里 `study`） |
| **记忆干扰** | 两个相似术语/公式总混；成组的数词/助数词、日期、月份更常见 | 同读音、近形、近义；同一系统（数字+助数词）；两张卡的 lapses 都高 | `separate`：成组时保留一个锚点、其余建议暂停、写系统对比表；两两干扰时写对比钩子（**暂停只给 noteId/cardId，不执行**） | `groups` 建议 + 锚点 `AINote` / `VocabPlus` |
| **记忆术** | 难记信息加 mnemonic 或与相关概念建立联系 | 没有 hook；义项孤立；每次都要从头推 | `mnemonic`：加一条 ≤ 80 字的钩子（对比 / 场景 / 谐音 / 构词） | `AINote` 末段 / `VocabPlus` |

- 病因可以叠加，但 `verdict` 只填**主导**的一个；其余写进 `evidence`。
- 不要为了“多写点”而硬凑：一张卡只解决一个主要问题，比五个都碰一点更有效。
- **成组干扰**（数词/助数词、日期、月份、量词）不要逐张编谐音：先把它看成一个系统，
  用 `groups` 保留一个锚点、暂停其余、写一张对比表；见 §6.5。
- 如果四种病因都不成立（内容本身没毛病，只是间隔太短/当天负载太高），**不要硬改**：
  在报告里写“内容无明显问题，建议等待或减少新卡”，`fields` 留空。等待/改调度不在本技能执行。
- 拿不准词义/读音/词性时，先 `jmdict-lookup`（AGENTS §4），不要凭记忆补一个像样的解释。

## 三、固定流程

1. **扫描**（只读）：`leech.py scan` → 表格 + `temp/leech_scan.json`。证据包括
   lapses/reps、每张卡字段全文、字数/义项数/例句数、同读音/近形候选。
2. **诊断**：逐张对照 §2，选一个主导病因，`evidence` 必须引用具体证据
   （lapses、字段内容、混淆对象）。`understanding` 不要硬加记忆钩子。
   先看 `scan` 的 `clusters`：出现 `[数词/助数词]` 或 `[同读音]` 时，先判断是不是
   成组干扰；成组走 §6.5，不要一张一张改。
   超过 ~30 张：先 `context-offload` / `local-llm` 做首轮分诊，主模型只复核最终
   `fields` 与钩子；不要把整份 scan JSON 贴进主对话。
3. **写计划**：按 §5 写 `data/leech/plan_<日期>.json`。`fields` 是**最终完整值**，
   不是补丁；只写 §6 白名单字段。
4. **演练**：`apply --plan …`（不加 `--commit`）。读 diff，核对张数/字段数；
   **把摘要给用户看，等明确的“可以写”**。
5. **真写**：`apply --plan … --commit`。脚本自动备份 → 写字段 → 回读 → 摘 `leech`。
6. **汇报 + 回退**：给出备份路径和 `restore` 命令（见 §8）。

> **不要在同一轮里 scan 完直接 `--commit`。** 改写 `AINote` 是覆盖用户已有讲解，
> 必须先让用户看到“哪张卡、改哪个字段、旧值→新值”。

## 四、命令

```powershell
$WS    = "<工作区根>"
$PY    = "python"
$LEECH = "$WS\.dsh\skills\jp-anki-leech\scripts\leech.py"
```

```powershell
# 1) 扫描（只读；默认 tag:leech，最多 100 张）
& $PY -X utf8 $LEECH scan
& $PY -X utf8 $LEECH scan --limit 0 --out "$WS\temp\leech_scan.json"
& $PY -X utf8 $LEECH scan --note-id 1736762890267

# 2) 演练：只打印 diff，不写库
& $PY -X utf8 $LEECH apply --plan "$WS\data\leech\plan_20261027.json"

# 3) 用户确认后真写
& $PY -X utf8 $LEECH apply --plan "$WS\data\leech\plan_20261027.json" --commit

# 4) 回滚（备份路径由 apply 打印）
& $PY -X utf8 $LEECH restore --backup "$WS\data\leech\backup_20261027_133000.json" --commit
```

常用开关：

- `--query "tag:leech"`：默认；标签被改名时传新查询。
- `--limit N`：默认 100；`0` = 全部。
- `--note-id 1,2`：只处理点名的卡（覆盖 `--query`）。
- `--out PATH` / `--no-out` / `--json`：JSON 落盘路径 / 不落盘 / 只输出完整 JSON。
- `scan` 表格下方的 `候选干扰组` 是**候选**：`数词/助数词` 用「数字+助数词」判定，
  `同读音` 用读音判定；`事情/用事` 这类语义组要自己判断，脚本不猜。
- `--keep-leech`：写成功后保留 `leech` 标签（想人工复核后再摘时用）。
- `--allow-untagged`：允许写没有 `leech` 标签的笔记；只用于计划过期，**先确认**。

退出码：`0` = 校验通过 / 无需变更 / 全部写入并回读一致；`1` = 校验失败、写入失败、
回读不一致或摘标签失败。**校验失败时整批不写**，不会写一半。

## 五、`plan.json` 形状

一个计划可以同时有 `groups`（干扰组建议）和 `items`（具体字段改写）：

```json
{
  "version": 1,
  "groups": [
    {
      "name": "数の言い方（日・月・つ）",
      "members": [1736762890767, 1736762890791, 1736762903583, 1736762903589, 1736762903590],
      "keep": 1736762903583,
      "suspend": [1736762890767, 1736762890791, 1736762903589, 1736762903590],
      "evidence": "5 张都是数字+助数词；日/月/つ 三套读音混在一起；lapses 8-11",
      "contrast": "日（1-10）：ついたち・ふつか・みっか・よっか・いつか・むいか・なのか・ようか・ここのか・とおか\n月（1-12）：いちがつ・にがつ・さんがつ・しがつ・ごがつ・ろくがつ・しちがつ・はちがつ・くがつ・じゅうがつ・じゅういちがつ・じゅうにがつ\nつ（1-9）：ひとつ・ふたつ・みっつ・よっつ・いつつ・むっつ・ななつ・やっつ・ここのつ",
      "order": [1736762903583, 1736762903589, 1736762903590, 1736762890767, 1736762890791]
    }
  ],
  "items": [
    {
      "noteId": 1736762903583,
      "verdict": "interference",
      "evidence": "与 二日/八月/九月/八つ 同属数词系统；先保留二月做锚点",
      "fields": {
        "VocabPlus": "数词先分类：日=ふつか、月=にがつ、つ=やっつ。先分清「日/月/つ」，再记读音。"
      }
    }
  ]
}
```

规则：

- `groups` 和 `items` 至少有一个；只有 `groups` 时 `apply --commit` 也不写库。
- `groups` 只是**建议**：不写字段、不 suspend/unsuspend。暂停/解冻由用户在 Anki 里手动做。
- `members` / `keep` / `suspend` / `order` 都用 **noteId**；脚本会把 `suspend` 解析成
  cardId 打印出来（Anki 的暂停是按卡，不是按笔记）。
- `keep` 必须在 `members` 里，且不能同时出现在 `suspend`；`suspend` / `order` 必须是
  `members` 的子集；`members` 至少 2 张。`evidence` 必填。
- `contrast` 是给人看的对比表（可多行），**不要**塞进卡片字段；锚点卡的 `VocabPlus` /
  `AINote` 只写一条 ≤80 字的分类规则。
- 组员可以包含不是 `leech` 的对照卡（只用于说明）；真正写字段的 `items` 仍要求 `leech`
  （或显式 `--allow-untagged`）。
- `items` 的规则不变：`verdict` ∈ `overload` / `vague` / `understanding` /
  `interference` / `mnemonic`；`evidence` 必填；`fields` 是最终完整值；`understanding`
  时 `fields` 必须为空；`split` / `suspend` / `study` 只打印、不执行；`items.suspend`
  也用 noteId（脚本解析成 cardId 打印）。
- `noteId` 重复、笔记不存在、没有 `leech` 标签（且未加 `--allow-untagged`）→ 整批拒绝。
- 计划文件默认放 `data/leech/`；备份也在这里，**不要**放 `temp/`（会被 `temp clean` 清掉）。

## 六、按笔记类型改（只改这些）

| 类型 | 正面 | 可写字段 | 改法 |
|---|---|---|---|
| `Basic`（`2-例句`） | 音频 + 图片 | `AINote` | 中文翻译要贴句；核心词汇第一条 = `Word`；只留一个语法点；钩子放末段 |
| `Japanese Vocabulary` | 音频 + 词性 | `AINote` / `Meaning` / `Sentence Translation` | `Meaning` 第一条 = 本句语境的义项；`AINote` 统一成 `<p>` 格式；钩子放末段 |
| `eggrolls-JLPT10k-v3.5` | 词形 + 最多 4 例句 | `VocabDefSC` / `VocabPlus` / `SentDefSC1-4` | `VocabDefSC` 用 ①②③ 按场景分义项；`VocabPlus` 放钩子；**不要删/清空 `SentKanji*` 来“拆分”** |

遇到不认识的笔记类型：**停手问用户**，不要猜字段名，也不要改模板。

### 6.1 `AINote` 形状（`Basic` / `Japanese Vocabulary`）

```html
<p><b>中文翻译：</b>自然、贴句的中文翻译。</p>
<p><b>核心词汇：</b><br><ruby>事情<rt>じじょう</rt></ruby>：名词。情况、缘由、苦衷。<br>…</p>
<p><b>语法要点：</b><br>句型：含义 + 接续 + 在句中的功能</p>
<p><b>记忆钩子：</b>一条 ≤ 80 字的钩子。</p>
```

- 只有 `<p> <br> <b> <ruby> <rt>`；禁止 `<div>/<span>/<ul>/<li>/style/class`、LaTeX、`\`、`$`、
  Markdown 围栏、`**`、半角双引号 `"`（用「」）。
- **必须有** `<b>中文翻译：</b>` 和 `<b>核心词汇：</b>`（冒号在 `<b>` 里）——
  `check_cards` 靠这两个锚点查段落；写成 `<b>中文翻译</b>` 会被打回。
- 可见正文 ≤ 400 字。超了先删，不是先加。
- 汉字标 ruby；送假名放 `<rt>` 外；纯假名不标；中文汉字绝不标。
- 旧卡的 `<div>/<ul>` 格式要整体改成 `<p>`；不要只补一句，否则闸门不过。

### 6.2 `Meaning` / `VocabDefSC`

- 纯文本；义项用 `；` 分隔；多义用 `① ② ③` 标场景，**不超过 3 个**。
- 第一条必须是**这个例句里的义项**，不是词典第一条。
- 除 `<br>` 外不要 HTML；不要半角双引号；不要把图片 `<img>` 抄进来。
- 词义/词性有疑问先 `jmdict-lookup`；不要凭记忆扩写。

### 6.3 `VocabPlus`（eggrolls 专用）

- 纯文本，≤ 80 字；模板用 `furigana:` 过滤器渲染，**不能写 HTML**（`<ruby>` / `<br>` 都不行）。
- 不放 `[sound:]`、`{{…}}`、换行模板语法。
- 只放一条钩子；不要写成第二个释义段。

### 6.4 记忆钩子（mnemonic）的写法

允许四类，按可信度排序：

1. **对比**：反义/近义/易混词（`暗い ↔ 明るい`；`経つ` 是时间流逝，`過ぎる` 是经过/过头）。
2. **场景**：把词绑到来源台词/画面（`Source` 里有作品与集数时优先）。
3. **谐音**：必须标注“谐音”，且不能改变正确读音；只作为检索线索，不替代释义。
4. **构词**：只写**真实**词源/词素；不确定就查 JMdict/词典，**不编**。

硬规则：≤ 80 字；必须和这个词的形/音/义有关；不写冒犯/NSFW 内容；
不把“钩子”写成新的定义；人为联想就明说“人为”，不要伪装成词源。

### 6.5 成组干扰：数词/助数词、日期、月份

这类不是“两张卡互相干扰”，而是**一整个系统**在互相干扰：`二日` / `八つ` / `二月` /
`八月` / `九月` 都是「数字 + 助数词」，读音没有统一规则。逐张编谐音只会增加噪音。

处理顺序：

1. `scan` 的 `clusters` 会把它们归到 `[数词/助数词]`，并列出子组（日/月/つ）。
2. 选一个**锚点**：优先规则性最强/最常用的子系统。示例顺序：月（规则多）→ 日（高频、
   不规则）→ つ（另一套数法）。最终顺序由你按使用频率定。
3. 其余成员写进 `groups.suspend`；在 Anki 里**手动**暂停（脚本会打印
   `暂停搜索串：cid:… or cid:…`，直接粘到浏览器搜索框，选中后暂停）。
4. 整组写一张 `contrast` 对比表（放计划/报告，**不要**塞进卡片）。
5. 锚点卡只写一条**分类规则**（`VocabPlus` / `AINote` 末段，≤80 字），例如：
   `数词先分类：日=ふつか、月=にがつ、つ=やっつ。先分清「日/月/つ」，再记读音。`
6. 锚点稳定后，按 `order` 手动解冻下一张；不要一次全解冻。

对照表（示例；读音要再用 JMdict 核）：

```text
日（1-10）：ついたち・ふつか・みっか・よっか・いつか・むいか・なのか・ようか・ここのか・とおか
月（1-12）：いちがつ・にがつ・さんがつ・しがつ・ごがつ・ろくがつ・しちがつ・はちがつ・くがつ・じゅうがつ・じゅういちがつ・じゅうにがつ
つ（1-9）：ひとつ・ふたつ・みっつ・よっつ・いつつ・むっつ・ななつ・やっつ・ここのつ
```

例外单独记：4月 しがつ、7月 しちがつ、9月 くがつ；1日 ついたち … 10日 とおか；
11日以后多数是 じゅういちにち…，但 14日 じゅうよっか、20日 はつか、24日 にじゅうよっか 是例外。
`八つ` 是 1-9 的「つ」数法，不要和 `八月` 的「月」混在一起记。

注意：

- 只保留一个锚点通常最有效；如果子系统之间已经分得清，也可以每个子系统留一个锚点。
- 不要改 `VocabDefSC` 把义项删光：数词卡的问题是**读音冲突**，不是释义。
- 暂停/解冻是学习决策；脚本只给 noteId/cardId 和顺序，**不执行**。

## 七、失败处理

| 现象 | 动作 |
|---|---|
| `连不上 AnkiConnect` | 让用户开 Anki（AnkiConnect 插件）；不要改用 sqlite 直连 |
| `Close the affected editor` | 那张卡正在编辑器里开着；让用户关掉编辑窗口，重跑（幂等） |
| `计划未通过校验` | 按报错改 plan；**整批未写**，不会写一半 |
| `AINote 缺少段落：中文翻译` | 写成 `<b>中文翻译：</b>` / `<b>核心词汇：</b>`，冒号别丢 |
| `字段 X 不在白名单` | 计划写错字段；不要为了“改得更多”去碰模板字段 |
| `groups[...] keep 不能同时出现在 suspend 里` | 组里选一个锚点；锚点不要放进暂停列表 |
| `groups[...] suspend 有非成员` | `members` 要包含所有被暂停/排序的 noteId |
| `groups[...] members 至少 2 张` | 单张不是“组”；单张干扰用 `items` 的对比钩子 |
| `没有 leech 标签` | 计划过期或已处理；确认后加 `--allow-untagged`，或重新 scan |
| `回读不一致` | 浏览器/编辑器开着；关掉重跑；字段已写但没刷新时切走再切回 |
| `摘标签失败` | 字段已写；在 Anki 浏览器里手动移除 `leech`，不影响内容 |
| `queue=-1`（已暂停） | **不要** unsuspend；先把内容改好，由用户决定何时恢复 |
| 拆分/暂停建议没执行 | 设计如此；在 Anki 浏览器里按 noteId/cardId 手动做，或让用户点名后另开任务 |

## 八、收工汇报

1. 扫描了多少张（模型/牌组分布）、诊断各病因多少张；
2. 改写了多少张 / 多少个字段；只诊断不改多少张；
3. 备份路径（`data/leech/backup_*.json`）与回读结果（一致/不一致）；
4. `leech` 标签摘了多少、是否保留；
5. 干扰组：N 组，每组的 keep / suspend（noteId + cardId）/ order；拆分建议、暂停建议
   各几条（说明**未执行**）；
6. 回退命令：`restore --backup <路径> --commit`。

## 九、实测与坑（2026-10-27）

- 当前全库 `tag:leech` **19 张**：`eggrolls-JLPT10k-v3.5` 16 张 + `Japanese Vocabulary` 3 张；
  18 张 review、1 张 learning；牌组配置 `leechFails=8`、`leechAction=1`（达到阈值自动暂停），
  但这批多数已被手动恢复。本技能**不改 queue**。
- 当前 19 张里有 **5 张数词**：`二日` / `八つ` / `二月` / `八月` / `九月`。`scan` 的
  `clusters` 会归到 `[数词/助数词]`（子组 日：二日；月：二月/八月/九月；つ：八つ）；
  `経つ` 不以数字开头，不会误入。
- 这 5 张的建议：先保留一个月（规则多）做锚点，其余 4 张手动暂停；锚点稳定后按
  `groups.order` 解冻。示例计划见 §5。
- 16 张 eggrolls 的 `AINote` 是空的——它们的修法是 `VocabDefSC` + `VocabPlus`，
  不要硬造 `AINote`（模板不显示）。
- 3 张 Japanese Vocabulary 的 `AINote` 还是旧 `<div>/<ul>` 格式；要改就整体改成
  `<p>`，只补一句会被 `check_cards` 打回。
- `もてる` 的 `AINote` 原始 2026 字 / 可见 1007 字，`Meaning` 79 字还带 `<img>`——
  典型信息过载；新值不要把图片抄进去。
- `VocabPlus` 走 `furigana:` 过滤器：写 `<ruby>` 会原样显示成标签，不是振假名。
- `scan` 的 `similar` 只在当前 leech 批次内找同音/近形；要查全库同音词，
  用 Anki 搜索 `Transliteration:<读音>` / `VocabFurigana:<读音>`，再判断干扰。
- **不要清空 `SentKanji2-4` 来“拆卡”**：那是删内容，不是拆分；拆分建议只写进 `split`。
- 摘掉 `leech` 后，用 `prop:lapses>=8` 仍能找回这批卡；不要为了“留痕”再加别的 tag。

## 十、相关文件

- 脚本：`.dsh/skills/jp-anki-leech/scripts/leech.py`
- 结构闸门：`code/common/check_cards.py`（`AINote` 段落 / 标签白名单 / 半角引号）
- Anki 通道：`code/common/anki_api.py`（读写、备份回读都走它）
- 语义核验：技能 `jmdict-lookup`（改 `Meaning` / `VocabDefSC` / 读音前先查）
- `AINote` 规范正文：`docs/jp-card-agent-instruction.md`
- Anki 官方 Leeches：<https://docs.ankiweb.net/manual/leeches>

---

**本技能只做 leech 卡的诊断与卡背改写。** 清理 → `jp-anki-triage`；生成 → `jp-anki-generate`；
激活 → `jp-anki-activate`；挖生词 → `jp-anki-mine`；配音 → `jp-anki-audio`；
振假名读音 → `jp-anki-check-ruby`；每日讲义 → `jp-anki-daily-lesson`。
