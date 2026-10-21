# P4 Task Engine 现状审计

> 日期：2026-09-21  
> 项目：wechatbot-new  
> 阶段：**P4-G0**（READ ONLY 审计 + 架构设计 + 离线测试基线）  
> 方式：只读扫描。本轮未实现生产 Task Engine，未接微信，未改 P3 Topic Engine，未进入 Risk / Decision。  
> 对照：`P0-CLOSURE-REPORT.md`、`P1-P2-CLOSURE-REPORT.md`、`P3-G2-CLOSURE-REPORT.md`、`P3-TOPIC-DATA-MODEL-DESIGN.md`，以及当前源码。

---

## 0. 冻结基线确认

已完整读取 P0 / P1 / P2 / P3 关闭报告，并对照当前源码。

```text
P0 STATUS            = CLOSED
P1 STATUS            = CLOSED
P2 STATUS            = CLOSED
P3-G0 STATUS         = COMPLETE
P3-G1 STATUS         = COMPLETE
P3-G2 STATUS         = COMPLETE

P4                   = NOT STARTED（本轮开始设计，未实施）
TOPIC_ENGINE_ENABLED = false（模块默认；runtime_control 真机结束后已关）
```

P3 已证明：

```text
Topic Side-path              = VERIFIED
Real LLM Topic Extractor     = VERIFIED
Live WeChat Topic Ingestion  = VERIFIED
Evidence                     = VERIFIED
Failure Isolation            = VERIFIED

Trigger                      = PRESERVED
Chat                         = PRESERVED
Stop Bot                     = PRESERVED
```

生产默认：

```text
TOPIC_ENGINE_ENABLED = false
```

源码核对：

| 项 | 位置 | 现状 |
|---|---|---|
| 模块默认关 | `topic_engine.py` `TOPIC_ENGINE_ENABLED = False` | 确认 |
| 运行时覆盖 | `topic_sidepath.is_topic_engine_enabled()`：`runtime_control/TOPIC_ENGINE_ENABLED` > 环境变量 > 模块常量 | 确认 |
| 真机 QIYE | `agt_38b43979a544`，`chat_prompt_name=QIYE`，`extractor_prompt_name=TOPIC_EXTRACTOR` | 开关关闭时 Extractor 不跑 |
| P4 文档 / 代码 | 仓库内无 `P4-*.md`、无 `task_engine.py` / `task_store.py` / `task_extractor_client.py` | 确认尚未开始 |

本轮遵守：

- 未修改 `message/identity.py`、`dedupe.py`、`outbound.py`、`trigger.py`、`reply_format.py`、`listener.py`、`bot_runtime.py`
- 未修改 `topic_store.py`、`topic_engine.py`、`topic_sidepath.py`、`topic_extractor_client.py`（只读）
- 未修改 `prompts/QIYE.md`、`prompts/企业_1.md`、`prompts/extractors/TOPIC_EXTRACTOR.md`
- 未进入 Risk / Decision / Reminder / Workflow / Dashboard / RAG / 多 Agent / 自动催办 / 自动发微信

---

## 1. 当前真实对象关系（已落地）

```text
Conversation.id  (conv_*)
    ├── AgentConfig.id  (agt_*)     P2 绑定 Chat Prompt / Extractor Prompt 名
    └── Topic Store 目录
            data/topic_store/conversations/{conv_id}/
                messages.jsonl          MessageRecord
                topics.json             Topic[]
                links.json              TopicMessageLink[]
                processed.json          TopicProcessingRecord
```

运行时主链（P0，冻结）：

```text
微信本地库
  → WxMessage
  → message.listener.message_listener
  → inbound_from_wx_message → InboundMessage
  → BotRuntime.evaluate_inbound
  → try_enqueue_topic_sidepath(inbound, verdict)   # 旁路，不改 verdict
  → REPLY → Chat；NO_ACTION → 结束
```

Topic 旁路（P3，已验证，默认关）：

```text
TopicSidepath worker
  → TopicEngine.process_inbound
  → project MessageRecord
  → upsert_message
  → Topic Extractor（独立 Prompt，store_context=false）
  → Topic / TopicMessageLink / TopicProcessingRecord
  → 禁止 send_reply / wx.SendMsg
```

**没有** Task 对象，**没有** Task 旁路。

