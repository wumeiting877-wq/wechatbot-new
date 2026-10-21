# P8-G3 Delivery Design

> 日期：2026-09-23  
> 依据 G0。复用已有 session 串行，不新开 Query Worker。

---

## 1. 选择

```text
A. 复用已有会话串行     采用
B. 最小 pending         采用
C. 新线程 / 独立 Worker  不采用
```

`user_queues` 不能复用。`release_session` 不加回调：Stop 清空 `_session_busy` 时不会调用它，加回调也补不到 Stop，还会把补发塞进 Runtime 底层。

## 2. 时机

```text
规则 / Classifier          收到时做一次，之后不再做
↓
AgentReplyPlan             只保存路由结果
↓
try_acquire_session
├─ 成功
│    Query Service → Formatter → send_reply → release → 补发下一条
└─ 失败
     pending
     ↓
     同一个 chat 的 session 释放
     ↓
     再检查 is_accepting_work 和 allow_reply
     ↓
     这时才 Query Service → Formatter → send_reply
```

Query 保存的是请求，不是当时的回复正文。发送前用收到时解析出的 `conversation_id` 重读 Store。不重新解析会话。

固定文案不读 Store：

```text
Command
Classifier failure
身份查询
跨会话 OUT_OF_SCOPE
```

分类失败只挂起当时的固定指引，不挂起重试 classifier。

`allow_reply` 在第一次到达时失败，仍按 P8-G1 丢掉，不入队，也不回 Chat。已经入队之后如果碰到 10 秒冷却，保留这条，等下一次空闲检查，不丢掉。

## 3. AgentReplyPlan

```text
kind = QUERY | FIXED

chat_id            session lock 的窗口名
conversation_id    QUERY 才有，路由时解析
message_id
sender_id

query_type         QUERY
topic_id           QUERY
topic_title        QUERY

fixed_text         FIXED
created_at
```

Router 仍然只做 route。什么时候读 Store、什么时候发送，由 `agent_reply_delivery.py` 决定。真正的 `QueryService.execute` 留在 `collaboration_query._materialize`，发送回调只调用宿主 `send_reply`。

## 4. 队列

每个 Runtime 实例自己的内存：

```text
chat_id -> FIFO，最多 3 条
```

一个微信窗口对应一把 session lock，也对应这一条队列。第 4 条丢弃最新的，不覆盖旧的，不另发“太忙”文案。

去重键：

```text
conversation_id + message_id
```

`message_id` 为空时不去重，避免把无法识别的两条消息折叠掉。不按正文去重。P0 的平台消息去重不改。

TTL 60 秒。过期丢弃，日志 `PENDING_QUERY_EXPIRED`，不通知用户。

## 5. 补发

同一个 chat 同时只允许一次 flush。一次 flush 按 FIFO 发送，下一条必须重新 `allow_reply` 并重新拿锁。拿到锁之后才读 Store。

触发点：

```text
process_user_messages finally
    release_session 之后 notify_session_released(chat_id)

本模块自己发送并 release 之后
    继续 flush 同一 chat

check_inactive_users
    每轮末尾 flush_idle_pending
    只处理当前没有 session lock 的 chat
```

`check_inactive_users` 是已经存在的循环，用来度过 Chat 刚刚 `note_replied` 之后的 10 秒冷却。不是新 Worker，也不是 Scheduler。

别的 chat release 不能补发这个 chat。

## 6. Stop / Restart

第一次 `offer` 时给这个 Runtime 注册 stop hook 和 emergency hook。两者都只清空 pending，不发送。

```text
STOPPING / STOPPED / emergency
    is_accepting_work() == false
    flush 再次看到时也清空，不 send_reply

check_inactive_users 发现已停止
    清空 user_queues 之外，再 clear pending
```

不落盘。重启后的新 Runtime 是空的。同一个进程里 Stop 再进入 `STARTING`，队列也已经清掉，不会恢复。

## 7. 不做什么

```text
不改 release_session
不改 user_queues 的合并和 Chat 模型
不改四个 Engine flag
不改 Query Service 的六类语义
不改 Classifier 枚举
不写 Store / processing / operations audit
```
