# P5 Decision / Risk Engine 现状审计

> 日期：2026-09-22  
> 项目：wechatbot-new  
> 阶段：**P5-G0**（READ ONLY 审计 + 数据模型 + Extractor / Engine 架构 + 离线测试基线）  
> 方式：只读扫描。本轮未实现生产 Decision Engine / Risk Engine，未接微信，未改 Topic / Task / listener / Trigger。  
> 对照：`P0-CLOSURE-REPORT.md`、`P1-P2-CLOSURE-REPORT.md`、`P3-G2-CLOSURE-REPORT.md`、`P4-G2-CLOSURE-REPORT.md`，以及当前源码。

---

## 0. 冻结基线确认

已完整读取 P0 / P1 / P2 / P3 / P4 关闭报告，并对照当前源码。

```text
P0 STATUS            = CLOSED
P1 STATUS            = CLOSED
P2 STATUS            = CLOSED

P3 Topic Engine      = COMPLETE
P4 Task Engine       = COMPLETE

P5 Decision Engine   = NOT STARTED
P5 Risk Engine       = NOT STARTED
```

P3 / P4 已证明：

```text
Topic Side-path              = VERIFIED
Task Side-path               = VERIFIED
Real Topic LLM               = VERIFIED
Real Task LLM                = VERIFIED
Live Topic Ingestion         = VERIFIED
Live Task Extraction         = VERIFIED
Topic Evidence               = VERIFIED
Task Evidence                = VERIFIED

Trigger                      = PRESERVED
Chat                         = PRESERVED
Stop Bot                     = PRESERVED
```

生产默认（源码模块常量）：

```text
TOPIC_ENGINE_ENABLED = false     topic_engine.py
TASK_ENGINE_ENABLED  = false     task_engine.py
```

旁路开关读取顺序（P3 / P4 已落地，本轮不改）：

```text
runtime_control/{TOPIC|TASK}_ENGINE_ENABLED
  > 环境变量
  > 模块常量
```

本轮遵守：

- 未修改 `message/identity.py`、`dedupe.py`、`outbound.py`、`trigger.py`、`reply_format.py`、`listener.py`、`bot_runtime.py`
- 未修改 `topic_store.py`、`topic_engine.py`、`topic_sidepath.py`、`topic_extractor_client.py`、`prompts/extractors/TOPIC_EXTRACTOR.md`
- 未修改 `task_store.py`、`task_engine.py`、`task_sidepath.py`、`task_extractor_client.py`、`prompts/extractors/TASK_EXTRACTOR.md`
- 未修改 `prompts/QIYE.md`、`prompts/企业_1.md`
- 未创建 `decision_engine.py` / `risk_engine.py` / `decision_store.py` / `risk_store.py` / `decision_sidepath.py` / `risk_sidepath.py`
- 未进入 Reminder / 自动催办 / Dashboard / 真机微信

---

## 1. 当前真实对象关系（已落地）

```text
Conversation.id  (conv_*)
    ├── AgentConfig.id  (agt_*)
    ├── Topic Store     data/topic_store/conversations/{conv_id}/
    │       messages.jsonl          MessageRecord
    │       topics.json             Topic[]
    │       links.json              TopicMessageLink[]
    │       processed.json          TopicProcessingRecord
    └── Task Store      data/task_store/conversations/{conv_id}/
            tasks.json              Task[]
            links.json              TaskMessageLink[]
            processed.json          TaskProcessingRecord
```

运行时主链（P0，冻结）：

```text
微信本地库
  → message.listener.message_listener
  → inbound_from_wx_message → InboundMessage
  → BotRuntime.evaluate_inbound
  → try_enqueue_topic_sidepath(inbound, verdict)   # 旁路，不改 verdict
  → REPLY → Chat；NO_ACTION → 结束
```

已验证旁路（默认关）：

