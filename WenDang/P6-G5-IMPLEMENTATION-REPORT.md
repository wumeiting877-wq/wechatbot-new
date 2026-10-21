# P6-G5 Implementation Report

> 日期：2026-09-22

---

## 新增

```text
wechatbot-new/topic_retry.py
wechatbot-new/tests/test_p6g5_topic_retry.py
wechatbot-new/tests/_p6g5_probe_topic_failed_retry.py
```

最小改动：

```text
topic_sidepath.py
  + process_record_and_fanout
  + _apply_topic_engine_result
  + _fanout_topic_result
```

未改：

```text
topic_engine.py topic_store.py
downstream_retry.py
task_engine.py task_store.py task_sidepath.py
decision_engine.py decision_store.py decision_sidepath.py
risk_engine.py risk_store.py risk_sidepath.py
listener Trigger Self P0 Dedupe Outbound Chat Prompt
四个 EXTRACTOR decision schema
bot_lifecycle webui_bot_process keep_alive
```

---

## 服务

`TopicRetryService`

- 注入已构造 `TopicSidepath` + 可选 `runtime` / `conversation`
- `retry_topic(conversation_id, message_id, version=..., runtime=...)`
- 模块函数 `retry_topic(..., service=)` 必须显式传 service，避免隐式建队列

一次请求最多调用一次 `TopicEngine.process_record`。  
成功后走 `TopicSidepath` 既有 `_fanout_topic_result` → `_maybe_enqueue_*`。

---

## 错误码

| code | 何时 |
|---|---|
| `ENGINE_DISABLED` | Sidepath 未启用，或注入的 Engine `enabled=False` |
| `NOT_FOUND` | 无 Topic processing；不创建 |
| `NOT_RETRYABLE` | 非 FAILED（含 NEW_TOPIC / EXISTING_TOPIC / TOPIC_UPDATE / UNRELATED / SKIPPED） |
| `STOPPED` | Runtime 不接活 |
| `MISSING_MESSAGE` | MessageRecord 不存在 |

成功时 `result=SUCCESS`，`decision` 保留 Extractor 真值。  
再次失败时 `result=FAILED`，透出 Engine `error_code`。无递归。

---

## 审计

```text
TOPIC_RETRY_REQUESTED
TOPIC_RETRY_SUCCESS
TOPIC_RETRY_FAILED
TOPIC_RETRY_REJECTED
```

写到 Topic Store `write_audit`；服务内存 `audit_events` 供测试。

---

## 下游开关

Topic retry SUCCESS 后不绕过：

```text
Task / Decision / Risk 各自 enabled()
runtime.is_accepting_work()
topic_result_allows_*
```

例：Task disabled + Decision/Risk enabled → fan-out `0/1/1`。

---

## 未做（有意）

```text
Topic Retry Queue / worker
max_retries / backoff
WebUI / Dashboard / 微信命令
自动把 NOT_FOUND 当首次执行
改 Engine / Store schema
改 P6-G1 SUCCESS replay fan-out
改 P6-G2 downstream_retry.py
```
