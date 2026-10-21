# P3 Topic Engine 设计

> 日期：2026-09-20  
> 阶段：P3-G0  
> 对照：`P3-TOPIC-DATA-MODEL-DESIGN.md`、`P3-TOPIC-EXTRACTOR-PROMPT-DESIGN.md`  
> 本文件是设计。**禁止本轮把引擎接到生产微信回复。**

---

## 1. 唯一职责

```text
MessageRecord
    ↓
Topic Engine
    ↓
decision ∈ { NEW_TOPIC, EXISTING_TOPIC, TOPIC_UPDATE, UNRELATED }
```

不负责：

- 是否回复微信（那是 P0 Trigger）
- Task / Risk / Decision
- 主动提醒、日报、RAG、多 Agent

Topic 结果 **不得**绕过 Trigger 调用 `send_reply` / `wx.SendMsg`。

---

## 2. 在现有链路上的位置

保持 P0/P1/P2 主链不变：

```text
微信
 → Message Gateway
 →（REPLY）Conversation → AgentConfig → Chat Prompt → LLM → 微信

旁路（P3，异步、可失败）：
合法入站
 → project MessageRecord
 → Topic Engine
 → Topic Store
 → 仅日志 / 离线查看
```

```text
                    ┌─────────────────────────────┐
                    │  P0 evaluate_inbound        │
                    │  stopped/outbound/self/     │
                    │  system/dedupe/trigger      │
                    └─────────────┬───────────────┘
                                  │
                    EXTERNAL + NEW + 非 system
                                  │
              ┌───────────────────┴───────────────────┐
              │                                       │
              ▼                                       ▼
     Topic Engine 旁路                         现有 Trigger 结果
     （独立 try/except）                       REPLY → Chat
     永不 send_reply                           NO_ACTION → 结束
```

「合法消息」定义（P3 采用，不改 Trigger 枚举）：

```text
bot 可工作（RUNNING / DEGRADED）
AND 非 outbound
AND 非 self
AND 非 system/recall
AND 非 duplicate
AND 能解析到 Conversation.id
AND direction=INBOUND
```

**包含**群内未 @、Trigger=`unauthorized` 的消息。  
否则「当前群正在讨论什么」无法成立（现场 `ACCEPT_ALL_GROUP_CHAT_MESSAGES=false`）。

**不包含**：Stop 后消息、机器人自己的话、重复捕获。

这 **不是** 把 Trigger 改成 `UPDATE_ONLY`。  
`UPDATE_ONLY` 常量保持预留。旁路读取 verdict 的 identity/dedupe/reason，不改 `decide_trigger`。

### 调用点（G1 才写代码，G0 只定边界）

推荐最小挂载：`message_listener` 在 `evaluate_inbound` 返回之后、`action != REPLY` 的 early return **之前**，投入一个 **永不抛向主路径** 的函数。

约束：

- 不改 Self / Dedupe / Outbound / `decide_trigger` 内部
- 不把 Topic 决策映射成 REPLY
- 失败 swallow + 记审计
- 若团队不允许动 `listener.py`：G1 用包装回调，禁止重写网关

这是实施 BLOCKER，见 Gap Report。

**禁止**挂在 `process_user_messages` 之后：那里已经 7 秒合并，丢失消息边界。

---

## 3. 处理流水线

```text
1. Resolve Conversation.id
2. Persist MessageRecord（幂等 upsert）
3. If already processed (success) → return
4. Rule prefilter
      acknowledgement / 空 / 纯表情 → UNRELATED 或 SKIPPED，不调 LLM
5. Retrieve candidate topics（最多 5 个 ACTIVE/WAITING）
6. Build Extractor input（当前消息 + 最近 N 条 + 候选 Topic）
7. Call Topic Extractor（独立 Prompt，独立超时）
8. Validate structured output
9. Apply decision（建 / 挂 / 更新 / 不建）
10. Write processing marker + audit
```

任一步失败：写 FAILED 审计，不写脏 Topic，**不影响 Chat**。

---

## 4. Conversation 解析

不修改 `InboundMessage.conversation_id`。

查找顺序：

1. `chat_wxid` == `Conversation.platform_conversation_id`
2. `chat_name` == `Conversation.display_name` 且 `platform=WECHAT`
3. 都失败 → 不入库、不调用 Extractor，审计 `CONVERSATION_NOT_RESOLVED`

禁止 fallback 成 nickname 字符串当 Topic 外键。

---

## 5. 规则预筛（减少乱建 Topic）

在 LLM 之前：

