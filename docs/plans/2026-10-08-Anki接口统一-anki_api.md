# 统一 Anki 访问接口（`code/common/anki_api.py`）—— 计划与执行记录

> 状态：active ｜ 最后核实：2026-10-10

> **状态**：第一期已完成（2026-10-08），已验收。
> **本文件**：§1–§8 是 `exit_plan_mode` 提交、经批准的那份计划原文（未改写）；
> §9 是执行记录 —— 实际落地、与计划的偏离、那处快照解码 bug 的逐条差异、
> 验证证据、复跑方法、第二期待办与遗留。
>
> 放在 `docs/plans/` 而不是 `data/plans/`：后者是 `activate.py` 的机器用激活计划
> （`plan_activate_*.json`），这里是人的决策档案。

---

## 1. 目标与成功标准

**目标**：在 `code/common/` 新增唯一的 Anki 访问模块 `anki_api.py`（AnkiConnect 传输 + 类型化读写 + 学习记录 + 离线快照），并把**常跑链路**里所有 Anki 读写改成走它；其余脚本按第二期机械替换。

**成功标准**

1. 全仓 `127.0.0.1:8765` 只出现在 `code/common/anki_api.py` 里（`code/common/paths.py:74` 的注释除外）。
2. 全仓不再有 `def anki(` / `def invoke(` / `def ac(` —— 当时有 **26 份**（24 个在 `code/` 下，另加 `.dsh/skills/jp-anki-pipeline/scripts/preflight.py:61` 与 `core6000-analysis/fetch.py:11`）。
3. `python code/common/anki_api.py audit` 退出码 0（自动扫重复客户端，防回退）。
4. **行为不变**：所有脚本的 CLI、stdout/stderr 契约、退出码、`--commit` 演练闸门、产出文件格式一字不改。
5. 离线段可回归验证：`today_weak.py --source snapshot --json` 改动前后的差异可完整归因（见 §9.3）。
6. Anki 没开时，每个脚本仍给出可读的中文提示，而不是 traceback。

## 2. 现状：重复清单（证据）

**A. 传输层被抄了 26 份**，差异全在这些地方：

| 维度 | 现有取值 |
|---|---|
| 超时 | 20s（preflight）、30s（`today_weak.py:110`）、120s（`check_cards.py:28`）、300s（pipeline / today_new / mine / mine_audio / check_ruby）、600s（`core6000-analysis/fetch.py:14`） |
| URL 来源 | 写死 `http://127.0.0.1:8765`（多数）；`ANKI_URL` 环境变量（`today_weak.py:36`）；`ANKICONNECT_URL` 环境变量（`vocab_cover/collect_vocab.py:56`、`make_activate_plan.py:48`、`oneshot/activate_gikai_words.py:23`）；`PL.ANKI_URL`（`preflight.py:63`） |
| 失败语义 | `RuntimeError`（`check_cards.py:30`、`pipeline.py:164`、`today_new.py:210` 的 `AnkiError`）、`SystemExit('AnkiConnect 错误 [action]…')`（`activate.py:127`、`mine.py:172`、`mine_audio.py:72`）、`SystemExit` 带"请确认 Anki 已启动"提示（`today_weak.py:113`）、`resp.get('result')` 静默 None（`preflight.py:69`、`activate_gikai_words.py:51`） |
| JSON 编码 | 有的 `ensure_ascii=False` + `charset=utf-8`，有的不带 |

**B. 读卡片资料：`findNotes → notesInfo` 分块循环约 35 处**，块大小 100/200/400 各写各的：`pipeline.py:168`、`mine.py:176`、`mine_audio.py:76`、`activate.py:131`、`check_cards.py:34`、`check_ruby.py:169,189`、`today_new.py:721,763`、`core6000_example.py:626,690,742,753,2233`、`today_weak.py:135`、`inspect_pending.py:31`、`migrate_pool_tag.py:100`、`probe_ruby.py:21`、`freq_external.py:283`、`collect_vocab.py:135` …

**C. 读卡片状态：`findCards → cardsInfo` 分块约 14 处**：`activate.py:138`、`today_new.py:714`、`today_weak.py:143`、`probe_filtered_deck_search.py:44`、`count_core6000_mature.py:26`、`scan_latex_residue.py:72` …

