# P8-G3 Current State Audit

> 日期：2026-09-23  
> 进入实现前的缺口。锁和队列的只读结论见 `P8-G3-G0-DELIVERY-AUDIT.md`。

---

## 1. 冻结基线

```text
P0–P5 = CLOSED / COMPLETE
P6-G0 … P6-G5 = COMPLETE
P6-G6 = BLOCKED / TYPE C
P7-G0 … P7-G2 = COMPLETE
P8-G0 = COMPLETE
P8-G1 = COMPLETE
P8-G2 = COMPLETE
```

进入本 Gate 时：

```text
P8-G2 targeted = 25 OK
P8-G1 targeted = 42 OK
Non-Live Regression = 690 OK
```

四个 Engine 都是 `false`。本 Gate 不改它们。

## 2. 已有查询链

`message/listener.py` 在 `evaluate_inbound` 得到 `REPLY` 之后、主题旁路之前调用 `handle_collaboration_route`。

P8-G2 已经把 classifier 放在 session lock 之前。命中 Query、Command、跨会话、身份查询或分类失败时，函数返回 true，调用方直接结束。不会进 Topic Sidepath，也不会进 `handle_wxauto_message`。

发送只走宿主的 `send_reply`。模块里没有 `wx.SendMsg`。

## 3. 唯一缺口

当前 Chat 已经持有 `try_acquire_session(chat_id)` 时：

```text
Query 已被识别
Query 已被消费
不进旁路
不进 Chat
拿不到锁
本轮不发送
```

用户必须重新问一次。

普通 `@Agent 你好` 仍走原来的 `user_queues` → `process_user_messages` → `get_deepseek_response`。这条链本 Gate 不重构。

## 4. 不能动的边界

```text
P0 duplicate 仍在 Router 之前
六类 Query 语义不变
Classifier 枚举不变
不写业务 Store
不写 operations_action_audit
不新增 Redis / Kafka / 数据库队列 / Scheduler / 跨进程队列
不新增 Engine
不处理 MY_TASKS、负责人映射、写 Command、跨会话查询、Reminder、自动 Retry
Live Extractor 的 Connection error 继续单独记录
「任务怎么样了」的 CLASSIFIER_INVALID 不在本 Gate 改 prompt
```
