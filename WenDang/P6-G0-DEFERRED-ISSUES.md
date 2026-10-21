# P6-G0 延期事项

> 日期：2026-09-22  
> P6-G0 = **COMPLETE**。本文件只记录延期，不把它们当成当前 BLOCKER。

---

## 本轮关闭

| ID | 项 | 结果 |
|---|---|---|
| B1 | keep_alive 在 Stop 后补 AddListenChat | **CLOSED** |
| B2 | start_bot 不识别孤儿 / 第二 Bot | **CLOSED** |
| B3 | Extractor 日志一律 topic_extractor | **CLOSED**（OBS） |
| N2 误当 BUG | 同文两次 Topic | **不是缺陷**。已加防误修测试 |

---

## Deferred / NON-BLOCKER

| ID | 项 | 说明 |
|---|---|---|
| DJ-R8 | Decision 书面 CASE | 继续 Deferred。禁止改 `DECISION_EXTRACTOR` 迎合案例 |
| RK-R9 | Risk 书面 CASE vs 模型 | 同 DJ-R8 类。禁止改 schema |
| Topic replay fan-out | Topic replayed SUCCESS 仍可能 fan-out Task/Decision/Risk | RCA 观察项。**不是** P6-G0 BLOCKER。本轮明确不处理。下一评估单独开指令 |
| LIVE-L2 / L5 | 真机收/停后再发一条微信 | 本窗口未发业务句。进程生命周期已证。需要时由操作员补一手测 |
| WebUI 热加载 | 运行中 15396 仍是旧 Flask 进程 | `start_bot` 409 需重启 WebUI。bot.py 新逻辑已由 Popen 加载 |
| §16 全链路字段 | trace_id / local_id / engine / stage 统一 | OBS 可选。本轮只改 purpose 标签，避免重构业务 |

---

## 明确不做（仍禁止）

| 项 | 说明 |
|---|---|
| 正文时间窗 / 同文本 hash / 模糊去重 | 会把 N2「修坏」 |
| 生产长期 ENABLE 四个 Engine | 保持 false |
| 改 Trigger / Self / Dedupe key / Outbound / Chat Prompt | 冻结 |
| 改四个 EXTRACTOR decision schema | 冻结 |
| Risk severity / 自动 RESOLVED / 自动通知 / Dashboard | 冻结 |
| Progress / Reminder 业务 / 日报周报 / RAG / 企业微信 | 冻结 |

不生成新的 P6-G0-BLOCKER-REPORT。原 `P6-G0-BLOCKER-REPORT.md` 保留为当时快照。
