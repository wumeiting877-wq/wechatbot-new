# P8-G3 Regression Report

> 日期：2026-09-23

定向 22 条通过。原有非 live 用例没有新增失败。

---

## 1. 定向

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g3_query_delivery tests.test_p8g1_collaboration_query tests.test_p8g2_query_intent
Ran 89 tests in 2.096s
OK
```

```text
tests.test_p8g3_query_delivery        22 OK
tests.test_p8g1_collaboration_query   42 OK
tests.test_p8g2_query_intent          25 OK
```

P8-G1 的规则句、范围、停止、会话锁、旁路切断仍然成立。P8-G2 的 classifier 仍在锁之前，忙时不再把已识别的 Query 丢掉。

## 2. Non-Live

按 `discover -s tests` 加载，排除四个 `Real*ExtractorTests`：

```text
kept 712
skipped_live 42
Ran 712 tests in 47.491s
OK
failures 0
errors 0
```

进入本 Gate 前的非 live 基线是 690 OK。712 = 690 + 本 Gate 22 条。旧 690 条没有新增失败。

## 3. Live Extractor

本 Gate 没有执行四个 `Real*ExtractorTests`（共 42 条），也没有修改 Topic / Task / Decision / Risk Real Extractor。

```text
KNOWN LIVE DEPENDENCY FAILURE
```

不归因到 P8-G3。

## 4. 开关

回归结束后：

```text
TOPIC_ENGINE_ENABLED     = false    is_topic_engine_enabled()     = false
TASK_ENGINE_ENABLED      = false    is_task_engine_enabled()      = false
DECISION_ENGINE_ENABLED  = false    is_decision_engine_enabled()  = false
RISK_ENGINE_ENABLED      = false    is_risk_engine_enabled()      = false
```
