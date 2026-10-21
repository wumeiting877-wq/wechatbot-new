# P6-G3 Gate 0 — READ ONLY 当前状态审计

> 日期：2026-09-22  
> 范围：Task / Decision / Risk Engine + Store + `downstream_retry.py`  
> 本 Gate：**只读**。未改 Engine / Store schema / Topic / Retry UI。

本文件回答：`commit_apply` 成功之后、`write_processing(SUCCESS)` 之前，真实流水线长什么样，以及 retry 会碰到什么。

---

## 冻结基线（进入本 Gate 时）

```text
P0..P2 = CLOSED
P3 Topic / P4 Task / P5 Decision / P5 Risk = COMPLETE
P6-G0 = COMPLETE
P6-G1 = COMPLETE
P6-G2 = COMPLETE
unittest discover = 555 OK

TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

P6-G2 已记录本窗口为 D3（deferred），未证明、未修复。

---

## 扫描文件

```text
task_engine.py / task_store.py
decision_engine.py / decision_store.py
risk_engine.py / risk_store.py
downstream_retry.py
```

未扫描、未修改：Topic Engine / Topic Store / Topic Side-path。

---

## 三路公共流水线

三个 Engine 的 `process_record` 结构对称：

```text
enabled?
    no  → EngineResult(skipped=True, decision=DISABLED)
    yes → try _process_record
            except → _isolate → write_processing(FAILED) + audit
```

`_process_record` 成功路径：

```text
require topic
get message
message belongs to topic?
has_successful_processing?
    yes → replay skip（不再 Extractor / apply / finalize）
outbound / rule_prefilter?
    yes → _finalize(SKIPPED|UNRELATED)   ← 无实体写入
list existing entities
build extractor input
Extractor.extract
parse / normalize
validate_*
_apply_* / commit_apply                  ← 实体 + Evidence 落盘
_finalize
    write_processing(SUCCESS summary)
    write_audit
    return EngineResult
```

危险窗口（本 Gate 唯一重点）在：

```text
commit_apply SUCCESS
        ↓
_finalize / write_processing(SUCCESS) 尚未完成
        ↓
异常 → process_record except → _isolate → processing=FAILED
```

P6-G2 Isolate 路径（Extractor timeout / validate 失败）发生在 `commit_apply` **之前**，本窗口未覆盖。

---

## Task Engine

```text
Extractor
  ↓  parse_task_extractor_json / normalize
Validate  validate_task_decisions
  ↓
_apply_decisions
  NEW_TASK:
      make_task_id(conversation_id, topic_id, message_id, ordinal, created_at)
      组装 Task + CREATED_BY link + RELATED links
  TASK_UPDATE:
      按 existing task_id 改字段 + UPDATED_BY link
  UNRELATED: skip
  ↓
Store commit_apply(new_tasks, updates, new_links)
  ↓
Evidence 已在 commit_apply 内写入 links.json（与实体同一次 _commit）
  ↓
_finalize
  write_processing(decision_summary=NEW_TASK|..., task_ids=[确定性 id])
  write_audit
  ↓
Processing SUCCESS write
```

确定性 id：

```text
task_{sha1(conversation_id|topic_id|created_msg_id|ordinal|created_at)[:12]}
tlink_{sha1(task_id|message_id|relation)[:12]}
```

`created_at` 取自 **MessageRecord.created_at**（稳定），不是 apply 当时的 `now`。因此同一 `message_id` 再次 apply，会生成 **同一个** `task_id`。

`commit_apply` 碰撞策略（非幂等 upsert）：

```text
if task_id in used_ids:
    suffix = 2
    while f"{task_id}_{suffix}" in used_ids:
        suffix += 1
    task_id = f"{task_id}_{suffix}"   # 例如 task_abc123_2
    item["id"] = task_id
    tasks.append(item)                # 追加第二条实体
```

links 侧已去重：

```text
(task_id, message_id, relation) 已存在 → continue
```

注意：suffix 只改 `new_tasks` 的 id，**不改** `new_links` 里的 `task_id`。若发生 suffix：

- 新实体 id = `task_xxx_2`
- Evidence 仍指向原 `task_xxx`（CREATED_BY 已存在则跳过）
- suffix 实体可能没有 CREATED_BY

Task `commit_apply` **不校验** CREATED_BY 个数。suffix 实体可以落盘。

`write_processing`：同一 `message_id|version` 覆盖；SUCCESS 冻结，FAILED 可被覆盖。

`_isolate`：无条件写 `decision_summary=FAILED`。不检查实体是否已存在。

---

## Decision Engine

```text
Extractor
  ↓
Validate  validate_decision_decisions
  ↓
