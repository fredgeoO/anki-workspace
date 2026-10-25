# 本地模型链路 · 防错手册

> 状态：active ｜ 最后核实：2026-10-20

**这是什么**：本地模型（qwen3.8-27b @ NInfer 4090）在这条链路里干两件活（补讲解、挖生词），
这份手册讲怎么用代码把「出错」变成「可诊断、可重试、不连坐」。
**为什么存在**：模型输出不可靠又不便宜返工，防线必须在脚本里，不能靠人盯。
**什么时候读**：改 `pipeline.py gen` / `mine.py gen` 的提示词或校验逻辑时；模型产出异常时。
铁律：**机械判断归代码，语义判断才归模型**（[AGENTS.md](../../AGENTS.md) §3 第 6 条）。

---

## 1. 分工边界：本地模型只干这两件事

| | 任务 A | 任务 B |
|---|---|---|
| 干什么 | 给**例句卡**补 `AINote` + `Sentence HTML` | 从例句里挖**素材生词**建成第三个词汇牌组 |
| 入口 | `code/execution/pipeline.py` `gen` | `code/execution/mine.py` `gen` |
| 产出 | `data/pipeline/gen/output_NN.json` | `data/vocab/gen_mine/output_NN.json` |
| 判定/校验器 | `code/common/check_cards.py`（`split_hard`） | `code/common/check_mine.py`（`check`） |
| 失败收尾 | `failed.json` → 强模型 → `pipeline.py merge-fix` | `failed.json` → 强模型 → `mine.py merge-fix` |
| 落库 | 回写例句卡两个字段 | `0-日本语学习::0-词汇::0-素材生词` |

**为什么两件事必须分开跑**：任务 A 的输入是整句例句 + 生成规范（每张卡 400 字讲解），
任务 B 的输入是候选词 + 出现例句；两者的**输出形状、校验规则、失败处置**都不同。
混成一次调用会把 prompt 撑到窗口边缘，而且失败后无法判断是哪一半坏了。
所以：一次只给本地模型**一件事**，一批 6–15 条（由 `fit_groups` 按预算再切）。

**「只收 core6000/考级词汇里没有的词」这条筛选**——**不进模型**，由代码算：
`mine.py build_payload` 用 `pipeline.rebuild_known_index()` 建的索引查
`0-词汇::2-考级词汇`（10,609 张）+ `0-词汇::1-高频日语单词 6000`（6,000 张），
命中即排除（含活用形、平/片假名变体、词干）。模型只回答"这是不是一个词、值不值得学"。

---

## 2. 事故目录：真实发生过的崩法 → 现在的代码防护

| # | 现象 | 根因 | 防护（代码位置） | 测试 |
|---|---|---|---|---|
| 1 | `merge-fix` 报"并入 2 条"，真实词条 `錆` 被覆盖成排除条目，`write` 被堵死 | `patch_outputs` 前缀回退不区分占位条目，`錆` 恰是 `錆臭ぇ` 的前缀 | 前缀回退**只允许落在占位条目**（`is_placeholder`）+ 排除本批其他原词 + 一条 fix 只改一条 + 落空告警（`mine.py patch_outputs`） | test_mine_patch 1–5 |
| 2 | `write` 报「例句中找不到该词形 ['介抱する']」 | `conjugation_variants` 把 `する` 当普通词尾，`サ変` 生不出 `介抱し/した/して` | `endswith('する') and len>2` 单独展开并提前返回（`pipeline.conjugation_variants`） | test_mine_patch 8 |
| 3 | `write --commit` 整批被拒 `cannot create note because it is a duplicate`（6 条全新词） | `Index` 是笔记类型**首字段**，而序号用了"笔记条数+1"，曾删卡留空洞 → 撞上仍在的 6100 | `next_index()` 取**模型内数字最大值 + 1**，写前打印序号（`mine.py next_index`） | — |
| 4 | 整批 `gen` 崩：`AttributeError: 'int' object has no attribute 'strip'`，已判好的条目一起丢 | 本地模型把 `translation` 回成了数字，校验器假设字段是字符串 | **吸收层** `code/common/llm_out.py`（`as_text`/`as_bool`/`is_boolish`）+ 校验器报"字段类型不是字符串"这条硬错误 + 每组 try/except | test_llm_out 1/3/4 |
| 5 | 候选 `食わして` 一直进 `failed.json`；强模型"好心"补成 `食わす` 又被 `write` 判 mismatch | `same_origin` 要求"残差是输出词的子串"，而口语缩略形的词典形不含残差 | 提示词写死"**只能往后接**，否则原样保留候选" + `origin_possible()` 在**判定阶段**就拦下并给出可执行提示 | test_mine_patch 13 |
| 6 | `AINote` 是数字时阶段二整批作废（同类，未实际发生） | 同上，`check_cards.split_hard` 直接 `.startswith()` | `split_hard` 全程 `as_text` + 条目非 dict → 硬错误（`check_cards.py`） | test_llm_out 3 |
| 7 | 产出被写坏后**无法回溯**模型到底回了什么 | `gen` 不落盘原始回复 | `llm_out.dump_raw()`：只在"这组没做出来"时写 `gen/raw/`、`gen_mine/raw/`，同名不覆盖 | test_llm_out 2 |

