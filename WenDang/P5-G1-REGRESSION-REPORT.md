# P5-G1 回归报告

> 日期：2026-09-22  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 目的：确认 P5-G1 新增离线 Decision Engine **没有**改变 P0 / P1 / P2 / P3 / P4 冻结行为。

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
P3 Topic Engine = COMPLETE
P4 Task Engine  = COMPLETE
```

本轮未修改：Self / Dedupe / Outbound / Stop Bot / Trigger / Message Gateway / Chat Prompt 正文 / listener / Topic Engine / Topic Side-path / Topic Extractor Prompt / Task Engine / Task Side-path / Task Extractor Prompt。  
原测试未删、未 skip、未改预期。

---

## P5 Decision Tests（本轮新增，不计入旧基线数字）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_decision_store tests.test_decision_extractor tests.test_decision_engine_offline
```

结果：**57 tests, OK**

---

## P4 Task Offline

```text
.\.venv\Scripts\python.exe -m unittest tests.test_task_store tests.test_task_extractor tests.test_task_engine_offline
```

结果：**50 tests, OK**（基线 50）

---

## P4 Task Side-path / Adapter

```text
.\.venv\Scripts\python.exe -m unittest tests.test_task_sidepath tests.test_task_live_adapter.TaskExtractorIsolationTests tests.test_task_live_adapter.TaskFailurePreservesTopicTests
```

结果：**25 tests, OK**（Side-path 13 + Adapter 隔离/失败 12，与 P4-G2 自动测试基线一致）

未重跑 `RealTaskExtractorTests`：本轮未改 `TASK_EXTRACTOR.md` / `task_extractor_client.py` / `task_engine.py`；隔离测试已证明 Chat / Topic / Task Prompt 边界仍在。真实 Task LLM 不是 G1 必须项。

---

## P3 Topic Offline

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_store tests.test_extractor_prompt tests.test_topic_engine_offline
```

结果：**39 tests, OK**（基线 39）

---

## P3 Topic Side-path / Adapter

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_sidepath
.\.venv\Scripts\python.exe -m unittest tests.test_topic_live_adapter.ExtractorIsolationTests
```

结果：**12 + 7 = 19 tests, OK**

未重跑 `RealTopicExtractorTests`：本轮未改 Topic Extractor / Topic Engine；隔离测试已证明 `get_extractor_response` 与 Prompt 边界仍在。真实 Topic LLM 不是 G1 必须项。

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

## 结论

```text
P5 Decision Offline     = PASS（57）
P4 Task Offline         = PASS（50）
P4 Task Side-path/Adapter isolation = PASS（25）
P3 Topic Offline        = PASS（39）
P3 Topic Side-path/Adapter isolation = PASS（19）
P0                      = PASS（59）
P1/P2                   = PASS（103）

P0/P1/P2/P3/P4 frozen baseline = PRESERVED
```
