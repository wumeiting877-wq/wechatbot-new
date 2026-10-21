# P9-G5 Authorization Policy Design

> Policy：`TASK_ASSIGNEE_ONLY_V1`

## 决策对象

`AuthorizationDecision` 保存：status、action_type、actor_ref、actor_person_id、target_type、target_id、target_person_id、reason、policy。它不是 Action 主键，也不写入 Action Record。

## Prepare

目标必须先被现有 Target Resolver 唯一解析。随后 Authorizer 只用保存前已确定的 `conversation_id + task_id` 检查负责人。拒绝时 Business Action 返回：

```text
status = NOT_AUTHORIZED
reason = 具体 AuthorizationDecision.status
0 PREPARED
0 lifecycle
```

授权位于状态适用性检查之前，避免向未授权者披露 DONE 等业务状态。

## Confirm

`BusinessActionStore.commit_confirmation` 先在 Action lock 内校验记录存在、状态为 PREPARED、确认 actor_ref 与准备 actor_ref 一致。只有通过后，Apply callback 才重新授权。授权拒绝通过内部异常中止提交：

- 生命周期不调用；
- Action 保持 PREPARED；
- Task 不变；
- 写入 `ACTION_REJECTED` 审计；
- 返回 `NOT_AUTHORIZED` 与稳定 reason。

确认只使用记录里的 `target_task_id`，不重新解析标题。Actor mismatch 比授权优先。

## 幂等与兼容

- Action ID 仍仅由 conversation_id、message_id、action_type、target_task_id 组成；
- Action Record 仍保留原 actor_ref；
- actions.json schema_version 不变；
- 旧 PREPARED 在确认时自动进入新授权检查；
- 已终态 Action 继续按既有幂等规则返回，不重复生命周期。
