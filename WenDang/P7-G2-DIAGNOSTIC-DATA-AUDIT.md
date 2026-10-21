# P7-G2 Diagnostic Data Audit

> 日期：2026-09-23  
> 只读扫描真实 Store。没有为诊断新增字段。

---

## 能只读拿到的数据

| 需要 | 来源 | 读方法 |
| --- | --- | --- |
| MessageRecord | `data/topic_store/conversations/<conv>/messages.jsonl` | `TopicStore.get_message` / `list_messages` |
| Topic | 同会话 `topics.json` | `list_topics` / `get_topic` |
| Task | `data/task_store/.../tasks.json` | `list_tasks` / `get_task` |
| Decision | `data/decision_store/.../decisions.json` | `list_decisions` / `get_decision` |
| Risk | `data/risk_store/.../risks.json` | `list_risks` / `get_risk` |
| Processing | 各 Store `processed.json`，key = `message_id\|version`，默认 version 1 | `get_processing` |
| TopicMessageLink | topic `links.json` | `list_links` |
| Task / Decision / Risk Evidence | 各自 `links.json` | `list_links` |
| Engine Audit | `*_engine_audit.jsonl` | `read_audit` |
| Manual Action Audit | `data/operations/operations_action_audit.jsonl` | `read_action_audit` |
| 三态 | `OperationsReadModel.engine_view` | 不重新分类 |

`operations_read_model.py` 与 `operations_action_audit.py` 已有只读路径。诊断服务只调用读取。

---

## Processing 真实字段

Topic：

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

Task / Decision / Risk：

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

没有独立 `error_code`。诊断页展示 `error` 原文字，不从字符串拆 code。

读模型与诊断都只读默认 version 1。这和 P7-G0 的 `get_processing` 调用一致，避免「状态说缺失、页面却展示另一版 processing」。

---

## Entity 真实字段

Topic 没有 `created_msg_id`。页面用存储的 `id` 标成 `topic_id`，并展示 `title`、`summary`、`status`，以及已有的 confidence / 时间 / message_count。

Task 的负责人字段是 `assignee_text`，没有名为 `assignee` 的列。页面展示 `assignee_text`。同时展示 `title`、`status`、`created_msg_id`。

Decision 展示已有的 `title`、`decision_text`、`summary`、`status`、`created_msg_id`、`topic_id`、`supersedes_decision_id`。

Risk 展示已有的 `title`、`description`、`condition_text`、`impact_text`、`status`、`created_msg_id`、`topic_id`、`task_id`。

字段空着显示「未提供」。没有记录显示「无记录」。

---

## Evidence relation

| Store | 允许的 relation |
| --- | --- |
| Topic | CREATED_BY、RELATED、UPDATED_BY |
| Task | CREATED_BY、RELATED、UPDATED_BY |
| Decision | CREATED_BY、RELATED。UPDATED_BY 被 Store 禁止 |
| Risk | CREATED_BY、RELATED、UPDATED_BY |

诊断固定分这三栏。Decision 的 UPDATED_BY 为 0，显示「无记录」，不补一种 relation。

关联规则只接受：

```text
entity.created_msg_id == 当前 message_id
或 link.message_id == 当前 message_id
或当前这条 processing 记录里写明的 topic_id / task_ids / decision_ids / risk_ids
```

不用标题、正文相似度或时间接近。别的消息、别的会话的 link 不进入本页 Evidence。

---

## Audit

Engine audit 至少带 `ts`、各引擎的 `*_decision`、`error`。诊断按 `message_id` + `conversation_id` 过滤后只返回最近 20 条。`FAILED` 只作为观察标记 `AUDIT_FAILED_PRESENT`，不把 processing 状态改成 `FAILED_RETRYABLE`。

人工审计事件是 `MANUAL_RETRY_REQUESTED` 与 `MANUAL_RETRY_RESULT`，时间字段是 `ts`，来源标成 `operations_action_audit.ts`。它不参与三态。

---

## 时间来源

```text
processing.processed_at
audit.ts
message.created_at
message.ingested_at
entity.created_at / entity.updated_at / entity.last_message_at
evidence.created_at
operations_action_audit.ts
```

这些来源分开标注，不合并成一个业务时间。
