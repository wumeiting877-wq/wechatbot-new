# P8-G3 Closure Report

> 日期：2026-09-23  
> 状态：COMPLETE

---

## 1. 结论

会话空闲时，Query 仍是识别后立即读 Store 并 `send_reply`。

会话忙时，Query 不再丢失。当前回复释放 session 之后，按 FIFO 补发。补发前才执行 Query Service，Classifier 不跑第二次。

Query 仍不进 Chat，不进 Topic Sidepath。

## 2. 硬门槛

```text
会话空闲 Query → 立即回复
会话忙 Query → pending → 当前回复结束后串行回复
不进 Chat LLM
不进 Topic Sidepath
Classifier 不重复
Query Service 在发送前重新执行
conversation_id 用收到时解析的结果
同 message 不重复 pending
FIFO，每 chat 最多 3 条
TTL 60 秒，过期不通知
Stop / Emergency Stop 清空 pending，之后 send_reply = 0
Restart 不恢复旧 pending
send_reply 仍是唯一发送路径
P8-G1 42 PASS
P8-G2 25 PASS
Non-Live 旧 690 PASS，合计 712 PASS
4 Engine flags = false
```

没有触发 STOP。没有引入外部队列，没有改 Store schema，没有改 P0，没有把 pending 送进 Chat 或旁路。

## 3. 证据

```text
tests.test_p8g3_query_delivery          22 OK
tests.test_p8g1_collaboration_query     42 OK
tests.test_p8g2_query_intent            25 OK
Non-Live discover                       712 OK，排除 Real Extractor 42 条
```

文档：

```text
WenDang/P8-G3-G0-DELIVERY-AUDIT.md
WenDang/P8-G3-CURRENT-STATE-AUDIT.md
WenDang/P8-G3-DELIVERY-DESIGN.md
WenDang/P8-G3-IMPLEMENTATION-REPORT.md
WenDang/P8-G3-TEST-REPORT.md
WenDang/P8-G3-REGRESSION-REPORT.md
WenDang/P8-G3-DEFERRED-ISSUES.md
WenDang/P8-G3-CLOSURE-REPORT.md
```

## 4. 停止在这里

不进入：

```text
MY_TASKS
负责人身份映射
写 Command
跨会话 Query
Reminder
自动 Retry
新 Engine
```

等待下一步指令。
