# P6-G6 Recovery Design

> 日期：2026-09-23  
> 设计结论：**不实现 recovery**

分类是 TYPE C。Gate 3 只在 TYPE B 时允许设计可执行恢复。这里记录为什么建议中的 API 不能落地。

---

## 被拒绝的 API

```text
processing_recovery.py
recover_missing_processing(engine, conversation_id, message_id, version)
```

它要求：

```text
确认 NOT_FOUND
↓
收集确定性证据
↓
证明业务 apply 已完整发生
↓
原样重建 processing
↓
不跑 LLM
```

重建所需的原 decision 不在稳定字段里。

---

## 为什么这些字段不够

| 候选证据 | 能证明什么 | 不能证明什么 |
|---|---|---|
| MessageRecord 存在 | 消息已入库。Topic 路径在 Extractor 之前就 upsert | Engine 做过某种 decision |
| Topic + CREATED_BY | 这条消息写过创建链接 | 再次执行应复用该 Topic。实测会分配 `_2` |
| Topic 对象 | id / title / summary | 没有 `created_msg_id`。不能从 Topic 反查创建消息 |
| RELATED link | 消息与 Topic 有关 | 分不清 EXISTING_TOPIC 和“被别人当作 evidence” |
| Task/Decision/Risk.`created_msg_id` + CREATED_BY | 有一条创建实体 | `decision_summary` 是否还包含 `UNRELATED`，以及顺序 |
| `*_engine_audit.jsonl` | isolate 曾尝试记一笔 | 成功 audit 在 processing 之后，CASE B 只留下 `FAILED` |

禁止使用正文、标题、decision_text、condition、impact、assignee、时间接近。

---

## 若强行写入会违反的规则

```text
看到 Task 就写 NEW_TASK          猜测 decision
看到 Topic 就写 NEW_TOPIC        忽略 _2 碰撞和 EXISTING/UNRELATED
把 audit FAILED 抄回 processing  与已经成功的业务 apply 矛盾
version=2                        逃避原 processing identity
NOT_FOUND 直接 retry             改变 P6-G2 / P6-G5 契约，并重跑 Extractor
```

Engine flag 也不被拿来当恢复开关：本 Gate 没有 metadata repair 实现。恢复既不是业务执行，也不是已证明的 metadata 修补。

---

## 保留的行为

```text
processing 不存在 → NOT_FOUND
FAILED            → 现有显式 retry
SUCCESS           → replay
STOPPED           → retry 拒绝，不写 Store
```
