# P5 Extractor 架构设计

> 日期：2026-09-22  
> 阶段：P5-G0  
> 对照：`P5-CURRENT-STATE-AUDIT.md`、`P5-DECISION-ENGINE-DESIGN.md`、`P5-RISK-ENGINE-DESIGN.md`、`P4-TASK-EXTRACTOR-PROMPT-DESIGN.md`  
> 本文件是架构 + Prompt **设计稿**。本轮不创建生产 Prompt 文件，不改已有三个 Prompt。

---

## 1. 必须隔离的 Prompt 集合

实施后应保持：

```text
Chat Prompt          != Topic Extractor
                    != Task Extractor
                    != Decision Extractor
                    != Risk Extractor
```

| | Chat | Topic | Task | Decision | Risk |
|---|---|---|---|---|---|
| 职责 | 对用户说话 | 在讨论什么 | 谁要做什么 | 最终确认了什么 | 未来可能出什么问题 |
| 文件 | `QIYE.md` 等 | `TOPIC_EXTRACTOR.md` | `TASK_EXTRACTOR.md` | `DECISION_EXTRACTOR.md` | `RISK_EXTRACTOR.md` |
| Loader | `resolve_chat_prompt` | `resolve_extractor_prompt("TOPIC_EXTRACTOR")` | 同左 Task | 同左 Decision | 同左 Risk |
| 失败 | 可能回复用户 | 只记审计 | 只记审计 | 只记审计 | 只记审计 |
| 现状 | 已冻结 | 已冻结 | 已冻结 | **未创建** | **未创建** |

禁止：

```text
把 Decision / Risk schema 写入 QIYE.md / 企业_1.md
写入 TOPIC_EXTRACTOR.md / TASK_EXTRACTOR.md
把新 Prompt 放到 prompts/ 根目录（会进 Chat 下拉框）
复用 topic_extractor_client.parse_extractor_json（STRIP_KEYS 含 decisions/risks）
复用 task 的 parser 作为 Decision/Risk 解析器
store_context=true
改 DEFAULT_EXTRACTOR_PROMPT_NAME
```

`resolve_extractor_prompt` 已按文件名读取 `prompts/extractors/{name}.md`。G1/G3 只需新增文件，**不必改** `agent_store.py`。

独立 LLM client：可复用底层 `get_extractor_response`（`store_context=false`），parser / 允许键 / 禁止 decision 枚举必须各自独立。

---

## 2. 方案比较：独立 Extractor vs 统一 Action Extractor

### 方案 A：独立 Extractor（推荐 v1）

```text
Topic 成功
   ├→ Task Extractor        （已冻结，不改）
   ├→ Decision Extractor    （新）
   └→ Risk Extractor        （新）
```

文件：

```text
prompts/extractors/TASK_EXTRACTOR.md       禁止修改
prompts/extractors/DECISION_EXTRACTOR.md   G1 创建
prompts/extractors/RISK_EXTRACTOR.md       G3 创建
```

优点：职责单一；测试 CASE 清晰；Prompt hash / processing version 独立升级；一类 LLM 失败不污染其它类型；**不解冻 P4**。

缺点：Topic 成功后最多三次抽取调用（Task + Decision + Risk）。Demo 体量可接受。可用规则预筛减少调用（「收到」三套都 UNRELATED 且可短路）。

### 方案 B：统一 Action Extractor

```text
Topic
 ↓
ACTION_EXTRACTOR
 ↓
tasks[] + decisions[] + risks[]
```

优点：少一次或两次模型调用。

缺点（对当前仓库是致命的）：

1. 必须改 `TASK_EXTRACTOR.md` 的输出 schema，或废弃它 —— **P4 COMPLETE / VERIFIED，禁止**
2. `task_extractor_client` 的 `ALLOWED_DECISION_KEYS` / `STRIP_KEYS` / `validate_task_decisions` 全部要重写
3. 一个 JSON 里 Task 非法会导致 Decision/Risk 整单失败，或反过来 —— 失败隔离被破坏
4. Task processing 与 Decision processing 难以再用独立 version/hash
5. 任务书明确：若方案 B 要求修改冻结的 Task 语义，则 **不适合 v1**

**方案 B 判定：不适合 v1。**

不为「架构漂亮」重写 P4。三次调用的成本用独立开关 + 预筛控制。

---

## 3. 推荐运行时扇出

```text
Topic Extractor 成功（已有）
        │
        ├─ Task Extractor        独立 client / 独立 processing
        ├─ Decision Extractor    独立 client / 独立 processing
        └─ Risk Extractor        独立 client / 独立 processing
```

约束：

- 三者 **不能** 决定对方是否运行
- 全部闸门只有：Topic 成功 + 各自 ENABLED 开关
- Risk 可读 OPEN Task 快照，但不 wait Task future
- 禁止 Decision/Risk 自己做 Topic 分类（输入里已经有且仅有一个 `topic`）

---

## 4. Decision Extractor 输入 / 输出

### 输入窗口

```text
conversation            = 1
topic                   = 1
current_message         = 1
recent_topic_messages  <= 12
existing_decisions     <= 10
```

禁止：全群历史、其它 Topic、Chat context、existing_tasks。

### 输出

见 `P5-DECISION-ENGINE-DESIGN.md` §6。  
无 `DECISION_UPDATE`。替换用 `supersedes_decision_id`。

