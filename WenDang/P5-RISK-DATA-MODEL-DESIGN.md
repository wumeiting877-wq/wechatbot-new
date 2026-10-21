# P5 Risk 数据模型设计

> 日期：2026-09-22  
> 阶段：P5-G0  
> 对照：`P5-CURRENT-STATE-AUDIT.md`、`P5-DECISION-DATA-MODEL-DESIGN.md`、`P4-TASK-DATA-MODEL-DESIGN.md`  
> 本文件是设计，不是已落地代码。本轮不创建 `risk_store.py`。

---

## 1. 设计目标

P5 Risk v1 只回答：

```text
一个已经形成的 Topic 中，有没有明确的未来不利结果？
```

Risk 定义：

> 在可识别的条件 / 原因 / 风险来源下，未来可能发生的不利结果。

不是：当前已经发生的问题、建议、闲聊、应答、工作指派、已确认方案、进度、日报。

最低 Evidence：

```text
必须同时能从输入原文指出：
  1. 未来不利结果（impact）
  2. 条件 / 原因 / 风险来源 之一（condition）
缺一则 v1 不建 Risk
```

绑定规则：

```text
Risk.conversation_id  = Conversation.id     # conv_*
Risk.topic_id         = Topic.id            # topic_*
Risk.task_id          = task_* | ""         # v1 可空
禁止 Risk.conversation = display_name
禁止把 Risk 字段写回 Topic / Task / Decision / Chat Prompt
```

---

## 2. Risk 应该绑定什么

Risk 比 Decision 更复杂，因为现实里既有主题级风险，也有任务级风险。

### 类型 A：Topic Risk

```text
如果 ERP 今天修不好，会影响明天演示。
```

主要属于 Topic。即使还没有「谁去修」的 Task，这句话仍然是 Risk。

### 类型 B：Task Risk

```text
王强如果 17 点前处理不完，会影响今晚回归。
```

可能与某 OPEN Task 有直接关系，但 **句子本身已经是 Risk**。

### 字段方案

| 方案 | 字段 | v1 |
|---|---|---|
| 只绑 Topic | `topic_id` | 不够，缺会话分区 |
| Conversation + Topic | `conversation_id` + `topic_id` | **MUST**，理由同 Task/Decision |
| 再强制 `task_id` | 非空 task_id | **不采用**。会让「无 Task 的主题风险」无法落盘，也会让 Risk 等待 Task 成功 |
| 可空 `task_id` | `task_id` 可空 | **OPTIONAL 采用** |

**v1 允许 `task_id` 可空。**

写入规则：

- 若填写，必须是本次输入 `candidate_tasks` 中的 `task_*`，且属于同一 `conversation_id` + `topic_id`
- 对不上 → 不写 `task_id`，**仍允许**在其它字段合法时建 Risk（宁可主题风险，不可伪造任务外键）
- Task Store 不可用 / Task FAILED / 开关关闭 → `candidate_tasks=[]`，`task_id` 必须空，Risk 照常可建

Risk **本质仍属于 Topic**。`task_id` 是可选引用，不是所有权转移，也不是运行依赖。

---

## 3. 存储方案对比

### 方案 A：独立 JSON Store（推荐）

```text
data/risk_store/
  conversations/{conversation_id}/
    risks.json              Risk 列表
    links.json              RiskMessageLink
    processed.json          RiskProcessingRecord
  risk_engine_audit.jsonl
```

与 P3 Topic / P4 Task / P5 Decision 同一纪律：独立目录、独立失败域、按 `conv_*` 分区。

### 方案 B：统一 `data/action_store/`

不采用。会耦合已冻结的 Task Store，也把 Decision / Risk 成败绑在同一文件树上。

### 方案 C：放进 Topic Store 或 Task Store

不采用。禁止扩大 P3 目录语义；禁止往 `tasks.json` 写 `risk_ids`（P4 已 STRIP）。

### 方案 D：SQLite

不采用。与 P3/P4/Decision 同一判断。不为 P5 引入连接生命周期。

### 推荐

**方案 A。** 不复制消息正文。Risk Evidence 只存 `message_id`。

Decision Store 与 Risk Store **分开**。不要因为都是 P5 就合并成 `action_store`。二者语义、状态机、Extractor、失败域都不同；后续 Gate 还要拆开实施。

---

## 4. 实体总览

