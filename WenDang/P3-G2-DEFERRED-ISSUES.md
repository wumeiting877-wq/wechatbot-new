# P3-G2 延期事项

> 日期：2026-09-21

---

## 本轮未完成（不阻塞关闭）

| 项 | 说明 |
|---|---|
| 真机 R9 重复 callback | wxauto 未打出重复 callback；Duplicate 由 CASE-S5 覆盖 |
| 正式长期开启 `TOPIC_ENGINE_ENABLED` | 默认保持 false，直到明确指令 |
| DISABLED 跳过写审计 | 关闭后直接 return，未写 `TOPIC_SIDE_PATH_SKIPPED`；入库停止已用 Store 证明 |

---

## 已完成（不再延期）

| 项 | 说明 |
|---|---|
| 真实 MODEL 语义 CASE-01～07 | **PASS** |
| 真机 R1～R8 / R10～R12 | **PASS** |
| QIYE Agent `extractor_prompt_name=TOPIC_EXTRACTOR` | 已绑定；`chat_prompt_name` 未改 |
| Bot `install_into` 导出 Extractor 辅助函数 | 真机首轮 NameError 已修 |

---

## 不属于本轮

| 项 | 说明 |
|---|---|
| P4 Task / Risk / Decision / Owner / Due | 禁止 |
| Topic UI / Dashboard | 禁止 |
| 自动 RESOLVED | v1 只创建 ACTIVE |
| 使用 `UPDATE_ONLY` Trigger | 禁止接线 |
| 改 `QIYE.md` / `企业_1.md` | 禁止 |
| `chat_contexts` 仍按 nickname 分键 | P1 残留 |