---

## 2. 当前是否已经存在真正 Task 能力？

**否。没有真正的 Task Engine。**

必须区分：

| 表象 | 是什么 | 是不是 Task Engine |
|---|---|---|
| `prompts/QIYE.md` 写「整理任务、风险、结论」 | Chat 人设口吻 | **否**。自然语言回复，无结构化 Task，不落盘 |
| `prompts/AI.md`「解决任务」 | 通用助手措辞 | **否** |
| `reminders.py` + `recurring_reminders.json` | 用户让机器人「到点提醒我」 | **否**。个人提醒，会发微信，无 Topic 绑定，无 Evidence |
| `message/handler.py` reminder 关键字 | P0 管道一步 | **否** |
| Topic Extractor 禁止输出 `tasks/assignee/due` | 防污染 | **否**。P3 明确剥离这些字段 |
| `topic_extractor_client.STRIP_KEYS` 含 `tasks/assignee/due_at` | Validator 丢弃 | **否**。证明 Task 被故意排除 |
| Chat 模型口头说「任务是…」 | 幻觉 / 闲聊 | **否** |

仓库检索：

```text
task_engine.py              不存在
task_store.py               不存在
task_extractor_client.py    不存在
TASK_EXTRACTOR.md           不存在
assignee / due_at 业务字段  不存在于 Topic / Conversation / Agent
```

结论：P4 从零设计。禁止把 Reminder 或 Chat 文案当成已实现。

---

## 3. 容易被误认的旧代码

### 3.1 Reminder（最像，但不是）

`reminders.py`：

- 输入：当前用户一句话（「10 分钟后提醒我…」）
- 存储：`recurring_reminders.json`，字段是 `user_id` / `time_str` / `content`
- 输出：到期后进消息队列或 `send_reply`
- 身份：提醒对象 = 对机器人说话的那个人，不是群里被点名的「王强」
- 无 `topic_id`、无 `message_id` Evidence、无企业工作事项语义

P4 不得复用 Reminder 存储、解析 Prompt、或到期发送路径。

### 3.2 Topic 上的动作词

智群 Demo 里大量动作词已经进入 **Topic**，例如：

- 「王强今天 16 点前把空值处理规则做完」→ P3 归到 ERP Topic，**不**建 Task
- 「李娜把权限问题修一下」类语句 → 权限 Topic
- 「赵凯明天 12 点前准备离线包」→ 演示 Topic

P3 Prompt 明确：标题不要人名和截止时间；禁止输出 tasks/assignee/due。

### 3.3 TopicProcessingRecord

这是 **Topic 幂等**，不是 Task 幂等。P0 Dedupe 也不是。P4 必须另建 `TaskProcessingRecord`。

---

## 4. 是否已有任务/待办/提醒数据结构？

| 结构 | 有无 | 说明 |
|---|---|---|
| Task | 无 | — |
| ToDo / 待办实体 | 无 | — |
| Reminder | 有 | 见 3.1，禁止当 Task |
| Topic | 有 | 业务主题，无负责人/截止 |
| MessageRecord | 有 | 消息档案，可作 Evidence 原文 |
| Conversation | 有 | 会话容器 |
| 企业通讯录 / 用户目录 | **无** | 全仓库无 contacts / assignee_id 目录 |

---

## 5. Topic Store 当前能提供的 Evidence

`TopicStore` 已实现只读能力，P4 可在不改 P3 语义的前提下 **读取**：

### 5.1 MessageRecord（`topic_store._normalize_message`）

```text
id, conversation_id, platform_message_id
sender_id, sender_wxid, sender_name
content, message_type, created_at
direction, reply_to_message_id
raw_reference { chat_name, chat_wxid, local_id, create_time, quote_excerpt }
ingested_at, schema_version
```

足以支持 Task Evidence 的：

- 原文 `content`
- 消息主键 `id`（`msg_*`）
- 会话外键 `conversation_id`（必须是 `conv_*`）
- 发送者展示名 `sender_name`
- 可能的稳定发送者 `sender_wxid`（可空）
- 时间 `created_at`（格式在真机投影里可能是平台时间字符串，不一定是严格 ISO）

不足以单独当「负责人目录」的：

