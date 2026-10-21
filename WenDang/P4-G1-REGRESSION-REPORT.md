# P4-G1 回归报告

> 日期：2026-09-21  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 目的：确认 P4-G1 新增离线 Task Engine **没有**改变 P0 / P1 / P2 / P3 冻结行为。

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
P3-G0/G1/G2 = COMPLETE
```

本轮未修改：Self / Dedupe / Outbound / Stop Bot / Trigger / Message Gateway / Chat Prompt 正文 / listener / Topic Engine / Topic Side-path / Topic Extractor Prompt。  
原测试未删、未 skip、未改预期。

---

## P4 Task Tests（本轮新增，不计入旧基线数字）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_task_store tests.test_task_extractor tests.test_task_engine_offline
```

结果：**50 tests, OK**

---

## P3 Topic Offline

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_store tests.test_extractor_prompt tests.test_topic_engine_offline
```

结果：**39 tests, OK**（基线 39）

---

## P3 Side-path + Live Adapter

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_sidepath tests.test_topic_live_adapter
```

结果：**27 tests, OK**

含 Side-path CASE-S1～S10 与 Extractor 隔离；真实 LLM 适配测试在当前环境可运行且通过。行为与 P3-G2 一致：不改 verdict、不发微信。

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
P3 Topic Offline       = PASS（39）
P3 Side-path / Adapter = PASS（27）
P0 Regression          = PASS（59）
P1/P2 Regression       = PASS（103）

P0/P1/P2/P3 frozen baseline = PRESERVED
Trigger / Chat / Stop Bot / Topic 语义 = PRESERVED
TASK_ENGINE_ENABLED default = false
TOPIC_ENGINE_ENABLED default = false
```
