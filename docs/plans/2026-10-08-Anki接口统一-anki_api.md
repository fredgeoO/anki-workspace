# 统一 Anki 访问接口（`code/common/anki_api.py`）—— 结论

> 状态：active ｜ 最后核实：2026-11-09
>
> （重构已于 2026-10-08 落地并验收，本文件已压缩为结论）

## 背景

AnkiConnect 传输层与 `findNotes → notesInfo` 分块循环在全仓被抄了 26+ 份，超时、URL 来源、
失败语义各写各的；离线读快照另有约 20 处各自 `sqlite3.connect`。目标：收敛为唯一入口
`code/common/anki_api.py`（在线 AnkiConnect + 离线只读 `Snapshot`），行为不变，并配
`audit` 防回退扫描（`127.0.0.1:8765` / `def anki(` 归零）。

## 最终落地结果

- 新增 `code/common/anki_api.py`；第一期迁移 12 个常跑链路文件 + README，全部完成。
  现在全仓 90+ 个脚本 `import anki_api as AK`（AGENTS.md 铁律 1：Anki 唯一入口）。
- `audit` 长期保持 **0 阻塞**；第二期机械替换（analysis / vocab_cover / oneshot）也已陆续完成。
- 顺带修掉一处快照解码 bug：旧实现借用游标导致 notetype 名全部退化成 `?`，
  `Snapshot.notetype_map()` 改为一条 JOIN 查询取完再分组。
- 已知遗留（当时的）：两个删不掉的 ACL 坏目录；本地模型客户端当时未收口
  （后由 [decisions/2026-11-01-三内核与写库收口.md](../decisions/2026-11-01-三内核与写库收口.md) 处理）。

## 指针

- 机制与用法：[docs/architecture.md](../architecture.md)、[code/README.md](../../code/README.md)。
- 防回退口径：`& $PY code\common\anki_api.py audit`（0 = 干净），已收进 `doctor`。
- 迁移前的手工客户端写法属历史，只记 [docs/deprecated.md](../deprecated.md)。
