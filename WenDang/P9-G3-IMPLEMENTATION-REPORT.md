# P9-G3 Implementation Report

> 日期：2026-09-23

## 1. 新增

```text
business_action.py
business_action_store.py
business_action_audit.py
tests/test_p9g3_business_action.py
```

`BusinessActionService.prepare_action` 接收 `ActionRequest`。`confirm_action(action_id, actor_ref)` 是唯一执行入口。

`COMPLETE_TASK` 的成功 Preview 展示操作、任务标题、当前 `OPEN` 和目标 `DONE`。准备阶段不调用生命周期。

Action ID 由会话、消息、动作类型和 `target_task_id` 的长度前缀拼接后做 SHA1，前缀为 `act_`。

## 2. 执行与恢复

确认在 `actions.json.lock` 内调用 `TaskLifecycleService.complete_task`。生命周期自己再锁 `tasks.json`。任务模块不反向获取 Action 锁。

`TRANSITIONED` 写成 `EXECUTED`。`ALREADY_IN_STATE` 写成 `SUCCEEDED_NOOP`。`STALE_STATE`、`WRITE_FAILED`、`TASK_NOT_FOUND` 写成 `FAILED`，不覆盖任务，也不自动重试。

终态落盘失败时返回 `RECORD_PERSIST_FAILED`，磁盘上的记录仍是 `PREPARED`。下一次确认把已经完成的任务收成 `SUCCEEDED_NOOP`。

Audit 追加失败不影响已经成功的 Task 和 Action Record。

`actions.json` 损坏时返回 `CORRUPT`，原文件保留，生命周期调用为 0。

## 3. 未改的路径

未改：

```text
query_router.py
collaboration_query.py
message/listener.py
query_intent_classifier.py
agent_reply_delivery.py
query_service.py
query_formatter.py
task_lifecycle.py
task_store.py
task_target_resolver.py
task_identity_link.py
task_engine.py
```

这些文件不引用 `business_action`。四个 Engine 常量未改。

Business Action 源码不含 `send_reply`、`SendMsg`、`query_intent_classifier`、Extractor、`update_task`、`transition_task_status`。状态写入只出现为 `complete_task`。

## 4. 微信

「帮我把任务改成完成」仍是原来的固定拒绝。Business Action、Resolver、生命周期调用都是 0。

「接口联调今天已经完成了」仍是普通聊天。任务保持 `OPEN`。离线 Extractor 仍是 `UNRELATED`。
