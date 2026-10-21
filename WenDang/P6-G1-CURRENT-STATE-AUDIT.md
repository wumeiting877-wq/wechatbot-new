# P6-G1 当前状态审计

> 日期：2026-09-22  
> Gate 0 细节：`P6-G1-G0-REPLAY-CURRENT-STATE-AUDIT.md`  
> 探针：`P6-G1-REPLAY-TRACE.md`

---

## 冻结基线

```text
P0–P2 = CLOSED
P3 Topic / P4 Task / P5 Decision+Risk = COMPLETE
P6-G0 = COMPLETE
unittest discover 修复前 = 530 OK
四 Engine 开关 = false
```

P6-G0 Deferred：「Topic replayed SUCCESS 仍可能 fan-out Task/Decision/Risk」。本轮处理该项。

---

## Replay 真实语义（Gate 0）

`TopicEngine` 在 `has_successful_processing` 时：

- 跳过 Topic Extractor  
- 返回上次 `decision` + `topic_id`  
- `replayed=True`，`skipped=True`  
- 不重写 Store

这是 **Topic 层幂等跳过**，不是下游补偿循环。

`FAILED` 后再处理 **不是** replay（processing 不算成功）。那条路径仍允许 Extractor 与首次 fan-out。

---

## 修复前 fan-out（Gate 1）

同一 MessageRecord 第二次 `_process`：

| 计数 | 第一次 | 第二次 | delta |
|---|---|---|---|
| Topic Extractor | 1 | 1 | 0 |
| Task / Decision / Risk enqueue | 1/1/1 | 2/2/2 | +1/+1/+1 |
| 下游 Extractor | 1/1/1 | 1/1/1 | 0 |
| 下游 worker processed | 1/1/1 | 2/2/2 | +1/+1/+1 |
| Topic / Link / Task / Risk 实体 | 不增 | 不增 | 0 |

**Deferred 问题成立：** Extractor 已跳过，但 Side-path 仍 fan-out。

---

## Gate 2：下游二次收到同一 Topic 时

| # | 问题 | 修复前 | 修复后 |
|---|---|---|---|
| 1 | Queue 是否再次入队？ | **是** | 否 |
| 2 | Worker 是否再次执行？ | **是**（随后 Engine replay skip） | 否 |
| 3 | Extractor 是否再调？ | 否（下游 `has_successful_processing`） | 否 |
| 4 | Store 是否重复 processing？ | 否（成功 processing 冻结） | 否 |
| 5 | 是否重复新增实体？ | 否 | 否 |
| 6 | Evidence 是否重复？ | 否（Engine 不 `_apply_decision`；`add_link` 本就幂等） | 否 |
| 7 | 是否增加 LLM cost？ | 否（Extractor=0） | 否 |
| 8 | 未来主动副作用？ | Queue 占用；若下游曾 FAILED 会**顺便重试** | 关闭 |

不能因为「Store 最后没重复实体」就认定没有问题。Queue put 与 worker 执行已经违反「同一 MessageRecord fan-out ≤ 1」。

---

## Gate 3：幂等边界

**replay 不是下游补偿机制。** 证据：

1. Engine 设 `skipped=True` 并跳过 Extractor / `_apply_decision` / `_finalize`。  
2. 无注释、无测试、无设计稿写「Topic SUCCESS replay 用来补 Task/Decision/Risk」。  
3. P4「Topic 日后重试成功后再跑」= Topic **FAILED → 再成功**（`replayed=False`），不是本路径。  
4. 下游 Engine 各自已有 `has_successful_processing` replay。

因此默认策略：

```text
replayed=True → 不再次 fan-out
```

未触发 STOP。未改 Topic Store schema / P0 / Extractor / listener / Trigger。

---

## 最小修复落点

仅 `topic_sidepath.py` `_process`：

```text
FAILED / UNRELATED 首次 / SKIPPED 首次  → 原逻辑（UNRELATED/SKIPPED 仍走 _maybe_enqueue，下游拒绝）
SUCCESS replayed=false                   → Task / Decision / Risk fan-out
SUCCESS replayed=true                    → TOPIC_REPLAY audit，fanout_skipped=true，return
```

未改 `TopicEngine` decision、Store schema、三个下游 Engine。
