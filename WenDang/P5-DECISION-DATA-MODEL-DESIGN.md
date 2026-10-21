# P5 Decision 数据模型设计

> 日期：2026-09-22  
> 阶段：P5-G0  
> 对照：`P5-CURRENT-STATE-AUDIT.md`、`P3-TOPIC-DATA-MODEL-DESIGN.md`、`P4-TASK-DATA-MODEL-DESIGN.md`  
> 本文件是设计，不是已落地代码。本轮不创建 `decision_store.py`。

---

## 1. 设计目标

P5 Decision v1 只回答：

```text
一个已经形成的 Topic 中，大家最终确认采用了什么方案？
```

Decision 定义：

> 针对当前 Topic，由明确确认句固定下来的企业事实：采用什么、不采用什么、以什么为准。

不是：建议、讨论中的方案、问题事实、工作指派、未来风险、进度、日报。

绑定规则：

```text
Decision.conversation_id  = Conversation.id     # conv_*
Decision.topic_id         = Topic.id            # topic_*
禁止 Decision.conversation = display_name
禁止把 Decision 字段写回 Topic / Task / QIYE.md / TOPIC_EXTRACTOR.md / TASK_EXTRACTOR.md
禁止 Decision.task_id     （v1 不绑 Task）
```

---

## 2. Decision 应该绑定什么

### 方案 A：只绑 `topic_id`

不够。与 Task 相同的 Store 事实：

1. Topic Store / Task Store 都按 `conversations/{conv_id}/` 分区。没有 `conversation_id` 就无法在不扫全盘的情况下定位 Topic / Message。
2. 删除 Conversation 是删整目录。Decision 必须能按同一 `conv_*` 级联。
3. 真机已证明同一 Conversation 可有多个 ACTIVE Topic。只拿 `topic_*` 反查会话目录不是当前 API。

### 方案 B：`conversation_id` + `topic_id`（推荐）

```text
必须：conversation_id + topic_id
```

- `conversation_id` = 存储分区 + 会话级联 + 与 P3/P4 对齐的外键纪律  
- `topic_id` = 领域归属：确认的是 **这个讨论** 的方案，不是会话级「综合决议桶」

无 `topic_id` 的 Decision 会重新引入 P3 已拒绝的「项目综合」。

### 方案 C：再绑 `task_id`

不采用 v1。

| 理由 | 说明 |
|---|---|
| 语义 | Decision 本质属于 Topic（最终确认讨论结论），不是 Task（谁去做） |
| 时序 | 「可以，按异常池方案执行」经常 **先于** 或 **独立于** 指派 |
| 耦合 | 绑死 `task_id` 会让 Decision 等待 Task 成功，违反旁路隔离 |
| CASE | M03「那就这么定，王强今天 17 点前处理」= 1 Decision + 1 Task，二者平行，不是 Decision 从属于 Task |

**结论：Decision 本质属于 Topic，不属于 Task。v1 禁止 `task_id`。**

---

## 3. 存储方案对比

### 方案 A：独立 JSON Store（推荐）

```text
data/decision_store/
  conversations/{conversation_id}/
    decisions.json          Decision 列表（小，整体重写）
    links.json              DecisionMessageLink
    processed.json          DecisionProcessingRecord
  decision_engine_audit.jsonl
```

优点：不改 `topics.json` / `tasks.json`；复用 `store_io` 原子写 / FileLock；失败不影响 Topic / Task 文件；与 P3/P4 分区方式一致。

### 方案 B：统一 `data/action_store/`

把 Task + Decision + Risk 塞进同一棵树。

不采用。Task Store 已 COMPLETE / VERIFIED。统一会诱使改 `task_store.py` 文件格式与 processing 主键，直接违反「禁止为了漂亮重写 P4」。

### 方案 C：放进 Topic Store 会话目录

```text
data/topic_store/conversations/{conv_id}/decisions.json
```

不采用。会扩大 P3 目录语义，后续很容易去改冻结的 `topic_store.py`。

### 方案 D：SQLite

不采用。仓库没有业务 SQLite。P3/P4 已两次拒绝。Demo / 个位数监听对象用 JSON 足够。跨实体 JOIN 仍不是 v1 需求。

### 禁止塞入

| 位置 | 判定 |
|---|---|
| `config.local.json` | 禁止 |
| `chat_contexts.json` | 禁止 |
| `CoreMemory` | 禁止 |
| `recurring_reminders.json` | 禁止。那是 Reminder |
| Topic `topics.json` 内嵌 `decisions[]` | 禁止 |
| Task `tasks.json` 的 `decision_ids` | 禁止。该键已被 P4 STRIP |

### 推荐

**方案 A。** MessageRecord **不复制**；Decision Evidence 只存 `message_id`，读取时问 Topic Store。

---

## 4. 实体总览

```text
Conversation.id
    ├── Topic.id
    │     └── Decision[]              该主题下已记录的确认
    ├── MessageRecord[]               仍只存在 Topic Store
    ├── TopicMessageLink[]            P3 Evidence（只读）
    ├── DecisionMessageLink[]         P5 Evidence
    └── DecisionProcessingRecord
```

