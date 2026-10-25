---
name: jp-anki-check-ruby
description: anki-workspace 的**振假名读音自检器**：拿**字幕自带的注音**校验生成的 `<ruby>` 读法。`check_cards.py` 只查结构，**查不出汉字标错读音**；ABS Player 导入时会把字幕里的 `漢字(かな)` 注音剥掉，子代理看不到字幕作者的权威读音，只能自己猜。本脚本把字幕注音与生成结果逐条对照，把「读音错误」变成**确定性的、可自动拦截**的问题。当用户说「振假名读音要校验」「字幕注音和卡上的读音要对一下」「读音盲区要列出来交强模型看」时加载本技能。**不含**清理、生成、激活、挖生词、配音——那些在各自独立的技能里。仅适用于 anki-workspace。
---

# 日语 Anki · 振假名读音自检（check_ruby）

本技能覆盖**一件事**：拿字幕自带的注音校验生成的 `<ruby>` 读法。

## 一、为什么需要它

`check_cards.py` 只查结构：文本是否逐字一致、标签是否白名单、ruby/rt 是否配对。它**查不出一件事**：汉字标错读音。而 ABS Player 导入时会**剥掉字幕里的 `漢字(かな)` 注音**，子代理看不到字幕作者的权威读音，只能自己猜——猜错一分，卡面显示的就是错的读音，且没有任何闸门会报。

字幕本身带着答案：筛选后的 SRT 里每条 `漢字(かな)` 都是字幕作者给的读音。本脚本把它与生成结果逐条对照，把「读音错误」变成**确定性的、可自动拦截**的问题。

实测（平家物語 S01E02）：33 处注音里抓出 6 处真实错读（暇 ひま→いとま、美女 びじょ→びんじょう、祇女 ぎじょ→ぎにょ、蹴 け→く、蹴下乗合 でんか→てんがののりあい、一本葛 いっぽん/くず→ひもと/かずら）。

## 二、命令

```powershell
$WS  = "<工作区根>"
$PY  = "python"
$COM = "$WS\code\common"
$DAT = "$WS\data"
```

### 2.1 校验子代理产出（阶段二 verify 之前）

```powershell
& $PY "$COM\check_ruby.py" --plan "data/evidence/<集>/plan.json" --gen "$DAT\pipeline\gen"
& $PY "$COM\check_ruby.py" --plan "data/evidence/<集>/plan.json" --json "$DAT\pipeline\gen/output_01.json"
```

### 2.2 直接扫库里已入库的卡（回归用）

```powershell
& $PY "$COM\check_ruby.py" --plan "data/evidence/<集>/plan.json" --anki "tag:动画::<作品名>::<季>::第NN集"
```

### 2.3 不想给 plan.json 时，直接指筛选后的 SRT

```powershell
& $PY "$COM\check_ruby.py" --srt "subtitles/.../（制作anki卡牌用）.srt" --gen "$DAT\pipeline\gen"
```

## 三、判定口径

对每条字幕注音 `漢字(かな)`，在卡里找**覆盖这几个汉字**的 ruby（允许拆成多个 ruby、也允许一个 ruby 覆盖更长的词），再看它的读法是否与字幕注音一致：

| 判定 | 说明 |
|---|---|
| OK | 读法完全一致 |
| INFO | 读法里**包含**字幕注音（例：字幕只注了 `仏(ほとけ)`，卡里是 `<ruby>仏御前<rt>ほとけごぜん</rt></ruby>`；或字幕 `一本葛(ひともとかずら)` 被拆成 `<ruby>一本<rt>ひもと</rt></ruby><ruby>葛<rt>かずら</rt></ruby>`） |
| MISMATCH | 读法对不上 —— `Sentence HTML` 里出现即**不合格**；只出现在 `AINote` 里算提醒 |

退出码：`Sentence HTML` 有 MISMATCH 时为 1，否则 0（可直接串进流水线做闸门）。

## 四、读音盲区与待复核

约一半的读音机械可查，剩下的看 `--blind-out` 那份清单，交给强模型过：

```powershell
& $PY "$COM\check_ruby.py" --plan "data/evidence/<集>/plan.json" --anki "tag:动画::<作品名>::<季>::第NN集" --blind-out "$DAT\evidence\<集>\ruby_blind_spot.md"
```

`ruby_engine.py check` 的「待复核」短清单也是交强模型的读音盲区裁决。

## 五、已有卡上的错读可直接修

```powershell
& $PY "$COM\ruby_engine.py" apply --query "tag:…" --mode fix --fix-ainote --commit
```

只动权威来源明确说错的卡，写前自动落 `data/ruby/revert_<时间戳>.json`。

## 六、收工汇报

- 机械可查的读音：OK / INFO / MISMATCH 统计；
- `--blind-out` 清单路径（需要强模型裁决的读音盲区）；
- 是否有 MISMATCH（退出码 1 表示 `Sentence HTML` 有读音错）。

---

**本技能只做读音校验。** 清理（阶段 1）→ `jp-anki-triage`；生成（阶段 2）→ `jp-anki-generate`；激活（阶段 3）→ `jp-anki-activate`；挖生词（阶段 4）→ `jp-anki-mine`；配音（阶段 5）→ `jp-anki-audio`。
