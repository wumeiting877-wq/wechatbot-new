# P8-G0 Query Contract Design

> 日期：2026-09-23  
> 本文件只定义契约。P8-G0 不写 Query Service，不改生产代码。

---

## 1. 链路

```text
Query Intent
↓
QueryRequest
↓
Query Service          同步、只读、当前 conversation_id
↓
QueryResult            items 来自 Store 字段
↓
Reply Formatter        确定性文本，不调用 LLM
↓
send_reply
```

Classifier 若存在，只填 `query_type` 和过滤器。它不返回 answer，不返回 Task/Risk 正文。

---

## 2. QueryRequest v1

```text
QueryRequest {
    conversation_id     必填。Conversation.id，来自 resolve_topic_conversation
    message_id          入站 message_id / platform_message_id
    sender_id           仅作追踪。不参与 assignee 过滤

    query_type          LIST_TOPICS | LIST_TASKS | LIST_DECISIONS
                        | LIST_RISKS | OPEN_RISKS | TOPIC_SUMMARY

    topic_id            可选。TOPIC_SUMMARY 使用
    topic_title         可选。与当前会话某个 title 全字匹配时使用
}
```

v1 不包含：

```text
assignee
assignee_text
status          各 Intent 的 status 规则写死在 Service 内
time_scope      没有稳定的“刚才”定义
```

`conversation_id` 缺失或解析失败：不查 Store，结果为 `CONVERSATION_NOT_RESOLVED`。

---

## 3. QueryResult v1

```text
QueryResult {
    query_type
    conversation_id

    items               只含下面 DTO。不附 processing，不附 P7 三态
    total               len(items)

    source              topic_store | task_store | decision_store | risk_store
                        TOPIC_SUMMARY 为 topic_store（主来源）
    sources             TOPIC_SUMMARY 额外列出实际读过的 store 名

    generated_at        查询时刻 ISO 时间
    empty               total == 0
    outcome             OK | EMPTY | NOT_FOUND | AMBIGUOUS
                        | OUT_OF_SCOPE | CONVERSATION_NOT_RESOLVED
}
```

`source` 表示答案来自业务 Store，不是 Chat 模型生成的。

DTO 只复制 Store 里真实存在的键。没有的键不出现。

### TopicItem

```text
id
conversation_id
title
summary
status
message_count
last_message_at
created_at
```

### TaskItem

```text
id
conversation_id
topic_id
title
description
status
assignee_text
due_text
created_msg_id
created_at
updated_at
```

`due_at` 在写入时被清空，v1 不展示。

### DecisionItem

```text
id
conversation_id
topic_id
title
decision_text
summary
status                 存储值，v1 为 RECORDED
created_msg_id
supersedes_decision_id
created_at
```

不增加 Open/Closed。

### RiskItem

```text
id
conversation_id
topic_id
task_id
title
description
condition_text
impact_text
status                 存储值 OPEN
created_msg_id
created_at
updated_at
```

不展示 severity、owner。

### TopicSummaryItem

```text
topic                  TopicItem
tasks                  TaskItem 列表（该 topic_id）
decisions              DecisionItem 列表（该 topic_id，去掉被 supersede 指向的 id）
risks                  RiskItem 列表（该 topic_id 且 status == OPEN）
```

摘要不读 `messages.jsonl` 全文，不调用 LLM。

每条 item 保留 `id`、`topic_id`（主题自身用 `id`）、`created_msg_id`（任务/决定/风险）。微信正文默认不展开 evidence 链接。这些字段留给测试和以后的“为什么这么说”。

---

## 4. 各 Intent 的读法

```text
LIST_TOPICS
    list_topics(conversation_id)
    不按 status 删行。status 原样放进 DTO

LIST_TASKS
    list_tasks(conversation_id)
    不按 IN_PROGRESS / DONE 过滤

LIST_DECISIONS
    list_decisions(conversation_id)
    去掉 id 出现在其他行 supersedes_decision_id 中的项
    按 created_at 降序
    不使用时间窗

LIST_RISKS
    list_risks(conversation_id)

OPEN_RISKS
    list_risks(conversation_id) 中 status == OPEN

TOPIC_SUMMARY
    见下一节
```

