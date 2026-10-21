# P8-G0 Current State Audit

> 日期：2026-09-23  
> 范围：只读审计。不改生产代码，不改 runtime_control，不进入 P8-G1。  
> 结论：P8-G0 = COMPLETE。第一版只读 Query 不需要改 Store schema、P0 Dedupe、Engine decision schema、processing schema，也不需要新 Queue。

---

## 阶段

```text
P0–P5 = CLOSED / COMPLETE
P6-G0 … P6-G5 = COMPLETE
P6-G6 = BLOCKED / TYPE C / KNOWN LIMITATION
P7-G0 … P7-G2 = COMPLETE
P8-G0 = COMPLETE（本文件）
```

P8 不扩展 Dashboard、自动 Retry、批量 Retry、运维功能。

四个 Engine 的源码常量仍是 `False`：

```text
topic_engine.py      TOPIC_ENGINE_ENABLED = False
task_engine.py       TASK_ENGINE_ENABLED = False
decision_engine.py   DECISION_ENGINE_ENABLED = False
risk_engine.py       RISK_ENGINE_ENABLED = False
```

运行时若存在 `runtime_control/*_ENGINE_ENABLED` 或同名环境变量，会覆盖常量。本 Gate 不读取、不改写这些开关。

---

## 本 Gate 扫过的真实入口

| 环节 | 文件 | 函数 |
| --- | --- | --- |
| 微信监听注册 | `bot.py` | `wx.AddListenChat(..., callback=message_listener)` |
| 入站 | `message/listener.py` | `message_listener` |
| 身份对象 | `message/identity.py` | `inbound_from_wx_message` → `InboundMessage` |
| P0 准入 | `bot_runtime.py` | `BotRuntime.evaluate_inbound` |
| Trigger | `message/trigger.py` | `decide_trigger` |
| 群 @ / 关键词 | `group_rules.py` | `evaluate_group_trigger` / `detect_group_at` |
| 私聊名单 | `message/pipeline.py` | `decide_should_process` |
| Topic 旁路 | `topic_sidepath.py` | `try_enqueue_topic_sidepath` |
| 命令 / 入队 | `message/handler.py` | `handle_wxauto_message` |
| Chat | `message/processor.py` | `process_user_messages` |
| Prompt | `memory_store.py` | `load_chat_prompt` / `get_user_prompt` |
| LLM | `llm_client.py` | `get_deepseek_response` |
| 发送 | `bot.py` | `send_reply` → `wx.SendMsg` |
| Store | `topic_store.py` `task_store.py` `decision_store.py` `risk_store.py` | 见 Store 审计 |

项目里没有名为 Chat Router 的对象。`@Agent` 到回复是上述函数的顺序调用。

---

## 审计结论（给 P8-G1）

1. `@智群Agent 现在有哪些任务？` 在群里命中现有 `@` 规则后，走普通 Chat LLM，不读 Task Store。
2. Query 的最小插入点在 `message_listener` 里：`evaluate_inbound` 返回之后、`try_enqueue_topic_sidepath` 之前。只处理 `action == REPLY`。
3. Engine 打开后，这条 REPLY 消息会被 Topic 旁路收下，并可能扇出到 Task / Decision / Risk。当前四个开关为 false 时，旁路在入队前直接返回 `TOPIC_ENGINE_DISABLED`，不会提取。
4. 四个 Store 都按 `Conversation.id` 分目录只读。没有跨会话列表 API。`InboundMessage.conversation_id` 不是 Store 的 conversation id。
5. v1 Query Intent：`LIST_TOPICS`、`LIST_TASKS`、`LIST_DECISIONS`、`OPEN_RISKS`、`LIST_RISKS`、`TOPIC_SUMMARY`。
6. `MY_TASKS`、`TASKS_BY_ASSIGNEE`、带时间窗的 `RECENT_DECISIONS`、跨会话查询：Deferred。
7. Query 与 Command 分开。写操作第一版固定回复不支持，不调用 Engine。
8. 回复继续走现有 `send_reply`。Stop 时 listener 在旁路和 Chat 之前返回；`send_reply` 再经 `ensure_can_send`。
9. P8-G1 可以只加路由、只读 Query Service 和文本格式化，不改 Engine / Store schema，不新建 Queue。

---

## 明确不做

```text
NO PRODUCTION CODE CHANGE
不实现 Query Service
不改 listener / P0 / Chat Prompt / Engine / Store
不把 Store 全量塞进 Chat Prompt
不把 P7 Operations 三态混进员工查询
不处理 P6-G6
```

测试基线沿用 P7-G2，本 Gate 未重跑：

```text
Core / Offline / Non-Live Regression = 623 OK
Full discover = 665 total
其中 10 条 = Real Extractor live 连接失败或超时
```

这 10 条不归因到 P8。不修改 live adapter expectation。

---

## 文档索引

```text
P8-G0-CHAT-ROUTING-AUDIT.md
P8-G0-STORE-QUERY-CAPABILITY-AUDIT.md
P8-G0-QUERY-MATRIX.md
P8-G0-QUERY-CONTRACT-DESIGN.md
P8-G0-ROUTING-DESIGN.md
P8-G0-SECURITY-AND-SCOPE.md
P8-G0-DEFERRED-ISSUES.md
P8-G0-CLOSURE-REPORT.md
```
