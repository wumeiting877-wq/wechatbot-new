# P9-G3 Confirmation Contract

> 日期：2026-09-23

正式执行只有一个入口：

```text
confirm_action(action_id, actor_ref)
```

`prepare_action` 返回之后不会自动 Apply。

## 1. 谁可以确认

v1 要求确认者与准备者是同一个 `actor_ref`。不一致返回 `ACTOR_MISMATCH`，不调用生命周期，记录保持 `PREPARED`。原来的 Actor 仍可以随后确认。

空 `actor_ref` 返回 `ACTOR_REQUIRED`，不执行。

这里不判断组织角色。审批或代确认不在本 Gate。

## 2. 执行路径

```text
读取 Action Record
确认 state = PREPARED
确认 actor_ref
TaskLifecycleService.complete_task(conversation_id, target_task_id)
写入 Action 终态
```

目标来自记录里的 `target_task_id`。确认阶段调用 Resolver 的次数是 0。

## 3. 生命周期结果

| `complete_task` | Action |
| --- | --- |
| `TRANSITIONED` | `EXECUTED` |
| `ALREADY_IN_STATE` | `SUCCEEDED_NOOP` |
| `STALE_STATE` | `FAILED`，原因 `STALE_STATE`，不覆盖任务 |
| `WRITE_FAILED` | `FAILED`，原因 `WRITE_FAILED`，不标成 `EXECUTED` |
| `TASK_NOT_FOUND` | `FAILED`，原因 `TASK_NOT_FOUND` |
| 其它 | `FAILED`，原因沿用生命周期状态 |

`WRITE_FAILED` 和 `FAILED` 都不会由同一次 Action 自动重试。

Preview 时是 `OPEN`、确认前已被别人完成时，走 `ALREADY_IN_STATE → SUCCEEDED_NOOP`。任务文件在这次确认中不再修改。

Preview 时是 `OPEN`、确认前变成 `IN_PROGRESS` 或 `CANCELLED` 时，走 `STALE_STATE`。任务保持那个状态。

## 4. 没有确认

只调用 `prepare_action` 时，`complete_task = 0`，`transition_task_status = 0`，任务保持 `OPEN`。

## 5. 不在本契约里的确认

不识别「确认」「是」「执行」「好的」。不存在当前会话的待确认指针。微信不会收到 Preview 或执行结果。
