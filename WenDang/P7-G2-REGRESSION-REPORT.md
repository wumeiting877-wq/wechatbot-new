# P7-G2 Regression Report

> 日期：2026-09-23

P7-G2 自己的 17 条测试通过。不含真实 LLM 的回归通过。此前一次含真实 Extractor 的完整 discover 有 10 条连接失败，失败点不在诊断代码。

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests
Ran 665 tests in 449.251s
FAILED (failures=10)
```

10 条都在真实 Extractor 的 live adapter，错误是 `Connection error.` 或 `EXTRACTOR_TIMEOUT`：

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

诊断套件、P7-G0、P7-G1、P6-G6 不在这 10 条里。没有删除、跳过或改写旧断言。

同日复核：按 `discover -s tests` 的模块路径加载，排除四个 `Real*ExtractorTests`（本 Gate 禁止运行 LLM / Engine），其余：

```text
Ran 623 tests in 38.696s
OK
```

623 = 不含真实 LLM 的旧测试 + 17 条 P7-G2。四个 Engine 常量与 `is_*_engine_enabled()` 仍为 false。

包含并仍通过：

```text
tests.test_p6g6_missing_processing
tests.test_p6g5_topic_retry
tests.test_p6g2_downstream_retry
tests.test_p6g3_apply_finalize_consistency
tests.test_p6g4_collision_evidence
tests.test_p7g0_operations_read_model
tests.test_p7g1_manual_retry
```

DIAG-14、DIAG-15 在新套件内部又各跑了一次 P7-G0 与 P6-G6。discover 计数仍是各文件一遍，加上这 17 条。

回归结束后：

```text
TOPIC_ENGINE_ENABLED    模块常量 false，is_topic_engine_enabled() false
TASK_ENGINE_ENABLED     模块常量 false，is_task_engine_enabled() false
DECISION_ENGINE_ENABLED 模块常量 false，is_decision_engine_enabled() false
RISK_ENGINE_ENABLED     模块常量 false，is_risk_engine_enabled() false
```

`operations_routes.py` 新增路由都是 GET。原有 POST 仍只在 `operations_action_routes.py`。
