# ainote_enrich 使用说明：加强某张卡的 AINote 讲解（含「语感」）

> 状态：active ｜ 最后核实：2026-10-19
> 脚本：`code/execution/ainote_enrich.py`（统一入口 `python code/cli.py ainote …`）
> 适用：Anki 模型 `Japanese Vocabulary` 的词汇卡（core6000、素材生词都可以）

## 一、这是什么

用户的高频需求：「这张卡的讲解太薄，帮我把 AINote 讲透，再加一段语感」。
以前每次要在对话里手写 HTML；现在一条命令跑完：

```
本地模型生成 6 节  →  机械闸门  →  （人看一眼）→  备份旧值  →  只写 AINote
```

**只写 `AINote` 一个字段**。Word / Sentence / Sentence HTML / Sentence Translation /
音频 / 标签 / deck / due 一律不动。这不是修卡，是改教学文案。

## 二、命令

```powershell
$WS = "<工作区根>"
$PY = "python"
$AE = "$WS\code\execution\ainote_enrich.py"

& $PY $AE show   --id 1792084330990          # 只看卡上现值（只读）
& $PY $AE gen    --id 1792084330990          # 生成 5 节 → data\ainote\gen\<noteId>_out.json
& $PY $AE apply  --id 1792084330990          # 演练：旧/新 AINote 全文对照
& $PY $AE apply  --id 1792084330990 --commit # 真写（写前备份旧 AINote）
& $PY $AE enrich --word 分際 --commit        # gen（缺产出才跑）+ apply 一条命令
& $PY $AE revert --commit                    # 按最近一份备份还原
& $PY $AE revert --commit --backup <路径>    # 指定备份
```

也可以走统一入口：`& $PY "$WS\code\cli.py" ainote enrich --word 分際 --commit`。

### 选卡（至少给一个）

| 参数 | 含义 |
|---|---|
| `--id 1792084330990` | noteId；可逗号分隔或重复 |
| `--index 6827` | 卡上的 `Index` 字段（精确） |
| `--word 分際` | `Word` 字段**精确**匹配（Anki 的 `Word:` 会带回近似词，脚本会再过滤） |
| `--query 'tag:素材生词'` | Anki 搜索语法；自动限定 `Japanese Vocabulary` 模型 |

## 三、写进 AINote 的 6 节

```
1. 中文翻译          ← 直接取卡的 Sentence Translation，模型不参与（原句信息不丢）
2. 核心词汇          ← 目标词读音/词性/本义/引申/搭配 + 近义词辨析 + 句中其他实词
3. 语法要点          ← 助词、句型、接续、褒贬色彩
4. 动词变形解析      ← 原形 → 活用形；没有变形就明说
5. 语境与表达风格    ← 谁对谁说、场合、礼貌度、书面/口语
6. 语感              ← 语域、说话人姿态、褒贬、中文对应说法、近义词对比、可操作判断
```

「语感」是这条命令的重点。好的语感不是「这个词有轻蔑的语气」这种空话，而是：

- 语域：粗俗 / 随意 / 中性 / 正式 / 书面
- 说话人姿态：轻蔑、居高临下、自嘲、亲昵、客观
- 中文对应：「你算老几」「就凭你这身份」
- 可操作判断：**能不能对上司说**；换成近义词会变成什么感觉

## 四、机械闸门（写库前）

1. 5 节都非空且达到最小长度（核心词汇 40 字、语法 30、语境 30、语感 60）。
2. 「核心词汇」里必须出现目标词（或卡上的读音）。
3. 「语感」至少命中 2 个语感关键词（语域/轻蔑/口语/正式/对比/上司…），防止模型写空话。
4. HTML 标签白名单：`br b strong ruby rt ul li`；`<ruby>` 必须配对。
5. 不允许占位符（TODO、待补、XXX…）。
6. 写库后回读：AINote 必须与写入值逐字一致。

不合格会带反馈重问一次；两次都不过就只落盘 `data\ainote\gen\<noteId>_rejected.json`，
**不写库**。

## 五、模型产出可以手改

`apply` **只读** `data\ainote\gen\<noteId>_out.json`，不重跑模型。
模型写的某句不对（事实、活用、措辞），直接改 JSON 里的 5 个值，再 `apply --commit`。

实测本地 27B 的常见残差（闸门抓不到，每次都要人看）：

| 残差 | 例子 | 处理 |
|---|---|---|
| ruby 结构写错 | `<ruby>身分</ruby><rt>みぶん</rt>`（rt 跑到 ruby 外） | 改成 `<ruby>身分<rt>みぶん</rt></ruby>` |
| 活用判断错 | 把「向かって」说成「不是动词活用」 | 改成「向かう 的て形」 |
| 块级元素塞进 `<p>` | `<p><ul>…</ul></p>` | 渲染器已按块级片段处理；手改时可以留 `<ul>` |

生成后如果卡上的 Word / Sentence / 译文 / AINote 又改过，`apply` 会拒绝
（`input_hash` 对不上），重跑 `gen` 即可；`--force` 可强行套用（一般别用）。

## 六、落盘与回退

| 路径 | 用途 |
|---|---|
| `data\ainote\gen\<noteId>_out.json` | 模型产出（**断点续跑的最小单位**；可手改） |
| `data\ainote\gen\<noteId>_rejected.json` | 两次没过闸门的产出（含原因，只供排查） |
| `data\ainote\backup_<时间戳>.json` | **revert 的唯一依据**，别删 |

`revert` 默认用最近一份备份；演练不加 `--commit`。

## 七、最常踩的坑

| 坑 | 处理 |
|---|---|
| 以为它会顺手改例句/译文/振假名 | 不会。它只写 AINote；那些字段由别的链路负责 |
| 不看演练直接 commit | 模型可能「语感」写得空、或把近义词辨析写错；**至少扫一眼新 AINote 全文** |
| 卡上内容改过还套旧产出 | `apply` 会拒绝；重跑 `gen`，别用 `--force` 蒙 |
| 把 ① 中文翻译交给模型 | 脚本不会；翻译永远取卡上的 `Sentence Translation` |
