# P5-G4 真机微信测试报告

> 日期：2026-09-22  
> Gate 0 单 Bot / 单 listener = **PASS**  
> Gate 1 RS1～RS13 = **PASS**（17）  
> Gate 2 真实 Risk LLM R01～R09 / M01 / M02 = **PASS**（12）  
> 测试群：智群 · 企业消息协同智能体（`conv_6fbe0f455b94` / `58847495172@chatroom`）  
> Agent：`chat_prompt_name` 绑定企业 Prompt；Extractor：`TOPIC_EXTRACTOR` / `TASK_EXTRACTOR` / `DECISION_EXTRACTOR` / `RISK_EXTRACTOR`  
> Risk Extractor：`RISK_EXTRACTOR`；生产落盘 hash `088d48da…`；文件 sha256 `f95d92ec…`（`resolve_extractor_prompt` 哈希口径不同，见 Deferred N4）；model `deepseek-v4-flash`  
> 测试号：ceshi。机器人：智群Agent（`wxid_cl50iij8z3629`）。Bot pid=44864。未扩大监听名单。

```text
Gate 1 = PASS
Gate 2 真实 Risk LLM = PASS
Live WeChat Risk Extraction = VERIFIED
RK-R1～RK-R17 = 17 项验收完成
（R9 书面 CASE 期望 Decision=1 未命中，Risk 仍 SUCCESS；并存由 R10/R11 证明）
```

未自动加好友、未建群、未群发。未用 `SendMsg` 冒充群成员。  
测试窗口曾写 `TOPIC_ENGINE_ENABLED=true` / `TASK_ENGINE_ENABLED=true` / `DECISION_ENGINE_ENABLED=true` / `RISK_ENGINE_ENABLED=true`。  
结束后四个开关均恢复 **false**；模块默认仍为 **false**。超时注入已删除。未写生产长期开启指令。未实现 severity / 自动 RESOLVED / Risk 通知 / Dashboard。

---

## 环境证据（测试窗口内）

```text
state   = RUNNING → STOPPING → STOPPED（RK-R17 前 webui_stop，16:15:58）
wechat  = connected（R1～R15）；STOPPED 后 disconnected
ai      = ok
pid     = 44864（wrapper 8096；WebUI 27624/15396 不是 Bot）
listener = 1（启动前已清残留 bot.py）
today_received = 3（仅 @ 命中 Chat：R11 + R12 及 D-N2 重复 @）
today_replied  = 3
dropped_unauthorized = 13（未 @ 的 Risk / Topic 旁路消息）
dropped_self = 2（R11 / R12 的 OUTBOUND 回声）
dropped_stopped = 0（R17 发送时 listener 已退出，见下）
today_errors = 0
RISK_QUEUE_FULL = 0
```

R17：`/stop_bot` 使进程 `RUNNING→STOPPING→STOPPED`（`stop_flag` / `webui_stop`），`wechat=disconnected`，无残留 `bot.py`。ceshi 发送 `@智群Agent Stop之后还有风险吗？` 之后：

- `events.jsonl` 最后一条真机 MESSAGE 仍是 R15（16:15:10 / local_id=120）
- Topic `messages.jsonl` 无该句
- Risk / Task / Decision Store 无该句
- `today_received` / `today_replied` 未再增加

进程已退出，因此没有 `reason=stopped` 的 listener 审计行。这比 stop_flag 拒绝更强：Chat / Topic / Task / Decision / Risk 全部不运行。离线 RS13 已覆盖 `reason=stopped`。

---

## CASE-RK-R1 ～ R17

