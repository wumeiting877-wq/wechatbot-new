# P6-G3 Implementation Report

> 日期：2026-09-22  
> 范围：Task / Decision / Risk Store `commit_apply` 幂等 skip。  
> 未改 Engine 业务语义、未改 Topic、未改 Retry Service eligibility。

---

## 改了什么

三个 Store 的 `commit_apply`：

```text
task_store.py
decision_store.py
risk_store.py
```

新增判定：

```text
_lookup_by_id
_same_logical_entity  （id + conversation_id + topic_id + created_msg_id）
```

行为：

```text
同逻辑实体已存在 → skip 追加，applied_ids 仍返回原 id
同 id 但 created_msg_id 不同 → 保持碰撞后缀 _2
links 仍按 (entity_id, message_id, relation) 去重
```

未改：

```text
make_task_id / make_decision_id / make_risk_id
write_processing / _isolate
downstream_retry.py
task_engine.py / decision_engine.py / risk_engine.py
Topic *
create_task / create_decision / create_risk 的 suffix（不在 Engine retry 路径）
```

---

## 为什么这样改

探针证明：

- Task / Risk retry 会写出 `_2` 第二条实体（CASE B）
- Decision retry 会 `CREATED_BY_REQUIRED`，processing 卡在 FAILED（CASE C）

责任在 `commit_apply` 把 retry 当成碰撞。  
最小修复是让 Store 认出“这是同一次确定性 apply”，而不是上事务框架。

`_isolate` 仍然写 FAILED。不能在 finalize 异常时直接标 SUCCESS：当时只知道异常，不知道调用方会不会再 retry。恢复发生在下一次完整 `_finalize`。

---

## 未做

```text
Retry preflight reconcile
Dashboard / 人工 Retry UI
自动 retry / queue / cron
Engine disabled 默认打开
```

`create_*` 直连 API 仍可能 suffix。Engine 路径走 `commit_apply`，本 Gate 已覆盖。见 deferred。

---

## 开关

```text
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```
