# P9-G4 Confirmation Conversation Design

> 日期：2026-09-24

## 会话顺序

`evaluate_inbound → REPLY` 后依次执行：

```text
P9 confirmation / supported task command
P8 collaboration query / generic command
Topic sidepath
Normal Chat
```

slash command 不由 P9 处理。会话范围只复用已登记 Conversation 的解析结果；Actor 只取 `InboundMessage.sender_wxid`。

## 发起

显式命令先检查 Actor、Conversation、message id，以及同一 `conversation_id + actor_ref + COMPLETE_TASK` 下 180 秒内的 PREPARED。存在新鲜 Pending 时不创建第二条。否则仅调用 `BusinessActionService.prepare_action` 并发送 Preview，Task 保持 OPEN。

## 确认

确认入口只接受 `text.strip() == "确认完成"`。查找范围固定为当前 Conversation、当前 `sender_wxid` 和 `COMPLETE_TASK`：

- 0 条：固定回复无待确认操作；
- 1 条且 180 秒内：调用 `confirm_action(action_id, actor_ref)`；
- 多条：固定歧义回复，不猜最新；
- 只有过期记录：固定超时回复，不修改 Action 状态。

Stop / Emergency Stop 下不确认、不调用 Lifecycle、不发送结果。

