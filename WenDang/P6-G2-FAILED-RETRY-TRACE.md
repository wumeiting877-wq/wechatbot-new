# P6-G2 FAILED Retry Trace

> 日期：2026-09-22  
> 证明：三个 Engine 在 **不改代码** 的前提下，FAILED 后再 `process_record` 可以 SUCCESS。

---

## 探针命令

```text
.\.venv\Scripts\python.exe -m unittest \
  tests.test_task_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed \
  tests.test_decision_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed \
  tests.test_risk_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed \
  tests.test_task_store.TaskStoreTests.test_processing_success_replay_skips_and_failed_can_retry \
  tests.test_decision_store.DecisionStoreTests.test_processing_success_replay_skips_and_failed_can_retry \
  tests.test_risk_store.RiskStoreTests.test_processing_success_replay_skips_and_failed_can_retry -v
```

```text
Ran 6 tests in 0.180s
OK
```

---

## Task

```text
1. Boom Extractor.process_record
   → decision=FAILED
   → processing.decision_summary=FAILED
   → has_successful_processing=false
   → tasks=[]  （apply 未执行）

2. HeuristicTaskExtractor.process_record（同 conversation/topic/message，version=1）
   → Extractor 再次调用
   → decision=NEW_TASK
   → write_processing 覆盖同一 key
   → open tasks = 1
   → evidence link 一次
```

既有断言：`test_failed_then_retry_can_succeed`。

---

## Decision

```text
FAILED（Boom）
→ process_record（Heuristic）
→ NEW_DECISION
→ recorded decisions = 1
```

---

## Risk

```text
FAILED（Boom）
→ process_record（Heuristic）
→ NEW_RISK
→ open risks = 1
```

---

## Store 覆盖

```text
write_processing(FAILED)
has_successful_processing == False

write_processing(UNRELATED 或 NEW_*)
同一 key 被替换
has_successful_processing == True

再 write_processing(任何值)
返回冻结的成功记录，不覆盖
```

---

## P6-G2 封装后的独立 retry 轨迹（RETRY-01）

场景：Topic processing=NEW_TOPIC；Decision/Risk 已 SUCCESS；Task=FAILED。

```text
retry_downstream(engine=task, conversation_id, message_id, topic_id)

→ INVALID_ENGINE? no
→ engine.enabled? true
→ get_processing → FAILED
→ runtime accepting? true
→ eligibility FAILED? true
→ audit DOWNSTREAM_RETRY_REQUESTED
→ TaskEngine.process_record  一次
→ Task Extractor +1
→ Decision Extractor +0
→ Risk Extractor +0
→ Topic Extractor +0
→ Chat +0
→ processing 覆盖为 NEW_TASK
→ audit DOWNSTREAM_RETRY_SUCCESS

再次 retry
→ previous_status=NEW_TASK
→ REJECTED NOT_RETRYABLE
→ Extractor +0
```

RETRY-02 / RETRY-03 对称。

---

## FAILED → retry FAILED（RETRY-04）

```text
audit REQUESTED × 1
audit FAILED × 1
无 REQUESTED 第二次
无 while / 递归
Task Extractor 仅 +1（这一次显式请求）
Decision / Risk / Topic / Chat 不变
```

---

## 结论

```text
Engine 天然支持 FAILED retry
Store 天然覆盖
P6-G2 只是显式、可审计、一次一发的入口
不重跑 Topic
不 fan-out 另外两路
```
