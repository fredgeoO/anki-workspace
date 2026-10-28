# 备份 SOP：anki-workspace + Anki 学习资料

> 状态：active ｜ 最后核实：2026-10-28

**这是什么**：备份与恢复的唯一权威流程（工作区 + Anki 收藏库/媒体/插件 → G: 盘）。
**为什么存在**：备份做错比不做更糟（收藏库带 -wal 时副本不一致、旧备份先删就没了），
所以步骤、校验判据、恢复路径都写死在这里。
**什么时候读**：要备份/恢复时；换机器或大改库之前。

- 最近一次执行：**2026-10-09 08:2x**，目标 `<备份盘>:\anki-backup-2026-10-09`（见 §8 台账）
- 上一份备份 `<备份盘>:\anki-backup-2026-10-04` 已在本次备份校验通过后删除（保留策略见 §4.1）
- 备份介质：**G: 盘**（非系统盘，与工作区/Anki 数据不在同一物理盘）

---

## 0. TL;DR（记不住就照这一段做）

```powershell
# 0) 先完全退出 Anki（含托盘图标）——这是唯一必须人工做的一步
# 1) 一条命令做完：建目录 + robocopy 六棵树 + 校验 + 写 manifest
& $PY code\tools\backup_anki.py --dest <备份盘>:\anki-backup-<当天日期>
```

跑完看它最后打印的 **VERIFY** 段：每棵树「源↔备份 文件数/字节数一致」
+ 收藏库 **SHA256 与源库逐字节相同** + notes/cards/revlog 计数与源一致，就算成功。
任一项不一致 → 不要删旧备份，按 §7 排查。

> 在 DSH 会话里，G: 盘属于会话工作区之外，命令会先要一次「更宽的文件权限」的批准，
> 属正常现象。你自己开 PowerShell 窗口跑则没有这一层。

---

## 1. 什么时候备份

| 触发条件 | 说明 |
|---|---|
| 每隔几天 / 每次做完一集素材流水线后 | 常规节奏，成本约 1–3 分钟（G: 盘是本地盘） |
| 大改动之前 | 迁移、批量改字段、改牌组配置、清媒体库之前 |
| 感觉「这段时间学了很多」时 | revlog 是真正无法重建的东西 |
| 换机器 / 重装系统之前 | 必做 |

**不要依赖的东西**：`data/snapshots/` 里的快照是分析用的、不是备份（会被脚本覆盖重写）；
Anki 自己 `backups/` 里的 colpkg 只是滚动备份（默认最多保留若干份，且**不含媒体**）。

---

## 2. 要备份什么（四类、六棵树）

