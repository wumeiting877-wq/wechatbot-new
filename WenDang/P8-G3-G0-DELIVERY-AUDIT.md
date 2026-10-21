# P8-G3 G0 Delivery / Lock Audit

> 日期：2026-09-23  
> 只读。实现挂起补发之前，核对 session lock、`user_queues` 和 Stop。

---

## 1. 结论

Query 不能进 `user_queues`。那条队列的唯一消费者会调用 Chat LLM。

会话锁是 `BotRuntime._session_busy` 里的 `chat_id`。`release_session` 没有回调。Stop 会直接清空这组锁，不逐个 `release_session`。

因此本 Gate 使用进程内 `pending_agent_reply`，挂在 Runtime 实例上。Chat 在 `process_user_messages` 的 `finally` 里释放锁之后补发。不改 `release_session` 本身。

---

## 2. 七个问题

### 2.1 Chat session lock 的真实 key 是什么？

`chat_id` 字符串，放在 `BotRuntime._session_busy` 这个 set 里。

微信主链里它就是监听窗口名，例如 `项目群A`，不是 Conversation UUID。`try_acquire_session(chat_id)` 成功就把这个字符串加进去。

`session_lock()` 是另一套按 `chat_id` 放的 `threading.Lock`。Chat 和 P8 Query 都不走它。真正挡住并行回复的是 `_session_busy`。

### 2.2 谁 acquire？

两处：

```text
message/processor.py  process_user_messages
    runtime.try_acquire_session(user_id)

collaboration_query.py  发送前
    runtime.try_acquire_session(chat_id)
```

`user_id` 和 Query 的 `chat_id` 是同一个窗口名。

### 2.3 谁 release？

```text
process_user_messages
    队列被取空、异常、以及 finally 都会 release_session(user_id)

collaboration_query 发送路径
    finally release_session(chat_id)

begin_graceful_stop
    直接 clear _session_busy
    不调用 release_session
```

### 2.4 release 之后有没有 hook？

没有。`release_session` 只做 `discard`。

Runtime 已有的是 Stop / Emergency hook：`register_stop_hook`、`register_emergency_hook`。`begin_graceful_stop` 会跑这两类 hook。`activate_emergency` 只跑 emergency hook。它们都发生在锁已经被清空之后，不能当成“锁释放后补发”的回调。

### 2.5 `user_queues` 是否只服务 Chat？

是。结构是 `{user_id: {messages, last_message_time, sender_name, username}}`。

写入方是 `message/handler.py` 和 `reminders.py`。消费方只有 `check_inactive_users` → `process_user_messages`。合并后的正文进入 `get_deepseek_response`。Stop 时这个队列会被清空。

### 2.6 Query 能否复用现有 queue 而不进入 Chat LLM？

不能。队列里没有类型字段。一旦被 `process_user_messages` 取走，就会走联网判断和主 Chat 模型。无法只复用存储、不复用处理器。

### 2.7 最小 pending 放哪里？

放进程内存，键是 session lock 的 `chat_id`。不写 Topic / Task / Decision / Risk，不写 `processing`，不写 operations audit，不持久化。

保存的是路由完成后的 `AgentReplyPlan`，不是已经格式化好的查询结果。

---

## 3. 忙时丢失是怎么发生的

P8-G2 的顺序是：

```text
规则 / classifier
↓
Query Service
↓
allow_reply
↓
try_acquire_session
↓
send_reply
```

`try_acquire_session` 失败时，Query 已经返回 handled，旁路和 Chat 都不会再接。旧实现直接 return，回复被丢掉。用户只能再问一次。

`allow_reply` 先于锁。冷却未过时，P8-G1 就是不发、也不回 Chat。这不是本 Gate 要修的丢失。

---

## 4. 时效

`QUEUE_WAITING_TIME` 是 7 秒，只决定 Chat 合并窗口，不是模型最长耗时。`REPLY_COOLDOWN_SECONDS` 是 10 秒。Chat 回复本身没有硬上限。

如果忙的时候就把 Store 结果格式化好，几十秒后补发的是旧快照。Query Service 是只读的，可以延后到真正发送之前再执行。Classifier 不能延后，也不能再跑一次。

TTL 取 60 秒：盖得住一次慢回复加上冷却重试，又不会在很久之后突然回答。过期只打 `PENDING_QUERY_EXPIRED`，不另发一条消息。

---

## 5. Stop

`is_accepting_work()` 在 `STOPPING` / `STOPPED` / emergency / stop flag 下为 false。

`begin_graceful_stop` 和 `activate_emergency` 都会清发送队列，并调用已注册的 hook。pending 必须在这些 hook 里清空。不能等下一次 `release_session`，因为 Stop 不走 release。

pending 只在内存里。Stop 之后再启动，无论是新进程还是同一个 Runtime 重新进入 `STARTING`，旧 pending 都不存在。
