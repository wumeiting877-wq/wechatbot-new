# P8-G0 Store Query Capability Audit

> 日期：2026-09-23  
> 范围：`topic_store.py`、`task_store.py`、`decision_store.py`、`risk_store.py` 的现有只读方法。不假设未出现的 API。

---

## 1. 共同约束

四个 Store 的读方法第一个参数都是 `conversation_id`，文件在：

```text
data/topic_store/conversations/<conversation_id>/
data/task_store/conversations/<conversation_id>/
data/decision_store/conversations/<conversation_id>/
data/risk_store/conversations/<conversation_id>/
```

没有 `list_all_conversations`，没有跨目录扫描函数。调用方必须先拿到 `Conversation.id`。

`topic_engine.resolve_topic_conversation` 写明：禁止把 `InboundMessage.conversation_id` 当作 Store 的 conversation id。解析顺序是 `chat_wxid` → `find_by_platform_conversation_id`，否则 `chat_name` → `find_conversation_by_display_name`。命中对象的 `id` 才是 Store 键，形如 `conv_` 加哈希。解析失败时 Query 不能改去扫别的会话。

下面“能按某字段读”如果没有同名方法，指的是：先 `list_*` 当前会话，再在内存里过滤。这足够支撑 P8 v1，不需要改 schema，也不需要新的 Store 方法。

不存在的方法（四个 Store 都没有）：

```text
find_*
get_by_topic          （Task/Decision/Risk 没有这个名字）
get_by_conversation   （list_* 本身就是按会话读）
get_by_message
get_by_assignee
get_by_status
```

`get_processing` / `has_successful_processing` 属于 P7 处理状态。P8 员工查询不调用它们。

---

## 2. Topic

### 已有只读方法

```text
list_topics(conversation_id)
get_topic(conversation_id, topic_id)
list_messages(conversation_id)
get_message(conversation_id, message_id)
recent_messages(conversation_id, limit=12, exclude_id="")
list_links(conversation_id)
links_for_topic(conversation_id, topic_id)
links_for_message(conversation_id, message_id)
```

### 能否按这些键读取

| 键 | 现况 |
| --- | --- |
| conversation_id | 能。`list_topics` 只打开该会话的 `topics.json` |
| topic_id | 能。`get_topic` |
| status | 能在内存过滤。没有按 status 的专用方法。候选集合常量是 `ACTIVE` / `WAITING` / `OPEN` |
| 时间 | 记录上有 `created_at`、`updated_at`、`last_message_at`。没有按时间窗的专用方法。可按字符串排序 |

### `create_topic` 写入的字段

```text
id
conversation_id
title              最长 40
summary            最长 500
status             创建时固定 ACTIVE
confidence         HIGH / MEDIUM / LOW
created_at
updated_at
last_message_at
message_count      创建时 0，refresh_topic_message_count 按 link 去重重算
schema_version
```

状态常量还有 `WAITING`、`OPEN`、`RESOLVED`、`ARCHIVED`。`update_topic` 允许改 `status`，但当前 `topic_engine` 更新时只写 `confidence`、`last_message_at`、可选 `summary`，再刷新 `message_count`。生产提取路径不会把 status 改离 `ACTIVE`。

`title`、`summary`、`status`、`message_count` 都在实体上，足够做不调用 LLM 的 `TOPIC_SUMMARY` 主题头。关联 Task / Decision / Risk 不在 Topic 文件里，要按 `topic_id` 去另外三个 Store 过滤。

---

## 3. Task

### 已有只读方法

```text
list_tasks(conversation_id)
get_task(conversation_id, task_id)
list_open_tasks(conversation_id, topic_id, limit=10, content="")
list_links(conversation_id)
links_for_task(conversation_id, task_id)
```

`list_open_tasks` 同时要求 `topic_id` 和 `status == OPEN`。它不是“当前群全部未完成任务”的接口。会话级列表用 `list_tasks`。

### 能否按这些键读取

| 键 | 现况 |
| --- | --- |
| conversation_id | 能。`list_tasks` |
| topic_id | 能。内存过滤，或在已知 topic_id 时用 `list_open_tasks` |
| assignee | 字段名是 `assignee_text`，自由文本。没有 `assignee` / `assignee_id` / `assignee_wxid`，这三项在 `FORBIDDEN_TASK_KEYS` 里 |
| status | 能在内存过滤 |
| created_msg_id | 实体上有这个字段，能在内存过滤。没有 `get_by_message` |

### `_normalize_new_task` 的真实字段

```text
id
conversation_id
topic_id
title
description
status
assignee_text
due_text
due_at             写入时被清空；update 若传入 due_at 会抛 DUE_AT_FORBIDDEN
created_msg_id
confidence
created_at
updated_at
schema_version
```

### 真实 status

常量：

```text
OPEN
IN_PROGRESS
DONE
CANCELLED
```

`ALLOWED_WRITE_STATUSES` 只有 `OPEN`。`_normalize_new_task` 把 status 写成 `TASK_STATUS_OPEN`。`update_task` 遇到 `status` 字段直接抛 `INVALID_STATUS`。

