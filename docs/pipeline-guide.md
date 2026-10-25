# 日语字幕卡流水线 · 操作手册

> 状态：active ｜ 最后核实：2026-10-20

**这是什么**：一集字幕卡从导入到入库的操作手册 —— 每阶段跑什么命令、判据是什么、闸门在哪。
**为什么存在**：换作品/换集时照它跑就行，不必读代码；判据与闸门就写在命令旁边。
**怎么用**：先看 §0（两条流水线与一键命令）；换新作品看 §8；日常只跑一集就用
`python code/cli.py episode --tag "动画::…::第NN集"`（阶段 2-5 一条命令）。
**不在这里**：每日讲义/弱项/补例句见 `jp-anki-daily` 技能与 docs/today_new-使用说明.md；
退场机制与历史只在 [docs/deprecated.md](deprecated.md)。

---

## 0. 两条流水线与一键命令

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$EXE = "$WS\code\execution"   # 执行区：五个阶段的脚本
$COM = "$WS\code\common"      # 共享库与自检器（check_cards.py / check_mine.py）
$DAT = "$WS\data"             # 快照、缓存、各阶段工作目录

# ── 阶段 0：拉取判据（词表/语法表/已有例句）。跨集复用，词表变了才需要重跑
& $PY "$EXE\pipeline.py" prepare

# ── 阶段 1：清理（把无学习内容的卡挑出来）
& $PY "$EXE\pipeline.py" triage --query "tag:待标记"      # 出报告，不改库
#   → 人工过一遍 data/pipeline/drop_candidates.md / data/pipeline/keep_list.md
& $PY "$EXE\pipeline.py" apply                            # 打标签 + suspend

# ── 阶段 2：生成（振假名 + 讲解）
& $PY "$EXE\pipeline.py" split --tag "动画::<作品名>::<季>::第NN集" --batches 12
#   → gen 直连本地模型逐批生成（不派子代理、不花云端 token；已存在的批次自动跳过）
& $PY "$EXE\pipeline.py" gen
& $PY "$EXE\pipeline.py" write                            # 入库（会先校验一遍，不通过就不写）

# ── 阶段 4：素材生词（把例句里出现、但 core6000/考级词汇都没有的词建成第三个词汇牌组）
& $PY "$EXE\mine.py" scan                          # 只读扫描，出候选与报告
#   → gen 直接调本地模型判定（split 后一条命令跑完；--print-prompts 才是子代理备用路径）
& $PY "$EXE\mine.py" split --batches N
& $PY "$EXE\mine.py" gen
& $PY "$EXE\mine.py" write --commit                # 直接入库（校验在内部；含 Index / JitenAnimeRank）

# ── 阶段 5：给生词卡挂音频（单词 TTS + 例句原声）
& $PY "$EXE\mine_audio.py" plan                    # 只读：看每张卡要挂什么
& $PY "$EXE\mine_audio.py" apply --commit          # 直接真写：上传媒体 + 写两个字段（写完自动回读）

# ── 按需（不是全量）：给用户点名的 core6000 词补第二条例句（gen → tts → apply 演练 → apply --commit）
& $PY "$EXE\core6000_example.py" gen --words "徹夜,適当,残り"     # 详见第 9 节
```

> **每个阶段只留一道机械闸门，且闸门放在"改库前"**（见 §0.4）：
> 生成时 `gen` 内部机械判一次，脚本在入库前校验一次，入库后只做抽检。
> 同一件事不再查第二遍 —— 想单独看校验结果时，`pipeline.py verify` /
> `mine.py verify` / `mine_audio.py verify` 都还在，但都不是必经步骤。

**路径约定**：`$EXE` = 执行区（上面所有脚本）、`$COM` = 共享库与自检器、
`$DAT` = 数据（快照 `data/snapshots/`，工作目录 `data/pipeline|vocab|plans|i1|weak/`）、
生成物在 `$WS\output\`（`i1/`、`audio/`）、报告在 `$WS\docs\reports\`。
完整目录表见根目录 `README.md`。

**每次要改的只有三处**：
- `triage --query`：ABS Player 新导入的卡带什么标签（本次是 `待标记`）
- `split --tag` / `plan --tag`：本集的集数标签。**命名随你**，只要同一集前后一致即可；
  推荐 `动画::<作品名>::<季>::第NN集`（与既有 01–04 集一致）。代码不认作品名，只把它当字符串
- `--batches`：约 **14 张/批**。157 张用 12 批；张数 ÷ 14 向上取整即可

若收藏结构调整（新增词表 deck、改 deck 名），只改 `code/execution/pipeline.py` 顶部的 `CFG` 配置区。

---

## 0.1 阶段 4 与前三个阶段的关系

阶段 1–2 处理的是**例句卡本身**（清理 → 补振假名与讲解），阶段 4 则是**新增词汇卡**：把例句里出现、但 `core6000` 与 `考级词汇` 都没收录的词，
建成第三个词汇牌组 `0-日本语学习::0-词汇::0-素材生词`。

```
ABS 字幕卡 ──阶段1 triage/apply──▶ 保留的例句卡 ──阶段2 split/write──▶ 带振假名的例句卡
                                                                                    │
                                                              阶段4 scan ◀──────────┘ （只读，不动例句卡）
                                                                  │
                                              阶段4 split → 子代理 → write（内含校验）
                                                                  │
                                                                  ▼
                                                    0-词汇::0-素材生词（新词汇卡）
```

**阶段 4 不修改任何例句卡**，只读 `Sentence` / `Sentence HTML` / `Source` 三个字段。
所以它可以反复跑、也可以随时跳过，不影响前三个阶段。
建议在阶段 2 的 `write` 之后跑——那时例句卡的文字与振假名都已校验过，可以直接复用。

---

## 0.2 可选前置：入库前先把字幕筛一遍（`filter_subtitle.py`）

阶段一是在卡**已经进库之后**清理。若想连导卡的人工一起省掉，可以先在**字幕层面**筛：
只把值得做卡的片段留在字幕里，再拿这份字幕去导卡，阶段一的 triage 就没什么可删的了。

判据与阶段一一致（历史名词/官职/地名、古文、生僻或低频字词、惯用搭配、复杂长句 ⇒ 保留），
额外要求**句子完整**、**脱离剧情上下文也能读懂**，并剔除只在本作登场的人名与设定名。
被字幕切开的相邻句子会**合并成一条**（时间码取首块开始→末块结束），块内混进来的纯语气词行一并剔除。

```powershell
& $PY "$EXE\filter_subtitle.py" probe  --src "<原始 srt>"                     # 只读体检：编码/换行/块数
& $PY "$EXE\filter_subtitle.py" apply  --plan "data/evidence/<集>/plan.json"  # 出筛选后的字幕 + 判定证据
& $PY "$EXE\filter_subtitle.py" verify --plan "data/evidence/<集>/plan.json"  # 回读逐字比对
```

`plan.json` 里 `groups` 写保留的块序号（多个序号 = 合并成一条），`drop_lines` 写块内要剔除的语气词行。
产物是重排编号的 SRT（日文文本逐字保留，含全角空格与原本的换行位置；导卡时这些换行就是卡面里的 `<br>`），
证据沿用阶段一的文件名 `keep_list.md` / `drop_candidates.md` / `verdict.csv`，放在 `data/evidence/<集>/`。
判据漏掉的好句子，把序号加回 `groups` 重跑 `apply` 即可。

实测：平家物语第 01 集 336 块 → 保留 63 条（覆盖 95 块），弃用 241 块
（语气词/感叹 101、无学习点 62、残句 45、音效/舞台指示 23、上下文依赖 10）。

---

## 0.3 哪一步能交给本地模型（按「错误可不可见」分）

把活交给本地/弱模型的前提**不是模型够不够聪明，而是这一步做错了能不能被确定性地查出来**。
本集（平家物語 S01E02）实测下来，判据是「错误可见性」：

| 环节 | 本集体量 | 做错了看得见吗 | 建议 |
|---|---|---|---|
| 字幕筛选 keep/drop | 309 块 | **看不见**（漏掉的句子永远不会变成卡） | 本地跑，但**改小批（≤30 块/批）**；再用 `review_shortlist.py` 出短名单复核 |
| 阶段二 例句卡生成 | 5 批、输出 38.7K 字符（本集 token 大头） | 看得见（`gen` 内部校验 + 入库前校验 + `check_ruby`） | **已改成本地直连**（`pipeline.py gen`，不派子代理） |
| 阶段四 生词判定 | 26 候选、输出 4.9K 字符 | 看得见（`check_mine` 自检 + 入库前校验） | 适合本地 |
| 古文/和歌翻译、史实、读音 | 少量 | **看不见**（无闸门） | 留强模型，或要求本地给出处 |

两条为此新增的闸门：

```powershell
# ① 振假名读音自检：拿**字幕自带的注音** + deck 已有卡的先例校验
& $PY "$COM\check_ruby.py" --plan "data/evidence/<集>/plan.json" --gen "$DAT\pipeline\gen"
& $PY "$COM\check_ruby.py" --plan "data/evidence/<集>/plan.json" --anki "tag:动画::<作品名>::<季>::第NN集"
#    --blind-out 会把「两道闸门都盖不到的读音」单列成一份清单 —— 强模型只审这一份

