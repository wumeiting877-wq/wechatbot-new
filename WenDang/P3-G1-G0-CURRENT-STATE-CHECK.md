# P3-G1 Gate 0 当前状态核对

> 日期：2026-09-21  
> 阶段：P3-G1 实施前 READ ONLY  
> 方式：对照 P3-G0 文档与当前真实源码，未改业务代码。

---

## 0. 冻结基线

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED

P0 / P1 / P2 FROZEN BASELINE CONFIRMED
```

依据：`P0-CLOSURE-REPORT.md`、`P1-P2-CLOSURE-REPORT.md`、`P3-TOPIC-ENGINE-CURRENT-STATE-AUDIT.md`。  
本轮范围：`P3-G1 = IMPLEMENTATION + OFFLINE VALIDATION`。不进入 P3-G2 / P4，不接真实微信旁路。

---

## 1. 文档与代码是否一致

P3-G0 七份设计文档与当前仓库一致，无结构级偏差。

| 核对项 | 文档结论 | 源码证据 | 一致？ |
|---|---|---|---|
| 1. 不存在正式 Topic Engine | 无 Store / Extractor / Engine | 无 `topic_store.py` / `topic_engine.py` / `topic_extractor_client.py` | 是 |
| 2. `UPDATE_ONLY` 仍只是预留 | Trigger 常量，未返回 | `message/trigger.py` 定义常量；`decide_trigger` 只返回 `NO_ACTION` / `REPLY` | 是 |
| 3. `extractor_prompt_name` 为空、未接 Extractor | Agent 字段恒为 null | `config.local.json` 两个 Agent 均为 `null`；`agent_store.empty_agent_config` 默认 `None`；无 Extractor 文件 | 是 |
| 4. `InboundMessage.conversation_id` 不是 `Conversation.id` | `chat_wxid or chat_name` | `message/identity.py` L119：`conversation_id=chat_wxid or chat_name` | 是 |
| 5. Chat Prompt loader 不负责 Extractor | `prompts/{name}.md`，不递归 | `agent_store.resolve_chat_prompt` 拼 `prompts/%s.md`；`webui_data.list_prompt_names` 只列当前目录 `.md` | 是 |
| 6. 无 MessageRecord 长期业务存储 | 仅运行时 InboundMessage | 无独立消息 jsonl / 业务库 | 是 |
| 7. 无 Topic Store | 推荐 `data/topic_store/` 未建 | 仓库无 `data/` 业务目录 | 是 |
| 8. 无 TopicProcessingRecord | 设计稿 | 源码无此实体 | 是 |
| 9. 无 TopicMessageLink | 设计稿 | 源码无此实体 | 是 |
| 10. P0/P1/P2 测试基线仍在 | P0 59；P1/P2 103 | `tests/test_p0_message_runtime.py` 等仍在；`WenDang/P0-TEST-REPORT.md`、`P1-P2-TEST-REPORT.md` 仍记录基线 | 是 |

其它一致性：

- `conversation_store.py` 有 `find_conversation_by_display_name`，**没有** `find_by_platform_conversation_id`（G1 允许只读新增）。
- 现场 Prompt：`prompts/AI.md`、`QIYE.md`、`企业_1.md`。无 `prompts/extractors/`。
- 离线 fixture 已存在：`tests/fixtures/topic_engine/zhiqun_demo.json`、`boundary_cases.json`。
- 冻结文件未被本轮事前改动：`message/listener.py`、`identity.py`、`dedupe.py`、`outbound.py`、`trigger.py`、`reply_format.py`、`bot_runtime.py`、`prompts/QIYE.md`、`prompts/企业_1.md`。

---

## 2. 发现的偏差

无结构级偏差。

已知且文档已声明、**不阻塞 G1** 的残留（本轮不修）：

1. `chat_contexts` / 记忆 / `user_queues` 仍按 nickname 分键。
2. `InboundMessage.conversation_id` 仍是 wxid/nickname，需 G1 解析层 lookup 到 `conv_*`。
3. `reply_to_message_id` 在真实 listener 中常空（quote 仍是字符串展开）。离线 G1 可在 MessageRecord 上携带该字段。
4. Chat Prompt 仍可能在用户回复里幻觉 JSON。P3 旁路不能也不应靠改 `QIYE.md` 解决。

---

## 3. 是否允许继续 G1

```text
GATE 0 = PASS
允许继续 G1
```

理由：当前确实没有 Topic Engine；P0/P1/P2 冻结基线仍在；真实代码与 P3-G0 文档一致。  
G1 将只新增离线能力，不修改冻结核心，不接入 `message/listener.py`。
