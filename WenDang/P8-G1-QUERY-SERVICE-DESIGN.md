# P8-G1 Query Service Design

> 日期：2026-09-23  
> 实现：`query_service.py`、`query_formatter.py`。  
> 同步、只读、当前 `Conversation.id`。0 LLM，0 写入，0 processing。

---

## 1. 请求

`conversation_id` 只来自 `resolve_topic_conversation` 命中的 `Conversation.id`。解析失败时不调用 `execute`，结果为 `CONVERSATION_NOT_RESOLVED`，`list_*` 次数为 0。

```text
QueryRequest {
    conversation_id
    message_id
    sender_id          只作追踪，不参与过滤
    query_type
    topic_id?
    topic_title?
}
```

没有 `assignee`、`status`、`time_scope`。

## 2. 结果

```text
QueryResult {
    query_type
    conversation_id
    items
    total              len(items)
    source
    sources
    generated_at
    empty              total == 0
    outcome            OK | EMPTY | NOT_FOUND | AMBIGUOUS
                       | OUT_OF_SCOPE | CONVERSATION_NOT_RESOLVED
}
```

每条记录先检查 `item.conversation_id == request.conversation_id`。不一致就丢弃。Service 只把这个 id 传给 `list_*`，不列会话目录，不打开另一个 conversation。

## 3. 读法

```text
LIST_TOPICS       list_topics，不按 status 删
LIST_TASKS        list_tasks，不按 status 删，状态原样是 OPEN
LIST_DECISIONS    list_decisions
                  去掉 id 被任何记录的 supersedes_decision_id 指向的项
                  created_at 降序
                  不改 status，仍是 RECORDED
LIST_RISKS        list_risks 全部
OPEN_RISKS        其中 status == OPEN
```

DTO 只复制契约里的键。任务不带 `due_at`。风险不带 `severity`、`owner`、`due`。

## 4. TOPIC_SUMMARY 绑定

命中即停：

```text
1. topic_id 在当前会话命中
2. topic_title 与 title 全字相等，且只有一个
3. 没有指定主题，且当前会话恰好 1 个 Topic
```

否则：

```text
0 个主题                         EMPTY
指定了 topic_id 但不存在          NOT_FOUND，不用其它主题补
指定了标题但 0 命中               没有主题则 EMPTY，否则 NOT_FOUND
标题命中多个，或未指定且有多个      AMBIGUOUS
```

`AMBIGUOUS` 的 items 只有 `id` 和 `title`。不按 `last_message_at` 或 `message_count` 挑一个。

摘要只带该 `topic_id` 的任务、未被 supersede 的决定、`status == OPEN` 的风险。不读聊天全文。

## 5. 与 P6-G6 / P7 的边界

查询不调用 `get_processing`，不补 processing，不 Retry，不读 Operations 三态。实体已经落盘就可以被查到。

## 6. Formatter

输入 `QueryResult`，输出微信纯文本。

```text
空任务    当前未查询到已记录的任务。
空风险    当前未查询到已记录的风险。
空决定    当前未查询到已记录的决定。
空主题    当前未查询到已记录的主题。
```

任务状态写 Store 里的 `OPEN`，不译成「进行中」或「待处理」。负责人为空写「未记录」。有 `due_text` 才写「时间说明」。

决定头是「当前记录到 N 条决定（按记录时间从新到旧）」。不写「刚才」。

未关闭风险写「当前记录到 N 条未关闭的风险」，状态行仍是 `OPEN`。

多个主题：

```text
当前会话有多个主题，请用主题名称再问一次：
1. 接口联调
2. 验收准备
```

主题摘要某一侧为空时，主题头仍然在，该侧写对应的「未查询到已记录」句子。