**D. 字段拆包 `{k: v['value']}` 约 8 处**：`check_cards.py:42`、`today_weak.py:152`、`mine_audio.py:144`、`core6000_example.py:2235`、`gen_i1_prompt.py:175`。

**E. 写后回读校验（write → `sleep(0.5)` → 重读比对）5 处**：`activate.py:466`、`mine.py:895`、`mine_audio.py:284`、`core6000_example.py:2465`、`pipeline.py:748`。

**F. 媒体挂音频（storeMediaFile → `[sound:…]` → 回读确认）2 处**：`mine_audio.py:271`、`core6000_example.py:2445`。

**G. 改 due（`setSpecificValueOfCard keys=['due']`，必须传 int）3 处**：`activate.py:455,524`、`restore_test_card.py:24`。

**H. 标签 addTags/removeTags 7 处**：`activate.py:461,526,528`、`pipeline.py:595`、`migrate_pool_tag.py:143,172`。

**I. 读取学习记录（revlog / rated）两条互不相通的路径**：

- 在线：`today_weak.py:121` 用 `findNotes query='rated:N:R'` + `notesInfo` + `cardsInfo` 拼出"坏的卡"；`core6000-analysis/fetch.py:37` 用 `cardReviews`。
- 离线：约 20 个脚本各自 `sqlite3.connect` 快照（`today_weak.py:193`、`analyze_revlog.py:11`、`anki_revlog_analysis.py:31`、`study_plan.py:210` …），其中"复制 live collection(+wal/shm) 再只读打开"的样板在 `anki_revlog_analysis.py:26` 与 `verify_queue.py:17` 各写了一遍，`unicase` collation 与 `notetypes/fields/decks` 解码在每处都重复。

**J. 配置读法 3 处雷同**：`getDeckConfig → new.perDay` 在 `today_new.py:653` 与 `gen_i1_prompt.py:346`；`deckNames` 在 `today_new.py:730`、`collect_vocab.py:113`、`make_activate_plan.py:106`。

> 同一类问题还有一处**不在本次范围**：`today_new.py:836-1100` 自带一套本地模型客户端，而 `code/common/local_llm.py` 没有任何脚本 import。建议单独一轮处理。

## 3. 设计：`code/common/anki_api.py`

**命名**：叫 `anki_api.py`，不叫 `anki.py` —— 后者会遮蔽 `data/pylibs` 里可能装的 `anki` 包。导入别名统一 `import anki_api as AK`，沿用 `paths as WSP` / `jp_decks as JD` 的既有风格。

**依赖**：只用标准库（与全仓一致：`urllib` / `json` / `sqlite3`）。

### 3.1 传输层与错误模型

```python
DEFAULT_URL     = 'http://127.0.0.1:8765'
DEFAULT_TIMEOUT = 300          # 现有多数取值；调用方要 20s/30s/600s 就显式传
CHUNK           = 200          # notesInfo / cardsInfo 的默认块大小
API_VERSION     = 6

load_config(**overrides) -> {'url':…, 'timeout':…, 'chunk':…}
    # 优先级：overrides > env(ANKI_URL | ANKICONNECT_URL, ANKI_TIMEOUT, ANKI_CHUNK) > 默认值
class Client:                  # 显式控制 url/timeout 时用；模块级函数走默认 client
    def call(self, action, timeout=None, **params) -> result
call(action, timeout=None, **params) -> result      # 模块级
health() / probe() -> {'ok', 'url', 'version', 'error'}   # 不抛异常，供体检用

class AnkiError(RuntimeError)                       # 基类（兼容 except RuntimeError / AnkiError）
class AnkiUnavailable(AnkiError)                    # 连不上：URLError/timeout/拒绝
class AnkiActionError(AnkiError)                    # .action / .error

friendly(exc) -> str                                # 中文提示（含 URL 与"Anki 开着吗"）
guard()                                             # with: AnkiError → SystemExit(friendly(exc))
```

### 3.2 读接口