```text
Topic Side-path worker
  → TopicEngine.process_inbound
  → MessageRecord + Topic + TopicMessageLink
  → Topic 成功且 topic_id 非空
        ↓ _maybe_enqueue_task（topic_sidepath.py，P4-G2 已加）
  Task Side-path worker
  → TaskEngine.process_record
  → Task + TaskMessageLink
  → 禁止 send_reply / wx.SendMsg
  → 失败不影响 Topic / Chat / Trigger
```

**没有** Decision 对象，**没有** Risk 对象，**没有** Decision / Risk 旁路。

---

## 2. Gate 0 十五问

### 1. 当前是否已有真正 Decision 实体？

**否。**

仓库检索：

```text
decision_engine.py              不存在
decision_store.py               不存在
decision_sidepath.py            不存在
decision_extractor_client.py    不存在
DECISION_EXTRACTOR.md           不存在
data/decision_store/            不存在
DecisionMessageLink             不存在
DecisionProcessingRecord        不存在
```

`P4-G1-DEFERRED-ISSUES.md` D9、`P4-G2-DEFERRED-ISSUES.md`、`P4-G2-CLOSURE-REPORT.md`、`CURRENT-PROJECT-INTRODUCTION.md` 均写：**Decision Engine = NOT STARTED**。

源码里出现的 `decision` 全部是 **Extractor 枚举字段**（`NEW_TOPIC` / `NEW_TASK` / `UNRELATED`），不是「大家最终确认了什么」这一业务实体。

### 2. 当前是否已有真正 Risk 实体？

**否。**

```text
risk_engine.py                  不存在
risk_store.py                   不存在
risk_sidepath.py                不存在
risk_extractor_client.py        不存在
RISK_EXTRACTOR.md               不存在
data/risk_store/                不存在
RiskMessageLink                 不存在
RiskProcessingRecord            不存在
```

`P4-G1-DEFERRED-ISSUES.md` D8 与 P4-G2 关闭报告均为 **Risk Engine = NOT STARTED**。

`task_store.FORBIDDEN_TASK_KEYS` 含 `risk_ids` / `decision_ids`：这是 **禁止写入 Task 的占位键**，证明 P4 刻意排除这两种实体，不是已实现的外键。

### 3. Chat Prompt 中出现的「结论 / 风险」是否只是自然语言？

**是。只是 Chat 人设口吻，不是 Engine。**

| 文件 | 原文 | 判定 |
|---|---|---|
| `prompts/QIYE.md` | 「整理任务、风险、结论和项目进展」 | 对用户说话的职责声明。无 JSON schema，不落盘 |
| `prompts/企业_1.md` | 「决策支持」「风险防范」「风险控制与应急预案」「结论先行」 | 顾问人格。无 Store / Evidence / Processing |
| `prompts/AI.md` | 「先推导后结论」 | 通用助手措辞 |

真正 Engine 至少需要：结构化 Store、Evidence、Processing、独立 Extractor、失败隔离。Chat Prompt 一项都没有。

P3 审计已记录：真机 `chat_contexts.json` 里模型曾在 display_reply 里手写 JSON，那是 Chat 幻觉，不是 Extractor。P5 不得把这种现象当成 Decision / Risk 已存在。

### 4. Reminder / Task / Topic 中是否存在容易被误认为 Decision / Risk 的旧结构？

**有表象，全部必须排除。**

| 表象 | 实际是什么 | 能否当 Decision / Risk |
|---|---|---|
| QIYE / 企业_1 「结论 / 风险 / 决策」 | Chat 文案 | **否** |
| Topic / Task 的 `decision` 字段 | Extractor 动作枚举 | **否**。语义是 NEW_TOPIC / NEW_TASK，不是企业决议 |
| `TaskProcessingRecord.decision_summary` | 本条消息 Task 抽取结果拼接 | **否** |
| Topic `summary` | 当前对讨论的理解，可变 | **否**。讨论摘要 ≠ 已确认方案 |
| Task `title` / `description` | 谁需要做什么 | **否** |
| `FORBIDDEN_TASK_KEYS.risk_ids / decision_ids` | 丢弃键 | **否**。明确禁止落盘 |
| `reminders.py` + `recurring_reminders.json` | 个人到点提醒，会发微信 | **否**。无 Topic，无 Evidence，会发微信 |
| Topic 正文里的「如果…会影响…」 | 已作为 **Topic 讨论内容** 入库 | **否**。P3 只回答「在讨论什么」，不抽 Risk |
| Task CASE-T08「我建议…先进异常池」 | P4 正确判 **不是 Task** | **否**。建议被丢掉了，也 **没有** 变成 Decision。这正是 P5 要补的缺口 |

