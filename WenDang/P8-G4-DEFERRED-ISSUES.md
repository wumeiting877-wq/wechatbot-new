# P8-G4 Deferred Issues

> 日期：2026-09-23

本 Gate 正确停在 TYPE C。下面这些仍然不做。

---

## 1. 身份模型

```text
人员主键
sender_wxid → person
Task.assignee_text → 同一个 person
重名 AMBIGUOUS
未绑定的固定「无法确定你的负责人身份」文案
```

需要单独阶段。不要在查询 Gate 里给 Task 加 `assignee_id` / `assignee_wxid` / `employee_id`。

在那之前，`MY_TASKS` 和 `TASKS_BY_ASSIGNEE` 保持固定拒绝。

## 2. 继续 Deferred

```text
RECENT_DECISIONS
CROSS_CONVERSATION_QUERY
写 Command：创建 / 修改 / 完成 / 关闭 / 删除 / 指派
按人扫描全部会话
组织架构 / HR / RBAC
Reminder
自动 Retry
P6-G6 processing
新的业务 Engine
```

## 3. Live

42 条 Real Extractor 的 live dependency 不在本 Gate。
