# P6-G6 Missing Processing Trace

> 日期：2026-09-23  
> 方法：`process_record` 内替换 Store.`write_processing`。  
> 不是手工删除 `processed.json`。  
> 探针：`tests/_p6g6_probe_missing_processing.py`  
> 锁定：`tests/test_p6g6_missing_processing.py`

注入两种模式：

```text
first = 只有第 1 次 write_processing 失败，之后放行
all   = 每一次 write_processing 都失败
```

第 1 次是 `_finalize` 里的原 decision。  
第 2 次是 `_isolate` 里的 `FAILED`。

---

## CASE A — 第 1 次失败，isolate 成功

四路结果相同：业务实体已经在，最终 processing = `FAILED`。

| Engine | 第 1 次尝试 | 第 2 次尝试 | 落盘 processing | 业务 |
|---|---|---|---|---|
| Topic | `decision=NEW_TOPIC`，带真实 topic_id，version=1 | `decision=FAILED`，topic_id 为空 | `FAILED`，version=1，topic_id=null | 1 个 Topic + CREATED_BY |
| Task | `decision_summary=NEW_TASK`，task_ids 非空 | `FAILED` | `FAILED` | 1 个 Task，created_msg_id=当前消息 |
| Decision | `NEW_DECISION`，decision_ids 非空 | `FAILED` | `FAILED` | 1 个 Decision + CREATED_BY |
| Risk | `NEW_RISK`，risk_ids 非空 | `FAILED` | `FAILED` | 1 个 Risk + CREATED_BY |

Audit 只留下 `FAILED`，没有留下第 1 次的原 decision。  
Topic 的 FAILED processing 不指向已经创建的 topic。

这是 P6-G2 / P6-G5 已有 retry 能接住的状态。不是本 Gate 的缺口。

Task 上复跑既有 `retry_downstream`：实体仍是 1 个，processing 回到 `NEW_TASK`，task_ids 等于已有 id。P6-G3 幂等仍然成立。

---

## CASE B — 两次都失败

四路都是：

```text
EngineResult.decision = FAILED
processing = 不存在
MessageRecord = 存在
Audit = FAILED（不是原来的 NEW_*）
```

业务侧：

```text
Topic     1 Topic + 1 CREATED_BY，Topic 对象没有 created_msg_id
Task      1 Task，created_msg_id = message_id，1 CREATED_BY
Decision  1 Decision，created_msg_id = message_id，1 CREATED_BY
Risk      1 Risk，created_msg_id = message_id，1 CREATED_BY
```

第 1 次调用参数里已经有最终 entity id 和原 decision。  
这些字段没有写入 `processed.json`。

`retry_topic` / `retry_downstream` 对这个状态返回 `NOT_FOUND`，`executed=false`，不再调用 Extractor，不新增实体。

---

## Topic 再次执行会分配第二个 Topic

CASE B 之后，若直接再调用同一次 `process_record`（同一 message、同一 `created_at`、同一脚本仍返回 `NEW_TOPIC`）：

```text
Extractor 再跑 1 次
topic_id 与已有 id 碰撞
create_topic 追加后缀 _2
同一 message 出现两条 CREATED_BY
processing 写成 NEW_TOPIC，topic_id = 第一个 id + "_2"
```

探针实测第二个 id 为 `topic_b2fe52feb57c_2`。  
不会返回已有 Topic，也不会走 EXISTING_TOPIC。

这只证明“把缺失当成首次执行”会复制 Topic。  
现有 `retry_topic` 没有走这条路。

---

## 无法区分的两组 Store 形状

### 1. UNRELATED 成功但 processing 双写失败 vs Extractor 在 apply 前失败

两条消息各自跑完 CASE B 风格注入后，业务 Store 相同：

```text
MessageRecord 存在
Link 为空
Topic 不存在
processing 不存在
audit decision = FAILED
```

差异只在第 1 次调用参数：一条是 `UNRELATED`，一条是 isolate 直接写的 `FAILED`。  
落盘 audit 的 decision 字段都是 `FAILED`，不保留 `UNRELATED`。

### 2. EXISTING_TOPIC 双写失败 vs 从未执行、只被别人引用为 Evidence

```text
证据消息：只有 RELATED，processing 不存在，audit 为空
EXISTING_TOPIC CASE B：只有 RELATED，processing 不存在，audit=FAILED
```

Link 关系相同。Audit 即使存在，记的也是 `FAILED`，不是 `EXISTING_TOPIC`。

### 3. Task `NEW_TASK` vs `NEW_TASK,UNRELATED`

两次 CASE B 的落盘足迹相同：

```text
1 个 Task
1 条 CREATED_BY
processing 不存在
```

第 1 次调用的 `decision_summary` 分别是 `NEW_TASK` 和 `NEW_TASK,UNRELATED`。  
这个差异没有落盘。

---

## 结论

完整 processing 缺失从真实 `process_record` 可达。  
CASE A 留下 `FAILED`。  
CASE B 留下 `NOT_FOUND`，同时业务数据可以已经存在。  
现有文件不能把“从未执行”和“执行过但 processing 丢失”分成可还原原 decision 的两类。
