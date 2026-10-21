# P4-G2 Gate 0：当前真实源码审计

> 日期：2026-09-21  
> 性质：**READ ONLY**。本文件写完前未修改业务代码。  
> 依据：`P4-G1-IMPLEMENTATION-REPORT.md`、`P4-G1-TEST-REPORT.md`、`P4-G1-REGRESSION-REPORT.md`、`P4-G2-READINESS.md`、`P4-G1-DEFERRED-ISSUES.md` 与真实源码。

```text
P0 STATUS          = CLOSED
P1 STATUS          = CLOSED
P2 STATUS          = CLOSED
P3-G0 / G1 / G2    = COMPLETE
P4-G0 / G1         = COMPLETE
P4-G2              = NOT STARTED
```

---

## 冻结基线核对

| 项 | 文档 | 本轮核对 |
|---|---|---|
| P0 | CLOSED | 保持。禁止改 identity / dedupe / outbound / trigger / `evaluate_inbound` |
| P1 / P2 | CLOSED | 保持。禁止改 Chat Prompt 正文 |
| P3-G2 | COMPLETE，Side-path 27 OK | `topic_sidepath.py` 已在 `listener` 的 `evaluate_inbound` 之后挂钩 |
| P4-G1 | COMPLETE，Task Offline 50 OK | `task_store.py` / `task_engine.py` / `task_extractor_client.py` / `TASK_EXTRACTOR.md` 存在 |
| G1 回归 | P0 59 / P1-P2 103 / Topic Offline 39 | 文档记录；Gate 1 后再实测 |
| G2 就绪 | `P4-G2-READINESS.md` = YES（离线） | 与源码一致：Task Engine 离线可用，**生产未挂钩** |
| 延期 D1 | Topic 成功后触发 Task | 正是本轮范围；禁止改 Trigger / Topic decision / Chat Prompt |

G1 文档与真实源码 **没有严重不一致**。不构成 BLOCKER。

```text
G2 Gate 0 = PASS
允许进入 Gate 1（只挂 Task Side-path，Heuristic / Mock，不接真实 LLM，不接真机）
不必修改 listener.py / trigger.py / bot_runtime.py / InboundMessage
```

---

## 1. TopicSidepathWorker 当前如何取得 TopicEngine 结果？

`topic_sidepath.py` 单 worker `_loop` → `_process(payload)`：

```text
result = engine.process_inbound(inbound, conversations=[conversation] + list(self.conversations))
self.last_result = result
```

`payload` 在 `try_enqueue` 时已放入：

```text
{"inbound", "conversation", "enqueued_at"}
```

`conversation` 已由 `resolve_topic_conversation` 解析，**不是** `InboundMessage.conversation_id`。

成功路径：`decision != FAILED` 且无 `error_code` → `TOPIC_PROCESS_SUCCESS`。  
当前成功路径结束后 **没有** 任何 Task 调用。

---

## 2. `TopicEngine.process_inbound` / `process_record` 实际返回什么？

两者都返回 `topic_engine.EngineResult` dataclass：

| 字段 | 含义 |
|---|---|
| `skipped` | 开关关闭 / 重放 / conversation 未解析 |
| `decision` | `NEW_TOPIC` / `EXISTING_TOPIC` / `TOPIC_UPDATE` / `UNRELATED` / `SKIPPED` / `FAILED` / `DISABLED` |
| `topic_id` | 成功归属时为 `topic_*`；UNRELATED / SKIPPED / FAILED 多为 `None` |
| `message_id` | Topic Store 中的 MessageRecord id |
| `conversation_id` | `conv_*` |
| `error` / `error_code` | 失败隔离码，如 `CONVERSATION_NOT_RESOLVED`、`EXTRACTOR_TIMEOUT` |
| `candidate_topic_ids` / `evidence_message_ids` / `confidence` | 审计 |
| `isolated` | 失败不向外抛 |
| `replayed` | 已有成功 Topic Processing |

`as_dict()` 已公开上述字段。Worker 已把 `result.as_dict()` 写入 Topic audit。

---

## 3. 是否能从返回值直接取得 decision / topic_id / message_id / conversation_id？

**能。** 四个字段都在 `EngineResult` 上，不需要改 `process_inbound` 签名。

注意：

