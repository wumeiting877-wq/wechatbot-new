# P4 Task 数据模型设计

> 日期：2026-09-21  
> 阶段：P4-G0  
> 对照：`P4-TASK-CURRENT-STATE-AUDIT.md`  
> 本文件是设计，不是已落地代码。

---

## 1. 设计目标

P4 v1 只回答：

```text
一个已经形成的 Topic 中，有没有明确需要执行的工作事项？
```

Task 定义：

> 一个明确需要某人或某角色执行的动作事项。

不是：问题事实、建议、闲聊、应答、风险、决定、进度、日报。

绑定规则：

```text
Task.conversation_id  = Conversation.id     # conv_*
Task.topic_id         = Topic.id            # topic_*
禁止 Task.conversation = display_name
禁止把 Task 字段写回 Topic / QIYE.md / TOPIC_EXTRACTOR.md
```

---

## 2. 为什么必须同时保留 conversation_id 与 topic_id

不是风格偏好。来自当前 Store 的真实约束。

### 只保留 topic_id？不够

1. **Topic Store 按会话分区**  
   路径是 `data/topic_store/conversations/{conv_id}/topics.json`。  
   没有全局 Topic 索引。没有 `conversation_id` 就无法在不扫全盘的情况下读 Topic / Message / Link。

2. **同一 Conversation 已证明有多个 Topic**  
   智群 Demo 期望 3 个；真机 QIYE 曾同时存在 2 个 ACTIVE Topic。  
   只绑会话无法回答「这是哪件事里的工作」。

3. **删除 / 审计**  
   P3 删除 Conversation 是删整目录。Task 必须能按同一 `conv_*` 级联，而不能只拿一个 `topic_*` 去猜目录。

### 只保留 conversation_id？不够

研究问题是「**已形成的 Topic 中**」抽 Task。  
一条群消息在会话里，但不一定属于某个业务主题（UNRELATED）。  
无 `topic_id` 的 Task 会变成会话级待办桶，重新引入 P3 已经拒绝的「项目综合」。

### 推荐

```text
必须：conversation_id + topic_id
```

`conversation_id` = 存储分区 + 会话级联 + 与 P3 对齐的外键纪律。  
`topic_id` = 领域归属。  
G1 写入前两者都必须是已存在的 `conv_*` / `topic_*`，禁止 nickname。

---

## 3. 存储方案对比

### 方案 A：独立 JSON Store（推荐）

```text
data/task_store/
  conversations/{conversation_id}/
    tasks.json              Task 列表（小，整体重写）
    links.json              TaskMessageLink
    processed.json          TaskProcessingRecord
  task_engine_audit.jsonl
```

优点：

- 不改 `topic_store.py` 文件格式，不污染 `topics.json`
- 复用 `store_io` 原子写 / FileLock
- Demo 体量（单会话几个 Topic、个位数 Task）足够
- 独立类 `TaskStore`，失败不影响 Topic 文件

缺点：

- Conversation 删除时 P4 以后要同时删 Task 目录（G1 可只实现 TaskStore 自己的 delete）
- 跨会话查询弱（P4 v1 不需要）

### 方案 B：放进 Topic Store 会话目录

```text
data/topic_store/conversations/{conv_id}/tasks.json
```

优点：消息 / Topic / Task 同目录，删除会话一次搞定。

缺点：

- P3 目录语义被扩大，后续很容易去改冻结的 `topic_store.py`
- Topic 备份与 Task 失败写盘耦合在同一棵树
- 与「不得为了 P4 重构 P3」冲突风险更高

不采用。

### 方案 C：SQLite

P3-G0 已写过升级条件：单会话 Message > ~5000，或 P4 实体要稳定 JOIN。  
当前仍是 Demo / 个位数监听对象。仓库没有业务 SQLite。  
为 Task 单独上 SQLite 会引入连接生命周期与备份策略，收益不明显。

**不上 SQLite。** 等 Task + Risk + Decision 真的要跨实体 JOIN 再评估。

### 禁止塞入

| 位置 | 判定 |
|---|---|
| `config.local.json` | 禁止。已含密钥与 CONVERSATIONS |
| `chat_contexts.json` | 禁止。按 nickname，会裁剪 |
| `CoreMemory` | 禁止 |
| `recurring_reminders.json` | 禁止。那是 Reminder |
| Topic `topics.json` 内嵌 `tasks[]` | 禁止。污染 P3 模型 |
| `QIYE.md` | 禁止 |

