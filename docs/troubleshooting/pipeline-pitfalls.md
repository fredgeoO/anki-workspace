# 流水线踩过的坑（pipeline pitfalls）

> 状态：active ｜ 最后整理：2026-10-20

**这是什么**：跑字幕卡流水线时真踩过的坑，以及每个坑的正确处理。**为什么存在**：这些错
大多不会报错，只会悄悄写坏卡或白跑一趟；放在操作手册里会把手册撑得很长，所以单独收在这里。
**什么时候读**：`pipeline.py gen` / `mine.py` / `mine_audio.py` 出怪结果时；开工前扫一眼更省事。
当前做法见 [../pipeline-guide.md](../pipeline-guide.md)，退场机制见 [../deprecated.md](../deprecated.md)。

## 阶段 0-5 通用

| 坑 | 症状 | 处理 |
|---|---|---|
| PowerShell 5.1 默认 gb2312 编码 | 中文查询发出去变乱码，返回 0 条 | 请求体必须 `[System.Text.Encoding]::UTF8.GetBytes($json)` |
| PS 5.1 执行策略禁止运行 `.ps1` | `UnauthorizedAccess` | 用 `Invoke-Expression (Get-Content -Raw -Encoding UTF8 <path>)`，或直接用 Python |
| AnkiConnect 的 `deleteNotes` 不接受 `confirmDeletion` | 报 unexpected keyword argument | 那是 MCP 包装参数，直连时只传 `notes` |
| 含空格的字段名搜索 | `"Sentence HTML":` 报"冒号前未找到关键字" | 冒号要一起放进引号：`"Sentence HTML:"`；查询空字段用 `AINote:`，非空用 `AINote:_*` |
| `createBackup` 动作不存在 | unsupported action | **不要改用 `exportPackage`**（它会让 Anki 退出，见本表最后几行）。依赖 Anki 自己的自动备份 `%APPDATA%\Anki2\<用户>\backups\*.colpkg` 即可 |
| 在 Anki 浏览器里开着某张卡时写字段 | 界面不刷新，看起来没写进去 | 切走再切回，或按 F5 |
| 半角/全角空格 | `あれ　もう1個は…` 用半角 `1`；有句子用全角空格 U+3000，有的用半角 U+0020 | `Sentence HTML` 必须逐字保留原空格，不能凭视觉统一 |
| `お墓` 标成 `<ruby>お墓<rt>おはか</rt></ruby>` | 敬语接头辞被包进 ruby | 应为 `お<ruby>墓<rt>はか</rt></ruby>` |
| `来` 同卡两种注音 | 审计脚本误报为不一致 | `来る`→く、`来た`→き 是活用形异读，**正确** |
| 字幕切行导致的残句 | 结尾停在 `は/が/を/に/のが/けど/って` | **不是**异常。残余可讲就正常生成并在语法要点注明主句被省略；只有文字乱码、读音无法确定时才跳过 |
| 试跑校验器把 `<rt>` 里的假名算进正文 | "逐字不一致"永远为真 | 比对口径：**先整块删 `<rt>…</rt>`，再剥其余标签** |
| 拿 `AINote` 当查重依据 | 用 `AINote:_*` 拉"已处理"的卡做参照系，`AINote` 还空着的同名例句漏检（未跑的批次、suspended 的弃用卡） | **查重只比 `Sentence` 字段**（归一化后），参照集合取本 deck/全库所有卡，不看 `AINote` 空不空 |
| `setSpecificValueOfCard` 传字符串静默失效 | 调 `keys=['due'], newValues=['13924']` 不报错、`error` 为 `null`，但值**根本没写进去**；一度被误判成"AnkiConnect 不支持重排新卡" | **数值列必须传整数**：`newValues=[13924]`。用 `flags` 这个无害字段做探针验证写通道，别用 `due` 试 |
| 片假名词的平假名变体造成误匹配 | `build_variants` 对 `KATA_ONLY` 也 `add(kata2hira(w))`，于是 `デモ↔でも`、`ナノ↔なの`、`イカ↔いか` 被当成同一个词。`でも`/`なの`/`いか` 是最高频语法词，**每集稳定复现** | 匹配用途（激活）改成**非对称**：平假名词→片假名保留（`いたずら→イタズラ` 是对的），片假名词→平假名**不做**。`pipeline.build_variants` 保持原样以免破坏回归基线；triage 那边只是判定偏宽松，无害 |
| AnkiConnect `exportPackage` 会让 Anki 直接退出 | 调 `exportPackage` 导出 `0-日本语学习` 整包时，Anki 进程消失（无窗口、8765 端口无监听），调用方一直挂着 | **别用 `exportPackage` 做备份**。Anki 自己有自动备份（`%APPDATA%\Anki2\<用户>\backups\*.colpkg`，默认每 30 分钟），足够。退出后重新启动 Anki 即可，收藏无损 |
| pip 在工作区里装包被沙箱拒 | `pip install --target <工作区> edge-tts` 报 `PermissionError: … .whl.metadata`；而同一目录下手写文件完全正常 | 不是权限问题，是 **pip 的临时文件处理**被沙箱挡下（`%TEMP%` 与工作区内都失败）。阶段五因此自带纯标准库的 TTS 客户端，不依赖 pip |
| edge-TTS WebSocket 403 | 握手返回 `HTTP/1.1 403 Forbidden`，但同一个 token 走 `voices/list` 正常 | 握手 URL **必须带 `ConnectionId`**（32 位 hex），另外 `Sec-MS-GEC-Version` 要与客户端版本一致、还要带 `Cookie: muid=…`。三样齐了才 101 |
| 阶段四 `word` 交回的是**残差**而不是词典形 | 子代理把 `引き落`、`甘く見` 原样当 `word` 交付（`reading` 却已填词典形读音）。`check_mine.py` 只查结构、查不了"这是不是一个词"；`verify` 的同源判据是**残差 ⊂ 输出词**，也照样放行 → 卡面词条成了碎片 | 人工过 `mine_report.md` / `dryrun_notes.json` 时**专门看 `word` 列**。补成词典形（`引き落とす`、`甘く見る`）本身是安全的；若补全后校验报「已存在于…」（`引き落とす` 就在 `2-考级词汇` N3 低频），说明它本来就在牌组里，改判 `include=false` 即可 —— 这正是安全网的作用 |
| 阶段四残差漏出已知词 | `引き落とし`（`引き落とす` 的连用形）没被 `scan` 的变体表枚举到，于是 `引き落` 作为"生词"残差漏进候选 | `conjugation_variants` 的 `_CONJ_TAILS` 只枚举 `〜ます/た/て` 等**带尾缀**的形式，裸连用形（`〜し`）覆盖不到。不要试图枚举穷尽；靠校验阶段在**补全词典形之后**回头查一次"已在已有牌组里"即可（`write` 不再重查同一件事，见 §0.4）|
| 换集时上一集的 `output_NN.json` 会残留 | `split` 只重写本集的 `input_NN` 与 `manifest`，**不清理**多余的旧 `output_NN`。本集批次比上一集少时就会留下孤儿（本次生词 3 批 vs 上次 4 批 → `output_04.json` 留下；阶段二为补做 2 张遗留卡追加过第 06 批 → 阶段二目录也有孤儿） | 换集后先看一眼 `data/pipeline/gen/` 与 `data/vocab/gen_mine/` 里 `output_*.json` 的批号是否 ≤ 本集 `manifest` 的批数，多出来的删掉（它们本来就写着"可随时删"）；`verify` 是按 manifest 读文件的，孤儿不会**静默**混入，但会在下一集同批号时顶替真产出 |
| 生成侧把两个字段混在一个 `hard` 列表里判 | `Sentence HTML` 漏标一个汉字（`<ruby>様<rt>よう</rt></ruby>子`）→ 整张卡判失败 → **合格的 AINote 被一起丢掉** → 卡进 `needs_llm.json` 等强模型；带问题重问两轮也修不好（模型上一轮就是这么标的） | `check_cards.split_hard()` 按字段拆开判：`AINote` 侧不合格才重问，`Sentence HTML` 侧交给 `ruby_engine repair`。`gen`/`merge-fix` 都走这一份口径（2026-10-11《七大罪》E01 实测） |
| `ruby check` 把**送假名词干**误报成待复核 | `見習 卡里 みなら，sudachi みならい`、`気持 きも vs きもち`、`間違 まちが vs まい`……每集稳定十几处；`ruby_engine apply --mode fix` 不会自动改（Sudachi 不是权威源），但人照它改会把 `見習(みなら)い` 改成 `見習(みならい)い`（读成 みならいい） | 根因是 `_sudachi_reading` 对**裸词干**取的是别的词条的读音。改成先在句子里找「基底 + 纯假名尾巴」的 token，按尾巴长度从读音里切掉尾巴（送假名的读音就是它自己）。2026-10-11 全例句 deck 待复核 66 → 39，读音冲突仍为 0 |

