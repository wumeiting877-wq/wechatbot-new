# P3 Topic Engine Gap Report

> 日期：2026-09-20  
> 阶段：P3-G0  
> 依据：`P3-TOPIC-ENGINE-CURRENT-STATE-AUDIT.md`、`P3-TOPIC-DATA-MODEL-DESIGN.md`、`P3-TOPIC-ENGINE-DESIGN.md`、`P3-TOPIC-EXTRACTOR-PROMPT-DESIGN.md`、`P3-TOPIC-TEST-DATASET.md`  
> 分类：BLOCKER / REQUIRED / OPTIONAL / FUTURE / LIMITATION  
> BLOCKER = 不解决不能开始 P3 正式实施（G1）  
> 本轮 **未写业务代码**。下列不是测试 FAIL，是现状缺口。

---

## 1. P3-G0 必须回答的 15 问

### 1. 当前项目是否已经存在 Topic 类似能力？

**否。**  
只有：

- Trigger 常量 `UPDATE_ONLY`（从未返回）
- `AgentConfig.extractor_prompt_name = null`
- Chat Prompt 口吻里的「主题」字样，以及真机 Chat 幻觉 JSON

没有 Topic Store、没有 Extractor 文件、没有 MessageRecord。

### 2. Message 应该如何持久化？

新增 `MessageRecord`，独立 JSONL store。  
从 `InboundMessage` **投影**，不重构 P0 对象。  
主键 `msg_` + sha1(conversation.id + platform_message_id)。

`chat_contexts` / 记忆 log **不**当消息档案。

### 3. Topic 应该使用 JSON 还是 SQLite？

**独立 JSON Store。** 不上 SQLite，不塞 `config.local.json`。  
消息用 jsonl 追加；Topic / links / processed 用 JSON。  
SQLite 留到 Message 量级或 P4 JOIN 真正需要时。

### 4. Topic 主键如何生成？

```text
topic_id = "topic_" + sha1(conversation.id + "|" + created_msg_id + "|" + utc_now)[:12]
```

永久内部 id。禁止 title hash，禁止 nickname。

### 5. Message 与 Topic 是 1:1 还是 N:N？

**存储 N:N（Link 表）。**  
**Extractor v1 每次 1 个主 Topic。**  
不伪装 multi-topic。

### 6. active topics 如何检索？

同 `conversation_id`，status ∈ {ACTIVE, WAITING, OPEN}。  
排序：reply_to 命中 > 关键词重叠 > last_message_at。  
关键词召回是 CASE-05 的必要条件，不能只取最近 5 条时间序。

### 7. 一次给 Extractor 几个候选 Topic？

**最多 5。** 最近消息 **最多 12** 条。禁止全历史。

### 8. Extractor Prompt 如何与 Chat Prompt 隔离？

文件：`prompts/extractors/TOPIC_EXTRACTOR.md`  
独立 loader；不进 Chat 下拉框；不写入 `QIYE.md` / `企业_1.md`。  
调用 `store_context=False`，失败不发微信。

### 9. Topic Engine 失败时如何不影响微信回复？

旁路 try/except；独立超时；不 `send_reply`；失败只记审计与 FAILED marker。  
Chat 路径零依赖 Topic 返回值。

### 10. Topic Processing 如何保证幂等？

`TopicProcessingRecord(message_id, topic_processing_version)`。  
成功则跳过。不改 P0 Dedupe。

### 11. 什么情况下创建新 Topic？

新的可命名业务对象，候选覆盖不了，且不是寒暄/附和/人词替换。

### 12. 什么情况下回到已有 Topic？

同一业务对象、reply_to、同义表述、插话后再续。CASE-03 / CASE-04 / CASE-05。

### 13. 什么消息应该 UNRELATED？

闲聊、acknowledgement、空/表情、无业务对象的短消息。CASE-02 / CASE-06。

### 14. Topic 是否允许自动 RESOLVED？

**P3 v1 不允许。** NEW_TOPIC 只落到 ACTIVE。

### 15. 进入 P3 正式实施前有哪些 BLOCKER？

见下一节。无新的 P0/P1/P2 回归 BLOCKER；P1/P2 原 B1–B3 已关闭。

---

## 2. BLOCKER（G1 开工前必须拍板并实现的最小集）

### B1. Topic 调用点不能只挂在 REPLY 上

现场群策略：未 @ → `NO_ACTION unauthorized`，listener 直接 return。  
Demo 要求理解整段群聊且不主动回复。

