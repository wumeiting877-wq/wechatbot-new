# P6-G5 Topic FAILED Retry Trace

> 日期：2026-09-22  
> 证明：Topic Engine 在 **不改 Engine / Store schema** 的前提下，FAILED 后再 `process_record` 可以 SUCCESS，且首次 FAILED 的 fan-out 为 0。

---

## 探针命令

```text
.\.venv\Scripts\python.exe -m unittest \
  tests._p6g5_probe_topic_failed_retry \
  tests.test_topic_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed \
  tests.test_topic_store.TopicStoreTests.test_processing_success_replay_skips_and_failed_can_retry -v
```

```text
Ran 5 tests in 0.179s
OK
```

---

## NEW_TOPIC

```text
1. Boom Extractor.process_record
   → decision=FAILED
   → replayed=false
   → has_successful_processing=false
   → topics=[]
   → Topic Extractor = 1

2. HeuristicTopicExtractor.process_record（同 MessageRecord，version=1）
   → Extractor +1
   → replayed=false
   → decision=NEW_TOPIC
   → write_processing 覆盖同一 key FAILED → NEW_TOPIC
   → has_successful_processing=true

3. 第三次 process_record
   → replayed=true
   → Extractor delta = 0
```

---

## EXISTING_TOPIC / TOPIC_UPDATE

先成功 seed 一条 NEW_TOPIC，再对第二条 MessageRecord：

```text
Boom → FAILED, has_successful_processing=false
Heuristic → EXISTING_TOPIC / TOPIC_UPDATE
replayed=false
Extractor +1（相对 FAILED 那一次）
```

EXISTING_TOPIC 不是 Topic replay。

---

## Sidepath FAILED fan-out

```text
TopicSidepath._process + Boom Extractor
→ last_result.decision=FAILED
→ Task/Decision/Risk enqueued_count = 0/0/0
```

这是正确行为。本 Gate 补的是：显式 retry 成功后如何走回同一套 fan-out。

---

## 结论

Topic Store / Engine **天然支持** FAILED → SUCCESS。  
不需要新 processing version，不需要新 schema，不需要新 Queue。
