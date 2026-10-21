# P9-G3 Regression Report

> 日期：2026-09-23

P9-G1 生命周期 17 条通过。P9-G2 目标解析 25 条通过。P8 查询与 Task 旧套件通过。Non-Live 旧 809 通过，加上本 Gate 32 条后为 841 OK。

## 1. P9-G3

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p9g3_business_action
```

```text
Ran 32 tests in 0.575s
OK
failures 0
errors 0
```

## 2. P9-G1

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p9g1_task_lifecycle
```

```text
Ran 17 tests in 0.239s
OK
failures 0
errors 0
```

## 3. P9-G2

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p9g2_task_target
```

```text
Ran 25 tests in 0.108s
OK
failures 0
errors 0
```

## 4. P8 与 Task

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g1_collaboration_query tests.test_p8g2_query_intent tests.test_p8g3_query_delivery tests.test_p8g4_identity tests.test_p8g5_identity_model tests.test_p8g6_task_identity_link tests.test_task_store tests.test_task_engine_offline tests.test_task_sidepath
```

```text
Ran 196 tests in 7.061s
OK
failures 0
errors 0
```

这 9 个模块的条数与 P9-G2 回归时相同。

## 5. Non-Live

`discover` 起点为 `tests`。排除四个类：

```text
RealTaskExtractorTests
RealTopicExtractorTests
RealDecisionExtractorTests
RealRiskExtractorTests
```

```text
kept 841
skipped_live 42
Ran 841 tests in 51.678s
OK
failures 0
errors 0
```

```text
841 = 旧 809 + 本 Gate 32
809 old PASS
```

Real Extractor 仍是 42 条，未运行，未改 expectation。

## 6. Engine

```text
TOPIC_ENGINE_ENABLED=false
TASK_ENGINE_ENABLED=false
DECISION_ENGINE_ENABLED=false
RISK_ENGINE_ENABLED=false
```
