# P8-G1 Current State Audit

> 日期：2026-09-23  
> 范围：进入实现前的只读核对。基线是 P8-G0 = COMPLETE，且 P8-G0 没有改生产代码。

---

## 1. 入站路径

`message/listener.py` 的 `message_listener` 在 `runtime.evaluate_inbound(...)` 之后、判断 `action != REPLY` 之前，直接调用 `try_enqueue_topic_sidepath`。

因此在本 Gate 之前：

```text
action == REPLY     会入 Topic 旁路（Engine 打开时），然后进 handle_wxauto_message → Chat
action == NO_ACTION 且 reason == unauthorized
                    仍会入 Topic 旁路，但不进 Chat
stopped             listener 在 Router 可能出现的位置之前就 return
```

`/` 命令在 `message/handler.py` 的 `handle_wxauto_message` 里处理，不在 listener。

群 `@` 由 `group_rules.detect_group_at` 去掉 `@{bot_name}`。`verdict.extra` 只有 `content_for_handler`，没有单独的 `processed_content`。

## 2. 会话键

`InboundMessage.conversation_id` 是 `chat_wxid` 或 `chat_name`，不是 Store 用的 `Conversation.id`。

`topic_engine.resolve_topic_conversation` 的顺序已经固定：

```text
chat_wxid → find_by_platform_conversation_id
否则 chat_name → find_conversation_by_display_name（platform == WECHAT）
```

四个 Store 的 `list_*` 都只打开 `data/<store>/conversations/<conversation_id>/` 下的一个文件。没有跨目录扫描 API。

## 3. 只读能力

| 查询 | 现成方法 | 本 Gate 需要在内存里补的规则 |
| --- | --- | --- |
| LIST_TOPICS | `topic_store.list_topics` | 不按 status 删行 |
| LIST_TASKS | `task_store.list_tasks` | 不按 status 过滤；生产 status 为 OPEN |
| LIST_DECISIONS | `decision_store.list_decisions` | 去掉被 `supersedes_decision_id` 指向的 id；`created_at` 降序 |
| LIST_RISKS | `risk_store.list_risks` | 原样返回 |
| OPEN_RISKS | 同上 | 只留 `status == OPEN` |
| TOPIC_SUMMARY | `list_*` + 绑定 | 不读 `messages.jsonl`，不读 processing |

DTO 必须丢掉 Store 里有、但契约不展示的键：`due_at`、`confidence`、`schema_version`、`severity`、`owner`。

## 4. 发送与锁

Chat 回复走 `bot.send_reply`。它内部做 `ensure_can_send`、`submit_send`、`register_outbound`。真正发出后 `note_replied`。

限流在 `runtime.allow_reply`。Chat 在 `process_user_messages` 里先 `allow_reply`，再用 `try_acquire_session` / `release_session`。Query 跳过这条函数，所以回复前必须自己调用同一组方法。

`runtime.is_accepting_work() == false` 时，listener 在准入之后立即返回，不会进入后续回复。

## 5. 当时不存在的东西

```text
没有 Query Router
没有 Query Service
没有确定性 Formatter
没有 Query Queue
Chat Prompt 不读四个业务 Store
```

四个 Engine 常量与 `is_*_engine_enabled()` 均为 false。`runtime_control` 下没有开关文件。

## 6. 对实现的约束

```text
不改 Store schema
不改 P0 Dedupe
不改 Engine / processing schema
不新增 Queue / Worker
不调用 Chat LLM 生成查询答案
Query / Command 不得进入 Topic 旁路和 Chat
NOT_QUERY 与未 @ 群消息保持原路径
```

现有 `test_topic_sidepath` 要求源码里 `try_enqueue_topic_sidepath` 仍出现在 `verdict.get("action") != REPLY` 之前。Query 分支必须在这次调用之前 return，而不是把旁路调用挪到 REPLY 判断之后。
