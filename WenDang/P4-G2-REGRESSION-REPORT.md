# P4-G2 回归报告

> 日期：2026-09-21  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 目的：确认 P4-G2 Task Side-path **没有**改变 P0 / P1 / P2 / P3 冻结行为。

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
P3-G0/G1/G2 = COMPLETE
```

本轮未修改：Self / Dedupe / Outbound / Stop Bot / Trigger / Message Gateway / Chat Prompt 正文 / `evaluate_inbound` / Topic Engine / Topic Extractor Prompt / Topic decision schema。  
原测试未删、未 skip、未改预期。

listener 仍只有 Topic 一条旁路。Task 挂在 Topic worker 成功之后。

---

## P4 Task Offline（G1 基线，必须保持 50）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_task_store tests.test_task_extractor tests.test_task_engine_offline
```

结果：**50 tests, OK**（基线 50）

---

## P4-G2 新增自动测试（不计入旧 50）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_task_sidepath
.\.venv\Scripts\python.exe -m unittest tests.test_task_live_adapter.TaskExtractorIsolationTests tests.test_task_live_adapter.TaskFailurePreservesTopicTests
.\.venv\Scripts\python.exe -m unittest tests.test_task_live_adapter.RealTaskExtractorTests
```

| 套件 | 结果 |
|---|---|
| Task Side-path TS1～TS10 + 隔离 | **13 OK** |
| Extractor 隔离 + 失败注入 | **12 OK** |
| Real Task T01～T10 + prompt/model 记录 | **11 OK** |

合计新增 **36 OK**。

---

## P3 Topic Offline

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_store tests.test_extractor_prompt tests.test_topic_engine_offline
```

结果：**39 tests, OK**（基线 39）

---

## P3 Side-path + Live Adapter

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_sidepath
.\.venv\Scripts\python.exe -m unittest tests.test_topic_live_adapter.ExtractorIsolationTests
.\.venv\Scripts\python.exe -m unittest tests.test_topic_live_adapter.RealTopicExtractorTests
```

结果：**12 + 7 + 8 = 27 tests, OK**（基线 27）

含 Side-path CASE-S1～S10 与 Extractor 隔离；真实 Topic LLM 语义仍通过。行为与 P3-G2 一致：不改 verdict、不发微信。

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
P4 Task Offline        = PASS（50）
P4-G2 新增             = PASS（36）
P3 Topic Offline       = PASS（39）
P3 Side-path / Adapter = PASS（27）
P0                     = PASS（59）
P1/P2                  = PASS（103）
```

冻结层回归全部保持。

---

## 真机结束后复跑（2026-09-21 16:05 后）

真机窗口只改 `runtime_control` 开关与超时注入，未改冻结源码。收尾复跑（不含真实 LLM 套件）：

| 套件 | 结果 |
|---|---|
| P4 Offline 50 + Task Side-path 13 + P3 Offline 39 + Topic Side-path 12 + P0 59 | **173 OK**（4.998s） |
| P1/P2 103 + Topic Isolation 7 + Task Isolation 12 | **122 OK**（1.010s） |

真实 Task / Topic LLM T01～T10 以 Gate 2 当时结果为准，收尾未再打生产模型。
