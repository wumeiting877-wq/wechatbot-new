# P6-G6 Blocker Report

> 日期：2026-09-23  
> 状态：BLOCKED  
> 分类：TYPE C

---

## 触发的停止条件

```text
processing 缺失可达
现有数据无法区分“未执行”和“执行过但 processing 丢失”
恢复原 decision 必须猜测
```

没有改 Store schema，没有加 transaction id / WAL / Saga，没有改确定性 entity id。

---

## 证据

`tests/_p6g6_probe_missing_processing.py` 在 `process_record` 里注入 `write_processing` 双失败：

```text
Topic / Task / Decision / Risk
业务实体 + CREATED_BY 已存在
get_processing = None
audit decision = FAILED
```

同一探针还证明：

```text
UNRELATED 丢失 与 apply 前失败     业务 Store 相同
EXISTING_TOPIC 丢失 与 Evidence RELATED   Link 相同
NEW_TASK 与 NEW_TASK,UNRELATED     实体足迹相同
Topic 被再次 process_record        分配 topic_id_2，不是复用第一个 Topic
```

---

## 明确不做

```text
不把 NOT_FOUND 改成自动执行 Engine
不写 recover_missing_processing
不根据实体猜测 NEW_TASK / NEW_TOPIC / NEW_DECISION / NEW_RISK
不把 audit 的 FAILED 当成原 decision
不升 processing version
不加 recovery queue / worker / WebUI
```

既有契约继续有效：

```text
NOT_FOUND → retry 拒绝
FAILED    → 既有 retry_topic / retry_downstream
SUCCESS   → replay，0 新 fan-out
```
