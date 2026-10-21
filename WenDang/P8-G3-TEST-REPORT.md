# P8-G3 Test Report

> 日期：2026-09-23

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g3_query_delivery
```

这一组与 P8-G1、P8-G2 一起跑：

```text
Ran 89 tests in 2.096s
OK
```

其中 `tests.test_p8g3_query_delivery` 22 条。P8-G1 仍是 42，P8-G2 仍是 25。

---

## 1. 要求的场景

| 测试 | 结果 |
| --- | --- |
| DELIVERY-01 锁忙时 Query handled，旁路 0，Chat 0，发送 0，pending 1，尚未读 Store | PASS |
| DELIVERY-02 `release_session` 本身不补发；随后 flush 才 `QueryService` 1 次并 `send_reply` 1 次 | PASS |
| DELIVERY-02 Chat `process_user_messages` 结束后补发，Chat 模型只被你好调用一次 | PASS |
| DELIVERY-03 挂起期间新增 Task，补发正文包含新 Task | PASS |
| DELIVERY-04 classifier 调用在补发后仍为 1，回复来自 Store 而不是模型 answer | PASS |
| DELIVERY-05 FIFO：任务然后风险 | PASS |
| DELIVERY-06 同一 `conversation_id + message_id` 只保留 1；同文不同 message_id 保留 2 | PASS |
| DELIVERY-07 pending 2，Stop 后 pending 0，`send_reply` 0，Query Service 0 | PASS |
| DELIVERY-08 Stop 再 STARTING/RUNNING，旧 pending 不在；新 Runtime 也是空的 | PASS |
| DELIVERY-09 emergency stop 后不发送 | PASS |
| DELIVERY-10 超过 60 秒，flush 丢弃，日志 `PENDING_QUERY_EXPIRED`，不发给用户 | PASS |
| DELIVERY-11 `@智群Agent 你好` 仍进原 Chat，pending 0 | PASS |
| DELIVERY-12 锁空闲时不入队，直接 Query Service + `send_reply` | PASS |
| DELIVERY-13 Command 固定文案忙时入队，释放后原句发送，不读 Store | PASS |
| DELIVERY-14 classifier invalid 忙时入队固定指引，补发不再调用 classifier | PASS |

## 2. 同时锁住的约束

```text
补发不跨 chat
冷却未过时已入队的 Query 保留，冷却结束后再发
第 4 条丢弃最新，前 3 条顺序不变
两个线程同时 flush 只发送 1 次
release_session 源码没有 pending / flush
delivery 与 collaboration_query 不含 Engine(、Extractor、write_processing、commit_apply、retry、SendMsg、get_deepseek、operations_action_audit
Chat finally 在 release_session 之后才 notify
四个 Engine flag 仍为 false
```

DELIVERY-02 在补发前把宿主会话列表改成另一个群。回复仍是原来的 `conv_a`，说明没有重新解析会话。