### 推荐

**方案 A。** MessageRecord **不复制**；Task Evidence 只存 `message_id`，读取时问 Topic Store。

---

## 4. 实体总览

```text
Conversation.id
    ├── Topic.id
    │     └── Task[]                 该主题下的工作事项
    ├── MessageRecord[]              仍只存在 Topic Store
    ├── TopicMessageLink[]           P3 Evidence（只读）
    └── TaskMessageLink[]            P4 Evidence
    └── TaskProcessingRecord
```

ID 前缀：

```text
conv_xxxxxxxxxxxx
topic_xxxxxxxxxxxx
msg_xxxxxxxxxxxx
task_xxxxxxxxxxxx
tlink_xxxxxxxxxxxx
```

---

## 5. Task 字段逐项

候选清单来自任务书。**列出来不等于采用。**

| 字段 | v1 | 说明 |
|---|---|---|
| `id` | **必须** | `task_` + sha1(conversation_id + topic_id + created_msg_id + ordinal + created_at)[:12]。同一消息多 Task 用 `ordinal=0,1,…`。碰撞后缀 `_2`。禁止 title hash |
| `conversation_id` | **必须** | `conv_*` |
| `topic_id` | **必须** | 已存在的 `topic_*`。创建时校验 Topic 存在 |
| `title` | **必须** | 短业务动作标题，≤40 字。例如「处理供应商编码空值规则」。不要整句、不要把截止时间写进 title |
| `description` | **可选** | ≤500 字。原文要点，禁止编造。可空 |
| `status` | **必须** | v1 **只写入 `OPEN`**。见状态机 |
| `assignee` | **不应进入 v1** | 易与对象 / 账号混淆。用 `assignee_text` |
| `assignee_id` | **未来** | 无通讯录，禁止伪造 |
| `assignee_type` | **未来** | 人 / 角色 / 系统。v1 不区分 |
| `assignee_text` | **必须可空** | 从原文抽出的负责人文字。允许空字符串，但空负责人时创建规则更严（见 §6） |
| `due_at` | **可选字段，v1 默认空** | 仅确定性解析器可写。Extractor / LLM **禁止**填写 |
| `due_text` | **必须可空** | 原文截止用语：「今天 16 点前」。无截止则空 |
| `created_at` | **必须** | ISO-8601（引擎写入时刻或消息时间，G1 用 utc_now / 消息时间字符串原样存审计，不二次猜时区） |
| `updated_at` | **必须** | |
| `confidence` | **必须** | `HIGH \| MEDIUM \| LOW`，最近一次有效抽取 |
| `schema_version` | **必须** | `1` |
| `created_msg_id` | **必须** | 冗余 CREATED_BY 的 message_id，便于检索 |
| `task_processing 外键` | **不应进 Task 行** | 放 ProcessingRecord |

不采用的建议字段（即使 Demo 出现）：

```text
progress_percent
risk_ids / decision_ids
reminder_id
assignee_wxid
priority
source_agent
embedding
```

Extractor 若输出这些：校验器丢弃，不落盘。

---

## 6. 负责人：三种方案

企业群里的「王强 / 李娜 / 赵凯」当前只是：

- 正文点名，或
- `MessageRecord.sender_name`

不是企业通讯录 ID。

### 方案 A：`assignee_name = 王强`

优点：直观。  
缺点：叫 `name` 像已解析的主数据；以后加 ID 时语义分裂。与 `sender_name` 对齐但负责人 ≠ 发送者，更容易被填成发送者。

### 方案 B：`assignee_id + assignee_name`

id 从哪里来？

| 候选来源 | 现实 |
|---|---|
| 企业通讯录 | **不存在** |
| `sender_wxid` | 只覆盖「自己领任务且自己说话」；点名场景失效 |
| 用 sender_name 反查历史消息 wxid | 改名/重名/未发言者失败；等于伪造目录 |
| 生成 `usr_` 内部 id | 没有稳定键，下次「王强」会变成另一个 id |

**禁止伪造用户目录。** 方案 B 不能做 v1。

### 方案 C：`assignee_text`（推荐）

只保存模型从 **当前输入原文** 抽到的负责人文字。

优点：

- 与项目真实能力一致
- 不假装解析成功
- 发送者自称「我中午前修复」时，允许把 `assignee_text` 填成 `current_message.sender_name`（有消息证据），仍不写 `assignee_id`

