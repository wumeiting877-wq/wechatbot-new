# P8-G0 Closure Report

> 日期：2026-09-23  
> 结论：P8-G0 = COMPLETE  
> 生产代码：NO PRODUCTION CODE CHANGE

---

## 硬门槛

| # | 要求 | 结果 |
| --- | --- | --- |
| 1 | 找到真实 `@Agent` → Chat 路由 | 已找到。`message_listener` → `evaluate_inbound` → `handle_wxauto_message` → `process_user_messages` → `get_deepseek_response` → `send_reply` |
| 2 | Query 最小插入位置 | `message_listener` 内，`evaluate_inbound` 之后、`try_enqueue_topic_sidepath` 之前，且仅 `REPLY` |
| 3 | Query 消息会不会进业务旁路 | 会。`classify_topic_skip` 对 `REPLY` 放行。当前 Engine 常量为 false，实际入队前返回 `TOPIC_ENGINE_DISABLED`。P8-G1 对已识别 Query/Command 跳过入队 |
| 4 | 四 Store 能支持哪些查询 | `LIST_TOPICS`、`LIST_TASKS`、`LIST_DECISIONS`、`LIST_RISKS`、`OPEN_RISKS`、带绑定限制的 `TOPIC_SUMMARY` |
| 5 | 第一版 Query Intent | 上表六项。识别采用 Hybrid，本 Gate 不实现 |
| 6 | 默认只查当前 conversation | `Conversation.id` 来自 `resolve_topic_conversation`。禁止用入站 conversation_id，禁止扫其他目录 |
| 7 | 身份不确定的查询 | `MY_TASKS`、`TASKS_BY_ASSIGNEE` = Deferred |
| 8 | QueryRequest / QueryResult | 已定义。items 只用真实字段。空结果用“未查询到已记录” |
| 9 | Query 与 Command 分离 | 读走 Query Service。写走固定 NOT SUPPORTED，不进 Chat，不进 Engine |
| 10 | P8-G1 能否不改 Engine / Store schema | 能。只读现有 `list_*` / `get_*`，同步执行，复用 `send_reply` |

没有触发 STOP：

```text
不必改 Store schema
不必改 P0 Dedupe
不必改 Engine decision schema
不必改 processing schema
不必跨 conversation 搜索
不必新增 Queue / Worker
```

---

## 第一版会做的查询

```text
LIST_TOPICS
LIST_TASKS
LIST_DECISIONS
LIST_RISKS
OPEN_RISKS
TOPIC_SUMMARY
```

Deferred：

```text
MY_TASKS
TASKS_BY_ASSIGNEE
RECENT_DECISIONS
CROSS_CONVERSATION_QUERY
SEMANTIC_QUERY
FREEFORM_STORE_QUERY
COMMAND / WRITE
```

---

## 测试基线（沿用 P7-G2，本 Gate 未重跑）

```text
Core / Offline / Non-Live Regression = 623 OK
Full discover = 665 total
10 条 Real Extractor live failure
```

这 10 条不归因到 P8。未修改 live adapter expectation。未新增测试。

```text
TOPIC_ENGINE_ENABLED    = false（源码常量）
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

未改 `runtime_control`。

---

## 交付

```text
WenDang/P8-G0-CURRENT-STATE-AUDIT.md
WenDang/P8-G0-CHAT-ROUTING-AUDIT.md
WenDang/P8-G0-STORE-QUERY-CAPABILITY-AUDIT.md
WenDang/P8-G0-QUERY-MATRIX.md
WenDang/P8-G0-QUERY-CONTRACT-DESIGN.md
WenDang/P8-G0-ROUTING-DESIGN.md
WenDang/P8-G0-SECURITY-AND-SCOPE.md
WenDang/P8-G0-DEFERRED-ISSUES.md
WenDang/P8-G0-CLOSURE-REPORT.md
```

无 Implementation Report。本 Gate 没有生产代码变更。

---

## 停止线

到此停止。不进入 P8-G1 实现。等待下一步指令。