---

## 按需补例句②（core6000）

| 坑 | 处理 |
|---|---|
| 想"顺手把 6000 张都补齐" | **不要**。只做用户点名的词；全量是显式 `--all` 的另一件事 |
| 模型把新句造成原句的近义改写（只换主语/时间/地点），甚至照用原句的句型 | 规范里明确要求换语境/语体/句型；**没有机械闸门查得出换皮**，`gen` 也不会为它重问，只能靠人看演练输出（`contrast` 里自己写「两者都用了同一个句型」就是信号）|
| 已有两句话的卡被整篇重渲染（已有的 ①② 讲解变冗余、`<ul><li>` 被换成 `<p>`、套出 `<div><div>`）| 已经修掉：这类卡**只写 `Sentence HTML`**，其余 4 个字段逐字不动（契约 §5.4）|
| 模型换了义项却不说明，或给目标词注了第二种读音 | 提示词要求「义项以卡上 `Meaning` 为准、换义项必须在 ② 写明」「读音用卡上 `Transliteration`」；`gen` 只给 `target_reading_mismatch` / `target_gloss_missing` 两条**警告**（不拦卡），演练时要对着卡上 `Meaning`/`Transliteration` 看 ② 的目标词那一行 |
| 原卡板块标签带振假名（`<b>中文<ruby>翻译<rt>ほんやく</rt></ruby></b>`）或写成 `<p><b>标签</b>：正文</p>` | 比对板块名要**先删 `<rt>` 再剥标签**，且标记只扫 `<b>/<strong>/<h3>/<h4>`（不重叠地扫 `<p>…</p>` 会把里面的 `<b>` 一起吃掉，整块静默丢失）。认不出的板块整块保留 |
| `Sentence HTML` 的块分隔不一定是 `<br><br>` | 依次试 `<br><br>` / `</p><p>` / 单个 `<br>`，取块数正好等于原句数的那种；都不等就走模型值 |
| 模型把 `お`/`ご` 包进 ruby 基底（`お墓`→`おはか`） | 闸门 4 会拦：基底不得只含假名，敬语接头辞留在外面（`お<ruby>墓<rt>はか</rt></ruby>`）|
| 多汉字词被逐字标 ruby（`<ruby>場<rt>ば</rt></ruby><ruby>所<rt>しょ</rt></ruby>`） | 闸门查不出来（每个 `<ruby>` 都合规），但不符合本 deck「一词一 ruby」的风格 —— 只能人看 `Sentence HTML` |
| 怕 TTS 读错就不敢 `--commit` | TTS 读错**无法靠比对文件查出来**（同一文本两次合成本来就不同字节）。**2026-10-06 起不再要求听音频确认**：演练输出没问题就直接 `--commit`，事后发现读错用 `revert --commit` 回退 |
| 在 Anki 浏览器里开着这些卡写字段 | 界面不刷新，看似没写进去。切走再切回或 F5 |
| 一次塞多张卡给模型 | `--per-batch` 实际只接受 1（`>1` 直接用一段说明拒绝）：契约的响应按单张卡组织，塞多张只会漏卡/串卡。要省时间请用选择器缩小范围 |
