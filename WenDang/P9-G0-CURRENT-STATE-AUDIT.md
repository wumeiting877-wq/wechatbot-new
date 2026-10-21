# P9-G0 Current State Audit

> 日期：2026-09-23
> 范围：只读。本 Gate 不改生产代码。

## 1. 阶段

```text
P8 — Collaboration Query Layer = 结束
P9 — Collaboration Action Layer = 进入
本 Gate = P9-G0 READ ONLY AUDIT
```

冻结基线保持：

```text
P0–P5 = CLOSED / COMPLETE
P6-G0 … P6-G5 = COMPLETE
P6-G6 = BLOCKED / TYPE C
P7-G0 … P7-G2 = COMPLETE
P8-G0 … P8-G3 = COMPLETE
P8-G4 = BLOCKED / TYPE C（历史结论保留）
P8-G5 = COMPLETE / MODEL-A
P8-G6 = COMPLETE
```

## 2. 已经完成、本 Gate 只读取的层

```text
P8 Query Layer = 已完成
Identity Model = 已完成
TaskIdentityLink = 已完成
```

Query 与 Command 的当前分界：

```text
Query = READ
Command = 仍固定拒绝
```

`QueryService` 只有查询方法。源码中没有 `update_task`、`close_risk`、`create_task`。P8 的八个查询保持只读：

```text
LIST_TOPICS
LIST_TASKS
LIST_DECISIONS
LIST_RISKS
OPEN_RISKS
TOPIC_SUMMARY
MY_TASKS
TASKS_BY_ASSIGNEE
```

## 3. 四个 Engine

模块常量，本 Gate 结束时仍为：

```text
TOPIC_ENGINE_ENABLED=false
TASK_ENGINE_ENABLED=false
DECISION_ENGINE_ENABLED=false
RISK_ENGINE_ENABLED=false
```

位置：

```text
topic_engine.py
task_engine.py
decision_engine.py
risk_engine.py
```

Engine 关闭时，旁路不会执行抽取写入。微信里命中 Command 的句子在协作路由处直接返回，到不了 `try_enqueue_topic_sidepath`。

## 4. 生产写能力一句话

```text
Task     CREATE_STATUS = OPEN ONLY
Risk     CURRENT PRODUCTION WRITE = OPEN ONLY
Decision CURRENT PRODUCTION WRITE = RECORDED ONLY
Topic    生产 Engine 不改变 status；创建时写入 ACTIVE
```

`IN_PROGRESS`、`DONE`、`CANCELLED`、`MITIGATED`、`RESOLVED`、`CLOSED`、`SUPERSEDED`、`ARCHIVED` 都是常量或 Store 可接受的字符串，不是当前生产写路径。

## 5. 微信写操作

当前识别出的写句型走固定回复：

```text
当前不能在这里修改任务、风险或决定。
```

这条路径：

```text
0 Store write
0 Engine action
0 QueryService.execute
```

## 6. 下一 Gate

真实代码决定：

```text
路径 B
底层生命周期不足
→ P9-G1 Lifecycle State Model
```

不进入 Command Router。理由见 `P9-G0-ACTION-CAPABILITY-MATRIX.md` 与 `P9-G0-CLOSURE-REPORT.md`。

## 7. Non-Live

本 Gate 不新增生产测试。回归数字见 Closure Report。进入本 Gate 时的基线是 767 OK。
