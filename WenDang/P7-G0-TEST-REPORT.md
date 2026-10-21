# P7-G0 Test Report

> 日期：2026-09-23

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p7g0_operations_read_model -v
Ran 15 tests
OK
```

| 用例 | 结果 |
| --- | --- |
| OPS-01 Topic SUCCESS，retryable=false | PASS |
| OPS-02 Topic FAILED，retry_type=TOPIC_RETRY | PASS |
| OPS-03 Task FAILED，retry_type=DOWNSTREAM_RETRY | PASS |
| OPS-04 Decision FAILED，retry_type=DOWNSTREAM_RETRY | PASS |
| OPS-05 Risk FAILED，retry_type=DOWNSTREAM_RETRY | PASS |
| OPS-06 无 processing → NOT_FOUND_UNKNOWN，retryable=false，需人工检查；实体和 audit 不升级 SUCCESS | PASS |
| OPS-07 UNRELATED → SUCCESS / 已处理 | PASS |
| OPS-08 SKIPPED → SUCCESS | PASS |
| OPS-09 四 Engine 独立，不互相覆盖 | PASS |
| OPS-10 只有 FAILED / UNKNOWN 才 attention；issues 按时间倒序并标明 source_timestamp | PASS |
| OPS-11 Engine disabled 只影响 engine_enabled，不伪造 FAILED | PASS |
| OPS-12 STOPPED 仍能读，processing 内容不变 | PASS |
| OPS-13 operations_read_model.py 不含写 Store / retry / send_reply | PASS |
| OPS-14 NOT_FOUND 契约仍是不可重试 | PASS |
| 只读 API、404、POST 405、页面无 retry 入口 | PASS |
