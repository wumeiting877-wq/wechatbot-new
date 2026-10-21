# P6-G6 G0 Current State Audit

> 日期：2026-09-23  
> 范围：READ ONLY。本文件只记录四个 Engine 的真实写入时序。  
> 未改生产代码。

---

## 冻结基线

```text
P0–P5 = CLOSED / COMPLETE
P6-G0 … P6-G5 = COMPLETE
unittest discover 进入本 Gate 前 = 595 OK
```

四个模块常量保持：

```text
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

Retry 契约保持：

```text
processing 不存在 → NOT_FOUND，禁止自动当成首次执行
processing = FAILED → 既有 retry_topic / retry_downstream
processing = SUCCESS → replayed，不重跑 Extractor，不重新 fan-out
```

---

## 共同控制流

四个 Engine 的 `process_record` 都是：

```text
try:
    _process_record
except Exception:
    _isolate
```

`_isolate` 自己再包两层互不影响的 `try/except`：

```text
write_processing(FAILED)   失败则吞掉
write_audit(FAILED)        失败则吞掉
return EngineResult(decision=FAILED, isolated=True)
```

因此：

```text
_finalize 里第一次 write_processing(SUCCESS 决策) 抛错
→ 进入 _isolate
→ isolate 再写一次 FAILED
```

这两次写入都不是业务 commit 的一部分。

---

## Topic

成功路径（`TopicEngine._process_record` → `_apply_decision` → `_finalize`）：

```text
upsert_message                  messages.jsonl   单独 append
↓
Extractor / validate
↓
NEW_TOPIC:
    create_topic                topics.json      单独 atomic write
    add_link CREATED_BY         links.json       单独 atomic write
    refresh_topic_message_count topics.json      又一次单独 write
    每条 evidence RELATED       links.json + topics.json  各自单独 write
EXISTING_TOPIC / TOPIC_UPDATE:
    add_link RELATED 或 UPDATED_BY
    update_topic
    refresh_topic_message_count
UNRELATED / SKIPPED / prefilter:
    不写 Topic，不写 Link
↓
write_processing                processed.json   单独 atomic write
↓
write_audit                     topic_engine_audit.jsonl  单独 append
```

异常路径：

```text
任意异常（含 write_processing 抛错）
↓
_isolate
↓
write_processing(decision=FAILED)   失败被吞掉；且不带 topic_id
↓
write_audit(topic_decision=FAILED)  失败被吞掉
```

不在同一个 Store commit 里的写入：

```text
messages.jsonl
topics.json
links.json
processed.json
topic_engine_audit.jsonl
```

`create_topic` 用 `created_msg_id` 只参与 `make_topic_id`。落盘的 Topic 对象没有 `created_msg_id` 字段。

部分成功窗口真实存在：Topic / Link 已经各自落盘之后，`processed.json` 仍可能写失败。

---

## Task

成功路径：

```text
读取 Message / Topic / Evidence（不写 Task）
↓
Extractor / validate
↓
内存组装 new_tasks / updates / new_links
↓
commit_apply
    _commit: 先写 tasks.json，再写 links.json
    第二步失败时尝试把两份旧内容写回
    回滚自身失败会被吞掉，然后原异常继续抛出
↓
write_processing                另一个 processed.json
↓
write_audit                     task_engine_audit.jsonl
```

`commit_apply` 返回之后，`_finalize` 才写 processing。  
Task 实体与 processing 不是同一个 commit。

`decision_summary` 是 validated 列表的逗号拼接，包含被 apply 跳过的 `UNRELATED`。  
`UNRELATED` 不产生 Task，也不产生 Link。

异常路径与 Topic 相同：isolate 写 `decision_summary=FAILED`，失败则 processing 保持原样。

---

## Decision

与 Task 同构，差异：

```text
commit_apply 写 decisions.json + links.json
v1 只有 NEW_DECISION，禁止 UPDATED_BY
write_processing 在 commit_apply 之后
audit 在 write_processing 之后
```

`UNRELATED` 同样进入 `decision_summary`，但不写 Decision 实体。

---

## Risk

与 Task 同构：

```text
commit_apply 写 risks.json + links.json
NEW_RISK / RISK_UPDATE 在同一次 _commit
write_processing 在 commit 成功返回之后
audit 在 write_processing 之后
```

`UNRELATED` 进入 `decision_summary`，不写 Risk。

---

## Audit 的位置

四个 Engine 的成功 audit 都在 `write_processing` 之后。  
`write_processing` 抛错时，成功 audit 不会写。  
随后 `_isolate` 会尽力写一条 `FAILED` audit。这条 audit：

```text
不在业务 commit 内
不记录原来的 NEW_* / EXISTING_TOPIC / UNRELATED
Topic isolate 还不记录已创建的 topic_id
```

Audit 不能当作“原来 decision”的事务证据。

---

## 对 Gate 1 的直接含义

代码上，下面这条路径没有事务把业务结果和 processing 绑在一起：

```text
业务 apply 已返回
↓
第一次 write_processing(原 decision) 失败
↓
_isolate 的 write_processing(FAILED) 也失败
↓
processing 文件里没有这条 message
```

这是否在 `process_record` 里真实发生，由故障注入探针证明，见 `P6-G6-MISSING-PROCESSING-TRACE.md`。
