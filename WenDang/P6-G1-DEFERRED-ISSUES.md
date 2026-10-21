# P6-G1 延期事项

> 日期：2026-09-22  
> P6-G1 = **COMPLETE**。下列不是本轮 BLOCKER。

---

## 本轮关闭

| ID | 项 | 结果 |
|---|---|---|
| Topic replay fan-out | Topic replayed SUCCESS 仍 fan-out Task/Decision/Risk | **CLOSED**。`replayed=true` 不再入下游 Queue |

---

## Deferred / NON-BLOCKER

| ID | 项 | 说明 |
|---|---|---|
| force_reprocess | 显式重跑同一 MessageRecord | 本阶段禁止实现。FAILED Topic 仍可因「非 successful processing」自然重跑；SUCCESS replay 不再顺带重试下游 |
| 下游 FAILED 的独立重试 | Topic 已 SUCCESS、Task/Decision/Risk 曾 FAILED | 修复前依赖 Topic replay 顺便再 enqueue。那不是设计补偿。需要时另开指令，不要借用 replay |
| DJ-R8 / RK-R9 | 书面 CASE vs 模型 | 继续 Deferred。禁止改 EXTRACTOR |
| LIVE-L2 / L5 | 真机补一手 | P6-G1 纯幂等，不需要真机 |
| §16 全链路字段 | trace_id / local_id 统一 | OBS 可选。本轮只加 `TOPIC_REPLAY` 事件 |

---

## 明确不做（仍禁止）

| 项 | 说明 |
|---|---|
| 正文时间窗 / hash / 模糊去重 | 会把 N2 修坏 |
| 生产长期 ENABLE 四个 Engine | 保持 false |
| 改 Trigger / Self / Dedupe / Outbound / Chat Prompt | 冻结 |
| 改四个 EXTRACTOR schema | 冻结 |
| 新 Queue / Worker / Dashboard / 催办 / RAG | 冻结 |

不生成 `P6-G1-BLOCKER-REPORT.md`：replay **不是**下游补偿设计。
