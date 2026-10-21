# P8-G0 Chat Routing Audit

> 日期：2026-09-23  
> 方法：只读扫描当前代码。不根据旧文档补链。

---

## 1. 一条 `@智群Agent 现在有哪些任务？` 的真实路径

监听注册在 `bot.py`：`wx.AddListenChat(nickname=user_name, callback=message_listener)`。微信回调进入 `message/listener.py` 的 `message_listener(msg, chat)`。

```text
WeChat message
↓
wx.AddListenChat callback
↓
message_listener                         message/listener.py
↓
InboundMessage = inbound_from_wx_message message/identity.py
    conversation_id = chat_wxid 或 chat_name
    这不是 Topic/Task Store 使用的 Conversation.id
↓
runtime.is_accepting_work()              bot_runtime.py
    false → evaluate_inbound 记一笔后 return
    不入 Topic 旁路，不进 Chat，不 send_reply
↓
classify_incoming_attr                   message/pipeline.py
    自己拍一拍 / 非好友 → return
↓
is_user_group_chat(who)                  bot.py
    GetListenChatType：group / friend
↓
runtime.evaluate_inbound                 bot_runtime.py
    outbound.match                       message/outbound.py
    is_self_message                      message/identity.py
    dedupe.check                         message/dedupe.py
    decide_trigger                       message/trigger.py
        decide_should_process            message/pipeline.py
            群：evaluate_group_trigger   group_rules.py
            私聊：who 是否在 listen_users
↓
verdict.action == REPLY 或 NO_ACTION
↓
try_enqueue_topic_sidepath               topic_sidepath.py
    发生在 REPLY 分支继续之前
↓
仅 REPLY 继续
↓
语音 / 链接 / 引用 / 合并转发 文本化
↓
handle_wxauto_message                    message/handler.py
    /命令 → send_reply 后结束
    提醒关键词 → 可能结束
    图片 / 表情 / URL
    log_user_message_to_memory
    user_queues[who] 追加一条
↓
check_inactive_users 等到 QUEUE_WAITING_TIME
↓
process_user_messages                    message/processor.py
    is_accepting_work / session / allow_reply
    可选联网搜索
    load_chat_prompt → get_user_prompt   memory_store.py
    get_deepseek_response                llm_client.py
        system = Chat Prompt（+ 可选记忆片段）
        history = chat_contexts
        user = 合并后的队列文本
        call_chat_api_with_retry
↓
send_reply                               bot.py
    runtime.submit_send
    runtime.ensure_can_send
    runtime.register_outbound
    wx.SendMsg
```

群里这条消息能进 Chat，是因为 `detect_group_at` 用 `RuntimeIdentity.bot_name` 去掉 `@名字`，`evaluate_group_trigger` 得到 `at_triggered=True`。`decide_trigger` 因此给出 `action=REPLY`。`content_for_handler` 形如：

```text
[群聊消息-来自群'{who}'-发送者:{sender}]:现在有哪些任务？
```

随后整段文本进入 `user_queues`，再进入主 Chat Prompt。没有任何步骤读取 `task_store`。

私聊没有 `@` 这一步。`decide_should_process` 只看 `who in listen_users`。在监听名单内则 `reason=private_listen_list`，同样 `REPLY`，然后走同一条 handler → queue → LLM → `send_reply`。

---

## 2. P0 在 Query 之前已经做完的事

`BotRuntime.evaluate_inbound` 的顺序是固定的：

```text
stopped
→ outbound
→ self
→ system / recall
→ duplicate
→ 私聊名单或群触发
```

`decide_trigger` 的动作只有 `NO_ACTION` 和 `REPLY`。`UPDATE_ONLY` 在 `message/trigger.py` 里有常量，当前这条准入函数不会返回它。

群触发条件在 `group_rules.py`：

```text
accept_all
或 enable_at 且文本命中 @{bot_name}
或 enable_keyword 且命中关键词
然后还有回复概率
```

未命中时 `decide_trigger` 的 reason 是 `unauthorized`，action 是 `NO_ACTION`。listener 在旁路调用之后 return，不进 Chat。

因此 P8 v1 应继续使用这次 `REPLY` 作为 Query 的门。不要对所有群消息做 Query。不要放宽监听名单。

---

## 3. Query 消息今天会不会进业务旁路

会，只要 Engine 打开。

`message_listener` 在判断 `verdict.action != REPLY` 之前就调用 `try_enqueue_topic_sidepath(inbound, verdict)`。

`classify_topic_skip` 对下面两种情况返回“可以入队”：

```text
action == REPLY
action == NO_ACTION 且 reason == unauthorized
```

`@Agent 现在有哪些风险？` 是 `REPLY`，所以 Engine 打开时会入 Topic 队列。Topic worker 成功且不是 replay 时，`_fanout_topic_result` 再调用：

```text
try_enqueue_task_after_topic
try_enqueue_decision_after_topic
try_enqueue_risk_after_topic
```

提取器可能把“有哪些风险”写成新的业务语义。这是 P8 必须切断的副作用。

