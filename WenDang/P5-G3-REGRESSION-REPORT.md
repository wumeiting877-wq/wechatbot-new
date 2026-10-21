# P5-G3 回归报告

> 日期：2026-09-22  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 目的：确认 P5-G3 Risk Engine Offline **没有**改变 P0 / P1 / P2 / P3 / P4 / P5 Decision 冻结行为。

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
P3 Topic Engine = COMPLETE
P4 Task Engine  = COMPLETE
P5-G0 / G1 / G2 = COMPLETE
```

本轮未修改：Self / Dedupe / Outbound / Stop Bot / Trigger / Message Gateway / Chat Prompt 正文 / `evaluate_inbound` / listener / Topic Engine / Topic Extractor Prompt / Topic decision schema / Task Engine / Task Side-path / Task Extractor Prompt / Task decision schema / Decision Engine / Decision Side-path / Decision Extractor Prompt / Decision decision schema。

仅调整两处 G1/G2「Risk 文件尚不存在」的负向断言，改为「Decision 不调用 Risk / Side-path 未接」。Decision Offline 数量仍为 **57**。

---

## P5 Risk Offline（本轮新增）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_risk_store tests.test_risk_extractor tests.test_risk_engine_offline
```

结果：**68 tests, OK**

---

## P5 Decision Offline（G1 基线，必须保持 57）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_decision_store tests.test_decision_extractor tests.test_decision_engine_offline
```

结果：**57 tests, OK**（基线 57）

---

## P5 Decision Side-path / Adapter isolation

```text
.\.venv\Scripts\python.exe -m unittest tests.test_decision_sidepath
.\.venv\Scripts\python.exe -m unittest tests.test_decision_live_adapter.DecisionExtractorIsolationTests tests.test_decision_live_adapter.DecisionFailurePreservesTopicAndTaskTests
```

| 套件 | 结果 |
|---|---|
| Decision Side-path DS1～DS11 + 隔离 | **15 OK** |
| Extractor 隔离 + 失败注入 | **11 OK** |

未重跑 `RealDecisionExtractorTests`：本轮未改 `DECISION_EXTRACTOR.md` / `decision_extractor_client.py` / `decision_engine.py`。不重开 Decision G2 真机。

---

## P4 Task Offline

```text
.\.venv\Scripts\python.exe -m unittest tests.test_task_store tests.test_task_extractor tests.test_task_engine_offline
```

结果：**50 tests, OK**（基线 50）

---

## P4 Task Side-path / Adapter isolation

```text
.\.venv\Scripts\python.exe -m unittest tests.test_task_sidepath tests.test_task_live_adapter.TaskExtractorIsolationTests tests.test_task_live_adapter.TaskFailurePreservesTopicTests
```

结果：**25 tests, OK**（Side-path 13 + Adapter 隔离/失败 12）

未重跑 `RealTaskExtractorTests`：本轮未改 Task Extractor / Task Engine。

---

## P3 Topic Offline

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_store tests.test_extractor_prompt tests.test_topic_engine_offline
```

结果：**39 tests, OK**（基线 39）

---

## P3 Topic Side-path / Adapter isolation

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_sidepath
.\.venv\Scripts\python.exe -m unittest tests.test_topic_live_adapter.ExtractorIsolationTests
```

结果：**12 + 7 = 19 tests, OK**

未重跑 `RealTopicExtractorTests`：本轮未改 Topic Extractor / Topic Engine / `topic_sidepath.py`。

---

## P0

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p0_message_runtime tests.test_runtime_admit tests.test_pipeline tests.test_wechat_reply_format tests.test_webui_bot_process tests.test_webui_data
```

结果：**59 tests, OK**（基线 59）

覆盖：Self、Dedupe、Outbound、Stop Bot、Trigger、Message Gateway、Formatter。行为未变。

---

## P1 / P2

```text
.\.venv\Scripts\python.exe -m unittest tests.test_conversation_store tests.test_agent_prompt_binding tests.test_p1_p2_audit tests.test_config_save tests.test_webui_data tests.test_p0_message_runtime tests.test_runtime_admit tests.test_pipeline tests.test_wechat_reply_format tests.test_webui_bot_process tests.test_llm_client
```

结果：**103 tests, OK**（基线 103）

`DEFAULT_EXTRACTOR_PROMPT_NAME` 仍为 `TOPIC_EXTRACTOR`。

---

## 结论

```text
P5 Risk Offline                  = PASS（68）
P5 Decision Offline              = PASS（57）
P5 Decision Side-path            = PASS（15）
P5 Decision Adapter Isolation    = PASS（11）
P4 Task Offline                  = PASS（50）
P4 Task Side-path/Adapter isolation = PASS（25）
P3 Topic Offline                 = PASS（39）
P3 Topic Side-path/Adapter isolation = PASS（19）
P0                               = PASS（59）
P1/P2                            = PASS（103）

P0/P1/P2/P3/P4/P5-G0/G1/G2 frozen baseline = PRESERVED
```