### 5. 当前 MessageRecord 能否支撑 Decision Evidence？

**足以支撑 v1 Evidence。** 不需要改 MessageRecord schema，不需要改 `InboundMessage`。

`topic_store._normalize_message` 已有：

```text
id, conversation_id, platform_message_id
sender_id, sender_wxid, sender_name
content, message_type, created_at
direction, reply_to_message_id
raw_reference { chat_name, chat_wxid, local_id, create_time, quote_excerpt }
ingested_at, schema_version
```

Decision 需要的：

| 需求 | 来源 | 判定 |
|---|---|---|
| 哪一句是确认句 | `MessageRecord.id` + `content` + Link | 足够 |
| 哪一句是建议句 | 同上，经 Topic 窗口取出 | 足够 |
| 谁说的 | `sender_name` | 足够表达发言者；**不是** 决策人主数据 |
| 会话 | `conversation_id` | 足够 |
| 引用回复链 | `reply_to_message_id` | 真机常空；v1 不依赖，靠 `recent_topic_messages` |

不复制完整正文到未来 Decision Store。只存 `message_id`。

### 6. 当前 MessageRecord 能否支撑 Risk Evidence？

**足以支撑 v1 Evidence。** 同样只读 Topic Store。

Risk 需要「条件 / 原因」和「未来不利结果」都来自消息原文。`content` 足够承载；不需要新的消息字段。  
`created_at` 格式在真机可能不是严格 ISO——v1 不据此给风险定级，也不解析绝对时间。

### 7. TopicMessageLink 能否提供主题内上下文？

**能。且必须用它，禁止用全群历史。**

已实现：

```text
TopicStore.links_for_topic(conversation_id, topic_id)
TopicStore.get_message / list_messages
```

P4 已证明可组装 `recent_topic_messages ≤ 12`：只取 **本 Topic 已链接** 的 MessageRecord，按 `created_at` 排序。  
Decision / Risk Extractor 应复用同一窗口策略，**不要**改 `topic_store.py`。

P3 v1 仍是 1 Message → 1 主 Topic。双主题消息会把次主题漏掉——这是 LIMITATION，P5 不修 P3。

### 8. TaskMessageLink 能否辅助 Risk 判断？

**可以只读辅助，不能作为 Risk 运行闸门。**

`TaskStore.list_open_tasks(conversation_id, topic_id, limit=10)` 已存在。Risk Extractor **可以**把当前 Topic 的 OPEN Task 作为 `candidate_tasks`，用于可选填写 `task_id`。

`TaskMessageLink` 本身不必塞进 Risk 输入窗口。Task 行上的 `title` / `assignee_text` / `due_text` / `created_msg_id` 已够 v1 对齐。

约束：

- `task_id` 可空
- Task Engine FAILED / DISABLED / 尚未跑完 → `candidate_tasks=[]`，Risk **仍应运行**
- 同一条消息上新创建的 Task，v1 **看不到**（并行旁路，见引擎设计 LIMITATION）
- 禁止为了给 Risk 喂 Task 而改 Task decision schema 或让 Risk 等待 Task 成功

### 9. 当前是否已有 decision / risk prompt？

**无独立 Extractor Prompt。**

`prompts/extractors/` 现有且仅有：

```text
TOPIC_EXTRACTOR.md
TASK_EXTRACTOR.md
```

`agent_store.resolve_extractor_prompt(name)` 按 `prompts/extractors/{name}.md` 读取，**不必改** `agent_store.py` 即可新增 `DECISION_EXTRACTOR` / `RISK_EXTRACTOR`。  
`list_prompt_names()` 不递归子目录，放在 `extractors/` 不会进入 Chat 下拉框。