| # | 备份目录 | 是什么 | 源路径 | 丢失后果 |
|---|---|---|---|---|
| 1 | `workspace\` | 整个 anki-workspace | `<工作区根>` | 代码/报告/字幕/中间产物全没 |
| 2 | `anki-collection\` | **学习进度本体**：收藏库 + 媒体索引 + 界面偏好 | `%APPDATA%\Anki2\账户 1\` 的 4 个文件 + `%APPDATA%\Anki2\prefs21.db` | **复习记录、排期、卡片内容全没**（最致命） |
| 3 | `anki-media\collection.media\` | 卡片音频/图片 | `%APPDATA%\Anki2\账户 1\collection.media` | 卡片还在但没声音/图 |
| 4 | `anki-backups\` | Anki 自动滚动备份（colpkg，可导入） | `%APPDATA%\Anki2\账户 1\backups` | 少一层保险 |
| 5 | `anki-addons\addons21\` | 插件与插件配置（含 AnkiConnect） | `%APPDATA%\Anki2\addons21` | 重装插件、丢 AnkiConnect 配置 |

外加写入目标根目录的 `README-备份说明.md`，和 `_verify\`（manifest + robocopy 原始日志）。

**明确不备份**（有意排除，写在命令里）：

| 排除项 | 原因 |
|---|---|
| 工作区 `**\__pycache__\` | Python 字节码缓存，自动重建 |
| 工作区 `temp\` | 一次性文件区（临时脚本/dump/日志），随时会被 `cli.py temp clean` 清掉，无需进备份（2026-10-20 起） |
| `%APPDATA%\Anki2\账户 1\media.trash\` | Anki 的「已删媒体」回收站（本次约 926 MB），**作为可选恢复源**，默认不备份（见 §5.2 ③） |
| 系统临时/回收站 | — |

**体积参考**（2026-10-09 实测，用于估算空间）：

| 项 | 文件数 | 大小 |
|---|---|---|
| workspace | 3600 | 996.8 MB |
| anki-collection（含 prefs21.db） | 4 | 49.3 MB |
| anki-media | 44832 | 1.15 GB |
| anki-backups | 51 | 401.5 MB |
| anki-addons | 940 | 51.0 MB |
| **内容合计** | **49427** | **约 2.6 GB** |
| 加上 `_verify\`（manifest + 6 份日志）与 `README-备份说明.md` | 49435 | — |

> G: 盘至少要留 **5 GB** 空闲（复制过程需要同时容纳新旧两份时才需要更多；
> 按 §4.1 先删旧备份再把新备份做在同一盘，最省空间）。

**关于 `data\pylibs`（约 320 MB）**：它**在备份范围内**，但不值得为它担心 ——
丢了可以用 `python code/oneshot/install_workspace_wheels.py` 重装
（sudachipy + sudachidict_core + matplotlib）。

---

## 3. 执行前的检查（Pre-flight）

1. **Anki 完全退出**（含托盘）。判断方法：

   ```powershell
   (Test-NetConnection 127.0.0.1 -Port 8765 -InformationLevel Quiet)   # 应为 False
   ```

   AnkiConnect 还有响应（返回 `True` / `version` 能取到版本号）就说明 Anki 还开着，
   此时 `collection.anki2` 被占用、`-wal` 还在长 —— **不要开始备份收藏库**。

   为什么必须关：Anki 用 WAL 模式，主库文件 + `-wal` 才是一份完整的库；
   运行中复制出来的副本要么直接打不开（`database is locked`），要么是撕裂状态。
   关掉 Anki 时它会自动把 WAL 合并进主库，那一刻复制最干净。

2. **确认源路径存在**（`账户 1` 是带空格的资料夹名，命令里必须带引号）：

   ```powershell
   $P = "$env:APPDATA\Anki2\账户 1"
   Test-Path $P, "$P\collection.anki2", "$P\collection.media", "$P\backups"
   Test-Path "$env:APPDATA\Anki2\addons21"
   ```

3. **确认 G: 盘可写、空闲够**。

4. **记住这一刻**：备份是时间点快照，备份之后新学的卡、新复习记录都不在里面。

---

## 4. 执行

### 4.1 目标目录命名与保留策略

```
<备份盘>:\anki-backup-YYYY-MM-DD\          例：<备份盘>:\anki-backup-2026-10-09
├─ workspace\
├─ anki-collection\
├─ anki-media\collection.media\
├─ anki-backups\
├─ anki-addons\addons21\
├─ _verify\                          manifest.json + robocopy-*.log
└─ README-备份说明.md                 这一份备份的说明 + 恢复步骤
```

- **日期取执行当天** `yyyy-MM-dd`。
- **保留策略：只留最新一份**。做法是**先把新备份做完并校验通过，再删旧的**
  （顺序不能反）：

  ```powershell
  # 校验通过之后才执行；确认路径无误再回车
  Remove-Item -Recurse -Force '<备份盘>:\anki-backup-2026-10-04'
  ```

  想留历史点也行，但 G: 盘每份约 2.6 GB，自己算空间。

### 4.2 一条命令（推荐）

```powershell
$WS = '<工作区根>'
& python "$WS\code\tools\backup_anki.py" --dest <备份盘>:\anki-backup-2026-10-09
```

`code\tools\backup_anki.py` 依次做：建目录 → robocopy 六棵树（各自写日志到 `_verify\`）
→ 离线校验收藏库副本 → 写 `_verify\manifest.json` 与 `README-备份说明.md`。
`--dry-run` 只打印计划不落盘。

### 4.3 手工命令（脚本跑不了 / 只想备份某一棵树时）

以下六条是脚本内部实际执行的命令，可单独用。`robocopy` 的退出码 **0–7 都算成功**
（1 = 有文件被复制），**≥8 才是失败**。

```powershell
$WS  = '<工作区根>'
$ANK = "$env:APPDATA\Anki2"
$DST = '<备份盘>:\anki-backup-2026-10-09'

