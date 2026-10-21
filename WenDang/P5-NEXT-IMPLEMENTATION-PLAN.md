# P5 下一步实施计划（等待指令）

> 日期：2026-09-22  
> 阶段：P5-G0 **已完成，在此 STOP**  
> 本文件只划后续 Gate。**不要在未收到实施指令时执行。**  
> 禁止自动进入 P5-G1。禁止同时开工 Decision 生产实现 + Risk 生产实现。

---

## 1. G0 已交付

| 文件 | 内容 |
|---|---|
| `WenDang/P5-CURRENT-STATE-AUDIT.md` | 冻结基线 + 无真正 Decision/Risk + Evidence 足够 |
| `WenDang/P5-DECISION-DATA-MODEL-DESIGN.md` | 绑 Conversation+Topic、不可原地覆盖、RECORDED、Evidence |
| `WenDang/P5-RISK-DATA-MODEL-DESIGN.md` | 可空 task_id、只写 OPEN、无 severity、Evidence |
| `WenDang/P5-DECISION-ENGINE-DESIGN.md` | Topic 成功后独立旁路、不依赖 Task |
| `WenDang/P5-RISK-ENGINE-DESIGN.md` | 不依赖 Task/Decision 成功；Task FAILED 不阻塞 |
| `WenDang/P5-EXTRACTOR-ARCHITECTURE-DESIGN.md` | 独立 Extractor；拒绝 Action Extractor |
| `WenDang/P5-TEST-DATASET.md` | D01～D08、R01～R08、M01～M03 |
| `WenDang/P5-GAP-REPORT.md` | 25 问 + 无 BLOCKER |
| `tests/fixtures/p5/*.json` | 机器可读 fixture |

未实现引擎，未改冻结模块，未改生产群行为，未创建生产 `DECISION_EXTRACTOR.md` / `RISK_EXTRACTOR.md`。

开放 BLOCKER：**无**。

---

## 2. 为什么 Decision 先做、Risk 后做

审计没有给出相反证据。

Decision 链短且可测：

```text
建议 → 明确确认 → Decision
```

P4 已把「建议不是 Task」测死（T08）。P5 只要在同一句子类型上补「有没有确认句」，边界清楚。

Risk 需要同时成立：

```text
当前事实 + 未来影响 + 条件/来源 +（可选）Task 上下文
```

还要挡住当前问题、建议、模糊担忧、已恢复。误报会形成企业「风险清单」。无定级标准所以 v1 连 severity 都不写，复杂度仍高于 Decision。

因此：

```text
Decision first, Risk second
不要默认下一阶段同时实现两者
```

---

## 3. 推荐拆分（必须拆开）

```text
P5-G1  Decision Engine Offline
P5-G2  Decision Side-path + Real LLM + Live
P5-G3  Risk Engine Offline
P5-G4  Risk Side-path + Real LLM + Live
```

收到「实施 P5」类指令时，默认只做 **G1**，除非指令明确点名 G2/G3/G4。

---

## 4. P5-G1：Decision Engine Offline

目标：可在 **离线 fixture** 上跑通 Decision Engine；默认不启用；不接微信；不改 P3/P4 语义；**不实现 Risk Engine**。

研究问题验收口径：

> 在已经形成的 Topic 中，离线识别确认：D01/D04 能建，D02/D03/D06/D07/D08 不建，D05 保留旧 Decision 并 supersede，CREATED_BY 是确认句不是建议句。

### Gate 0 — 实施第一天仍只读

```text
P0/P1/P2/P3/P4 仍 CLOSED / COMPLETE
TOPIC_ENGINE_ENABLED / TASK_ENGINE_ENABLED 默认 false
冻结文件未出现未授权 diff
仍无生产 decision_engine.py
fixture 仍可读
```

若有人已改 Topic/Task decision 或出现第二套 Decision 实现 → STOP，写 BLOCKER，不继续 G1。

### Gate 1 — Decision Store

新增 `decision_store.py`：

