# P5-G4 延期事项

> 日期：2026-09-22  
> 本轮已完成：Risk Side-path 挂载、Heuristic RS1～RS13、真实 Risk LLM R01～R09 / M01 / M02、真机 RK-R1～RK-R17、开关恢复、P0/P1/P2/P3/P4/P5 离线回归。  
> P5-G4 = **COMPLETE**。

---

## 已关闭（原 G3 留给 G4）

| ID | 项 | 结果 |
|---|---|---|
| G4-1 | Risk Side-path | **PASS**。`risk_sidepath.py` 挂在 Topic SUCCESS 之后，与 Task / Decision 并列 fan-out。未改 listener。 |
| G4-2 | Real Risk LLM | **PASS**。`RISK_EXTRACTOR` + `deepseek-v4-flash`：R01～R09 / M01 / M02 = 12 OK。 |
| G4-3 | Live Risk | **PASS**。ceshi 在企业群发送 RK-R1～R17。单 Bot pid=44864 / 单 listener。 |
| D1 | 真机 RK-R1～R17 | **PASS**。架构硬门槛全部 PASS。R9 书面 CASE 期望见 N1。 |
| D2 | 真机 Evidence | **PASS**。6 Risk 均可追溯 MessageRecord；CREATED_BY / UPDATED_BY 正确。 |
| D3 | 真机 RISK_UPDATE | **PASS**。R8/R9 更新 `risk_53ef714ebf19`，未重复建，status 仍 OPEN。 |
| D4 | 真机 Risk timeout 与 Chat 并行 | **PASS**。R12 Risk 85ms FAILED；Topic SUCCESS；Chat 1 次。 |
| D5 | 真机 Task / Decision FAILED 不阻塞 Risk | **PASS**。R14 Task 144ms FAILED；R15 Decision 95ms FAILED；Risk 均 SUCCESS。 |
| D6 | 真机结束后恢复开关 | **PASS**。四个 `runtime_control` 开关 = false；超时注入已删；Bot = STOPPED。 |

---

## 非 BLOCKER 观察

| ID | 项 | 说明 |
|---|---|---|
| N1 | RK-R9 书面 CASE vs 模型 | 书面期望「就按照异常池方案执行」附近 Decision=1。真机 Decision=`UNRELATED`（G2 已记录 `dec_d0300a1a5d9f`）。Risk 仍 `RISK_UPDATE` SUCCESS。Task+Risk 并存由 R10 证明。不构成 STOP。与 DJ-R8 同类，**禁止**为此改 `DECISION_EXTRACTOR`。 |
| N2 | 双 `topic_extractor` | 真机窗口偶发同一 inbound 两次 Topic LLM（R12 `msg_c12a74795b40`）。两次 Risk 均为 FAILED，未写脏 Risk。G4 启动前已清残留 bot.py；现象仍偶发。不改 listener。 |
| N3 | `RISK_ENGINE_DISABLED` 不落 skip audit | 与 Task / Decision 开关关闭行为一致：`try_enqueue` 直接返回。R13 以「Risk Store 无新写入 + Topic 仍 SUCCESS」判定 PASS。 |
| N4 | Extractor prompt hash 口径 | 真机 processing 记录 `088d48da…`；文件 sha256 `f95d92ec…`。`resolve_extractor_prompt` 与裸文件哈希不同。Gate 2 已记录文件 hash。不构成 FAIL。 |
| DJ-R8 | Decision 书面 CASE | 继续 Deferred / NON-BLOCKER。本轮未改 Decision 语义或 Prompt。 |

---

## 明确不做（仍禁止）

| 项 | 说明 |
|---|---|
| 长期生产开启 Topic + Task + Decision + Risk | 需单独指令 |
| severity / severity_text | v1 禁止。无企业定级标准 |
| 自动 RESOLVED / MITIGATED / CLOSED | v1 只写 OPEN。已恢复陈述保持原 Risk OPEN |
| Risk 自动通知 / 催办 / Dashboard | 禁止本阶段 |
| 同消息新建 Task 后回填 `Risk.task_id` | 并行旁路看不到本条新 Task。v1 允许 `task_id=""` |
| 改 listener / Trigger / Chat Prompt / Topic / Task / Decision decision schema | 冻结 |
| 改 DECISION_EXTRACTOR 以迎合 DJ-R8 / RK-R9 | 禁止 |

不生成 `P5-G4-BLOCKER-REPORT.md`。