# 1) 工作区（约 1 GB）——跳过 __pycache__ 与两个沙箱拒绝的空目录
robocopy $WS "$DST\workspace" /E /COPY:DAT /DCOPY:DAT /XJ /MT:16 /R:2 /W:1 `
  /XD __pycache__ live-cfemqh6w probe-mk-c3ozfqej `
  /NP /NDL /NFL /LOG:"$DST\_verify\robocopy-workspace.log"

# 2) 收藏库本体（先关 Anki！）——只挑这几个文件，所以不加 /E；/IF 让其缺失也不报错
robocopy "$ANK\账户 1" "$DST\anki-collection" `
  /IF collection.anki2 collection.anki2-wal collection.media.db2 deleted.txt `
  /COPY:DAT /NP /NDL /NFL /LOG:"$DST\_verify\robocopy-collection.log"

# 2b) 界面偏好（在 Anki2 根目录，不在资料夹里）——与收藏库同一个目标目录
robocopy $ANK "$DST\anki-collection" /IF prefs21.db /COPY:DAT /NP /NDL /NFL `
  /LOG:"$DST\_verify\robocopy-prefs.log"

# 3) 媒体库（约 1.15 GB / 4.5 万文件，最慢的一项）
robocopy "$ANK\账户 1\collection.media" "$DST\anki-media\collection.media" `
  /E /COPY:DAT /DCOPY:DAT /XJ /MT:24 /R:2 /W:1 /NP /NDL /NFL `
  /LOG:"$DST\_verify\robocopy-media.log"

# 4) Anki 自动滚动备份（colpkg）
robocopy "$ANK\账户 1\backups" "$DST\anki-backups" /E /COPY:DAT /DCOPY:DAT `
  /XJ /MT:8 /R:2 /W:1 /NP /NDL /NFL /LOG:"$DST\_verify\robocopy-backups.log"

# 5) 插件（跳过 __pycache__）
robocopy "$ANK\addons21" "$DST\anki-addons\addons21" /E /COPY:DAT /DCOPY:DAT `
  /XJ /MT:8 /R:2 /W:1 /XD __pycache__ /NP /NDL /NFL /LOG:"$DST\_verify\robocopy-addons.log"
```

几处**不显眼但重要**的参数：

| 参数 | 作用 |
|---|---|
| `/E` | 含空目录（工作区有空的占位目录，不加会漏） |
| `/COPY:DAT` / `/DCOPY:DAT` | 拷数据+属性+时间戳（保住 mtime，便于比对） |
| `/XJ` | 不跟随 junction/符号链接（避免被引到别处去，或形成环） |
| `/MT:16`（媒体 `/MT:24`） | 多线程，媒体库提速明显 |
| `/R:2 /W:1` | 失败重试 2 次、间隔 1 秒；默认 100 万次会让它卡死一小时 |
| `/NP /NDL /NFL` | 日志里不刷进度与文件名（日志小、可读） |
| 两个 `/XD` 排除 | `__pycache__` 与 `temp\`（一次性文件区，已由 `WS_EXCLUDE_DIRS` 登记） |

---

## 5. 恢复（怎么把这些东西放回去）

> 恢复前**先备份当前状态**（哪怕已经坏了），别直接覆盖 —— 恢复错方向就没有第二次机会了。

### 5.1 完整恢复

**第一步：完全退出 Anki。**

```powershell
# ① 恢复工作区（把 $DST 换成实际备份目录）
robocopy '<备份盘>:\anki-backup-2026-10-09\workspace' `
         '<工作区根>' `
         /E /COPY:DAT /DCOPY:DAT /XJ

