# P4 Task Engine 设计

> 日期：2026-09-21  
> 阶段：P4-G0  
> 对照：`P4-TASK-DATA-MODEL-DESIGN.md`、`P4-TASK-EXTRACTOR-PROMPT-DESIGN.md`  
> 本文件是设计。**禁止本轮实施生产引擎、禁止接微信。**

---

## 1. 唯一职责

```text
已形成的 Topic
    + 当前 MessageRecord
    + 该 Topic 的消息 Evidence
    + 该 Topic 已有 Task
        ↓
Task Extractor
        ↓
0..N 个 NEW_TASK / TASK_UPDATE / UNRELATED
        ↓
Task Store + Audit
```

不负责：

- Topic 分类（P3 已 CLOSED）
- 是否回复微信（P0 Trigger）
- Risk / Decision / Progress / 日报
- 主动提醒、催办、`send_reply`、`wx.SendMsg`
- Dashboard / RAG / 多 Agent

Task 结果不得绕过 Trigger 发微信。

---

## 2. 推荐链路：Topic 成功之后的隔离旁路

任务书要求在 A / B / C 中按 **当前 P3 实现** 选择，不要按架构喜好。

### 方案 A

```text
Topic 成功
    ↓
Task 才执行
```

### 方案 B

```text
Message
 ├ Topic
 └ Task     两者独立旁路
```

### 方案 C

```text
Message
  ↓
Topic
  ↓
Task
```

### 对当前代码的硬事实

1. 研究问题本身就是「**已经形成的 Topic 中**」能否抽出工作事项。方案 B 会在没有 Topic 的消息上抽 Task，等于再做一遍主题/事项分类。
2. `MessageRecord` 只在 `TopicEngine._process_record` 里入库。独立 Task 旁路若自己投影消息，会复制 P3 入库语义，或在 Topic 关闭时写一套平行档案——都在改 P3 边界。
3. Topic 预筛已把「收到 / 中午吃什么 / 表情」标 UNRELATED。独立 Task 旁路要么重复预筛，要么对闲聊抽待办。
4. Topic FAILED（timeout、JSON 错误）时 **不写脏 Topic**（P3-G2 R12 已证）。此时没有合法 `topic_id`。Task 若仍跑，只能伪造归属或退化为会话级待办。
5. Topic 误分类时，Task 绑错主题。这应用 LIMITATION 记录，而不是在 P4 里重做 Topic。
6. 1 Message → N Task 与 Topic 单主决策不冲突：N 个 Task 都挂当前这一个 `topic_id`。

### 推荐

**方案 C 的流水线 + 方案 A 的闸门 + 失败隔离。**

```text
evaluate_inbound
    ↓
Topic Side-path worker          （已有，P3 冻结）
    TopicEngine.process_*
        成功且 decision ∈ { NEW_TOPIC, EXISTING_TOPIC, TOPIC_UPDATE }
        且 topic_id 非空
            ↓  同一 worker 内 try/except，或以后独立 Task 队列
        TaskEngine.process_record   （P4，尚未实施）
            失败 → Task FAILED 审计
            不得改 Topic、不得改 verdict、不得发微信
        其它（UNRELATED / SKIPPED / FAILED / DISABLED）
            → 不跑 Task，不写 Task 成功幂等
```

| Topic 结果 | Task |
|---|---|
| NEW_TOPIC / EXISTING_TOPIC / TOPIC_UPDATE + topic_id | 跑 |
| UNRELATED / SKIPPED | 不跑 |
| FAILED / timeout | 不跑；Topic 日后重试成功后再跑 |
| DISABLED | 不跑（无新 MessageRecord） |
| Topic 误分类 | 跑，但继承错误 topic_id（LIMITATION） |

**Task Engine 失败不影响 Topic。** 已成功的 Topic / Link / TopicProcessing 保持不动。  
**Topic 失败不允许 Task 补跑。** Task 不得创建 Topic。

G1（离线）：测试直接调用 `TaskEngine`，fixture 里预置 Topic + Message + Link，不挂 listener。  
真机挂钩需要改 `topic_sidepath.py` 或 `listener.py`，二者均冻结 → **不属于 G1**，见实施计划 G2 以后。

禁止方案 B 作为 v1：会逼着改 Message 入库，或在无 Topic 时造 Task。

---

## 3. 在现有链路上的位置（实施时）

保持 P0/P1/P2/P3 主链与 Topic 旁路不变：

```text
                    P0 evaluate_inbound
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
     Topic Side-path                    Trigger → Chat / 静默
     （已有）
              │
              │  Topic 成功且有 topic_id
              ▼
     Task Engine（新旁路观察者）
     Store + Audit only
     永不 send_reply
```

G1 连 Topic Side-path 都不改。离线 `process_record(topic, message, ...)` 即可。

---

