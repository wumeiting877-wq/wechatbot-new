# P6-G5 Current State Audit

> 日期：2026-09-22  
> 在 Gate 0 只读审计之后，纳入 Gate 1 探针与实现边界。

Gate 0 全文见：`P6-G5-G0-CURRENT-STATE-AUDIT.md`。

---

## 冻结基线（进入本 Gate 时）

```text
P0..P2 = CLOSED
P3 Topic / P4 Task / P5 Decision / P5 Risk = COMPLETE
P6-G0 = COMPLETE
P6-G1 = COMPLETE
P6-G2 = COMPLETE
P6-G3 = COMPLETE
P6-G4 = COMPLETE
unittest discover = 579 OK

TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

---

## 六问结论（不变）

1. Topic FAILED **允许**同 `message_id|version` 再 `process_record`。
2. FAILED **会覆盖**同 processing key；成功记录冻结。
3. retry SUCCESS 后同一 key **覆盖**为 NEW_TOPIC / EXISTING_TOPIC / TOPIC_UPDATE / UNRELATED / SKIPPED。
4. fan-out 必须走回 `TopicSidepath` 的 `_maybe_enqueue_*`，不得复制三套 allow 规则。
5. **可以复用 TopicSidepath**。
6. **不需要新 Queue。**

---

## Gate 1 探针

```text
tests._p6g5_probe_topic_failed_retry
tests.test_topic_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed
tests.test_topic_store.TopicStoreTests.test_processing_success_replay_skips_and_failed_can_retry
```

```text
Ran 5 tests in 0.179s
OK
```

详见 `P6-G5-TOPIC-FAILED-RETRY-TRACE.md`。

---

## 实现边界

新增：

```text
topic_retry.py
TopicSidepath.process_record_and_fanout
TopicSidepath._apply_topic_engine_result
TopicSidepath._fanout_topic_result
```

未改：

```text
topic_engine.py topic_store.py
downstream_retry.py
task_store.py decision_store.py risk_store.py
listener Trigger Self P0 Dedupe
四个 EXTRACTOR decision schema
keep_alive Stop Start Bot process preflight
```

STOP 条件均未触发。
