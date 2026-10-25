# ImmersionKit 抓例句卡 / 素材生词卡 使用说明

> 状态：active ｜ 最后核实：2026-10-17（标签改为 `动画::中文名` / 裸 `素材生词`；
> 分批跑改带 `--no-order`，due 交给插件 `jiten_reorder`）

> 一句话：给一个日语词表，自动从 [ImmersionKit](https://www.immersionkit.com/dictionary)
> 抓「对白例句 + 剧照 + 原声 + 振假名」，用本地模型补讲解，写成 Anki 里的
> **例句卡**（`Basic` / `2-例句`）与**素材生词卡**（`Japanese Vocabulary` / `0-素材生词`）。
>
> 入口：`python code\cli.py immersion fetch | gen | merge | write | verify`
> 实现：`code/execution/immersionkit.py`（流程）+ `code/common/immersion_api.py`（接口与纯函数）

---

## 1. 为什么用它（与现有流水线的关系）

现有例句卡来自「字幕 + 视频」那一条链（`episode.py` / `filter_subtitle.py`）。
ImmersionKit 免费提供了同两样东西——**原声**与**剧照**——外加**母语级振假名**和英文译文，
而且可以**按词检索**。于是「我手上有一批想学的词」这件事，不必先有作品字幕才能成卡。

两条链是**并存**的，不互相替代：

| | 每集字幕流水线 | ImmersionKit |
| --- | --- | --- |
| 起点 | 一集字幕（SRT） | 一个词表 |
| 收词口径 | 该集里所有未知词（`mine.py` 判定） | 你给的词，剔除 core6000/考级后按 Jiten 词频排 |
| 媒体 | 需要自己抽帧/切音 | 站上直接给图与音频 URL |
| 落点 | `2-例句` / `0-素材生词` | 同样的两个牌组、同样的模型 |

---

## 2. 四个子命令（默认全程演练，`--commit` 才写库）

```powershell
$PY = "python"
$WS = "<工作区根>"

# 0. 词表（一行一个词，UTF-8）：data\immersion\words.txt
& $PY "$WS\code\cli.py" immersion fetch                     # 选词 + 选句 → data\immersion\fetch_*.json + 报告
& $PY "$WS\code\cli.py" immersion gen                       # 本地模型出 读音/词性/释义/翻译/讲解
& $PY "$WS\code\cli.py" immersion write --to both           # 演练：只打印将要写的卡与媒体
& $PY "$WS\code\cli.py" immersion write --to both --commit  # 真写（含媒体上传）
& $PY "$WS\code\cli.py" immersion verify                    # 只读校验：字段/振假名/媒体
```

后一步默认读 `data\immersion\latest.json`（每步都会刷新它）；要指定别的计划用 `--in <路径>`。

### 常用开关

| 开关 | 作用 |
| --- | --- |
| `--words-file <路径>` | 词表位置（默认 `data\immersion\words.txt`） |
| `--n 1..3` | 每个词最多几条例句（默认 1）；词表里 `词<TAB>条数` 可按词覆盖 |
| `--category anime,drama` | 类别白名单（默认 anime,drama；`games` 是西语游戏的日配，默认排除） |
| `--deck <slug,slug>` | 只取这些作品的句子（slug 见候选报告里的「出处」列） |
| `--min-len` / `--max-len` | 句长上下限（默认 3–40 字） |
| `--speaker-max 0.6` | 括号内（`(メリル)` 这类说话人标记）占比上限 |
| `--delay 0.5` / `--refresh` | 真上网的间隔 / 忽略缓存重抓 |
| `--workers 4` | **`fetch` 并发线程数**（默认 4；`1` = 老串行行为）。实测 8 个词：串行 45.4 s → 4 线程 7.1 s；缓存命中的词不占线程 |
| `--limit N` | 只处理前 N 个词（试跑；`fetch`/`gen` 都有） |
| `fetch --keep-known` | **反过来的选词口径**：只抓 core6000/考级里**已有**的词（给例句牌组补对白例句用）。配 `write --to example` 只出例句卡，不建素材生词卡 |
| `write --to example` | 只写例句卡；`--to mined` 只写素材卡；默认 `both` |
| `prewarm --in <计划>` | **只把媒体先抓进 `collection.media`**（不建卡、不调模型）—— 用来跟 `gen` 并行，或先把图/音备好 |
| `write --keep-media` | 媒体先下载到 `data\immersion\media\` 再上传（便于复查） |
| `--no-ainote` | 不调本地模型（`gen` 或 `write`）：`AINote` 与 `Sentence HTML` **一起留空** |

### 用云端模型生成（2026-10-23 起）

`immersion gen` 直连本地模型；要把「卡片内容」交给**非本地模型**（子代理 / 别的 API），走这条：

```powershell
& $PY "$WS\code\cli.py" immersion fetch --words-file data\immersion\words_20k30k.txt
#   → 子代理按 docs/mine-agent-instruction.md 的字段规范写 {entries:[…]}
& $PY "$WS\code\cli.py" immersion merge --file data\immersion\gen_20k30k\out.json
& $PY "$WS\code\cli.py" immersion write --to mined --commit
```

`merge` **不调任何模型**，只做「吸收 + `check_mine` 校验 + 并回计划」；`include=false` 的条目
记成 `gen=skip`，`write` 不会建卡。校验规则只有一份（`code/common/check_mine.py`），
与 `mine.py` 完全同口径。

---

## 3. 词表格式

`data\immersion\words.txt`，UTF-8，一行一个词：

```
# 注释行
嫌い
名乗る	2      ← 这个词要 2 条例句（覆盖 --n）
```

选词口径（`fetch` 阶段自动执行，报告里逐条给出理由）：

1. 剔掉**已在 core6000 / 考级词汇**里的词 —— 判据是 `pipeline.rebuild_known_index()`
   （与 `mine.py` 同一套归一化，11,728 词形 / 229,007 写法），**不另立口径**；
2. 剔掉两个目标牌组里**已有 `Word`** 的词；
3. 其余的按 **`JitenAnimeRank` 升序**抓（词表里没有的词写 `999999`，排最后）。

`--keep-known` 把第 1 条反过来（**只留** core6000/考级 里已有的词，第 2 条照旧）——
用于给例句牌组补「已经在学的词」的对白例句，练听力用。这类词**本来就有词汇卡**，
所以写库时应当配 `--to example`，不要再生成素材生词卡。

> 词表怎么来：`code/oneshot/immersion_jiten_wordlist.py` 从
> `data/freq/jiten_freq_Anime.csv` 取 `Rank ≤ --max-rank` 的条目，套上面同一套口径，
> 再剔三类噪声（句片段/带标点/超长、纯语法胶水、假名写法但正字已收），
> 输出 `words.txt` + `candidates*.tsv` + `docs/reports/ImmersionKit词表-*.md`。
> 常用两遍：`--words-only`（新词，只做单词）与 `--known-only --words-only`（补例句）。

---

## 4. 选句规则（`fetch`）

服务端已按 `sort=sentence_length:asc` 给序 = **短句优先**；本地只做**否决式**过滤：

* 句子或译文为空、含 `<br>`（多说话人拼接 / 译文串了别的字幕）→ 弃；
* **命中判定**：`matched_indexes` 精确切片 → `word_list` 整词 → 词被拆成多个 token 时拼回来
  → 最后才退回原句子串（drama 的 `matched_indexes` 常常是空的，不能只信它）；
* 类别 / 作品白名单（客户端再校验一次，因为**非法 category 会被服务端静默忽略**）；
* 句长 `--min-len ~ --max-len`；括号内内容占比 ≤ `--speaker-max`；
* 同一个 `example.id` 跨词只用一个（不会两个词各写一张同句卡）。

在此之上还有三条**挑优**规则（`immersionkit.choose_picks`，2026-10-15 实测加的）：

* **振假名优先**：一次多取 8 条候选，优先挑 `furigana_to_html` 对得上的 ——
  注音串把 `我々[われわれ]` 整词标成一格时转换会失败，原来那条卡就只剩原句；
* **够长优先**：头一条短于 8 字时重扫一遍（`min_len=8`），换成「够用的最短句」——
  服务端短句优先，`--min-len 3` 拦不住 `…あっ` / `いいや` / `…めろ` 这类碎片；
* **独立命中优先**：优先目标词**作为独立词元**出现的句子（`is_token_hit`）——
  否则单假名词会被子串兜底带偏（`め` 命中「ごめんください」、`え` 命中「よく冷えてるよ」）。

清洗：去掉 `‪`/`‬` 这类 bidi 控制符、NBSP→空格、折叠连续半角空格；
**全角空格（U+3000）保留**（站上的词分隔符，现有例句卡也一直保留）。

---

## 5. 振假名 → `Sentence HTML`

站上给的是 `漢字[よみ]` 串（`私[わたし]　嫌[きら]いよ`）。转换时**读音取自它、字符与空白取自
`sentence`**（注音串自己会插空格：`大っ嫌いです` 的注音是 `大[だい]っ 嫌[きら]いです`）。
结果与 `sentence` **逐字相同** —— 这正是 `check_cards.py` 的硬判据（它先删 `<rt>…</rt>` 再剥标签比对）。

真实数据里会遇到的形态（都有单测，见 `code\tests\test_immersionkit.py`）：

| 输入 | 输出 | 说明 |
| --- | --- | --- |
| `嫌[きら]い` | `<ruby>嫌<rt>きら</rt></ruby>い` | 常规 |
| `痛[]い` | `痛い` | 空读音 → 不注音（该卡 `Sentence HTML` 留空，见下） |
| `～[から]` | `～` | 符号基 → 读音丢掉 |
| `お金[おかね]` | `<ruby>お金<rt>おかね</rt></ruby>` | 读音含前导假名 → 并进基 |
| `この町[まち]` | `この<ruby>町<rt>まち</rt></ruby>` | 读音不含前导假名 → 前导留纯文本 |
| `食べ物[たべもの]` | `<ruby>食べ<rt>たべ</rt></ruby><ruby>物<rt>もの</rt></ruby>` | 中间假名逐字对上 |
| `私は学生[がくせい]` | `私は<ruby>学生<rt>がくせい</rt></ruby>` | 长基对不上就缩短（防错读音） |

**宁缺勿错**：整句对不上、或句中有汉字拿不到读音（如 `痛[]い`）→ 该卡 `Sentence HTML` 留空，
并在 `fetch` 报告里标出原因（`check_cards.py` 把「有汉字没 ruby」当硬错，留空是唯一安全解）。
留空时 `AINote` 也**一起留空**（仓库约定：两者同空同有，否则 `verify` 判硬错）；
`--no-ainote` 与「模型没给出 AINote」同理。

---

## 6. 落点与字段（**不是**网站原生卡片）

| | 例句卡 | 素材生词卡 |
| --- | --- | --- |
| 牌组 | `0-日本语学习::2-例句` | `0-日本语学习::0-词汇::0-素材生词` |
| 模型 | `Basic`（该牌组现有 467 张全是它） | `Japanese Vocabulary`（与 core6000 同模板） |
| 字段 | Sentence / Word / Sentence HTML / AINote / **Image** / **Sentence Audio** / Source / URL | Index / JitenAnimeRank / Word / Sentence / Sentence HTML / Transliteration / Meaning / Part of Speech / AINote / Sentence Translation / Sentence Audio / Word Audio / Pitch Accent URL / Pitch Accent |

* `Image`：`<img src="ik_<example id>.jpg" width="700">`（站上的剧照）；
* `Sentence Audio`：`[sound:ik_<example id>.mp3]`（**原声**，不是 TTS）；
* 素材卡的 `Meaning` 末尾也带一次配图（现有素材卡就有这个先例）；
* `Source` = `ImmersionKit · <作品 slug> · <类别> · <example id>`；`URL` = 该词的词典页；
* 标签（**2026-10-17 口径**，见 [evidence](evidence/immersion-tag-retag-2026-10-17.md)）：
  例句卡 `动画::<中文名>`（drama → `日剧::<中文名>`，整部一个标签，不带季/集）；
  素材卡只挂裸 `素材生词`。
  中文名查 `data/evidence/immersion_retag/slug_map.yaml`；表里没有的作品先落
  `动画::<英文 slug>` 并记进 `data/immersion/unmapped_slugs.txt`，补表后一次 `replaceTags` 改名
  （旧标签 `沉浸式::<类别>::<slug>` / `素材生词::<日期>` + `素材生词::IK-<slug>` 已全库废弃，别再写回去）；
* `Word Audio` / `Pitch Accent` 默认**留空**（站上 `dictionary_entries.sound` 实测为空，
  仓库也没有音调数据源）；
* 库里那个空的 `ImmersionKitCard`（0 张）**不碰**。

---

## 7. 媒体

* 文件名 `ik_<example id>.jpg` / `ik_<example id>.mp3` —— id 全局唯一，天然去重、可重跑覆盖；
* 顺序是**先落地媒体、再建卡**（字段里要引用 `[sound:…]` / `<img src="…">`）；
* 默认走 AnkiConnect 的 `url=` 直传（实测可用）；`--keep-media` 则由本脚本带浏览器 UA
  下载到 `data\immersion\media\` 再上传（CDN 拒绝默认 UA 时用这条）；
* 媒体落地失败的那些卡**整张不写**（宁可没有卡，也不要无声无图的卡）；
* **单个文件失败不再拖垮整批**（2026-10-15 改）：站上的 URL 有脏数据（尾部多一个 `%3E`）
  或 CDN 上文件已不在（403），以前 `ensure_media` 直接抛错 → 整块几百条笔记全丢。
  现在单文件失败只记为 `failed`，**只跳过引用它的那张卡**（连同该词的素材卡），
  失败原因打在日志里；其余卡照写。

---

## 8. 去重与幂等（重要）

`addNotes` 的查重**只看首字段**：例句卡是 `Sentence`（能挡住重复），
素材卡却是每次都重新分配的 `Index`（**挡不住**）。因此：

* `fetch` 阶段：剔掉目标牌组里已有 `Word` 的词；
* `write` 阶段：再按 `(牌组, 归一化 Word, 归一化 Sentence)` 查一遍身份，
  已有的直接跳过（打印「牌组里已有同词同句，跳过 N 条」）。

复跑同一份计划应当 **0 新增**；`--commit` 后脚本会**逐字段回读**核对，不一致会报出来。
（2026-10-15 开发时实测过这个坑：复跑让 3 张素材卡带着新 Index 又写了一遍，已加闸门并清理。）

---

## 9. 校验

```powershell
& $PY "$WS\code\cli.py" immersion verify                       # 本脚本的闸门（字段/振假名/媒体）
& $PY "$WS\code\common\check_cards.py" --anki 'tag:动画::* or tag:日剧::*'   # 仓库自带的例句卡硬闸门
& $PY "$WS\code\common\textio.py" audit --strict               # 文本 I/O 自审
& $PY "$WS\code\common\anki_api.py" audit                      # Anki 访问自审（阻塞项必须为 0）
& $PY "$WS\code\tests\test_immersionkit.py"                    # 纯函数回归（不连网、不碰 Anki）
```

`verify` 检查：模型对不对、每个写入字段与库里是否一致、`AINote` 与 `Sentence HTML` 是否同空同有、
`Sentence HTML` 里有没有漏标的汉字、与 `Sentence` 是否逐字一致、引用的媒体是否真在媒体库里。

### 修 `AINote` 结构（`immersion_fix_ainote.py`）

```powershell
& $PY "$WS\code\oneshot\immersion_fix_ainote.py" --deck example            # 演练（默认不写库）
& $PY "$WS\code\oneshot\immersion_fix_ainote.py" --deck mined --commit
# 只修某一批：吃「model<TAB>noteId<TAB>问题」清单，避免被同牌组里修不了的旧账拦住
& $PY "$WS\code\oneshot\immersion_fix_ainote.py" --deck mined --nids data\immersion\qc_hard_nids.txt --commit --allow-partial
```

默认策略是**原子**的：同一个牌组里只要有一张修不了，就一张都不写（避免半修）。跑大批时用 `--nids`
把范围缩到本批，再加 `--allow-partial` 只写能修的、把修不了的列出来（那类要重问模型重生成）。

---

## 10. ImmersionKit 接口备忘（实测，2026-10）

* 数据 API：`https://apiv2.immersionkit.com`（FastAPI，`/openapi.json` 可读）
* `GET /search?q=<词>` —— **无需登录**即 200。默认 UA（`Python-urllib/3.x`）会被挡成 **403**，
  必须带浏览器 UA。
* 参数：`q`(必需)、`category`、`locale`(默认 `detect`；传 `eng` → 0 条)、
  `sort`(默认 `sentence_length:asc`，非法值 400)、`exactMatch`、`showUrlInMedia`、
  `jlpt`、`wk`、`limit`、`offset`
  * `limit` **被服务端忽略**（一律客户端切片）；`offset` 有效但会连带改变 `category_count`
    （**计数不可信**，只当参考）；
  * `index` 传任何值都 **400**，别传；
  * 非法 `category`（`news`/`zzz`）会**静默变成不筛选** → 客户端必须再校验一次；
  * `jlpt=N` 与 `wk=N` 实测等价（`wk1==jlpt1`、`wk30==jlpt5`），语义未完全确定，只作可选过滤。
* `showUrlInMedia=true` 时 `image`/`sound` 直接是 CDN 全 URL，可直接 GET：
  `https://us-southeast-1.linodeobjects.com/immersionkit/media/{category}/{Deck Title}/media/{filename}`
* 别用的端点：`/download_media?path=`（200 + S3 错误 XML，路径口径不对）、
  `/sentences?ids=`（500）、`/download_sentence`（只出 apkg）；
  `/stats`、`/tasks` 需要 `authorization` 头（401）。
* `exactMatch=true` 时 `dictionary_entries` 收敛到 1 条 JMdict 词条
  （`headword` / `reading` / `tags` / `glossary_list` / `sound`）—— 用作释义与词性的兜底。
* 每条 example：`id`(`{category}_{deck}_{9位}`)、`sentence`、`sentence_with_furigana`、
  `word_list`、`translation`、`image`、`sound`、`matched_indexes`、`title`。
* 响应很大（一个词 200+ 条、60KB+）→ 一律落磁盘缓存 `data\immersion\cache\`，重跑零请求。

### 关于登录

整条流水线**不需要登录**（搜索/例句/媒体都是公开的），所以**不要把口令写进任何脚本、配置或文档**。
将来若真要调 `/stats` 之类需要鉴权的端点，从环境变量读（例如 `IMMERSION_KIT_AUTH`），不要落库。

---

## 11. 产物一览（`data\immersion\`）

| 文件 | 内容 |
| --- | --- |
| `words.txt` | 输入词表 |
| `fetch_<时间戳>.json` / `latest.json` | 计划：入选词、每词的候选句、逐条取舍理由、媒体 URL |
| `plan_<时间戳>.json` | `gen` 之后的计划（含读音/词性/释义/翻译/讲解） |
| `plan_write_<时间戳>.json` | 演练时的完整载荷（写库前肉眼确认用） |
| `written_<时间戳>.json` | 真写之后的 noteId / 字段 / 标签明细（`verify` 的输入） |
| `report_fetch_*.md` / `report_verify_*.md` | 人选报告 / 校验报告 |
| `cache/` | 接口响应缓存（一个 URL 一个文件） |
| `media/` | `--keep-media` 时的本地媒体副本 |
| `words_known.txt` | `--keep-known` 用的词表（core6000/考级已有、要补对白例句的词） |
| `candidates*.tsv` | 词表生成器的逐条判定（rank/词/读音/词性/留否/原因） |
| `chunks/` | 分批跑的每块小词表（`<词表名>_chunk_NNN.txt`） |
| `batch_progress*.json` | 分批跑进度（每块状态/耗时/卡数/校验结果，断了重跑会跳过已完成块） |
| `batch_run*.log` | 分批跑的完整日志 |

### 分批跑（词多的时候）

`fetch` **中途不落盘**，只在整轮跑完后写一次计划 —— 上千个词要跑小时级，断了全丢。
所以大批量用 `code/oneshot/immersion_batch.py`：把词表切块（默认 150 词），
逐块 `fetch → gen → write --commit → verify`，进度写各自的
`batch_progress*.json`，可断点续跑（**一批一个进度文件**，共用会让新词表误判成「已完成」）。

```powershell
# 一句一个词表的口径；断点续跑＝重跑同一条命令（已完成的块自动跳过）
& $PY code\oneshot\immersion_batch.py                                    # 默认 words.txt，写两个牌组
& $PY code\oneshot\immersion_batch.py --words-file data\immersion\words_known.txt `
      --keep-known --to example --progress data\immersion\batch_progress_known.json
# 生产跑法：--pipeline（第 N+1 块 fetch 与第 N 块 gen/write 并行，实测约 7–15 分钟/块）
& $PY code\oneshot\immersion_batch.py --words-file data\immersion\words_10k20k.txt `
      --pipeline --progress data\immersion\batch_progress_10k20k.json
```

* 中途干净停：建一个 `data\immersion\STOP` 文件，驱动会在块之间停下（删掉即续跑）。
* `write` 一律带 `--no-order`：本机 AnkiConnect **写不了 `due`**
  （`setSpecificValueOfCard` 把 `due/type/queue` 列为 protected），
  新素材卡的位置由 Anki 插件 `jiten_reorder` 在 Anki 进程内按 `JitenAnimeRank` 排
  （见 [ADR](decisions/2026-10-jitenanimerank仅作注解.md)）。

`code/oneshot/immersion_phase_b.py` 是守护进程：盯着 A 阶段的进度文件，A 跑完自动接 B。

> ⚠ **两个批次不能同时跑**：`fetch`/`gen`/`write` 靠 `data\immersion\latest.json` 串起来，
> 并发会互相踩计划文件。要串行（守护进程就是干这个的）。

#### 调度开关（别跟复习抢 Anki）

| 开关 | 作用 |
| --- | --- |
| `--anki-wait-minutes 120` | 每块开跑前先 `AK.health()`；Anki 没开就轮询等待，**超时才干净停下**（exit 3），不会把 300 条笔记全判成失败 |
| `--pause-window HH:MM-HH:MM` | 暂停窗口，可重复：落在窗口里只睡 60 秒轮询、**完全不碰 Anki**；距窗口开始不足「一块的估值时长」就**不开新块**（所以不会跨进学习时段） |
| `--min-headroom-minutes 0` | 在历史估值之外再要求的余量（0＝只用估值） |
| `--stop-file data\immersion\STOP` | 建这个空文件 → 块与块之间干净停下（exit 5）；删掉重跑即续 |
| `--only N` / `--from N` / `--redo` | 调试：只跑第 N 块 / 从第 N 块起 / 忽略进度重跑 |
| `--pipeline` | **流水线跑法**：第 N+1 块的 `fetch` 与第 N 块的 `gen`+`write` 并行；块内「预下媒体」与「gen」也并行（下载不再串着等） |

#### `--pipeline`：下载与生成并行

用户 2026-10-16 的要求：「下载音频/anki 卡牌的任务可以和卡片生成任务并列运行，
卡牌的下载提前一个块运行，AI 生成注解可以处理之前下载的组块」。实现成两端：

```
生产端（一个线程）    fetch(N+1) ──────────────► fetch(N+2) ──► …
消费端（主线程）              prewarm(N) ∥ gen(N) → write(N) → verify(N)
```

* **块间**：`fetch` 是网络 + 缓存（不占 GPU），`gen` 吃本地模型（占 GPU）→ 两者重叠；
* **块内**：`prewarm`（CDN 下 300 个图/音，实测 ~8 分钟）与 `gen`（本地模型，~6–11 分钟）
  同时跑 → 这一段从「两段相加」变成「取较大者」；随后 `write` 里媒体全部命中 `cached`，
  只剩 `addNotes`（~1 分钟）；
* **不与 `latest.json` 抢道**：消费端一律 `--in <明确路径>`；`fetch_*.json` 只有生产端写，
  `plan_*.json` / `written_*.json` 只有消费端写，所以 `newest()` 探到的必是自己那一份；
* 实测（B 阶段 150 词/块）：串行块 14–25 分钟 → 流水线约 **9–11 分钟/块**。

> 日志想实时看就设 `$env:PYTHONUNBUFFERED='1'`：python 的 stdout 接到管道是块缓冲，
> 不设的话日志会比真实进度**慢好几千字节**（本次就因此误判过「卡住了」）。

一块要多久由历史记录估（`est_chunk_minutes` = `sum(t_total)/sum(words)`；B 阶段实测
**22.7 分钟/块（150 词）**）。**`t_total` 的单位是秒** —— 曾把它当分钟，估出 1,359 分钟/块，
于是「余量永远不够」一块都不开（2026-10-16 修）。块「瞬时失败」（<30 秒）且是首次尝试时，
不占用后面的块，等 Anki 回来重试本块一次。

> **卡顿的根因不是制卡**：Anki 背后用 3D 渲染，与本地模型抢 GPU，复习时才卡。
> 把 Anki 调成 **software 渲染模式**即可，不必限制制卡时间；确实要避让再用 `--pause-window`。

---

## 12. 排错

| 现象 | 处理 |
| --- | --- |
| `GET … 失败（HTTP 403 …）` | 请求没带浏览器 UA（本脚本已带）；确认网络/代理 |
| 某词「没有可用例句（共 N 条）」 | 放宽 `--max-len`、加入 `games`，或换词；报告里有该词的总条数 |
| 某卡 `Sentence HTML` 留空 | 振假名对不上或有未注音汉字（报告里写了原因）。`--no-ainote` 时属于**预期行为** |
| 「牌组里已有同词同句，跳过 N 条」 | 正常幂等提示，不是错误 |
| 媒体 `missing` | 用 `--keep-media` 重试（CDN 拒绝默认 UA 时走本地下载再上传） |
| 媒体 `failed`（`… download failed with return code 403`） | 站上 URL 脏（尾部 `%3E`）或 CDN 文件已不在 —— 只跳过那几张卡，不需要处理 |
| `Index` 撞车风险 | 已按「模型内最大序号 + 1」分配（见 `mine.py:1350` 的说明），不要改回 `count()+1` |
| Anki 复习时卡顿 | Anki 的 3D 渲染与本地模型抢 GPU —— 调成 **software 渲染模式**，不是制卡引起的；要避让用 `--pause-window` |
| 分批跑一块都不开、日志写「余量不足」 | `est_chunk_minutes` 的估值口径（历史 `t_total` 是**秒**）；确认暂停窗口没有短过一块时长 |
| 分批跑卡住不动 | 看日志最后一行是不是「AnkiConnect 不可用…等 30 秒」—— Anki 被关了；`--anki-wait-minutes` 到点会自己停 |