`find_notes` / `find_cards` / `notes_info` / `cards_info` / `notes_map` / `cards_map` / `field` / `field_values` / `note_values` / `cards_of_notes` / `count` / `deck_names` / `deck_names_and_ids` / `deck_config` / `deck_new_per_day` / `tags` / `model_names` / `model_field_names` / `model_templates` / `media_names` / `cards_reviewed_by_day`

统一语义：id 参数一律 `int` 化并去重保序；`notes_info` 对不存在的 id 会被 AnkiConnect 静默丢掉，调用方自己按 `notes_map` 缺失判断。

### 3.3 写接口

`new_note` / `add_notes` / `update_note_fields` / `update_notes` / `add_tags` / `remove_tags` / `replace_tags` / `store_media_file` / `attach_audio` / `delete_media_file` / `create_deck` / `change_deck` / `suspend` / `unsuspend` / `are_suspended` / `forget_cards` / `set_card_values` / `set_card_due` / `verify_note_fields`

- `set_card_due` 内部 `int()` 强制（`activate.py:456` 踩过"必须传 int"），返回 `r == [True] or r is True`。
- `attach_audio` / `verify_note_fields` 把"写了要回读"做成默认行为，`settle` 默认 0.5s。
- **模块永不隐式写库**：没有 import 副作用，没有自动建 deck/自动补 tag；`--commit` 闸门仍归各脚本。

### 3.4 学习记录（在线 + 离线）

```python
rated_query(days, ease=None, deck=None) -> str
card_reviews(card_ids=None, deck=None, start_id=0) -> [row]    # AnkiConnect cardReviews

class Snapshot:                     # 离线只读：文件快照 或 live collection 副本
    Snapshot.open(path=None, live_copy=False, copy_to=None)
    .revlog(...) / .reviewed_rows(...) / .reviewed_since(...) / .reviewed_card_count(...)
    .notes(...) / .notes_map(...) / .cards(...) / .new_cards(...)
    .decks() / .notetype_map() / .split_fields(...)
```

**只读边界写死**：`Snapshot` 不提供任何写方法；快照一律 `mode=ro`；改库只经 AnkiConnect。

### 3.5 模块自带 CLI + 防回退扫描

```
python code/common/anki_api.py check [--json]        体检
python code/common/anki_api.py count "<查询串>"
python code/common/anki_api.py tags
python code/common/anki_api.py revlog --days 3 [--ease again] [--source anki|snapshot] [--json]
python code/common/anki_api.py exec <动作> [--params '{...}']   逃生口
python code/common/anki_api.py audit [--strict] [--all]         扫重复客户端
```

## 4. 迁移

### 4.1 第一期（本次做，常跑链路 12 个文件）

| 文件 | 删掉 | 换成 |
|---|---|---|
| `code/common/check_cards.py` | `ANKI_URL:22`、`anki():25`、手写分块 `:39` | `AK.find_notes` → `AK.notes_info` → `AK.field_values` |
| `code/common/check_ruby.py` | `ANKI_URL:55`、`anki():71`、两处 `:169,:189` 分块 | `AK` 同上（`--anki` 模式） |
| `code/execution/pipeline.py` | `ANKI_URL:59`、`anki():159`、`notes_info():168` | `AK.find_notes / notes_map / cards_of_notes / add_tags / suspend / update_note_fields` |
| `code/execution/activate.py` | `anki():121`、`notes_info():131`、`cards_info():138` | `AK.cards_info / set_card_due / add_tags / remove_tags` |
| `code/execution/mine.py` | `anki():165`、`notes_info():176` | `AK.find_notes / notes_map / create_deck / add_notes(AK.new_note(...))` |
| `code/execution/mine_audio.py` | `anki():65`、`notes_info():76` | `AK.find_notes / notes_map / media_names / store_media_file / update_note_fields` |
| `code/execution/today_new.py` | `ANKI_URL:95`、`anki():202`、`chunks():217`、`NOTE_CHUNK` | `AK.deck_config / find_cards / cards_info / notes_map / deck_names` |
| `code/execution/core6000_example.py` | `TN.anki`(10)、`TN.chunks`(4)、`TN.ANKI_URL`、`TN.AnkiError` | `AK.*`（`live_values` → `AK.note_values`） |
| `code/analysis/today_weak.py` | `invoke():105`、在线取数段、快照 sqlite 段 | 在线 → `AK.find_notes/notes_map/cards_map/answered_cards`；离线 → `AK.Snapshot` |
| `code/tools/regress_pipeline.py` | `P.anki / P.notes_info:47` | `AK.find_notes / notes_map` |
| `.dsh/skills/jp-anki-pipeline/scripts/preflight.py` | `anki():61`、`PL.ANKI_URL` | `AK.Client(timeout=20).health() / AK.count / AK.tags` |
| `code/execution/gen_i1_prompt.py`（已废弃） | `anki():155` | 最小改动：`anki = AK.call` 兼容别名 |

