# P9-G1 Task Lifecycle Design

> 第一版正式流转只有 `OPEN → DONE`。`DONE` 是终态。

## 1. 两个入口

普通字段更新仍走 `TaskStore.update_task`。它见到非空 `status` 继续抛 `INVALID_STATUS`。

生命周期走专用入口：

```text
TaskLifecycleService.complete_task(conversation_id, task_id)
  → TaskStore.transition_task_status(
        conversation_id,
        task_id,
        expected_status=OPEN,
        target_status=DONE,
    )
```

`complete_task` 只表达「把仍为 OPEN 的任务完成」。非法目标不从这里传入。表本身放在 Store，避免调用方绕过服务时把 `IN_PROGRESS` 或 `CANCELLED` 写成合法流转。

v1 表：

```text
ALLOWED_TASK_TRANSITIONS_V1
OPEN → DONE
```

## 2. 锁内顺序

`transition_task_status` 持有 `tasks.json.lock` 期间重新读取文件。锁外看到的 status 不参与判断。

```text
解析失败，或 tasks 不是对象列表 → CORRUPT
找不到 task_id → TASK_NOT_FOUND
current == target → ALREADY_IN_STATE
current != expected → STALE_STATE
(current, target) 不在 v1 表 → INVALID_TRANSITION
否则改 status、刷新 updated_at → tmp + os.replace → TRANSITIONED
replace 或写 tmp 失败 → WRITE_FAILED
```

除 `TRANSITIONED` 以外都不替换 `tasks.json`。`created_at`、描述、负责人文本、消息链接、processing、`TaskIdentityLink` 都不在这次写入里。

`current == target` 放在 `expected_status` 之前。`complete_task` 固定期望 `OPEN`。任务已经是 `DONE` 时，再完成一次是幂等的 `ALREADY_IN_STATE`，不改 `updated_at`，也不打生命周期日志。两个调用都期望 `OPEN` 时，先完成的得到 `TRANSITIONED`，后执行的重读到 `DONE`，得到 `ALREADY_IN_STATE`。

`expected_status` 用在「还需要改 status」的时候。当前既不是期望值，也还不是目标值，返回 `STALE_STATE`，避免把别人改过的任务静默盖成 `DONE`。例如文件里已经是 `CANCELLED`，`complete_task` 返回 `STALE_STATE`。

期望值与当前一致、但配对不在 v1 表时，返回 `INVALID_TRANSITION`。因此这些仍然非法：

```text
OPEN → IN_PROGRESS
OPEN → CANCELLED
DONE → OPEN
DONE → IN_PROGRESS
DONE → CANCELLED
IN_PROGRESS → DONE
IN_PROGRESS → CANCELLED
CANCELLED → OPEN
CANCELLED → DONE
```

## 3. 结果

```text
TaskTransitionResult
  status
  conversation_id
  task_id
  from_status
  to_status
  task
```

成功和幂等、非法、过期会带上当时读到的 task 副本。`CORRUPT`、`TASK_NOT_FOUND`、`WRITE_FAILED` 的 `task` 为空。`WRITE_FAILED` 在返回前把内存里的 status 改回原值；文件仍是 replace 之前的字节。

成功时打一条普通日志：`Task lifecycle transitioned`。不写 `operations_action_audit`，不写 `UPDATED_BY` / `COMPLETED_BY`。

## 4. 损坏文件

`read_json` 在解析失败时返回默认空列表，并且不写回。迁移如果沿用这个空列表再保存，会把损坏文件盖成空任务表。

迁移因此单独读：JSON 无法解析，或 `tasks` 不是对象列表，返回 `CORRUPT`，原字节保留。文件不存在则视为没有这张任务，返回 `TASK_NOT_FOUND`，不创建文件。

## 5. 刻意不接的层

`task_lifecycle.py` 只调用 Task Store。不解析自然语言，不识别微信 Command，不发送微信，不调用模型，不解析人员，不改 `TaskIdentityLink`。

Command Router、QueryService、Task Engine、Extractor 提示词都不调用这个服务。完成任务仍是以后的显式 Action，不是业务句子的自动抽取。

`commit_apply` 的字段直赋保持原样，生命周期不走那条缝。

## 6. 查询

`LIST_TASKS`、`MY_TASKS`、`TASKS_BY_ASSIGNEE` 继续返回已落盘任务。`DONE` 仍出现在列表里。Formatter 打印 `状态：DONE`。本 Gate 不增加 `task_id` 展示。