## 4. 处理流水线（G1 要实现的逻辑，本轮不写代码）

```text
1. 校验 conversation_id、topic_id、MessageRecord 已存在
2. Topic 必须存在且为本会话
3. 若 TaskProcessing 已成功 → return replayed
4. 方向 OUTBOUND → SKIPPED（与 P3 一致，不抽机器人自己的话）
5. 规则预筛
      纯 acknowledgement / 空 → UNRELATED，不调 LLM
6. 组装输入
      current_message
      recent_topic_messages ≤ 12（按 TopicMessageLink ∩ MessageRecord，时间序，不含当前）
      existing_tasks ≤ 10（本 topic OPEN）
      conversation / topic 摘要
7. Task Extractor
8. Validate decisions[]
9. Apply：NEW_TASK / TASK_UPDATE / UNRELATED
10. Write TaskProcessing + audit
```

任一步 Extractor/校验失败：写 FAILED，不写脏 Task，**不影响 Topic**。

---

## 5. Extractor 输入上限

不要把全群历史丢给模型。

| 输入 | 上限 | 原因 |
|---|---|---|
| `conversation` | 1 | id / type / display_name |
| `topic` | 1（当前） | 不重新分类；给 title/summary/status |
| `current_message` | 1 | 裁剪 content ≤ 800 字 |
| `recent_topic_messages` | **≤ 12** | 与 P3 `MAX_RECENT_MESSAGES` 同量级；只含 **本 Topic 已链接** 的消息，避免把权限讨论塞进 ERP Task 窗口 |
| `existing_tasks` | **≤ 10** | Demo 单 Topic 下任务个位数；给满是为了 UPDATE 命中。只 OPEN。排序：正文点名命中 assignee_text 优先，其次 `updated_at` |
| 全会话消息 | **禁止** | P3 已证明会话里同时有多个 Topic |
| 其它 Topic 的 Task | **禁止 v1** | 防止跨主题改挂 |
| sibling topics | **禁止 v1** | 那是变相 Topic 分类 |

`candidate existing tasks` = 就是这 10 条 `existing_tasks`，不另搞检索服务。

---

## 6. Extractor 输出 Schema（v1 最终）

任务书中的 JSON 是候选。按「保守写状态、支持 1 消息多 Task、不自动 DONE」改定：

```json
{
  "decisions": [
    {
      "decision": "NEW_TASK | TASK_UPDATE | UNRELATED",
      "task_id": null,
      "title": "",
      "description": "",
      "assignee_text": "",
      "due_text": "",
      "confidence": "HIGH | MEDIUM | LOW",
      "evidence_message_ids": [],
      "reason": ""
    }
  ]
}
```

| 字段 | 规则 |
|---|---|
| `decisions` | 1..5 条。禁止空数组；无事项时一条 `UNRELATED` |
| `NEW_TASK` | `task_id` 必须 null；`title` 必填；`assignee_text`/`due_text` 可空但受创建规则约束 |
| `TASK_UPDATE` | `task_id` 必须 ∈ 本次 `existing_tasks`；只把出现在原文的字段更新；无新截止不要编 `due_text` |
| `UNRELATED` | `task_id` 必须 null；不写 title |
| `due_at` | **禁止出现**；出现则剥离 |
| `status` / `TASK_COMPLETE` / `DONE` | **禁止**；出现则剥离或整条判非法 |

不采用 `TASK_COMPLETE` 作为 v1 decision：一旦进 Prompt，模型会在「已经处理完了」时推动 DONE。与 P3 不自动 RESOLVED 同一原则。

CASE-T10：期望 `UNRELATED`（或 RELATED 都不写 status）。引擎 **零 status 变更、零 NEW_TASK**。

---

## 7. 状态写入白名单

```text
NEW_TASK     → status=OPEN
TASK_UPDATE  → 不改 status；可改 title/description/assignee_text/due_text
UNRELATED    → 零 Task 写入
```

第一版实际允许写入的状态：**只有 OPEN**。  
IN_PROGRESS / DONE / CANCELLED 不写。

---

## 8. 规则预筛（减少乱建）

在 LLM 之前（可复用 P3 同类集合，但 **不要调用** TopicEngine 内部函数以免耦合；G1 复制常量表）：

| 条件 | 结果 |
|---|---|
| content 空 | SKIPPED |
| 纯 acknowledgement：收到 / 好的 / 嗯 / 1 / ok / OK / 谢谢 / 收到收到 | UNRELATED |
| 仅表情 / `[图片]` | UNRELATED |
| 其余 | 进 Extractor |

「收到，16 点前给结果」**不是**纯 ack，会进 LLM。Prompt 要求：对已有指派的复述确认 → UNRELATED，不 NEW、不把截止再写一遍除非截止变了。

「ERP 同步失败了」会进 LLM，期望 UNRELATED（问题事实 ≠ Task）。不要用关键词「失败」建 Task。

