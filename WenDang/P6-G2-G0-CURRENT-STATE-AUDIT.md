# P6-G2 Gate 0 — READ ONLY 当前状态审计

> 日期：2026-09-22  
> 范围：Task / Decision / Risk / Topic Engine + Store + Side-path  
> 本 Gate：**只读**。未改 Engine / Store schema / Topic replay。

---

## 扫描文件

```text
task_engine.py / task_store.py / task_sidepath.py
decision_engine.py / decision_store.py / decision_sidepath.py
risk_engine.py / risk_store.py / risk_sidepath.py
topic_engine.py / topic_store.py / topic_sidepath.py
```

---

## 1. FAILED processing 是否会阻止下一次 process？

**不会。**

三个下游 Store 的 `has_successful_processing()` 只认 `SUCCESS_DECISIONS`：

| Engine | SUCCESS_DECISIONS |
|---|---|
| Task | `NEW_TASK` / `TASK_UPDATE` / `UNRELATED` / `SKIPPED` |
| Decision | `NEW_DECISION` / `UNRELATED` / `SKIPPED` |
| Risk | `NEW_RISK` / `RISK_UPDATE` / `UNRELATED` / `SKIPPED` |

`FAILED` 不在集合内。`process_record()` 仅在 `has_successful_processing == True` 时 `replayed=True` 并跳过 Extractor。

因此：

```text
FAILED processing
→ has_successful_processing = false
→ 下一次 process_record 会重新走 Extractor
```

---

## 2. successful processing 是否会 replay skip？

**会。** 三个 Engine 对称：

```text
if store.has_successful_processing(cid, message_id):
    return EngineResult(skipped=True, replayed=True, ...)
```

不会再调 Extractor，不会再 `commit_apply`。

---

## 3. 同一个 message_id + version 是否允许 FAILED 后重新处理？

**允许。**

`processing_key = message_id|version`，默认 `version = 1`。

`write_processing()`：

```text
prev = records[key]
if _is_success_processing(prev):
    return prev          # 成功记录冻结
records[key] = item      # 非成功（含 FAILED）允许覆盖
```

不需要新 version，不需要新 schema。

---

## 4. FAILED 后第二次成功会如何更新 processing？

**覆盖同一 key。**

```text
records[message_id|1] :
  FAILED  →  NEW_TASK / NEW_DECISION / NEW_RISK / UNRELATED / SKIPPED
```

不是追加第二条 processing。`processed_at` / `decision_summary` / `error` / 实体 id 列表一并换成成功记录。

已有离线测试：

```text
test_task_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed
test_decision_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed
test_risk_engine_offline.FailureInjectionTests.test_failed_then_retry_can_succeed
```

Gate 1 复跑：**6/6 OK**（含对应 Store 测试）。

---

## 5. processing 是否覆盖 FAILED，还是追加？

**覆盖。** 同一 `processing_key` 字典赋值。JSON 文件结构为 `{ "records": { key: item } }`，不是 jsonl append。

---

## 6. Evidence 是否会重复？

典型 FAILED 路径（Extractor timeout / exception）发生在 `_apply_*` **之前**：

```text
extract → parse → validate → apply/commit → _finalize
                ↑
            失败在这里
```

因此第一次 FAILED **不会写 Task/Decision/Risk 实体，也不会写 evidence link**。

第二次 SUCCESS 才 `commit_apply`。links 侧已有存在性去重：

```text
(task_id, message_id, relation) 已存在 → continue
```

Decision / Risk 同理。

边缘：若 `commit_apply` 已成功但 `_finalize` 随后崩溃，可能留下实体 + FAILED processing。现有 Engine 未改。见 `P6-G2-DEFERRED-ISSUES.md`。**不阻塞 P6-G2**：当前 Isolate 路径不走这条。

---

## 7. Store 是否已经天然支持 retry？

**是。三个 Store 都天然支持。**

不需要：

```text
schema migration
retry_count
next_retry_at
新 processing version
改 Topic Engine
```

Engine 自身已支持：

```text
FAILED ≠ successful processing
→ 再次 process_record 会重新执行
```

P6-G2 **不得修改三个 Engine**。只加薄封装。

---

## Topic replay（P6-G1 冻结，只读确认）

`topic_sidepath._process`：

```text
if result.replayed:
    audit TOPIC_REPLAY fanout_skipped
    return
_maybe_enqueue_task / decision / risk
```

Topic replay **不是**下游补偿。本阶段禁止为了 retry 重新打开 fan-out。

---

## 开关层级

| 层 | 行为 |
|---|---|
| 模块常量 `*_ENGINE_ENABLED` | 默认 **false**，必须保持 |
| `runtime_control/*_ENGINE_ENABLED` 文件 | Side-path `is_*_engine_enabled()` 优先 |
| 环境变量 | 次之 |
| Side-path `try_enqueue` | disabled → skip，不入队 |
| Side-path worker | `not enabled()` 或 Runtime 不接活 → 不 `process` |
| Engine `process_record` | `enabled=False` → `DISABLED`，不写 processing，不调 Extractor |
| Side-path 构造 Engine | 入队成功后 `TaskEngine(enabled=True)` |

结论：开关的权威在 **Side-path 入队/worker + Engine.enabled**。  
显式 retry **不走 Queue**。第一版必须检查 `engine.enabled`：关闭则 `ENGINE_DISABLED`，禁止构造 `enabled=True` 旁路。

测试与 P6-G1 相同：注入 `enabled=True` 的 Engine，模块常量仍 false。

---

## Runtime / Stop

`BotRuntime.is_accepting_work()` = `is_operational()`：

```text
RUNNING / DEGRADED 且未 send_blocked → True
STOPPING / STOPPED / ERROR / STARTING → False
```

Side-path worker 已：`not runtime.is_accepting_work()` → `SKIP_STOPPED`。

模块级 `bot_runtime.runtime` 单例默认 `state=STOPPED`。显式 retry **不自动绑定该单例**（否则离线测试全被拒绝，且会在 Bot 已 Stop 时误用全局状态）。

设计选择（非 STOP）：

```text
runtime 传入且不接活 → reject STOPPED（含 STOPPING）
runtime 未传入     → 允许（内部离线 capability）
生产路径若会跑 LLM，调用方应传入 Runtime
```

---

## Queue

下游 retry **不必**经过 Side-path Queue。`process_record` 是同步方法。

第一版 **不新增 Retry Queue**。未触发 STOP。

---

## 身份字段（已存在，不新增 schema）

| 字段 | 来源 |
|---|---|
| `conversation_id` | processing / 请求 |
| `message_id` | processing key |
| `topic_id` | processing 记录 |
| `engine` | 调用方 |
| `version` | `*_processing_version`，默认 1 |

禁止用正文 / title 匹配。

---

## Eligibility（Store 语义）

| processing | retryable |
|---|---|
| `FAILED` | **是** |
| `NEW_TASK` / `TASK_UPDATE` / `NEW_DECISION` / `NEW_RISK` / `RISK_UPDATE` | 否（已 successful） |
| `UNRELATED` / `SKIPPED` | 否（已 successful；Store 未把 UNRELATED 定义为 retryable） |
| 不存在 processing | 否（`NOT_FOUND`，禁止自动创建） |

Decision Store **没有** `DECISION_UPDATE` 成功态。若出现，同样拒绝。

---

## Gate 0 结论

```text
Store 天然支持 FAILED 覆盖重试
Engine 天然支持 FAILED 后再 process
不改 Engine / 不改 schema / 不改 Topic replay
最小实现 = 薄 DownstreamRetryService
```
