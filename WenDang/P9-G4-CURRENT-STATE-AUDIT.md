# P9-G4 Current State Audit

> 日期：2026-09-23
> 进入时：P9-G0 … P9-G3 = COMPLETE。Non-Live = 841 OK。四个 Engine 常量均为 false。

## 1. 已经冻结的写路径

P9-G1 的 `TaskLifecycleService.complete_task` 只接受 `OPEN → DONE`。

P9-G2 的 `TaskTargetResolver` 只接受 `TASK_ID` 和 `EXACT_TITLE`。重复标题是 `AMBIGUOUS`。`CURRENT_TASK` 是 `UNSUPPORTED_REFERENCE`。模糊标题是 `NOT_FOUND`。其它会话的任务不返回。

P9-G3 的 `BusinessActionService.prepare_action` 只写 Action Record。`confirm_action(action_id, actor_ref)` 才调用 `complete_task`。幂等、审计和崩溃恢复都在这一层。

微信入口当时还没有接这三条链。P8 对「帮我把任务改成完成」一类句子返回固定拒绝：

```text
当前不能在这里修改任务、风险或决定。
```

## 2. 接入点

`message/listener.py` 在 `evaluate_inbound` 得到 `REPLY` 之后、协作查询之前，是唯一合适的插入位置。

P9-G3 的源码边界要求 `message/listener.py` 文本里不能出现 `business_action`。因此监听循环调用 `task_command_ingress.handle_task_command_turn`，再由它进入 `handle_business_action_conversation`。

会话 id 继续用 `resolve_topic_conversation`。不用入站 `conversation_id`，也不用窗口名。

发送继续用 `AgentReplyDelivery.offer_agent_reply`，最终落到 `send_reply`。

## 3. 本 Gate 不改的合同

不改 Action 状态机。不增加 `CANCELLED` 或 `EXPIRED`。不改 `confirm_action` 的参数。不让 Task Engine、Topic Engine、Decision Engine、Risk Engine 或 Extractor 参与完成任务。

四个开关保持：

```text
TOPIC_ENGINE_ENABLED=false
TASK_ENGINE_ENABLED=false
DECISION_ENGINE_ENABLED=false
RISK_ENGINE_ENABLED=false
```
