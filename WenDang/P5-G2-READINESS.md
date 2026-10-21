# P5-G2 Readiness

> 日期：2026-09-22  
> 问题：Decision Engine 是否具备进入 **Topic 成功后独立 Side-path** 的技术条件？  
> 本文件不批准接真机。不得自动进入 P5-G2。

---

## 结论

```text
YES — 离线 Decision Engine 已具备进入独立 Side-path 的技术条件。
NO  — 现在还不能接真机、不能打开生产开关。
```

G2 可以按 P4-G2 已验证模式增加旁路投递，但必须单独指令。

---

## 检查表

| 项 | 状态 | 说明 |
|---|---|---|
| Decision Store | **READY** | 独立 JSON Store；Evidence 指向 MessageRecord；按 Conversation 隔离 |
| Decision Extractor | **READY** | 独立 Prompt + 独立 parser；不进 Chat 下拉；不改 Topic/Task Prompt |
| Decision Engine | **READY** | `process_record` 离线入口；默认 `DECISION_ENGINE_ENABLED=false` |
| Evidence | **READY** | 恰好 1 个 CREATED_BY=确认句；RELATED 可挂建议句 |
| Supersede | **READY** | 新行 + `supersedes_decision_id`；旧正文与 `RECORDED` 不变 |
| Idempotency | **READY** | 成功 Processing skip；多 Decision / supersede 重放不增生 |
| Failure Isolation | **READY** | timeout / invalid JSON / 非法 evidence / 非法 supersede / Store 失败均不脏写，不影响 Topic / Task / Chat |
| Offline Cases | **READY** | D01～D08、M01/M03 Decision 半边全部 PASS |
| Regression | **READY** | P4 50、P3 39、P0 59、P1/P2 103 保持 |

---

## G2 仍必须自己做的事

1. 独立 `decision_sidepath.py`：bounded queue + 单 worker  
2. Topic 成功且 `topic_id` 非空后 `try_enqueue_decision_after_topic`（最小追加，不得改 Topic decision）  
3. 真实 LLM 跑 D01～D08  
4. 可选真机 QIYE；结束后恢复 `DECISION_ENGINE_ENABLED=false`  
5. 仍不实现 Risk；仍不发微信；仍不写 SUPERSEDED/CANCELLED 状态

---

## 明确还没准备好的

```text
Production Decision side-path = NOT ENABLED
Real Decision LLM             = NOT VERIFIED
Live Decision extraction      = NOT VERIFIED
Risk Engine                   = NOT IMPLEMENTED
```

```text
STOP
WAIT FOR P5-G2 INSTRUCTION
```
