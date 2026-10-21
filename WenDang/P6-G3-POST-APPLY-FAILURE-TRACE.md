# P6-G3 Post-Apply Failure Trace

> 日期：2026-09-22  
> 注入点：`commit_apply` 已成功，强制 `_finalize` 抛 `RuntimeError`。  
> 随后调用 P6-G2 `retry_downstream(...)`。  
> 先取证，后修复。本文件同时记录修复前 / 修复后。

注入不是 Extractor exception。Extractor 返回 `NEW_*`，validate 通过，实体已写入。

---

## 注入后（三路，修复前后相同）

### Task

```text
entity_count     = 1
entity_id        = task_d57f3428e2c3
created_msg_id   = msg_p6g3_task
CREATED_BY       = 1
RELATED          = 0
processing       = FAILED
processing.task_ids = []
has_success      = false
Isolate          = RuntimeError: P6-G3 post-apply finalize boom
```

### Decision

```text
entity_count     = 1
entity_id        = dec_cff0d2cf94f3
CREATED_BY       = 1
processing       = FAILED
has_success      = false
```

### Risk

```text
entity_count     = 1
entity_id        = risk_a0488ad0f642
CREATED_BY       = 1
processing       = FAILED
has_success      = false
```

---

## 修复前：retry 探针

### Task — CASE B

```text
retry.ok              = true
retry.engine_decision = NEW_TASK
entity_ids            = task_d57f3428e2c3, task_d57f3428e2c3_2
CREATED_BY            = 1   （仍只挂在原 id）
processing            = NEW_TASK
processing.task_ids   = [task_d57f3428e2c3]
```

第二个逻辑 Task 已出现。suffix 实体没有 Evidence。  
processing 看似恢复，业务数据已重复。

### Decision — CASE C

```text
retry.ok              = false
retry.error_code      = CREATED_BY_REQUIRED
retry.error           = dec_cff0d2cf94f3_2
entity_count          = 1
entity_id             = dec_cff0d2cf94f3
processing            = FAILED
processing.error      = CREATED_BY_REQUIRED: dec_cff0d2cf94f3_2
```

没有第二条 Decision（suffix 在 `_commit` 前被 CREATED_BY 校验挡住）。  
processing 永久 FAILED，每次 retry 重复同一错误。

### Risk — CASE B

```text
retry.ok              = true
retry.engine_decision = NEW_RISK
entity_ids            = risk_a0488ad0f642, risk_a0488ad0f642_2
CREATED_BY            = 1
processing            = NEW_RISK
processing.risk_ids   = [risk_a0488ad0f642]
```

与 Task 同构：suffix 孤儿实体，原 Evidence 不重复。

---

## 修复前矩阵

| Engine | apply 后故障 | processing | retry 后实体变化 | 是否安全 |
|---|---|---|---|---|
| Task | yes | FAILED | +suffix `_2`；字段相同；CREATED_BY 不增 | **否** |
| Decision | yes | FAILED | 数量不变；retry 失败；processing 卡住 | **否** |
| Risk | yes | FAILED | +suffix `_2`；CREATED_BY 不增 | **否** |

---

## 修复后：同一注入 + 同一 retry

### Task

```text
retry.ok              = true
entity_ids            = [task_d57f3428e2c3]
suffix                = none
CREATED_BY            = 1
processing            = NEW_TASK
has_success           = true
```

### Decision

```text
retry.ok              = true
engine_decision       = NEW_DECISION
entity_ids            = [dec_cff0d2cf94f3]
CREATED_BY            = 1
processing            = NEW_DECISION
has_success           = true
```

### Risk

```text
retry.ok              = true
entity_ids            = [risk_a0488ad0f642]
CREATED_BY            = 1
processing            = NEW_RISK
has_success           = true
```

---

## 修复后矩阵

| Engine | apply 后故障 | processing（注入后） | retry 后实体变化 | 是否安全 |
|---|---|---|---|---|
| Task | yes | FAILED | 同 id，数量 1，字段不变，Evidence 不变 | **是** |
| Decision | yes | FAILED | 同 id，数量 1，processing → NEW_DECISION | **是** |
| Risk | yes | FAILED | 同 id，数量 1，字段不变，Evidence 不变 | **是** |

额外核对（CONSIST 测试，不仅数数量）：

```text
entity id 稳定
title / assignee / decision_text / condition / impact 未被覆盖
CREATED_BY 三元组不变
RELATED 三元组不变（含 prior message Evidence）
processing.task_ids / decision_ids / risk_ids = 原确定性 id
audit：FAILED → DOWNSTREAM_RETRY_REQUESTED → NEW_* → DOWNSTREAM_RETRY_SUCCESS
```
