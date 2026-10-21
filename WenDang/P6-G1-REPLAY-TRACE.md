# P6-G1 Replay Trace

> 日期：2026-09-22  
> 路径：同一 `MessageRecord` → `TopicSidepath._process` ×2  
> 不经 listener / P0 DUPLICATE。Heuristic Extractor + counter。

Gate 1 原始记录：`P6-G1-G1-REPLAY-TRACE.md`

---

## 修复前

| 指标 | 第一次 | 第二次 | delta |
|---|---|---|---|
| Topic Extractor | 1 | 1 | 0 |
| Task Extractor | 1 | 1 | 0 |
| Decision Extractor | 1 | 1 | 0 |
| Risk Extractor | 1 | 1 | 0 |
| Topic processing | 1 NEW_TOPIC | 1 | 0 |
| Task Queue put | 1 | 2 | **+1** |
| Decision Queue put | 1 | 2 | **+1** |
| Risk Queue put | 1 | 2 | **+1** |
| Task/Decision/Risk worker | 1/1/1 | 2/2/2 | **+1** |
| `replayed` | false | **true** | |
| Topic / Link / Task / Risk 实体 | 1 / 1 / 1 / 1 | 不变 | 0 |

Decision 实体本探针为 0（启发式对该句未建 Decision），不影响 enqueue 计数。

---

## 修复后（同一探针）

| 指标 | 第一次 | 第二次 | delta |
|---|---|---|---|
| Topic Extractor | 1 | 1 | 0 |
| 下游 Extractor | 1/1/1 | 1/1/1 | 0 |
| Task Queue put | 1 | 1 | **0** |
| Decision Queue put | 1 | 1 | **0** |
| Risk Queue put | 1 | 1 | **0** |
| 下游 worker processed | 1/1/1 | 1/1/1 | **0** |
| `replayed` | false | true | |
| 实体 | 不变 | 不变 | 0 |

第二次 audit：`TOPIC_REPLAY`，`message_id` / `topic_id` 齐全，`fanout_skipped=true`。

---

## 与 P0 / N2 对照

| 场景 | 入口 | Topic processing | fan-out |
|---|---|---|---|
| P0 DUPLICATE 同 pid | listener + verdict | 不入 Topic Queue | 0 新 fan-out |
| Topic replay 同 MessageRecord | 内部 `_process` | `replayed=true` | **0**（本轮后） |
| N2 同正文不同 pid | 两条 NEW inbound | 两次 `replayed=false` | 2/2/2 |