### 4.2 第二期（同一模块，另跑一轮机械替换）

- `code/analysis/` 的 revlog 读取 → `AK.Snapshot`。
- `code/analysis/vocab_cover/{collect_vocab,make_activate_plan,freq_external}.py` → `AK`（含非标 `modelFieldAdd` 走 `AK.call`）。
- `code/oneshot/*` 24 份客户端 → 机械替换。
- `core6000-analysis/fetch.py` → `AK`。
- 文档：`README.md` 脚本表与约定。

### 4.3 不动的东西

Agent 侧的 Anki MCP 工具、`code/analysis/anki_analyze/` 孤岛、`edge_tts_min.py`、`local_llm.py`、`jp_decks.py`、`paths.py`。

## 5. 公共接口 / 数据流 / 兼容性

- **新增**：`code/common/anki_api.py`。无 schema 变更、无 Anki 模型/模板变更、无产出文件格式变更。
- **删除的对外符号**：`today_new.anki` / `today_new.chunks` / `today_new.ANKI_URL`（外部使用者 `core6000_example.py` 同批改掉）；各文件的 `ANKI_URL`、`def anki`、`notes_info`、`cards_info`。
- **数据流**：脚本 → `anki_api` → AnkiConnect(127.0.0.1:8765)；离线读 → `anki_api.Snapshot` → `collection.anki2(mode=ro)`。
- **兼容性**：`ANKI_URL` / `ANKICONNECT_URL` / `ANKI_PROFILE`（经 `paths.LIVE_COLLECTION`）全部继续生效；所有脚本命令行参数不变。

## 6. 边界与失败模式

| 情形 | 处理 |
|---|---|
| Anki 没开 / 插件没装 | `AnkiUnavailable` + 中文提示；`guard()` 下与今天的 `SystemExit` 同等退出码 |
| AnkiConnect 返回 `error` | `AnkiActionError(action, error)`，消息保持 `AnkiConnect 错误 [action]: …` |
| 浏览器开着导致 `updateNoteFields` 不生效 | `verify_note_fields` 回读报出不一致 |
| id 列表很大 | 按 `CHUNK` 分块；`cards_of_notes` 分块拼 `nid:` 查询 |
| `addNotes` 部分被拒 | 返回值与输入等长、失败位为 `None` |
| `setSpecificValueOfCard` 需要 int | `set_card_due` 内 `int()` 强转 + 校验 `[True]` |
| 不存在的 noteId | 保持 AnkiConnect 行为：静默丢弃 |
| 非日文/半角字符查询 | 统一 `ensure_ascii=False` + `charset=utf-8` |
| 快照文件不存在/被锁 | `SnapshotError` 明确报路径；`live_copy` 只读副本，绝不动 live 文件 |
| `Snapshot` 写库 | 不提供写 API；`mode=ro` + uri |
| 超时差异 | 默认 300s；`today_weak` 30s、`preflight` 20s 保留 |
| 非标准动作（`modelFieldAdd`） | 不包装，走 `AK.call` + `exec` CLI 逃生口 |

## 7. 验证与验收

静态（audit + grep）、离线回归（today_weak snapshot 逐字节）、在线只读对拍、失败路径（关掉 Anki）、纪律（`--commit` 闸门与演练文案不变）。执行结果见 §9.4。

## 8. 假设与不做的事

AnkiConnect v6 动作集不变；只用标准库；脚本 CLI/输出/退出码不变；不做「直读 sqlite 写库」；不统一本地模型客户端；不重写 `anki_analyze/` 孤岛。第二期在本次对拍通过后单独进行。

