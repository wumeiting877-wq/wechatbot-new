# P6-G1 Gate 0 — Replay 当前语义（READ ONLY）

> 日期：2026-09-22  
> 性质：**只读审计**。依据 `topic_engine.py` / `topic_store.py` / `topic_sidepath.py` 源码，不根据旧文档推断。  
> 正式汇总：`P6-G1-CURRENT-STATE-AUDIT.md`

---

## 1. 真实调用链

```text
MessageRecord（TopicStore.upsert_message）
        ↓
TopicEngine.process_inbound / process_record
        ↓
_process_record
        ├─ has_successful_processing(cid, message_id) == True
        │     → 跳过 Topic Extractor
        │     → 不调用 _apply_decision
        │     → 不调用 _finalize / 不写新 processing
        │     → return EngineResult(
        │           skipped=True,
        │           replayed=True,
        │           decision=prev.decision,
        │           topic_id=prev.topic_id,
        │           message_id, conversation_id,
        │       )
        └─ 否则：outbound / rule_prefilter / Extractor → _finalize
        ↓
TopicSidepath._process
        ├─ FAILED / error_code            → 不 fan-out
        ├─ CONVERSATION_NOT_RESOLVED      → 不 fan-out
        └─ 其它（含 replayed SUCCESS）     → 见本轮修复前后
```

---

## 2. 关键字真实行为

| 符号 | 源码位置 | 真实语义 |
|---|---|---|
| `processing_key` | `topic_store.processing_key` | `"{message_id}\|{version}"`，默认 version=1 |
| `has_successful_processing` | `topic_store.py` | processing 存在且 `decision ∈ SUCCESS_DECISIONS` |
| `SUCCESS_DECISIONS` | `topic_store.py` | `NEW_TOPIC` / `EXISTING_TOPIC` / `TOPIC_UPDATE` / `UNRELATED` / `SKIPPED`。**不含 FAILED** |
| `replayed` | `topic_engine._process_record` | 仅当已有成功 processing 时设为 `True` |
| `skipped=True`（replay 路径） | 同上 | 表示跳过 Extractor，**不是** `decision=SKIPPED` |
| `SUCCESS` | Side-path 用语 | `_process` 把非 FAILED 且无 `error_code` 当作成功处理 |
| `topic_id` | 来自 prev processing | replay 原样带回；NEW_TOPIC 首次成功后非空 |

`FAILED` 不是 successful processing。Topic 失败后再跑 **不是 replay**：会再调 Extractor，`replayed=False`。P4 文档里「Topic 日后重试成功后再跑 Task」指这条路径。

---

## 3. Topic Engine 返回值（replay）

```text
decision     = 上次 processing.decision（可能是 NEW_TOPIC / EXISTING_TOPIC / …）
topic_id     = 上次 processing.topic_id
replayed     = True
skipped      = True
error_code   = ""
error        = ""
```

**不**再写 Topic Store processing。  
**不**再 `add_link` / `create_topic`。  
**不**再调 Topic Extractor。

---

## 4. TopicSidepath 如何消费返回值（修复前）

`_process` 只判断：

1. `CONVERSATION_NOT_RESOLVED` → return  
2. `decision == FAILED` 或 `error_code` → return，不 fan-out  
3. 否则 `processed_count += 1`，然后无条件：

```text
_maybe_enqueue_task
_maybe_enqueue_decision
_maybe_enqueue_risk
```

**不读 `replayed`。不读 `skipped`。**

下游 `topic_result_allows_task/decision/risk` 只要求：

```text
error_code 为空
decision ∈ {NEW_TOPIC, EXISTING_TOPIC, TOPIC_UPDATE}
topic_id 非空
```

因此 replay 带回的 `NEW_TOPIC + topic_id` **会再次 put Task/Decision/Risk Queue**。

---

## 5. 两类情况不得混淆

### A. P0 DUPLICATE

同一 `platform_message_id` 再次从 listener 进入。  
`evaluate_inbound` → `dedupe=DUPLICATE`。  
`classify_topic_skip` → `SKIP_DUPLICATE`。  
**根本不入 Topic Queue。** 本轮不改。

### B. Topic replay（本阶段对象）

系统内部对 **已经 SUCCESS 的同一 MessageRecord** 再调 `TopicEngine.process_inbound` / `TopicSidepath._process`。  
P0 不参与。`replayed=True`。这是本 Gate 处理对象。

---

## 6. N2 不是 replay

同正文、不同 `platform_message_id` → 两个 MessageRecord → 两次独立首次 processing（`replayed=False`）。  
P6-G0 已锁定。本轮不得做成文本去重。
