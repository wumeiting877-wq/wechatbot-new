# P6-G2 Implementation Report

> 日期：2026-09-22

---

## 新增

```text
wechatbot-new/downstream_retry.py
wechatbot-new/tests/test_p6g2_downstream_retry.py
```

未改：

```text
task_engine.py task_store.py task_sidepath.py
decision_engine.py decision_store.py decision_sidepath.py
risk_engine.py risk_store.py risk_sidepath.py
topic_engine.py topic_store.py topic_sidepath.py
listener Trigger Self P0 Dedupe Outbound Chat Prompt
四个 EXTRACTOR decision schema
bot_lifecycle webui_bot_process
```

---

## 服务

`DownstreamRetryService`

- 注入 `topic_store` + 三个已构造 Engine + 可选 `runtime` / `conversation`
- `retry_downstream(engine, conversation_id, message_id, topic_id, version=..., runtime=...)`
- 模块函数 `retry_downstream(..., service=)` 必须显式传 service，避免隐式建队列

一次请求最多调用一次目标 `Engine.process_record`。

---

## 错误码

| code | 何时 |
|---|---|
| `INVALID_ENGINE` | 不是 task/decision/risk |
| `ENGINE_DISABLED` | 未注入或 `enabled=False` |
| `NOT_FOUND` | 无 processing；不创建 |
| `NOT_RETRYABLE` | 非 FAILED（含 SUCCESS / UNRELATED / SKIPPED / NEW_*） |
| `STOPPED` | Runtime 不接活 |
| `IDENTITY_MISMATCH` | 请求 topic_id ≠ processing.topic_id |
| `MISSING_TOPIC` / `MISSING_MESSAGE` | 记录不存在 |

成功时 `result=SUCCESS`，`engine_decision` 保留 Extractor 真值（`NEW_TASK` 等）。  
再次失败时 `result=FAILED`，透出 Engine `error_code`。

---

## 审计

```text
DOWNSTREAM_RETRY_REQUESTED
DOWNSTREAM_RETRY_SUCCESS
DOWNSTREAM_RETRY_FAILED
DOWNSTREAM_RETRY_REJECTED
```

写到对应 Store `write_audit`；服务内存 `audit_events` 供测试。

---

## 未做（有意）

```text
Retry Queue / worker
max_retries / backoff
WebUI
改 Engine
改 Topic replay
绑 bot_runtime.runtime 全局单例
```