---

# 9. 执行记录（2026-10-08）

## 9.1 落地清单

**新增 1 个文件**：`code/common/anki_api.py`（约 1230 行，含完整 docstring：为什么要有它、三条数据通道、配置、子命令）。

**迁移 12 个文件**（如 §4.1 计划，全部完成）+ `README.md`：

| 文件 | 结果 |
|---|---|
| `code/common/check_cards.py` | 客户端 + 分块循环删除；`__main__` 加 `AK.guard()` |
| `code/common/check_ruby.py` | 客户端删除；`cards_from_anki`/`build_lexicon` 改用 `AK` |
| `code/execution/pipeline.py` | 客户端 + `notes_info` 删除；`apply` 用 `AK.cards_of_notes`；写入用 `AK.update_note_fields` |
| `code/execution/activate.py` | 客户端 + `notes_info`/`cards_info`/`BATCH` 删除；due 用 `AK.set_card_due`；两处 `except SystemExit` → `except AK.AnkiError` |
| `code/execution/mine.py` | 客户端 + `notes_info` 删除；`addNotes` 载荷改 `AK.new_note` |
| `code/execution/mine_audio.py` | 客户端 + `notes_info` 删除；媒体/字段写入改 `AK` |
| `code/execution/today_new.py` | 客户端 + `chunks` 删除；队列读改写 `AK`；保留 `AnkiError = AK.AnkiError` 别名 |
| `code/execution/core6000_example.py` | 10 处 `TN.anki` + 4 处 `TN.chunks` 全部改 `AK`；`live_values` → `AK.note_values` |
| `code/analysis/today_weak.py` | `invoke` + 快照 sqlite 段删除；在线走 `AK`、离线走 `AK.Snapshot` |
| `code/tools/regress_pipeline.py` | `P.anki`/`P.notes_info` → `AK` |
| `.dsh/skills/jp-anki-pipeline/scripts/preflight.py` | 自动以客户端删除；体检用 `AK.Client(timeout=20).health()` |
| `code/execution/gen_i1_prompt.py`（已废弃） | 只留 `anki = AK.call` 别名，逻辑未动 |
| `README.md` | 共享库表加 `anki_api.py`；四条约定 → 五条，新增"跟 Anki 打交道一律走 anki_api" |

## 9.2 与计划的偏离（4 处，均已在此披露）

1. **`mine_audio.py` 没有改用 `attach_audio`**（计划 §4.1 曾写）。该脚本 `apply` 之后本来就跑一次独立的 `verify_rows` 回读；用 `attach_audio` 会再叠加一轮"媒体库 + 字段"回读，等于给同一份确定性数据加第二道网（与 README 约定 4 冲突）。改成忠实翻译 `AK.store_media_file` + `AK.update_note_fields`，行为零变化。`attach_audio` 仍留在模块里供后续使用。
2. **`Snapshot.open(live_copy=True)` 不用 `tempfile.mkdtemp`**。实测：本工作区在 DSH 文件沙箱下运行时，`mkdtemp` 建出的目录带一个"拒绝"的 DACL —— 连进程自己往里写文件都报 `PermissionError`，`icacls` 看它干脆是 Access is denied；而 `os.makedirs` 建的同级目录正常继承父目录 ACL。改为 `unique_dir()`（`os.makedirs` + 随机后缀），副本落在 `data/snapshots/live-*`，`close()` 自动清理。
3. **`AK.guard()` 加到了各 CLI 入口**（`today_weak` / `activate` / `mine` / `mine_audio` / `pipeline` / `check_cards` / `check_ruby`）。计划 §3.1 只定义了 `guard()`，这里明确落到入口，以满足成功标准 6。顺带把 `AnkiUnavailable` 的 **message 本身**写成可读的一句（`today_new stats` 那种把 `str(e)` 直接塞进表格的地方才不会退化成 `URLError: <urlopen error…>`）。
4. **README 提前到本期改**（计划排在第二期）。刚删掉 12 份客户端，不留"唯一接口"这条规则的话，很容易被重新踩回去。

