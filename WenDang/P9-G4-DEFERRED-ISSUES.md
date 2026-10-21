# P9-G4 Deferred Issues

> 日期：2026-09-24

本 Gate 明确不处理：

- LLM Command Classifier、语义解析、模糊标题；
- CURRENT_TASK、LAST_TASK、RECENT_TASK、聊天序号和稳定短编号；
- 取消 Action，以及 CANCELLED / EXPIRED Action State；
- CREATE/UPDATE/START/CANCEL/REASSIGN_TASK；
- Risk Close、Decision Transition、Topic Resolve、Delete；
- RBAC、负责人权限、审批和代确认；
- Evidence COMPLETED_BY 与 Reminder。

下一 Gate 应根据真实运行结果，在 Action Authorization / RBAC 与 Task Command UX / Stable References 之间选择，不在本轮扩大动作类型。

