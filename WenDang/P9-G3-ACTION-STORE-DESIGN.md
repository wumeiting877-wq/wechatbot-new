# P9-G3 Action Store Design

> 日期：2026-09-23

Action Record 是当前状态、幂等和崩溃恢复的真值。Audit 不是。

## 1. 文件

```text
data/business_actions/actions.json
data/business_actions/actions.json.lock
```

文档形状：

```text
{
  schema_version: 1
  actions: {
    act_<hash>: BusinessActionRecord
  }
}
```

`BusinessActionRecord` 含：

```text
action_id
action_type
conversation_id
message_id
actor_ref
target_task_id
target_title
expected_status
target_status
state
created_at
confirmed_at
completed_at
result_status
result_reason
```

文件不存在表示空存储，可以写入第一条 `PREPARED`。`NO_ACTION_NEEDED`、`AMBIGUOUS`、`NOT_FOUND` 和不支持的 selector 不创建这个文件。

## 2. 状态

```text
PREPARED
EXECUTED
SUCCEEDED_NOOP
FAILED
```

`PREPARED` 表示目标已经唯一解析，当时任务是 `OPEN`，仍在等待确认。任务本身保持 `OPEN`。

`EXECUTED` 表示这次确认把任务从 `OPEN` 写成了 `DONE`。

`SUCCEEDED_NOOP` 表示确认时任务已经是 `DONE`，生命周期返回 `ALREADY_IN_STATE`，文件没有再次修改。

`FAILED` 表示这次确认没有把任务写成 `DONE`。原因来自生命周期，例如 `STALE_STATE`、`WRITE_FAILED`、`TASK_NOT_FOUND`。

## 3. 损坏

`actions.json` 存在但 JSON 无法解析、`schema_version` 不是 1、`actions` 不是对象，或记录的 `action_id` 与键不一致，都是 `CORRUPT`。

损坏时准备和确认都拒绝执行。不把文件当成空存储，不重新创建，不调用 `complete_task`。原字节保留。

## 4. 幂等

准备：同一个指纹再次进入时返回已有记录，不改 `created_at`，不写第二份。

确认：`EXECUTED` 或 `SUCCEEDED_NOOP` 再次确认返回 `ALREADY_EXECUTED`，生命周期调用为 0。

`FAILED` 再次确认不调用生命周期，不自动重试。要再执行，必须使用新的 `message_id`，从而得到新的 `action_id`。

## 5. 锁

确认路径在 `FileLock(actions.json.lock)` 内完成三件事：读状态、调用 `apply`、把终态 `os.replace` 到 `actions.json`。

`apply` 只调用 `TaskLifecycleService.complete_task`。生命周期再获取 `tasks.json` 的锁。顺序固定为：

```text
actions.json.lock
↓
tasks.json.lock
```

`task_store.py` 和 `task_lifecycle.py` 不引用 Business Action，因此没有反向路径。并发的两个 `confirm_action` 里，只有先进入该临界区的一次会调用生命周期。另一条看到已经写好的终态。

## 6. 崩溃恢复

若生命周期已经把 `OPEN` 写成 `DONE`，但 Action 终态没能落盘，记录保持 `PREPARED`。这次调用返回 `RECORD_PERSIST_FAILED`，并带上生命周期的 `TRANSITIONED`。任务已经是 `DONE`。

下一次 `confirm_action` 仍读到 `PREPARED`，再次进入 `complete_task`，得到 `ALREADY_IN_STATE`，然后把记录收成 `SUCCEEDED_NOOP`。这次不会把任务文件再写一遍，也不会把结果说成「失败所以任务没完成」。

同一条确认不会在落盘失败后自动再调一次生命周期。恢复发生在下一次明确的 `confirm_action`。