| 条件 | 结果 |
|---|---|
| content 为空 / 仅空白 | SKIPPED |
| 纯 acknowledgement：收到 / 好的 / 嗯 / 1 / ok / OK / 谢谢 / 收到收到 | UNRELATED，不调 LLM |
| 仅表情 / `[图片]` 且无文字 | UNRELATED 或 SKIPPED |
| 长度过短且无业务名词（≤2 字，非专名） | UNRELATED |
| 其余 | 进候选检索 + LLM |

预筛 UNRELATED 也写 processing marker，保证幂等。

---

## 6. 候选 Topic 检索（不能全量丢给模型）

范围：同一 `conversation_id`，`status in (ACTIVE, WAITING, OPEN)`。  
ARCHIVED / RESOLVED 默认不进候选；若当前消息明显回复某 RESOLVED Topic（reply_to 指向其 CREATED_BY/RELATED 消息），允许额外带回 **1** 个。

排序信号（规则，非向量）：

1. `reply_to_message_id` 落在某 Topic 的 link 上 → 强命中，置顶
2. `last_message_at` 新
3. title / summary 与当前文本的关键词重叠（简单 token / 连续子串，不做 embedding）
4. 同一 sender 刚参与的 Topic 轻微加权

截断：**最多 5 个** 送给 Extractor。  
当前 Demo 同时 3 个 Topic，5 足够。禁止把历史全部 Topic 送进窗口。

---

## 7. Extractor 输入

建议上限（与 `MAX_GROUPS=5` 对齐并略放宽，因为 Extractor 不带 Chat 人格长文）：

| 字段 | 上限 |
|---|---|
| current_message | 1 |
| recent_messages | **12** 条同会话、已入库、按时间 |
| active_topics | **≤5** 候选 |
| 单条 content | 截断 800 字 |
| 单 Topic summary | 截断 400 字 |

不要把 Chat Prompt、记忆 JSON、联网结果塞进 Extractor。

输入形状：

```json
{
  "conversation": {
    "id": "conv_xxxxx",
    "conversation_type": "GROUP",
    "display_name": "QIYE"
  },
  "current_message": {
    "id": "msg_xxxxx",
    "sender_name": "陈总",
    "sender_wxid": "",
    "content": "ERP 增量同步的问题现在解决了吗？",
    "created_at": "2026-09-20T09:05:00+08:00",
    "reply_to_message_id": "",
    "message_type": "text"
  },
  "recent_messages": [],
  "active_topics": [
    {
      "id": "topic_xxxxx",
      "title": "ERP 数据同步异常",
      "summary": "...",
      "status": "ACTIVE",
      "last_message_at": "...",
      "message_count": 4
    }
  ]
}
```

`reason` 只出现在 **输出**，且不得转发微信。

---

## 8. Extractor 输出与校验

```json
{
  "decision": "NEW_TOPIC | EXISTING_TOPIC | TOPIC_UPDATE | UNRELATED",
  "topic_id": null,
  "proposed_title": "",
  "summary_update": "",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence_message_ids": [],
  "reason": ""
}
```

校验（失败 = 整次处理 FAILED，不落 Topic）：

| decision | topic_id | 其它 |
|---|---|---|
| NEW_TOPIC | 必须空或非已存在 id | 必须有 `proposed_title`；系统生成新 id |
| EXISTING_TOPIC / TOPIC_UPDATE | 必须是本次输入里的真实候选 id | 禁止引用未给出的 id |
| UNRELATED | 必须空 | 不得创建 Topic |
| 任意 | | `evidence_message_ids` 必须是已知 message id；当前消息应在列中（UNRELATED 可仅当前） |
| 任意 | | 不得含 `tasks` / `risks` / `decisions` 字段；有则剥离 |
| 任意 | | `confidence` 非法 → 降为 LOW 仍可接受，或 FAILED（G1 选降级） |

JSON 解析：允许从 markdown fence 中取出第一个 JSON 对象。解析失败 → FAILED。

`reason` 只写审计。

---

## 9. 决策落地

### NEW_TOPIC

- 创建 Topic：`status=ACTIVE`，title=`proposed_title`（截断 40 字），summary=`summary_update` 或 title
- Link：当前消息 `CREATED_BY`；evidence 中其它已知消息 `RELATED`
- 不因为人员变化、用词变化而新建

### EXISTING_TOPIC

- 不改 title（v1）
- 不强制改 summary
- Link：`RELATED`
- 更新 `last_message_at`、`message_count`

### TOPIC_UPDATE

- 同 EXISTING，但用 `summary_update` 覆盖/合并 summary（以模型稿为准，长度上限 500 字）
- Link：`UPDATED_BY`
- title 仅当原 title 明显过宽且 `confidence=HIGH` 时允许小改；v1 **建议不改 title**，减少抖动

### UNRELATED

