# P5-G2 Gate 0：当前真实源码审计

> 日期：2026-09-22  
> 性质：**READ ONLY**。本文件写完前未修改业务代码。  
> 依据：`P5-G1-IMPLEMENTATION-REPORT.md`、`P5-G1-TEST-REPORT.md`、`P5-G1-REGRESSION-REPORT.md`、`P5-G2-READINESS.md`、`P5-G1-DEFERRED-ISSUES.md`、`P4-G2-G0-CURRENT-STATE-AUDIT.md` 与真实源码。

```text
P0 STATUS          = CLOSED
P1 STATUS          = CLOSED
P2 STATUS          = CLOSED
P3 Topic Engine    = COMPLETE
P4 Task Engine     = COMPLETE
P5-G0 / G1         = COMPLETE
P5-G2              = NOT STARTED
```

---

## 冻结基线核对

| 项 | 文档 | 本轮核对 |
|---|---|---|
| P0 | CLOSED | 保持。禁止改 identity / dedupe / outbound / trigger / `evaluate_inbound` |
| P1 / P2 | CLOSED | 保持。禁止改 Chat Prompt 正文 |
| P3-G2 | COMPLETE | `topic_sidepath.py` 已在 `listener` 的 `evaluate_inbound` 之后挂钩 |
| P4-G2 | COMPLETE | Topic 成功后 `_maybe_enqueue_task` → 独立 Task Queue |
| P5-G1 | COMPLETE，Decision Offline 57 OK | `decision_store.py` / `decision_engine.py` / `decision_extractor_client.py` / `DECISION_EXTRACTOR.md` 存在 |
| G1 回归 | P4 50 / P3 39 / P0 59 / P1-P2 103 | 文档记录；Gate 1 后再实测 |
| G2 就绪 | `P5-G2-READINESS.md` = YES（离线） | 与源码一致：Decision Engine 离线可用，**生产未挂钩** |
| 延期 D1 | Topic 成功后独立 enqueue Decision | 正是本轮范围；禁止改 Trigger / Topic decision / Task / Chat Prompt / listener |

G1 文档与真实源码 **没有严重不一致**。不构成 BLOCKER。

```text
G2 Gate 0 = PASS
允许进入 Gate 1（只挂 Decision Side-path，Heuristic / Mock，不接真实 LLM，不接真机）
不必修改 listener.py / trigger.py / bot_runtime.py / InboundMessage
不必修改 Topic / Task decision schema
```

---

## 1. Topic 成功后当前在哪里 enqueue Task？

`topic_sidepath.py` 单 worker `_loop` → `_process(payload)`：

```text
result = engine.process_inbound(inbound, conversations=[conversation] + list(self.conversations))
self.last_result = result
...
TOPIC_PROCESS_SUCCESS
self._maybe_enqueue_task(payload, result)
```

`_maybe_enqueue_task` 调用：

```text
try_enqueue_task_after_topic(
    result,
    conversation=payload.get("conversation"),
    topic_store=self.store,
    runtime=self._hooked_runtime,
    sidepath=self.task_sidepath,
)
```

失败隔离：外层 `try/except`，不得回滚 Topic。  
当前成功路径 **没有** Decision 调用。

---

## 2. 是否能在同一位置独立 enqueue Decision？

**能。** 推荐在 `_maybe_enqueue_task` 之后（或并列）增加 `_maybe_enqueue_decision`，各自独立 `try/except`：

```text
Topic success
    ├→ try_enqueue_task_after_topic
    └→ try_enqueue_decision_after_topic
```

Task 的 SUCCESS / FAILED / DISABLED / QUEUE_FULL 发生在 **独立 Task worker** 内，Topic worker 只 `put_nowait`，**看不到** Task 结果，因此也无法用 Task 结果去闸门 Decision。

不必改 listener。不必把 Decision 挂在 Task success 之后。

---

## 3. Topic `EngineResult` 是否已包含 conversation_id / topic_id / message_id / decision？

**是。** `topic_engine.EngineResult` 已有：

| 字段 | 含义 |
|---|---|
| `decision` | `NEW_TOPIC` / `EXISTING_TOPIC` / `TOPIC_UPDATE` / `UNRELATED` / `SKIPPED` / `FAILED` / `DISABLED` |
| `topic_id` | 成功归属时为 `topic_*`；UNRELATED / SKIPPED / FAILED 多为 `None` |
| `message_id` | Topic Store 中的 MessageRecord id |
| `conversation_id` | `conv_*` |
| `error` / `error_code` | 失败隔离码 |
| `as_dict()` | 已公开上述字段 |

