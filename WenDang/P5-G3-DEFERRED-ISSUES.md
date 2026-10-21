# P5-G3 延期事项

> 日期：2026-09-22  
> 本轮已完成：Risk Store、RISK_EXTRACTOR、独立 parser、Risk Engine 离线、Heuristic R01～R08 / M01 / M02 / R09、Failure Isolation、Idempotency、冻结层回归。  
> P5-G3 = **COMPLETE**。  
> 禁止自动进入 P5-G4。

---

## 明确留给 G4 / 更后

| ID | 项 | 说明 |
|---|---|---|
| G4-1 | Risk Side-path | 未创建 `risk_sidepath.py`。不得在 G3 挂 listener / `topic_sidepath`。G4 按 Topic 成功后并列 fan-out，与 Task / Decision 独立 queue。 |
| G4-2 | Real Risk LLM | G3 离线主路径是 `HeuristicRiskExtractor`。`RiskExtractorClient` 已预留 `store_context=false`。G4 再用生产 `RISK_EXTRACTOR` + 真实模型跑 R01～R08 / M01 / M02。 |
| G4-3 | Live Risk | 不接真实微信。G4 真机前必须先做单 listener / 单 Bot 进程核对。 |
| F1 | Risk severity | v1 禁止。无企业定级标准。`confidence` 只表示抽取可信度。 |
| F2 | 自动 RESOLVED / MITIGATED / CLOSED | v1 只写 OPEN。已恢复陈述保持原 Risk OPEN。 |
| F3 | 风险 UI / Dashboard | 禁止本阶段。 |
| F4 | 同消息新建 Task 后回填 `Risk.task_id` | 并行旁路看不到本条新 Task。v1 允许 `task_id=""`。不要为了对齐而串行 Task → Risk。 |
| D-N1 | DJ-R8 Decision 非 BLOCKER | 书面期望 Decision+Task；真机 Decision=`UNRELATED`。**禁止**为 Risk 修改 `DECISION_EXTRACTOR`。继续留在 Decision Deferred。 |
| D-N2 | 疑似双 listener 进程 | P5-G2 偶发同一 inbound 两次 `topic_extractor`。Decision processing 幂等未产生重复数据。G3 离线不改 listener / BotRuntime。G4 真机前增加单 listener / 单 Bot 进程核对。 |

---

## 本轮已关闭

| 项 | 结果 |
|---|---|
| Risk Store + Link + Processing | PASS |
| RISK_EXTRACTOR 物理隔离 | PASS |
| Heuristic 离线红线 R01～R08 / M01 / M02 | PASS |
| 当前问题 / 建议 / 模糊担忧 / Task 指令 不建 Risk | PASS |
| 已恢复不自动 RESOLVED | PASS |
| Task FAILED / unavailable 不阻塞 Risk | PASS |
| RISK_UPDATE 不重复建 | PASS |
| Failure Isolation / Idempotency | PASS |
| 冻结层回归 | PASS |

不生成 `P5-G3-BLOCKER-REPORT.md`。
