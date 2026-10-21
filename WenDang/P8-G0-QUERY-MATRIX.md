# P8-G0 Query Matrix

> 日期：2026-09-23  
> 范围一律是已解析的当前 `Conversation.id`。过滤都在 `list_*` 之后的内存中完成。

| Query Type | 示例 | Store | Filter | 是否可实现 | 原因 |
| ---------- | -- | ----- | ------ | ----- | -- |
| LIST_TOPICS | 现在有哪些主题？ | topic_store `list_topics` | 当前 conversation_id | 可实现 | 主题在该会话 `topics.json`。字段含 title、summary、status、message_count |
| LIST_TASKS | 现在有哪些任务？ | task_store `list_tasks` | 当前 conversation_id | 可实现 | 不按 status 再细分。落盘 status 只有 OPEN，回复原样显示 OPEN |
| LIST_DECISIONS | 刚才确定了什么？ / 有哪些决定？ | decision_store `list_decisions` | 当前 conversation_id；默认去掉被其他行 `supersedes_decision_id` 指向的 id；按 `created_at` 从新到旧 | 可实现 | 有 `created_at` 可以排序。没有“刚才”的时间窗，文案不能说这是刚才 |
| LIST_RISKS | 记录了哪些风险？ | risk_store `list_risks` | 当前 conversation_id | 可实现 | 现有写入只有 OPEN，结果与 OPEN_RISKS 相同 |
| OPEN_RISKS | 目前有哪些风险？ | risk_store `list_risks` | 当前 conversation_id 且 status == OPEN | 可实现 | status 常量含 OPEN，且 v1 只写 OPEN。`list_open_risks` 还要求 topic_id，会话级过滤放在 Query Service |
| TOPIC_SUMMARY | 主题「接口联调」现在是什么情况？ | topic_store `get_topic` + task/decision/risk 按 topic_id | 当前 conversation_id；主题必须先绑定 | 可实现，带绑定限制 | 主题自身有 title、summary、status、message_count。关联实体用 topic_id 过滤。不调用 LLM |
| TASKS_BY_ASSIGNEE | 张三现在负责什么？ | task_store 只有 `assignee_text` | 无稳定身份键 | Deferred | 没有 assignee_id / wxid。禁止用昵称或 LLM 猜测 |
| MY_TASKS | 我有什么任务？ | 入站 sender_* 与 Task 无映射 | 无法把 sender 对到 assignee_text | Deferred | 不靠 sender_name 猜 |
| RECENT_DECISIONS | 刚才（作为时间窗） | decision_store `created_at` | 未定义时间窗 | Deferred | 排序可以用 LIST_DECISIONS。不单独做“刚才” |
| CROSS_CONVERSATION_QUERY | 另一个项目群有什么任务？ | 无跨会话读 API | 禁止 | Deferred / OUT_OF_SCOPE | 第一版固定拒绝，不扫描其他目录 |
| SEMANTIC_QUERY | 用意思去搜 Store | — | — | Deferred | 不是有限 Intent |
| FREEFORM_STORE_QUERY | 模型自己编查询 | — | — | Deferred | Classifier 不能生成答案或查询语句 |

员工原话到类型的对应：

```text
现在有哪些任务？     LIST_TASKS
目前有哪些风险？     OPEN_RISKS
刚才确定了什么？     LIST_DECISIONS
现在有哪些主题？     LIST_TOPICS
这个主题现在什么情况？  TOPIC_SUMMARY（绑得上才查，否则列出主题名）
张三现在负责什么？   不进入 TASKS_BY_ASSIGNEE
我有什么任务？       不进入 MY_TASKS
```

空结果不是“没有风险/没有任务”，而是“当前未查询到已记录的……”。
