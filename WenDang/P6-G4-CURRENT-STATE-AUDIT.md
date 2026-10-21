# P6-G4 Current State Audit

> 日期：2026-09-22  
> 进入本 Gate 时的冻结基线与问题边界。

---

## 冻结基线

```text
P0 = CLOSED
P1 = CLOSED
P2 = CLOSED

P3 Topic Engine     = COMPLETE
P4 Task Engine      = COMPLETE
P5 Decision Engine  = COMPLETE
P5 Risk Engine      = COMPLETE

P6-G0 = COMPLETE
P6-G1 = COMPLETE
P6-G2 = COMPLETE
P6-G3 = COMPLETE

unittest discover = 568 OK

TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

P6-G3 已冻结：

```text
同逻辑实体
→ commit_apply 幂等 skip
→ 不产生 *_2
→ Evidence 不重复
→ processing 最终恢复 SUCCESS
```

不得回退。

---

## 本 Gate 两个剩余问题

来自 P6-G3 Deferred：

| ID | 问题 | 本轮处理 |
|---|---|---|
| D1 | `create_task` / `create_decision` / `create_risk` 直连 API 仍 suffix | Gate 0 审计后 **不改成幂等** |
| D2 | 真碰撞 suffix 后 `new_links.entity_id` 可能仍指向原 id | Gate 1 探针证明后 **最小 remap** |

---

## Gate 0 结论（只读）

`create_*` **不是**生产业务 API。

- Engine 写路径只走 `commit_apply`
- WebUI / Bot / Side-path / Retry Service 都不调用 `create_*`
- 全部调用点在 Store 单测与 Engine 测试 fixture

详见 `P6-G4-DIRECT-CREATE-CALLSITE-AUDIT.md`。

Gate 2 走情况 A：保持 suffix + 标记 internal/legacy + 源码/行为锁定测试。

---

## Gate 1 结论（修复前探针）

强制相同实体 id、不同 `created_msg_id`：

| Store | suffix 实体 | Evidence | 判定 |
|---|---|---|---|
| Task | `task_*_2` 写出 | suffix 无 CREATED_BY；message B 错挂原 id | **孤儿 + 错挂，真实存在** |
| Decision | 未写出 | 校验 `CREATED_BY_REQUIRED`，整次 commit 回滚 | **真碰撞写不进去** |
| Risk | `risk_*_2` 写出 | suffix 无 CREATED_BY；message B 错挂原 id | **孤儿 + 错挂，真实存在** |

`create_*` 直连路径自己在 suffix 之后生成 link，Evidence 完整。问题只在 `commit_apply`。

详见 `P6-G4-COLLISION-EVIDENCE-TRACE.md`。

---

## 本阶段实现边界

| 做 | 不做 |
|---|---|
| `commit_apply` 维护 `original_id → final_id` | 改 `make_*_id` |
| links / applied_ids / CREATED_BY 校验用最终 id | 取消真碰撞 suffix |
| Engine 把 processing ids 改成 Store 返回的最终 id | 把 `create_*` 改成幂等 |
| 锁定 create_* 为 internal/legacy | Dashboard / Retry UI / 自动 retry |
| REF-01～10 | 打开四个 Engine flag |