---

## 3. 五道防线（从便宜到贵）

1. **提示词硬约束**（最便宜，直接减少错误率）
   - `pipeline.LOCAL_INSTRUCTION` 铁律 10–12：noteId 是数字、两个字段必须是字符串、每张卡都要有输出、
     **振假名以"词"为单位**（`食わす → くわす`，不要只给词的一部分标读音）。
   - `mine.MINE_INSTRUCTION` 字段说明 + 铁律 5–8：`word` **只能往后接**（候选必须是子串）、
     字段值必须是字符串、`include` 必须是 JSON 布尔、每条候选都要有对应条目、不许省略。
2. **吸收层**：`llm_out.as_text/as_bool/is_boolish/as_int` —— 非字符串当"没有这个字段"，
   由校验器报成一条明确硬错误（而不是抛异常），且**异常不穿透**。
3. **隔离与留证**：两个 `gen_loop` 都是"每组 try/except"——一组出意外只影响这一组，
   下一轮逐条重问；没做出来的组把模型原始回复写进 `raw/`。**一条坏回复绝不能带走 11 条好结果。**
4. **机械闸门 + 带反馈重问**：`check_cards.split_hard` / `check_mine.check` 把不合格压成短清单，
   作为 `feedback` 塞回下一轮请求（`gen --retries`，重问**逐条发**）。
   HTML 类的机械问题不重问模型，交给 `ruby_engine.py repair` 确定性重渲染。
5. **强模型/人工只看短名单**：`data/pipeline/gen/needs_llm.json`、
   `data/vocab/gen_mine/failed.json`/`needs_llm.json` —— 通常 0–2 条。

**预算闸门**（防"跑了几分钟本地算力才发现装不下"）：
`pipeline.fit_groups(items, size, render, cfg, LLM)` 用**真实请求正文**估算 token，
超预算就自动再切小；单条就超预算的交给 try/except 记成"这组没做出来"。

---

## 4. 操作规程

```powershell
$WS = "<工作区根>"
$PY = "python"
$EXE = "$WS\code\execution"

# ── 任务 A：例句卡 AINote + Sentence HTML
& $PY "$EXE\pipeline.py" split --tag "动画::…::第NN集" --batches 12
& $PY "$EXE\pipeline.py" gen                  # 失败逐张重试；仍失败的进 failed.json
& $PY "$EXE\pipeline.py" write                # 入库（先校验；不通过就不写）

# ── 任务 B：素材生词（筛选由代码做，模型只判定）
& $PY "$EXE\mine.py" scan --tag "动画::…::第NN集"
& $PY "$EXE\mine.py" split --batches N        # ≈10–15 候选/批
& $PY "$EXE\mine.py" gen
& $PY "$EXE\mine.py" write --commit           # 直接写（2026-10-12 口径）
```

跑完看三样东西，别的都不用查：
1. 批次结尾的 **收录/排除计数**与 `failed.json` 条数；
2. `data/pipeline/gen/raw/`、`data/vocab/gen_mine/raw/` 里有没有新证据文件（有 = 那组出过事，翻一眼原因）；
3. 强模型短名单文件（`needs_llm.json` / `failed.json`）里剩下的条目 —— 只处理这几条。

**回归测试**（改这两个脚本后必跑）：

```powershell
& $PY "$WS\code\tests\test_llm_out.py"       # 吸收层 / 校验器 / 分组预算
& $PY "$WS\code\tests\test_mine_patch.py"    # merge-fix / 同源 / 活用 / 类型
```

> 坑：沙箱里**系统 temp 不可写**，`tempfile.mkdtemp()` 建的目录在受限令牌下也写不了；
> 测试要用临时目录就用工作区的一次性文件区 `temp/`（`WSP.TEMP`，见 `test_llm_out.py`），
> 用完由 `python code/cli.py temp clean` 一起清掉。

---

## 5. 残余风险（知道了就好，别指望代码兜住）

* **语义错**：振假名读错（`飯食わす` 标成 `た`）、义项选错、专有名词被当真词 ——
  形状都对，机械闸门查不出来。兜底是 `ruby_engine.py check` / `check_ruby.py --blind-out`
  的读音盲区清单 + 人工抽检；**别让它静默过库**。
* **模型的"好心"改写**：把口语形换成词典形、把残差补成另一个词 —— 现在会被
  `origin_possible` 拦下并要求重做，但重做仍可能再错，最终进 `failed.json`。
* **长句批次**：`fit_groups` 只按估算切，估算偏保守；极端长对白仍可能单条超预算，
  这类卡会稳定进 `failed.json`（不是随机失败）。
* 其它本地模型调用点：`code/tools/local_filter.py`（字幕筛选）已是"正则提取 + try/except"
  的写法，暂时没加固的必要。
