# P5-G3 Gate 0 当前状态核对

> 日期：2026-09-22  
> 阶段：P5-G3 实施前 READ ONLY  
> 方式：对照 P5-G0 设计文档、P5-G2 关闭报告，以及当前真实源码。Gate 0 未改业务代码。  
> 范围：Risk Engine **离线最小实现**。不接微信，不改 listener / topic_sidepath / Task / Decision，不接 Risk Side-path，不跑真实 Risk LLM。

---

## 0. 冻结基线

```text
P0 STATUS            = CLOSED
P1 STATUS            = CLOSED
P2 STATUS            = CLOSED

P3 Topic Engine      = COMPLETE
P4 Task Engine       = COMPLETE

P5-G0                = COMPLETE
P5-G1                = COMPLETE
P5-G2                = COMPLETE
P5-G3                = 本轮开始实施（Gate 0 只读核对）
```

依据：`P5-CURRENT-STATE-AUDIT.md`、`P5-G2-CLOSURE-REPORT.md`、`P5-G2-DEFERRED-ISSUES.md`、`P5-NEXT-IMPLEMENTATION-PLAN.md`，以及源码模块常量。

生产默认（模块常量，当前仓库）：

```text
TOPIC_ENGINE_ENABLED    = false     topic_engine.py
TASK_ENGINE_ENABLED     = false     task_engine.py
DECISION_ENGINE_ENABLED = false     decision_engine.py
Risk Engine             = NOT IMPLEMENTED
```

`runtime_control/` 当前无长期开启开关文件。Bot 保持 **STOPPED**（本轮不启动）。

当前已验证（P5-G2 关闭，本轮不重开真机）：

```text
Topic Side-path    = VERIFIED
Task Side-path     = VERIFIED
Decision Side-path = VERIFIED

Real Topic LLM     = VERIFIED
Real Task LLM      = VERIFIED
Real Decision LLM  = VERIFIED

Live Topic Ingestion     = VERIFIED
Live Task Extraction     = VERIFIED
Live Decision Extraction = VERIFIED

Decision Evidence  = VERIFIED
Decision Supersede = VERIFIED

Trigger  = PRESERVED
Chat     = PRESERVED
Stop Bot = PRESERVED
```

---

## 1. 文档已读

| 文件 | 状态 |
|---|---|
| `P5-CURRENT-STATE-AUDIT.md` | 已读 |
| `P5-RISK-DATA-MODEL-DESIGN.md` | 已读 |
| `P5-RISK-ENGINE-DESIGN.md` | 已读 |
| `P5-EXTRACTOR-ARCHITECTURE-DESIGN.md` | 已读 |
| `P5-TEST-DATASET.md` | 已读 |
| `P5-GAP-REPORT.md` | 已读 |
| `P5-NEXT-IMPLEMENTATION-PLAN.md` | 已读 |
| `P5-G2-CLOSURE-REPORT.md` | 已读 |
| `P5-G2-DEFERRED-ISSUES.md` | 已读 |

---

## 2. 十二项仓库核对

| # | 要求 | 真实仓库 | 结论 |
|---|---|---|---|
| 1 | 不存在 `risk_engine.py` | 根目录无此文件 | **PASS** |
| 2 | 不存在 `risk_store.py` | 根目录无此文件 | **PASS** |
| 3 | 不存在 `risk_extractor_client.py` | 根目录无此文件 | **PASS** |
| 4 | 不存在生产 `RISK_EXTRACTOR.md` | `prompts/extractors/` 仅有 TOPIC / TASK / DECISION | **PASS** |
| 5 | 不存在 `risk_sidepath.py` | 根目录无此文件 | **PASS** |
| 6 | 没有第二套完整 Risk Engine | Chat「风险」仅为自然语言；Reminder 会发微信，已排除；Task `FORBIDDEN_TASK_KEYS` 含 `risk_ids` | **PASS** |
| 7 | Topic / Task / Decision 冻结语义仍在 | `topic_*.py` / `task_*.py` / `decision_*.py` 及三套 Extractor Prompt 仍为 G2 关闭态；开关默认 false | **PASS** |
| 8 | `tests/fixtures/p5/risk_cases.json` 存在 | CASE-R01～R08 完整 | **PASS** |
| 9 | `tests/fixtures/p5/mixed_cases.json` 存在 | CASE-M01 / M02 / M03 完整 | **PASS** |
| 10 | TaskStore 能只读获得当前 Topic OPEN Task | `TaskStore.list_open_tasks(conversation_id, topic_id, limit=10)` 已存在 | **PASS** |
| 11 | 即使 TaskStore 不可用，Risk Offline 仍可继续 | 设计：读失败 → `candidate_tasks=[]` → 继续。不需要改 TaskStore。G3 Engine 将捕获该异常 | **PASS**（架构可落地） |
| 12 | 无需修改 P3 / P4 / P5 Decision 即可完成 G3 | 离线入口 `process_record(conversation, topic, message)`；只读 TopicStore / 可选只读 TaskStore | **PASS** |