```text
Conversation.id
    ├── Topic.id
    │     └── Risk[]                  该主题下的风险（task_id 可空）
    ├── Task[]                        P4，只读引用
    ├── MessageRecord[]               Topic Store
    ├── TopicMessageLink[]            只读窗口
    ├── TaskMessageLink[]             不进 Risk 输入；不复制
    ├── RiskMessageLink[]
    └── RiskProcessingRecord
```

ID 前缀：

```text
risk_xxxxxxxxxxxx
rlink_xxxxxxxxxxxx
```

---

## 5. Risk 字段逐项

| 字段 | v1 | 说明 |
|---|---|---|
| `id` | **MUST** | `risk_` + sha1(conversation_id + topic_id + created_msg_id + ordinal + created_at)[:12]。碰撞 `_2`。禁止 title hash |
| `conversation_id` | **MUST** | `conv_*` |
| `topic_id` | **MUST** | 已存在的 `topic_*` |
| `task_id` | **OPTIONAL 可空** | `task_*` 或 `""`。非法 id 不得写入 |
| `title` | **MUST** | ≤40 字。例如「今日未修复将影响明日演示」。不要只写「有风险」 |
| `description` | **OPTIONAL** | ≤500 字。原文要点，可空 |
| `condition_text` | **MUST** | 条件 / 原因 / 风险来源，从原文抄。例如「如果今天还修不好」「现场 Wi-Fi 不稳定导致断网」 |
| `impact_text` | **MUST** | 未来不利结果。例如「影响明天现场演示」「系统无法演示」 |
| `status` | **MUST** | v1 **只写入 `OPEN`** |
| `severity` | **NOT V1 / FUTURE** | 见 §6。禁止模型写 HIGH/CRITICAL 当企业定级 |
| `severity_text` | **NOT V1** | v1 也不收。避免「很严重」这种无标准文案冒充定级 |
| `confidence` | **MUST** | `HIGH \| MEDIUM \| LOW`，抽取置信度，**不是** 风险等级 |
| `created_msg_id` | **MUST** | 陈述未来不利结果的那条消息 |
| `created_at` | **MUST** | |
| `updated_at` | **MUST** | RISK_UPDATE 可刷新；不改 status |
| `schema_version` | **MUST** | `1` |
| `mitigation_text` | **FUTURE** | 「最好准备离线包」是建议，不是缓解已发生 |
| `owner_text` | **NOT V1** | 负责人属于 Task |

`condition_text` 或 `impact_text` 为空 → 不建 Risk。  
当前问题句只有 impact 的现在时（「ERP 同步失败了」）→ 不建。

---

## 6. severity 是否进入 v1

候选枚举：`LOW | MEDIUM | HIGH | CRITICAL`。

**不进入 v1。**

原因：

1. 项目没有企业风险定级标准（无资产清单、无影响金额、无演示 SLA 编码）。
2. MessageRecord 只能提供自然语言。模型没有足够 Evidence 区分 HIGH 与 CRITICAL。
3. 一旦落盘，下游很容易把模型口吻当成管理结论。
4. `confidence` 已经表达抽取把握，不要再叠一套等级。

`severity` / `severity_text` = **FUTURE**。  
Extractor 输出这些键：校验器丢弃，不失败整单（除非同时缺 condition/impact）。

---

## 7. 状态机

```text
OPEN  →  MITIGATED  →  RESOLVED
  │                       │
  └→ CLOSED ←─────────────┘
```

| 状态 | v1 写入 | 说明 |
|---|---|---|
| OPEN | **允许（唯一）** | NEW_RISK 落地状态 |
| MITIGATED | 只读预留 | 不写 |
| RESOLVED | 只读预留 | **禁止**因为「Wi-Fi 已经恢复了」自动 RESOLVED |
| CLOSED | 只读预留 | 不写 |

对齐：

```text
P3 v1 不自动 RESOLVED
P4 v1 不自动 DONE
P5 Risk v1 不自动 MITIGATED / RESOLVED / CLOSED
```

RISK_UPDATE **不改 status**。  
模型若输出 `RISK_RESOLVED` / `CLOSED`：非法或映射为不写盘的 UNRELATED，**不得**改 status。

---

## 8. Risk 是否可更新

Risk 更接近 Task（进行中的担忧），而不是 Decision（已冻结事实）。

允许 v1：

```text
NEW_RISK | RISK_UPDATE | UNRELATED
```

