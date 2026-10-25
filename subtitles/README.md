# subtitles/ —— 日语字幕原文

> 状态：active ｜ 最后核实：2026-10-26

这个目录放**日语 `.srt` 字幕**，一集一个文件，是整条流水线的起点：
`字幕 → 例句卡 → 清理 → 讲解 + 振假名 → 素材生词 → 配音`。
脚本只读这里，不往里写；产出（卡片、`output/`、`data/`）都在别处。

**这里是唯一入库的「素材」**：其余数据目录都是可重建的产物，见 [data/README.md](../data/README.md)。
字幕本身不可再生（要么重新找、要么重新抄时间轴），所以进 git；公开仓库时请注意字幕版权。

## 目录结构

```
subtitles/
├─ ARIA The ANIMATION/                          13 集   水星领航员 S1
├─ Heike Monogatari/                            11 集   平家物語
│  └─ anki/                                      2 集   已整理、可直接导卡的版本
├─ Nanatsu no Taizai/                           24 集   七つの大罪 S1
├─ Nanatsu no Taizai_ Imashime no Fukkatsu/     24 集   七つの大罪 S2「戒めの復活」
├─ Tensei Oujo to Tensai Reijou no Mahou Kakumei/  12 集  転生王女と天才令嬢の魔法革命
│  └─ anki/                                      3 集
└─ Yani Neko/                                   12 集   ヤニねこ
```

约定：

- **一个作品一个目录**，目录名用英文 / 罗马字作品名（与 Anki 里的中文集标签**不是**自动对应关系）。
- **一集一个 `.srt`**，UTF-8 编码；简体中文/英文台词混在里面的版本不要放这儿。
- 目录名与 Anki 集标签 `动画::<作品>::<季>::第NN集` 由命令行显式指定
  （`cli.py episode --tag "动画::…"`），脚本不会从目录名推导标签，换作品要自己起名字。

## 文件命名

历史上有三种来源，都保持原样，不做统一（改了会丢出处信息）：

| 来源 | 例 |
|---|---|
| Netflix 日语 CC（主流） | `平家物語.S01E01.平家にあらざれば人にあらず.WEBRip.Netflix.ja[cc].srt` |
| 早期下载（序号作后缀） | `Aria The Animation 01.srt`、`Aria The Animation S01E05 (AI …).srt` |
| AT-X 录播 | `Tensei Oujo to Tensai Reijou no Mahou Kakumei - 01 (AT-X).srt` |

新增一集时用第一种写法最省事：

```
<作品名>.S<季>E<集>.<副标题>.ja.srt
```

## `anki/` 子目录

放**已经整理过、可以直接导卡**的同一集字幕。和原字幕的差别（以 `平家物語` E01 实测）：

| | 原字幕 | `anki/` 版 |
|---|---|---|
| cue 数 | 336 | 63 |
| `漢字(かな)` 注音 | 有 | 去掉（只剩汉字） |
| 纯音效行（`（犬の鳴き声）` 之类） | 保留 | 删掉 |
| 相邻台词 | 逐条 | 合并成一句 |

注意它**不是原字幕的子集**（切分方式变了，逐字比对只有 26 条完全一致），
所以两者要各自维护，别拿一个覆盖另一个。

## 加一集的流程

1. 在 `subtitles/<作品名>/` 下放 `.srt`；需要导卡版就再建 `anki/` 子目录。
2. 找入口：`cli.py list` —— 字幕筛选是 `filter_subtitle`，整集流水线是 `episode`。
3. 再查参数：`cli.py <组> --help`。用法永远以 `--help` 为准，本文只讲「文件放哪」。
