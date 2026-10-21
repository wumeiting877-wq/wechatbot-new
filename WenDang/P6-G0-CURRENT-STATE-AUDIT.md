# P6-G0 当前状态审计

> 日期：2026-09-22  
> 阶段：P6-G0 **READ ONLY** 全链路生产化稳定性审计  
> 未修改任何业务源码、未改开关长期值、未接 Real LLM。

```text
P0 = CLOSED
P1 = CLOSED
P2 = CLOSED
P3 Topic Engine = COMPLETE
P4 Task Engine  = COMPLETE
P5-G0 … P5-G4   = COMPLETE

P6-G0           = BLOCKED
```

BLOCKED 原因见 `P6-G0-BLOCKER-REPORT.md`。  
N2 Duplicate Topic Extractor 的 **RCA 已完成**，见 `P6-G0-DUPLICATE-TOPIC-RCA.md`：不是双 listener，也不是同一 MessageRecord 被 worker 处理两次。

---

## 冻结基线核对

| 模块 | 状态 | 本轮 |
|---|---|---|
| P0 Self / Dedupe / Outbound / Stop Bot | CLOSED | 只读。未改 |
| P1 Conversation | CLOSED | 只读 |
| P2 AgentConfig / Prompt Binding | CLOSED | 只读 |
| P3 Topic Engine / Store / Extractor / Side-path | COMPLETE | 只读。未改 TOPIC_EXTRACTOR 语义 |
| P4 Task Engine | COMPLETE | 只读 |
| P5 Decision Engine | COMPLETE | 只读。DJ-R8 仍 Deferred |
| P5 Risk Engine | COMPLETE | 只读。未为 RK-R9 改 Decision |

四个 Engine 模块默认 `*_ENGINE_ENABLED = False`。审计时刻 `runtime_control` 四个开关文件均为 `false`。

---

## Gate 0–9 结论摘要

| Gate | 结论 |
|---|---|
| 0 拓扑 | 真实链：`WeChat DB Listener → message_listener → evaluate_inbound → try_enqueue_topic_sidepath → Topic worker → fan-out`。仓库仅一个 `bot.py` |
| 1 listener 实例 | **每 Bot 进程 1 个** `db.Listener` 线程。`add_listener` **append**。`keep_alive` 可在 Stop 后重新 `AddListenChat` |
| 2 inbound identity | N2 样本是 **两条微信消息**（local_id 115 与 116），不是一次事件两次 callback |
| 3 Topic queue | 单 worker；无成功路径 retry；同一 `MessageRecord.id` 入队 1 次则 Extractor 1 次 |
| 4 Stop/Start | Stop 清 queue / StopListening；**不 join keep_alive**；进程可能残留；`start_bot` 不扫孤儿 PID |
| 5 Dedupe 边界 | P0 key = `platform_message_id`（否则 event_hash），TTL **120s**，发生在 Topic enqueue **之前**。同文不同 local_id **不去重**（有意为之） |
| 6 fan-out | 每个 Topic SUCCESS 各 1 次 Task/Decision/Risk enqueue。N2 因两条 inbound 变成 2/2/2。Store processing_key 防脏写 |
| 7 Store 幂等 | upsert 按 id / platform_message_id；成功 processing 拒绝覆盖；FAILED 允许再跑 |
| 8 LLM 次数 | 每条 distinct inbound：Topic/Task/Decision/Risk 各 ≤1 成功调用（Risk R12 为 timeout FAILED）。Chat 对 @ 各 1。观测日志把四个 Extractor 都记成 `topic_extractor` |
| 9 Stop Bot | 状态机 STOPPING→STOPPED 有效；P5-G4 R17 进程退出后不再 ingest。代码上 keep_alive 仍可能在残留进程里把 listener 拉回来 |

---

## 十三问（N2）

| # | 问题 | 答案 |
|---|---|---|
| 1 | 重复发生在哪一层？ | **微信层两条 SQLite 行**，不是 Topic worker / Extractor 重入 |
| 2 | 两次入口是否相同？ | 都是 `message_listener` ← 同一 Listener 线程，两次独立 callback |
| 3 | 是否相同 message_id？ | **否**。P0：`…:115` vs `…:116`。Topic：`msg_36ddcb06012c` vs `msg_c12a74795b40` |
| 4 | 是否相同 MessageRecord？ | **否**。`messages.jsonl` 两行 |
| 5 | 是否同一个 process？ | 是（P5-G4 记录 Bot pid=44864） |
| 6 | 是否同一个 thread？ | Listener 同线程两次投递；Topic worker 顺序处理两条 payload |
| 7 | 是否多个 listener？ | **本样本否**。同一 pid 两次 `dedupe=NEW` |
| 8 | 是否 worker 重入？ | 否。单 worker，无成功路径 requeue |
| 9 | 是否存在 retry？ | 本样本否。Extractor client 有 JSON/空响应 1 次重试能力，本条 audit 各 1 次 SUCCESS |
| 10 | 是否与 Start/Stop 有关？ | **本样本无关**（R12 窗口 RUNNING）。Stop 生命周期另有独立风险 |
| 11 | 是否传播到 Task/Decision/Risk？ | **是**。两条 inbound 各 fan-out 一套。Risk 均 `EXTRACTOR_TIMEOUT` FAILED |
| 12 | 是否重复写 Store？ | 两个 MessageRecord。无重复 Topic/Task/Decision/Risk 实体。两条 FAILED processing |
| 13 | 是否额外 LLM？ | **是**。相对「用户以为的一句」：多 1 次 Topic + Task + Decision + Chat；Risk 多 1 次 timeout |

---

## 建议的最小 instrumentation（本轮未改生产码）

统一字段：`trace_id, message_id, platform_message_id, local_id, conversation_id, stage, thread_name, pid, ts`

阶段：`INBOUND_RECEIVED / MESSAGE_RECORD_CREATED / TOPIC_ENQUEUE / TOPIC_DEQUEUE / TOPIC_EXTRACTOR_START / TOPIC_EXTRACTOR_END / TOPIC_STORE_WRITE / TASK_ENQUEUE / DECISION_ENQUEUE / RISK_ENQUEUE`

另外：`get_extractor_response` 不得把 Task/Decision/Risk 记成 `topic_extractor`。

等待下一 Gate 再改。
