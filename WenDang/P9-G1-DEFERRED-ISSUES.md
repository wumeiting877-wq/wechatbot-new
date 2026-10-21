# P9-G1 Deferred Issues

> 本 Gate 只交付 `OPEN → DONE`。下面留到后续 Gate。

## 1. 状态表

```text
OPEN → IN_PROGRESS
OPEN → CANCELLED
DONE 的 reopen / cancel / restart
IN_PROGRESS → DONE
IN_PROGRESS → CANCELLED
CANCELLED → OPEN
```

这些常量还在，迁移结果仍是 `INVALID_TRANSITION` 或 `STALE_STATE`。

## 2. 其它对象

```text
Risk close / resolve / mitigate
Decision status transition
Topic resolve / archive
```

Risk 仍只写 `OPEN`。Decision 仍只写 `RECORDED`。Topic 生产 Engine 仍不改 status。

## 3. 动作链

```text
Target Resolver
Command Router 接入生命周期
Confirmation
BusinessActionAudit
Reassign Task
Delete
```

微信「帮我把任务改成完成」仍是固定拒绝。完成陈述不会自动把 Task 写成 `DONE`。本 Gate 不记录 `COMPLETED_BY`。

`update_task` 与 `commit_apply` 仍是锁外读入整表、锁内再整文件替换。两个 `transition_task_status` 彼此在同一把锁里重读，不会互相覆盖。旧的整表写如果与迁移交错，仍可能用过期快照盖回文件。Engine 关闭，生产路径目前不会并发打到 `commit_apply`。收紧旧写路径留到以后，不借 `commit_apply` 的 status 直赋来完成任务。

## 4. 查询产品

`LIST_TASKS` 继续包含 `DONE`。是否改成只看未完成任务，留给以后的 Query 定义。微信回复仍不展示 `task_id`。

## 5. 下一 Gate 未选

本轮停在生命周期合同。下一步在下面两条里再定，本轮不执行：

```text
P9-G2 — Task Target Resolution
P9-G2 — Business Action Foundation
```
