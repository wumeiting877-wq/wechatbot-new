# P8-G4 Current State Audit

> 日期：2026-09-23  
> 审计时点：实现之前。本 Gate 结束后生产代码仍是这个状态。

---

## 1. 已经能查的

```text
现在有哪些任务？
→ LIST_TASKS
→ 当前 Conversation.id
→ 只读 Task Store
```

回复列出本会话已记录任务，状态保持存储值 `OPEN`。

## 2. 个人身份问句

P8-G2 起，这些句子在 Query Intent Classifier 之前结束：

```text
我有什么任务 / 我的任务          → UNSUPPORTED_IDENTITY / self
张三负责什么 / 张三有哪些任务    → UNSUPPORTED_IDENTITY / assignee
李明负责补材料                  → NOT_QUERY，继续原旁路
```

固定回复：

```text
当前暂不支持按个人身份查询任务。
你可以问“现在有哪些任务？”

当前暂不支持按人员身份查询任务。
```

不读 Store，不进 Chat，不进旁路。分类器调用次数为 0。

## 3. 身份与任务仍然断开

入站有 `sender_id` / `sender_wxid` / `sender_name`。Task 只有 `assignee_text`。没有人员目录把两边接上。详见 `P8-G4-G0-IDENTITY-AUDIT.md`。

## 4. 交付

P8-G3 的 pending 只挂已经路由完成的 `AgentReplyPlan`。身份问句走的是固定句，不带已解析的 person id。本 Gate 不把它们改成查询计划。

## 5. 开关

```text
TOPIC_ENGINE_ENABLED=false
TASK_ENGINE_ENABLED=false
DECISION_ENGINE_ENABLED=false
RISK_ENGINE_ENABLED=false
```

P6-G6 的 processing 缺口仍单独挂着。本 Gate 不补。
