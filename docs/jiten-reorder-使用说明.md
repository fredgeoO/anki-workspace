# 插件 `jiten_reorder`：素材生词新卡按 `JitenAnimeRank` 排位置

> 状态：active ｜ 最后核实：2026-10-17（ImmersionKit 批量跑一律 `write --no-order`，
> 新卡 due 全部交给本插件）

> 一句话：把 `0-素材生词` 里**新卡**的 `cards.due` 改成该词 `JitenAnimeRank` 的数值 ——
> Anki 按 `due` 升序出卡，于是**词频高（rank 小）的先学**。
>
> 产物：[data/anki_addon/jiten_reorder/](../data/anki_addon/jiten_reorder)（源码，UTF-8）
> 与 `data/anki_addon/jiten_reorder.ankiaddon`（约 3 KB，可安装包）。
> 已装入 `%APPDATA%\Anki2\addons21\jiten_reorder\` —— **重启 Anki 才会加载**。
>
> 背景与原则见 [ADR：`JitenAnimeRank` 只作注解，顺序一律看 `cards.due`](decisions/2026-10-jitenanimerank仅作注解.md)。

---

## 1. 为什么必须做成插件

| 事实 | 出处 |
| --- | --- |
| `0-素材生词` 的预设是 `new.order = 1`（NEW_CARDS_DUE）＝ 新卡按 `due` 出 | 卡组预设（`newGatherOrder`/`newInsertOrder` = `['due','random']`） |
| 新版 Anki 的 `newSortOrder` 预置枚举里**没有**「按字段排序」 | `template / none / templateThenRandom / randomNoteThenTemplate / randomCard` |
| **AnkiConnect（这一分支）写不了 `due`** | `setSpecificValueOfCard` 只允许 `factor/ivl/reps/lapses/custom_data/did/flags`；`due`/`type`/`queue` 是 protected → `compatibilityError: Use native scheduling commands for protected state` |
| `scheduling_setDueDate` 不能用 | 它走 `col.sched.set_due_date`，对**新卡**是「变成复习卡」，不是排位置 |
| 自己直接写库也不行 | 工作区铁律：`anki_api.py audit` 会标记 `sqlite3.connect` 写库；离线读只走 `AK.Snapshot(mode=ro)` |

→ 结论：**只能在 Anki 进程内用 `col.update_card()` 写 `due`**，所以做成插件。

`code\execution\reposition.py` 保留为**只读体检**工具（`--check`）：
数「due 序 vs rank 序」的逆序对与不一致对数。`--commit` 在这版 AnkiConnect 下
**不可能成功**（`due` protected），别再试。

---

## 2. 行为

* **触发**：
  * 打开配置（profile）时 `gui_hooks.profile_did_open` 静默跑（`config.json` 的 `autoRun: true`）；
  * 工具菜单 **「按 JitenAnimeRank 重排素材生词新卡」** 手动跑。
* **范围**：只动 `is:new` 的卡（复习卡一律不碰）；
* **取值**：`due = int(JitenAnimeRank)`；字段空或非数字 → `999999`（排最后）；
* **写回**：先 `col.update_card(card)`；失败再退回
  `col.db.execute("update cards set due=? where id=?")`（两条路都走 `col`，不自己开连接）；
* **收尾**：写完回读前 200 张核对，然后 `mw.reset()` 刷新界面。

跑完打印改了多少张、跳过多少张；**没有输出就是没问题**（每次打开 Anki 都会跑一遍，幂等）。

---

## 3. `config.json`

```json
{
  "decks": ["0-日本语学习::0-词汇::0-素材生词"],
  "field": "JitenAnimeRank",
  "autoRun": true
}
```

| 键 | 说明 |
| --- | --- |
| `decks` | 要重排哪些牌组（**写全名**，含 `::`） |
| `field` | 拿哪个笔记字段当位置（默认 `JitenAnimeRank`，笔记类型 `Japanese Vocabulary` 的 Sort Field 就是它） |
| `autoRun` | 打开配置时是否自动跑；`false` 则只留工具菜单手动触发 |

改 `config.json` 后重启 Anki（或用工具菜单 → 附加组件 → 编辑配置，改完同样要重启）。

---

## 4. 安装 / 更新

1. 打包好的安装包：Anki → 工具 → **附加组件 → 从文件安装…** → 选
   `data\anki_addon\jiten_reorder.ankiaddon`；
   或者直接把 `data\anki_addon\jiten_reorder\`（`__init__.py` + `config.json` + `manifest.json`）
   复制进 `%APPDATA%\Anki2\addons21\`；
2. **重启 Anki** —— 插件只在启动时加载，装完不重启等于没装；
3. 首次打开配置时会静默重排一次。

> 注意：`addons21` 在 `%APPDATA%` 下，**不在工作区内**，DSH 文件沙箱默认写不了，
> 需要一次越权写（用户批准）。源码以工作区内的 `data\anki_addon\` 为准。

---

## 5. 体检（只读）

```powershell
& $PY "$WS\code\execution\reposition.py" --check
```

2026-10-16 首次体检：素材生词共 **2,044 张卡**（其中新卡 1,910 张，全都有排名），
按 `due` 升序与按 rank 升序**不一致 291,239 / 1,823,095 对（15.97%）**，相邻倒挂仅 15 处 ——
差异 **100% 来自最早试点的那 24 张卡**（due 1631950–1632031 挤在最前，rank 却是
4/849/1565/…/9697 混排）；其余 1,882 张本来就是按 rank 顺序建的（建卡顺序＝rank 序）。
插件跑完后这个比例应降到 0。

---

## 6. 与旧路径的关系

[ADR](decisions/2026-10-jitenanimerank仅作注解.md) 写的
`make_activate_plan.py … --global` → `activate.py apply --global`
（`python code\cli.py vocab reorder-jiten`）那条路，**阶段三 activate 已于 2026-10-12 退役**
（见 [pipeline-guide.md](pipeline-guide.md)），别再执行。
现在「按词频排新卡位置」的**唯一入口就是这个插件**。