禁止把 schema 写进 `QIYE.md` / `企业_1.md` / 已有两个 Extractor。

注意：`topic_extractor_client.STRIP_KEYS` 含 `decisions` / `risks`。Decision / Risk 必须有 **自己的 parser**，不得复用 Topic 的 `parse_extractor_json`。

### 10. 当前是否已有 decision / risk store？

**无。**

现有业务 JSON Store：

```text
data/topic_store/     P3
data/task_store/      P4
conversation_store    P1（会话配置，不是事件）
```

没有 `data/decision_store/`、`data/risk_store/`、`data/action_store/`。没有业务 SQLite（`wxbot.py` 的 sqlite3 只读微信客户端库）。

### 11. 当前是否已有 decision / risk processing record？

**无。**

已有且必须 **隔离** 的幂等层：

| 记录 | 职责 | 能否复用给 P5 |
|---|---|---|
| P0 `DedupeIndex` | 微信重复回调，内存 TTL | **否** |
| `TopicProcessingRecord` | 该消息 Topic 是否处理过 | **否**。成功含 UNRELATED，会误跳过 Decision |
| `TaskProcessingRecord` | 该消息 Task 是否处理过 | **否**。Task FAILED 不得变成 Risk 已处理 |

P5 必须新建 `DecisionProcessingRecord` 与 `RiskProcessingRecord`。

### 12. 当前是否有状态字段可能和 Decision / Risk 混淆？

**有命名碰撞，设计时必须分开。**

| 字段 | 含义 | 不是 |
|---|---|---|
| Topic/Task `decision` | Extractor 动作：NEW_TOPIC / NEW_TASK | 企业决议实体 |
| Topic `status` | v1 只写 `ACTIVE` | Decision `RECORDED` |
| Task `status` | v1 只写 `OPEN` | Risk `OPEN`（同名不同实体） |
| Trigger `REPLY` / `NO_ACTION` | 是否回复微信 | 与 Decision / Risk 无关 |
| Chat「结论」 | 自然语言 | 不落盘 |

P5 实体状态推荐：

```text
Decision.status  v1 只写 RECORDED
Risk.status      v1 只写 OPEN
```

Extractor JSON 仍可用键名 `decision`（与 P3/P4 一致），但文档与审计必须写 **extractor decision** vs **Decision 实体**。

### 13. 是否必须修改 P3 / P4 才能实现 P5？

**不必修改 P3 / P4 数据模型、Topic decision、Task decision、listener、Trigger。**

P5 只读：

- `TopicStore.get_topic` / `get_message` / `links_for_topic` / `list_messages`
- `TaskStore.list_open_tasks`（Risk 可选上下文）

写入全部进入新 Store。

G1 / G3（离线）连 `topic_sidepath.py` 都不改，测试直接 `process_record`。  
G2 / G4（旁路）可按 P4-G2 已验证模式，在 Topic 成功之后 **追加** `try_enqueue_decision_after_topic` / `try_enqueue_risk_after_topic`。这是旁路投递，不是改 Topic 分类，**不是本轮 BLOCKER**。本轮禁止改这些文件。

### 14. 是否已经存在第二套类似能力？

**不存在完整第二套 Decision / Risk Engine。**

容易被当成第二套、必须永久排除：

1. Chat Prompt 口吻  
2. Reminder（会发微信）  
3. Topic / Task 的 extractor `decision` 字段  
4. 规划文档里的「风险中心 / 决策中心」页面（P1-P2 明确不要创建）  
5. Task 禁止键 `risk_ids` / `decision_ids`

### 15. 是否存在历史代码需要明确排除？

**需要排除，不要复用。**

```text
reminders.py / recurring_reminders.json
prompts/QIYE.md、企业_1.md、AI.md 中的结论/风险措辞
topic_extractor_client.parse_extractor_json（会 STRIP decisions/risks）
Task 的 TASK_UPDATE 就地改 title/due_text（Decision 不得套用为覆盖原文）
P0 DedupeIndex
TopicProcessingRecord / TaskProcessingRecord
config.local.json / chat_contexts.json / CoreMemory
Dashboard / 催办 / send_reply
```