缺点：

- 不能按人查询稳定列表
- 不能自动 @ 微信（P4 本来就禁止发微信）

### 空负责人规则（CASE-T02）

```text
有明确动作对象 + 原文出现负责人或「我 + 具体动作」
    → 可以建 Task（assignee_text 可为人名或发送者名）

有明确动作对象，但无人、无「我」、无角色
    → v1 不建 Task
    → 不写 assignee_text="" 的孤儿待办

「需要再跑一次回归。」
    → 不建 Task
```

允许空 `assignee_text` 的唯一例外（本阶段 **不作为必测 CASE**，G1 可当 LIMITATION）：强祈使且对象极具体、但未点名。v1 为降低噪声，**默认仍不建**。宁可漏，不可堆无人认领的待办。

**不得**把发送者默认填成负责人。周敏下令 ≠ 周敏执行。

---

## 7. 截止时间

原文形态：

```text
今天 16 点前
中午前
明天 12 点前
周五
月底前
尽快
```

### 方案 A：只存 `due_text`

优点：不丢原文、不引入错误日期。  
缺点：不能排序、不能到期扫描。P4 本阶段不做提醒，所以可接受。

### 方案 B：`due_text` + `due_at`，且 `due_at` 必须确定性解析

优点：以后催办有绝对时间。  
致命约束：不得让 LLM 把「明天」换成错误日历日。

参照点应是 **消息时间**，不是引擎运行的「现在」。  
但 `MessageRecord.created_at` 真机可能是微信时间戳字符串，时区不统一。在解析器未写清之前写 `due_at` 会脏数据。

### 推荐（P4 v1）

```text
必须可空：due_text     ← LLM / Extractor 只填这个
字段预留：due_at       ← 默认 ""
禁止：Extractor JSON 携带 due_at；校验器丢弃
尽快 / 尽快吧 / 有空时：due_text 原样可存，due_at 仍空
无截止：due_text=""
```

绝对时间解析 = **OPTIONAL / FUTURE**，单独模块，输入 `(due_text, message_created_at)`，失败则保持 `due_at` 空。  
不进入 P4-G1 必做范围。Reminder 里的 LLM 时间解析 **禁止**搬过来（那会发微信且以「现在」为锚）。

CASE-T01 期望存 `due_text="今天 16 点前"`，不验收 `2026-09-20T16:00:00+08:00`。

---

## 8. TaskMessageLink（Evidence 第一天就要有）

不能出现「有 Task 但不知道哪句话产生的」。

```text
TaskMessageLink

id              tlink_{12 hex}
task_id         task_*
message_id      msg_*          必须已存在于 Topic Store MessageRecord
relation        CREATED_BY | UPDATED_BY | RELATED
confidence      HIGH | MEDIUM | LOW
created_at
```

联合唯一：`(task_id, message_id, relation)`。

| relation | v1 | 何时 |
|---|---|---|
| CREATED_BY | **使用** | NEW_TASK 的当前消息；每个 Task 恰好一条 |
| UPDATED_BY | **使用** | TASK_UPDATE（改截止、改标题要点等） |
| RELATED | **使用** | 确认执行、补充同一事项的上下文；不改 status |
| COMPLETION_EVIDENCE | **不进入 v1** | 留给将来 DONE；现在写了会诱使自动完成 |

`evidence_message_ids` 必须来自本次 Extractor 输入，且必须包含 `current_message.id`。

---

## 9. 基数

### Topic : Task = 1 : N

明显不是 1:1。智群 Demo 一个 ERP Topic 上就可以有「空值规则」一项，以后还可能有别的。

```text
一个 Topic 下 0..N 个 OPEN Task
```

### Message : Task

P3 v1 是 **1 Message → 1 主 Topic**。  
P4 **不能**把这套直接套到 Task。

```text
1 Message → 0..N Task     P4 v1 支持
上限 5 个 decision / 每条消息
```

例：

```text
王强处理供应商编码，李娜修权限。
→ 两个 NEW_TASK（CASE-T04）
```

约束：本轮抽到的 Task **全部绑定当前消息的 `topic_id`**（Topic Engine 给出的那一个）。  
不在 Task Extractor 里新建 Topic，不跨 Topic 改挂（那会变相做主题分类）。

已知限制：若这句话的主 Topic 被 P3 判成 ERP，则「李娜修权限」也会落在 ERP Topic 下。这是 P3 单主 Topic 遗产，P4-G0 **不修改 P3** 来修。记入 Gap LIMITATION。