---

## 3. Fixture 观察

`risk_cases.json` 已覆盖 R01～R08，**没有** RISK_UPDATE 专用 CASE。

G3 允许：

```text
补充新的测试 CASE
不得修改 R01～R08 语义
```

本轮将新增 `CASE-R09`（同一担忧更具体 → RISK_UPDATE），不改 R01～R08。

`mixed_cases.json`：G3 只验 M01 / M02 的 Risk 半边。Decision / Task 半边已冻结，不在本轮重跑引擎。

---

## 4. 冻结层测试中的「Risk 未实现」断言

两处 G1/G2 负向断言会在新增 Risk 文件后失败：

```text
tests/test_decision_engine_offline.py
  test_risk_engine_not_implemented
    → 断言 risk_engine.py / risk_store.py / risk_extractor_client.py / RISK_EXTRACTOR.md 不存在

tests/test_decision_live_adapter.py
  test_m01_decision_yes_risk_not_run
    → 断言根目录不存在 risk_engine.py
```

这 **不是** 必须修改 Decision schema / Prompt / Engine 才能做离线。  
这是 G1/G2「尚未实施 Risk」的守卫，G3 落地后必须改成：

```text
Risk Side-path 仍不存在
Decision Engine 不调用 Risk Engine
Decision 离线测试不写入 Risk Store
```

将在实施报告中记录。Decision Offline 测试数量保持 **57**（替换断言，不删用例）。

---

## 5. P5-G2 Deferred 保留

| ID | 项 | G3 处理 |
|---|---|---|
| N1 | DJ-R8 书面期望与真机模型结果不同 | **禁止**为 Risk 修改 `DECISION_EXTRACTOR`。继续 Decision Deferred |
| N2 | 偶发同一 inbound 两次 `topic_extractor`（疑似双 listener） | G3 离线，**不**改 listener / BotRuntime。记入 `P5-G3-DEFERRED-ISSUES.md`，G4 真机前核对单进程 |

---

## 6. STOP 条件核对

| # | 条件 | 结论 |
|---|---|---|
| 1 | 必须修改 Topic schema | **否** |
| 2 | 必须修改 Task schema | **否**。`Risk.task_id` 是新实体上的可空引用 |
| 3 | 必须修改 Decision schema | **否** |
| 4 | 必须修改 listener | **否**。离线直调 `process_record` |
| 5 | 必须修改 Trigger | **否** |
| 6 | 必须让 Risk 依赖 Task SUCCESS | **否**。扇出是 Topic 成功后并列 |
| 7 | 必须实现 Side-path 才能做离线 | **否**。与 P5-G1 相同 |
| 8 | 已有另一套完整 Risk Engine | **否** |
| 9 | 必须上 severity 才能通过 | **否** |
| 10 | 必须自动 RESOLVED 才能通过 | **否** |
| 11 | 必须真实 LLM 才能完成 G3 | **否**。HeuristicRiskExtractor |
| 12 | 必须接微信才能完成 G3 | **否** |
| 13 | 必须修改 P5-G2 Decision Prompt | **否** |

**不生成 `P5-G3-BLOCKER-REPORT.md`。不 STOP。**

---

## 7. Gate 0 结论

```text
P5-G3 Gate 0     = PASS
Risk Engine      = NOT IMPLEMENTED（本轮开始离线落地）
Production side-path = 禁止本轮接入
真实 Risk LLM    = 留到 P5-G4
允许继续 Gate 1  = YES
```
