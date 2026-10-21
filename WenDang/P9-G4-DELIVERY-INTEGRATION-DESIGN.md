# P9-G4 Delivery Integration Design

> 日期：2026-09-24

Preview、固定错误和确认结果统一构造 `AgentReplyPlan(kind=FIXED)`，通过 `offer_agent_reply` 进入现有 AgentReplyDelivery，最终调用 `send_reply`。

不直接调用微信 `SendMsg`。会话忙时，Preview 或结果进入 pending 队列；会话释放后补发。Preview 暂存期间 Action 可保持 PREPARED，但 Task 仍为 OPEN；只有 `confirm_action` 可以触发生命周期。

投递失败只记录普通日志，不复制 Business Action Audit。`ACTION_PREPARED`、`ACTION_CONFIRM_REQUESTED`、`ACTION_EXECUTED` 等仍完全由 P9-G3 负责。