| 动作 | 行为 |
|---|---|
| NEW_RISK | 当前 Topic 下没有可命中的同一担忧 → 新建，status=OPEN |
| RISK_UPDATE | 命中 existing OPEN Risk，只可改 `title` / `description` / `condition_text` / `impact_text` / `confidence` / 可选补 `task_id`（仅空→非空且合法）。**不改 status** |
| UNRELATED | 当前问题、建议、完成陈述、收到、纯 Task 指令 |

「Wi-Fi 已经恢复了」即使已有「断网无法演示」Risk → **UNRELATED**，保持 OPEN。完成/解除陈述不是 v1 的关闭通道。

同一担忧的条件被说得更具体（「如果今天修不好」→「如果今晚 8 点前修不好」）→ RISK_UPDATE，不要第二条 NEW_RISK。

---

## 9. RiskMessageLink

```text
RiskMessageLink

id              rlink_{12 hex}
risk_id         risk_*
message_id      msg_*          必须已存在于 Topic Store MessageRecord
relation        CREATED_BY | RELATED | UPDATED_BY
confidence      HIGH | MEDIUM | LOW
created_at
```

联合唯一：`(risk_id, message_id, relation)`。

| relation | v1 | 何时 |
|---|---|---|
| CREATED_BY | **使用** | NEW_RISK 的当前消息（必须含未来不利结果）。每个 Risk 恰好一条 |
| RELATED | **使用** | 支撑条件的上文，例如「现场 Wi-Fi 现在不稳定」 |
| UPDATED_BY | **使用** | RISK_UPDATE 的当前消息 |
| MITIGATION_EVIDENCE | **NOT V1** | 会诱使写成已缓解 |
| RESOLUTION_EVIDENCE | **NOT V1** | 会诱使自动 RESOLVED |

没有 CREATED_BY 的 Risk 不允许写入。  
不复制消息正文。

---

## 10. 基数

```text
Topic : Risk     = 1 : N
Message : Risk   = 1 : 0..N     上限 5 个 extractor decision / 每条消息
Task : Risk      = 0..1 : 0..N  可空；一个 Task 可被多条 Risk 引用（v1 不强制唯一）
```

一条消息可以同时是 Task 指令 + Risk（M02）。Risk 仍全部挂当前 `topic_id`。

同一条件+同一影响不要拆两条。不同影响可以两条（v1 Prompt 偏保守：不确定则合并或 UNRELATED）。

---

## 11. Risk identity / 更新命中

1. 输入 `existing_risks`：当前 Topic 下 OPEN，最多 10 条。
2. `RISK_UPDATE.risk_id` 必须 ∈ 该列表。
3. 可选 `candidate_tasks` 最多 10 条 OPEN Task，供填写 `task_id`。
4. 引擎不做模糊合并。非法 `risk_id` → 整单失败。

---

## 12. RiskProcessingRecord

独立业务幂等。不得复用 P0 Dedupe / TopicProcessing / TaskProcessing / DecisionProcessing。

```text
RiskProcessingRecord

message_id                 msg_*
conversation_id            conv_*
topic_id                   当时 topic_*（可空：未跑）
risk_processing_version    1
extractor_prompt_name      RISK_EXTRACTOR
extractor_prompt_hash      sha256
decision_summary           NEW_RISK,RISK_UPDATE,UNRELATED,...
risk_ids                   本条成功写入/更新的 risk id[]
processed_at
error
```

主键：`message_id + risk_processing_version`。

规则：

- 成功（非 FAILED）→ 跳过
- FAILED 允许同 version 重试
- Prompt hash 变了默认不重跑；升 version 才重跑
- Topic FAILED → 不跑、不写成功幂等
- Task FAILED → **仍跑** Risk；不把 Task 失败写进本记录当成功

---

## 13. 生命周期

| 事件 | 行为 |
|---|---|
| 删除 Conversation | 删除 `data/risk_store/conversations/{id}/` |
| 删除 Topic | v1 不级联删 Risk |
| 删除 Task | v1 不删 Risk；`task_id` 可变成悬空引用（LIMITATION，G1 不修） |
| 删除 Message | 不删 Risk；Link 保留 message_id |
| 日志 | preview ≤80 字；禁止 API Key / Authorization / 完整 .env |

---

## 14. schema_version

`1`。  
以后加 severity、写 RESOLVED、必填 task_id 都升版本，并升 `risk_processing_version`。
