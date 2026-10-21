# P7-G0 Data Source Audit

> 日期：2026-09-23  
> 只读扫描。未改 Store schema，未改 Engine。

---

## Processing 存放

四条链各自一份 `processed.json`，key 都是 `message_id|version`，默认 version = 1。

| Engine | 文件 | key 函数 | 读取 |
| --- | --- | --- | --- |
| Topic | `data/topic_store/conversations/<conv>/processed.json` | `topic_store.processing_key` | `TopicStore.get_processing` |
| Task | `data/task_store/conversations/<conv>/processed.json` | `task_store.processing_key` | `TaskStore.get_processing` |
| Decision | `data/decision_store/conversations/<conv>/processed.json` | `decision_store.processing_key` | `DecisionStore.get_processing` |
| Risk | `data/risk_store/conversations/<conv>/processed.json` | `risk_store.processing_key` | `RiskStore.get_processing` |

记录包在 `{"records": {key: record}}`。

---

## Processing 字段（真实写入）

Topic `write_processing` 落盘：

```text
message_id
conversation_id
topic_processing_version
extractor_prompt_name
extractor_prompt_hash
decision
topic_id
processed_at
error
```

Task / Decision / Risk 落盘：

```text
message_id
conversation_id
topic_id
*_processing_version
extractor_prompt_name
extractor_prompt_hash
decision_summary
task_ids | decision_ids | risk_ids
processed_at
error
```

没有独立的 `error_code` 字段。失败时 `error` 是 `"<code>: <detail>"` 拼出来的字符串。读模型不把这段字符串拆成 `error_code`。

Topic 的业务结果在 `decision`。下游的业务结果在 `decision_summary`（缺省才回退 `decision`）。

---

## SUCCESS / FAILED 集合

Topic `SUCCESS_DECISIONS`：

```text
NEW_TOPIC
EXISTING_TOPIC
TOPIC_UPDATE
UNRELATED
SKIPPED
```

Task：

```text
NEW_TASK
TASK_UPDATE
UNRELATED
SKIPPED
```

Decision：

```text
NEW_DECISION
UNRELATED
SKIPPED
```

Risk：

```text
NEW_RISK
RISK_UPDATE
UNRELATED
SKIPPED
```

四边都有 `FAILED`。Topic 成功判断是整串 `decision in SUCCESS_DECISIONS`。下游成功判断按逗号 / 分号拆开，每一段都在本 Engine 的 `SUCCESS_DECISIONS` 里。Retry 资格与现有 `topic_retry` / `downstream_retry` 一致：只有明确 `FAILED` 可重试。

---

## MessageRecord

只存在于 Topic Store：`messages.jsonl`。

字段：

```text
id
conversation_id
platform_message_id
sender_id
sender_wxid
sender_name
content
message_type
created_at
direction
reply_to_message_id
raw_reference
ingested_at
schema_version
```

下游 Store 不保存 MessageRecord。消息索引以 Topic Store 为准。

---

## Audit

| Engine | 文件 | 决策字段 |
| --- | --- | --- |
| Topic | `data/topic_store/topic_engine_audit.jsonl` | `topic_decision` |
| Task | `data/task_store/task_engine_audit.jsonl` | `task_decision` |
| Decision | `data/decision_store/decision_engine_audit.jsonl` | `decision_decision` |
| Risk | `data/risk_store/risk_engine_audit.jsonl` | `risk_decision` |

共同可见：`ts`、`conversation_id`、`message_id`、`error`。Audit 不是 processing 的事务证据，不能把缺失记录改成 SUCCESS。

---

## Runtime

`runtime_control/status.json` 由 `BotRuntime.snapshot` / `read_status_file` 读写。本 Gate 使用的真实字段：

```text
state          → runtime_state
pid            → bot_pid
wechat         → connected / disconnected
emergency
```

`is_accepting_work` 不是落盘字段。读模型按现有语义推导：`state` 为 `RUNNING` 或 `DEGRADED`，且 `emergency` 为假，且不存在 `STOP_REQUEST` / `EMERGENCY_STOP`。

`listen_count` 不在 `status.json`。WebUI 概览从配置 `LISTEN_LIST` 现算。读模型不另算，缺字段时为 null。

---

## Engine flags

权威方法，不复制第二套规则：

```text
topic_sidepath.is_topic_engine_enabled
task_sidepath.is_task_engine_enabled
decision_sidepath.is_decision_engine_enabled
risk_sidepath.is_risk_engine_enabled
```

顺序：`runtime_control/*_ENGINE_ENABLED` 文件，其次环境变量，最后模块常量。当前文件与常量都是 `false`。