```text
data/decision_store/conversations/{conv_id}/
    decisions.json
    links.json
    processed.json
decision_engine_audit.jsonl
```

只读 TopicStore。禁止改 `topic_store.py` / `task_store.py`。不上 SQLite。

### Gate 2 — Decision Extractor Prompt + Client

新增：

```text
prompts/extractors/DECISION_EXTRACTOR.md
decision_extractor_client.py
```

正文以 G0 规则稿为准。`resolve_extractor_prompt("DECISION_EXTRACTOR")`。不改 Chat / Topic / Task Prompt。

### Gate 3 — Decision Engine

新增：

```text
decision_engine.py
tests/test_decision_engine_offline.py
```

- `DECISION_ENGINE_ENABLED = false`
- `enabled=True` 仅测试传入
- 不修改 `topic_engine.py` / `topic_sidepath.py` / `task_*.py` / `listener.py`

离线入口：`process_record(conversation, topic, message)`；测试灌 Topic Store + Decision Store。

### Gate 4 — Offline Fixture

以 `tests/fixtures/p5/decision_cases.json` 为权威。D01～D08 全过。可选 M01/M03 的 Decision 半边。

### Gate 5 — Regression

```text
P5 Decision 离线 CASE
P4 Task 离线 + sidepath
P3 Topic 离线 + sidepath
P0 / P1 / P2 单测
```

不跑真机。不打开任何生产开关。不创建 `risk_engine.py`。

---

## 5. P5-G2：Decision 旁路（需单独指令）

在 G1 COMPLETE 之后：

- 独立 `decision_sidepath.py`：bounded queue + 单 worker
- Topic 成功后 `try_enqueue_decision_after_topic`（P4-G2 同模式）
- 允许对 `topic_sidepath.py` 做 **最小追加** enqueue，不得改 Topic decision / MessageRecord / listener / Trigger
- 真实 LLM D01～D08
- 可选真机 QIYE；结束后恢复 `DECISION_ENGINE_ENABLED=false`
- 仍不实现 Risk

---

## 6. P5-G3：Risk Engine Offline（需单独指令）

在 Decision 至少完成 G1（推荐 G2 也完成）之后：

- `risk_store.py` / `RISK_EXTRACTOR.md` / `risk_extractor_client.py` / `risk_engine.py`
- 不改 Decision / Task / Topic 语义
- `RISK_ENGINE_ENABLED = false`
- 跑 `risk_cases.json` R01～R08；M01/M02 的 Risk 半边
- Task FAILED 不阻塞的隔离测试必须有
- 读 TaskStore 失败时 `candidate_tasks=[]` 仍能 NEW_RISK

---

## 7. P5-G4：Risk 旁路（需单独指令）

- `risk_sidepath.py` + Topic 成功后独立 enqueue
- 不得挂在 Task 成功回调上
- 真实 LLM + 可选真机
- 结束后关闭开关
- 不进入 Dashboard / 催办

---

## 8. G1 允许的最小修改 vs 禁止

允许新增：

```text
decision_store.py
decision_extractor_client.py
decision_engine.py
prompts/extractors/DECISION_EXTRACTOR.md
tests/test_decision_*.py
tests/fixtures/p5/ 微调期望措辞（不得放宽 D03/D02）
```

禁止：

```text
修改 Topic / Task / Chat Prompt / listener / Trigger / identity / dedupe / outbound
创建 risk_engine.py / risk_store.py / risk_sidepath.py
创建 DECISION_EXTRACTOR 以外的生产 Prompt
send_reply / wx.SendMsg
SQLite
Reminder 融合
Dashboard
```

---

## 9. 完成 G0 的状态

```text
P5-G0 STATUS = COMPLETE

Decision Engine = NOT IMPLEMENTED
Risk Engine     = NOT IMPLEMENTED

P0/P1/P2/P3/P4 frozen baseline = PRESERVED

Recommended next stage = P5-G1 Decision Engine Offline

STOP
WAIT FOR NEXT INSTRUCTION
```
