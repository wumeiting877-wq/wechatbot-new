# P6-G4 Collision Evidence Trace

> 日期：2026-09-22  
> 探针：`tests/_p6g4_probe_collision_evidence.py`  
> 强制：相同实体 id + 不同 `created_msg_id`（message A ≠ message B）

共享 id：

```text
task_forcedcoll1
dec_forcedcoll01
risk_forcedcoll1
```

消息：

```text
msg_p6g4_a
msg_p6g4_b
msg_p6g4_prior   # RELATED
```

---

## 修复前（真实探针，不是 Deferred 推断）

### Task

```text
entities = task_forcedcoll1, task_forcedcoll1_2
applied_ids 第二次 = [task_forcedcoll1_2]
```

| 实体 | CREATED_BY | RELATED |
|---|---|---|
| `task_forcedcoll1` | msg_p6g4_a **和** msg_p6g4_b | msg_p6g4_prior |
| `task_forcedcoll1_2` | **无** | **无** |

```text
suffix_orphan_created_by = true
wrong_hang_on_original   = true
```

**BUG 成立：** suffix 实体 Evidence 丢失；message B 错挂原 id。

### Decision

```text
第一次 applied = [dec_forcedcoll01]
第二次 second_error = DecisionStoreError:CREATED_BY_REQUIRED
entities 仍只有 dec_forcedcoll01
suffix 未落盘
```

| 实体 | CREATED_BY | RELATED |
|---|---|---|
| `dec_forcedcoll01` | msg_p6g4_a | msg_p6g4_prior |
| `dec_forcedcoll01_2` | 不存在 | 不存在 |

**BUG 成立：** 真碰撞无法写入。校验看的是 suffix id，links 仍带原 id。

### Risk

与 Task 同构：

```text
entities = risk_forcedcoll1, risk_forcedcoll1_2
suffix 无 CREATED_BY / RELATED
message B CREATED_BY 挂在原 id
CREATED_BY 校验走的是 new_risks 原 id，因此 commit 成功
```

**BUG 成立。**

### create_task 直连（对照）

```text
first  = task_forcedcoll1     CREATED_BY → msg_p6g4_a
second = task_forcedcoll1_2   CREATED_BY → msg_p6g4_b
direct_api_suffix_has_created_by = true
```

直连 API 在 suffix **之后**自己生成 link，Evidence 完整。  
孤儿只发生在 `commit_apply`。

---

## 修复后（同一探针）

三路结构相同：

```text
original CREATED_BY → message A
original RELATED    → prior
suffix   CREATED_BY → message B
suffix   RELATED    → prior
applied_ids 第二次  → *_2
suffix_orphan_created_by = false
wrong_hang_on_original   = false
Decision 不再 CREATED_BY_REQUIRED
```

Decision 现在也能写出 `dec_forcedcoll01_2`，且恰好 1 个 CREATED_BY。
