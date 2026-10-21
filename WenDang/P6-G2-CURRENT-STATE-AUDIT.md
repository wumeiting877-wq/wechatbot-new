# P6-G2 Current State Audit

> 日期：2026-09-22  
> 在 Gate 0 只读审计之后，纳入 Gate 1 探针与实现边界。

Gate 0 全文见：`P6-G2-G0-CURRENT-STATE-AUDIT.md`。

---

## 冻结基线（进入本 Gate 时）

```text
P0..P2 = CLOSED
P3 Topic / P4 Task / P5 Decision / P5 Risk = COMPLETE
P6-G0 = COMPLETE
P6-G1 = COMPLETE
unittest discover = 540 OK

TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

---

## 七问结论（不变）

1. FAILED **不阻止**下一次 `process_record`。
2. successful processing **会** replay skip。
3. 同 `message_id|version` **允许** FAILED 后重写。
4. 第二次成功 **覆盖** 同一 processing key。
5. **覆盖，不追加。**
6. Extractor 失败路径 **不会**先写 evidence；成功后再写一次。
7. Store **天然支持 retry**。Engine 不改。

---

## Gate 1 探针

已复跑既有离线测试（未改 Engine）：

```text
tests.test_task_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed     OK
tests.test_decision_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed OK
tests.test_risk_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed     OK
tests.test_task_store.TaskStoreTests.test_processing_success_replay_skips_and_failed_can_retry      OK
tests.test_decision_store.DecisionStoreTests.test_processing_success_replay_skips_and_failed_can_retry OK
tests.test_risk_store.RiskStoreTests.test_processing_success_replay_skips_and_failed_can_retry      OK
```

语义：

```text
Task     FAILED → process_record → NEW_TASK
Decision FAILED → process_record → NEW_DECISION
Risk     FAILED → process_record → NEW_RISK
```

Extractor 会重新调用。实体只在成功那次生成。

---

## 本阶段实现边界

| 做 | 不做 |
|---|---|
| `downstream_retry.py` 同步薄封装 | 改 Task/Decision/Risk/Topic Engine |
| eligibility + Runtime/enabled 闸门 | Retry Queue / worker / cron / backoff |
| audit 四事件 | WebUI / API / 微信命令 |
| RETRY-01..12 | 自动定时 retry |
| | schema / retry_count |

---

## 开关与 Runtime（实现采用）

```text
engine.enabled == False  → ENGINE_DISABLED
runtime.is_accepting_work() == False → STOPPED
runtime is None → 允许（离线内部调用；不绑全局 STOPPED 单例）
```

模块常量保持 false。