- `UNRELATED` / `SKIPPED` / `FAILED` / `DISABLED`：`topic_id` 通常为 `None`，不得触发 Task。
- `CONVERSATION_NOT_RESOLVED`：`error_code` 有值，`conversation_id` 可能为空。
- 重放成功：`replayed=True`，仍可能带原 `decision` + `topic_id`。Task Engine 自身有 Processing 幂等。

---

## 4. 如果返回值没有完整对象，能否通过 TopicStore 公开接口读取 Topic / MessageRecord？

返回值 **没有** 完整 Topic / Message dict，只有 id。

TopicStore **已有** 公开只读接口，不必解冻 `topic_store.py`：

```text
TopicStore.get_topic(conversation_id, topic_id) -> Optional[dict]
TopicStore.get_message(conversation_id, message_id) -> Optional[dict]
```

Task Engine 入口需要的是这两个 dict，加上 `payload["conversation"]`。

```text
conversation  ← Topic worker payload（已解析）
topic         ← store.get_topic(result.conversation_id, result.topic_id)
message       ← store.get_message(result.conversation_id, result.message_id)
```

三者都可以在 `topic_sidepath._process` 成功之后、不改 listener 的情况下取得。

---

## 5. TaskEngine 的真实入口参数是什么？

`TaskEngine.process_record(conversation: dict, topic: dict, message: dict) -> EngineResult`

离线已验证。内部会：

1. `store.require_topic(cid, topic_id)` — Topic 必须已存在  
2. `topic_store.get_message` — MessageRecord 必须已存在  
3. `message_belongs_to_topic` — 当前消息必须已有 Topic Evidence  
4. 失败全部 `isolated=True`，写 Task FAILED Processing，**不改 Topic**

没有 `process_inbound`。没有 listener 挂钩。模块常量 `TASK_ENGINE_ENABLED = False`。

---

## 6. 是否需要 Task 独立 Queue？

**需要。** 理由来自真实 Topic worker 模型：

- Topic worker **concurrency=1**，`queue.Queue(maxsize=32)`，`put_nowait`。  
- `_process` 当前 **同步** 等待 Topic Extractor。  
- 若在同一 `_process` 里再同步调用 Task LLM（默认 timeout 20s），Topic 队列会积压，Stop shutdown 变慢，违反硬性能原则。

推荐：新增 `task_sidepath.py`，`Queue(maxsize=32)` + 单 worker + `put_nowait`。  
Topic 成功后 **快速 enqueue**，Topic worker 立即继续。  
Queue 满：`TASK_QUEUE_FULL`，丢弃本次 Task 分析，不影响 Topic / Chat。

不需要、也禁止：每个 Task 新开线程、无限 Queue、复用 SendQueue。

---

## 7. Topic worker 当前是否会被 LLM 调用阻塞？

**会被 Topic Extractor 阻塞**（设计如此：Side-path 已从 listener 卸下阻塞）。  
listener 只 `put_nowait`，不等待 Topic LLM。

当前 **不会** 被 Task LLM 阻塞，因为还没有 Task 调用。  
G2 若同步调用 Task，就会把 Task 阻塞叠加到 Topic worker 上。**禁止这样做。**

---

## 8. Topic 成功之后同步调用 Task 会不会延长 Topic worker 时间？

**会。** Task Extractor timeout 上限约 20s。同步等待会让：

```text
Topic queue 积压
Task timeout 反向拖慢 Topic
Stop shutdown 变慢
```

因此 G1 架构必须是：

```text
Topic 成功 → 快速 enqueue Task → Topic worker 继续
Task Engine 单独 worker 执行
```

---

## 9. Stop Bot 后 Topic worker 如何 shutdown？

已有模型（**不改 `bot_runtime.py`**）：

1. `TopicSidepath.attach_runtime` → `runtime.register_stop_hook(self.shutdown)` 与 `register_emergency_hook`  
2. `begin_graceful_stop` 遍历 `_on_stop_hooks`  
3. `shutdown`：`_stop.set()`，`get_nowait` 丢弃未处理 Topic  
4. worker 取到任务后若 `_stop.is_set()` 或 `not runtime.is_accepting_work()` → 丢弃，不处理新微信业务