---

## 9. 校验器

独立于 Topic validator。Topic 的 `parse_extractor_json` 会丢掉 `assignee`/`due`，**不能复用**。

校验失败 → 本条消息 Task FAILED，已 apply 的部分若未提交则整单回滚（G1：先 validate 全部 decision 再写盘）。

要点：

- `decision` 枚举
- evidence id ⊆ 输入已知消息，且含 current
- NEW_TASK 无 task_id、有 title
- TASK_UPDATE 的 task_id 合法
- 剥离未知键与 `due_at` / `tasks` / `risks` / `decisions`（此处 decisions 若是「决议」字段）
- `assignee_text` 必须是输入文本中出现过的连续片段，或等于 `current_message.sender_name`（仅当正文有「我…」类自称）。**禁止**输出输入里不存在的人名
- 不得凭空补负责人

---

## 10. Apply 语义

### NEW_TASK

- 插入 Task：`status=OPEN`，字段来自 decision
- Link：当前消息 `CREATED_BY`；evidence 中其它已知消息 `RELATED`
- `due_at=""`
- 不得因为「建议」创建

### TASK_UPDATE

- 按 `task_id` 更新非空字段
- 空字符串表示「本条未提供」，不要用空覆盖已有 `assignee_text`/`due_text`，除非 Prompt 明确说清除（v1 **不支持清除**，避免误删）
- Link：`UPDATED_BY`
- 不改 status、不改 topic_id、不改 conversation_id

### UNRELATED

- 零 Task 写入
- 仍写成功 Processing（本条已分析过，无事项）

---

## 11. 幂等三问

### 同一 Message 重放怎么办？

`TaskProcessingRecord` 成功则跳过。  
重放不得第二条「空值规则」Task（CASE-T05 的亲戚）。

与 Topic 重放独立：Topic 成功重放后，若 Task 尚未成功处理，**应当跑 Task**（G1 离线顺序：先 Topic fixture，再 Task）。  
因此 Processing 主键不能共用 Topic 的 processed.json。

### Extractor FAILED 后怎么办？

同 `task_processing_version` 允许重试。  
不得留下半套 Task：validate 全过再写。

### Prompt 升级后怎么办？

hash 变了默认 **不**自动重抽。  
升 `task_processing_version` 才重跑。避免生产 Prompt 一改就对历史消息批量 NEW_TASK。

---

## 12. 失败隔离

```text
Task 异常
  → EngineResult.decision=FAILED, isolated=True
  → Task audit + FAILED processing
  → 不抛向 TopicEngine / listener / Chat
  → 禁止 send_reply
```

独立超时（建议 20s，可与 Topic 同量级，但用自己的 runtime_control 文件名，**不要**复用 `TOPIC_EXTRACTOR_TIMEOUT_SEC`，以免测 Topic timeout 时误伤/误测 Task）。

G1 源码约束（实施时）：`task_engine.py` / `task_sidepath` 不得出现 `send_reply(` / `wx.SendMsg(`。可仿 P3 的 `engine_source_forbids_wechat_sidepath` 测试。

LLM 调用：`store_context=false`。禁止 `resolve_chat_prompt` / `get_user_prompt`。

---

## 13. 与 Topic / Chat 的模块边界

| 模块 | P4 v1 |
|---|---|
| `task_store.py` | 新建 |
| `task_engine.py` | 新建 |
| `task_extractor_client.py` | 新建（独立 parser） |
| `prompts/extractors/TASK_EXTRACTOR.md` | 新建 |
| `topic_store.py` | **只读使用** 公开方法：`get_topic` / `list_messages` / `links_for_topic` / `get_message` |
| `topic_engine.py` | **不改** |
| `topic_sidepath.py` | G1 **不改** |
| `TOPIC_EXTRACTOR.md` / `QIYE.md` | **不改** |
| `listener.py` 等 P0 | **不改** |

开关（G1 可先模块常量，默认 false）：

```text
TASK_ENGINE_ENABLED = false
```

未接到 listener 时该开关只影响将来；离线测试显式 `enabled=True`。

---

## 14. 核心问题 13 / 14 的答案

**13. Task Engine 失败是否影响 Topic？**  
否。隔离写 Task FAILED。Topic 已成功记录保持。

**14. Topic 失败是否允许 Task 运行？**  
否。无合法 topic_id 则不跑。Topic 重试成功后，因当时没有 Task 成功 processing，可以跑 Task。

---

## 15. 明确不做

```text
Risk / Decision / Progress / Daily Report
Reminder / Notification / 催办 / 发微信
Workflow / Dashboard / RAG / 多 Agent
自动 DONE / 自动 RESOLVED
跨 Topic 改挂 Task
SQLite
改 P3 单主 Topic 为多决策
```
