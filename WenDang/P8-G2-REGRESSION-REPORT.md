# P8-G2 Regression Report

> 日期：2026-09-23

P8-G2 定向 25 条通过。原有非 live 用例没有新增失败。

---

## 1. 定向

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g2_query_intent
Ran 25 tests in 0.446s
OK
```

同一次还跑过 `tests.test_p8g1_collaboration_query`，42 条 OK。P8-G1 的规则句、范围、停止、会话锁、旁路切断仍然成立。

## 2. Non-Live

按 `discover -s tests` 加载，排除四个 `Real*ExtractorTests`：

```text
kept 690
skipped_live 42
Ran 690 tests in 44.547s
OK
failures 0
errors 0
```

进入本 Gate 前的非 live 基线是 665 OK。690 = 665 + 本 Gate 25 条。旧 665 条没有新增失败。

## 3. Live Extractor

本 Gate 没有执行四个 `Real*ExtractorTests`（共 42 条），也没有修改 Topic / Task / Decision / Risk Real Extractor。

P8-G1 记录的 10 条 `Connection error` / `EXTRACTOR_TIMEOUT` 继续有效：

```text
KNOWN LIVE DEPENDENCY FAILURE
```

不归因到 P8-G2。

## 4. 开关

回归结束后：

```text
TOPIC_ENGINE_ENABLED     = false    is_topic_engine_enabled()     = false
TASK_ENGINE_ENABLED      = false    is_task_engine_enabled()      = false
DECISION_ENGINE_ENABLED  = false    is_decision_engine_enabled()  = false
RISK_ENGINE_ENABLED      = false    is_risk_engine_enabled()      = false
```