### CREATED_BY 语义（必须写进 Prompt）

```text
建议句 ≠ 确认句
CREATED_BY = 当前确认句
RELATED    = 窗口内被确认的建议 / 方案陈述
单独建议   = UNRELATED，不要预建 Decision
```

---

## 5. Risk Extractor 输入 / 输出

### 输入窗口

```text
conversation            = 1
topic                   = 1
current_message         = 1
recent_topic_messages  <= 12
existing_risks         <= 10
candidate_tasks        <= 10     # OPEN Tasks；可空数组
```

**给 OPEN Tasks：要给，最多 10。**  
不给 Decision 列表。不给全量 TaskMessageLink。

### 输出

见 `P5-RISK-ENGINE-DESIGN.md` §6。  
无 severity。无自动 RESOLVED。

---

## 6. Decision Extractor Prompt 规则稿（G1 落地，G0 不建文件）

建议文件：`prompts/extractors/DECISION_EXTRACTOR.md`

必须遵守：

1. 你不是聊天机器人，不要对群成员说话。
2. 不要重新做 Topic 分类。所有 Decision 属于输入里的唯一 topic。
3. Decision = 明确确认采用/不采用/以什么为准的企业事实。
4. 建议不是 Decision。没有后续确认，不要建。
5. 「收到」「好的」「嗯」「行。」不是 Decision。即使上文有方案也宁可不建。
6. 当前问题事实不是 Decision。Task 指派不是 Decision。Risk 陈述不是 Decision。
7. 确认句才是 CREATED_BY。建议句只能出现在 evidence 里供 RELATED。
8. 禁止输出 status、DECISION_UPDATE、CANCELLED、SUPERSEDED、task_id、severity。
9. 方案被明确改口：NEW_DECISION 且 `supersedes_decision_id` 指向 existing 中同一事项；不要改旧行。
10. `supersedes_decision_id` 必须是 existing_decisions.id 或 null。
11. evidence 必须含 current_message.id，且 id 来自输入。
12. 不确定就 UNRELATED。只输出 JSON。
13. 无确认时 decisions 为一条 UNRELATED。
14. 一条消息最多 5 条；通常 1 条。
15. 禁止编造方案名、系统名、账号；decision_text 必须能从输入原文指认。

正向：D01、D04、D05。  
负向：D02、D03、D06、D07、D08。

---

## 7. Risk Extractor Prompt 规则稿（G3 落地，G0 不建文件）

建议文件：`prompts/extractors/RISK_EXTRACTOR.md`

必须遵守：

1. 你不是聊天机器人，不是定级委员会。
2. 不要重新做 Topic 分类，不要创建 Task / Decision。
3. Risk 必须同时有未来不利结果 + 可识别条件/原因/来源。
4. 「ERP 同步失败了」是当前问题，不是 Risk。
5. 「最好准备一个离线包」是建议，不是 Risk。
6. 「感觉有点危险」不够具体，不建。
7. 「赵凯明天准备离线包」是 Task，不是 Risk。
8. 「收到」不是 Risk。
9. 「Wi-Fi 已经恢复了」即使已有 Risk 也 UNRELATED，不要 RESOLVED，不要 RISK_UPDATE 去关闭。
10. 禁止输出 severity、status、RESOLVED、MITIGATED、CLOSED。
11. `confidence` 只表示抽取把握。
12. `task_id` 可空；只有 existing `candidate_tasks` 里的 id 才能填。
13. 同一担忧更具体 → RISK_UPDATE，不要重复 NEW。
14. evidence 含 current_message.id。不确定则 UNRELATED。
15. 最多 5 条。无风险时一条 UNRELATED。

正向：R01、R04。  
负向：R02、R03、R05、R06、R07、R08。

---

## 8. Parser / 校验隔离要点

| Client | 允许 extractor decision | 必须 STRIP |
|---|---|---|
| Topic（冻结） | NEW_TOPIC / EXISTING_TOPIC / TOPIC_UPDATE / UNRELATED | tasks, risks, decisions, assignee, due… |
| Task（冻结） | NEW_TASK / TASK_UPDATE / UNRELATED | due_at, risks, status, DONE… |
| Decision（新） | NEW_DECISION / UNRELATED | status, task_id, DECISION_UPDATE, severity, CANCELLED |
| Risk（新） | NEW_RISK / RISK_UPDATE / UNRELATED | severity, status, RESOLVED, MITIGATED, CLOSED |

整单 Validate 通过才 apply。与 P4 相同。

Temperature / timeout 与 P3/P4 Extractor 同量级（0.2 / 20s）即可；G1/G3 再定。不得改 Chat timeout。

---

## 9. Prompt 升级

```text
hash 变了 → 默认不重跑已成功 processing
需要重抽 → 升 decision_processing_version 或 risk_processing_version
Topic / Task processing version 不因此升高
```

三套 Extractor 独立升级，避免改 Risk Prompt 重跑全部 Task。

---

## 10. 本轮不创建的生产文件

```text
prompts/extractors/DECISION_EXTRACTOR.md
prompts/extractors/RISK_EXTRACTOR.md
decision_extractor_client.py
risk_extractor_client.py
```

机器可读期望见 `tests/fixtures/p5/`。
