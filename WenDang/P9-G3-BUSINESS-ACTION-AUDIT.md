# P9-G3 Business Action Audit

> 日期：2026-09-23

Audit 只追踪业务动作。Task 的当前状态仍以 Task Store 为准。Audit 不能用来修补 Task。

## 1. 文件

```text
data/business_actions/business_action_audit.jsonl
```

这不是 `data/operations/operations_action_audit.jsonl`。运维 Retry 审计保持原样。P8 Query 不读这份文件。删掉审计文件之后，`MY_TASKS` 仍从 Task Store 和 `TaskIdentityLink` 读到 `DONE`。

## 2. 事件

```text
ACTION_PREPARED
ACTION_CONFIRM_REQUESTED
ACTION_EXECUTED
ACTION_NOOP
ACTION_FAILED
ACTION_REJECTED
```

每条至少有：

```text
ts
event
action_id
action_type
conversation_id
message_id
actor_ref
target_type = TASK
target_id
before_status
after_status
result
reason
```

因此一条记录可以回答：谁、什么时候、哪个 Task、什么 Action、结果。目标不唯一时 `target_id` 为空，不从候选里挑一个写进审计。

成功确认会留下 `ACTION_CONFIRM_REQUESTED` 和 `ACTION_EXECUTED`。`before_status = OPEN`，`after_status = DONE`。

已经完成的任务被确认时留下 `ACTION_NOOP`，前后状态都是 `DONE`。

歧义、Actor 不匹配、类型不允许、缺少 Actor 或 `message_id`，留下 `ACTION_REJECTED`。`STALE_STATE`、`WRITE_FAILED`、`TASK_NOT_FOUND` 留下 `ACTION_FAILED`。不匹配事件里的 `actor_ref` 是这次尝试确认的人。

重复确认不再写第二条 `ACTION_EXECUTED` 或 `ACTION_NOOP`。

## 3. 写失败时业务怎么处理

执行业务写之前，`PREPARED` 记录已经在 `actions.json`。

业务写成功之后，Action Record 的终态是恢复和幂等的依据。Audit 追加失败只记一条警告，不回滚已经成功的 Task，也不把已经写成 `EXECUTED` 的 Action Record 改回去。

Action 终态本身写失败时，记录保持 `PREPARED`，调用返回 `RECORD_PERSIST_FAILED`。这不是「任务没完成」。下一次确认按生命周期的 `ALREADY_IN_STATE` 收成 `SUCCEEDED_NOOP`。

## 4. 两者的分工

```text
BusinessActionRecord  当前状态、幂等、崩溃恢复
BusinessActionAudit   事件历史
```

查询、Processing、Evidence、Identity Link 都不读 Audit，也不写 Audit。
