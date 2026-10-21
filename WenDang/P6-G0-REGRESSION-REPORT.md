# P6-G0 回归报告

> 日期：2026-09-22  
> 解释器：项目 `.venv\Scripts\python.exe`（系统 Python 无 flask，不能代表冻结回归）  
> Real LLM / 真机：**未跑**（RCA 离线已定位，本阶段原则不接真实 LLM）

```text
Ran 334 tests in 15.376s
OK
```

---

## 套件

| 包 | 模块 | 结果 |
|---|---|---|
| P0 | `tests.test_p0_message_runtime` `tests.test_runtime_admit` | PASS |
| P1/P2 | `tests.test_p1_p2_audit` | PASS |
| P3 Topic Offline | `tests.test_topic_engine_offline` `tests.test_topic_store` | PASS |
| Topic Side-path | `tests.test_topic_sidepath` | PASS |
| Topic Adapter Isolation | `tests.test_topic_live_adapter.ExtractorIsolationTests` `tests.test_extractor_prompt` | PASS |
| P4 Task Offline | `tests.test_task_engine_offline` `tests.test_task_store` | PASS |
| Task Side-path | `tests.test_task_sidepath` | PASS |
| Task Adapter Isolation | `tests.test_task_live_adapter.TaskExtractorIsolationTests` `tests.test_task_extractor` | PASS |
| P5 Decision Offline | `tests.test_decision_engine_offline` `tests.test_decision_store` | PASS |
| Decision Side-path | `tests.test_decision_sidepath` | PASS |
| Decision Adapter Isolation | `tests.test_decision_live_adapter.DecisionExtractorIsolationTests` `tests.test_decision_extractor` | PASS |
| P5 Risk Offline | `tests.test_risk_engine_offline` `tests.test_risk_store` | PASS |
| Risk Side-path | `tests.test_risk_sidepath` | PASS |
| Risk Adapter Isolation | `tests.test_risk_live_adapter.RiskExtractorIsolationTests` `tests.test_risk_extractor` | PASS |
| WebUI process helper | `tests.test_webui_bot_process` | PASS（venv） |

未包含：各 `Real*ExtractorTests`（需 Key；`skipUnless`）。

---

## 开关核验（测试后）

```text
runtime_control/TOPIC_ENGINE_ENABLED    = false
runtime_control/TASK_ENGINE_ENABLED     = false
runtime_control/DECISION_ENGINE_ENABLED = false
runtime_control/RISK_ENGINE_ENABLED     = false
模块常量四个 Engine                       = False
```

本轮回归 **没有** 把生产开关写成长期 true。

---

## 用系统 python 误跑的一次（作废）

`python`（WindowsApps 3.13）334 中有 flask 缺失导致 P1/P2 import error。  
**不以该次为准。** 冻结回归以 venv 334 OK 为准。
