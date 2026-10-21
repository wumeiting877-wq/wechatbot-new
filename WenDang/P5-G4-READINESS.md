# P5-G4 Readiness

> 日期：2026-09-22  
> 只回答：Risk Engine 是否具备进入 **Topic 成功后的独立 Side-path + Real LLM + Live**？  
> **不得直接接 Side-path。等待 P5-G4 指令。**

---

## 1. 就绪检查

| 能力 | G3 | 说明 |
|---|---|---|
| Risk Store | **READY** | `data/risk_store/conversations/{conv_*}/risks.json` |
| RiskMessageLink | **READY** | CREATED_BY / RELATED / UPDATED_BY |
| RiskProcessingRecord | **READY** | `message_id + risk_processing_version`；成功 skip；FAILED 可重试 |
| RISK_EXTRACTOR | **READY** | `prompts/extractors/RISK_EXTRACTOR.md` 独立，不进 Chat 下拉 |
| Risk parser | **READY** | 独立 `parse_risk_extractor_json`；生命周期 decision 拒绝 |
| Risk Engine | **READY（Offline）** | `process_record(conversation, topic, message)` |
| condition / impact | **READY** | 缺一不建 |
| RISK_UPDATE | **READY** | 不改 status；R09 PASS |
| task_id optional | **READY** | 非法则清空，不丢 Risk |
| Task failure isolation | **READY** | TaskStore 异常 → `candidate_tasks=[]`，Risk 继续 |
| Idempotency | **READY** | replay skip；多 Risk / UPDATE 不膨胀 |
| Failure Isolation | **READY** | timeout / JSON / Store 失败不脏写、不改 Topic/Task/Decision |
| R01～R08 | **READY（Heuristic）** | 全部 PASS |
| M01 / M02 Risk | **READY（Heuristic）** | 全部 PASS |
| Regression | **READY** | Decision 57 + P4 50 + P3 39 + P0 59 + P1/P2 103 |

---

## 2. G4 仍必须新做

```text
1. 独立 risk_sidepath.py
   Topic 成功且 topic_id 非空后并列 fan-out
   不得挂在 Task SUCCESS 之后
   不得改 listener / Trigger
   不得阻塞 Topic worker / Chat

2. RISK_ENGINE_ENABLED 运行时开关读取顺序
   runtime_control > 环境变量 > 模块常量
   默认仍必须 false

3. Real Risk LLM
   Heuristic 不能代替生产模型
   至少复跑 R01～R08 / M01 / M02

4. Live Risk
   真机前：单 listener / 单 Bot 进程核对（P5-G2 N2）
   不重开 Decision G2，不改 DECISION_EXTRACTOR（DJ-R8 继续 DEFERRED）

5. 结束后恢复开关，Bot STOPPED
```

---

## 3. 判定

```text
Risk Engine Offline     = COMPLETE
具备进入 G4 的离线基础  = YES
已接 Side-path          = NO
已接真实 Risk LLM       = NO
已接 Live               = NO

WAIT FOR P5-G4 INSTRUCTION
```

G4 不是「打开开关试试」。必须单独证明：Topic 成功后的独立旁路、真实模型、真机隔离、失败不回灌 Chat。