不需要改 Topic Engine decision schema。

---

## 4. 是否能通过 TopicStore 公开接口获得 Topic / MessageRecord？

**能。** 返回值只有 id，没有完整对象。TopicStore **已有** 公开只读接口，不必解冻 `topic_store.py`：

```text
TopicStore.get_topic(conversation_id, topic_id) -> Optional[dict]
TopicStore.get_message(conversation_id, message_id) -> Optional[dict]
```

Decision Engine 入口需要：

```text
conversation  ← Topic worker payload（已 resolve_topic_conversation）
topic         ← store.get_topic(result.conversation_id, result.topic_id)
message       ← store.get_message(result.conversation_id, result.message_id)
```

与 P4 Task Side-path 取数方式相同。

---

## 5. DecisionEngine 真实入口是否仍为 `process_record(conversation, topic, message)`？

**是。** `DecisionEngine.process_record(conversation: dict, topic: dict, message: dict) -> EngineResult`

离线已验证。内部会：

1. `store.require_topic(cid, topic_id)` — Topic 必须已存在  
2. `topic_store.get_message` — MessageRecord 必须已存在  
3. `message_belongs_to_topic` — 当前消息必须已有 Topic Evidence  
4. 失败全部 `isolated=True`，写 Decision FAILED Processing，**不改 Topic / Task**

没有 `process_inbound`。没有 listener 挂钩。模块常量 `DECISION_ENGINE_ENABLED = False`。

Decision **不得自己猜 Topic**。

---

## 6. 是否需要 Decision 独立 Queue？

**需要。** 理由与 P4 Task 相同：

- Topic worker **concurrency=1**，`queue.Queue(maxsize=32)`，`put_nowait`。  
- `_process` **同步** 等待 Topic Extractor。  
- 若再同步调用 Decision LLM（默认 timeout 20s），Topic 队列会积压，Stop shutdown 变慢。  
- **禁止复用 Task queue**：Task 积压不得拖死 Decision，反之亦然。

推荐：新增 `decision_sidepath.py`，`Queue(maxsize=32)` + 单 worker + `put_nowait`。  
Topic 成功后 **快速 enqueue**，Topic worker 立即继续。  
Queue 满：`DECISION_QUEUE_FULL`，丢弃本次 Decision 分析，不影响 Topic / Task / Chat。

禁止：每个 Decision 新开线程、无限 Queue、同步等 Decision LLM、复用 Task / SendQueue。

---

## 7. 同步调用 Decision LLM 是否会拖慢 Topic worker？

**会。** Decision Extractor timeout 上限约 20s。同步等待会让：

```text
Topic queue 积压
Decision timeout 反向拖慢 Topic
Stop shutdown 变慢
listener 虽不等待 Topic，但 Topic 自身被拉长
```

因此 G1 架构必须是：

```text
Topic 成功 → 快速 enqueue Decision → Topic worker 继续
Decision Engine 单独 worker 执行
```

listener 只 `put_nowait` Topic，不等待 Topic / Task / Decision LLM。

---

## 8. 当前 Stop hook 如何停 Task Side-path？

已有模型（**不改 `bot_runtime.py`**）：

1. `TaskSidepath.attach_runtime` → `runtime.register_stop_hook(self.shutdown)` 与 `register_emergency_hook`  
2. 首次 Task enqueue 时 `attach_runtime`  
3. `shutdown`：`_stop.set()`，`get_nowait` 丢弃未处理 Task  
4. worker 取到任务后若 `_stop.is_set()` 或 `not runtime.is_accepting_work()` → 丢弃  
5. `TopicSidepath.shutdown` 在显式注入 `task_sidepath` 时一并 `task_sidepath.shutdown`

listener 在 `is_accepting_work()==False` 时 **不进入** `try_enqueue_topic_sidepath`。Stop 后不会有新 Topic，也就没有新 Decision 输入。Decision queue 仍须自己停止接收/消费，防止 Stop 前已入 Topic 队列、Stop 后才跑完 Topic 再投递 Decision。

---

## 9. Decision 能否复用同样 Stop 模型？

**能。**

```text
DecisionSidepath.attach_runtime → register_stop_hook / register_emergency_hook
shutdown：_stop.set() + 清空 queue
TopicSidepath.shutdown 在显式注入 decision_sidepath 时一并停 Decision
```

不要求强杀正在跑的 Decision LLM 线程；完成后不得把 Stop 之后的新消息写成 Decision。

---

## 10. 是否无需修改 listener / P0 / Trigger？

