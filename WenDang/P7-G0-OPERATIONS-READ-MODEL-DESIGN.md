# P7-G0 Operations Read Model Design

> 日期：2026-09-23

---

## 状态名

统一使用 `NOT_FOUND_UNKNOWN`。不使用 `NOT_RUN`、`PENDING`、`WAITING`。

```text
SUCCESS
FAILED_RETRYABLE
NOT_FOUND_UNKNOWN
```

`engine_enabled` 单独存放。Engine 关闭不是 processing 失败。

---

## 分类

processing 记录不存在：

```text
state = NOT_FOUND_UNKNOWN
decision = ""
retryable = false
retry_type = NONE
requires_manual_investigation = true
notice =
  processing record not found
  automatic retry disabled
  manual investigation required
```

即使 Topic / Task / Decision / Risk 实体或 CREATED_BY 已经存在，也不升级为 SUCCESS。Audit 里的 decision 只进 `last_audit_event` / `last_audit_error`。

记录存在，且 decision 属于该 Engine 的 `SUCCESS_DECISIONS`：

```text
state = SUCCESS
decision = 原始 decision 或 decision_summary
retryable = false
retry_type = NONE
```

`UNRELATED` 与 `SKIPPED` 属于 SUCCESS，文案是「已处理」，同时保留原始 decision。

记录存在，且 decision / decision_summary 明确为 `FAILED`：

```text
state = FAILED_RETRYABLE
retryable = true
Topic      → retry_type = TOPIC_RETRY
Task / Decision / Risk → retry_type = DOWNSTREAM_RETRY
```

本 Gate 不调用 retry。

记录存在，但结果既不是已知 SUCCESS 也不是 FAILED：

```text
state = NOT_FOUND_UNKNOWN
retryable = false
retry_type = NONE
notice = processing outcome unrecognized / automatic retry disabled / manual investigation required
```

不发明第四个对操作员可见的状态名。

---

## 时间

```text
有 processing.processed_at 且不是「缺失记录」→ source = processing.processed_at
NOT_FOUND 且没有 processing 时间 → source = message.created_at
仍没有 → source = message.ingested_at
```

`source_timestamp.source` 标清来源。Issues 按该时间倒序。

---

## 聚合

```text
MessageOperationsView
├─ message
├─ topic
├─ task
├─ decision
└─ risk
```

不把整条消息收成一个成功率。`attention_required` 为任一 Engine 处于 `FAILED_RETRYABLE` 或 `NOT_FOUND_UNKNOWN`。

---

## 文案

```text
SUCCESS            → 已处理
FAILED_RETRYABLE   → 处理失败，可重试
NOT_FOUND_UNKNOWN  → 处理状态未知，需人工检查
```

不显示「未处理」。

---

## 边界

读模型不写 Store，不运行 Engine，不发微信，不做自动 retry，不做 Reminder。P7-G1 才能讨论人工 Retry Action，并且必须继承：`NOT_FOUND_UNKNOWN` 的 `retry_type = NONE`。