_apply_decisions
  NEW_DECISION:
      make_decision_id(conversation_id, topic_id, message_id, ordinal, created_at)
      组装 Decision + CREATED_BY + RELATED
  UNRELATED: skip
  ↓  仅当 new_decisions 非空
Store commit_apply(new_decisions, new_links)
  ↓
_finalize → write_processing(SUCCESS) → audit
```

确定性 id：`dec_{sha1(...)}` / `dlink_{sha1(...)}`。种子与 Task 同构，retry 再 apply 会得到同一 `dec_id`。

`commit_apply` 同样 suffix `_2`。随后：

```text
for decision_id in applied_ids:          # 可能已是 dec_xxx_2
    _assert_exactly_one_created_by(...)  # suffix id 在 links 中为 0 条
```

因此 Decision 在「同 id 已存在 → suffix」路径上，**很可能在 `_commit` 之前因 `CREATED_BY_REQUIRED` 失败**，实体不追加，但 apply 抛错 → Isolate → processing 仍 FAILED。

links 去重与 Task 相同：`(decision_id, message_id, relation)`。

Decision 无 `UPDATED_BY`（v1 禁止）。无 update 路径。

---

## Risk Engine

```text
Extractor
  ↓
Validate  validate_risk_decisions
  ↓
_apply_risks
  NEW_RISK:
      make_risk_id(...)  同构确定性 id
      Risk + CREATED_BY + RELATED
  RISK_UPDATE:
      改字段 + UPDATED_BY
  UNRELATED: skip
  ↓  仅当 new_risks/updates/new_links 非空
Store commit_apply(...)
  ↓
_finalize → write_processing(SUCCESS) → audit
```

`commit_apply` 同样 suffix `_2`。CREATED_BY 校验用的是 **原始** `new_risks[].id`，不是 suffix 后的 `applied_ids`：

```text
created_ids = [item.get("id") for item in (new_risks or [])]
for risk_id in created_ids:
    _assert_at_least_one_created_by(risk_id, links)
```

原 id 的 CREATED_BY 已存在 → 校验通过 → suffix 实体可以落盘，且 **没有** 自己的 CREATED_BY。

---

## Retry Service（P6-G2，未改）

```text
retry_downstream(engine, conversation_id, message_id, topic_id, version)
  engine in {task, decision, risk}
  engine.enabled == True
  processing 必须已存在
  processing.decision_summary 必须全部是 FAILED
  Runtime accepting
  Topic / Message 存在
  → audit REQUESTED
  → engine.process_record(...)          # 完整再跑，含 Extractor
  → SUCCESS / FAILED audit
```

eligibility **只看 processing == FAILED**。  
不检查：

```text
实体是否已按 created_msg_id 存在
Evidence 是否已完整
commit_apply 是否已经成功过
```

因此本窗口一旦 processing=FAILED，retry **会再次 apply**。

一次显式请求最多执行一次。无 queue / cron / backoff。

---

## 只读推断（尚未用故障注入证明）

| 问题 | 只读判断 | 待 Gate 1/2 证明 |
|---|---|---|
| 窗口是否存在 | **存在**。apply 与 processing 不是同一次写盘 | 注入 `_finalize` 异常 |
| processing 在窗口后的状态 | `_isolate` 会写 FAILED（若 isolate 自己也失败则可能缺失） | 记录真实 processing |
| Task retry 是否 duplicate | Store 会 suffix → **可能 CASE B** | 数实体 / id / suffix |
| Decision retry 是否 duplicate | suffix 后 CREATED_BY 校验可能挡住写入 → **可能 CASE C**（不重复但 processing 永久 FAILED） | 记录 error_code |
| Risk retry 是否 duplicate | 校验看原 id → **可能 CASE B** | 数实体 / suffix |
| Evidence 是否重复 | links 按三元组去重，原 id 的 CREATED_BY **不重复**；suffix 实体可能 **没有** Evidence | 按 relation 计数 |
| Store 是否完全幂等 | **否**。links 幂等，实体 id 碰撞走 suffix 而不是 skip/upsert | 探针 |

Gate 0 **不假设** 一定有 duplicate。以上是代码路径推断，Gate 1 必须用注入证明真实行为。

---

## 明确不在本轮改动的层

```text
Topic Engine / Topic Store / Topic replay
entity id 生成公式（make_*_id 种子）
decision schema / 业务字段
Store JSON schema
transaction / Saga / 2PC
Retry Queue / worker / cron
WebUI / REST / 微信命令
把 FAILED 无条件改成 SUCCESS
```

最小修复候选（仅当探针证明需要）：

1. `commit_apply` 对「同一确定性 id + 同一 created_msg_id」改为 skip（利用现有确定性 id，不改生成规则）
2. 否则才考虑 retry preflight reconcile

先取证。