ID 前缀：

```text
conv_xxxxxxxxxxxx
topic_xxxxxxxxxxxx
msg_xxxxxxxxxxxx
dec_xxxxxxxxxxxx
dlink_xxxxxxxxxxxx
```

---

## 5. Decision 字段逐项

候选清单来自任务书。**列出来不等于采用。**

| 字段 | v1 | 说明 |
|---|---|---|
| `id` | **MUST** | `dec_` + sha1(conversation_id + topic_id + created_msg_id + ordinal + created_at)[:12]。同一消息多 Decision 用 `ordinal=0,1,…`。碰撞后缀 `_2`。禁止 title hash |
| `conversation_id` | **MUST** | `conv_*` |
| `topic_id` | **MUST** | 已存在的 `topic_*`。创建时校验 Topic 存在 |
| `title` | **MUST** | 短确认标题，≤40 字。例如「采用异常池方案」。不要把整段确认句塞进 title |
| `decision_text` | **MUST** | 确认内容原文要点，≤500 字。禁止编造。这是企业事实正文 |
| `summary` | **OPTIONAL** | ≤500 字。v1 若空则引擎可复制 `decision_text`。不单独让模型再写一套故事 |
| `status` | **MUST** | v1 **只写入 `RECORDED`**。见状态机 |
| `confidence` | **MUST** | `HIGH \| MEDIUM \| LOW`，创建时的抽取置信度。此后不因后续消息改写本行 |
| `created_msg_id` | **MUST** | 确认句 MessageRecord.id（CREATED_BY）。**不是**建议句 |
| `supersedes_decision_id` | **OPTIONAL 可空** | 若本条替换某条已有 Decision，填其 `dec_*`；必须 ∈ 本次 `existing_decisions`。空 = 全新确认 |
| `created_at` | **MUST** | ISO-8601 或消息时间字符串原样 |
| `updated_at` | **MUST** | v1 创建后不因「方案改了」而改本行正文；仅预留字段对称 |
| `schema_version` | **MUST** | `1` |
| `task_id` | **NOT V1** | Decision 不绑 Task |
| `decided_by` / `decided_by_id` | **NOT V1** | 发言者在 MessageRecord。无通讯录 |
| `version`（实体内递增） | **NOT V1** | 用新行 + `supersedes_decision_id`，不在原行打版本号 |
| `cancelled_reason` | **NOT V1** | |
| `embedding` | **NOT V1** | |

Extractor 若输出 `task_id` / `status` / `CANCELLED` / `severity`：校验器丢弃或整单失败，不落盘。

---

## 6. Decision 是否可修改

场景：

```text
10:00  决定先用增量同步。
11:00  刚才方案改了，改成全量同步。
```

### 方案 A：直接更新原 Decision

`Decision.decision_text` 被覆盖。

不采用。企业事实被静默改写，审计无法回答「10:00 到底确认过什么」。与「Decision 是企业事实记录」冲突。

### 方案 B：保留旧 Decision，新建新 Decision，并建立 SUPERSEDES（推荐）

```text
dec_old  status=RECORDED  decision_text=采用增量同步  created_msg_id=msg_1000
dec_new  status=RECORDED  decision_text=改用全量同步  created_msg_id=msg_1100
         supersedes_decision_id=dec_old
```

优点：历史可追溯；确认句各自有 CREATED_BY；不改 P3/P4。  
「当前有效决定」查询（只读规则，v1 可后置）：

```text
status=RECORDED
且没有任何其它 Decision.supersedes_decision_id 指向本 id
```

### 方案 C：同一 Decision 带 version 数组

实现复杂，等于在 JSON 行内嵌历史。v1 体量不需要。升级路径以后仍可用方案 B 的多行表达。

### 与 Task UPDATE 的关键差别

Task 是 **进行中的工作事项**：改截止时间应当更新同一 Task，避免重复待办。  
Decision 是 **已确认事实**：方案被推翻应留下旧事实 + 新事实，而不是把旧事实改成新事实。

因此 **v1 不提供 DECISION_UPDATE 就地改文**。Extractor 只有：

```text
NEW_DECISION | UNRELATED
```

替换关系用 `NEW_DECISION.supersedes_decision_id`。

---

## 7. 状态机

```text
RECORDED  →  SUPERSEDED
    │
    └→ CANCELLED
```

| 状态 | v1 写入 | 说明 |
|---|---|---|
| RECORDED | **允许（唯一）** | NEW_DECISION 落地状态 |
| SUPERSEDED | 只读预留 | **不自动写**。替换关系放在新行的 `supersedes_decision_id` |
| CANCELLED | 只读预留 | **不自动写**。没有「取消决定」状态机 |

对齐：

```text
P3 v1 不自动 RESOLVED
P4 v1 不自动 DONE
P5 Decision v1 不自动 SUPERSEDED / CANCELLED
```

即使 11:00 明确改方案，旧行仍保持 `RECORDED`。有效性由 supersede 指针表达，避免模型/引擎猜测「作废」。

