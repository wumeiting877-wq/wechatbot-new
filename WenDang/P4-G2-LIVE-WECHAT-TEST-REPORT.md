# P4-G2 真机微信测试报告

> 日期：2026-09-21  
> Gate 1 TS1～TS10 = **PASS**  
> Gate 2 真实 LLM T01～T10 = **PASS**  
> 测试群：QIYE（`conv_6fbe0f455b94` / `58847495172@chatroom`）  
> Agent：`agt_38b43979a544`，`chat_prompt_name=QIYE`，`extractor_prompt_name=TOPIC_EXTRACTOR`  
> Task Extractor：`TASK_EXTRACTOR`（不改 Chat Prompt / Topic Prompt）  
> 测试号：ceshi。机器人：扶级。Bot pid=10884。未扩大监听名单。

```text
Gate 1 = PASS
Gate 2 真实 LLM = PASS
Live WeChat Task Extraction = VERIFIED
TA-R1～TA-R13 = 13 PASS
```

未自动加好友、未建群、未群发。未用 `SendMsg` 冒充群成员。  
测试窗口曾写 `TOPIC_ENGINE_ENABLED=true` / `TASK_ENGINE_ENABLED=true`。  
结束后两个开关均恢复 **false**；模块默认仍为 **false**。超时注入已删除。未写生产长期开启指令。

备份：`WenDang/_p4g2_live_backup_20260921-155254`

---

## 环境证据（测试窗口内）

```text
state   = RUNNING → STOPPED（TA-R13 前 stop_flag）
wechat  = connected（R1～R12）；STOPPED 后 disconnected
ai      = ok
today_received = 2（仅 @ 命中 Chat 的两条：R10 / R11）
today_replied  = 2
dropped_unauthorized = 11（R1～R9 + 计划外「需要」+ R12）
dropped_self = 2（R10 / R11 的 OUTBOUND 回声）
dropped_stopped = 0（R13 时 listener 已停，无 inbound 事件）
```

---

## CASE-TA-R1 ～ R13

| CASE | 内容 | 结果 | 证据 |
|---|---|---|---|
| TA-R1 | 王强 16 点前空值规则 | **PASS** | Topic=`EXISTING_TOPIC` ERP `topic_133346d8cf49`；Task=`NEW_TASK` `task_1380d0300975`，assignee=王强 |
| TA-R2 | 需要再跑一次回归 | **PASS** | Task=`UNRELATED`；0 新 Task |
| TA-R3 | 李娜把权限问题修一下 | **PASS** | Topic=`TOPIC_UPDATE` `topic_d6b1f2e4ac3a`；Task=`NEW_TASK` `task_5c9949e86fe4`，李娜，due 空 |
| TA-R4 | 王强+李娜 | **PASS** | 2×`NEW_TASK`：`task_28dbe579e8d3` 王强、`task_abde3359a929` 李娜；均绑当时主 Topic ERP |
| TA-R5 | 改到 17 点 | **PASS** | `TASK_UPDATE` `task_1380d0300975`，due_text=`17点`；NEW=0 |
| TA-R6 | 收到 | **PASS** | Topic=`UNRELATED`；Task `TOPIC_NOT_ELIGIBLE`；0 新 Task |
| TA-R7 | 建议异常池 | **PASS** | Task=`UNRELATED`；0 NEW_TASK |
| TA-R8 | 按方案做 | **PASS** | `TASK_UPDATE` `task_28dbe579e8d3`；负责人仍是王强，不是 ceshi |
| TA-R9 | 空值规则已经处理完 | **PASS** | Task=`UNRELATED`；原 Task 仍 OPEN；DONE=0 |
| TA-R10 | @扶级 赵凯离线包 | **PASS** | Topic=`NEW_TOPIC` `topic_fc0bfe451f09`；Task=`NEW_TASK` `task_986bc535c485` 赵凯；Chat **1** 次；自己的回复 `OUTBOUND` |
| TA-R11 | Task Extractor timeout | **PASS** | 注入 `TASK_EXTRACTOR_TIMEOUT_SEC=0.05`；Topic=`EXISTING_TOPIC` SUCCESS；Task=`FAILED` / `EXTRACTOR_TIMEOUT` 82ms；Chat **1** 次；0 新 Task |
| TA-R12 | 关闭 Task Engine | **PASS** | `TASK_ENGINE_ENABLED=false`；Topic=`TOPIC_UPDATE` 现场演示仍写入；Task Store 无 `msg_4d19631fc41c`；Chat 0 |
| TA-R13 | Stop Bot | **PASS** | `RUNNING→STOPPING→STOPPED`（16:04:21）；`@扶级 Stop之后…` 无 inbound、无回复、Store 无新写入 |

计划外消息「需要」（15:58）`UNRELATED` / `TOPIC_NOT_ELIGIBLE`，不计入 CASE。

R1～R9 与 R12：Trigger `unauthorized`，微信回复 **0**。  
R10 / R11：Chat 各 **1** 次；Task 没有第二条 `SendMsg`。

---

## 真机 Task 集合

| Task id | title | assignee_text | due_text | status | topic_id |
|---|---|---|---|---|---|
| `task_1380d0300975` | 处理空值规则并再跑一次回归 | 王强 | 17点 | OPEN | `topic_133346d8cf49` |
| `task_5c9949e86fe4` | 修复质检员可见采购价格的权限问题 | 李娜 | （空） | OPEN | `topic_d6b1f2e4ac3a` |
| `task_28dbe579e8d3` | 处理供应商编码 | 王强 | （空） | OPEN | `topic_133346d8cf49` |
| `task_abde3359a929` | 修复权限问题 | 李娜 | （空） | OPEN | `topic_133346d8cf49` |
| `task_986bc535c485` | 准备离线包和现场检查清单 | 赵凯 | 明天12点前 | OPEN | `topic_fc0bfe451f09` |

全部能追溯到 MessageRecord（`CREATED_BY` / `UPDATED_BY`）。无 Evidence 的 Task 未出现。DONE=0。

---

## 真机 Topic 集合（本轮相关）

| Topic id | title | status |
|---|---|---|
| `topic_133346d8cf49` | ERP 增量同步异常 | ACTIVE |
| `topic_d6b1f2e4ac3a` | 质检员可见采购价格 | ACTIVE |
| `topic_fc0bfe451f09` | 现场演示准备 | ACTIVE |

Task 未改 Topic 决策语义。R11 Task FAILED 后 ERP Topic 仍 SUCCESS。R12 Topic 在 Task 关闭时仍 `TOPIC_UPDATE`。

---

## 性能观察

| 项 | 值 |
|---|---|
| 未 @ listener | 约 5.5～9ms abort=`unauthorized`，不等待 Topic / Task LLM |
| R10 / R11 admit | 约 7～16ms 后进入 Chat；Topic / Task 旁路并行 |
| Topic Extractor | 约 1.3～10.6s |
| Task Extractor 成功 | 约 1.3～3.5s（独立 worker） |
| TA-R11 Task timeout | 82ms；Topic 2190ms SUCCESS；Chat 1970ms 仍 1 次 |
| QUEUE_FULL | 0 |
| TASK_PROCESS_FAILED | 1（仅 R11 `EXTRACTOR_TIMEOUT`） |

---

## 结论

```text
Live WeChat Task Extraction = VERIFIED
TA-R1～TA-R13 = 13 PASS
TOPIC_ENGINE_ENABLED default = false
TASK_ENGINE_ENABLED  default = false
```