# ② 判弃块复核短名单：把几百条判弃压到十几条
& $PY "$TOOLS\review_shortlist.py" --verdict "data/evidence/<集>/verdict.csv"
```

**为什么需要 ①**：`check_cards.py` 只查结构，**查不出汉字标错读音**；而 ABS Player 导入时会把字幕里的
`漢字(かな)` 注音剥掉，子代理只能猜。本集靠这条对照从 33 处注音里抓出 **6 处真实错读**
（暇 ひま→いとま、美女 びじょ→びんじょう、祇女 ぎじょ→ぎにょ、蹴 け→く、
殿下乗合 でんか→てんがののりあい、一本葛 いっぽん/くず→ひもと/かずら），
其中一处还是事后回归时**它自己抓出来的**（AINote 里漏改的 `蹴 け`）。

⚠️ ①的覆盖边界（实测本集 249 个含汉字基底 / 407 次出现）：字幕注音盖住 49 个、
deck 读音词典盖住 20 个、**两道都盖不到 185 个（274 次）**。
也就是说读音风险只有约一半是机械可查的 —— 剩下那一半要靠 `--blind-out` 的清单让强模型快速过一遍。

**② 为什么需要**：判弃是**不可逆**的。本集本地代理判弃 176 块，人工逐条看很贵，
而 `review_shortlist.py` 用 `pipeline.classify` 的同一套判据反向扫，只留 26 条命中，
再把已知的机械误报（命中只来自说话人标记/音效括号、命中词是更长词的一部分、残句、重复）
自动降级，最后**值得看的只有 15 条**，真正该保留的 2 条排在头两行。

结论：**本地模型做量、机械闸门把关、强模型只看短名单** —— 本集这条路上，
本地模型一次看 309 块时漏掉的 `#86 今様は この世の今を映し出す 鏡のようなものであるぞ`，
在 12 条小批的复核里被**同一个本地模型**自己捞了回来（12 条里 10 条与强模型判断一致）。

---

## 0.4 闸门只留一道（2026-10 调整，省 token / 省时间）

**原则：同一件事只查一次，且查在"改库前"。**
以前每个阶段都有 2–3 道重叠的检查（子代理自检 + 独立 verify + write 内部再查一遍 +
写库后全量回读），它们查的是同一份确定性数据，结论必然一致 —— 属于纯重复劳动。
现在改成：

| 阶段 | 以前 | 现在 |
|---|---|---|
| 阶段二 生成 | 子代理自检 → `verify` → `write` 校验 → 写后全量回读逐字比对 | `gen` 内部判一次（不合格只重问一轮）→ `write`（内部跑同一份校验）→ 写后**抽检 3 张 + 一次统计** |
| 阶段四 生词 | 子代理自检 → `verify`（逐条规则 + 已在牌组里）→ `write` 又把同样两条各跑一遍（还要重建一次 1.7 万张的索引） | 子代理自检一次 → 校验一次（`write` 会在需要时自己跑）→ `write` 只做"新牌组幂等 + 向来源卡重取例句" |
| 阶段四 规则实现 | `check_mine.py`、`mine.check_entry`（它的拷贝）、`check_cards.py` 三层等价实现 | 只有 `code/common/check_mine.py` 一份 |
| 阶段五 音频 | `apply --commit` 回读 + 再单独跑 `verify` | `apply --commit` 内部回读；`verify` 降为可选 |
| 生成方自检 | "必须做到 0 不合格"（会反复重写整批） | 脚本机械判一次、只重问一轮；仍不合格的两个字段留空 |

被删掉的是**重复**，不是**把关**：教学内容的正确性仍然由
①生成时 `gen` 内部的机械校验（`check_cards.py` / `check_mine.py`）、
②入库前的机械校验（`write` 内部）、
③`check_ruby.py` 的读音对照 三道不同性质的检查覆盖。
`verify` 三个命令都保留着，只是不再是必经步骤（想先看报告再决定时才单独跑）。

代价说清楚：弃用判定与写库的**小概率遗漏**不再有第二道网兜底了。
按用户口径这是可接受的 —— 这是学语言的卡，多一条少一条不影响什么；
真觉得某集重要，就把 `verify` 和写后回读加回去跑一遍。

还有两处**没有**动，因为它们直接关系教学质量：
- 阶段四的判定仍要读完整规范（`mine-agent-instruction.md`）；阶段二已改成
  `pipeline.py` 里自包含的 `LOCAL_INSTRUCTION`（本地模型读不了文件，规范必须压进提示词）；
- `check_ruby.py --blind-out` 的读音清单仍建议让强模型过一遍（读音错了看不出来）。
  想再省，就从这两处下手，不要从"少查一遍结构"下手。

---

## 0.5 编码统一：文本 I/O 一律走 `textio`（2026-10-08）

**一切文本 I/O 与编码走 `code/common/textio.py`（唯一实现）**：`import textio` 一行就把 stdio 接管成
UTF-8，读文件用 `textio.read_text` / `textio.load_json`，子进程用 `textio.run`，stdin 用 `read_stdin`；
**不要再手写 `sys.stdout.reconfigure(...)`**。本机 shell 是 **Windows PowerShell 5.1**，
`Get-Content` / `Import-Csv` / `Out-File` 默认 **ANSI=GBK** —— **别用它解析工作区 JSON**：
读 UTF-8 的日文会解成乱码或报错得到 `$null`，按日文字段名取的属性全 `$null` → 判断恒真
（2026-10-08 因此误删了 `output/cmp4` 的 39 个产出）。改完脚本或怀疑输出乱码时跑：

```powershell
& $PY "$COM\textio.py" check            # stdio / 管道 / 各种编码的文件，15 项自检
& $PY "$COM\textio.py" audit --strict   # 0 = 没有手工编码补丁、会直接跑的脚本都 import textio
iex ([IO.File]::ReadAllText("$COM\ps-utf8.ps1", [Text.Encoding]::UTF8))   # PS 侧补丁：Get-Content 等默认钉成 utf8
& $PY -X utf8 -c "print('日本語 ♪')"    # ad-hoc python 一行：加 -X utf8 就不会被 GBK 打死
```

PS 侧只能这样加载：本 shell 是受限令牌，`.ps1` 文件跑不了（Restricted/AllSigned/RemoteSigned 都拦，
`Unrestricted` 报 `AuthorizationManager check failed`，只有 `Bypass` 行），`$PROFILE` 也不被加载
（profile 已装好，只对你自己的 PowerShell 窗口生效）。也可以
`Set-ExecutionPolicy -Scope Process Bypass -Force` 之后再 dot-source。
铁律全文见 [AGENTS.md](../AGENTS.md) §1 第 3 条与 §3 第 2 条；档案见
[plans/2026-10-08-编码统一-textio.md](plans/2026-10-08-编码统一-textio.md)。

---

## 1. 阶段一：清理

### 1.1 判据（三维，占一样即保留）

一张卡**保留**，当且仅当它至少满足下面一条，**且该语言知识没有被已有例句覆盖**：

