# code/ —— 代码地图与写码约定

> 状态：active ｜ 最后核实：2026-11-10

这里是工作区的可复用代码。**统一入口是 `cli.py`**：它只做「组 → 脚本」映射与参数透传，
不含业务逻辑。想知道全部组和真实脚本路径，跑 `python code/cli.py list`；参数用
`python code/cli.py <组> --help`。更细的分区理由与历史见 [docs/architecture.md](../docs/architecture.md) §1–2，
数据流与测试矩阵见 [docs/implementation.md](../docs/implementation.md)。

## 1. 目录地图

| 路径 | 作用 |
|---|---|
| `cli.py` | 组 → 脚本映射（`GROUPS` / `VOCAB` / `WEAK`）。加功能只加映射，别在这里写逻辑 |
| `common/paths.py` | 路径唯一来源（`WSP.DATA_PIPELINE`、`WSP.TEMP` …），不写死绝对路径 |
| `common/anki_api.py` | **Anki 唯一通道**：`find_notes` / `notes_info` / `update_note_fields` / `verify_note_fields` / `Snapshot.open(live_copy=True)`；命令行 `check`、`audit`、`count`、`find`、`notes`、`revlog` |
| `common/writeback.py` | **写库事务**：演练 / 备份 / 写 / 回读；只暴露字段与标签，结构上不碰调度列 |
| `common/batchjob.py` | **批处理清单 + 收尾层**：split / manifest / 断点续跑 / `failed.json` / 解析→校验→并回（mine、pipeline、proper 共用） |
| `common/textio.py` | **文本 I/O 唯一入口**：UTF-8 stdio、容错解码、`read_text` / `dump_json` / `run` / `audit --strict` |
| `common/jp_decks.py` | 牌组名、考级级别标签解析（`level_from_tags`）。**别拼子 deck 路径** |
| `common/ruby_engine.py` | 拿原句当骨架**确定性**渲染/修复 `Sentence HTML` |
| `common/ruby_text.py` | `漢字[かんじ]` ↔ `<ruby>` 的解析与纯文本提取；标签构造走 `ruby_engine.wrap` |
| `common/htmltext.py` | 去 HTML 标签 / `<br>` 转换行（`ruby_text` 与讲义共用） |
| `common/jp_text.py` | 日语文本清洗与字符判定：`norm` / `strip_html` / `hira2kata` / `vocab_guard` / `dupkey` / 假名·汉字正则 / 词汇来源常量 / `vocab_shape_variants`。**两套汉字口径**：这里的 `KANJI` 含 CJK 扩展 A，`ruby_text.KANJI` 不含 |
| `common/audio_names.py` | `[sound:…]` 解析（`sounds_of`）与媒体文件命名（`safe_token` / `media_name`） |
| `common/llm_client.py` | 本地模型客户端（OpenAI Responses API）：`llm_chat` / `load_llm_config` / `usage_row` / `extract_json` |
| `common/llm_out.py` | 模型产出吸收层：畸形 JSON、类型错、超预算、漏卡重问 |
| `common/card_prompt.py` | 讲解/振假名提示词组装（规则正本仍是 `execution/card_rules.md`） |
| `common/jmdict_check.py` | JMdict 核验：词形/读音/词性对词典；只读词典，不写 Anki |
| `common/immersion_api.py` | ImmersionKit 只读客户端（搜索/媒体/缓存），不碰 Anki |
| `common/check_*.py` | 闸门：卡片结构、生词、读音、专名。退出码即结论 |
| `common/local_llm.py` | 本地模型客户端**转发层**；实现正本在全局技能 `~/.dsh/skills/local-llm/scripts/local_llm.py` |
| `execution/` | 各阶段：`episode.py` `pipeline.py` `mine.py` `mine_audio.py` `cards.py` `note_regen.py`（卡片修正 · AINote ①②） `activate.py` `today_new.py` `ainote_enrich.py` `proper.py` `immersionkit.py` `filter_subtitle.py` `reposition.py`；系列子夹见下两行 |
| `execution/core6000/` | core6000 系列：`core6000_example.py`（入口 `cli.py core6000`）、`core6000_meaning.py`（入口 `cli.py meaning`）+ `core6000_text.py` `core6000_text2.py` `core6000_jisho.py` `core6000_gates.py` `core6000_render.py` + `core6000_example_prompt.md` |
| `execution/lesson/` | 每日讲义系列（入口仍是 `today_new.py`）：`lesson_text.py` `lesson_check.py` `lesson_paths.py` `lesson_render.py` + `lesson_local_prompt.md` |
| `execution/card_rules.md` | 讲解 / 振假名规则正本；改提示词先看它 |
| `tools/` | `doctor.py` `temp_clean.py` `edge_tts_min.py` `check_audio.py` `backup_anki.py` `subtitle_tag.py` `today_new_words.py` `season_new_words.py` `rank_gate.py` `unranked.py` `proper_extract.py` `jisho_example.py` 等可复用能力 |
| `analysis/` | 弱项与词汇分析（`today_weak.py`、`vocab_cover/`）；ankiR 报告入口 `ankir.py` + `ankir_bridge.R`（只读，见技能 `jp-anki-r-analysis`） |
| `oneshot/` | 一次性探针/迁移：不维护，**不要照抄**；用完的挪 `archive/` |
| `tests/` | 回归测试，直接跑单个文件：`& $PY code\tests\test_llm_out.py` |
| `plugins/anki-workspace/` | DSH 插件（desktop profile）：十一个 Agent 工具 + 每轮 `<anki-workspace>` 上下文 + Web 面板；不直接读写 Anki，动作落回 `cli.py` / `anki_api.py` |

