# P8-G1 Implementation Report

> 日期：2026-09-23  
> 结论：P8-G1 已实现。没有改 Store schema、P0 Dedupe、Engine decision、processing schema，也没有 Query Queue。

---

## 1. 新增模块

| 文件 | 职责 |
| --- | --- |
| `query_router.py` | 规则意图。Query / Command / OUT_OF_SCOPE / NOT_QUERY |
| `query_service.py` | 只读当前 Conversation.id |
| `query_formatter.py` | QueryResult → 微信纯文本 |
| `collaboration_query.py` | 解析会话、调用 Service、经 `send_reply` 回复 |

## 2. 唯一生产接入

`message/listener.py`：`evaluate_inbound` 之后，若 `action == REPLY`，调用 `handle_collaboration_route`。返回 True 时写 trace 并 return。

`try_enqueue_topic_sidepath` 仍在 `verdict.get("action") != REPLY` 之前，供 NOT_QUERY 和未触发群消息使用。已识别的 Query / Command / 跨会话查询在 return 之前不会执行到它。

## 3. 发送

回复函数优先用 host 上的 `send_reply`，否则用 `bot.send_reply`。调用前：

```text
runtime.allow_reply(chat_id)
runtime.try_acquire_session(chat_id)
```

发送参数 `is_system_message=True`，避免把查询回复写进记忆日志。没有 `wx.SendMsg`。

限流拒绝或会话锁拿不到时，不发送，也不退回 Chat / 旁路。

## 4. 没有做的事

```text
没有改 Chat Prompt、memory prompt、system prompt
没有 Query Classifier 模型
没有 MY_TASKS / TASKS_BY_ASSIGNEE
没有跨会话搜索
没有写命令
没有 Reminder、自动 Retry、新 Engine
没有往四个业务 Store 写查询日志
```

四个 Engine 常量仍是 false。测试里的 Topic 旁路用 `TopicSidepath(enabled=True)` 注入，不写 `runtime_control`。