## 9.3 快照解码 bug：逐条差异

`today_weak.bad_notes_snapshot` 原实现把 `notetypes` 的游标借给内层 `fields` 查询复用，外层循环只剩一行。**不是"最后一个"**：`SELECT id, name FROM notetypes` 走 Anki 的 name 索引，行序按名字排，旧实现剩下的是**第一行 `Basic`**（用一份独立探针确认：`shared-cursor mid2model size = 1 → {1784541678984: Basic}`）。于是非 Basic 的卡全部退化成 `model='?'`、`name='(无名字)'`，在线（AnkiConnect）路径不受影响。

`AK.Snapshot.notetype_map()` 改为一条 `SELECT ntid, ord, name FROM fields ORDER BY ntid, ord` 取完再分组。逐条差异（`--days 30`，`again`+`hard`）：

| | 冻结快照 `data/snapshots/_anki_snap` | live 副本 |
|---|---|---|
| 受影响行数 | **951 / 974** | **1118 / 1187** |
| `model`+`name`（kind 不变） | 805 行：`?`→`eggrolls-JLPT10k-v3.5`、`(无名字)`→`怒り` | 950 行 |
| `model`+`name`+`kind` | 146 行：`?`→`どんなときどう使う日本語表現文型Note`、**word→grammar** | 168 行 |
| 模型分布 | `{?:951, Basic:23}` → `{文型Note:146, Japanese Vocabulary:504, eggrolls:301, Basic:23}` | 同构（168/572/378/69） |
| kind 分布 | all word → **grammar 146 + word 828** | all word → **grammar 168 + word 1019** |
| `noteId` 集合 / `again` / `hard` / `deck` / 同期作答卡数 | **逐行未变**（3561） | **逐行未变**（4167） |

**防回退断言**：把旧解码路径（单条 notetype map）套到**现在这份** `bad_notes_snapshot` 上重跑，输出与改动前的 CLI 基线**逐字节相同**（两个库都成立）。这条保证"迁移本身零行为变化"，§9.3 的差异**全部**来自那处有意修掉的 bug。

## 9.4 验证证据（全部可复跑，harness 在 `.tmp/anki_api_baseline/`）

| 检查 | 结果 |
|---|---|
| `anki_api.py audit` | **0 阻塞项**，exit 0；第二期 44 个待办另列（`--all`）。扫描是 tokenize 级的：注释与 docstring 里的 `127.0.0.1:8765` 不算，`'-is:suspended'` 里的 `suspend` 也不算动作名 |
| `pipeline.py prepare` 产物 `data/pipeline/gen/cache.json` | 旧传输 vs 新模块**逐键相同**（词条 10910 / 句型 518 / 参照 352） |
| `notes_info` / `cards_info` / 字段拆包 | 与旧手写循环在 300 条真实笔记/卡上**逐字节相同** |
| `Snapshot` 离线解码 vs 在线 AnkiConnect | 同一批 40 张卡 5 个字段**零不一致**；4 个 notetype 全部解出 |
| `today_weak` 在线表达式 | `rated:N:R`（N=1/3/30 × 有/无 deck × again/hard）、作答卡计数、`notes_map`、`cards_map` 同刻比对 **0 失败** |
| CLI 逐字节对拍（改动前基线 vs 改动后） | `today_new stats`/`plan --dry-run`、`core6000 status`、`mine_audio plan`/`verify`、`check_cards --anki`、`activate revert`、`preflight --offline`、`today_weak --json`/`--plain`/`--days 30` 全部 `out=same` |
| 迁移脚本 vs 旧传输（`run_old.py`） | `mine_audio plan`/`verify`、`activate revert`、`check_cards --anki` **逐字节相同** |
| Anki 没开（`ANKI_URL` 指向死端口，13 条命令） | **无一处 traceback**，都给中文提示；`--source snapshot` 与 `preflight --offline` 照常可用 |
| `import anki_api`（Anki 不可达） | 成功 —— import 无 I/O、无副作用 |
| `--help` 冒烟（12 个脚本） | 全部 exit 0（`check_cards.py` 例外：它本来就没有 argparse，`--help` 被当文件路径，改动前即如此） |

