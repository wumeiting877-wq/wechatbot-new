# P6-G0 Trace Evidence

> 日期：2026-09-22  
> 样本：RK-R12 / N2。未改代码。未打生产 instrumentation。

群：`conv_6fbe0f455b94` / `58847495172@chatroom`  
Bot：`wxid_cl50iij8z3629` 智群Agent  
发送者：ceshi，`sender_id=2`，`sender_wxid=""`（群；identity 走 unconfirmed EXTERNAL，非 SELF）

---

## A. 第一 inbound（被 P5-G4 当成「第一次 Topic」）

```text
ts                  = 2026-09-22 16:10:12
local_id            = 115
platform_message_id = 58847495172@chatroom:115
create_time         = 1790064603
sort_seq            = 1790064603000
dedupe              = NEW
action              = REPLY
MessageRecord.id    = msg_36ddcb06012c
Topic               = TOPIC_UPDATE topic_fc0bfe451f09  4095ms  replayed=false
Task                = UNRELATED   1 enqueue
Decision            = UNRELATED   1 enqueue
Risk                = FAILED EXTRACTOR_TIMEOUT 85ms
Chat                = 1  (main_chat 1540ms)
```

events.jsonl：

- `INBOUND EXTERNAL NEW REPLY` pid=`…:115`
- `extractor/topic_extractor` ×3（Topic 4041ms + Task 1555ms + Decision 1666ms）——**标签全部叫 topic_extractor**
- `main/main_chat` ×1
- OUTBOUND 回复：「记下了，同样按待定风险记录…」

---

## B. 第二 inbound（P5-G4 点名的 msg_c12a74795b40）

```text
ts                  = 2026-09-22 16:10:55
local_id            = 116
platform_message_id = 58847495172@chatroom:116
create_time         = 1790064646
sort_seq            = 1790064646000
dedupe              = NEW
action              = REPLY
MessageRecord.id    = msg_c12a74795b40
Topic               = EXISTING_TOPIC topic_fc0bfe451f09  2186ms  replayed=false
Task                = UNRELATED   1 enqueue
Decision            = UNRELATED   1 enqueue
Risk                = FAILED EXTRACTOR_TIMEOUT 90ms
Chat                = 1  (main_chat 1283ms)
```

与 A 间隔：create_time **+43s**。正文逐字相同。

Chat 回复：「这条和上一条一样，我已经记过了」。  
local_id=117 为该回复回声，`OUTBOUND SELF`，Topic skip `OUTBOUND`。

---

## C. 计数表（本句可见文本，两条 inbound）

| message_id | enqueue | dequeue | extractor_success | store_processing | Task | Decision | Risk | Chat |
|---|---|---|---|---|---|---|---|---|
| msg_36ddcb06012c | 1 | 1 | 1 | 1 SUCCESS | 1 | 1 | 1 FAILED | 1 |
| msg_c12a74795b40 | 1 | 1 | 1 | 1 SUCCESS | 1 | 1 | 1 FAILED | 1 |

正常目标「一条 inbound 全 = 1」：**对每个 MessageRecord 成立。**  
对「用户眼里的一句」= 2。

---

## D. 情况判定

| 情况 | 成立？ |
|---|---|
| A 微信层两次事件 | **是**（两个 local_id） |
| B evaluate_inbound ×2 同一事件 | 否 |
| C evaluate 一次 enqueue 两次 | 否 |
| D enqueue 一次 worker 两次 | 否 |
| E worker 一次 Extractor HTTP 两次 | 本样本否（各 1 次 SUCCESS audit） |

---

## E. 旁证：不是双 listener 打同一行

同一 `platform_message_id` 第二次应 `dedupe=DUPLICATE` 且 Topic `SKIP_DUPLICATE`。  
两次都是 `NEW` + 两个 MessageRecord → 两行微信消息。

P5-G4 `today_received = 3（R11 + R12 及 D-N2 重复 @）` 与本 trace 一致。
