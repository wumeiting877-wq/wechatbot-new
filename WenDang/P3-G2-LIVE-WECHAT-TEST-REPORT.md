# P3-G2 真机微信测试报告

> 日期：2026-09-21  
> Gate 2 真实 LLM CASE-01～07 = **PASS**  
> 测试群：QIYE（`conv_6fbe0f455b94` / `58847495172@chatroom`）  
> Agent：`agt_38b43979a544`，`chat_prompt_name=QIYE`，`extractor_prompt_name=TOPIC_EXTRACTOR`  
> 测试号：ceshi。机器人：扶级。未扩大监听名单。

```text
Gate 1 = PASS
Gate 2 真实 LLM = PASS
P0 / P1 / P2 回归 = PASS（103 OK，含 P0 59）
真机 R1～R12 = 11 PASS / 1 NOT RUN（R9）
Live WeChat Topic Ingestion = VERIFIED
```

未自动加好友、未建群、未群发。未用 `SendMsg` 冒充群成员。  
结束后 `TOPIC_ENGINE_ENABLED` 恢复为 **false**（`runtime_control/TOPIC_ENGINE_ENABLED` + 模块默认）。

---

## CASE-R1 ～ R12

| CASE | 内容 | 结果 | 证据 |
|---|---|---|---|
| R1 | 未 @ ERP 增量同步 | **PASS** | `NEW_TOPIC` `topic_133346d8cf49`「ERP 增量同步异常」；Trigger `unauthorized`；回复 0 |
| R2 | 同 Topic 供应商编码 | **PASS** | `EXISTING_TOPIC` → 同一 ERP Topic |
| R3 | 质检员采购价格 | **PASS** | `NEW_TOPIC` `topic_d6b1f2e4ac3a`「质检员可见采购价格」；两 Topic 共存 |
| R4 | 回到 ERP 供应商编码 | **PASS** | `EXISTING_TOPIC` → 原 ERP Topic，无第三个 ERP Topic |
| R5 | 中午吃什么 | **PASS** | `UNRELATED`（rule_prefilter）；0 新 Topic；0 回复 |
| R6 | 收到 | **PASS** | `UNRELATED`（rule_prefilter）；0 新 Topic；0 回复 |
| R7 | @扶级 + Topic | **PASS** | Topic `EXISTING_TOPIC`；Chat **1** 次回复；无第二条回复 |
| R8 | 机器人自己的回复 | **PASS** | `skip_reason=OUTBOUND`；`direction_outbound`；未入库分析 |
| R9 | 重复 callback | **NOT RUN** | 真机 wxauto 未出现重复 callback（`dropped_dup=0`）。Duplicate 由 Gate 1 CASE-S5 覆盖 |
| R10 | 关闭 Topic Engine | **PASS** | 运行中写 `TOPIC_ENGINE_ENABLED=false`；业务句未入库；@ 仍 Chat 1 次；无新 Topic |
| R11 | Stop Bot | **PASS** | `STOPPED` 后 `@扶级 Stop之后还在吗？` 无 inbound 事件、无回复、Store 无新写入 |
| R12 | Extractor timeout | **PASS** | 注入 0.05s；`EXTRACTOR_TIMEOUT` 86ms；Chat 仍 1 次回复；未新建 Wi-Fi Topic；listener admit 约 15ms |

第一轮 R1～R4/R7 曾因 Bot `install_into` 未导出 `_resolver_extractor_client` 全部 `FAILED`（隔离成功，Chat 未受影响）。补上 EXPORTS 后重发通过。上表以修复后重发为准；R5/R6/R8 第一轮已 PASS。

---

## 真机 Topic 集合

| Topic id | title | status | message_count |
|---|---|---|---|
| `topic_133346d8cf49` | ERP 增量同步异常 | ACTIVE | 8 |
| `topic_d6b1f2e4ac3a` | 质检员可见采购价格 | ACTIVE | 2 |

未出现一条消息一个 Topic。未自动 RESOLVED。未进入 P4 字段。

---

## 性能观察

| 项 | 值 |
|---|---|
| Topic queue length | 未出现堆积；无 `TOPIC_QUEUE_FULL` |
| Extractor latency | 约 2.3～3.1s（成功调用） |
| Topic FAILED latency | NameError 首轮 15～158ms；R12 timeout 86ms |
| FAILED 数 | 首轮 5（已修复）+ R12 1 |
| QUEUE_FULL 数 | 0 |
| MessageRecord 数 | 13（QIYE） |
| Topic 数 | 2 |
| 未 @ listener | 约 4～15ms abort=`unauthorized`，不等待 Extractor |
| R7/R12 Chat | Extractor 旁路并行；主链仍按原 Chat 回复 1 次 |

---

## 结论

```text
Live WeChat Topic Ingestion = VERIFIED
R9 live duplicate callback = NOT RUN（S5 已覆盖）
TOPIC_ENGINE_ENABLED default = false
```
