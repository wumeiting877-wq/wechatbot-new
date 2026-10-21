# P7-G1 Regression Report

> 日期：2026-09-23

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests
Ran 648 tests in 156.208s
OK
```

628 条原有测试保持通过，加上 20 条 P7-G1 测试。没有删除、跳过或改写旧断言。

包含并仍通过：

```text
tests.test_p6g6_missing_processing
tests.test_p6g5_topic_retry
tests.test_p6g2_downstream_retry
tests.test_p6g3_apply_finalize_consistency
tests.test_p6g4_collision_evidence
tests.test_p7g0_operations_read_model
tests.test_bot_lifecycle
```

`operations_routes.py` 仍然没有 POST。P7-G0 页面测试仍然要求不出现 `retry_topic` / `retry_downstream` 这两个标识，新页面没有写这两个名字。

回归结束后：

```text
TOPIC_ENGINE_ENABLED    模块常量 false，is_topic_engine_enabled() false
TASK_ENGINE_ENABLED     模块常量 false，is_task_engine_enabled() false
DECISION_ENGINE_ENABLED 模块常量 false，is_decision_engine_enabled() false
RISK_ENGINE_ENABLED     模块常量 false，is_risk_engine_enabled() false
```
