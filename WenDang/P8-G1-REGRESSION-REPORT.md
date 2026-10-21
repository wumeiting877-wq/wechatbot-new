# P8-G1 Regression Report

> 日期：2026-09-23

P8-G1 定向 42 条通过。不含真实模型的回归通过。没有新的非 live 失败。

---

## 1. 定向

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g1_collaboration_query
Ran 42 tests in 0.687s
OK
```

同时复跑并通过：

```text
tests.test_topic_sidepath
tests.test_task_sidepath
tests.test_decision_sidepath
tests.test_risk_sidepath
```

listener 插入点仍满足旧断言：`try_enqueue_topic_sidepath` 出现在 `verdict.get("action") != REPLY` 之前。

## 2. Non-Live

按 `discover -s tests` 加载，排除四个 `Real*ExtractorTests`：

```text
kept 665
skipped_live 42
Ran 665 tests in 26.984s
OK
```

进入本 Gate 前的非 live 基线是 623 OK。665 = 623 + 本 Gate 42 条。P6-G1 至 P6-G6、P7-G0 至 P7-G2 都在这 665 条里，没有单独失败。

## 3. Live Extractor

本 Gate 没有执行四个 `Real*ExtractorTests`（共 42 条）。P8-G1 禁止为查询测试调用 Real Extractor。

P7-G2 记录的完整 discover 是 665 条里 10 条失败，失败点是 `Connection error` / `EXTRACTOR_TIMEOUT`：

```text
test_task_live_adapter.RealTaskExtractorTests
    test_t03_lina_no_due
    test_t04_two_tasks
    test_t05_update_not_new
    test_t07_fact_zero_task
    test_t08_suggestion_no_new_task
    test_t09_confirm_no_ownerless_new
    test_t10_completion_not_done
test_topic_live_adapter.RealTopicExtractorTests
    test_case_01_continuous_erp
    test_case_02_chitchat_unrelated
    test_case_03_erp_perm_erp_reuse
```

这些 expectation 没有修改。

```text
KNOWN LIVE DEPENDENCY FAILURE
```

不归因到 P8-G1。本 Gate 的非 live 回归没有新增失败。

## 4. 开关

回归结束后：

```text
TOPIC_ENGINE_ENABLED     = false    is_topic_engine_enabled()     = false
TASK_ENGINE_ENABLED      = false    is_task_engine_enabled()      = false
DECISION_ENGINE_ENABLED  = false    is_decision_engine_enabled()  = false
RISK_ENGINE_ENABLED      = false    is_risk_engine_enabled()      = false
```

没有改 `runtime_control`。旁路测试只用实例参数 `enabled=True`，tearDown 后全局开关仍是 false。