同一负责人、同一截止、连续两个步骤（「做完空值规则，再跑一次回归」）→ **一个** Task，title 覆盖主动作，description 可含第二步。不要拆成两个几乎相同的待办。

---

## 10. 状态机（设计，不实施写入除 OPEN 以外的值）

```text
OPEN  →  IN_PROGRESS  →  DONE
  │           │
  └→ CANCELLED ←┘
```

| 状态 | v1 写入 | 说明 |
|---|---|---|
| OPEN | **允许** | NEW_TASK 唯一状态 |
| IN_PROGRESS | 只读预留 | 不写。避免「我在看」就把状态推走 |
| DONE | 只读预留 | **不自动完成**。见引擎设计 CASE-T10 |
| CANCELLED | 只读预留 | 不写 |

与 P3 对齐：P3 v1 只创建 `ACTIVE`，不自动 `RESOLVED`。  
P4 v1 只创建 `OPEN`，不自动 `DONE`。

TASK_UPDATE **不改 status**。  
模型若输出 TASK_COMPLETE：校验器视为非法或映射为不写盘的 UNRELATED，**不得**改 status。

---

## 11. Task identity / 更新命中

场景：

```text
09:08  王强今天 16 点前把空值处理规则做完
09:30  改成 17 点前
```

必须更新原 Task，禁止第二条 NEW_TASK。

v1 命中手段（都要）：

1. Extractor 输入带 `existing_tasks`（当前 Topic 下 OPEN，最多 10 条）。
2. `TASK_UPDATE` 的 `task_id` 必须 ∈ 该列表。
3. Prompt 规则：同一负责人 + 同一动作对象 → UPDATE；不要因截止变化而 NEW。
4. 引擎不靠 P0 Dedupe，不靠标题完全相等。

不在 v1 做模糊合并器（避免静默把两个真任务并成一个）。命中失败则：

- 非法 `task_id` → 整单 decision 失败（该条 FAILED，不写脏 Task）
- 模型误 NEW 且测试能抓到（CASE-T05）→ G1 用 fixture 约束 Prompt，而不是上启发式乱合并

---

## 12. TaskProcessingRecord（业务幂等）

P0 Dedupe 防微信重复回调，TTL 内存，不能当 P4 幂等。  
TopicProcessingRecord 只标记 **Topic** 是否处理过该消息。

同一条 Message 仍可能：离线重放、Topic 成功后第一次跑 Task、Task FAILED 重试、将来 Prompt 升级。

```text
TaskProcessingRecord

message_id                 msg_*
conversation_id            conv_*
topic_id                   当时使用的 topic_*（可空：未跑）
task_processing_version    1
extractor_prompt_name      TASK_EXTRACTOR
extractor_prompt_hash      sha256
decision_summary           NEW_TASK,TASK_UPDATE,UNRELATED,...（拼接或列表）
task_ids                   本条成功写入/更新的 task id[]
processed_at
error
```

主键：`message_id + task_processing_version`。

规则：

- 已有成功记录（decision 非 FAILED）→ 跳过，不新建、不重复更新
- FAILED 允许同 version 重试
- Prompt 正文 hash 变了 **默认不自动重跑**；升 `task_processing_version` 才重跑
- 不修改 P0 `DedupeIndex`，不修改 TopicProcessingRecord

Topic 对该消息仍是 FAILED 时：不写成功 TaskProcessing；也不写 UNRELATED 成功标记（否则 Topic 重试成功后 Task 会被误跳过）。见引擎设计依赖一节。

---

## 13. 生命周期（先设计）

| 事件 | 行为 |
|---|---|
| 删除 Conversation | 删除 `data/task_store/conversations/{id}/`（G1 提供方法；不改 P3 delete 也行，文档标明双目录） |
| 删除 Topic | v1 不级联删 Task；Task 仍留着但 G1 不实现删 Topic |
| 删除 Message | 不删 Task；Link 保留 message_id；正文以 Topic Store 为准，红acted 后 title 不自动改 |
| 保留期限 | v1 不自动过期 |
| 日志 | audit 只存 content preview ≤80 字，不含 API Key |

---

## 14. schema_version

`1`。  
以后加 `assignee_id` / 写 `due_at` / 允 DONE 都升版本，并升 `task_processing_version` 才重抽。
