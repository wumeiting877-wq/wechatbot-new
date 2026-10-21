# P9-G0 Action Capability Matrix

> 事实只来自当前 Store / Engine / 路由。不写「理论上可以」。
> 分类：A 底层写合同已安全可用，只缺 Command 接入；B 部分支持，要扩合同；C 要新的生命周期；D 不应在聊天命令里开放。

微信侧目前全部不可执行：Command 固定拒绝，四个 Engine 为 false。下表「当前可实现性」说的是底层写合同，不是用户现在已经能在微信里做到。

| Action | 示例 | 当前可实现性 | 分类 | 需要改什么 |
| --- | --- | --- | --- | --- |
| CREATE_TASK | 帮我建任务 | 当前已经支持 | A | Store / Engine 能新建 OPEN，含 title、description、assignee_text、due_text。缺 Command 接入。Engine 还要求已有主题、证据消息、负责人来自原文。接入时要带目标与确认，不要新造完成态 |
| UPDATE_TASK_TEXT | 修改任务描述 | 当前已经支持 | A | `update_task` 与 `TASK_UPDATE` 已能改 title、description、due_text。缺 Command 与精确目标。不得把 assignee_text 算进这个动作 |
| START_TASK | 标记进行中 | 需要新状态模型 | C | `IN_PROGRESS` 只是常量。`update_task` 对 status 抛 `INVALID_STATUS`。Engine 不传 status |
| COMPLETE_TASK | 标记完成 | 需要新状态模型 | C | `DONE` 不可写。Extractor 把完成陈述收成 `UNRELATED`。见 Task 审计：`NOT_SUPPORTED` |
| CANCEL_TASK | 取消任务 | 需要新状态模型 | C | `CANCELLED` 不可写。没有取消关系 |
| REASSIGN_TASK | 改负责人 | 需要新状态模型 | C | 高风险。文本可以被 `TASK_UPDATE` 改掉，旧 `TaskIdentityLink` 保留，已绑定则 `CONFLICT`。没有解绑/重绑。必须走精确别名与 `person_id`，不能只改 `assignee_text` |
| CREATE_RISK | 记录风险 | 当前已经支持 | A | 可新建 OPEN，且必须有 title、condition_text、impact_text。缺 Command 接入 |
| CLOSE_RISK | 关闭风险 | 需要新状态模型 | C | OPEN→MITIGATED / RESOLVED / CLOSED 全部拒绝。没有正式关闭 API |
| RECORD_DECISION | 记录决定 | 当前已经支持 | A | 可新建 RECORDED。没有原地改 `decision_text`。缺 Command 接入 |
| SUPERSEDE_DECISION | 替代决定 | 需要扩 contract | B | 新行可以写 `supersedes_decision_id`。旧行 status 保持 RECORDED。查询会藏被指向的行。缺「旧行变为 SUPERSEDED」的状态合同 |
| RESOLVE_TOPIC | 结束主题 | 需要新状态模型 | C | 生产 Engine 不写 Topic.status。没有 RESOLVED / ARCHIVED 写入链。Deferred |
| DELETE | 删除任务/风险/决定/主题 | 不建议开放 | D | 没有单条删除。只有删除整个会话目录的方法。第一版 `DELETE = NOT SUPPORTED` |

## 为什么不是 Command First

A 类只覆盖「再记一条 OPEN / RECORDED」。用户举例里的完成、开始、关闭、改派、结束主题都是 C，替代决定是 B。

```text
Task 可写状态 = OPEN
Risk 可写状态 = OPEN
Decision 可写状态 = RECORDED
Topic 生产路径不改 status
```

按这个事实，下一 Gate 是生命周期，不是把 A 类先接进微信。

## 第一批不做什么

不设计「一句话交给模型决定改哪个 Store」。

未来写路径固定为：

```text
Command Intent
↓
Resolve Target
↓
Preview
↓
Confirm / Apply
↓
Write Service
```

与 P8 并列，不扩展 `QueryService`：

```text
Agent Message Router
├─ Query    → P8 QueryService     （永久 READ ONLY）
├─ Command  → P9 Action Router → Target Resolver → Action Service
└─ Normal Chat
```

本 Gate 只留下这张图，不实现。

## 确认

第一版没有可以不经确认就从聊天落盘的动作。

记录新任务虽然底层能写 OPEN，但 Command 场景常常没有主题、没有符合 Engine 规则的负责人。Store 允许空负责人，Engine 不允许。在这两条规则对齐、并且目标唯一之前，不直接写。

必须先确认的候选：

```text
完成任务
取消任务
关闭风险
改负责人
删除
```

删除即使确认也不进入第一版。Store 没有单条删除。

## 幂等

P0 去重按 `platform_message_id`，否则按事件哈希，挡的是同一条入站消息。它不是业务动作 id。确认、重放、客户端再送一次，会是另一条消息。

Action Service 以后的候选身份：

```text
conversation_id + message_id + action_type
```

只设计，不实现。

## 审计

`operations_action_audit` 只记 `MANUAL_RETRY_REQUESTED` / `MANUAL_RETRY_RESULT`。那是运维人工重试，不是业务写操作。

四个 Engine 的 `write_audit` 记的是抽取决策与错误，不是「谁在微信里确认了对哪条实体做了什么」。

```text
后续需要 BusinessActionAudit
本 Gate 不实现
```

至少要能回答：谁、什么时候、哪个实体、什么写操作、结果是什么。

## 推荐的下一刀

见 Closure。这里只重复决定：

```text
路径 B → P9-G1 Lifecycle State Model
```

生命周期第一刀只处理 Task 的合法状态集合：明确 OPEN 之外哪些流转仍然非法，再决定 `OPEN → DONE` 是否成为唯一新增的合法流转。不要在同一刀里打开 Risk 关闭、Decision 状态改写、Topic 完结、改派和 Command Router。