- `sender_id` 是微信库整数，P0 已证明不能当业务身份
- 被点名的人经常 **不是** 发送者（周敏点王强）
- 无企业员工 ID

`reply_to_message_id`：P3-G1 已记录真机 listener 常空。Task 更新不能依赖引用回复，必须靠 Topic 内最近消息。

### 5.2 Topic

```text
id, conversation_id, title, summary
status=ACTIVE（v1 只写入 ACTIVE；不自动 RESOLVED）
confidence, created_at, updated_at, last_message_at, message_count
schema_version
```

**没有** `assignee` / `due_at` / `task_ids`。这是 P3 刻意排除，P4 不得回写进 Topic。

### 5.3 TopicMessageLink

```text
id, topic_id, message_id
relation ∈ { CREATED_BY, RELATED, UPDATED_BY }
confidence, created_at
联合唯一 (topic_id, message_id, relation)
```

存储已是 **N:N**。可以用 `links_for_topic` 取出一个 Topic 下的全部消息，作为 Task Extractor 的 `recent_topic_messages` 来源。

### 5.4 TopicProcessingRecord

主键 `message_id + topic_processing_version`。  
成功（含 UNRELATED/SKIPPED）跳过；FAILED 可同 version 重试。  
**不能**承担 Task 幂等。

真机（P3-G2）：QIYE `conv_6fbe0f455b94` 曾写入 13 条 MessageRecord、2 个 ACTIVE Topic、Link 可追溯。本仓库工作区当前 **没有** 残留 `data/topic_store/`（备份快照记 `topic_store_backup = ABSENT`）。离线 fixture 仍以 `tests/fixtures/topic_engine/zhiqun_demo.json` 为准。

---

## 6. MessageRecord 是否足以支持 Task Evidence？

**足以支撑 v1 Evidence，不足以支撑人员目录或绝对时间。**

| 需求 | MessageRecord | 判定 |
|---|---|---|
| 哪句话产生了 Task | `id` + `content` + Link | 足够 |
| 会话 | `conversation_id` | 足够 |
| 主题上下文 | 需经 Topic + Link 间接得到 | 足够（读 P3 Store） |
| 发送者是谁 | `sender_name` / `sender_wxid` | 足够表达「谁说的」 |
| 负责人是谁 | 常在正文里被点名 | 只能抽 `assignee_text`，不能落稳定 ID |
| 「今天 16 点」的绝对时间 | `created_at` 作参照 | 字段在，格式不统一；v1 不让 LLM 填 `due_at` |
| 引用回复链 | `reply_to_message_id` | 真机常空；v1 不依赖 |

不需要为 P4 修改 `InboundMessage` 或 `identity.py`。

---

## 7. sender 能否支持人员识别？

三层身份，不要混用：

```text
1. 发送者身份（已有）
   MessageRecord.sender_name / sender_wxid / sender_id

2. 被指派负责人（P4 要抽）
   正文里的「王强」「李娜」「赵凯」
   经常 ≠ 发送者

3. 企业通讯录 ID（没有）
   全项目无用户目录，禁止伪造
```

`sender_wxid` 只标识 **说话的人**。  
「周敏：王强今天 16 点前把空值处理规则做完」→ 发送者周敏，负责人王强。  
即使王强后来自己发过消息、有 `sender_wxid`，用昵称反查 wxid 也不稳定（改名、重名、未发言的被指派人）。

P4 v1 人员策略见数据模型：**只存 `assignee_text`**。

---

## 8. TopicMessageLink 能否支持 Task 来源追溯？

能支持 **Topic ← Message** 追溯，不能替代 **Task ← Message** 追溯。

P3 Link 回答的是：「这条消息属于哪个 Topic」。  
P4 还要回答：「这个 Task 由哪句话创建/更新」。

同一条消息可以：

- 属于一个 Topic（P3 v1 单主 Topic）
- 产生 0..N 个 Task

因此必须另建 `TaskMessageLink`（或等价表）。  
Topic Link 仍用于 **选取** Task Extractor 的主题内消息窗口，不把 Task id 写进 P3 Link。

---

## 9. Conversation / Agent / Topic / Message 真实关系

