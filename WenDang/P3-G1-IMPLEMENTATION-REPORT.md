# P3-G1 实施报告

> 日期：2026-09-21  
> 阶段：**P3-G1 IMPLEMENTATION + OFFLINE VALIDATION**  
> 依据：`P3-G1-G0-CURRENT-STATE-CHECK.md`（Gate 0 PASS）

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
P0 / P1 / P2 FROZEN BASELINE CONFIRMED
```

未进入 P3-G2、未进入 P4、未接入真实微信旁路。

---

## 1. 新增文件

| 文件 | 为什么新增 |
|---|---|
| `topic_store.py` | 独立 JSON Topic Store：MessageRecord / Topic / TopicMessageLink / TopicProcessingRecord / audit |
| `topic_engine.py` | 离线流水线：Conversation 解析、预筛、候选检索、校验、落地、失败隔离 |
| `topic_extractor_client.py` | 独立 Extractor 调用与 JSON 解析；测试用 HeuristicTopicExtractor |
| `prompts/extractors/TOPIC_EXTRACTOR.md` | 与 Chat Prompt 物理隔离的 Extractor 正文 |
| `tests/test_topic_store.py` | Gate 1 数据层单测 |
| `tests/test_extractor_prompt.py` | Gate 2 loader / 隔离 / hash / 错误码 |
| `tests/test_topic_engine_offline.py` | Gate 3–5 离线 fixture、失败注入、幂等 |
| `WenDang/P3-G1-G0-CURRENT-STATE-CHECK.md` | Gate 0 只读核对 |

---

## 2. 修改文件

| 文件 | 为什么修改 |
|---|---|
| `conversation_store.py` | **只新增**只读函数 `find_by_platform_conversation_id`。未改 Conversation.id 生成、migration、schema、原有 display_name 查找 |
| `agent_store.py` | **只新增** `resolve_extractor_prompt` 与错误码 `EXTRACTOR_PROMPT_NOT_FOUND` / `EXTRACTOR_PROMPT_EMPTY`。未改 `resolve_chat_prompt` 行为 |

未修改：

```text
message/listener.py
message/identity.py
message/dedupe.py
message/outbound.py
message/trigger.py
message/reply_format.py
bot_runtime.py
prompts/QIYE.md
prompts/企业_1.md
config.local.json
```

---

## 3. 数据模型

```text
InboundMessage  --project-->  MessageRecord
Conversation.id (conv_*)
    ├── MessageRecord[]
    ├── Topic[]                 新建仅 ACTIVE
    ├── TopicMessageLink[]      N:N；(topic_id, message_id, relation) 唯一
    └── TopicProcessingRecord   主键 message_id + topic_processing_version
```

- `MessageRecord.conversation_id` 必须是 `conv_*`，禁止 nickname / display_name 当外键。
- `msg_id = "msg_" + sha1(conversation.id + "|" + (platform_message_id or event_fingerprint))[:12]`
- Extractor v1：一条消息只选 **1** 个主 Topic。不声称 multi-topic。
- 未知字段 `tasks/risks/decisions/assignee/...` 剥离，不落盘。

---

## 4. Store 路径

```text
{root}/data/topic_store/
  conversations/{conversation_id}/
    messages.jsonl
    topics.json
    links.json
    processed.json
  topic_engine_audit.jsonl
```

测试使用临时目录，不写入生产 `config.local.json` / `chat_contexts.json` / CoreMemory。  
提供 `delete_conversation_topic_data(conversation_id)`，删除该会话 Message / Topic / Link / Processed。

---

## 5. Conversation 解析方式

严禁 `Topic.conversation_id = InboundMessage.conversation_id`。

查找顺序：

1. `chat_wxid` → `Conversation.platform_conversation_id`
2. `chat_name` → `Conversation.display_name`（platform=WECHAT）

失败：`CONVERSATION_NOT_RESOLVED`，不创建 Topic，不调 Extractor，写审计后返回。  
离线 fixture 直接传入已解析的 `Conversation` 对象。

---

## 6. Extractor 隔离方式

```text
Chat Prompt          prompts/{name}.md          resolve_chat_prompt
Topic Extractor      prompts/extractors/{name}.md   resolve_extractor_prompt
```

- Chat loader 不递归子目录；`TOPIC_EXTRACTOR` 不出现在 Chat Prompt 下拉框。
- Extractor 失败不 fallback Chat Prompt / 通用助手，不生成微信回复。
- 调用约定：`store_context=false`；默认模型 `INHERIT`；`temperature=0.2`，`max_tokens=800`，独立 timeout 20s。
- Prompt hash = `sha256(全文)`。

---

## 7. Candidate Retrieval 规则

范围：同 `conversation_id`，`status ∈ ACTIVE / WAITING / OPEN`，最多 **5**。  
排序：`reply_to` 命中 ≫ 关键词/领域标签重叠 ≫ `last_message_at`。  
**不能只按时间取最近 5 个**（CASE-05）。  
Recent messages ≤ **12**。不做 embedding / RAG。

---

## 8. 幂等

- MessageRecord：同 `id` / 同 `platform_message_id` upsert 不重复。
- Link：`(topic_id, message_id, relation)` 去重。
- `message_count` 按唯一 message_id 维护，重放不加两次。
- TopicProcessingRecord：成功（含 UNRELATED/SKIPPED）跳过；FAILED 允许同 version 重试。
- **不修改** P0 `DedupeIndex`。

---

## 9. Failure Isolation

任何 LLM timeout / exception / JSON 错误 / Prompt missing|empty / invalid topic_id / invalid evidence / Store 写失败：

- 写 `FAILED` processing + audit
- 不写脏 Topic
- 不调用 `send_reply` / `wx.SendMsg`
- 异常吞在 `TopicEngine.process_*` 边界，`isolated=True`

本轮未接 listener，由单测证明隔离。

---

## 10. 开关

```text
TOPIC_ENGINE_ENABLED = false   # topic_engine.py 模块常量
```

未接 listener，该开关不能改变当前微信收发行为。