## 2. 加新代码

1. 放进四区之一：`execution`（多步流程）、`tools`（可复用能力）、`analysis`（诊断/报告）；
   一次性的直接写进 `temp/`，别进 `code/`。core6000 / 每日讲义进各自子夹
   `execution/core6000/`、`execution/lesson/`——模块名保持扁平，调用方把系列目录一起挂进
   `sys.path`（路径常量在 `paths.py`：`WSP.EXEC_CORE6000` / `WSP.EXEC_LESSON`）。
2. 路径一律 `import paths as WSP`；文本 I/O 一律 `import textio`（不手写 `sys.stdout.reconfigure`）；
   碰 Anki 一律 `import anki_api as AK`。已知例外（历史遗留，不要照抄）：`analysis/anki_analyze/`、
   `oneshot/`、`tools/backup_anki.py`；以 `anki_api.py audit` 的明细为准。
3. 新入口加进 `cli.py` 的 `GROUPS` 映射，只加映射。
4. 不另造第二份实现：机械判断（结构、逐字、ruby、查重、回读）走既有 `check_*` / `ruby_engine`；
   汉字/假名正则、词汇写法变体等只在 `common/` 留一份。
5. 跨 `execution` 脚本借用的白名单在 `tests/test_import_guard.py`；白名单外新增会失败。

## 3. 改完自检

```powershell
& $PY code\common\anki_api.py audit          # 必须 0 阻塞（已知例外见 §2）
& $PY code\common\textio.py audit --strict   # 必须 0
& $PY code\tests\test_llm_out.py             # 换文件名就是另一组
```

动过 `common/` 或 `execution/` 就把 `code\tests\*.py` 全跑一遍（几秒，全离线）；缺第三方依赖
的测试按 ImportError 判定，不算回归。只改文档不用跑。新增 `docs/*.md` 要在头部写
「状态：active ｜ 最后核实：YYYY-MM-DD」（`doctor` 会查）。

## 4. 细节在哪

- 分区理由、`doctor` 十项、环境坑：`docs/architecture.md` §1–3、§6。
- 数据流、阶段产物、选词打分、覆盖率口径、每个测试挡什么：`docs/implementation.md`。
- 每集流水线怎么跑、判据、断点续跑：`docs/pipeline-guide.md`。
- 库结构、字段名、标签写法：`docs/anki-library.md`。