| 维度 | 判据 | 实现 |
|---|---|---|
| ① 单词 | 句中含 N4 以上、且未在参照系出现过的词 | 词表最长匹配 + 活用词干 + 假名/片假名互换 |
| ② 语法 | 命中语法 deck 的句型条目（N3 以上，或 ≥3 字的口语型） | 语法 deck 的 `Card` 字段作句型表，另加 70 条教材常漏的口语型 |
| ③ 惯用搭配 | 命中 80 条熟语表（`気を使う`、`にも程がある`…） | 你的旧卡里 39/92 的 Word 属于这一类，所以单列 |
| ④ 长句 | 含连体修饰，或去标点后 ≥26 字 | 正则近似 |
| ⑤ 新汉字 | 含词表完全未收录的汉字（`綺麗`/`眩`/`墓`） | 强新词信号 |

**参照系 = `0-日本语学习::2-例句` 这个 deck 本身的全部卡**（新卡就是要加进这个集合里）。每跑一集参照系就变大，判定会自动变严——这是想要的行为。

⚠️ **参照系不要按 `AINote` 过滤**：查重与覆盖判定的依据是 `Sentence` 字段，`AINote` 空不空只说明那张卡跑没跑过 prompt。用 `AINote:_*` 拉参照系会漏掉 `AINote` 还空着的重复例句（未跑的批次、suspended 的弃用卡）。
另外 triage 时本批卡已经在 deck 里了，**参照系必须剔除本批自身的 noteId**，否则每张卡都被自己的词和句型"覆盖"，会全部误判为 DROP。

**词汇门槛定在 N4** 的依据：你已有 92 张卡的 `Word` 字段分布是 N5×5 / N4×13 / N3×15 / N2×12 / N1×8 / 不在词表×39。N5 基础词你几乎不收，而"不在词表"的惯用搭配才是大头。

### 1.2 实测效果

| 指标 | 数值 |
|---|---|
| 导入 | 311 张（Aria 第 04 集整条字幕轨） |
| 判定保留 | 164 |
| 判定弃用 | 147（无学习内容 132 + 批内重复 14 + 与旧卡重复 1） |
| 保留维度分布 | 单词 96 / 单词+语法 23 / 语法 16 / 单词+长句 10 / 其余 19 |
| **回归复现率** | 对已判弃的 147 张重跑，**147/147 复现原判（100%）** |

### 1.3 已知盲区（人工过报告时重点看这几类）

这些是判据会漏判的，看到时手工放回：

- **纯假名副词**：`おそらく`、`だいたい` 不在你的词表里，判据看不见。判据要求纯假名词 ≥3 字才参与匹配（否则 `やあ` 会在 `いやあった` 里误命中），2 字的假名词一律不参与。
- **可能形**：`乗れる`（← 乗る）不会被识别为语法点。
- **派生名词**：`優しさ`（← 優しい，N5）匹配不到。
- **专有名词**：`アリア`、`アリシア` 会被正确忽略（不在词表中），这是对的。
- **惯用搭配表只有 80 条**：本次这一集只命中 1 次（`気が付`）。若某集熟语密集，需要扩充 `IDIOMS`。

### 1.4 执行方式：永远可逆

弃用卡不删除，而是**加标签 `待标记::弃` + suspend**。两个字段（`AINote`/`Sentence HTML`）保持为空，所以它们仍能被 `AINote:` 查询命中，不会被误当成已完成。

回退方法：`deck:0-日本语学习::2-例句 is:suspended` 全选取消暂停 → 移除 `待标记::弃` 标签。

---

## 2. 阶段二：生成

### 2.1 规范

完整规范在 [jp-card-agent-instruction.md](jp-card-agent-instruction.md)。核心：

- **`AINote` 四段**：中文翻译 / 核心词汇 / 语法要点 / 动词变形解析。第 4 段**按需出现**——句中若没有实际发生音变的活用动词就整段省略，不要写"原形→原形"凑格式。
- **`Sentence HTML`**：只有例句本身 + `<ruby>`，不包裹 `<p>`，不加标点，原文的 `<br>` 原样保留。
- **标签白名单**：只能用 `<p> <br> <b> <ruby> <rt>`。禁止 `div/span/h3/ul/li/style/class`。
- **ruby 三条容易错的规则**：送假名必须在 `<rt>` 外（`<ruby>食<rt>た</rt></ruby>べる`）；纯假名不加 ruby；敬语接头辞 `お/ご` 不包进 ruby 基底（`お<ruby>墓<rt>はか</rt></ruby>`）。

### 2.2 生成怎么走（2026-10-11 起：本地模型直连，不派子代理）

```powershell
& $PY "$EXE\pipeline.py" split --tag "…第NN集" --batches 12   # 切批 → data/pipeline/gen/input_NN.json
& $PY "$EXE\pipeline.py" gen                                  # 本地模型逐批 → output_NN.json
& $PY "$EXE\pipeline.py" write                                # 校验 + 入库
```

- **提示词正本 = `pipeline.py` 的 `LOCAL_INSTRUCTION`**（改提示词只改这一处；
  `jp-card-agent-instruction.md` 附录 B 只留对照表）。一次请求默认 **6 张**（`--per-request`），
  14 张的批 ≈ 3 次请求，一趟 4–8 分钟，**零云端 token**。
- **按 ~14 张/批** 切开：一张卡要产出 350–600 字符的讲解，一次全塞进去会把输出上限吃满。
- `gen` **默认跳过已存在的 `output_NN.json`**，中断了直接重跑即可续跑；重做整批加 `--force`。
- 输入里带上了 `Word` 字段：**卡上指定的重点词，模型会放在「核心词汇」第一条**。

**三级级联（2026-10-11）**：本地模型只在**结果可机械校验**的地方顶上，做不出来的不让它硬撑。

| 级 | 谁做 | 命令 | 说明 |
|---|---|---|---|
| ① | 本地模型（不花 token） | `gen` | 首轮 6 张/请求；**AINote 侧**不合格的逐张重问一轮（塞回同一批只会原样再错）。`Sentence HTML` 侧的机械问题不算失败 —— 见下 |
| ② | 本地模型再试 | `gen --fix-failed --per-request 3` | 只重跑 `failed.json` 里的卡，修好的直接并回 `output_NN.json` |
| ③ | 强模型（deepseek） | `merge-fix --file fix_output.json` | 按 `failed.json` 生成 fix 产出（同样的 JSON 数组，只放这些 noteId），并回 |

**判断按字段归属分开（2026-10-11 起，`check_cards.split_hard`）**：`AINote` 是纯语义产出，
不合格只能重问模型；`Sentence HTML` 的硬性问题（文本漂移、漏标 ruby、`<br>` 数不对）**全是机械问题**，
`ruby_engine.py repair` 拿原始 `Sentence` 当骨架重渲染就能确定性地修好。所以 `gen` 遇到后者
**照收讲解**，不再重问模型，也不再把它算成"没做出来"。

> 反例（2026-10-11《七大罪》E01，noteId 1791727898061）：本地模型的 AINote 完全合格，
> 只是把 `様子` 标成了 `<ruby>様<rt>よう</rt></ruby>子`。旧口径把两个字段混在一个 hard 列表里判
> → 整张卡判失败 → **讲解被丢掉** → 卡进 `needs_llm.json` 等强模型；而 `repair` 一次就能修好振假名。
> 同一张卡重问两轮都修不好（模型上一轮就是这么标的），正是"机械问题不该进语言模型"的典型。

实测（转生王女第 01 集，53 张）：①6 张/请求时 28 张一次过（**漏标振假名是主要失败原因**）；
②逐张重试又救回 11 张 → 39；③剩 14 张由强模型补（第一次 12/14 过，2 张是「的」「様」漏标，
改掉后 53/53）。**`failed.json` 是③的输入**，也是"这一集哪几张本地模型没扛住"的记录；
全部通过时 `gen` 会自动把它删掉，免得强模型去做已经做好的卡。

> 同一批里还有一类**隐性瑕疵**：`<ruby>` 缺失的孤立 `<rt>`（`<ruby>救<rt>すく</rt></ruby>援<rt>えん</rt>`）。
> 配对计数查不出来，但渲染时会把这个读音当普通文字显示在词条里。2026-10-11 起
> `check_cards.py` / `check_mine.py` 把它列为硬错误（`stray_rt()`），
> 存量卡用 `code/oneshot/fix_stray_rt.py`（默认演练，`--commit` 才写；产出文件与库一起改）。
> 本集 53 张里命中 3 张，已修。

### 2.3 两道质量闸门

