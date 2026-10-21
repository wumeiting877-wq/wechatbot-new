# P9-G0 Deferred Issues

> 本 Gate 只记录，不修。

## 1. 生命周期不足（决定下一 Gate）

```text
Task 生产可写状态 = OPEN
Risk 生产可写状态 = OPEN
Decision 生产可写状态 = RECORDED
Topic 生产 Engine 不改 status
```

因此：

```text
P9-G1 = Lifecycle State Model
不是 Command Router
```

完成任务、开始任务、取消任务、关闭风险、结束主题都 Deferred 到状态模型之后。本轮禁止顺手改 Store。

## 2. 目标解析

```text
TARGET_RESOLUTION GAP
```

没有当前任务指针，没有上次提到的任务，没有任务标题全字解析，微信不展示 `task_id`。多任务时「这个任务」未来必须 `AMBIGUOUS`。短编号 `T-01` 只评估，不实现。

## 3. 改派

```text
assignee_text 变化 → 旧 TaskIdentityLink 保留 → 只记 manual confirmation required
已绑定其他 person_id → CONFLICT
没有 unlink / rebind
```

`REASSIGN_TASK` 保持高风险，不在聊天命令第一版开放。身份模型与 `TaskIdentityLink` 本 Gate 冻结。

## 4. 替代决定只是指针

`supersedes_decision_id` 不修改旧 `Decision.status`。查询隐藏不等于 `SUPERSEDED`。状态改写 Deferred。

## 5. Topic 完结

没有 `RESOLVED` / `ARCHIVED` 生产写入链。Deferred。

`update_topic` 若被传入 status 会原样保存，且没有允许列表。生产 Engine 不传。收紧这个口子属于以后的状态模型，不是本 Gate 的修复。

## 6. Task commit_apply 更新缝

`TaskStore.commit_apply` 的更新循环把 fields 原样赋进去，不再拒绝 status。公开的 `update_task` 会拒绝。当前 Engine 不传 status。

这不是「已经支持 DONE」。以后做状态模型时要补上与 `update_task` 相同的拒绝，避免内部调用绕过合同。本 Gate 不改这段代码。

Risk 的 `commit_apply` 已经拒绝 status 并强制 OPEN。Decision 的 `commit_apply` 没有更新参数。

## 7. 创建规则不一致

Task Engine 的 `NEW_TASK` 要求负责人，且负责人必须来自原文或自称。`TaskStore.create_task` 允许空 `assignee_text`。Command 以后不能选更松的那条。

## 8. Command 与讨论的分流风险

当前靠整句 `fullmatch` 分开。带标题的「把接口联调这个任务标记为完成」匹配不上模板，落入普通聊天。普通聊天在 Engine 关闭时也不写完成态。

以后不能用单个关键词「完成 / 关闭 / 修改」同时充当 Command 和 Extractor 输入。

## 9. 删除

```text
DELETE = NOT SUPPORTED
```

不要物理删除业务事实。现有 `delete_conversation_*_data` 是整会话目录，不是单条删除，也不能当作业务删除 API。

## 10. 审计与幂等

```text
BusinessActionAudit = 尚未存在
operations_action_audit = 仅运维人工 Retry
动作身份候选 = conversation_id + message_id + action_type
```

都不在本 Gate 实现。P0 去重不能代替动作幂等。

## 11. 明确不碰

```text
P6-G6 missing processing = TYPE C，禁止顺手修
P8 Query 八个类型 = 冻结
Identity Store / Resolver / TaskIdentityLink = 只读
四个 Engine 开关 = 保持 false
Real Extractor 42 条 = 不作为本 Gate 关闭条件，不改 expectation
确认会话、Reminder、跨会话、组织权限 = 不进入
```
