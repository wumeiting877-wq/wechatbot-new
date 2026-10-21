# P8-G0 Security and Scope

> 日期：2026-09-23  
> v1 硬边界：一次查询只读当前会话已经落盘的业务实体。

---

## 1. 会话锁定

群里问“现在有什么任务”，Query Service 只能读这次入站解析出的 `Conversation.id`。

解析使用现有 `resolve_topic_conversation`：

```text
chat_wxid → platform_conversation_id
否则 chat_name → display_name（platform = WECHAT）
```

禁止：

```text
使用 InboundMessage.conversation_id 直接当 Store 键
遍历 data/*/conversations/
按群名模糊搜索其他会话
用员工昵称找到“他的其他群”
```

群 A 的用户不能通过 Query 读到群 B 的 Store。私聊同样只读该私聊自己的 `Conversation.id`。

另一个群的问法：

```text
帮我看另外一个项目群有什么任务
```

`outcome = OUT_OF_SCOPE`。不自动搜索。

会话解析失败：`CONVERSATION_NOT_RESOLVED`。不用别的会话补结果。

---

## 2. 谁可以触发

沿用 P0，不扩大监听。

```text
群：evaluate_group_trigger 得到 REPLY（@、关键词或全局接收，且通过回复概率）
私聊：who 已在 listen_users，reason = private_listen_list
```

不在名单中的私聊保持 `NO_ACTION`。未触发的群消息不进 Query Router。

v1 同时覆盖群聊和已在监听名单内的私聊。两者今天已经能进 Chat。Query 不新增聊天窗口。

---

## 3. Stop

`runtime.is_accepting_work()` 为 false 时，`message_listener` 在旁路和 handler 之前返回。Query 分支放在这次返回之后，因此停止时不会调用 Query Service、Chat、`send_reply`。

发送端 `send_reply` → `ensure_can_send` 在 STOPPING / 紧急停止时拒绝 `wx.SendMsg`。Query 不另做发送器，所以这段仍然生效。

Query 在调用 `send_reply` 之前还要调用 `allow_reply` 和该会话的会话锁。这两项今天在 `process_user_messages`，跳过队列就不能漏掉。

---

## 4. 不碰的系统

```text
不写四个业务 Store
不写 processing
不调用 topic_retry / downstream_retry
不因为查询结果异常去 Retry
不读 Operations Read Model 来回答员工
不把 UNKNOWN 说成业务结论
```

P6-G6（有实体但缺 processing）保持原状。Query 只展示实体，不补 processing。

---

## 5. 身份

```text
MY_TASKS、TASKS_BY_ASSIGNEE
```

v1 不做。Task 没有可与 `sender_id` / `sender_wxid` 对应的负责人 id。`assignee_text` 是自由文本。

`sender_id` 可以放进 QueryRequest 供以后追踪，不能当作过滤条件。

---

## 6. Conversation Scope Test Plan

P8-G1 至少覆盖：

```text
QUERY-SCOPE-01
    conv_A 查任务 → 只返回 A 的 Task

QUERY-SCOPE-02
    conv_A 与 conv_B 都有 risk
    在 A 中查询 → 结果里没有 B 的 risk id

QUERY-SCOPE-03
    指定不存在的 topic_id → outcome NOT_FOUND
    不返回其他主题充数

QUERY-SCOPE-04
    问法指向其他会话 → OUT_OF_SCOPE
    调用记录上没有第二个 conversation_id 的 list_* 

QUERY-SCOPE-05
    resolve_topic_conversation 失败
    → CONVERSATION_NOT_RESOLVED
    → 零次 list_* 

QUERY-STOP-01
    is_accepting_work() 为 false
    → 不调用 Query Service
    → 不调用 send_reply
```

这些测试在 P8-G1 写。本 Gate 不新增测试代码。