# ② 恢复 Anki 资料夹：先把现有的挪开，绝不直接覆盖
$ANK = "$env:APPDATA\Anki2"
Move-Item "$ANK\账户 1" "$ANK\账户 1.before-restore"
New-Item -ItemType Directory "$ANK\账户 1" | Out-Null

# ③ 收藏库文件（连 -wal 一起；`prefs21.db` 要放到上一层的 Anki2 根目录）
Copy-Item '<备份盘>:\anki-backup-2026-10-09\anki-collection\collection.anki2*' "$ANK\账户 1"
Copy-Item '<备份盘>:\anki-backup-2026-10-09\anki-collection\collection.media.db2' "$ANK\账户 1"
Copy-Item '<备份盘>:\anki-backup-2026-10-09\anki-collection\deleted.txt' "$ANK\账户 1"
Copy-Item '<备份盘>:\anki-backup-2026-10-09\anki-collection\prefs21.db' $ANK

# ④ 媒体库（1 GB+ / 4.5 万文件，耐心等）
robocopy '<备份盘>:\anki-backup-2026-10-09\anki-media\collection.media' `
         "$ANK\账户 1\collection.media" /E /COPY:DAT /DCOPY:DAT /XJ /MT:24

# ⑤ 插件与滚动备份
robocopy '<备份盘>:\anki-backup-2026-10-09\anki-addons\addons21' `
         "$ANK\addons21" /E /COPY:DAT /DCOPY:DAT /XJ /MT:8
robocopy '<备份盘>:\anki-backup-2026-10-09\anki-backups' `
         "$ANK\账户 1\backups" /E /COPY:DAT /DCOPY:DAT /XJ /MT:8

# ⑥ 打开 Anki 检查：牌组/卡数/复习记录/音频都在 → 满意后再删
Remove-Item -Recurse -Force "$ANK\账户 1.before-restore"
```

