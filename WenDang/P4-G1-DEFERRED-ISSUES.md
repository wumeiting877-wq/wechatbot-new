# P4-G1 延期事项

> 日期：2026-09-21  
> 阶段：P4-G1 执行中看到、**不属于 G1** 的问题。本轮禁止顺手实现。

---

| ID | 项 | 说明 |
|---|---|---|
| D1 | Task 真机 Side-path | Topic 成功后触发 Task Engine。需单独授权解冻 `topic_sidepath.py` 或 `listener.py`。G1 未接。 |
| D2 | `due_at` 确定性解析 | 以消息时间为锚解析「今天 16 点前」。失败保持空。禁止让 LLM 填。 |
| D3 | 企业通讯录 / `assignee_id` / `assignee_type` | 当前无目录，禁止伪造。v1 只存 `assignee_text`。 |
| D4 | 自动 DONE / IN_PROGRESS / CANCELLED | 完成陈述目前 UNRELATED，OPEN 会累积（LIMITATION L5）。 |
| D5 | `COMPLETION_EVIDENCE` | 留给将来 DONE，现在写入会诱使自动完成。 |
| D6 | 跨 Topic 改挂 | CASE-T04 两个事项同挂当前主 Topic（P3 单主 Topic 遗产）。 |
| D7 | Reminder 融合 / 催办 / 自动通知 / 发微信 | Reminder 仍是另一系统；Task 禁止 `send_reply`。 |
| D8 | Risk Engine | 未开始。 |
| D9 | Decision Engine | 未开始。 |
| D10 | Progress / 日报 | 未开始。 |
| D11 | Task Dashboard / Topic Dashboard | 未开始。 |
| D12 | RAG / Embedding / Vector DB / SQLite | 未开始。 |
| D13 | 升 `task_processing_version` 的 Prompt 重抽 | hash 变了默认不重跑。 |
| D14 | Conversation 删除时级联 Task 目录 | G1 提供 `delete_conversation_task_data`；未改 P3 delete。 |
| D15 | 真实 LLM Task Extractor 联调 | G1 用 Heuristic 跑 fixture 红线。真机模型不是本轮必须项。 |

G1 已知并接受的 LIMITATION 见 `P4-TASK-GAP-REPORT.md` L1–L11，本轮未试图修复。