| CASE | 内容 | 结果 | 证据 |
|---|---|---|---|
| RK-R1 | ERP 同步失败了 | **PASS** | Topic 正常；Risk=`UNRELATED` `msg_97141e8a1ded`；0 新 Risk；Chat 0 |
| RK-R2 | 如果今天还修不好，会影响明天现场演示 | **PASS** | `NEW_RISK` `risk_53ef714ebf19`；`CREATED_BY`=`msg_f8a7d2800a0f`；status=`OPEN`；无 severity；`task_id=""` |
| RK-R3 | 最好准备一个离线包 | **PASS** | Risk=`UNRELATED` `msg_8b9f3f6b96c3`；0 Risk |
| RK-R4 | 现场 Wi-Fi 不稳定 + 断网无法演示 | **PASS** | `NEW_RISK` `risk_dd30872bac2b`；condition 含 Wi-Fi/断网；impact 含无法演示；OPEN |
| RK-R5 | 感觉有点危险 | **PASS** | Risk=`UNRELATED` `msg_dd61d07ce5de`；0 Risk |
| RK-R6 | Wi-Fi 已经恢复了 | **PASS** | 0 NEW_RISK；0 RESOLVED / MITIGATED / CLOSED；`risk_dd30872bac2b` 仍 OPEN |
| RK-R7 | 赵凯明天准备离线包 | **PASS** | Risk=`UNRELATED` `msg_a74072f673ed`；Task 独立 `TASK_UPDATE` `task_986bc535c485` |
| RK-R8 | 如果今晚 8 点前还修不好 | **PASS** | `RISK_UPDATE` 同一条 `risk_53ef714ebf19`；`UPDATED_BY`=`msg_f07c01702881`；status 仍 OPEN |
| RK-R9 | 异常池方案执行 + 风险语义 | **PASS*** | Risk=`RISK_UPDATE` 同一条 `risk_53ef714ebf19`（`UPDATED_BY`=`msg_8d7be56cb8fa`）。Decision 本句=`UNRELATED`：G2 已有相同正文 `dec_d0300a1a5d9f`。三引擎都跑完，互不闸门 |
| RK-R10 | 王强今天 17 点前处理 + 回归风险 | **PASS** | Task=`TASK_UPDATE` `task_28dbe579e8d3`；Risk=`NEW_RISK` `risk_d036ad8b488c`；`task_id=""` |
| RK-R11 | @ + 投影调不通 / 彩排取消 | **PASS** | Topic=`TOPIC_UPDATE`；Risk=`NEW_RISK` `risk_dffd7103d1a5`；Chat **1** 次；无第二条 Risk `SendMsg` |
| RK-R12 | Risk timeout + @ | **PASS** | 注入 `RISK_EXTRACTOR_TIMEOUT_SEC=0.05`；Topic=`TOPIC_UPDATE` SUCCESS ~4095ms；Risk=`FAILED` / `EXTRACTOR_TIMEOUT` **85ms**；无脏 Risk（电源/展台未落盘）；Chat **1** 次；listener ~5–8ms |
| RK-R13 | `RISK=false` | **PASS** | Topic=`NEW_TOPIC` `topic_0c1f1b9a2835` SUCCESS；Risk Store 无 `msg_e384cb767d91`；Task / Decision 独立运行 |
| RK-R14 | Task FAILED 不阻塞 Risk | **PASS** | 注入 `TASK_EXTRACTOR_TIMEOUT_SEC=0.05`；Topic=`NEW_TOPIC` `topic_f9a48d3d708e` SUCCESS ~6089ms；Task=`FAILED` / `EXTRACTOR_TIMEOUT` **144ms**；Risk=`NEW_RISK` `risk_6e711ba8486c` SUCCESS ~1040ms |
| RK-R15 | Decision FAILED 不阻塞 Risk | **PASS** | 注入 `DECISION_EXTRACTOR_TIMEOUT_SEC=0.05`；Topic=`NEW_TOPIC` `topic_502985901024` SUCCESS ~3390ms；Decision=`FAILED` / `EXTRACTOR_TIMEOUT` **95ms**；Risk=`NEW_RISK` `risk_7961d34d5c75` SUCCESS ~1508ms |
| RK-R16 | TaskStore unavailable | **PASS** | 不砸生产 TaskStore。Gate 1 `test_rs10_taskstore_unavailable_still_creates_risk`：仍 `NEW_RISK`，`task_id=""`，`candidate_tasks_error=RuntimeError` |
| RK-R17 | Stop Bot | **PASS** | `RUNNING→STOPPING→STOPPED`（16:15:58）；`@智群Agent Stop之后还有风险吗？` 未被 ingest；无 Chat / Topic / Task / Decision / Risk |

