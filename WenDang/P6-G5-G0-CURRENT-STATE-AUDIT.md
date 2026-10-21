# P6-G5 Gate 0 — READ ONLY 当前状态审计

> 日期：2026-09-22  
> 范围：`topic_engine.py` / `topic_store.py` / `topic_sidepath.py` / `downstream_retry.py` / `task_sidepath.py` / `decision_sidepath.py` / `risk_sidepath.py`  
> 本 Gate：**只读**。未改 Engine / Store schema / P6-G1 replay / P6-G2 downstream retry / P0 Dedupe。

---

## 扫描文件

```text
topic_engine.py
topic_store.py
topic_sidepath.py
downstream_retry.py
task_sidepath.py
decision_sidepath.py
risk_sidepath.py
```

---

## 1. Topic FAILED 是否允许同 version 再 process？

**允许。**

`TopicEngine._process_record()` 在 upsert MessageRecord 之后只问：

```text
store.has_successful_processing(cid, message_id)
```

`has_successful_processing()` 只认 `SUCCESS_DECISIONS`：

```text
NEW_TOPIC
EXISTING_TOPIC
TOPIC_UPDATE
UNRELATED
SKIPPED
```

`FAILED` 不在集合内。因此：

```text
processing = FAILED
→ has_successful_processing = false
→ 不会 replayed=true
→ 同 MessageRecord + 同 DEFAULT_PROCESSING_VERSION=1
→ 再次 process_record 会重新进入 Extractor
```

已有离线测试：`tests.test_topic_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed`。

---

## 2. FAILED 是否会覆盖同 processing key？

**会覆盖。**

`processing_key = message_id|version`，默认 version=1。

`TopicStore.write_processing()`：

```text
prev = records[key]
if prev 且 prev.decision ∈ SUCCESS_DECISIONS:
    return prev          # 成功冻结，拒绝覆盖
records[key] = item      # FAILED / 空 允许覆盖
```

`_isolate()` 写 `decision=FAILED` 后，下一次 `_finalize()` 成功决策会写回同一 key。

成功记录不会被 FAILED 或其它成功决策覆盖（P6-G1 冻结）。

已有 Store 测试：`test_topic_store.test_processing_success_replay_skips_and_failed_can_retry`。

---

## 3. retry SUCCESS 后 processing 如何变化？

**同一 key 从 FAILED 覆盖为本次成功 decision。**

例如 NEW_TOPIC：

```text
message_id|1 : { decision=FAILED, topic_id=None, error=... }
                ↓ process_record 成功
message_id|1 : { decision=NEW_TOPIC, topic_id=topic_*, error="" }
```

之后 `has_successful_processing=true`。再 `process_record` 会 `replayed=true`，不再调 Extractor。

不升 version，不追加第二条 processing，不改 schema。

---

## 4. retry SUCCESS 后怎样才能使用现有 fan-out 逻辑？

Topic Engine 本身 **不** fan-out。fan-out 只在 `TopicSidepath._process()`：

```text
engine.process_inbound(...)
if FAILED / error_code     → 0 fan-out
if replayed=true           → EVENT_TOPIC_REPLAY, fanout_skipped, 0 fan-out
else SUCCESS               → _maybe_enqueue_task
                            → _maybe_enqueue_decision
                            → _maybe_enqueue_risk
```

三路 enqueue 最终走：

```text
try_enqueue_task_after_topic      → topic_result_allows_task
try_enqueue_decision_after_topic  → topic_result_allows_decision
try_enqueue_risk_after_topic      → topic_result_allows_risk
```

允许 fan-out 的 Topic decision 只有：

```text
NEW_TOPIC / EXISTING_TOPIC / TOPIC_UPDATE
且带 topic_id
且无 error_code
```

`UNRELATED` / `SKIPPED` / `FAILED` 被 `FORBIDDEN_TOPIC_DECISIONS` 拒绝 → enqueue skip。

每路还会自己检查：

```text
enabled()            # TASK/DECISION/RISK_ENGINE_ENABLED
runtime.is_accepting_work()
```

因此：**只要 retry 成功后走回 TopicSidepath 这一段 post-process，就自动遵守下游开关，不必复制三套 allow 规则。**

当前缺口：没有同步入口对「已存在 MessageRecord」调用 `process_record` 再走这段 fan-out。worker 只吃 inbound queue payload。

---

