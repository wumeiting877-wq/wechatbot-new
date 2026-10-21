# P5-G2 自动测试报告（Gate 1）

> 日期：2026-09-22  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> Extractor：`HeuristicDecisionExtractor`（Gate 1 不允许第一步同时接真实 LLM + 真机）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_decision_sidepath -v
```

结果：**15 tests, OK**（约 1.4s，含隔离断言）

另含隔离断言：listener 无第三条 Decision Side-path；Decision 四模块无微信发送调用。

---

## DS1～DS11

| CASE | 内容 | 结果 | 观察 |
|---|---|---|---|
| **DS1** | NEW_TOPIC + topic_id | **PASS** | Topic enqueue 后 Decision `enqueued_count=1` |
| **DS2** | EXISTING_TOPIC | **PASS** | 第二次 ERP 消息 decision=`EXISTING_TOPIC`，Decision enqueue +1 |
| **DS3** | TOPIC_UPDATE | **PASS** | 「规则/修复」→ `TOPIC_UPDATE`，Decision enqueue +1 |
| **DS4** | UNRELATED | **PASS** | 「中午吃什么」Topic 仍处理；Decision enqueue=0，`TOPIC_NOT_ELIGIBLE` |
| **DS5** | FAILED | **PASS** | Topic Extractor timeout → Topic `FAILED`；Decision enqueue=0 |
| **DS6** | SKIPPED | **PASS** | 空内容 → Topic `SKIPPED`；Decision enqueue=0 |
| **DS7** | DECISION_ENGINE_ENABLED=false | **PASS** | Topic 仍写入；Task 仍 enqueue；Decision enqueue=0，`DECISION_ENGINE_DISABLED` |
| **DS8** | Task FAILED 不阻塞 Decision | **PASS** | Topic SUCCESS；Task Processing=`FAILED`；Decision 仍 enqueue 并写入 |
| **DS9** | Decision worker exception | **PASS** | Topic / Task 仍在；Decision Processing=`FAILED`；无脏 Decision |
| **DS10** | Decision Queue Full | **PASS** | Topic `wait_idle` < 1.5s；出现 `DECISION_QUEUE_FULL`；Topic 不阻塞 |
| **DS11** | Stop Bot | **PASS** | `begin_graceful_stop` 后无新 Topic / 无新 Task / 无新 Decision / 无 Chat |

额外：

| 项 | 结果 |
|---|---|
| listener 只有 `try_enqueue_topic_sidepath` | **PASS** |
| `topic_result_allows_decision` 拒绝 UNRELATED/SKIPPED/FAILED/DISABLED/无 topic_id | **PASS** |
| `try_enqueue_decision_after_topic(None)` 不抛 | **PASS** |
| Decision 模块无 `send_reply(` / `SendMsg(` | **PASS** |
| Decision skip 码与 Task skip 码独立 | **PASS** |

Adapter 隔离 / 失败注入（不接真实 LLM）：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_decision_live_adapter.DecisionExtractorIsolationTests tests.test_decision_live_adapter.DecisionFailurePreservesTopicAndTaskTests -v
```

结果：**11 tests, OK**

覆盖：timeout / HTTP error / invalid JSON / empty output / invalid supersedes_decision_id / invalid evidence。  
Decision FAILED；Topic 快照不变；Task Store 仍空；无脏 Decision。

---

## Gate 1 PASS 条件

```text
DS1～DS11 PASS
P5 Decision Offline 57 PASS
P4 / P3 / P0 / P1-P2 回归 PASS
```

允许进入 Gate 2 真实 Decision LLM。未在本门同时做真机。
