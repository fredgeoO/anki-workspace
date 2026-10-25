---
name: jp-anki-audio
description: anki-workspace 的**阶段 5 · 生词配音**：给素材生词卡挂音频（Word Audio / Sentence Audio）。`Word Audio` 用 edge-TTS `ja-JP-NanamiNeural` 读**`Transliteration`（假名读音）**，不是汉字词形；`Sentence Audio` 复用来源例句卡的原声 `asbp_*.mp3`，无原声时 edge-TTS 兜底。含单词音频读错修复工具 `fix_word_audio.py`（固定 gen → tts → apply 流程）。当用户说「给生词卡配音」「这个词的 mp3 读错了 / 读音不对，修一下」「Word Audio 读音要换」时加载本技能。**不含**清理、生成、激活、挖生词——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语 Anki 阶段 5 · 生词配音（audio）

本技能覆盖**一件事**：给素材生词卡挂音频。

## 一、音频方案（用户指定）

| 字段 | 来源 | 理由 |
|---|---|---|
| `Word Audio` | **edge-TTS** `ja-JP-NanamiNeural` 读**假名读音** | 单词没有现成音频可用 |
| `Sentence Audio` | **复用来源例句卡的原声**（ASB Player 从字幕轨切出的 `asbp_*.mp3`）| 演员原声，语速/连读/语气真实，且文件已在媒体库里，不重复占空间 |
| `Sentence Audio`（无原声时） | edge-TTS 兜底 | 个别来源卡没切出音频 |

**为什么 `Word Audio` 喂的是读音（假名）而不是汉字词形**：TTS 读裸汉字词形有同音异读风险，且**错了听不出来**：`新興` 可能读成 しんきょう，`叶う` 可能读成 かない。edge-TTS 返回的 mp3 里也查不到它实际读的文本（LAME 头只有编码器元数据；同一文本两次合成字节并不相同，所以也无法靠比对来验证）。而 `Transliteration`（读音）字段是生成阶段就校验过的，直接拿它合成即可消除全部歧义，代价只是音频听起来和词形完全一样（本来就是同一个词）。`Word Audio` 只负责发声，不显示文本——卡面显示的是 `Word` 字段的词典形。

**为什么不用 edge-tts 这个包**：本机 pip 在工作区里解包 wheel 会被沙箱拒（临时文件 EPERM），而 TTS 协议本身不复杂。所以 `edge_tts_min.py` 用纯标准库实现：Sec-MS-GEC 令牌 + WebSocket 帧 + SSML。少一层依赖，也便于在别的机器上直接跑。

## 二、命令

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$EXE = "$WS\code\execution"
$TOOL = "$WS\code\tools"
```

### 5.1 主流程

```powershell
# 只读：列出每张卡将要挂什么音频
& $PY "$EXE\mine_audio.py" plan

# 演练：合成 TTS 到 output/audio/，不写库
& $PY "$EXE\mine_audio.py" apply

# 真写：上传媒体 + 写两个字段
& $PY "$EXE\mine_audio.py" apply --commit

# 回读校验：字段与媒体库是否一致
& $PY "$EXE\mine_audio.py" verify

# 清空这两个字段（媒体文件保留，无害）
& $PY "$EXE\mine_audio.py" revert --commit
```

只补某一集/某一批时用 `--tag`（plan / apply / verify 都支持）限定范围：

```powershell
& $PY "$EXE\mine_audio.py" apply --tag "素材生词::<来源>" --commit
```

不加 `--tag` 就是整个素材生词 deck。换集后补音频**务必带 `--tag`**：deck 里别的集的卡若 `Sentence` 与来源例句卡对不上 → 找不到原声 → `apply` 会把已有的原声 `[sound:asbp_*]` 改写成 TTS 兜底（质量下降）。

幂等：已有正确 `[sound:...]` 的字段默认跳过；`--force` 强制重做。

## 三、修一张读错的单词音频（fix_word_audio.py，2026-10-19 固化）

**本地模型照着下面 ①②③ 跑即可：不要自己写修复脚本，也不要在预览前猜读音。**

单词 mp3 读错，根因几乎都是 `Transliteration` 写错（实测：`阻止` 写成 しゅしょう、`罪人` 写成 つみと、`討つ` 写成 うたう、`分かつ` 写成 わかた）。修的时候**字段和音频必须一起改**：只改字段 → 音频还是错的；只换 mp3 → 下次 `mine_audio.py` 又按旧读音合成。

**不要再手写 `oneshot/fix_*.py`**，用固定工具（只读默认，`--commit` 才写）：

```powershell
# ① 不知道正确读音：只给词，脚本打印卡上 ruby 读音
& $PY "$TOOL\fix_word_audio.py" --word "<词>"

# ② 只读确认：现值 / 目标 / ruby 依据 / 同词其他卡
& $PY "$TOOL\fix_word_audio.py" --word "<词>" --reading "<ruby读音>" --expect "<当前读音>"

# ③ 真写：同名覆盖 mp3，[sound:] 引用不变，不碰 Sentence Audio
& $PY "$TOOL\fix_word_audio.py" --word "<词>" --reading "<ruby读音>" --expect "<当前读音>" --commit
```

`<词>` 换成用户点名的词；`<ruby读音>` / `<当前读音>` 从第①步输出里抄，**不要猜**。

### 读音只认机械依据

同一张卡 `Sentence HTML` 里该词的 ruby（含送假名：`分<rt>わ</rt>かつ` → わかつ）。脚本自己比对，对不上拒绝写；卡上没有该词 ruby 时也拒绝 `--commit`（交强模型/人确认）。**不要凭模型记忆或听感直接写**——2026-10-19 就有人把 `分かつ` 从 わかた 改成 わかたる（正确 わかつ），工具现在会用 ruby 拦住。

- `--reading` 必须纯假名；不要用 `Word` 汉字合成（同音异读，听不出来）。
- `--commit` 必带 `--expect "<当前读音>"`（旧值断言）；写完回读字段 + 媒体库；幂等，已是目标状态直接退出。
- **同词多卡共用一个 mp3**（文件名只由 `Word` 派生）：`--word` 命中多张会列 noteId 并拒绝，用 `--nid`；同词其他卡读音与目标不一致也拒绝（改文件会连带改掉它们的音频）。
- 只动 `Transliteration` + `Word Audio`。`--force` 只用于「ruby 本身确认错」或「同词多卡已决定统一读音」，**别拿它绕过检查**。
- 批量发现：`ruby_engine.py check --query "tag:…"` 查的是 `Sentence HTML`，查不出 `Transliteration` 字段错；那类只能靠听/用户点名，再逐张跑上面的命令。

## 四、收工汇报

- 挂了音频的张数、原声/TTS 各多少；
- 落盘路径（`output/audio/`）；
- 需要用户人工确认的点（读音盲区、需要强模型裁决的词）。

---

**本技能只做配音。** 清理（阶段 1）→ `jp-anki-triage`；生成（阶段 2）→ `jp-anki-generate`；激活（阶段 3）→ `jp-anki-activate`；挖生词（阶段 4）→ `jp-anki-mine`。
