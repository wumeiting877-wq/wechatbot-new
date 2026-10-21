# P9-G1 Regression Report

> 日期：2026-09-23

P8 查询与 Task 旧套件通过。Non-Live 旧 767 通过，加上本 Gate 17 条后为 784 OK。

## 1. P8 与 Task

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g1_collaboration_query tests.test_p8g2_query_intent tests.test_p8g3_query_delivery tests.test_p8g4_identity tests.test_p8g5_identity_model tests.test_p8g6_task_identity_link tests.test_task_store tests.test_task_engine_offline tests.test_task_sidepath
```

```text
Ran 196 tests in 11.107s
OK
failures 0
errors 0
```

这 9 个模块的条数与 P8-G6 回归时相同。Query、Identity、`TaskIdentityLink`、Task Store、Task Engine、Task Sidepath 没有新增失败。

## 2. Non-Live

`discover` 起点为 `tests`。排除四个类：

```text
RealTaskExtractorTests
RealTopicExtractorTests
RealDecisionExtractorTests
RealRiskExtractorTests
```

```text
Ran 784 tests in 53.132s
OK
failures 0
errors 0
```

```text
784 = 旧 767 + 本 Gate 17
767 old PASS
```

Real Extractor 仍是 42 条，未运行，未改 expectation。

## 3. Engine

```text
TOPIC_ENGINE_ENABLED=false
TASK_ENGINE_ENABLED=false
DECISION_ENGINE_ENABLED=false
RISK_ENGINE_ENABLED=false
```
