# P5-G4 回归报告

> 日期：2026-09-22  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 目的：确认 P5-G4 Risk Side-path **没有**改变 P0 / P1 / P2 / P3 / P4 / P5 Decision 冻结行为。

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
P3 Topic Engine = COMPLETE
P4 Task Engine  = COMPLETE
P5-G0 / G1 / G2 / G3 = COMPLETE
```

本轮未修改：Self / Dedupe / Outbound / Stop Bot / Trigger / Message Gateway / Chat Prompt 正文 / `evaluate_inbound` / listener / Topic Engine / Topic Extractor Prompt / Topic decision schema / Task Engine / Task Side-path / Task Extractor Prompt / Task decision schema / Decision Engine / Decision Side-path / Decision Extractor Prompt / Decision decision schema / `RISK_EXTRACTOR.md`。  
原测试未删、未 skip、未改预期（仅把 G3「risk_sidepath 不存在」负向断言改为隔离扫描）。

listener 仍只有 Topic 一条旁路。Risk 挂在 Topic worker 成功之后，与 Task / Decision **并列** fan-out，不读取 Task / Decision 结果。

---

## P5 Risk Offline（G3 基线，必须保持 68）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_risk_store tests.test_risk_extractor tests.test_risk_engine_offline
```

结果：**68 tests, OK**（基线 68）

---

## P5-G4 新增自动测试

```text
.\.venv\Scripts\python.exe -m unittest tests.test_risk_sidepath
.\.venv\Scripts\python.exe -m unittest tests.test_risk_live_adapter.RiskExtractorIsolationTests tests.test_risk_live_adapter.RiskFailurePreservesTopicTaskDecisionTests
.\.venv\Scripts\python.exe -m unittest tests.test_risk_live_adapter.RealRiskExtractorTests
```

| 套件 | 结果 |
|---|---|
| Risk Side-path RS1～RS13 + 隔离 | **17 OK** |
| Extractor 隔离 + 失败注入 | **11 OK** |
| Real Risk R01～R09 / M01 / M02 + prompt/model | **12 OK**（约 36.1s） |

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

未重跑 `RealDecisionExtractorTests`：本轮未改 `DECISION_EXTRACTOR.md` / `decision_extractor_client.py` / `decision_engine.py`。

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

未重跑 `RealTopicExtractorTests`：本轮未改 Topic Extractor Prompt / Topic Engine 语义。`topic_sidepath.py` 仅最小解冻（Risk fan-out）。

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

覆盖：Conversation、AgentConfig、Chat Prompt、`resolve_chat_prompt` 失败码。  
`DEFAULT_EXTRACTOR_PROMPT_NAME` 仍为 `TOPIC_EXTRACTOR`。

---

## 真机结束后复跑（2026-09-22 16:18 后）

真机窗口只改 `runtime_control` 开关与超时注入，未改冻结源码。收尾复跑：

| 套件 | 结果 |
|---|---|
| P5 Risk Offline 68 + Risk Side-path 17 + Risk Isolation 11 + Decision 57 + Decision Side-path 15 + Decision Isolation 11 + P4 50 + Task Side-path/Adapter 25 + P3 39 + Topic Side-path/Adapter 19 + P0 59 | **371 OK**（10.836s） |
| P1/P2 103 | **103 OK**（0.808s） |
| Real Risk LLM 12 | **12 OK**（36.108s） |

开关与注入核对：

```text
runtime_control/TOPIC_ENGINE_ENABLED    = false
runtime_control/TASK_ENGINE_ENABLED     = false
runtime_control/DECISION_ENGINE_ENABLED = false
runtime_control/RISK_ENGINE_ENABLED     = false
TASK_EXTRACTOR_TIMEOUT_SEC     已删除
DECISION_EXTRACTOR_TIMEOUT_SEC 已删除
RISK_EXTRACTOR_TIMEOUT_SEC     已删除
残留 bot.py                    无
```

---

## 结论

```text
P5 Risk Offline                  = PASS（68）
P5-G4 Risk Side-path             = PASS（17）
P5-G4 Adapter Isolation          = PASS（11）
P5-G4 Real Risk LLM              = PASS（12）
P5 Decision Offline              = PASS（57）
P5 Decision Side-path            = PASS（15）
P5 Decision Adapter Isolation    = PASS（11）
P4 Task Offline                  = PASS（50）
P4 Task Side-path/Adapter isolation = PASS（25）
P3 Topic Offline                 = PASS（39）
P3 Topic Side-path/Adapter isolation = PASS（19）
P0                               = PASS（59）
P1/P2                            = PASS（103）

P0/P1/P2/P3/P4/P5-G0/G1/G2/G3 frozen baseline = PRESERVED
```