| 闸门 | 检查内容 |
|---|---|
| 生成时（`gen` 内部） | 每批用 `check_cards.py` 同一份实现机械判一次，**按字段归属分开**：`AINote` 侧不合格才重问那一轮（`--retries 1`），`Sentence HTML` 侧的机械问题照收讲解、留给 `ruby_engine repair`；实在没产出的卡两个字段留空、留在待办队列里 |
| 入库前校验（`write` 内部） | 逐条规则 + 覆盖率（不多、不少、不重复）；不通过就不写库 |

另有两道不属于"校验"的保护：写库前确认两个目标字段均为空（防覆盖，加 `--overwrite` 可强制）；
写完**抽查 3 张**逐字比对，并用一次查询统计「AINote 仍为空」的卡。
以前这里是把全部 160 张的字段拉回来逐字重比一遍 —— 那等于把入库前的规则再算一遍，已删。
`verify` 命令还在，但它跑的就是 `write` 内部那一份校验，不是必经步骤。

### 2.4 硬性 vs 软性规则

- **可完全自动化**（`check_cards.py` 强制）：逐字一致、标签白名单、非法字符（`\`、`$`、半角引号、Markdown）、ruby 标签配对、`Sentence HTML` 无未标 ruby 的汉字、`AINote` 段落齐全。
- **只能靠语义判断**：`AINote` 里中文解释与日语词混排，ruby 覆盖是否正确只能人看（脚本只能查结构）。

### 2.5 本次入库结果

160 张全部通过，零不合格。AINote 长度中位 360 字符；109/160 带第 4 段；平均每张 2.3 个振假名。

---

## 3. 踩过的坑

坑与处理单独收在 [troubleshooting/pipeline-pitfalls.md](troubleshooting/pipeline-pitfalls.md)，
出怪结果时先翻它。

---

## 4. 下次的操作清单

```
[ ] 1. ABS Player 导出本集字幕卡，确认导入后的标签
[ ] 2. pipeline.py prepare            （词表没变可跳过，但很快，建议照跑）
[ ] 3. pipeline.py triage --query "tag:XXX"
[ ] 4. 人工过 drop_candidates.md（重点看第 1.3 节的盲区类型）
[ ] 5. pipeline.py apply              → 打标签 + suspend
[ ] 6. pipeline.py split --tag "…第NN集" --batches N
[ ] 7. pipeline.py gen                → 本地模型逐批生成（已存在的批次自动跳过，可续跑）
[ ] 8. pipeline.py write              → 先校验再入库（校验不通过就不写）
[ ] 9. 抽查 3 张渲染效果（ruby、段落间距、→ 是否显示正常）
[ ]10. mine.py scan --tag "…第NN集"   → 过 mine_report.md 的候选表
[ ]11. mine.py split → gen（本地模型判定；没判出的 gen --fix-failed / merge-fix 交强模型）→ write（校验 + 演练载荷，看 dryrun_notes.json 的 word 列）
[ ]12. mine.py write --commit         → 复用校验结果入库
[ ]13. mine_audio.py plan → apply（听 output/audio/）→ apply --commit（写完自动回读）
[ ]14. 到 0-词汇::0-素材生词 抽查 2 张（读音、释义、例句振假名、两个音频能播）
```
**试跑只在"提示词或规范刚改过"时才需要。** 2026-09 首次跑通时，试跑 3 张发现了 3 处规范缺陷
（"剥标签后逐字一致"表述不可实现、变形解析段漏标 ruby、纯假名被标 ruby），
都是看到真实产出才暴露的；定稿之后每集再试跑一遍只是把同一份提示词送两遍，
所以第 6 步之后直接全量跑即可。**改动过 `pipeline.py` 的 `LOCAL_INSTRUCTION`
或 `jp-card-agent-instruction.md` 时才回来试跑 2–3 张。**

**第 10–11 步的演练不能跳**（这是唯一"人看载荷"的机会，见下面的踩坑）：先 `write`（不加 `--commit`）
看一遍 `dryrun_notes.json` 的 `word` 列与例句振假名，再到 Anki 里确认 1 张卡的渲染，
然后 `write --commit`。阶段四的子代理产出错误率比阶段二低（条目短、判断点少），
但**词形归一是纯语义判断**，脚本只能查"这个词在不在牌组里"，查不了"这是不是一个词"。

> 阶段四曾经踩过一次：候选文件把 `Sentence HTML` 存成了 `strip_html(Sentence)`，
> 结果新卡例句一个振假名都没有。`check_cards.py` 不管生词卡的这个字段，所以没拦住。
> 现在校验会报「例句含汉字但 Sentence HTML 没有振假名」——看到这条**不要忽略**。

---

## 5. 文件清单

**常驻代码（长期保留；都在 `code/` 的复用区里）**

| 文件 | 作用 |
|---|---|
| [filter_subtitle.py](../code/execution/filter_subtitle.py) | 入库前的字幕前置筛选（probe / apply / verify），判据同阶段一 |
| [pipeline.py](../code/execution/pipeline.py) | 流水线主脚本（prepare / triage / apply / split / gen / write；verify 为可选的事后校验）。**阶段二的提示词正本 = 脚本里的 `LOCAL_INSTRUCTION`** |
| [jp-card-agent-instruction.md](jp-card-agent-instruction.md) | 生成阶段的完整规范（附录 B 是提示词对照表） |
| [check_cards.py](../code/common/check_cards.py) | 自检器，支持文件模式和 `--anki` 直接扫库 |
| [check_ruby.py](../code/common/check_ruby.py) | **振假名读音**自检：拿字幕自带注音 + deck 已有卡的先例校验，`--blind-out` 列出盖不到的读音（见 §0.3）|
| [activate.py](../code/execution/activate.py) | 只为 `vocab reorder-jiten` 的全局重排与历史批次 `revert` 保留 |
| [mine.py](../code/execution/mine.py) | 阶段四：素材生词牌组（scan / split / write；verify 为可选的事后校验）|
| [mine-agent-instruction.md](mine-agent-instruction.md) | 阶段四的完整规范，也是子代理要读的文档 |
| [check_mine.py](../code/common/check_mine.py) | 阶段四的自检器（校验 `data/vocab/gen_mine/output_NN.json`）|
| [mine_audio.py](../code/execution/mine_audio.py) | 阶段五：给生词卡挂音频（plan / apply / verify / revert；`apply --commit` 自带回读）|
| [edge_tts_min.py](../code/tools/edge_tts_min.py) | 纯标准库的 edge-TTS 客户端（阶段五的声音来源）|
| [check_audio.py](../code/tools/check_audio.py) | 阶段五的音频自检（帧数/时长合理性）|
| [review_shortlist.py](../code/tools/review_shortlist.py) | 判弃块复核短名单：把几百条判弃压到十几条，机械误报自动降级（见 §0.3）|
| [pipeline-guide.md](pipeline-guide.md) | 本手册 |
| `data/evidence/ep04_backup/` | 第 04 集的判定记录（`verdict.csv` 逐条判定、`plan.json`、弃用/保留清单）与回归测试证据 |

**运行过程中生成（都在 `data/` 与 `output/` 下，每集重建，可随时删）**

| 路径 | 作用 |
|---|---|
| `data/pipeline/gen/cache.json` | 词表 / 语法表 / 参照系缓存，由 `prepare` 生成 |
| `data/pipeline/gen/input_NN.json`、`data/pipeline/gen/output_NN.json`、`data/pipeline/gen/manifest.json` | 每批的输入、本地模型产出、批次清单 |
| `data/pipeline/plan.json`、`data/pipeline/drop_candidates.md`、`data/pipeline/keep_list.md` | 阶段一的判定结果 |
| `data/plans/plan_activate_*.json` | 历史批次的位置计划与回退依据（每张卡的 `due_before`），**别删**；全局重排的当前计划是 `plan_activate_jiten.json` |
| `data/vocab/mine_candidates.json` | 阶段四的候选池。**从 `split` 到 `write` 之间必须保持不动** —— 校验按它核对子代理产出、并定位例句来源（`mine_report.md` 是同一份数据的人读版，可随时删）|
| `data/vocab/gen_mine/input_NN.json`、`data/vocab/gen_mine/output_NN.json`、`data/vocab/gen_mine/manifest.json` | 阶段四每批的输入、子代理产出、批次清单（与阶段二的 `data/pipeline/gen/` 分开，互不覆盖）|
| `data/vocab/gen_mine/verified.json`、`data/vocab/gen_mine/dryrun_notes.json` | 阶段四校验通过的载荷 / `write` 演练载荷 |
| `output/audio/*.mp3` + `output/audio/manifest.json` | 阶段五合成的单词音频（演练产物，`--commit` 后已上传进媒体库，本地可删）|

---

## 6. 阶段四：素材生词（`mine.py`）

目的：把例句里出现、**但 core6000 与考级词汇都没有收录**的词，建成第三个词汇牌组
`0-日本语学习::0-词汇::0-素材生词`。于是课程表里会出现"你看的片子里真的有、但你还没学过的词"。

### 6.1 收录判据

| 项 | 值 |
|---|---|
| 判定用参照系 | `0-词汇::2-考级词汇`（10,609 张，字段 `VocabKanji`）＋ `0-词汇::1-高频日语单词 6000`（6,000 张，字段 `Word`）|
| 索引规模 | **11,728 个词典形 / 229,007 种可识别写法**，约 4 秒建好 |
| 判定口径 | 去 `〜`、NFKC 统一全半角、去空白后逐字比对；**活用形、假名↔片假名变体、活用词干都算同一个词** |
| 来源 | `0-日本语学习::2-例句` 里最终保留的例句（弃用卡也在 deck 里，但它们的句子不会被选中做新词卡）|
| 笔记模板 | `Japanese Vocabulary`（与 core6000 同一模板，复用其字段）|

**"算同一个词"是什么意思**：`漕い` 会因 `漕ぐ`（在 jp-core 里）被判为已存在，不会收进来。
这条判据同时用三个口径查（`mine.py known_lookups`）：

1. **词典形**：去装饰后逐字比对
2. **变体表**：`pipeline.build_variants` 产出的活用词干（`食べる→食べ`）
3. **反向活用**：`mine.hit_inflection` 反推 `作ろう→作る`、`読め→読む`、`甘く→甘い`、`信じ→信じる`

第 3 条是踩出来的：只做前两条时，`食べ`·`信じ`·`忘れ`·`溢れ` 这类活用形会被当成"新词"收进来
（它们确实**不逐字**存在于牌组里），但用户要的是"这个词没有"，不是"这个写法没有"。

### 6.2 候选怎么来、谁来判定

生词不是查出来的，是**减出来的**：拿已知词表在例句里做**句内最长匹配**，覆盖掉已知词，
剩下的连续片段就是候选。这个做法边界很脏，候选有三类：

| 类型 | 例子 | 谁来判断 |
|---|---|---|
| 真的生词 | `漕ぐ`、`突如`、`継承`、`貫禄` | 判定方 |
| 残缺碎片 | `満ち溢`（←満ち溢れる）、`食べ終`（←食べ終わる） | 判定方补全词典形 |
| 专有名词 / 语气词 | `河合`・`藍華`（人名）、`アクア`（作品设定） | 判定方排除 |

脚本负责**确定性的部分**（切词边界、查重、校验、写库），判定方负责**语义部分**
（判定是不是词、给词典形/读音/词性/释义/翻译）。和阶段二的分工完全一致。

⚠️ **残差法有个结构性盲区（2026-10-11 补的第二条通路）**：最长匹配会把多字词**吃掉一半** ——
`王女`→`王`+`女`、`魔道具`→`魔`+`道具`、`陛下`→`陛`+`下`（`女`/`道具`/`下` 都在已有牌组里），
剩下的单字残差被 `is_vocab_like`（含汉字要求 ≥2 字）丢掉 → **这类词永远进不了候选**。
所以 `scan` 现在把例句卡自带的 **`Word` 字段**（人工指定的重点词）也补成候选：

- 实测第 01 集（转生王女）53 张例句卡、29 张有 `Word`：残差候选 34 个 + Word 补充 **20 个** = 54 个，
  而其中 20 个是残差法**一个都没扫出来**的（`王女`/`陛下`/`魔道具`/`呪い`/`城下`/`男爵`/`学友`/`異端`/`低空`/`実戦`/`御髪`/`直訴`/`退陣`/`思案`…）。
- `Word` 里已有的词（`補充`/`無駄`/`様`）在 scan 阶段就按收录判据滤掉，不浪费判定；
  在例句里定位不到的（`化す`）也会列出来跳过 —— 否则入库时会卡在「例句中找不到该词形」。
- `--no-word-field` 可以关掉这条通路（回到纯残差口径）。

判定走**三级级联**（与阶段二同一套做法）：

| 级 | 谁做 | 命令 |
|---|---|---|
| ① | 本地模型，6 条/请求 | `mine.py gen` |
| ② | 本地模型逐条重试 | `mine.py gen --fix-failed --per-request 3` |
| ③ | 强模型（deepseek）补剩下的 | 写 `gen_mine/fix_output.json` → `mine.py merge-fix --file fix_output.json` |

判不出来的候选**按"不收"处理**（不建卡），宁可漏收也不硬凑。实测第 01 集（54 个候选）：
本地模型判出 50 个，4 个交强模型（2 收 2 不收）；另有 1 个本地判收的 `使える` 在入库前的
已知词闸门被判为「已有 `使う`」→ 改判不收。最终收录 **40 条**。

实测（227 张例句，Aria 01–04 集 + 一批新闻/纪录片字幕）：

| 指标 | 数值 |
|---|---|
| 残差候选（脚本过滤后） | **41 个** |
| 其中含汉字 / 纯假名 | 13 / 28 |
| 已被脚本剔除的已知词活用残片 | 46 个 |
| 已被脚本剔除的语法片段 | 1 个 |

从 339 个原始残差降到 41 个，靠的是四层过滤：功能词参与覆盖（`が`/`を`/`の` 不再留在残差里）、
功能词两端剥离（`お`/`すぎ`）、已知词活用形剔除、语法句型剔除。

### 6.3 五条命令（verify 可选）

```powershell
# 1. 只读扫描（不动库）。--tag 只扫某一集，不给就扫整个 2-例句 deck
& $PY "$EXE\mine.py" scan
& $PY "$EXE\mine.py" scan --tag "动画::<作品名>::<季>::第NN集" --limit 200
#   → data/vocab/mine_candidates.json（机器读）+ data/vocab/mine_report.md（人看）
#   残差 + 例句卡 Word 字段两条通路都扫（--no-word-field 关掉第二条）

# 2. 切批 + 本地模型判定（一条不落，不派子代理）
& $PY "$EXE\mine.py" split --batches 4
& $PY "$EXE\mine.py" gen                                  # 6 条/请求
& $PY "$EXE\mine.py" gen --fix-failed --per-request 3      # 没判出来的逐条再试
& $PY "$EXE\mine.py" merge-fix --file fix_output.json      # 强模型补的并回（如有）

# 3. 入库（2026-10-12 口径：直接 --commit，不先演练）。
#    产出有变动时 write 会自己先校验一遍；紧接着的 --commit 复用同一份结果
& $PY "$EXE\mine.py" write --commit
# （只有确实想先看载荷时才跑不带 --commit 的演练，它会写出 dryrun_notes.json）
& $PY "$EXE\mine.py" write

# （可选）只想先看校验报告、不入库：
& $PY "$EXE\mine.py" verify
```

**一批 ~10–15 个候选**（不是页码，是候选个数）。41 个候选 = 4 批。
（2026-10-11 起 `gen` 默认直连本地模型；只有端点不可用时才按第三节派子代理，那时「一批」就是子代理的单位。）

### 6.4 校验 + `write` 的两道闸门

**校验（`write` 在需要时自己跑，也可用 `verify` 单独跑）**逐条做四件事：
① 逐条结构规则（`check_mine.py`，与子代理自检**同一份实现**）；
② 与输入"同源"（残差必须是输出词的子串，防整条跑偏）；
③ 逐条查「是否已存在于 core6000/考级词汇」——**这是防止子代理把已知词补成词典形后蒙混过关的安全网**，
   命中的条目不会进 `verified.json`；
④ 定位来源句、并检查例句含汉字时有没有振假名。
校验通过的载荷写进 `verified.json`；`write` 发现它比全部产出文件都新就直接复用，不再重跑。

| 闸门（`write` 内部） | 检查 | 行为 |
|---|---|---|
| 二 | 新牌组里已有同名 `Word` | 跳过（幂等，重复跑不会重复建卡）|
| 三 | 回头向来源例句卡**重取** `Sentence` / `Sentence HTML` | 保证例句与振假名是来源卡的当前值，候选文件只是快照 |

> 原来的「闸门一」是在这里再查一遍"是否已存在于已有牌组里"。同一份索引、同一批词，
> 几分钟前校验时刚判过一遍，结论必然一样 —— 已删（见 §0.4）。

写完逐字回读 `AINote` / `Sentence HTML` / `Meaning` / `Transliteration` / `Word` /
`Part of Speech` / `Sentence Translation` 七个字段，按 `noteId` 定位比对（不靠数组顺序）。

### 6.5 一个必须避开的坑：`Sentence HTML` 只能用带 ruby 的那一份

例句卡有两个看着像"句子"的字段，用途完全不同：

| 字段 | 内容 | 写进生词卡的哪个字段 |
|---|---|---|
| `Sentence` | 原文，含 `<br>` 与全角空格 | `Sentence` |
| `Sentence HTML` | 原文 + `<ruby>` 振假名 | `Sentence HTML` |

第一版把 `strip_html(Sentence)` 当成了 `Sentence HTML` 存进候选，结果新卡的例句
**一行到底、一个振假名都没有**——`check_cards.py` 管不到生词卡的这个字段，所以没拦住。
现在 `scan` 分别保留两份，校验会报「例句含汉字但 Sentence HTML 没有振假名」，
`write` 还会在写库前向来源卡重取一次。

> 实测 227 张例句卡里 **220 张的 `Sentence HTML` 有振假名**，7 张没有（都是纯假名句）。

### 6.6 新牌组长什么样

`Japanese Vocabulary` 模板的背面依次渲染：读音 → 词 → `[词性]:释义` → 例句（带振假名）
→ `AINote` → Pitch Accent 链接。生词卡填的字段：

| 字段 | 来源 |
|---|---|
| `Index` | 集合内序号（接在 6000 之后）|
| `Word` / `Transliteration` / `Meaning` / `Part of Speech` | 子代理产出（词典形 / 假名读音 / 中文释义 / 中文词性）|
| `Sentence` / `Sentence HTML` | **复用来源例句卡**（不重新生成振假名）|
| `Sentence Translation` | 子代理产出的中文翻译 |
| `AINote` | 子代理产出：中文翻译 / 核心词汇 / 语法要点 /（动词变形解析）四段 |
| `Word Audio` / `Pitch Accent` | 留空（没有音频源，不影响渲染）|

标签：`素材生词::<YYYYMMDD>` ＋ `素材生词::<出处名>`。回退 = 浏览器搜 `tag:素材生词::*` 全选删除。

## 7. 阶段五：给生词卡挂音频（`mine_audio.py`）

目的：让 `0-素材生词` 的卡有声音——单词能听发音，例句能听**演员原声**。

### 7.1 两个字段分别走什么源

| 字段 | 来源 | 理由 |
|---|---|---|
| `Word Audio` | **edge-TTS**（`ja-JP-NanamiNeural`）读**假名读音** | 单词没有现成音频 |
| `Sentence Audio` | **复用来源例句卡的原声** `asbp_*.mp3` | 演员原声，语速/连读/语气真实；文件已在媒体库里，不重复占空间 |
| `Sentence Audio`（无原声时）| edge-TTS 兜底 | 个别来源卡没切出音频 |

实测 17 张里 **17 张都有原声**，TTS 兜底 0 张 → 只需新生成 17 个单词音频，
句子音频只是**引用**已有文件（`asbp_*` 在媒体库里有 924 个）。

### 7.2 为什么 Word Audio 喂读音而不是汉字词形

TTS 读裸汉字词形有同音异读风险，而且**读错了你听不出来是错的**：

- `新興` 可能读成 しんきょう（正确是 しんこう）
- `叶う` 可能读成 かない（正确是 かなう）

edge-tts 返回的 mp3 里查不到它实际读的文本（LAME 头里只有编码器元数据），
同一文本两次合成的字节也不相同，所以**无法靠比对文件来验证发音**。
而 `Transliteration`（读音）是生成阶段校验过的，直接拿它合成即可消除全部歧义。
代价只是音频听起来和词形完全一样——本来就是同一个词。

> `Word Audio` 只负责发声，**不显示文本**；卡面显示的是 `Word` 字段的词典形。
> 所以"用读音合成"不会让你看到任何奇怪的东西，也没有额外的时长成本。

### 7.3 为什么不用 `edge-tts` 这个包

`edge_tts_min.py` 是**纯标准库**实现（`socket` + `ssl` + `hashlib` + `struct`），
实现了 TTS 协议的三件事：`Sec-MS-GEC` 令牌、WebSocket 帧、SSML。

原因是本机 **pip 在工作区里解包 wheel 会被沙箱拒**（临时文件 EPERM），
装不上 `edge-tts`（它还要 aiohttp 等一串依赖）。协议本身不复杂，自己实现反倒更省事、
更好移植，也少一层依赖。

握手时要带齐这几样，**少一个就 403**（都踩过）：

| 项 | 值/做法 |
|---|---|
| `TrustedClientToken` | `6A5AA1D4EAFF4E9FB37E23D68491D6F4`（edge-tts 公开常量） |
| `Sec-MS-GEC` | `SHA256(向下取整到5分钟的Windows FILETIME + token)` 大写 hex |
| `Sec-MS-GEC-Version` | `1-143.0.3650.75`（要跟客户端版本号一致） |
| **`ConnectionId`** | 32 位无连字符 hex。**缺它直接 403**，最难查的一个 |
| `Cookie: muid=…` | 32 位大写 hex（新版 edge-tts 才加的） |

SSML 里的文本必须做 XML 转义，否则 `&`/`<`/`>` 会打断 SSML。

### 7.4 四条命令（verify 可选）

```powershell
& $PY "$EXE\mine_audio.py" plan             # 只读：每张卡将要挂什么（原声/ TTS、文件名）
& $PY "$EXE\mine_audio.py" apply            # 演练：合成 TTS 到 output/audio/，不写库
& $PY "$EXE\mine_audio.py" apply --commit   # 真写：上传媒体 + 写两个字段（写完自动回读）
& $PY "$EXE\mine_audio.py" verify           # 可选：事后单独再回读一遍（字段非空 + 文件真的在媒体库里）
& $PY "$EXE\mine_audio.py" revert --commit  # 清空两个字段（媒体文件保留，无害）
```

> `apply --commit` 结束时跑的就是 `verify` 那一份回读（`verify_rows()`），
> 所以平时不用再单独跑一次 `verify`。

**只补某一集**：`plan` / `apply` / `verify` 都支持 `--tag "素材生词::<来源>"`（不带就是整个
素材生词 deck）。换集后补音频**务必带 `--tag`**：deck 里别的集的卡若因 `Sentence` 与来源例句卡
对不上而找不到原声，`apply` 会把已有的原声 `[sound:asbp_*]` 改写成 `mine-sent-*.mp3`（TTS 兜底）。
实测平家物语第 01/02 集的 `摂政`、`仰せ` 就是这样 —— 它们的 `Sentence` 与例句卡不同（`摂政` 的
`Sentence HTML` 还被改成了「高倉天皇の摂政…」），来源匹配失败，2026-10-11 补转生王女那批音频时
带 `--tag` 才没被降级。

**命名约定**（避免与媒体库 81,418 个现有文件碰撞）：

- 单词：`mine-<词形>-<sha1前8位>.mp3`
- 句子（TTS 兜底时）：`mine-sent-<noteId>.mp3`
- 句子（原声）：直接引用例句卡的 `asbp_*.mp3`，不新建文件

**幂等**：已有正确 `[sound:...]` 的字段默认跳过；`--force` 强制重做。

### 7.5 已知边界

- **无法自动验证 TTS 发音**（见 8.2）。想确认就把 `output/audio/` 里的 mp3 播一遍再 `--commit`。
  这也是 `apply` 默认演练、并且演练阶段**也会合成音频**的原因。
- **`revert` 不删媒体文件**。删掉字段后那 17 个 `mine-*.mp3` 会变成孤儿文件（占约 200KB）。
  要清理就在 Anki 里「工具 → 检查媒体」。
- **`check_audio.py` 只能查物理合理性**（帧数、时长区间、非空、文件互不相同），
  查不了"读得对不对"。

### 7.6 修读错的单词音频（`fix_word_audio.py`）

`Word Audio` 读错，根因几乎都是 `Transliteration` 写错（2026-10-19 实测：`阻止`→しゅしょう、
`罪人`→つみと、`討つ`→うたう、`分かつ`→わかた）。TTS 无法从 mp3 反查文本（§7.2），
所以修的时候必须**字段 + 音频一起换**：只改字段 → 音频还是错的；只换 mp3 → 下次
`mine_audio.py` 又按旧读音合成。

1. **读音的机械依据 = 同卡 `Sentence HTML` 的 ruby**：`<ruby>阻止<rt>そし</rt></ruby>`；
   送假名算进读音（`分<rt>わ</rt>かつ` → わかつ）。没有该词 ruby = 没有依据，交强模型/人。
2. `Transliteration` 改成读音 → 用新读音重新 TTS → **文件名只由 `Word` 派生**，同名覆盖，
   `[sound:]` 引用不变；`Sentence Audio` 不动。
3. 写前断言旧读音（`--expect`），写后回读字段 + 媒体库；旧/新文件哈希只用来证明"换了"，
   不能证明"读对了"（edge-TTS 每次字节不同，短词常有 11232 bytes 的巧合，别拿大小判断）。
4. 同词多卡共用一个 mp3：`--word` 命中多张时用 `--nid`；同词其他卡读音不一致时先统一。

```powershell
& $PY "$TOOL\fix_word_audio.py" --word "<词>"                                    # 只读预览（打印 ruby 读音）
& $PY "$TOOL\fix_word_audio.py" --word "<词>" --reading "<ruby读音>" --expect "<当前读音>"          # 只读确认
& $PY "$TOOL\fix_word_audio.py" --word "<词>" --reading "<ruby读音>" --expect "<当前读音>" --commit # 真写
```

`<ruby读音>` / `<当前读音>` 从只读预览的输出里抄，不要猜。

脚本的守卫（纯假名、ruby 比对、同词冲突、`--commit` 必带 `--expect`）**不要用 `--force` 绕过**；
`--force` 只用于"ruby 本身确认是错的"或"同词多卡已决定统一读音"。

> 2026-10-19 的教训：当时把 `分かつ` 的 わかた 改成 わかたる（正确是 わかつ），
> 因为只凭读音直觉、没有对卡上的 ruby。现在 `fix_word_audio.py` 会拿 ruby 拦住这种改法。

---

## 8. 换一部新作品怎么办

代码里**没有任何作品名**，只有 `--tag` 这个字符串。换作品 = 换标签。

```
[ ] 1. ABS Player 看新作品，导出本集字幕卡进 Anki，确认导入后的标签
[ ] 2. 看一眼标签实际长什么样（决定下面用哪个字符串）：
       在 Anki 浏览器搜 deck:0-日本语学习::2-例句，看右侧标签栏的「动画::…」
       —— 拿不准字符串就照浏览器里显示的**原样**抄
[ ] 3. & $PY "$EXE\pipeline.py" prepare        （词表没变可跳过）
[ ] 4. & $PY "$EXE\pipeline.py" triage --query "tag:<导入时的标签>"
[ ] 5. 人工过 drop_candidates.md
[ ] 6. & $PY "$EXE\pipeline.py" apply
[ ] 7. & $PY "$EXE\pipeline.py" split --tag "动画::<新作品>::<季>::第01集" --batches N
[ ] 8. & $PY "$EXE\pipeline.py" gen → & $PY "$EXE\pipeline.py" write（先校验再入库）
[ ] 9. & $PY "$EXE\mine.py" scan --tag "动画::<新作品>::<季>::第01集"
[ ]10. & $PY "$EXE\mine.py" split → gen（→ 必要时 gen --fix-failed / merge-fix）→ write --commit
```

**标签命名完全随你**，代码只当字符串处理。唯一要求：同一集在
`split --tag` 与 `mine.py scan --tag` 里用**完全一致**的字符串。

需要注意的只有 `pipeline.py` 顶部 `CFG` 里与**收藏结构**（不是作品）相关的项：
`deck`、`vocab_decks`、`vocab_band_decks`、`vocab_tags`、`grammar_decks`、
`vocab_floor`、`drop_tag`、`pending_tag`，以及阶段四专用的
`mine_deck`、`known_vocab_scopes`、`mine_model`、`mine_tag_prefix`。
新增/改名词汇 deck 时才动它们 —— 尤其是 `known_vocab_scopes`：
**以后再有新的词汇牌组，必须加进这个列表**，否则它会变成"生词"的来源。

---

## 9. 按需补例句：core6000 的例句②（`core6000_example.py`）

### 9.1 目的与定位

**按需，不是全量补全。** 用户对自己**记不住的** `0-日本语学习::0-词汇::1-高频日语单词 6000`
（模型 `Japanese Vocabulary`，6000 张）里的卡，点名要一句**不同语境**的例句；脚本给这些卡
补上第二条例句，并把它和卡上已有的讲解合成 ①② 两段（外加新句的 edge-TTS 配音）。

- **只做点名的词。** 6000 张卡里绝大多数一直是**单例句**，这是正常状态，不要去"补齐"它。
- **不给选择器就拒绝跑**：`gen` / `tts` / `apply` 在没有目标选择器时直接打印选择器清单后退出，
  **不默认全库**；要全库必须显式 `--all`（或用 `--only SCOPE --limit N` 限定规模）。
  只有 `scan`（体检）与 `status`（看进度）能不带选择器跑。

契约（唯一接口，改接口先改它）：[core6000-example-design.md](core6000-example-design.md)；
模型侧规范（脚本只读）：`code/execution/core6000_example_prompt.md`；
用户的原始教学口径：[japanese-word-example-teaching.md](japanese-word-example-teaching.md)。
操作手册：[core6000-example-使用说明.md](core6000-example-使用说明.md)。

### 9.2 三条命令（顺序固定：gen → tts → apply）

```powershell
$CE = "$WS\code\execution\core6000_example.py"

& $PY $CE gen   --words "徹夜,適当,残り"     # 直连本地模型 → data/core6000/gen/<noteId>_out.json
& $PY $CE tts   --words "徹夜,適当,残り"     # edge-TTS → output/audio/core6000/（不碰 Anki）
& $PY $CE apply --words "徹夜,適当,残り"            # 演练：打印要写字段的前后对照 + 不写的字段清单 + AINote 预览
#   ★ 唯一的人看闸门：看一眼演练输出的前后对照 + Sentence HTML（2026-10-06 起不再要求听音频）
& $PY $CE apply --words "徹夜,適当,残り" --commit    # 真写（写前自动落 backup_<时间戳>.json）
& $PY $CE revert                            # 演练：只打印将还原什么
& $PY $CE revert --commit                   # 反悔：按 backup 逐条还原被写过的字段（媒体不删）
```

`gen` / `tts` / `apply` / `revert` 前后的**选择器必须完全一致**——`tts` 读 `gen` 的产出合成音频，
`apply` 又按同一套选择器重新挑卡，换了词就对不上了。

### 9.3 目标选择器（按优先级取第一个给出的）

| 选择器 | 含义 |
|---|---|
| `--note-ids 1621392074520,1621392074521` | 直接点名 noteId |
| `--words "徹夜,あまり"` | 比 `Word` 字段（退回 `Transliteration`），忽略大小写与空格 |
| `--from-file PATH` | 一行一个词或 noteId（`#` 注释、空行忽略）|
| `--from-weak --days N [--rating again\|hard\|both]` | **「只针对我记不住的」入口**：内部跑 `code/analysis/today_weak.py --plain --days N` 取词表（`--days` 默认 1，`--rating` 不填就用 `today_weak.py` 自己的默认）|
| `--query "<任意 Anki 查询>"` | 默认只加 deck + 模型过滤；`tag:待补例句` 这类由你写 |
| `--all` | 显式全库（≈6000 张）|
| `--only SCOPE` / `--limit N` | 范围过滤 / 最多做几张（都作用在「待做卡」上）|

`--only` 的实现默认是 **`missing-sentence`、`missing-ruby`**（契约 §5.3 的 `not-merged`
默认不参与：已有两句话的卡必须是 no-op）；`--only all` = 三项并集，可重复或逗号分隔。

### 9.4 五个字段变成什么（**只写该改的字段**）

| 字段 | 变成 | 什么时候才写 |
|---|---|---|
| `Sentence` | `原句<br><br>新句`（恰好 2 块，绝不追加第三句） | 单句的卡 |
| `Sentence HTML` | 两句的振假名（每个汉字都有 ruby），外壳沿用原卡形态（`<div>` / `<p>` / 裸 ruby） | 单句的卡；或已有 2 句但哪一句缺/坏振假名 |
| `Sentence Translation` | `原译<br><br>新译` | 单句的卡 |
| `AINote` | **沿用原卡版式与板块标签文字**，每个板块变成 `① 原句相关` + `② 新句相关`；原句部分的正文**逐字沿用卡里已有的文本**，不交给模型改写。② 的核心词表与 ① 同一行文（`<ruby>漢字<rt>かな</rt></ruby>（词性）：释义`），第一行是目标词本身、写明新句实际用的义项 | 单句的卡 |
| `Sentence Audio` | 原有 `[sound:…]` 原样保留 + `[sound:core6000-<noteId>-sentence-2.mp3]` | 单句的卡 |

**只写「真的坏了」的字段**（契约 §5.4）：渲染时顺手的空白/外壳归一化不算缺陷。
**已有 ≥2 条例句的卡只补振假名** —— 第二句是卡里既有的，其余 4 个字段没有新内容可写，
一律逐字不动（卡上原有 ①② 讲解、`<ul><li>` 排版都是原作者的版式，脚本不重排、不套 `<div><div>`）。
演练输出会明确列出「不写的字段（保持卡上现值，逐字不动）」。三句以上的卡、以及
「音频条数不对 / 译文全空 / AINote 没合并」这些别的毛病，脚本**不代笔**，报告列原因交人工。

`Word` / `Transliteration` / `Meaning` / `Part of Speech` / `Index` / 音调字段**一个字都不动**，
也不加标签、不动 deck 与 `cards.due`。已有振假名不会被模型重写（`Sentence HTML` 能按句切开就用卡里的）。

模型侧新增的教学口径（`core6000_example_prompt.md`）：**义项以卡上 `Meaning` 为准**
（故意换义项必须在 ② 的目标词那一行写明）、**读音用卡上 `Transliteration`**、
**写本族人真会说的话**（禁止为「和原句不同」硬凑不自然的搭配）、目标词挑最常用的用法/句式。
脚本在 `gen` 里对前两条各做一次便宜检查，命中记作警告
（`target_reading_mismatch` / `target_gloss_missing`，**不拦卡**）。

### 9.5 九道机械闸门（字段级）+ 一条 5b

`gen` 只跑闸门 1–5（拿到模型产出就能判，不合格时带提示重问 `--retries` 次，默认 1 次）；
`apply` 跑 6–9（渲染后才能判），**而且只查这次真的要写的字段**：

| # | 闸门 |
|---|---|
| 1 | 新句里必须出现目标词（`Word` / `Transliteration` / 汉字主干部命中其一）|
| 2 | 新句长度 6–45 字（去空白），且 ≠ 原句 |
| 3 | `new_sentence_ruby` 去掉 `<rt>` 再剥标签后与 `new_sentence` 逐字一致 |
| 4 | 新句含汉字 ⇒ 必须有 `<ruby>` 且每个 `<ruby>` 都有 `<rt>`；ruby 基底不得只含假名（敬语接头辞不包进基底）|
| 5 | `need_sentence1_ruby=true` 时 `sentence1_ruby` 必须同样合规 |
| 6 | 要写的 `Sentence` / `Sentence HTML` 渲染后恰好 2 块；要写的 `Sentence Audio` 恰好 2 个 `[sound:` |
| 7 | 要写 `AINote` 时，它必须含 `中文翻译`、`核心词汇`、`语法要点`，且含 `①` 与 `②` |
| 8 | 要写 `AINote` 时，原卡每个板块正文的前 12 字必须仍出现在新 `AINote` 里（防静默丢原文）|
| 9 | 要写的字段任何一个渲染后为空 ⇒ 拒绝 |

**另有一条闸门 5b**：卡上已有两句话、第二句却缺/坏振假名时（输入里带 `need_sentence2_ruby`），
模型交回的 `sentence2_ruby` 必须与卡上第二句逐字一致且 ruby 合规；`gen` 与 `apply` 各查一遍，
不合格就**拒绝这张卡**（绝不把模型改写过的句子写进库）。它与「这次写不写」无关，**永远照查**。

两处与契约原文的实测偏差（细节见契约 §3.3）：闸门 1/2 **只管模型新造的句子**——已有两句话的卡
里 `new_sentence` 只是把卡上第二句原样交回来，拿闸门 1 卡它属于误伤；`not-merged` 范围因为提示词
没有那四个键，会被**提前拦下**（报告里写明原因），而不是让模型瞎编 ①。

### 9.6 幂等、断点续跑与 no-op

- **already_ok**：已有合规「② + 音频」的卡重跑报 `already_ok` 跳过，不会重复追加第二句、
  不会重复写同一个 `[sound:]`；`--force` 才重做。
- **断点续跑**：每张卡的模型产出单独落 `data/core6000/gen/<noteId>_out.json`
  （闸门 1–5 通过的才算合格），中断后直接重跑 `gen` 只补没做完的；`--restart` 才整张重生成。
- **no-op 是设计**：已有两句话但没有 ①② 的卡默认不动它（见 §9.5 与契约 §5.3）。
- **修不了的卡不会被动**：3 句以上（全库 1 张）、提示词还不支持的 `not-merged`，会在报告里
  逐条列出原因。（已有两句话但第二句缺振假名**现在能修**：模型用 `sentence2_ruby` 交回同一句 +
  振假名，闸门 5b 验；不合格就拒绝这张卡。）

### 9.7 安全与回退

- `apply` **默认演练**（不写库）：打印**要写字段**的前后对照 + 「不写的字段（保持卡上现值，
  逐字不动）」+ 完整 `Sentence HTML` + `AINote` 预览。
- `apply --commit` 写库前先把每条卡**要写且真的会变**的旧值写进 `data/core6000/backup_<时间戳>.json`
  （revert 的唯一依据）；媒体上传后用 `getMediaFilesNames` 回读确认，写完逐卡回读校验：
  写过的字段必须等于写入值，**没写的字段必须仍等于写库前的现值**。
- `revert` 也要 `--commit` 才真写；它**只还原备份里那几个字段**，**媒体文件不删**（要清理就去
  Anki「工具 → 检查媒体」）。`--backup FILE` 指定某一份备份，默认取最近一份。
- 写库时不要有人在 Anki 浏览器里开着这些卡（界面不刷新，看着像没写进去）。

### 9.8 落盘

| 路径 | 内容 |
|---|---|
| `data/core6000/state.json` | 本次选择范围内每张卡的状态（句块数 / 版式 / 缺什么 / 已合规）|
| `data/core6000/plan_<日期>.json` | 本次要做的清单 + 渲染所需明细（**断点续跑清单**，按选择器回放用）|
| `data/core6000/report_<日期>.md` | 人看的报告（`scan`/`gen`/`tts`/`apply` 都会刷新它，含被拦下的卡与原因）|
| `data/core6000/word_index.json` | 词形索引缓存（`--words` / `--from-weak` 用；首次建一次，之后毫秒级）|
| `data/core6000/gen/<noteId>_in.json` | 发给模型的那张卡（追溯）|
| `data/core6000/gen/<noteId>_out.json` | 模型产出（**断点续跑的最小单位**）|
| `data/core6000/gen/<noteId>_meta.json` | usage / 耗时 / 每次尝试的闸门结论 |
| `data/core6000/metrics_<日期>.json` | token 账本 |
| `data/core6000/backup_<时间戳>.json` | `apply --commit` 前的 5 字段快照（revert 的唯一依据）|
| `output/audio/core6000/core6000-<noteId>-sentence-2.mp3` | 新句 TTS（`apply --commit` 时才上传进 Anki 媒体库）|

> **与每日讲义的关系**：`today_new.py` 把 core6000 卡的例句照 `Sentence` 字段**按句展开**进讲义
> （补过例句的词，第二天讲义的例句栏自然就是两句），不需要为它改讲义链路。
