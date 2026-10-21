# P4-G2 延期事项

> 日期：2026-09-21  
> 本轮已完成：Task Side-path 挂载、Heuristic TS1～TS10、真实 Task LLM T01～T10、真机 TA-R1～TA-R13、开关恢复、P0/P1/P2/P3/P4 离线回归。  
> P4-G2 = **COMPLETE**。

---

## 已关闭（原 D1～D5）

| ID | 项 | 结果 |
|---|---|---|
| D1 | 真机 TA-R1～TA-R13 | **PASS**。ceshi 在 QIYE 发送；13 CASE 全部 PASS。 |
| D2 | 真机 Task Evidence 追溯 | **PASS**。5 Task 均有 MessageRecord 链接。 |
| D3 | 真机性能统计 | **PASS**。见 `P4-G2-LIVE-WECHAT-TEST-REPORT.md`。 |
| D4 | 真机 TA-R11 Task timeout 与 Chat 并行 | **PASS**。Task 82ms FAILED；Topic SUCCESS；Chat 1 次。 |
| D5 | 真机结束后恢复开关 | **PASS**。两个 `runtime_control` 开关 = false；超时注入已删。 |

---

## 非 BLOCKER 观察

| ID | 项 | 说明 |
|---|---|---|
| N1 | `TASK_ENGINE_DISABLED` 不落 audit.jsonl | `try_enqueue` 在开关关闭时直接返回，不走 `_skip()` 写文件。真机 R12 以「Task Store 无新写入 + Topic 仍 SUCCESS」判定 PASS。若以后要运维检索，可补一条 SKIPPED audit。 |
| N2 | 计划外消息「需要」 | 15:58 ceshi 另发，不在脚本内。`UNRELATED`，未建 Task。 |

---

## 明确不做（仍禁止）

| 项 | 说明 |
|---|---|
| 长期生产开启 Topic + Task | 需单独指令 |
| Risk Engine | NOT STARTED |
| Decision Engine | NOT STARTED |
| 自动 DONE | v1 只写 OPEN |
| Task → Reminder → 自动发微信 | 两套系统 |
| 修改 Topic multi-topic / decision schema | 冻结 |
| 改 listener / Trigger / Chat Prompt | 冻结 |

不生成 `P4-G2-BLOCKER-REPORT.md`。