- 零 Topic 写入
- 仍写 MessageRecord + processing marker

---

## 10. 何时 NEW / 回到已有 / UNRELATED

### 创建新 Topic

同时满足：

1. 出现可命名的业务对象（系统、缺陷、活动、方案），不是寒暄
2. 候选列表无法覆盖该对象
3. 不是人员更换、同义词、短时插话
4. 预筛未判 acknowledgement

### 回到已有 Topic

1. 候选命中同一业务对象（即使中间插入过其它 Topic）
2. reply_to 指向该 Topic 的消息
3. 用词不同但对象相同（「接口有问题」/「接口还是不通」）
4. 中断后（甚至隔很多条）仍明确同一对象（「演示账号已经建好了」→ 演示 Topic）

### UNRELATED

- 吃什么、天气闲聊、纯表情
- 收到 / 好的 / 嗯 / 1
- 无法对应任何业务对象且信息量不足以建 Topic
- 与当前企业协作无关的私人闲聊

低置信度允许 `LOW` 并仍可 EXISTING（宁可挂错已有，也不要每条都 NEW）。  
**宁可不建，不要一条消息一个 Topic。**

---

## 11. Topic 状态机（P3 不自动走完）

```text
NEW_TOPIC → ACTIVE

ACTIVE ──(人工或未来规则)──► WAITING
ACTIVE ──(本阶段不自动)──► RESOLVED
RESOLVED ──► ARCHIVED
```

**P3 v1 不自动 RESOLVED。**  
没有可靠「已关闭」证据时，保持 ACTIVE。  
「解决了吗？」不是关闭；「已经修好了」也不自动关闭，除非以后 P4 有独立 Decision 证据。

WAITING / ARCHIVED：只预留，不做自动切换。

---

## 12. 模型调用策略

不复用 Chat Prompt，不把 Extractor 请求写入 `chat_contexts`。

第一版：

```text
默认继承全局 MODEL
AgentConfig 预留：
  extractor_prompt_name
  extractor_model = null | 模型名   # G1 可只加字段，不实现 router
```

调用建议：

- `store_context=False`
- temperature 低于 Chat（0.1–0.3）
- `max_tokens` 够 JSON 即可（~800）
- 独立超时（建议 20s），与 Chat 超时分离
- 不走「Prompt 失败就给用户发系统文案」的 Chat 错误路径

辅助模型 `gpt-4o-mini` 可用于以后降本，**不是** G1 必选项。  
G1 先主模型 + 独立 Prompt，避免再引入路由复杂度。

禁止：Extractor 与 Chat 共用一次 completion。

---

## 13. 失败隔离

```text
Topic Engine failure  ≠  Chat Reply failure
```

| 故障 | Topic | Chat |
|---|---|---|
| API timeout / error | FAILED 审计，不写 Topic | 原样 |
| JSON parse error | 同上 | 原样 |
| invalid topic_id | 同上 | 原样 |
| Prompt missing | 同上，码 `EXTRACTOR_PROMPT_NOT_FOUND` | 原样 |
| Conversation 解析失败 | 不入库 | 原样 |
| Extractor 抛异常 | 吞掉 | 原样 |

Chat 失败也不得回滚已成功的 Topic 写入（两者无事务）。

---

## 14. 幂等

见数据模型 `TopicProcessingRecord`。

额外：

- MessageRecord upsert 按 `msg_id`
- Link 按 `(topic_id, message_id, relation)` 去重
- 禁止因重放把 `message_count` 加两次

---

## 15. 审计日志

每条处理写一行 `topic_engine_audit.jsonl`：

```text
ts
conversation_id
message_id
topic_decision
topic_id
candidate_topic_ids
confidence
evidence_message_ids
extractor_prompt_name
extractor_prompt_hash
model
latency_ms
error
```

禁止：API Key、Authorization 头、完整 `.env`。  
content 如需排障只写 80 字 preview。

可复用 `audit.py` 的 jsonl + lock 形态，但 **文件分开**，不要与管理面审计混用。

---

## 16. 离线验证 vs 生产

P3-G0 / G1 默认：

```text
TOPIC_ENGINE_ENABLED = false   （实施时再加；默认关）
```

离线：读 `tests/fixtures/topic_engine/`，不碰微信、不改 Trigger、不改 Chat Prompt。

允许的验证面：JSON dump 或临时 debug 打印。  
禁止：主题中心页面、Dashboard、任务/风险/日报中心。

---

## 17. 明确不做

- 改 Self / Dedupe / Outbound / Stop / Formatter
- 用 Topic 决定是否回复
- 自动 RESOLVED
- 向量检索 / RAG
- Model Router
- 把 Extractor JSON 塞进 `QIYE.md`
