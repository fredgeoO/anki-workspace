# 插件 `jiten_reorder`：素材生词新卡按 `JitenAnimeRank` 排位置

> 状态：active ｜ 最后核实：2026-11-09

**功能仍在，且是「按词频排新卡位置」的唯一入口。** 插件源码正本
[data/anki_addon/jiten_reorder/](../data/anki_addon/jiten_reorder)（`__init__.py` + `config.json`
+ `manifest.json`）与安装包 `jiten_reorder.ankiaddon`；行为、`config.json` 键与安装步骤直接看源码。

要点：

- **做什么**：把配置牌组（默认 `0-日本语学习::0-词汇::0-素材生词`）里 `is:new` 卡的
  `cards.due` 写成笔记字段（默认 `JitenAnimeRank`，空/非数字 → `999999`）的数值——
  Anki 按 due 升序出卡，词频高的先学。复习卡一律不碰；幂等，无输出即没问题。
- **触发**：打开配置自动跑（`autoRun: true`）＋工具菜单「按 JitenAnimeRank 重排素材生词新卡」手动跑。
- **安装**：Anki → 附加组件 → 从文件安装 `jiten_reorder.ankiaddon`，**必须重启 Anki**。
  `addons21` 在工作区外，沙箱需一次越权写；以工作区内源码为准。
- **背景与原则**：[ADR：`JitenAnimeRank` 只作注解，顺序一律看 `cards.due`](decisions/2026-10-jitenanimerank仅作注解.md)。
  `JitenGlobalRank` 只作注解，本插件不读它。

## 已退场的旧做法

- **脚本直写 due**（`reposition.py --commit`）：这版 AnkiConnect 下 `due` 是 protected，
  `--commit` 不可能成功——见 [deprecated.md §11](deprecated.md)。
  `reposition.py` 只剩 `--check` 只读体检可用。
- **阶段三 activate**（`vocab reorder-jiten` → `activate.py apply --global`）：2026-10-12 退役，
  见 [deprecated.md §6](deprecated.md)。ImmersionKit 批量跑一律 `write --no-order`，新卡 due 交给本插件。
