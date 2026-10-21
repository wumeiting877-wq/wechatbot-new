# P5-G4 自动测试报告（Gate 1）

> 日期：2026-09-22  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> Extractor：`HeuristicRiskExtractor`（Gate 1 不允许第一步同时接真实 LLM + 真机）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_risk_sidepath -v
```

结果：**17 tests, OK**（约 1.6s，含隔离断言）

另含隔离断言：listener 无第四条 Risk Side-path；Risk 四模块无微信发送调用。

---

## RS1～RS13

| CASE | 内容 | 结果 | 观察 |
|---|---|---|---|
| **RS1** | NEW_TOPIC + topic_id | **PASS** | Topic enqueue 后 Risk `enqueued_count=1` |
| **RS2** | EXISTING_TOPIC | **PASS** | 第二次 ERP 消息 decision=`EXISTING_TOPIC`，Risk enqueue +1 |
| **RS3** | TOPIC_UPDATE | **PASS** | 「规则/修复」→ `TOPIC_UPDATE`，Risk enqueue +1 |
| **RS4** | UNRELATED | **PASS** | 「中午吃什么」Topic 仍处理；Risk enqueue=0，`TOPIC_NOT_ELIGIBLE` |
| **RS5** | FAILED | **PASS** | Topic Extractor timeout → Topic `FAILED`；Risk enqueue=0 |
| **RS6** | SKIPPED | **PASS** | 空内容 → Topic `SKIPPED`；Risk enqueue=0 |
| **RS7** | RISK_ENGINE_ENABLED=false | **PASS** | Topic 仍写入；Task / Decision 仍 enqueue；Risk enqueue=0，`RISK_ENGINE_DISABLED` |
| **RS8** | Task FAILED 不阻塞 Risk | **PASS** | Topic SUCCESS；Task Processing=`FAILED`；Risk 仍 enqueue 并写入 OPEN Risk |
| **RS9** | Decision FAILED 不阻塞 Risk | **PASS** | Topic SUCCESS；Decision Processing=`FAILED`；Risk 仍 enqueue 并写入 |
| **RS10** | TaskStore unavailable | **PASS** | `candidate_tasks_error=RuntimeError`；Risk SUCCESS；`task_id=""` |
| **RS11** | Risk Queue Full | **PASS** | Topic `wait_idle` < 1.5s；出现 `RISK_QUEUE_FULL`；Topic 不阻塞 |
| **RS12** | Risk worker exception | **PASS** | Topic / Task / Decision 仍在；Risk Processing=`FAILED`；无脏 Risk |
| **RS13** | Stop Bot | **PASS** | `begin_graceful_stop` 后无新 Topic / Task / Decision / Risk / Chat |

额外：

| 项 | 结果 |
|---|---|
| listener 只有 `try_enqueue_topic_sidepath` | **PASS** |
| `topic_result_allows_risk` 拒绝 UNRELATED/SKIPPED/FAILED/DISABLED/无 topic_id | **PASS** |
| `try_enqueue_risk_after_topic(None)` 不抛 | **PASS** |
| Risk 模块无 `send_reply(` / `SendMsg(` | **PASS** |
| Risk skip 码与 Task / Decision skip 码独立 | **PASS** |

Adapter 隔离 / 失败注入（不接真实 LLM）：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_risk_live_adapter.RiskExtractorIsolationTests tests.test_risk_live_adapter.RiskFailurePreservesTopicTaskDecisionTests -v
```

结果：**11 tests, OK**

覆盖：timeout / HTTP error / invalid JSON / empty output / invalid risk_id / invalid evidence。  
Risk FAILED；Topic / Task / Decision 快照不变；无脏 Risk。

冻结 Side-path 回归（Gate 1 内）：

| 套件 | 结果 |
|---|---|
| `tests.test_topic_sidepath` | **OK** |
| `tests.test_task_sidepath` | **OK** |
| `tests.test_decision_sidepath` | **OK** |

---

## Gate 1 PASS 条件

```text
RS1～RS13 PASS
Risk Adapter Isolation PASS
Topic / Task / Decision Side-path 未回归失败
```

允许进入 Gate 2 真实 Risk LLM。未在本门同时做真机。