```text
Conversation (conv_*)
    │  1:1 绑定 AgentConfig（P2）
    │      chat_prompt_name      → prompts/{name}.md          Chat
    │      extractor_prompt_name → prompts/extractors/{}.md   现仅 TOPIC_EXTRACTOR
    │
    ├── MessageRecord[]     1 Conversation : N Message
    ├── Topic[]             1 Conversation : N Topic     （真机 QIYE = 2；Demo = 3）
    └── TopicMessageLink    Topic N:N Message
```

P3 Extractor v1：1 Message → 1 个主 Topic。  
存储：N:N Link 已建好。

Task 规划位置：

```text
Conversation 1:N Topic 1:N Task
Message      1:N Task          （P4 v1 支持，见引擎设计）
Task         必须同时有 conversation_id 与 topic_id
```

为什么两者都要，见 `P4-TASK-DATA-MODEL-DESIGN.md` §2。不是拍脑袋：Topic Store 按 `conversation_id` 分目录，且同一会话已证明有多个 Topic。

---

## 10. Extractor / Prompt 隔离现状（对 P4 的约束）

| | Chat | Topic Extractor | Task Extractor（尚未实施） |
|---|---|---|---|
| 文件 | `prompts/QIYE.md` | `prompts/extractors/TOPIC_EXTRACTOR.md` | 设计为 `prompts/extractors/TASK_EXTRACTOR.md` |
| Loader | `resolve_chat_prompt` | `resolve_extractor_prompt`（已按文件名读子目录） | 可复用该 loader，**换文件名**，禁止改 Topic Prompt |
| LLM | `chat_contexts` | `get_extractor_response` `store_context=false` | 独立 client / 独立 parser；不得走 Chat |
| 输出 | 对用户说话 | 单 decision JSON | `decisions[]` JSON |
| WebUI 下拉 | `list_prompt_names` 不递归子目录 | 不会进 Chat 下拉 | 同左，只要不放到 `prompts/*.md` |

`topic_extractor_client.parse_extractor_json` 会 **剥离** `tasks/assignee/due/due_at`。  
因此 **不能** 复用 Topic 的 parser 来解析 Task 输出。G1 必须有独立 Task Extractor client。

`agent_store.DEFAULT_EXTRACTOR_PROMPT_NAME = "TOPIC_EXTRACTOR"`。  
P4 不得改这个默认值。Task Engine 显式传入 `TASK_EXTRACTOR`。

---

## 11. Topic → Message 持久化的隐含依赖（关键）

MessageRecord **只在 Topic Engine `_process_record` 里 upsert**。

```text
TopicEngine._process_record
    store.upsert_message(...)     # 先写消息
    has_successful_processing → 跳过
    Extractor / apply decision
```

推论：

1. `TOPIC_ENGINE_ENABLED=false` 时，生产 **没有** 新的 MessageRecord，也就没有 Task Evidence 来源。
2. Topic Extractor timeout / FAILED 时，消息可能已入库，但本条没有可用 `topic_id`（R12 已验证：timeout 不建脏 Topic）。
3. Task 若要「从已形成的 Topic 中抽工作事项」，v1 必须 **读 P3 Store，且要求本条已有成功 Topic 归属**。
4. 不得为了 Task 把 Message 持久化搬出 Topic Engine（那会改 P3 冻结语义）。G1 离线自行向 Topic Store 写入 fixture 消息即可。

这不是 BLOCKER（离线可测），但是 P4 链路选择的硬约束。详见引擎设计「推荐链路」。

---

## 12. 审计结论（Gate 0）

```text
真正 Task Engine          = 不存在
Reminder / Chat「任务」   = 不是 Task Engine
Topic Store Evidence      = 足以支撑 v1 Task 追溯
人员稳定 ID               = 不存在；v1 只存原文负责人文字
截止绝对时间              = 不让 LLM 写 due_at
P3 冻结模块               = 本轮未改，G1 离线也不需要改
P3 Topic 数据不足？       = 否。足够抽「已形成 Topic 内的工作事项」
必须修改 P0/P1/P2/P3？    = 否（G1 离线）。真机挂钩留到以后单独授权
已有另一套 Task Engine？  = 否

P4-G0 BLOCKER             = 无
允许继续设计并写文档      = 是
禁止本轮实施生产引擎      = 是
```

未生成 `P4-G0-BLOCKER-REPORT.md`（未发现必须 STOP 的重大问题）。
