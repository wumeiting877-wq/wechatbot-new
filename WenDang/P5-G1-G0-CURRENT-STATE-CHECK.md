# P5-G1 Gate 0 当前状态核对

> 日期：2026-09-22  
> 阶段：P5-G1 实施前 READ ONLY  
> 方式：对照 P5-G0 七份设计文档与当前真实源码，Gate 0 未改业务代码。  
> 范围：Decision Engine **离线最小实现**。不接微信，不改 listener / topic_sidepath / task_sidepath，不实现 Risk Engine。

---

## 0. 冻结基线

```text
P0 STATUS            = CLOSED
P1 STATUS            = CLOSED
P2 STATUS            = CLOSED

P3 Topic Engine      = COMPLETE
P4 Task Engine       = COMPLETE

P5-G0                = COMPLETE
P5-G1                = 本轮开始实施（Gate 0 只读核对）
```

依据：`P5-CURRENT-STATE-AUDIT.md`、`P5-GAP-REPORT.md`、`P5-NEXT-IMPLEMENTATION-PLAN.md`，以及源码模块常量。

生产默认：

```text
TOPIC_ENGINE_ENABLED    = false     topic_engine.py
TASK_ENGINE_ENABLED     = false     task_engine.py
Decision Engine         = NOT IMPLEMENTED
Risk Engine             = NOT IMPLEMENTED
```

当前已验证（P5-G0 审计冻结，本轮不重做真机）：

```text
Topic Side-path = VERIFIED
Task Side-path  = VERIFIED
Real Topic LLM  = VERIFIED
Real Task LLM   = VERIFIED
Live Topic Ingestion = VERIFIED
Live Task Extraction = VERIFIED
Trigger / Chat / Stop Bot = PRESERVED
```

---

## 1. 必须确认的 10 项

| # | 核对项 | 源码证据 | 结论 |
|---|---|---|---|
| 1 | 当前不存在 `decision_engine.py` | 仓库仅设计文档提及；无生产实现文件 | **确认** |
| 2 | 当前不存在 `decision_store.py` | 同上；无 `data/decision_store/` | **确认** |
| 3 | 当前不存在 `decision_extractor_client.py` | 同上 | **确认** |
| 4 | 当前不存在生产 `DECISION_EXTRACTOR.md` | `prompts/extractors/` 仅有 `TOPIC_EXTRACTOR.md`、`TASK_EXTRACTOR.md` | **确认** |
| 5 | 不存在第二套 Decision Engine | Chat「结论」只是自然语言；Reminder 会发微信，必须排除；Topic/Task 的 `decision` 是 Extractor 枚举，不是企业决议实体 | **确认** |
| 6 | P3 Topic 模型未变化 | `topic_store.py` 仍为 MessageRecord / Topic / TopicMessageLink / TopicProcessingRecord；无 Decision 字段 | **确认** |
| 7 | P4 Task 模型未变化 | `task_store.py` 仍禁止 `decision_ids` / `risk_ids`；无 Task→Decision 外键 | **确认** |
| 8 | TopicStore 公开读接口仍存在 | `get_topic` / `get_message` / `list_messages` / `links_for_topic` 均存在 | **确认** |
| 9 | `tests/fixtures/p5/decision_cases.json` 存在 | CASE-D01～D08；`mixed_cases.json` 含 M01/M03 Decision 半边 | **确认** |
| 10 | 不修改 P3 / P4 即可完成离线 G1 | 离线入口可 `process_record(conversation, topic, message)`；fixture 预置 Topic + Message + Link；Decision 写入独立 Store | **确认** |

冻结文件（本轮原则上禁止修改，Gate 0 未改）：

```text
message/identity.py
message/dedupe.py
message/outbound.py
message/trigger.py
message/reply_format.py
message/listener.py
bot_runtime.py
topic_store.py
topic_engine.py
topic_sidepath.py
topic_extractor_client.py
prompts/extractors/TOPIC_EXTRACTOR.md
task_store.py
task_engine.py
task_sidepath.py
task_extractor_client.py
prompts/extractors/TASK_EXTRACTOR.md
prompts/QIYE.md
prompts/企业_1.md
conversation_store.py
agent_store.py
llm_client.py
```

`resolve_extractor_prompt("DECISION_EXTRACTOR")` 已按文件名读取 `prompts/extractors/{name}.md`，**不必改** `agent_store.py`。  
`DEFAULT_EXTRACTOR_PROMPT_NAME = "TOPIC_EXTRACTOR"` 保持。  
`list_prompt_names()` 不递归 `extractors/`，新 Prompt 不会进入 Chat 下拉。  
`get_extractor_response` 已是 `store_context=false`；Decision parser **不得**复用 Topic `parse_extractor_json`（STRIP_KEYS 含 `decisions`）或 Task parser。

---

## 2. 与 P5-G0 设计的一致性

| 设计文件 | Gate 0 核对 |
|---|---|
| `P5-CURRENT-STATE-AUDIT.md` | Evidence 足够；不必改 MessageRecord / InboundMessage |
| `P5-DECISION-DATA-MODEL-DESIGN.md` | `conversation_id` + `topic_id`；禁止 `task_id`；正文不可覆盖；只写 RECORDED |
| `P5-DECISION-ENGINE-DESIGN.md` | Topic 成功后独立观察者；G1 离线直调；不接 listener |
| `P5-EXTRACTOR-ARCHITECTURE-DESIGN.md` | 独立 DECISION_EXTRACTOR；拒绝统一 Action Extractor |
| `P5-TEST-DATASET.md` | D01～D08 + M01/M03 Decision 半边为权威期望 |
| `P5-GAP-REPORT.md` | 开放 BLOCKER = 无 |
| `P5-NEXT-IMPLEMENTATION-PLAN.md` | 本轮只做 G1 Offline |

---

## 3. STOP 条件核对

| # | 条件 | 结论 |
|---|---|---|
| 1 | 必须修改 P3 Topic schema | **否** |
| 2 | 必须修改 P4 Task schema | **否** |
| 3 | 必须修改 listener | **否** |
| 4 | 必须修改 Trigger | **否** |
| 5 | 必须改 TASK_EXTRACTOR | **否** |
| 6 | 必须使用统一 Action Extractor | **否** |
| 7 | 必须让 Decision 绑定 Task | **否** |
| 8 | 必须原地覆盖旧 Decision | **否**。NEW + `supersedes_decision_id` |
| 9 | 必须自动 SUPERSEDED 才能通过 | **否**。旧行保持 RECORDED |
| 10 | 必须实现 Risk 才能完成 Decision | **否**。M01 只断言 Decision 半边 |
| 11 | Evidence 无法指向 MessageRecord | **否** |
| 12 | 冻结回归失败且无法在新增 Decision 代码中解释 | Gate 0 尚未跑回归；实施后若发生则 STOP |

**不生成 `P5-G1-BLOCKER-REPORT.md`。不 STOP。可以进入 Gate 1。**

---

## 4. Gate 0 结论

```text
P5-G1 Gate 0           = PASS
可进入 Decision Store  = YES
必须改 P3 / P4         = NO
必须接微信             = NO
必须实现 Risk          = NO
开放 BLOCKER           = 无
```
