# P8-G3 Implementation Report

> 日期：2026-09-23

---

## 1. 新增

`agent_reply_delivery.py`

```text
offer_agent_reply          空闲则现在发送，只有锁忙才入队
notify_session_released    指定 chat 补发
flush_idle_pending         给已有的空闲检查循环用
clear_pending              Stop / Emergency / 停止中的检查循环
pending_count / pending_snapshot
```

队列挂在 Runtime 的 `_agent_reply_pending` 上，不进 `snapshot()`，不写状态文件。

## 2. 查询接入

`collaboration_query.py` 在路由完成后构造 `AgentReplyPlan`，再交给 delivery。

```text
QUERY     保存 query_type、topic、收到时的 conversation_id
FIXED     保存固定文案
```

`_materialize` 在发送当时调用 `QueryService`。`conversation_id` 为空时只走 `conversation_not_resolved`，不重新 `resolve_topic_conversation`。`_transmit` 仍只调用宿主 `send_reply`。

Classifier 和规则仍在 `handle_collaboration_route` 里、拿锁之前跑完。补发不会再调用 `route_hybrid`。

## 3. 接到现有释放点

`message/processor.py` 只加了三处调用，Chat 合并、等待时间和主模型路径没有改：

```text
process_user_messages finally
    release_session 之后 notify_session_released

check_inactive_users
    已停止时 clear_pending
    正常轮次末尾 flush_idle_pending
```

`BotRuntime.release_session` 没有改。

## 4. 保护

```text
每 chat FIFO，最多 3 条，超出丢弃最新
conversation_id + message_id 去重（message_id 非空）
TTL 60 秒，过期不发给用户
同一 chat 的 flush 互斥
发送前重新 is_accepting_work() 和 allow_reply()
Stop hook 与 Emergency hook 清空队列
```

第一次到达就因冷却被 `allow_reply` 拒绝的，仍然不入队。这是 P8-G1 的行为。已经因为锁忙入队的，补发时若还在冷却，留在队列里。

## 5. 没有改

```text
query_service.py 的六类查询
query_intent_classifier.py 的枚举和 prompt
query_router.py 的规则
P0 dedupe
四个 Engine flag
业务 Store schema
operations_action_audit
```
