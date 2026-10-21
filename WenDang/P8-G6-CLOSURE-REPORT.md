# P8-G6 Closure Report

> 日期：2026-09-23  
> 状态：COMPLETE

---

## 1. 结论

```text
P8-G6 = COMPLETE
```

TaskIdentityLink 独立于 Task schema。个人查询只返回当前会话里已经确定链接的任务。

## 2. 已证明

```text
wxid → person_id 由 IdentityResolver 确定
Task → person_id 只来自 TaskIdentityLink
MY_TASKS 只返回已链接任务
TASKS_BY_ASSIGNEE 只返回已链接任务
无链接时不按 assignee_text 补结果
canonical_name 不是别名
同名不猜
昵称不猜
分类器不认人
只查询当前 Conversation
P8-G3 pending 复用，补发不重新认人
Stop / Emergency 清空 pending
链接失败不让 Task 创建失败
0 fuzzy
0 LLM identity
0 cross-conversation
0 历史自动迁移
```

`DISABLED` 人员不能新建链接。查询时不再返回任务，历史链接保留。

## 3. 回归

```text
P8-G1 … P8-G5 PASS
P8-G6 32 PASS
Non-Live 767 OK = 旧 735 + 本 Gate 32
4 Engine flags = false
Real Extractor 42 未作为本 Gate 单测
```

## 4. 停止线

本 Gate 完成后不进入：

```text
写 Command
跨会话 Query
组织权限
人员管理 UI
自动历史迁移
Reminder
自动 Retry
新业务 Engine
```

等待下一步指令。
