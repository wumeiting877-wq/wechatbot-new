# P3-G2 回归报告

> 日期：2026-09-21（Gate 4，真机后重跑）  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
```

本轮未修改 Self / Dedupe / Outbound / Stop Bot / Trigger / Message Gateway / Chat Prompt 正文 / `bot_runtime.py`。  
原测试未删、未 skip、未改预期。

---

## P3-G1 Topic Tests

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_store tests.test_extractor_prompt tests.test_topic_engine_offline
```

结果：**39 tests, OK**（基线 39）

---

## P0

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p0_message_runtime tests.test_runtime_admit tests.test_pipeline tests.test_wechat_reply_format tests.test_webui_bot_process tests.test_webui_data
```

结果：**59 tests, OK**（基线 59）

覆盖：Self、Dedupe、Outbound、Stop Bot、Trigger、Message Gateway、Formatter。

---

## P1 / P2

```text
.\.venv\Scripts\python.exe -m unittest tests.test_conversation_store tests.test_agent_prompt_binding tests.test_p1_p2_audit tests.test_config_save tests.test_webui_data tests.test_p0_message_runtime tests.test_runtime_admit tests.test_pipeline tests.test_wechat_reply_format tests.test_webui_bot_process tests.test_llm_client
```

结果：**103 tests, OK**（基线 103）

覆盖：Conversation、AgentConfig、Chat Prompt、`resolve_chat_prompt` 失败码。  
QIYE Agent 真机绑定 `extractor_prompt_name=TOPIC_EXTRACTOR`；`chat_prompt_name` 仍为 `QIYE`。企业_1 Agent extractor 仍为 null。

`get_deepseek_response` 仍含 Prompt 绑定与禁止静默 fallback（`tests.test_p1_p2_audit` PASS）。

---

## G2 新增自动测试（不计入上述基线数字）

Side-path 12 + Extractor 隔离 7 = **19 OK**  
真实 LLM 语义：`RealTopicExtractorTests` **8 OK**（见 `P3-G2-REAL-LLM-TEST-REPORT.md`，本轮未再打生产额度）。

---

## 结论

```text
P0 Regression = PASS
P1 Regression = PASS
P2 Regression = PASS
P3-G1 Topic Regression = PASS
P0/P1/P2 frozen baseline = PRESERVED
Trigger / Chat / Stop Bot 自动测试行为 = PRESERVED
```