因此当前落盘任务的 status 是 `OPEN`。P8 v1 不做 `TODO` / `DOING` / `DONE` 过滤，也不把 `OPEN` 显示成“进行中”。回复里的状态就是存储值 `OPEN`。

`assignee_text` 不能用来做“张三”的身份匹配。它是提取器写下的一段文字，和入站 `sender_id` / `sender_wxid` / `sender_name` 没有映射。

---

## 4. Decision

### 已有只读方法

```text
list_decisions(conversation_id)
get_decision(conversation_id, decision_id)
list_recorded_decisions(conversation_id, topic_id, limit=10, current_effective=True)
list_links(conversation_id)
links_for_decision(conversation_id, decision_id)
```

`list_recorded_decisions` 必须带 `topic_id`。会话级列表用 `list_decisions`。

### 能否按这些键读取

| 键 | 现况 |
| --- | --- |
| conversation_id | 能。`list_decisions` |
| topic_id | 能。内存过滤，或 `list_recorded_decisions` |
| created_msg_id | 实体上有，能在内存过滤 |

### `_normalize_new_decision` 的真实字段

```text
id
conversation_id
topic_id
title
decision_text
summary
status
confidence
created_msg_id
supersedes_decision_id    可空
created_at
updated_at
schema_version
```

没有 `owner`、`assignee`、`decided_by`。这些在 `FORBIDDEN_DECISION_KEYS` 里。

### status

常量：

```text
RECORDED
SUPERSEDED
CANCELLED
```

`ALLOWED_WRITE_STATUSES` 只有 `RECORDED`。文件头写明 v1 不自动写 `SUPERSEDED` / `CANCELLED`。

`list_recorded_decisions(..., current_effective=True)` 会丢掉“被别的决定的 `supersedes_decision_id` 指到”的 id，但那些行自己的 `status` 仍然是 `RECORDED`。这是指针，不是状态机。

P8 回复可以显示存储值 `RECORDED`。不能显示 Open/Closed，也不能因为被替代就把 status 说成 `SUPERSEDED`。

`created_at` 是 ISO 字符串，可以排序。没有“刚才”的时间窗定义，所以第一版不设 `RECENT_DECISIONS`。`刚才确定了什么` 走 `LIST_DECISIONS`，文案按记录时间从新到旧，不声称这是“刚才”。

---

## 5. Risk

### 已有只读方法

```text
list_risks(conversation_id)
get_risk(conversation_id, risk_id)
list_open_risks(conversation_id, topic_id, limit=10)
list_links(conversation_id)
links_for_risk(conversation_id, risk_id)
```

`list_open_risks` 必须带 `topic_id`。会话内全部 OPEN 要用 `list_risks` 再滤 `status == OPEN`。

### 能否按这些键读取

| 键 | 现况 |
| --- | --- |
| conversation_id | 能。`list_risks` |
| topic_id | 能。内存过滤，或 `list_open_risks` |
| status | 能。比较值就是 `OPEN` |
| created_msg_id | 实体上有，能在内存过滤 |

### `_normalize_new_risk` 的真实字段

```text
id
conversation_id
topic_id
task_id            可空；只有同一会话、同一 topic、且 Task status 为 OPEN 时才保留
title
description
condition_text
impact_text
status             固定 OPEN
confidence
created_msg_id
created_at
updated_at
schema_version
```

没有 `severity`、`owner`、`due`。这些在 `FORBIDDEN_RISK_KEYS` 里。

### status

常量：

```text
OPEN
MITIGATED
RESOLVED
CLOSED
```

允许写入的只有 `OPEN`。`update_risk` 禁止改 status。所以 v1 落盘风险都是 `OPEN`。

`OPEN_RISKS` 可以做：当前会话 `list_risks`，保留 `status == OPEN`。`目前有哪些风险` 使用这个类型。`LIST_RISKS` 是同一会话的全部行；在现有写入规则下两者结果相同。回复仍写“未查询到已记录的风险”，不写“没有任何风险”。

---

## 6. TOPIC_SUMMARY 能否拼出来

可以，不调用 LLM，不读聊天全文。

```text
get_topic(conversation_id, topic_id)
    title / summary / status / message_count / last_message_at
list_tasks → topic_id 相等
list_decisions → topic_id 相等，并去掉被 supersedes 指到的 id
list_open_risks(conversation_id, topic_id) 或 list_risks 再滤 topic_id + OPEN
```

“这个主题”没有会话级当前主题指针。绑定规则放在查询契约里：精确 `topic_id`、唯一精确标题，或该会话恰好只有一个主题。多个主题时返回主题列表，不猜测。

---

## 7. P8-G1 不需要改的部分

```text
不改四 Store 的文件格式和字段
不新增 find_* / get_by_*
不读 processing
不写 Store
不调用 topic_retry / downstream_retry
```

Query Service 只调用本节列出的已有读方法。