Service 在返回前检查每条 `item.conversation_id == request.conversation_id`。不一致的行丢弃，不拿其他会话补。

---

## 5. TOPIC_SUMMARY 的主题绑定

按这个顺序，命中即停：

```text
1. request.topic_id 在当前会话 get_topic 命中
2. request.topic_title 与某个 title 全字相等，且只有一个
3. 请求没指定主题，且 list_topics 恰好 1 条
```

否则：

```text
0 条主题        outcome = EMPTY
topic_id 不存在  outcome = NOT_FOUND
多个主题对不上   outcome = AMBIGUOUS，items 里只放 TopicItem 的 id 和 title
```

“这个主题”在有多个主题时就是 AMBIGUOUS。不选 last_message_at 最近的一个，也不让模型选。

---

## 6. 空结果

`empty == true` 且 `outcome == EMPTY` 时，正文用“未查询到已记录”：

```text
当前未查询到已记录的任务。
当前未查询到已记录的风险。
当前未查询到已记录的决定。
当前未查询到已记录的主题。
```

不使用：

```text
当前没有任何风险。
当前没有任务。
```

Store 没有行，只说明查询没有命中已落盘实体，不说明业务上不存在。

---

## 7. Reply Formatter

输入是 `QueryResult`，输出微信纯文本。不调用 Chat LLM，不把 Store JSON 交给模型。

任务示例（字段都来自 TaskItem）：

```text
当前记录到 3 个任务：

1. 完成接口联调
   负责人：李明
   状态：OPEN

2. 补充验收材料
   负责人：未记录
   状态：OPEN
```

规则：

```text
负责人 = assignee_text，空则“未记录”
状态 = 存储的 status 字符串
有 due_text 才多一行“时间说明：...”
不把 OPEN 译成“进行中”或“待处理”
```

决定示例：

```text
当前记录到 2 条决定（按记录时间从新到旧）：

1. 周五前完成联调
   状态：RECORDED

2. 验收材料由王磊补充
   状态：RECORDED
```

不写“刚才”，不写 Open/Closed。

风险示例：

```text
当前记录到 1 条未关闭的风险：

1. 联调环境不稳定
   条件：测试环境频繁重启
   影响：周五验收可能推迟
   状态：OPEN
```

“未关闭”对应过滤条件 `status == OPEN`，状态行仍写存储值 `OPEN`。

主题摘要示例：

```text
主题：接口联调
状态：ACTIVE
摘要：正在对齐回调字段
关联消息数：4

任务（2）
1. 对齐回调字段
   状态：OPEN

决定（1）
1. 周五前完成联调
   状态：RECORDED

风险（1）
1. 联调环境不稳定
   状态：OPEN
```

某一侧为空就写“未查询到已记录的任务/决定/风险”，主题本身仍然列出。

其他 outcome 的固定句：

```text
NOT_FOUND
    当前未查询到该主题。

AMBIGUOUS
    当前会话有多个主题，请用主题名称再问一次。
    然后逐行列出 title

OUT_OF_SCOPE
    当前只能查询本会话已记录的内容。

CONVERSATION_NOT_RESOLVED
    当前会话尚未绑定，无法查询已记录内容。

COMMAND / 写操作
    当前不能在这里修改任务、风险或决定。
```

正文交给现有 `send_reply`。`send_reply` 会再做微信纯文本清理。Formatter 自己不插入 markdown 表格。

---

## 8. Query Service 的副作用

```text
0 write
0 processing
0 业务 audit 写入
0 Engine
0 Retry
0 补 P6-G6 缺失 processing
```

P8-G0 不实现只读 query audit。以后若要记“谁查过”，单独加，不写进四个业务 Store。

---

## 9. 与 P7 的边界

```text
P7  这条消息处理成功了没有（processing / UNKNOWN）
P8  已经落盘的 Topic / Task / Decision / Risk 是什么
```

QueryResult 不带 `source_status`，不带 Operations 三态。
