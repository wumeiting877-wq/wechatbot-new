# Duplicate Topic Extractor RCA

> 样本：P5-G4 真机 RK-R12 / N2，群 `conv_6fbe0f455b94`  
> 证据：`runtime_control/events.jsonl`、`data/topic_store`、`data/risk_store`、`data/task_store`、`data/decision_store`  
> 本轮 **未改代码**。

---

## 1. 现象

P5-G4 记录：

```text
同一 inbound 偶发两次 Topic Extractor（R12 msg_c12a74795b40）
两次 Risk 均 FAILED，未写脏 Risk
疑似双 listener
```

Chat 自己在第二次回复里写了「这条和上一条一样，我已经记过了」。

---

## 2. 复现条件

真机 RUNNING，四个 Engine 临时 true，群内发送带 @ 的同一句风险陈述。  
本轮离线 mock **不会**复现「同一 MessageRecord 两次 Extractor」，因为根因不在 worker。

若测试号在约 40s 内把 **同一句**再发一次（或微信落了第二行），即可稳定看到两次 Topic / Task / Decision / Chat。

---

## 3. Trace

| t (本地) | 层 | 关键字段 | 结果 |
|---|---|---|---|
| 16:10:12 | WeChat / listener | local_id=**115** pid=`58847495172@chatroom:115` create_time=1790064603 | `INBOUND EXTERNAL NEW REPLY` |
| 16:10:12 | Topic enqueue | 同内容 | `TOPIC_SIDE_PATH_ENQUEUED` |
| 16:10:17 | Topic Extractor | `msg_36ddcb06012c` latency **4095ms** | `TOPIC_UPDATE` SUCCESS replayed=false |
| 16:10:17 | Risk | 同 message_id，timeout 0.05s | FAILED 85ms |
| 16:10:18 | Task / Decision | 同 message_id | UNRELATED SUCCESS |
| 16:10:21 | Chat | 1 次 main_chat | 发出回复 |
| 16:10:55 | WeChat / listener | local_id=**116** pid=`…:116` create_time=1790064646 | `INBOUND EXTERNAL NEW REPLY` |
| 16:10:55 | Topic enqueue | 同 **文本**，新 id | `TOPIC_SIDE_PATH_ENQUEUED` |
| 16:10:57 | Topic Extractor | `msg_c12a74795b40` latency **2186ms** | `EXISTING_TOPIC` SUCCESS replayed=false |
| 16:10:57 | Risk | 同 message_id | FAILED 90ms |
| 16:10:58–59 | Task / Decision | 同 message_id | UNRELATED SUCCESS |
| 16:11:04 | Chat | 第 2 次 main_chat | 「和上一条一样」 |
| 16:11:18 | Outbound echo | local_id=117 | `OUTBOUND SELF` skip Topic |

两次 WeChat `create_time` 相差 **43 秒**。local_id 连续 115→116（114/117 为机器人回复占用）。这不是 1s 轮询对同一行的双打。

---

## 4. 第一入口

```text
message_listener
  ← wechatauto Listener callback（chatroom 58847495172@chatroom）
  local_id=115
  evaluate_inbound → NEW
  try_enqueue_topic_sidepath → ENQUEUED
```

MessageRecord：`msg_36ddcb06012c`  
`platform_message_id`：`58847495172@chatroom:115`

---

## 5. 第二入口

```text
同一个 message_listener 函数
  同 Listener，约 43s 后第二次 callback
  local_id=116
  evaluate_inbound → NEW   （不同 platform_message_id，P0 不去重）
  try_enqueue_topic_sidepath → ENQUEUED
```

MessageRecord：`msg_c12a74795b40`  
`platform_message_id`：`58847495172@chatroom:116`

**不是** `evaluate_inbound` 一次、enqueue 两次。  
**不是** enqueue 一次、worker process 两次。  
**不是** worker 一次、Extractor HTTP 两次（本条各 1 次 SUCCESS audit）。

---

## 6. 是否相同 MessageRecord

否。

`messages.jsonl` 两行，id / platform_message_id / local_id / create_time 均不同。正文相同。

---

## 7. 是否相同 listener

是。同一 Bot 进程、同一 DB Listener 线程、两次合法新行。  
`dedupe=NEW` 两次，排除「同一 pid 被两个 callback 打」：那种第二下应是 `DUPLICATE`。

---

## 8. 是否相同 process/thread

同一 process（P5-G4 pid=44864）。  
Listener 两次投递；Topic 单 worker **串行**处理两条 queue 项。

---

## 9. Root Cause

