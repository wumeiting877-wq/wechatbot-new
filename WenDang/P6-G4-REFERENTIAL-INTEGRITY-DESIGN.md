# P6-G4 Referential Integrity Design

> 日期：2026-09-22  
> 不变式：实体最终 ID = Evidence Link 中使用的最终 ID。

---

## 不变式

任何成功写入的 Task / Decision / Risk：

```text
final_entity_id
→ CREATED_BY(created_msg_id)
```

若本次 apply 带 RELATED：

```text
final_entity_id
→ RELATED(prior_message_id)
```

禁止：

```text
entity.id     = xxx_2
link.entity_id = xxx
```

processing 中的 `task_ids` / `decision_ids` / `risk_ids` 必须是 final id。

---

## 两条路径继续并存

```text
同 id + 同 conversation + 同 topic + 同 created_msg_id
→ skip（P6-G3，不得改回 suffix）

同 id + 不同 created_msg_id
→ suffix _2（真碰撞，不得取消）
```

`make_task_id` / `make_decision_id` / `make_risk_id` 不改。

---

## 最小修复

在三个 Store 的 `commit_apply` 内维护：

```text
id_map = { original_id: final_id }
```

- skip：`id_map[original] = existing.id`
- suffix：`id_map[original] = original_2`
- 无碰撞：`id_map[original] = original`

然后：

1. 实体 `item["id"] = final_id`
2. `new_links` 经 `_remap_link`：改 `task_id` / `decision_id` / `risk_id`，并重算 link id
3. `applied_ids` 只收集 final id
4. Decision / Risk 的 CREATED_BY 校验对 final id 执行

Engine `_apply_decisions` 改用 `commit_apply` 返回值写 processing。  
这不是业务语义变化：NEW_* / UPDATE / UNRELATED 判定不变，只是把 Store 已决定的最终 id 记下来。

---

## create_* 不纳入幂等

生产不调用。直连 API 自己在 suffix 后写 CREATED_BY，本就不孤儿。  
保持 suffix，标记 internal/legacy。详见语义报告。

---

## UPDATED_BY

Task / Risk schema 允许 UPDATED_BY。Decision 禁止。

Engine 真碰撞路径是 NEW_*，不会在同一 commit 发 UPDATED_BY。  
Store remap 仍覆盖该 relation，避免 suffix 丢 link。  
后续对 suffix 实体做 UPDATE 时，调用方传入的已是 final id，不再 suffix。
