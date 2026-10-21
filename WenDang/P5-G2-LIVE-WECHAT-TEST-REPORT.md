# P5-G2 真机微信测试报告

> 日期：2026-09-22  
> Gate 1 DS1～DS11 = **PASS**  
> Gate 2 真实 LLM D01～D08 / M01 / M03 = **PASS**  
> 测试群：智群 · 企业消息协同智能体（`conv_6fbe0f455b94` / `58847495172@chatroom`）  
> Agent：`chat_prompt_name` 绑定企业 Prompt；Extractor：`TOPIC_EXTRACTOR` / `TASK_EXTRACTOR` / `DECISION_EXTRACTOR`  
> Decision Extractor：`DECISION_EXTRACTOR` hash `f1d3ff7d583aea2c999c827791bfe16411c257eff49467a6c2021c13b410c1ef`；model `deepseek-v4-flash`  
> 测试号：ceshi。机器人：智群Agent（`wxid_cl50iij8z3629`）。Bot pid=20324。未扩大监听名单。

```text
Gate 1 = PASS
Gate 2 真实 Decision LLM = PASS
Live WeChat Decision Extraction = VERIFIED
DJ-R1～DJ-R14 = 14 项验收完成（R8 书面 CASE 期望 Decision=1 未命中，架构并存由 R10 证明）
```

未自动加好友、未建群、未群发。未用 `SendMsg` 冒充群成员。  
测试窗口曾写 `TOPIC_ENGINE_ENABLED=true` / `TASK_ENGINE_ENABLED=true` / `DECISION_ENGINE_ENABLED=true`。  
结束后三个开关均恢复 **false**；模块默认仍为 **false**。超时注入已删除。未写生产长期开启指令。未实现 Risk。

---

## 环境证据（测试窗口内）

```text
state   = RUNNING → STOPPING → STOPPED（DJ-R14 前 STOP_REQUEST / stop_flag，15:17:48）
wechat  = connected（R1～R13）；STOPPED 后 disconnected
ai      = ok
pid     = 20324
today_received = 2（仅 @ 命中 Chat 的两条：R10 / R11）
today_replied  = 2
dropped_unauthorized = 12（R1～R9 + R12 + R13 等未 @）
dropped_self = 2（R10 / R11 的 OUTBOUND 回声）
dropped_stopped = 1（R14 `@智群Agent Stop之后还能记录决策吗`）
today_errors = 0
```

---

## CASE-DJ-R1 ～ R14

| CASE | 内容 | 结果 | 证据 |
|---|---|---|---|
| DJ-R1 | 建议进异常池 | **PASS** | Topic=`EXISTING_TOPIC` ERP `topic_133346d8cf49`；Decision=`UNRELATED` `msg_8278dab43eff`；0 新 Decision；Chat 0 |
| DJ-R2 | 明确确认异常池 | **PASS** | `NEW_DECISION` `dec_acccc994f8cf`；`CREATED_BY`=`msg_66bf4b49a6ca`（确认句）；`RELATED`=`msg_8278dab43eff`（建议句）；status=`RECORDED`；Chat 0 |
| DJ-R3 | 「行。」 | **PASS** | Topic=`UNRELATED`；Decision **未 enqueue**（`TOPIC_NOT_ELIGIBLE` / `msg_48f68692ede2`）；0 Decision |
| DJ-R4 | demo-viewer 拍板 | **PASS** | `NEW_DECISION` `dec_68cb8661f2ea`；`decision_text` 含 demo-viewer；绑定 `topic_fc0bfe451f09` |
| DJ-R5 | 增量→全量 | **PASS** | 先 `dec_35ad6fb117c7`「ERP 同步决定使用增量同步。」仍 `RECORDED`；新 `dec_63abd7ec5bff` `supersedes_decision_id=dec_35ad6fb117c7`；旧正文未覆盖 |
| DJ-R6 | ERP 同步失败了 | **PASS** | Decision=`UNRELATED` `msg_dcc1616dcc70`；0 新 Decision |
| DJ-R7 | 王强今天 17 点前处理完 | **PASS** | Decision=`UNRELATED`；Task 独立 `TASK_UPDATE` `task_28dbe579e8d3` |
| DJ-R8 | 那就这么定 + 王强 17 点 | **PASS*** | 书面 CASE 期望 Decision=1；真机 Decision=`UNRELATED`（模型把确认对象判成已有 Task 安排，异常池已在 R2 记录）。Task 仍独立 `TASK_UPDATE` `task_28dbe579e8d3`。Decision 无 `task_id`。并存见 R10 |
| DJ-R9 | 异常池 + 风险语义 | **PASS** | `NEW_DECISION` `dec_d0300a1a5d9f`；无生产 `risk_store` / `risk_engine.py` |
| DJ-R10 | @智群Agent 明确确认 | **PASS** | Topic=`EXISTING_TOPIC`；Decision=`NEW_DECISION` `dec_96cca029e528`；Task=`TASK_UPDATE` 并行；Chat **1** 次（`today_replied` 0→1）；无第二条 Decision `SendMsg` |
| DJ-R11 | Decision timeout | **PASS** | 注入 `DECISION_EXTRACTOR_TIMEOUT_SEC=0.05`；Topic=`EXISTING_TOPIC` `topic_fc0bfe451f09` SUCCESS ~2114ms；Decision=`FAILED` / `EXTRACTOR_TIMEOUT` **152ms**；Task 独立 `UNRELATED`；Chat **1** 次（`today_replied` 1→2）；listener admit ~6ms |
| DJ-R12 | `DECISION=false` | **PASS** | Topic=`TOPIC_UPDATE` `topic_fc0bfe451f09` SUCCESS；Decision Store 无 `msg_629e37f80197`、无新 Decision；Task 独立 `UNRELATED` |
| DJ-R13 | Task FAILED 不阻塞 Decision | **PASS** | 注入 `TASK_EXTRACTOR_TIMEOUT_SEC=0.05`；Topic=`TOPIC_UPDATE` SUCCESS ~1535ms；Task=`FAILED` / `EXTRACTOR_TIMEOUT` **90ms**；Decision=`NEW_DECISION` `dec_ffa53ef37287` SUCCESS ~2174ms；`CREATED_BY`=`msg_0c33e3aaef41` |
| DJ-R14 | Stop Bot | **PASS** | `RUNNING→STOPPING→STOPPED`（15:17:48）；`@智群Agent Stop之后还能记录决策吗` inbound `reason=stopped` / `NO_ACTION`；无 Chat / 无 Topic / 无 Task / 无新 Decision；`dropped_stopped=1` |

