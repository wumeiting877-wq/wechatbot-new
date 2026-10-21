# P5-G1 测试报告

> 日期：2026-09-22  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 权威 fixture：`tests/fixtures/p5/decision_cases.json`（未替换、未放宽 D02/D03）  
> 混合 Decision 半边：`tests/fixtures/p5/mixed_cases.json` 的 CASE-M01 / CASE-M03  
> Extractor：离线 `HeuristicDecisionExtractor`（G1 允许；真实模型联调不是 G1 必须项）

```text
.\.venv\Scripts\python.exe -m unittest ^
  tests.test_decision_store ^
  tests.test_decision_extractor ^
  tests.test_decision_engine_offline
```

结果：**57 tests, OK**

---

## CASE-D01～D08

| CASE | 结果 | 观察 |
|---|---|---|
| **CASE-D01** | **PASS** | 上文建议 + 当前「可以，就按照异常池方案执行。」→ 1 个 `RECORDED` Decision；`CREATED_BY` = 当前确认句；RELATED 含建议句；建议句不是 CREATED_BY；`supersedes_decision_id=null`；`decision_text` 含异常池 |
| **CASE-D02** | **PASS** | 「我建议供应商编码缺失的数据先进异常池。」→ **0 Decision**，`UNRELATED` |
| **CASE-D03** | **PASS** | 上文有完整方案，当前「行。」→ **0 Decision**；规则预筛，未调 Extractor |
| **CASE-D04** | **PASS** | 「那就这么定，现场演示使用 demo-viewer 账号。」→ 1 Decision，`status=RECORDED`，`decision_text` 含 demo-viewer |
| **CASE-D05** | **PASS** | 旧 `dec_demo_incr` 正文「决定使用增量同步。」保持原样；旧 `status` 仍 `RECORDED`；新 Decision=1；`supersedes_decision_id=dec_demo_incr`；新正文含全量同步；未原地覆盖 |
| **CASE-D06** | **PASS** | 「ERP 同步失败了。」→ **0 Decision** |
| **CASE-D07** | **PASS** | 「王强今天 17 点前处理完。」Task 指令 → **0 Decision** |
| **CASE-D08** | **PASS** | 「收到」→ **0 Decision**；允许规则预筛，未调 Extractor |

---

## 混合 CASE Decision 半边

| CASE | 结果 | 观察 |
|---|---|---|
| **M01 Decision** | **PASS** | 「就按照异常池方案执行，如果今晚处理不完，会影响明天演示。」→ Decision=YES；句中 Risk 内容未拒绝 Decision；本轮不跑 Risk Engine |
| **M03 Decision** | **PASS** | 预置异常池建议 + 「那就这么定，王强今天 17 点前处理。」→ Decision=YES；无 `task_id` 字段；不要求本 CASE 跑 Task Engine |

---

## Failure Injection

| 注入 | 结果 | 观察 |
|---|---|---|
| Extractor timeout | **PASS** | `FAILED` / `EXTRACTOR_TIMEOUT`；无脏 Decision；Topic / Task fixture 不变 |
| Extractor exception | **PASS** | `FAILED`；Topic / Task 不变 |
| invalid JSON | **PASS** | `JSON_PARSE_ERROR`；无 Decision |
| empty output | **PASS** | `EXTRACTOR_EMPTY`；无 Decision |
| invalid supersedes_decision_id | **PASS** | `INVALID_SUPERSEDES_DECISION_ID`；不写编造的 `dec_*` |
| invalid evidence id | **PASS** | `INVALID_EVIDENCE_ID`；不写 Decision |
| 第二条 INVALID 不留半套 | **PASS** | 先合法 NEW_DECISION、后非法 supersede → 整单失败，0 Decision |
| Prompt missing | **PASS** | `EXTRACTOR_PROMPT_NOT_FOUND`；不调 LLM |
| Prompt empty | **PASS** | `EXTRACTOR_PROMPT_EMPTY`；不调 LLM |
| Store write failure | **PASS** | `STORE_WRITE_FAILURE`；无脏 Decision；Topic 不变 |
| 进程不崩 | **PASS** | `process_record` 不向调用方抛异常，`isolated=True` |
| FAILED 可重试 | **PASS** | 同 version 重试后 `NEW_DECISION` 成功 |

无 Topic Evidence 的 Message → `TOPIC_EVIDENCE_MISSING`，不猜 Topic。**PASS**。

---

## Idempotency

| 场景 | 结果 |
|---|---|
| 同 Message 重放 → Decision 不重复 | **PASS** |
| 同 Message 多 Decision 重放 → 数量不增加 | **PASS** |
| supersede 消息重放 → 不再创建第二条 supersede Decision | **PASS** |
| 成功 Processing → skip | **PASS** |
| FAILED → 可重试成功 | **PASS** |

Store 层另证：成功 Processing 重放保留原记录；FAILED 可覆盖为成功。

---

## Prompt Isolation

| 项 | 结果 |
|---|---|
| `DECISION_EXTRACTOR.md` 独立存在 | **PASS** |
| 不会进入 Chat Prompt 下拉（`list_prompt_names` 无 DECISION_EXTRACTOR） | **PASS** |
| QIYE / 企业_1 未改，无 Decision schema | **PASS** |
| TOPIC_EXTRACTOR 未改 | **PASS** |
| TASK_EXTRACTOR 未改 | **PASS** |
| `DEFAULT_EXTRACTOR_PROMPT_NAME = TOPIC_EXTRACTOR` | **PASS** |
| parser 独立；剥离 `status` / `task_id` / `severity`；`DECISION_UPDATE`/`SUPERSEDED`/`CANCELLED` 整单非法 | **PASS** |

---

## Source Send Guard

| 项 | 结果 |
|---|---|
| `decision_store.py` / `decision_engine.py` / `decision_extractor_client.py` 无 `send_reply(` / `wx.SendMsg(` / `SendMsg(` / `from message.listener` | **PASS** |
| Decision Engine 只写 Store + Audit | **PASS** |
| `DECISION_ENGINE_ENABLED` 默认 false | **PASS** |
| 未实现 `risk_engine.py` / `risk_store.py` / `RISK_EXTRACTOR.md` | **PASS** |

预筛补充：「可以，就按照异常池方案执行。」**不是**纯 ack，进入 Extractor。**PASS**。

---

## 关闭门槛对照

```text
[PASS] Decision Store
[PASS] DecisionMessageLink
[PASS] DecisionProcessingRecord
[PASS] DECISION_EXTRACTOR 独立
[PASS] Decision parser 独立
[PASS] Decision Engine Offline
[PASS] D01
[PASS] D02
[PASS] D03
[PASS] D04
[PASS] D05
[PASS] D06
[PASS] D07
[PASS] D08
[PASS] M01 Decision
[PASS] M03 Decision
[PASS] 建议不建 Decision
[PASS] 行。 不建 Decision
[PASS] Task 指令不建 Decision
[PASS] 当前问题不建 Decision
[PASS] 改方案不会覆盖旧 Decision
[PASS] CREATED_BY 是确认句
[PASS] Failure Injection
[PASS] Idempotency
[PASS] Decision 不发微信
[PASS] DECISION_ENGINE_ENABLED 默认 false
[PASS] 未接 listener
[PASS] 未改 Topic / Task
[PASS] 未实现 Risk
```

P3 / P4 / P0 / P1/P2 回归见 `P5-G1-REGRESSION-REPORT.md`。
