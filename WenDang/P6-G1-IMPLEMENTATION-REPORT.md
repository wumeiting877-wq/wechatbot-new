# P6-G1 Implementation Report

> 日期：2026-09-22  
> 范围：Replay / Fan-out Idempotency  
> 未进入新业务 Engine。未实现 `force_reprocess`。

---

## 1. 结论

Topic SUCCESS replay **不是**下游补偿设计。  
最小修复：`topic_sidepath.py` 在 `replayed=True` 时不再 fan-out。

---

## 2. 修改文件

| 文件 | 变更 |
|---|---|
| `topic_sidepath.py` | `EVENT_TOPIC_REPLAY`；`_process` 在 `replayed` 时 audit 后 return |
| `tests/test_p6g1_replay_idempotency.py` | **新增** REPLAY-01～08 + P0 DUPLICATE 对照 + 开关断言 |
| `WenDang/P6-G1-*.md` | 本轮文档 |

未改：listener / Trigger / Self / P0 Dedupe / Outbound / Chat Prompt / 四个 EXTRACTOR / 四个 decision schema / TopicEngine / Topic Store schema / Task/Decision/Risk Engine / `bot_lifecycle.py` / `webui_bot_process.py`。

未新增 Queue / Worker / Dashboard / 提醒 / 日报 / RAG。

---

## 3. `_process` 行为

```text
Topic result
│
├─ FAILED / error_code / CONV_NOT_RESOLVED
│     └─ no fan-out
│
├─ replayed=true（任意上次成功 decision）
│     └─ audit TOPIC_REPLAY {message_id, topic_id, fanout_skipped=true}
│     └─ no Task / Decision / Risk enqueue
│
└─ replayed=false
      ├─ SUCCESS + topic_id → 下游 topic_result_allows_* 决定是否入队
      └─ UNRELATED / SKIPPED → 仍调用 _maybe_enqueue_*，下游拒绝（保持旧行为）
```

`EXISTING_TOPIC` / `TOPIC_UPDATE` 的**首次**处理 `replayed=false`，仍 fan-out。

---

## 4. 观察性

```text
event            = TOPIC_REPLAY
message_id
topic_id
fanout_skipped   = true
```

未做 trace 重构。P6-G0 的 `topic_extractor` / `task_extractor` / `decision_extractor` / `risk_extractor` purpose 标签未改。

---

## 5. 开关

模块常量保持：

```text
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

测试里 `TopicSidepath(..., enabled=True)` 仅为覆盖，与既有 P3/P4/P5 测试相同。

---

## 6. 未做

- `force_reprocess`
- 正文 / hash / 时间窗去重
- 把 P0 DUPLICATE 并进 replay
- 改下游 Engine 的 processing 幂等（已足够；本轮在更上游关 fan-out）
