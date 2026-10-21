# P6-G4 Implementation Report

> 日期：2026-09-22  
> 范围：真碰撞 Evidence 引用完整性。  
> 未改 `make_*_id`、未取消 suffix、未改 P6-G3 skip、未改 Retry eligibility、未改生命周期。

---

## 改了什么

三个 Store 的 `commit_apply`：

```text
task_store.py
decision_store.py
risk_store.py
```

新增：

```text
_remap_link(raw_link, id_map, entity_key, make_id)
id_map: original_id → final_id
```

行为：

```text
suffix 后
  entity.id              = final id
  new_links.entity_id    = final id
  applied_ids            = final id
  CREATED_BY 校验        = final id（Decision / Risk）
```

Risk 校验从 `new_risks` 原 id 改为 `created_final_ids`（skip 或 suffix 后的最终 id）。

三个 Engine：

```text
task_engine.py
decision_engine.py
risk_engine.py
```

`_apply_decisions` 使用 `commit_apply` 返回的 `*_ids` 写入 processing。  
未改 Extractor、未改 NEW_*/UPDATE 判定。

`create_*` 仅加 docstring：internal/legacy；suffix 行为未改。

---

## 为什么这样改

探针证明 D2 真实存在：

- Task / Risk：suffix 实体无 Evidence，CREATED_BY 错挂原 id
- Decision：真碰撞 `CREATED_BY_REQUIRED`，第二实体写不进去

责任在 `commit_apply` 改了实体 id 却没改本次 links。  
最小修复是 id_map，而不是改确定性 id，也不是取消 suffix。

Engine 若不消费 applied_ids，processing 仍会记下冲突前的 id。这一行必须一起改，否则 REF-07 在生产链路上不成立。

---

## 未做

```text
create_* 改幂等
Dashboard / 人工 Retry UI
自动 retry / queue / cron
Engine disabled 默认打开
改 downstream_retry.py eligibility
改生命周期 / Topic
```

---

## 开关

```text
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```