G1 必须有 **旁路**：EXTERNAL+NEW 合法入站即投影 Message 并分析，**不**修改 `decide_trigger` 的 REPLY 规则。  
这可能触及冻结文件 `message/listener.py` 的 **最小插入**。  
未授权插入点则 G1 只能做离线 runner，不能接真消息。

**不是**把 Topic 做成新 Trigger。

### B2. Conversation.id 解析层不存在

`InboundMessage.conversation_id` 是 wxid/nickname。  
Topic 必须挂 `conv_*`。  
需要只读 lookup（wxid 优先，其次 display_name）。找不到则跳过分析。  
禁止改 P0 InboundMessage 字段含义。

### B3. 无 MessageRecord / Topic Store

没有持久化就无法 evidence 与幂等。  
G1 必须新建独立 JSON store，禁止写入 `config.local.json`。

### B4. Extractor Prompt 与专用 loader 不存在

`extractor_prompt_name` 全为 null。Chat loader 不读子目录。  
G1 必须新增文件 + `resolve_extractor_prompt`，禁止 fallback 到 Chat Prompt。

---

## 3. REQUIRED（G1 应完成，但不改变冻结模块语义）

| ID | 项 |
|---|---|
| R1 | 结构化输出校验 + 非法 topic_id 拒绝写入 |
| R2 | 规则预筛 acknowledgement |
| R3 | 候选最多 5 + 关键词召回 |
| R4 | 失败隔离与审计 jsonl（无 API Key） |
| R5 | processing 幂等 |
| R6 | 离线 fixture runner：主样本 3 Topic + CASE-01～07 |
| R7 | `TOPIC_ENGINE_ENABLED` 默认 false，生产群行为不变 |
| R8 | AgentConfig 绑定 extractor 名；不改 Chat Prompt 正文 |

---

## 4. LIMITATION（诚实限制，不是缺陷伪装）

| ID | 限制 |
|---|---|
| L1 | v1 一条消息只归属一个主 Topic（CASE-07） |
| L2 | 不自动 RESOLVED / WAITING / ARCHIVED |
| L3 | 无 embedding；长间隔召回靠关键词，可能漏（CASE-05 是必测点） |
| L4 | `reply_to_message_id` 第一阶段常空（quote 目前只是字符串展开） |
| L5 | chat_contexts / 记忆仍按 nickname 分键（P1 残留，P3 不修） |
| L6 | 不接正式 UI |

---

## 5. OPTIONAL

- `extractor_model` 字段预留
- 简单 CLI / JSON dump 查看 Topic
- quote → reply_to 解析增强（不要为了它改 InboundMessage 结构）

---

## 6. FUTURE（禁止本阶段做）

- P4 Task / Risk / Decision
- 日报、主动提醒、RAG、企业知识库、多 Agent
- SQLite / ORM
- 主题中心 / Dashboard
- Model Router
- 自动关闭 Topic
- 重写 QIYE.md / 企业_1.md
- 解冻并重做 Self / Dedupe / Outbound / Stop / Formatter / Gateway

---

## 7. 对冻结模块的影响评估

| 模块 | G1 是否允许改 |
|---|---|
| identity / dedupe / outbound / trigger 决策 | **否** |
| reply_format / Stop / wxid 落盘 / Agent Chat 绑定语义 | **否** |
| `message/listener.py` | 仅允许 **调用旁路** 的最小插入，且须在实施指令中明示 |
| `conversation_store.py` | 允许 **新增** by-wxid 查找，不得改变 id 生成与迁移 |
| `agent_store.py` | 允许接线 `extractor_prompt_name` 与独立 resolve，不得改变 Chat 失败码语义 |
| `llm_client.py` | 允许新增 Extractor 调用函数；禁止改 Chat fallback 行为 |
| `config.local.json` schema | 不把 Topic 数组塞进去 |

---

## 8. 非 BLOCKER 的已知风险

1. Chat 仍可能在用户回复里输出 JSON（P2 未重写 QIYE）。P3 旁路不能阻止 Chat 幻觉，只能保证 Extractor 不走 Chat。  
2. 群消息全量入库会保存真实企业内容 → 按 Conversation 级联删除必须在 G1 实现最小版本。  
3. 若旁路同步调用 LLM，可能拖慢 listener 线程 → G1 应用队列/线程，失败不影响收消息。
