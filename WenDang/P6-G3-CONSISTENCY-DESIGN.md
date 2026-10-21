# P6-G3 Consistency Design

> 日期：2026-09-22  
> 基于 Gate 1/2 真实探针，不是事先假设。

---

## 问题分层

```text
确定性 id 再生出同一 id          ← 正确，保留
commit_apply 把同 id 当碰撞 suffix ← 本 Gate 唯一必须改的一层
Engine _apply / Retry eligibility ← 不必改
processing Isolate 写 FAILED      ← 正确，必须保留（不能吞掉 finalize 错误）
```

禁止：

```text
except: mark SUCCESS
根据标题/正文/时间猜“已经成功”
改 make_*_id
新表 / transaction id / Saga
```

---

## 选用方案：幂等 apply（Store）

同一逻辑实体的判定必须来自 Store 已有确定性字段：

```text
existing.id == incoming.id
AND existing.conversation_id == incoming.conversation_id
AND existing.topic_id == incoming.topic_id
AND existing.created_msg_id == incoming.created_msg_id
```

命中：

```text
skip 追加
不改原实体业务字段
links 仍走原有三元组去重
返回原 id 作为 applied id
```

未命中但 id 冲突（不同 `created_msg_id`，真哈希碰撞）：

```text
继续 suffix _2
```

这不是改 id 生成规则。碰撞后缀仍留给真正不同的消息。

---

## 为什么不改 Engine / Retry preflight

`process_record` 在 FAILED 后必须能再跑：这是 P6-G2 Extractor 失败路径。  
若在 Retry Service 里“看到实体就 reconcile SUCCESS”，会把不完整 apply 误标成功。

Store skip 之后，retry 仍走完整流水线：

```text
Extractor
validate
commit_apply  （skip 已存在的同逻辑实体）
_finalize     （processing FAILED → SUCCESS 覆盖）
```

processing 恢复来自真正跑完 `_finalize`，不是猜测。

---

## Evidence

```text
(entity_id, message_id, relation)
已存在 → continue
```

CREATED_BY / RELATED / UPDATED_BY 均按此去重。  
retry 不得 append 第二条相同三元组。

---

## 不采用的方案

| 方案 | 原因 |
|---|---|
| Engine 发现已有 created_msg_id 就跳过 apply | 扩大 Engine；与 Extractor 再决策耦合 |
| Retry preflight reconcile | 本轮 Store 证据已足够；先不实现 |
| 事务包住 apply+processing | STOP：新框架 |
| 失败时删除已写实体 | 补偿过重，且可能误删 |

---

## 不变式（关闭门槛）

```text
一个 message_id + engine + version

apply 成功 + finalize 失败 + 再次 retry：

逻辑实体数 = 1
无 suffix duplicate
Evidence 三元组不增加
业务字段不被错误覆盖
processing 最终为 SUCCESS_DECISIONS 之一
```

Extractor 失败（apply 未执行）路径保持 P6-G2：0 实体 → retry → 1 实体 + SUCCESS。
