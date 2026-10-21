# P6-G3 Current State Audit

> 日期：2026-09-22  
> Gate 0 全文见：`P6-G3-G0-CURRENT-STATE-AUDIT.md`。  
> 本文件纳入 Gate 1/2 探针结论与实现边界。

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

---

## 窗口是否真实存在

**存在。已用 `_finalize` 注入证明，不是推断。**

三个 Engine 都是：

```text
commit_apply（实体 + Evidence 已落盘）
    ↓
_finalize → write_processing(SUCCESS)
    ↓ 此处异常
process_record except → _isolate → write_processing(FAILED)
```

注入后真实状态（三路相同结构）：

| 项 | 值 |
|---|---|
| 实体数 | 1 |
| Evidence CREATED_BY | 1 |
| processing | FAILED |
| Isolate error | `RuntimeError: P6-G3 post-apply finalize boom` |
| has_successful_processing | false |

因此 P6-G2 Retry Service 会认为可 retry，并再次 `process_record`。

---

## Gate 2：修复前 retry 真实行为

| Engine | apply 后故障 | processing | retry 后实体变化 | 判定 |
|---|---|---|---|---|
| Task | yes | FAILED | `task_xxx` + `task_xxx_2`；CREATED_BY 仍 1（suffix 无 Evidence） | **CASE B 不安全** |
| Decision | yes | FAILED | 实体仍 1；retry `CREATED_BY_REQUIRED`；processing 仍 FAILED | **CASE C 不安全** |
| Risk | yes | FAILED | `risk_xxx` + `risk_xxx_2`；CREATED_BY 仍 1 | **CASE B 不安全** |

不是 Store 完全幂等（CASE A）。  
不是“数量没变就安全”：Decision 数量没变，但 processing 永久 FAILED。

---

## 根因（一层）

确定性 id 会在 retry 时再生出同一个 id。  
`commit_apply` 旧逻辑把“id 已存在”当成哈希碰撞，走 `_2` 后缀追加。  
Engine / Retry Service / schema **都不是**第一责任层。

---

## 本阶段实现边界

| 做 | 不做 |
|---|---|
| 三 Store `commit_apply`：同 id + 同 `created_msg_id`/`topic_id` → skip | 改 `make_*_id` |
| CONSIST-01～10 锁定 | 新 schema / transaction id |
| 真碰撞（同 id、不同消息）仍 suffix `_2` | Saga / 2PC / 新 Queue |
| | 改 Engine 业务 decision |
| | retry preflight / 把 FAILED 直接改 SUCCESS |
| | Topic / Dashboard / 自动 retry / UI |

开关模块常量保持 false。
