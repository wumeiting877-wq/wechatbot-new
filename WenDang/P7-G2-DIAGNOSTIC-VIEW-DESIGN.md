# P7-G2 Diagnostic View Design

> 日期：2026-09-23

---

## 分层

```text
OperationsReadModel          列表与三态
OperationsDiagnosticService  单条消息的证据
```

列表 API 不塞入 Entity、Evidence 和多条 Audit。

---

## MessageDiagnosticView

```text
message
operations_state     四路三态，直接拷贝 Read Model
runtime              runtime_view + engine flags
topic / task / decision / risk
diagnostics          审计说明、人工重试记录、四路 diagnosis_summary
```

`state`、`decision`、`retryable`、`retry_type` 不在诊断层重算。

---

## EngineDiagnosticView

```text
engine
state / state_label / decision
retryable / retry_type
processing_found / processing
entity_count / entity_ids / entities
evidence_count / evidence
audit_events
diagnostic_flags
diagnosis_summary
investigation_lines
```

Evidence 按 `CREATED_BY`、`UPDATED_BY`、`RELATED` 分栏，并给出各自条数。

---

## 观察标记

只允许事实标记：

```text
PROCESSING_MISSING
PROCESSING_PRESENT
ENTITY_PRESENT
CREATED_BY_PRESENT
UPDATED_BY_PRESENT
RELATED_PRESENT
CREATION_EVIDENCE_PRESENT
AUDIT_FAILED_PRESENT
MANUAL_RETRY_ATTEMPTED
```

`CREATION_EVIDENCE_PRESENT` 同时满足 `created_msg_id == 当前消息` 和本消息的 `CREATED_BY`。页面可以说「存在创建证据」。不生成 `NEW_TASK` / `NEW_TOPIC`。

`RELATED` 的说明是「消息与该业务实体有关」。不解释成 `EXISTING_TOPIC`。

不允许：

```text
RECOVER_AS_NEW_TASK
SHOULD_BE_SUCCESS
PARTIAL_SUCCESS
LIKELY_SUCCESS
PROBABLY_NOT_RUN
```

---

## diagnosis_summary

```text
Processing record present; stored decision is <已存储 decision>.
Processing record present.
Processing record missing; business entity evidence exists.
Processing record missing; no related business entity evidence found.
```

processing 缺失且没有实体、证据时，中文说明是「未发现业务处理记录」。不写「确认从未执行」「尚未处理」「系统已经处理成功」「建议自动重跑」。

processing 缺失且已有实体或证据时：

```text
系统存在业务写入痕迹，但无法从现有数据确定原 Processing Decision。
禁止自动重试。
```

状态仍是 `NOT_FOUND_UNKNOWN`。

---

## 页面

```text
← 返回运维中心
消息信息
Runtime / Engine 状态
处理状态
诊断详情（四路 Processing / Entity / Evidence / Audit）
人工重试审计
```

样式沿用处理状态页：表格、定义列表、状态标签。没有统计卡片、渐变或图表。

详情页不放重试、修复、重新处理。列表页继续使用 P7-G1 的原按钮和原 POST。