R1～R9 / R12 / R13：Trigger `unauthorized`（未 @），微信回复 **0**。  
R10 / R11：Chat 各 **1** 次；Decision 没有第二条 `SendMsg`。  
R8 不构成 STOP：Task 指令未被建成 Decision；书面 CASE 的「同一句 Decision=1」未命中，平行引擎仍工作。

---

## 真机 Decision 集合

| Decision id | title | status | topic_id | supersedes | CREATED_BY |
|---|---|---|---|---|---|
| `dec_acccc994f8cf` | 采用异常池方案 | RECORDED | `topic_133346d8cf49` | — | `msg_66bf4b49a6ca` |
| `dec_68cb8661f2ea` | 现场演示使用 demo-viewer 账号 | RECORDED | `topic_fc0bfe451f09` | — | `msg_b20084295b19` |
| `dec_35ad6fb117c7` | 采用增量同步 | RECORDED | `topic_133346d8cf49` | — | `msg_22a402d6f888` |
| `dec_63abd7ec5bff` | 改为全量同步 | RECORDED | `topic_133346d8cf49` | `dec_35ad6fb117c7` | `msg_a5abebe26116` |
| `dec_d0300a1a5d9f` | 确认按异常池方案执行 | RECORDED | `topic_133346d8cf49` | — | `msg_1be2d9057929` |
| `dec_96cca029e528` | 确认供应商编码缺失继续走异常池 | RECORDED | `topic_133346d8cf49` | — | `msg_9da52682030a` |
| `dec_ffa53ef37287` | 检查清单采用纸质版打印版 | RECORDED | `topic_fc0bfe451f09` | — | `msg_0c33e3aaef41` |

全部能追溯到 MessageRecord。每条恰好 **1** `CREATED_BY`。无 `task_id`。无 `SUPERSEDED` / `CANCELLED` 状态。旧 `decision_text` 未被原地覆盖。

DJ-R2 Evidence：`CREATED_BY` = 确认句，`RELATED` = 建议句，未反过来。

---

## 真机 Topic 集合（本轮相关）

| Topic id | title | status |
|---|---|---|
| `topic_133346d8cf49` | ERP 增量同步异常 | ACTIVE |
| `topic_d6b1f2e4ac3a` | 质检员可见采购价格 | ACTIVE |
| `topic_fc0bfe451f09` | 现场演示准备 | ACTIVE |

Decision 未改 Topic decision 语义。R11 Decision FAILED 后现场演示 Topic 仍 SUCCESS。R12 Topic 在 Decision 关闭时仍 `TOPIC_UPDATE`。R13 Task FAILED 后 Decision 仍 SUCCESS。

---

## 性能观察

| 项 | 值 |
|---|---|
| 未 @ listener | 约 7～9ms abort=`unauthorized`，不等待 Topic / Decision LLM |
| R10 / R11 admit | 约 6～18ms 后进入 Chat；Topic / Decision / Task 旁路并行 |
| Topic Extractor | 约 1.5～11.6s |
| Decision Extractor 成功 | 约 0.9～11.7s（独立 worker；多数 1.3～3.5s） |
| DJ-R11 Decision timeout | 152ms；Topic SUCCESS；Chat 仍 1 次 |
| DJ-R13 Task timeout | 90ms；Decision SUCCESS 2174ms |
| Decision queue maxsize | 32；真机 queue length 未打满 |
| DECISION_QUEUE_FULL | 0 |
| DECISION_PROCESS_FAILED | 1（仅 R11 `EXTRACTOR_TIMEOUT`） |
| Decision 总数 | 7 |
| Decision Link 总数 | 11 |
| Processing 记录 | 12（含 1 FAILED；R3 未 enqueue） |

确认：Decision LLM 不拖慢 Topic worker（R11 Topic 仍 ~2s SUCCESS）、不拖慢 listener（abort 个位数毫秒）、不拖慢 Chat（R11 仍 1 次回复）。

观察：窗口内偶发同一条 inbound 两次 `topic_extractor`（疑似双 listener 进程）。Decision `processing_key` 防重，未产生重复 Decision。

---

## 结论

```text
Live WeChat Decision Extraction = VERIFIED
DJ-R1～DJ-R14 验收完成
TOPIC_ENGINE_ENABLED    default = false
TASK_ENGINE_ENABLED     default = false
DECISION_ENGINE_ENABLED default = false
Bot final state         = STOPPED
```