**是，无需修改。**

当前 `message/listener.py` 唯一旁路：

```text
verdict = runtime.evaluate_inbound(...)
try_enqueue_topic_sidepath(inbound, verdict, runtime=runtime)
if verdict.get("action") != REPLY:
    return
```

P5-G2 **不应**再增加第三条 Decision Side-path。  
Decision 挂在 Topic `_process` 成功之后即可取得 `conversation` + `EngineResult` + TopicStore 对象。

| 冻结层 | 本轮是否必须改 | 结论 |
|---|---|---|
| `message/listener.py` | 否 | 已正确挂钩 Topic |
| `message/trigger.py` | 否 | Decision 不决定是否回复 |
| `bot_runtime.py` | 否 | 复用现有 stop hook |
| `InboundMessage` | 否 | 不需要新字段 |
| Self / Dedupe / Outbound | 否 | Topic 入队资格已过滤 |
| Topic Engine / Topic Prompt / Chat Prompt | 否 | Decision 只消费成功 Topic |
| Task Engine / Task Side-path / Task Prompt | 否 | Decision 与 Task 平行，互不闸门 |

唯一计划解冻 / 新增：

```text
topic_sidepath.py      — 成功路径末尾 try_enqueue Decision（最小侵入，与 Task 并列）
decision_sidepath.py   — 新增
tests/test_decision_sidepath.py
tests/test_decision_live_adapter.py
```

---

## Gate 0 十问结论

| # | 问题 | 答案 |
|---|---|---|
| 1 | Topic 成功后哪里 enqueue Task？ | `_process` SUCCESS 末尾 `_maybe_enqueue_task` |
| 2 | 能否同一位置独立 enqueue Decision？ | **能** |
| 3 | EngineResult 是否含四字段？ | **是**（conversation_id / topic_id / message_id / decision） |
| 4 | Store 能否补全对象？ | **能**（`get_topic` / `get_message`） |
| 5 | Decision 入口？ | `process_record(conversation, topic, message)` |
| 6 | 要不要独立 Queue？ | **要**（禁止同步等 Decision LLM，禁止复用 Task queue） |
| 7 | 同步 Decision 会拖慢 Topic worker？ | **会，禁止** |
| 8 | Stop 如何停 Task Side-path？ | `register_stop_hook` + `shutdown` 丢队列 |
| 9 | Decision 能否复用 Stop 模型？ | **能** |
| 10 | 能否不改 listener / P0 / Trigger？ | **能** |

---

## 三开关独立性（源码已具备条件）

```text
TOPIC_ENGINE_ENABLED    控制 Topic 入队（已有）
TASK_ENGINE_ENABLED     控制 Task 入队（已有，不得闸门 Decision）
DECISION_ENGINE_ENABLED 控制 Decision 入队（本轮新增 runtime_control 覆盖，模块默认 false）
```

| Topic | Decision | 预期 |
|---|---|---|
| false | true | 无 Topic 输入 → Decision 不运行 |
| true | false | Topic 正常；Task 按自己开关；Decision 不运行 |
| true | true | Topic → Decision；Task 开关不影响 Decision |

---

## BLOCKER 判定

```text
必须改 listener 才能接 Decision？     NO
必须改 Trigger？                     NO
必须改 Topic decision schema？       NO
必须改 Task Engine / Task decision？ NO
必须让 Decision 依赖 Task SUCCESS？  NO
必须改 bot_runtime / InboundMessage / Self / Dedupe / Outbound？  NO
必须实现 Risk 才能完成 G2？          NO
```

**不生成 `P5-G2-BLOCKER-REPORT.md`。**  
允许进入 Gate 1。

---

## 推荐挂钩（本轮实施，尚未改代码）

```text
TopicSidepathWorker
    ↓
TopicEngine.process_inbound
    ↓
Topic success ∈ {NEW_TOPIC, EXISTING_TOPIC, TOPIC_UPDATE} 且 topic_id != null
    ├→ TaskSidepath.try_enqueue     (已有，put_nowait, maxsize=32)
    └→ DecisionSidepath.try_enqueue (本轮新增，put_nowait, maxsize=32)
            ↓
        单 Decision worker
            ↓
        DecisionEngine.process_record(conversation, topic, message)
```

禁止触发 Decision：

```text
UNRELATED / SKIPPED / FAILED / DISABLED / CONVERSATION_NOT_RESOLVED / 无 topic_id
```

Decision 源码不得出现 `send_reply(` / `wx.SendMsg(` / `SendMsg(` / `from message.listener`。