`prefs21.db`（界面偏好）放在 `%APPDATA%\Anki2\` 下、不在资料夹里 —— 备份里躺在
`anki-collection\prefs21.db`，恢复时按 ③ 的最后一行拷回上一层；它只影响界面，非必需。

### 5.2 分场景的省事做法

| 场景 | 做法 |
|---|---|
| **只要学习进度、媒体回头再说** | Anki「文件 → 导入」选 `anki-backups\` 里最新的 `.colpkg`。注意 colpkg **不含媒体** |
| **只想找回某个音频/图片** | 直接从 `anki-media\collection.media\` 拷单个文件回去 |
| **误删了媒体，想从 Anki 回收站找** | 默认没备份 `media.trash`；如果磁盘上还在，去 `%APPDATA%\Anki2\账户 1\media.trash` 捞 |
| **AnkiWeb 同步一直正常** | 云端本身是一份独立副本，可作第三重保险（同步方向别选错：**下载**才是取回） |
| **只想恢复代码/文档** | 只做 5.1 的 ① |

### 5.3 恢复后自检

1. 打开 Anki，牌组数量、各牌组卡数对得上；
2. 随便点一张有音频的卡，能播；
3. 「统计」里复习记录还在、最新一条日期 ≈ 备份当天；
4. 工作区里 `python code\common\paths.py` 能打印路径；`code\analysis\vocab_cover\` 等脚本能跑。

---

## 6. 校验什么、怎么校验（每次备份都要过这一关）

| 校验项 | 方法 | 通过标准 |
|---|---|---|
| 文件数 / 字节数 | 源与备份各自 `Get-ChildItem -Recurse -File \| Measure-Object Length -Sum` | 六棵树逐项一致 |
| robocopy 结果 | 看 `_verify\robocopy-*.log` 的 `Files :` 行 | `FAILED : 0`（退出码 ≤7） |
| **收藏库指纹** | 备份副本 vs 源库的 **SHA256** | **完全一致（逐字节相同）—— 这是最硬的判据** |
| 学习进度没缩水 | 备份副本 vs 源：notes / cards / revlog 计数 | 完全一致 |
| 最新复习时间 | 备份副本 `select max(id) from revlog` | ≈ 备份时刻（说明录到了关 Anki 前最后一条） |
| 收藏库完整性 | `PRAGMA integrity_check` | `ok` —— **仅供参考，不稳定，见下方说明** |

**收藏库校验要点（重要）**：校验读的是**备份出来的副本**，不是源库 ——
这样既不占用/污染源库，也不需要 Anki 配合。

> **`unicase` 坑（2026-10-09 实测）**：新版 Anki 的 schema 带自定义排序规则
> `unicase`，**系统 Python 自带的 sqlite3 不认识它**。表现为：
> 只拷 `collection.anki2` 时 `PRAGMA integrity_check` 报
> `no such collation sequence: unicase`；用替身规则冒充则进一步报
> `row 1 missing from index idx_notetypes_name`（索引是按真 `unicase` 建的，
> 替身排不出同样顺序）。**这都不代表库坏了** —— Anki 自带的 SQLite 有该规则，能正常打开
> （本次已实际读过备份副本：23 个牌组、4 个笔记类型、17633 notes / 20161 cards / 45577 revlog，
> 最新复习 2026-10-09 07:50:05）。
> **所以判据是 SHA256 逐字节一致 + 计数一致**，`integrity_check` 只当参考；
> 想要权威检查就用 Anki 打开备份副本验一次。

```powershell
$c = '<备份盘>:\anki-backup-2026-10-09\anki-collection\collection.anki2'
python -X utf8 -c @"
import sqlite3, hashlib
db = sqlite3.connect(r'$c')          # 副本可直接读写；不要用 mode=ro（WAL 下会 database is locked）
for t in ('notes','cards','revlog'):
    print('%-9s:' % t, db.execute('select count(*) from %s' % t).fetchone()[0])
