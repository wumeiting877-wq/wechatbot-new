# P8-G2 Current State Audit

> 日期：2026-09-23  
> 只读。写分类器之前，对照 P8-G1 已落地代码。

---

## 1. 冻结基线

```text
P0–P5 = CLOSED / COMPLETE
P6-G0 … P6-G5 = COMPLETE
P6-G6 = BLOCKED / TYPE C
P7-G0 … P7-G2 = COMPLETE
P8-G0 = COMPLETE
P8-G1 = COMPLETE
```

进入本 Gate 时：

```text
P8-G1 targeted tests = 42 OK
Non-Live Regression = 665 OK
```

四个 Engine 常量都是 `false`，运行时开关同样是 `false`。本 Gate 不改这四个开关。

## 2. 已有查询链

`message/listener.py` 在 `evaluate_inbound` 得到 `REPLY` 之后、`try_enqueue_topic_sidepath` 之前调用 `handle_collaboration_route`。

P8-G1 的顺序是：

```text
evaluate_inbound
↓
REPLY
↓
classify_agent_message     纯规则
↓
Query Service / 固定文案
↓
allow_reply
↓
try_acquire_session
↓
send_reply
↓
return                     不进旁路，不进 Chat
```

规则未命中时 `classify_agent_message` 固定 `NOT_QUERY`，`handle_collaboration_route` 返回 `False`，原旁路和 `handle_wxauto_message` 继续。

`query_service.py` 只按当前 `conversation_id` 读 Store。`conversation_id` 只来自 `resolve_topic_conversation`。Formatter 只吃 `QueryResult`。

## 3. 规则已经接住的说法

整句命中时直接是：

```text
LIST_TOPICS
LIST_TASKS
LIST_DECISIONS
LIST_RISKS
OPEN_RISKS
TOPIC_SUMMARY
```

`/` 开头回到原 handler。跨会话查询是 `OUT_OF_SCOPE`。整句写指令是 `COMMAND`，固定文案「当前不能在这里修改任务、风险或决定。」

## 4. 身份句在 P8-G1 的落点

`classify_agent_message` 把「我有什么任务」「我的任务」「张三负责什么」「张三有哪些任务」标成 `KIND_NOT_QUERY`，而且 `query_type` 不是 `LIST_TASKS`。

当时没有单独的固定回复，这些句子会回到 Chat。Task 仍然只有 `assignee_text`，没有 `assignee_id` / wxid 映射。

「李明负责补材料」也会被宽的「某人负责」规则挡住，结果同样是 `NOT_QUERY`，然后进旁路。这是陈述，不是身份查询。

## 5. 会话锁

锁只在 `collaboration_query._send` 里获取，发生在规则识别和 Query Service 之后。Chat 正占着同一把锁时，本轮不发送，也不退回 Chat。没有 pending queue。

## 6. 本 Gate 要补的缺口

规则要整句命中。下面这些是查询，但 P8-G1 会掉回 Chat：

```text
帮我盘一下现在手上的待办
我们主要有哪些潜在问题需要注意
之前到底定下来了哪些事情
这个群现在主要在推进哪些事情
帮我看看当前主题整体怎么样
```

分类器只填这个缺口。它不能跑到 `/`、跨会话、身份查询、写指令、高置信规则前面。