模型若输出 `DECISION_UPDATE` / `CANCELLED` / `INVALID`：校验器视为非法，整单不落盘。

---

## 8. DecisionMessageLink（Evidence 第一天就要有）

不能出现「有 Decision 但不知道哪句确认、哪句只是建议」。

```text
DecisionMessageLink

id              dlink_{12 hex}
decision_id     dec_*
message_id      msg_*          必须已存在于 Topic Store MessageRecord
relation        CREATED_BY | RELATED
confidence      HIGH | MEDIUM | LOW
created_at
```

联合唯一：`(decision_id, message_id, relation)`。

| relation | v1 | 何时 |
|---|---|---|
| CREATED_BY | **使用** | **确认句**（当前消息）。每个 Decision 恰好一条。**不是建议句** |
| RELATED | **使用** | 被确认的建议 / 方案陈述（上文窗口内的 evidence） |
| CONFIRMED_BY | **NOT V1** | 与 CREATED_BY 重复 |
| UPDATED_BY | **NOT V1** | v1 无就地更新 |
| SUPERSEDED_BY | **NOT V1** | 替换指针在新 Decision 行上，不另写 relation |

### CREATED_BY 指建议句还是确认句？

**确认句。**

```text
09:20  我建议供应商编码缺失的数据先进异常池。   → RELATED（若后来被确认）
09:21  可以，就按照异常池方案执行。             → CREATED_BY
```

单独建议（没有确认）→ **不建 Decision**，也不预写「草稿 Decision」。建议不是半个 Decision。

`evidence_message_ids` 必须来自本次 Extractor 输入，且必须包含 `current_message.id`。  
建议句 id 可以出现在 evidence 里并落 RELATED；不得把建议句写成 CREATED_BY。

没有 CREATED_BY 的 Decision 不允许写入。

---

## 9. 基数

### Topic : Decision = 1 : N

一个 Topic 下可以先后确认多件不同的事（异常池方案、演示账号），也可以 supersede 同一主题的旧方案。

### Message : Decision

```text
1 Message → 0..N Decision     P5 Decision v1 支持
上限 5 个 extractor decision / 每条消息
```

通常一条确认句只产生 1 个 Decision。两条彼此独立的拍板可以 2 条。同一句话里的一个方案不要拆成多条。

全部绑定 **当前消息的 `topic_id`**（Topic Engine 给出的那一个）。不在 Decision Extractor 里新建 Topic，不跨 Topic 改挂。

---

## 10. Decision identity / supersede 命中

v1 命中手段：

1. Extractor 输入带 `existing_decisions`（当前 Topic 下 status=RECORDED，最多 10 条）。
2. `supersedes_decision_id` 若非空，必须 ∈ 该列表。
3. Prompt：同一事项的方案被明确改口 → NEW_DECISION + supersede 旧 id；禁止静默当同一行 UPDATE。
4. 引擎不做模糊合并。非法 id → 整单失败，不写脏 Decision。

「当前有效」列表给模型时，建议只送 **未被其它 existing 行 supersede 的 RECORDED**（若实现成本高，G1 也可先送最近 10 条 RECORDED 并在 Prompt 中说明 supersede 指针）。推荐前者，减少模型改错对象。

---

## 11. DecisionProcessingRecord（业务幂等）

不得复用 P0 Dedupe、TopicProcessingRecord、TaskProcessingRecord。

同一条 Message 仍可能：离线重放、Topic 成功后第一次跑 Decision、Decision FAILED 重试、将来 Prompt 升级。

```text
DecisionProcessingRecord

message_id                     msg_*
conversation_id                conv_*
topic_id                       当时使用的 topic_*（可空：未跑）
decision_processing_version    1
extractor_prompt_name          DECISION_EXTRACTOR
extractor_prompt_hash          sha256
decision_summary               NEW_DECISION,UNRELATED,... 
decision_ids                   本条成功写入的 dec_* []
processed_at
error
```

主键：`message_id + decision_processing_version`。

规则：

- 已有成功记录（summary 非 FAILED）→ 跳过，不新建
- FAILED 允许同 version 重试
- Prompt 正文 hash 变了 **默认不自动重跑**；升 `decision_processing_version` 才重跑
- Topic 对该消息仍是 FAILED 时：不跑 Decision，也不写成功幂等（否则 Topic 重试成功后 Decision 会被误跳过）
- Task 成功/失败 **不写入** 本记录，也不读取本记录

---

## 12. 生命周期（先设计）

| 事件 | 行为 |
|---|---|
| 删除 Conversation | 删除 `data/decision_store/conversations/{id}/`（G1 提供方法；不改 P3/P4 delete） |
| 删除 Topic | v1 不级联删 Decision |
| 删除 Message | 不删 Decision；Link 保留 message_id；正文以 Topic Store 为准 |
| 保留期限 | v1 不自动过期 |
| 日志 | audit 只存 content preview ≤80 字，不含 API Key / Authorization / 完整 .env |

---

## 13. schema_version

`1`。  
以后若允许写入 `SUPERSEDED` 状态、或增加 `task_id`，升版本并升 `decision_processing_version` 才重抽。
