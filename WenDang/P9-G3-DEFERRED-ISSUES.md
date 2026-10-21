# P9-G3 Deferred Issues

> 本 Gate 只交付结构化 `COMPLETE_TASK` 的准备、确认、幂等和审计。下面留到后续 Gate。

## 1. 对话层

```text
自然语言 Command Parser
微信 Confirmation
pending confirmation state
```

不处理「确认」「是」「执行」「好的」。不建立 `chat_id → pending action`。微信仍不调用 Business Action。

下一阶段才考虑：

```text
P9-G4 — Task Command Intent & Confirmation Conversation
```

那时候才会把「把接口联调标记为完成」收成 Command Intent、Preview，以及用户确认后再调用本 Gate 的服务。

## 2. 尚未支持的指向

```text
CURRENT_TASK
LAST_TASK
RECENT_TASK
INDEX_FROM_CHAT
稳定短编号
FUZZY_TITLE
SEMANTIC_TITLE
```

这些仍由 Resolver 返回 `UNSUPPORTED_REFERENCE` 或根本不进入 v1 selector。Action 层不开始猜测。

## 3. 其它命令

```text
CREATE_TASK
UPDATE_TASK
START_TASK
CANCEL_TASK
REASSIGN_TASK
Risk Close
Decision Transition
Topic Resolve
Delete
```

v1 一律 `ACTION_TYPE_NOT_ALLOWED`，不创建 Action。

## 4. 权限与附属模型

```text
RBAC
组织权限
审批 / 代确认
Reminder
Evidence：COMPLETED_BY / UPDATED_BY
```

v1 只核对准备者和确认者是不是同一个 `actor_ref`。

## 5. 仍保留的旧窗口

P9-G1 已记录：`update_task` / `commit_apply` 存在锁外读整表、锁内替换的旧并发窗口。本 Gate 没有改那条路径。Business Action 的状态写入只走 `TaskLifecycleService`。

`FAILED` 之后的重试也没有单独契约。同一个 `message_id` 不会再执行；新的执行需要新的业务动作身份。