R1～R10 / R13～R15：Trigger `unauthorized`（未 @），微信回复 **0**。  
R11 / R12：Chat 各至少 **1** 次；Risk 没有第二条 `SendMsg`。  
R9 不构成 STOP：Decision 未新建不影响 Risk SUCCESS；Task+Risk 并存见 R10，Chat+Risk 并存见 R11。

R1～R8 窗口前期 `TASK=false` / `DECISION=false`：明确 Risk 仍可写入，证明 Risk 不依赖 Task / Decision 开关。

---

## 真机 Risk 集合

| Risk id | title | status | topic_id | CREATED_BY |
|---|---|---|---|---|
| `risk_53ef714ebf19` | 今晚处理不完影响明天演示 | OPEN | `topic_133346d8cf49` | `msg_f8a7d2800a0f` |
| `risk_dd30872bac2b` | 现场 Wi-Fi 不稳定，断网会导致系统无法演示 | OPEN | `topic_fc0bfe451f09` | `msg_d87272225e13` |
| `risk_d036ad8b488c` | 王强17点前处理不完会影响今晚回归 | OPEN | `topic_133346d8cf49` | `msg_7f0dbcf481ef` |
| `risk_dffd7103d1a5` | 投影调不通会导致今晚彩排取消 | OPEN | `topic_fc0bfe451f09` | `msg_c60d3ad4650f` |
| `risk_6e711ba8486c` | 签到设备未按时到货导致开幕式延误 | OPEN | `topic_f9a48d3d708e` | `msg_d6624c6e1723` |
| `risk_7961d34d5c75` | 门票系统今晚未开启将导致明日入场排队失控 | OPEN | `topic_502985901024` | `msg_5f1d6591bd37` |

全部能追溯到 MessageRecord。无 `severity` 字段。全部 `status=OPEN`。`task_id` 均为 `""`。R6 已恢复未改 `risk_dd30872bac2b`。R8/R9 只追加 `UPDATED_BY`，未重复建。

---

## 性能观察

| 项 | 值 |
|---|---|
| 未 @ listener | 约 5～9ms abort=`unauthorized`，不等待 Topic / Risk LLM |
| R11 / R12 admit | 约 5～8ms 后进入 Chat；Topic / Task / Decision / Risk 旁路并行 |
| Topic Extractor | 约 2.7～6.1s（成功路径） |
| Risk Extractor 成功 | 约 1.0～11.6s（独立 worker） |
| RK-R12 Risk timeout | 85ms；Topic SUCCESS；Chat 仍 1 次 |
| RK-R14 Task timeout | 144ms；Risk SUCCESS 1040ms |
| RK-R15 Decision timeout | 95ms；Risk SUCCESS 1508ms |
| Risk queue maxsize | 32；真机 queue 未打满 |
| RISK_QUEUE_FULL | 0 |
| 真机 OPEN Risk 总数 | 6 |
| 无 RESOLVED / MITIGATED / CLOSED | 是 |

确认：Risk LLM 不拖慢 Topic worker（R12 Topic 仍 ~4s SUCCESS）、不拖慢 listener（abort 个位数毫秒）、不拖慢 Chat（R12 仍 1 次回复）。Task FAILED / Decision FAILED 均不闸门 Risk。

观察：R12 窗口内偶发同一 inbound 第二次 Topic Extractor（`msg_c12a74795b40`，D-N2）。两次 Risk 都是 FAILED，未产生重复 Risk。

---

## 结论

```text
Live WeChat Risk Extraction = VERIFIED
RK-R1～RK-R17 验收完成
TOPIC_ENGINE_ENABLED    default = false
TASK_ENGINE_ENABLED     default = false
DECISION_ENGINE_ENABLED default = false
RISK_ENGINE_ENABLED     default = false
Bot final state         = STOPPED
```
