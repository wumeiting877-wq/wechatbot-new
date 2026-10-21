# P3-G1 回归报告

> 日期：2026-09-21  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 目的：确认 P3-G1 新增离线 Topic Engine **没有**改变 P0 / P1 / P2 冻结行为。

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
```

本轮未修改：Self / Dedupe / Outbound / Stop Bot / Trigger / Message Gateway / Chat Prompt 正文 / listener。

---

## P0

命令（与 `P0-TEST-REPORT.md` 原清单一致）：

```text
.\.venv\Scripts\python.exe -m unittest ^
  tests.test_p0_message_runtime ^
  tests.test_runtime_admit ^
  tests.test_pipeline ^
  tests.test_wechat_reply_format ^
  tests.test_webui_bot_process ^
  tests.test_webui_data
```

结果：**59 tests, OK**

与历史基线 **59 tests** 一致，未删测、未跳过。

覆盖确认：Self、Dedupe、Outbound、Stop Bot、Trigger、Message Gateway、Formatter。行为未变。

---

## P1 / P2

命令（与 `P1-P2-TEST-REPORT.md` 原清单一致）：

```text
.\.venv\Scripts\python.exe -m unittest ^
  tests.test_conversation_store ^
  tests.test_agent_prompt_binding ^
  tests.test_p1_p2_audit ^
  tests.test_config_save ^
  tests.test_webui_data ^
  tests.test_p0_message_runtime ^
  tests.test_runtime_admit ^
  tests.test_pipeline ^
  tests.test_wechat_reply_format ^
  tests.test_webui_bot_process ^
  tests.test_llm_client
```

结果：**103 tests, OK**

与历史基线 **103 tests** 一致，未删测、未跳过。

覆盖确认：Conversation、AgentConfig、Chat Prompt、wxid 落盘、Prompt 绑定完整性。  
`resolve_chat_prompt` 既有失败码与 fallback 禁止规则保持不变。  
`extractor_prompt_name` 生产 Agent 仍为 `null`。

---

## 结论

```text
P0 Regression = PASS
P1 Regression = PASS
P2 Regression = PASS
P0/P1/P2 frozen baseline = PRESERVED
```