**层级：情况 A（微信层两条事件），叠加 P0 按 platform_message_id 去重。**

```text
微信 SQLite 写入 local_id=115
   与
微信 SQLite 写入 local_id=116（同正文，+43s）
```

P0 `DedupeIndex` key = `platform_message_id`（此处即 `chat_wxid:local_id`），TTL 120s。  
两条 key 不同 → 两次 NEW → 两次 Topic enqueue → 两次 Extractor → 两次 fan-out。

被误判为「双 listener / 同一 inbound」的原因：

1. 正文相同，Topic 第二次还写了「重复表述」。
2. `get_extractor_response` 把 Topic/Task/Decision/Risk 的成功日志都记成 `extractor/topic_extractor`。一句 inbound 在 events 里会看到 **3 条** `topic_extractor` 成功（Risk timeout 无成功行）。
3. 先前 Stop 残留进程是真实风险，但 **本样本时间线对不上双进程**：双进程同一 local_id 会撞 processing_key，不会生成两个 MessageRecord id。

最可能的业务解释：测试号把 R12 又发了一遍，或微信 4.x 把同一句话落成第二行。43s 间隔 + 新 local_id **不像** poll 双击同一行。

---

## 10. 影响范围

| 面 | 本样本 |
|---|---|
| Topic | 2 次 Extractor，2 条 processing SUCCESS，**未**重复建 Topic |
| Task | 2 次 enqueue / LLM，均为 UNRELATED，无脏 Task |
| Decision | 2 次 enqueue / LLM，均为 UNRELATED，无脏 Decision |
| Risk | 2 次 enqueue，均 FAILED timeout，无脏 Risk |
| Chat | 2 次 main_chat（today_replied 含 D-N2） |
| Store | 2 个 MessageRecord；Topic/Link 按设计更新/关联 |
| LLM Cost | 相对「一句」多付 1×(Topic+Task+Decision+Chat) + 1×Risk timeout |

---

## 11. 为什么现有测试没有发现

`test_topic_sidepath.test_s5_duplicate_no_enqueue` 用 **相同** `platform_message_id`。  
P0 `test_two_senders_same_text_not_deduped` 明确：**同文不同 pid 不去重**。  
没有「同会话同正文不同 local_id」的旁路计数断言。  
离线 Heuristic 不打真实 Extractor 日志，也看不到 `topic_extractor` 标签混淆。

---

## 12. 最小修复点

**本现象不要求改 Topic/Task/Decision/Risk decision schema，也不要求改 listener。**

若下一 Gate 要收口「用户可见的一句」：

1. **不要**上全局锁 / sleep / 粗暴正文时间窗（P6-G0 禁止项）。
2. 先加 trace：把 `local_id` + `platform_message_id` + `MessageRecord.id` 打在同一行。
3. 修正 `get_extractor_response` 的 purpose 标签（否则永远像「多次 Topic LLM」）。
4. 仅当产品确认「同会话同正文短间隔算重复发送」时，才在 **P0 之后、Topic 之前** 讨论策略；那是产品决策，不是 N2 的 worker 修复。

独立生命周期问题（Stop 后 keep_alive 可能再 `AddListenChat`）见 BLOCKER，**不是 N2 根因**。

---

## 13. 禁止修改项

```text
TOPIC_EXTRACTOR / TASK_EXTRACTOR / DECISION_EXTRACTOR / RISK_EXTRACTOR 决策语义
Chat Prompt / Topic Prompt / Task Prompt / Decision Prompt / Risk Prompt
P0 Dedupe 键语义（未经产品指令不得改成正文去重）
Trigger / Self / Outbound
DJ-R8 / RK-R9
新增 queue / worker
```

---

## 14. 建议新增测试

1. 同 `platform_message_id` 两次 listener：enqueue=1，extractor=1（已有 S5，保留）。
2. 同正文、不同 `local_id`：当前行为应是 enqueue=2；用计数器固化，避免被「修」成静默吞掉。
3. Topic replayed SUCCESS **不得**再次 fan-out（现有代码会 fan-out；本样本未走 replay）。
4. 日志：Task/Decision/Risk 成功不得写入 `purpose=topic_extractor`。

---

## 15. 是否允许进入 P6-G1

**否。**

N2 本身已解释，不是 Extractor 重入 BUG。  
P6-G0 仍 **BLOCKED**：Stop/Start 不能证明「Restart 不产生双 listener」（`keep_alive` + 残留进程 + `start_bot` 不扫孤儿）。见 `P6-G0-BLOCKER-REPORT.md`。

等待指令后再进入修复 Gate。
