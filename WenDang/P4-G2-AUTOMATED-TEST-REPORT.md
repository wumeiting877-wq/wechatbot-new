# P4-G2 自动测试报告（Gate 1）

> 日期：2026-09-21  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> Extractor：`HeuristicTaskExtractor`（Gate 1 不允许第一步同时接真实 LLM + 真机）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_task_sidepath -v
```

结果：**13 tests, OK**（约 0.7s）

另含隔离断言：listener 无第二条 Task Side-path；Task 四模块无微信发送调用。

---

## TS1～TS10

| CASE | 内容 | 结果 | 观察 |
|---|---|---|---|
| **TS1** | NEW_TOPIC + topic_id | **PASS** | Topic enqueue 后 Task `enqueued_count=1` |
| **TS2** | EXISTING_TOPIC | **PASS** | 第二次 ERP 消息 decision=`EXISTING_TOPIC`，Task enqueue +1 |
| **TS3** | TOPIC_UPDATE | **PASS** | 「规则/修复」→ `TOPIC_UPDATE`，Task enqueue +1 |
| **TS4** | UNRELATED | **PASS** | 「中午吃什么」Topic 仍处理；Task enqueue=0，`TOPIC_NOT_ELIGIBLE` |
| **TS5** | FAILED | **PASS** | Topic Extractor timeout → Topic `FAILED`；Task enqueue=0 |
| **TS6** | SKIPPED | **PASS** | 空内容 → Topic `SKIPPED`；Task enqueue=0 |
| **TS7** | TASK_ENGINE_ENABLED=false | **PASS** | Topic 仍写入 Store；Task enqueue=0，`TASK_ENGINE_DISABLED` |
| **TS8** | Task worker exception | **PASS** | Topic / Link 仍在；Task Processing=`FAILED`；无脏 Task |
| **TS9** | Task Queue Full | **PASS** | Topic `wait_idle` < 1.5s；出现 `TASK_QUEUE_FULL`；Topic 不阻塞 |
| **TS10** | Stop Bot | **PASS** | `begin_graceful_stop` 后无新 Topic / 无新 Task / 无 Chat |

额外：

| 项 | 结果 |
|---|---|
| listener 只有 `try_enqueue_topic_sidepath` | **PASS** |
| `topic_result_allows_task` 拒绝 UNRELATED/SKIPPED/FAILED/DISABLED/无 topic_id | **PASS** |
| `try_enqueue_task_after_topic(None)` 不抛 | **PASS** |
| Task 模块无 `send_reply(` / `SendMsg(` | **PASS** |

---

## Gate 1 PASS 条件

```text
TS1～TS10 PASS
Topic sidepath 回归 PASS（CASE-S1～S10 仍 OK）
P0 / P1 / P2 回归见 P4-G2-REGRESSION-REPORT.md
```

允许进入 Gate 2 真实 Task LLM。未在本门同时做真机。
