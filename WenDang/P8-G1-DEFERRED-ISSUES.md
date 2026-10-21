# P8-G1 Deferred Issues

> 日期：2026-09-23  
> 这些项不在本 Gate。没有用 LIST_TASKS 或跨会话搜索临时顶上。

---

## 1. 继续 Deferred 的查询

```text
MY_TASKS
TASKS_BY_ASSIGNEE
RECENT_DECISIONS
CROSS_CONVERSATION_QUERY
SEMANTIC_QUERY
FREEFORM_STORE_QUERY
```

「我有什么任务」「张三负责什么」现在是 `NOT_QUERY`，走原 Chat。没有把 `sender_name` 当成 `assignee_text`。

「刚才确定了什么」是 `LIST_DECISIONS`，不是 `RECENT_DECISIONS`。没有时间窗。

跨会话说法固定 `OUT_OF_SCOPE`，不搜索第二个会话。

## 2. 规则没覆盖的问法

规则要整句命中。改写句、夹在业务讨论里的问法会回到 Chat。这是故意的：漏判可以再问，误判会跳过一次提取。

Query Intent LLM 留在 `classify_unmatched_as_not_query`，固定 `NOT_QUERY`。需要覆盖更多说法时单独开 Gate。

## 3. 写操作

创建、完成、关闭、修改、指派只回复「当前不能在这里修改任务、风险或决定。」不写 Store。真正的写命令不在本 Gate。

## 4. 会话忙时的查询

Chat 正占用 `try_acquire_session` 时，查询被消费，但不发送，也不退回 Chat。这样两条回复不会穿插。员工需要等当前回复结束后再问一次。

## 5. 明确不做

```text
Query Queue / Worker
查询审计写入四个业务 Store
用查询句补 P6-G6 缺失的 processing
Reminder
自动 Retry
新 Engine
```

`LIST_RISKS` 已可由 Service 读取。员工口头说「有哪些风险」时，Router 给的是 `OPEN_RISKS`。只有「全部风险 / 所有风险」才走 `LIST_RISKS`。