print('last rev  :', db.execute('select max(id) from revlog').fetchone()[0])
db.close()
h = hashlib.sha256(open(r'$c','rb').read()).hexdigest().upper()
print('sha256    :', h)
"@
# 与源库比：应完全相同
$src = "$env:APPDATA\Anki2\账户 1\collection.anki2"
python -X utf8 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest().upper())" $src
```

**想在 Anki 开着的时候读学习进度**（不做备份、只做分析）：走
`code/common/anki_api.py` 的 `Snapshot.open(live_copy=True)`，它会把
`collection.anki2` + `-wal` + `-shm` 一起复制到临时目录再读，不碰运行中的库 ——
**不要自己 `sqlite3.connect` 源库**（会 `database is locked`）。

---

## 7. 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `sqlite3.OperationalError: database is locked` | Anki 开着（WAL + `-shm` 占用） | 关掉 Anki，或改用 `Snapshot.open(live_copy=True)` |
| `no such collation sequence: unicase` / `row 1 missing from index idx_notetypes_name` | 标准库 sqlite3 没有 Anki 的自定义排序规则 `unicase` | **不是库坏了**。以 SHA256+计数为准（§6）；要权威检查就用 Anki 打开 |
| 副本打开后条数比 Anki 里少 | 复制时 `-wal` 没带上（或 Anki 正在写） | 关 Anki 重做；务必连 `collection.anki2-wal` 一起拷 |
| 校验时「源库与副本 SHA256 不一致」 | 备份之后又开过 Anki（它 checkpoint 了 WAL） | 正常，重跑一次脚本即可（增量，很快） |
| `New-Item : 对路径 ... 的访问被拒绝` | 目标在 DSH 会话工作区之外（G: 盘），属正常沙箱限制 | 批准一次「更宽的文件权限」，或从自己的 PowerShell 窗口跑 |
| `Test-Path` 找不到 `账户 1` | 路径没加引号（带空格）/资料夹名不是这个 | 用 `"$env:APPDATA\Anki2\账户 1"` |
| robocopy 卡很久不动 | 默认会重试 100 万次 | 一定带 `/R:2 /W:1` |
| 日志里一堆 `ERROR 5 (0x00000005)` | 遇到沙箱拒绝的残留目录 | 用 `/XD` 排除后重跑，其余文件不受影响 |
| 文件名太长报错 | 媒体库存在超长文件名 | 优先用 robocopy（支持长路径）；仍有问题就单独排除该文件并记录 |
| 恢复后音频全丢 | 只导入了 colpkg（不含媒体） | 再按 §5.1 ④ 拷 `collection.media` |
| 脚本报「目标目录已存在且非空」 | 上一次中断/重跑 | 确认是同一份备份就加 `--overwrite`（增量续写） |

---

## 8. 执行台账（每次做完补一行）

| 日期 | 目标目录 | 结果 | 备注 |
|---|---|---|---|
| 2026-10-04 | `<备份盘>:\anki-backup-2026-10-04` | 成功（83167 文件 / 2.63 GB，integrity ok） | 手工执行；当时含 media.trash 等更多文件；已按保留策略删除 |
| 2026-10-09 | `<备份盘>:\anki-backup-2026-10-09` | 成功：49435 文件 / 2.6 GB；六棵树源↔备份一致；收藏库 SHA256 `0BB87F4B…D8B4AE` 与源**逐字节相同**；notes 17633 / cards 20161 / revlog 45577（最新复习 2026-10-09 07:50:05）；备份副本已实际打开复验：23 牌组 / 4 笔记类型 | 首次按本 SOP 执行；脚本 `code\tools\backup_anki.py` 落地 |

> 每次备份的权威数据在**那份备份自己的** `_verify\manifest.json` 里（文件数、字节数、
> SHA256、收藏库计数、最新复习时间），台账这行只是索引。
>
> 2026-10-09 这次是**边定稿本 SOP 边备份**：收藏库/媒体/插件在 08:23:53 那一轮复制，
> 之后改动的 `docs\backup-sop.md`、`README.md`、`code\tools\backup_anki.py` 单独同步进备份，
> `manifest.json` 里 workspace 的字节数按同步后的实际值重算（文件数不变，仍 3600）。
> 下次按 §0 一条命令走完，就不存在这种收尾补同步。

---

## 9. 重打 Release `.apkg`（对外发布导出，不是备份）

> 本节**不是备份流程**：备份走「退出 Anki + robocopy + SHA256 校验」（§0–§6）；
> 发布导出在 **Anki 开着** 时用 AnkiConnect `exportPackage` 出 `.apkg` 给外人导入
> （README §14「整库下载」）。注意：`exportPackage` 一次性导出**整个收藏**可能让
> Anki 直接退出（见 [pipeline-pitfalls](troubleshooting/pipeline-pitfalls.md) 末行），
> 所以按三个子牌组拆着导。

改过卡之后要重新打三个包：deck 名照抄、`path` 用绝对路径，

```powershell
# Anki 开着；includeSched=false = 不导出调度历史（due/ivl/factor/type/queue/reps/lapses 全清零）
$body = '{"action":"exportPackage","version":6,"params":{"deck":"0-日本语学习::0-词汇","path":"<绝对路径>\\1-vocab.apkg","includeSched":false}}'
Invoke-RestMethod http://127.0.0.1:8765 -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($body)) `
  -ContentType 'application/json; charset=utf-8'
```

另外两个同法换 deck 名与文件名：`0-日本语学习::1-语法` → `2-grammar.apkg`、
`0-日本语学习::2-例句` → `3-examples.apkg`。导完替换 GitHub Release 附件
（单附件上限 2 GiB，故按子牌组拆包）。