---

## 3. 四种业务语义（审计冻结）

| 语义 | 已有能力 | 例子 | P5 是否新建 |
|---|---|---|---|
| Topic = 大家正在讨论什么 | P3 COMPLETE | ERP 增量同步异常 | 只读 |
| Task = 谁需要做什么 | P4 COMPLETE | 王强今天 17 点前处理供应商编码空值规则 | 只读 |
| Decision = 大家最终确认了什么 | **无** | 可以，就按异常池方案执行 | **本阶段设计** |
| Risk = 未来可能发生什么不利结果 | **无** | 如果今天修不好，可能会影响明天现场演示 | **本阶段设计** |

两条误判边界（必须写进 Extractor，本轮只设计）：

```text
建议 ≠ Decision
  「我建议供应商编码缺失的数据先进异常池」→ Suggestion，RELATED 候选
  「可以，就按照异常池方案执行」→ Decision，CREATED_BY

当前问题 ≠ Risk
  「ERP 同步失败了」→ Current Problem / Topic 事实
  「如果 ERP 今天修不好，会影响明天的客户演示」→ Risk
```

P4 CASE-T08 已证明 Task 不会把建议建成待办。当前系统把这句 **丢掉**。P5 Decision 要等确认句，而不是回写 Task。

---

## 4. 当前稳定链路与 P5 插入点

```text
                    P0 evaluate_inbound
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
     Topic Side-path                    Trigger → Chat / 静默
     （P3 冻结，默认关）
              │
              │  Topic 成功且有 topic_id
              ├──────────────► Task Side-path     （P4 已有）
              ├──────────────► Decision Side-path （P5 设计，G2 才挂）
              └──────────────► Risk Side-path     （P5 设计，G4 才挂）
```

原则（本轮确认，不实施）：

- Decision / Risk 只是 **下游观察能力**
- 不得反向控制：微信是否回复、Topic 如何分类、Task 是否创建
- Topic FAILED → Decision 不跑、Risk 不跑
- Task FAILED → **不**阻塞 Decision，**不**阻塞 Risk
- 三者彼此不决定对方是否运行

---

## 5. STOP 条件核对

| # | 条件 | 结论 |
|---|---|---|
| 1 | 必须修改 P3 Topic 数据模型 | **否** |
| 2 | 必须修改 P4 Task 数据模型 | **否**。Risk.task_id 是新实体上的可空外键 |
| 3 | 必须修改 Topic decision | **否** |
| 4 | 必须修改 Task decision | **否** |
| 5 | 必须修改 listener | **否**。listener 已只调 Topic Side-path |
| 6 | 必须修改 Trigger | **否** |
| 7 | 必须合并现有 Task Engine 才能做 Decision / Risk | **否**。独立 Extractor |
| 8 | 已存在另一套完整 Decision / Risk Engine | **否** |
| 9 | Evidence 无法追溯 MessageRecord | **否**。MessageRecord + TopicMessageLink 已够 |
| 10 | 必须使用 Reminder 才能完成 | **否** |
| 11 | 必须引入 SQLite 才能开始 | **否**。延续独立 JSON Store |

**不生成 `P5-G0-BLOCKER-REPORT.md`。不 STOP。**

---

## 6. 审计结论（给后续文档用）

```text
Decision 实体              = 不存在，从零设计
Risk 实体                  = 不存在，从零设计
Chat「结论/风险」          = 自然语言，不是 Engine
MessageRecord              = 足以做 Evidence
TopicMessageLink           = 足以提供主题窗口
Task OPEN 列表             = Risk 可选上下文，非闸门
必须改 P3/P4 模型          = NO
必须上 SQLite              = NO
统一 Action Extractor      = 不适合 v1（会解冻 P4）
推荐下一阶段               = P5-G1 Decision Engine Offline
```