Task Side-path 应 **复用同一 hook 模型**：`register_stop_hook(TaskSidepath.shutdown)`。  
首次 Task enqueue 时 `attach_runtime`。  
不要求强杀正在跑的 Task LLM 线程；完成后不得把 Stop 之后的新消息写成 Task。

listener 在 `is_accepting_work()==False` 时 **不进入** `try_enqueue_topic_sidepath`（STOPPED 快路径在 `STEP_ADMIT` 之前 return）。Stop 后不会有新 Topic，也就没有新 Task 输入。Task queue 仍须自己停止接收/消费，防止 Stop 前已入 Topic 队列、Stop 后才跑完 Topic 再投递 Task。

---

## 10. P4 挂钩是否能不改 listener / P0？

**能。**

当前 `message/listener.py` 唯一旁路：

```text
verdict = runtime.evaluate_inbound(...)
try_enqueue_topic_sidepath(inbound, verdict, runtime=runtime)
if verdict.get("action") != REPLY:
    return
```

P4 **不应**再增加第二条 Task Side-path。  
Task 挂在 Topic `_process` 成功之后即可取得 `conversation` + `EngineResult` + TopicStore 对象。

| 冻结层 | 本轮是否必须改 | 结论 |
|---|---|---|
| `message/listener.py` | 否 | 已正确挂钩 Topic |
| `message/trigger.py` | 否 | Task 不决定是否回复 |
| `bot_runtime.py` | 否 | 复用现有 stop hook |
| `InboundMessage` | 否 | 不需要新字段 |
| Self / Dedupe / Outbound | 否 | Topic 入队资格已过滤 |
| Topic decision schema / Topic Prompt / Chat Prompt | 否 | Task 只消费成功 Topic |

唯一计划解冻：

```text
topic_sidepath.py   — 成功路径末尾 try_enqueue Task（最小侵入）
task_sidepath.py    — 新增
tests/test_task_sidepath.py
tests/test_task_live_adapter.py
```

---

## Gate 0 十问结论

| # | 问题 | 答案 |
|---|---|---|
| 1 | Worker 如何取得 Topic 结果？ | `process_inbound` → `EngineResult`，存 `last_result` |
| 2 | Engine 返回什么？ | `EngineResult`（decision / topic_id / message_id / conversation_id / error_code） |
| 3 | 能否直接取四字段？ | **能** |
| 4 | Store 能否补全对象？ | **能**（`get_topic` / `get_message`） |
| 5 | Task 入口？ | `process_record(conversation, topic, message)` |
| 6 | 要不要独立 Queue？ | **要**（禁止同步等 Task LLM） |
| 7 | Topic worker 会被 LLM 阻塞吗？ | 会被 Topic LLM 阻塞；目前无 Task |
| 8 | 同步 Task 会延长 Topic worker 吗？ | **会，禁止** |
| 9 | Stop 如何停 Topic worker？ | `register_stop_hook` + `shutdown` 丢队列 |
| 10 | 能否不改 listener / P0？ | **能** |

---

## BLOCKER 判定

```text
必须改 listener 才能接 Task？     NO
必须改 Trigger？                 NO
必须改 Topic decision schema？   NO
必须改 Topic Prompt？            NO
必须改 bot_runtime / InboundMessage / Self / Dedupe / Outbound？  NO
```

**不生成 `P4-G2-BLOCKER-REPORT.md`。**  
允许进入 Gate 1。

---

## 推荐挂钩（本轮实施，尚未改代码）

```text
TopicSidepathWorker
    ↓
TopicEngine.process_inbound
    ↓
Topic success ∈ {NEW_TOPIC, EXISTING_TOPIC, TOPIC_UPDATE} 且 topic_id != null
    ↓
TaskSidepath.try_enqueue  (put_nowait, maxsize=32)
    ↓
单 Task worker
    ↓
TaskEngine.process_record(conversation, topic, message)
```

禁止触发 Task：

```text
UNRELATED / SKIPPED / FAILED / DISABLED / CONVERSATION_NOT_RESOLVED / 无 topic_id
```

双开关：

```text
TOPIC_ENGINE_ENABLED  控制 Topic 入队（已有）
TASK_ENGINE_ENABLED   控制 Task 入队（本轮新增 runtime_control 覆盖，模块默认 false）
```

Task 源码不得出现 `send_reply(` / `wx.SendMsg(` / `SendMsg(`。