只有两处 stdout/stderr 差异，都已归因到**数据漂移**而非代码：

* `today_weak` 在线 stderr 的"同期作答卡片 12 → 15 张"：会话期间你在复习（同刻比对 harness 已证表达式等价）。
* `activate revert` 演练里 1 行：`少将` `due 9244 → 1791413955`、`type 0 → 1`（新卡被你学成学习卡）。

## 9.5 复跑方法

```powershell
$PY = "python"
$WS = "<工作区根>"
$BASE = "$WS\.tmp\anki_api_baseline"      # harness（不改仓库，纯只读验证）

# 1) 只读体检
& $PY "$WS\code\common\anki_api.py" check
& $PY "$WS\code\common\anki_api.py" audit          # 0 = 常跑链路干净；--all 列第二期待办

# 2) 逐字节回归（先 capture 一个 before，改完再 capture 一个 after，然后 compare）
& $PY "$BASE\capture.py" before offline            # 或 online
& $PY "$BASE\capture.py" after  offline
& $PY "$BASE\compare.py" "$BASE\before" "$BASE\after"

# 3) 与「旧传输」对拍（把 anki_api 的 Client.call 换回手写 HTTP 再跑同一命令）
& $PY "$BASE\ab_migrated.py" mig mine_audio_plan check_cards_anki

# 4) 快照解码 bug 的防回退断言（旧解码路径 vs 现在这份函数 + 改动前基线）
& $PY "$BASE\equiv_weak.py"                        # 需要先跑 capture.py before offline 生成基线
& $PY "$BASE\equiv_pipeline.py"                    # pipeline prepare 产物等价
& $PY "$BASE\equiv_weak_live.py"                   # 在线表达式同刻等价
& $PY "$BASE\anki_down.py"                         # Anki 没开时的观感
```

> `equiv_weak.py` 与 `compare.py` 依赖 `capture.py before …` 生成的基线目录 —— 收工打扫时
> 这些基线已被删（可再生成）；harness 脚本本身保留。

## 9.6 第二期待办（44 个文件，`audit --all` 可列全）

- `code/analysis/` 的 revlog/sqlite 读取：`analyze_revlog.py`、`anki_revlog_analysis.py`、`retention_cost_probe.py`、`weak_words_2d_live.py`、`planning/anki_plan.py`、`planning/anki_sim3.py`、`vocab_cover/{metrics,study_plan,study_time_budget}.py` → `AK.Snapshot`。
- `code/analysis/vocab_cover/{collect_vocab,make_activate_plan,freq_external}.py` → `AK`（`modelFieldAdd` 走 `AK.call`）。
- `code/oneshot/*` 24 份客户端（含 `restore_test_card.py` 的 `setSpecificValueOfCard` → `AK.set_card_due`）。
- `core6000-analysis/fetch.py` → `AK`（`deckNamesAndIds` / `cardReviews` / `modelTemplates` / `getNumCardsReviewedByDay`）。

## 9.7 遗留与风险

1. **两个删不掉的空目录**（本次踩 `tempfile.mkdtemp` 留下的）：`data/snapshots/probe-mk-c3ozfqej`、`data/snapshots/live-cfemqh6w`。它们自身的 DACL 连读都不允许，`rmdir`/`shutil.rmtree`/`cmd rmdir` 都是 Access is denied。清理需要在**完全权限**下跑一次 ACL 修复（`diagnose-windows-sandbox-acl` 脚本，一条命令）。新代码不会再产生这种目录。
2. **同类重复仍在**：`today_new.py` 自带本地模型客户端（约 250 行），`code/common/local_llm.py` 至今无人 import。建议单开一轮收口。
3. **未实跑的写路径**：`today_new gen` / `merge`、`mine write --commit`、`mine_audio apply --commit`、`core6000 apply --commit` 本次只做了结构审查 + 只读对拍（不写你的产物）。下一次真实跑那几条命令就是终验 —— 闸门与演练文案未改，出错也有 `--commit` 兜着。
4. **`Snapshot.open(live_copy=True)` 会往 `data/snapshots/` 写一份 42MB 副本**（`close()` 时删除）。若要留着检查，传 `copy_to=<目录>`。
