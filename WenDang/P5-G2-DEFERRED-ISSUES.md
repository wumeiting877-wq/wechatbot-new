# P5-G2 延期事项

> 日期：2026-09-22  
> 本轮已完成：Decision Side-path 挂载、Heuristic DS1～DS11、真实 Decision LLM D01～D08 / M01 / M03、真机 DJ-R1～DJ-R14、开关恢复、P0/P1/P2/P3/P4/P5 离线回归。  
> P5-G2 = **COMPLETE**。

---

## 已关闭

| ID | 项 | 结果 |
|---|---|---|
| D1 | 真机 DJ-R1～DJ-R14 | **PASS**。ceshi 在企业群发送；架构硬门槛全部 PASS。R8 书面 CASE 期望见 N1。 |
| D2 | 真机 Decision Evidence | **PASS**。7 Decision 均恰好 1 `CREATED_BY`，可追溯 MessageRecord。R2 `CREATED_BY`=确认句、`RELATED`=建议句。 |
| D3 | 真机 supersede | **PASS**。`dec_63abd7ec5bff` 替换 `dec_35ad6fb117c7`；旧正文与 `RECORDED` 保留。 |
| D4 | 真机 Decision timeout 与 Chat 并行 | **PASS**。R11 Decision 152ms FAILED；Topic SUCCESS；Chat 1 次。 |
| D5 | 真机 Task FAILED 不阻塞 Decision | **PASS**。R13 Task 90ms FAILED；Decision `dec_ffa53ef37287` SUCCESS。 |
| D6 | 真机结束后恢复开关 | **PASS**。三个 `runtime_control` 开关 = false；超时注入已删；Bot = STOPPED。 |

---

## 非 BLOCKER 观察

| ID | 项 | 说明 |
|---|---|---|
| N1 | DJ-R8 书面 CASE vs 模型 | 书面期望「那就这么定，王强今天 17 点前处理」→ Decision=1 + Task=1。真机 Decision=`UNRELATED`（模型把确认对象判成已有 Task 安排；异常池方案已在 R2 记录）。Task 仍独立 `TASK_UPDATE`。Decision+Task 并存由 R10 证明。不构成「Task 指令被建成 Decision」。 |
| N2 | 双 `topic_extractor` | 真机窗口偶发同一 inbound 两次 Topic LLM（疑似第二 listener 进程残留）。Decision `processing_key` 防重，未写重复 Decision。 |
| N3 | `DECISION_ENGINE_DISABLED` 不落 skip audit | 与 Task 开关关闭行为一致：`try_enqueue` 直接返回。R12 以「Decision Store 无新写入 + Topic 仍 SUCCESS」判定 PASS。 |

---

## 明确不做（仍禁止）

| 项 | 说明 |
|---|---|
| 长期生产开启 Topic + Task + Decision | 需单独指令 |
| Risk Engine | NOT IMPLEMENTED。未创建 `risk_engine.py` / `risk_store.py` / `risk_extractor_client.py` / `risk_sidepath.py` / `RISK_EXTRACTOR.md` |
| 自动写 SUPERSEDED / CANCELLED 状态 | v1 只追加新行，旧行保持 RECORDED |
| Decision 发微信 | 禁止 |
| 改 listener / Trigger / Chat Prompt / Topic / Task decision schema | 冻结 |

不生成 `P5-G2-BLOCKER-REPORT.md`。