当前四个 `*_ENGINE_ENABLED` 常量为 false。`TopicSidepath.try_enqueue` 在分类之前就返回 `TOPIC_ENGINE_DISABLED`，不会写 Store。所以今天这条消息只进 Chat，不进 Engine。开关一旦打开，现有代码不会因为这句话是查询而跳过旁路。

未 `@` 的普通群消息在 Engine 打开时仍会进 Topic（`unauthorized` 也放行），但不会进 Chat。P8 v1 不把这类消息改成 Query。

---

## 4. 三个插入位置

### 方案 A：listener 返回之后、Chat 之前

对应 `handle_wxauto_message` 或 `process_user_messages` 开头。

此时 `try_enqueue_topic_sidepath` 已经跑完。Query 只能换掉 Chat 回复，挡不住 Topic / Task / Decision / Risk。队列还会把查询和前后几条消息拼在一起，并且 `log_user_message_to_memory` 已经写过。

不采用为最终插入点。

### 方案 B：Chat 路径内部、Prompt 之前

对应 `process_user_messages` 里 `get_deepseek_response` 之前。

比方案 A 更晚。旁路、记忆日志、队列合并都已经发生。Query 还会经过 `QUEUE_WAITING_TIME`。Prompt 装载函数 `get_user_prompt` 只拼 Chat Prompt 和核心记忆，不读四个业务 Store。

不采用。

### 方案 C：Chat LLM 内用 Prompt 判断

模型既决定是不是查询，又生成答案。Store 不在调用链上。不可单测，会幻觉，也无法限制会话范围。

禁止。

### 采用的插入点

在 `message_listener` 内部，紧挨着现有旁路调用之前：

```text
verdict = runtime.evaluate_inbound(...)
↓
若 action == REPLY：
    Query Intent（只输出类型，不输出答案）
    ├─ Collaboration Query
    │     不调用 try_enqueue_topic_sidepath
    │     不调用 handle_wxauto_message
    │     不写 chat_contexts
    │     Query Service 同步读当前 Conversation.id
    │     Reply Formatter
    │     send_reply
    ├─ 明确的写指令
    │     同样不入旁路、不进 Chat
    │     固定文案：当前不支持修改
    └─ NOT_QUERY
          保持今天的旁路 + handler + Chat
```

这是能同时满足四条优先原则的最小位置：

```text
不污染 Topic / Task / Decision / Risk Engine
不产生新业务实体
不依赖模型记得 Store
Query Service 可单独测试
```

P8-G1 会改 `message/listener.py` 的这一处分支。不改 `decide_trigger`、dedupe、self、outbound 的判定。非 Query 的 `REPLY` 和 `unauthorized` 旁路行为保持原样。

这样做不会拆掉现有 `@Agent` Chat：只有被识别成 Query 或明确写指令的 `REPLY` 离开原路径。`@Agent 你好` 仍进原 Chat。

---

## 5. Stop、限流、发送

`is_accepting_work()` 为 false 时，listener 在 `try_enqueue_topic_sidepath` 之前 return。Query 分支如果放在这次 return 之后、旁路之前，停止状态下不会调用 Query Service，也不会调用 Chat。

`send_reply` 在真正发送前调用 `runtime.ensure_can_send`。停止或紧急停止会丢掉发送。Query 必须复用 `send_reply`，不能新写微信发送器。

Chat 的会话锁和 `allow_reply` 在 `process_user_messages`，不在 listener。Query 若跳过队列，就要在调用 `send_reply` 前自行调用 `runtime.allow_reply`，并占用同一会话锁，避免和该会话正在进行的 Chat 回复叠在一起。

`check_inactive_users` 在停止时清空 `user_queues`。Query 不进这个队列，所以不依赖这段清理，也不能绕过 `ensure_can_send`。

---

## 6. 私聊

`is_user_group_chat` 用微信监听类型区分群和私聊。两者在 `REPLY` 之后共用 handler、队列、Prompt、LLM、`send_reply`。

P8 v1：

```text
群聊：已经因 @ / 关键词 / 全局接收成为 REPLY 的消息
私聊：已经在监听名单内、因此成为 REPLY 的消息
```

不新增监听对象。未在名单内的私聊今天就是 `private_not_in_listen_list`，保持 `NO_ACTION`，不做 Query。

查询范围仍是解析出来的当前 `Conversation.id`。私聊可以查，查的是这个私聊会话自己的 Store，不是“私聊里看所有群”。

---

## 7. 现有命令不是 Query

`handle_wxauto_message` 最先看以 `/` 开头的文本命令（`/重启`、`/总结` 等），命中后 `send_reply` 并结束，不再进 Chat LLM。

```text
帮我把任务改成完成
帮我关闭风险
帮我创建任务
```

不是 `/` 命令。今天会进 Chat，Engine 打开后还会进旁路。P8 把这类句子标成 Command，不放进 Query Intent。见路由设计。

---

## 8. 同步读取

四个 Store 都是当前进程里的 JSON 文件，`list_*` 直接读该会话目录。Query v1 在回复线程里同步读。

不新建：

```text
Query Queue
Query Worker
Kafka
Redis
```
