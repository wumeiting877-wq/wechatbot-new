# P6-G0-FIX-OBS Report

> 日期：2026-09-22  
> 仅观测性修复。禁止改 Prompt / Model / request body / timeout / parser / decision schema / store_context / 业务返回值。

---

## 原问题

`llm_client.get_extractor_response` 成功一律：

```text
note_llm_call("topic_extractor", "extractor", ...)
log "Topic Extractor LLM ok"
```

Task / Decision / Risk 共用该入口。events 里会出现多条 `extractor/topic_extractor`，曾造成 N2 RCA 假象（把四引擎日志当成 Topic 双调用）。

---

## 修改

新增 `_extractor_log_purpose()`，仅映射日志标签：

```text
topic_extractor
task_extractor
decision_extractor
risk_extractor
```

未知值回退 `topic_extractor`（兼容旧调用）。

`get_extractor_response(..., purpose="topic_extractor")`：

- `note_llm_call(purpose_label, "extractor", ...)`
- `log.info("%s LLM ok model=%s", purpose_label, model_name)`

`chat.completions.create(...)` **没有** `purpose` 参数。线程名仍为 `TopicExtractorLLM`（不改行为）。

各 Engine 只在 `_default_extractor_llm_call` 里 `kwargs.setdefault("purpose", ...)`。测试用的 mock `llm_call` 不会多收参数。

未改：

- messages / temperature / max_tokens / timeout / store_context / model
- 四个 EXTRACTOR.md
- parser / Engine 决策

未做 §16 全链路字段重构（trace_id 等）。避免借 OBS 改业务。

---

## 测试

```text
test_purpose_labels_are_distinct                          PASS
test_get_extractor_response_signature_keeps_request_contract PASS
test_clients_pass_distinct_purpose                        PASS
test_extractor_log_purpose_distinguishes_engines          PASS
```

隔离测试（`get_extractor_response` 仍禁止 Chat Prompt / `get_deepseek_response`）仍 PASS。

---

## 结论

OBS 假阳性路径已关闭。本项不是生命周期 BLOCKER，但必须随 P6-G0 一起封板，避免下一轮 RCA 再误读日志。