## 5. 是否可以复用 TopicSidepath，而不复制 Task/Decision/Risk fan-out 规则？

**可以。优先方案。**

对 `TopicSidepath` 增加非常薄的同步入口（命名实现时决定），内部：

```text
engine.process_record(record, conversation)
↓
与 _process 相同的 FAILED / replayed 判断
↓
_maybe_enqueue_task / _maybe_enqueue_decision / _maybe_enqueue_risk
```

不要复制：

```text
topic_result_allows_task
topic_result_allows_decision
topic_result_allows_risk
```

若 `_process` 不能直接吃 retry identity，最小提取：

```text
_fanout_topic_result(...)   # 仅 SUCCESS 且 replayed=false 时调用
```

由正常 worker 与 Topic retry 共用。

`P6-G1`：`replayed=true` 的路径在 helper 之前 return，helper 根本不 fan-out。

---

## 6. 是否需要新 Queue？

**不需要。**

理由：

```text
Topic FAILED 后 MessageRecord 已在 Store
processing key 已存在
不需要 listener / inbound 再入队
显式 retry 第一版 = 同步内部 capability
下游仍走现有 Task / Decision / Risk Queue（不是第五条 Queue）
```

禁止：

```text
Topic Retry Queue
新 worker
新 scheduler
自动 retry / backoff
```

与 P6-G2 `downstream_retry.py` 同构：validate → gate → 一次 process → audit → return。

---

## Runtime / enabled 闸门（现况）

| 层 | 行为 |
|---|---|
| `TOPIC_ENGINE_ENABLED` | 模块常量 **false** |
| `TopicEngine.enabled` | 构造时 `enabled=None` 用模块常量；测试可 DI `True` |
| `TopicSidepath.enabled()` | override → runtime_control 文件 → env → 模块常量 |
| worker `_loop` | `not enabled()` 或 `runtime.is_accepting_work()==false` 则跳过 `_process` |
| `_engine()` | **若 engine 未注入，会 `TopicEngine(..., enabled=True)`** |

最后一点是显式 retry 必须避开的陷阱：

```text
不得在 TOPIC_ENGINE_ENABLED=false 时偷偷构造 enabled=True 的 Engine
retry 必须先问 sidepath.enabled() / 已注入 engine.enabled
测试可以依赖注入启用 Engine
```

Runtime：`is_accepting_work()` 仅 `RUNNING` / `DEGRADED`。`STOPPING` / `STOPPED` / `ERROR` / `STARTING` 为 false。与 P6-G2 一致，retry 应返回 `STOPPED`，不跑 Topic LLM。

---

## downstream_retry.py（冻结）

P6-G2 只服务 `task|decision|risk`。`engine="topic"` 会 `INVALID_ENGINE`。

这是正确边界：

```text
Topic SUCCESS + Task FAILED  → retry_downstream(task)
Topic FAILED                → 本 Gate 的 Topic retry
不得互相代替
```

本阶段 **不修改** `downstream_retry.py`。

---

## P6-G1 replay（冻结）

```text
processing ∈ SUCCESS_DECISIONS
→ process_record 立刻 replayed=true
→ TopicSidepath 不 fan-out
```

EXISTING_TOPIC / TOPIC_UPDATE 的**首次**成功 `replayed=false`，会 fan-out。不得把它们误判成 replay。

---

## P0 DUPLICATE / N2（冻结）

```text
同 platform_message_id → listener DUPLICATE → classify_topic_skip=DUPLICATE → 不入 Topic Queue
同正文 + 不同 platform_message_id → 两条 MessageRecord → 两次首次 Topic processing
```

本阶段不改 listener / Trigger / Dedupe。

---

## 六问结论

| # | 问题 | 答案 |
|---|---|---|
| 1 | Topic FAILED 是否允许同 version 再 process？ | **是** |
| 2 | FAILED 是否会覆盖同 processing key？ | **是**（成功记录除外） |
| 3 | retry SUCCESS 后 processing 如何变化？ | **同一 key 覆盖为成功 decision** |
| 4 | 怎样用现有 fan-out？ | **复用 TopicSidepath post-process / `_maybe_enqueue_*`** |
| 5 | 能否复用 TopicSidepath 而不复制 allow 规则？ | **能** |
| 6 | 是否需要新 Queue？ | **不需要** |

STOP 条件均未触发。允许进入 Gate 1 探针与最小 Topic Retry capability。
