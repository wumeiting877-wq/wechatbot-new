# P3 Topic Engine 现状审计

> 日期：2026-09-20  
> 项目：wechatbot-new  
> 阶段：**P3-G0**（审计 + 架构设计 + 离线验证基线）  
> 方式：READ ONLY。本轮未改业务代码，未实现 Topic Engine，未进入 P4。  
> 依据：`P0-CLOSURE-REPORT.md`、`P1-P2-CLOSURE-REPORT.md`、`P0-MESSAGE-GATEWAY-DESIGN.md`、`P1-CONVERSATION-MIGRATION-REPORT.md`、`P2-AGENT-PROMPT-INTEGRITY-REPORT.md`、`P1-P2-IMPLEMENTATION-REPORT.md`，以及当前源码。

---

## 0. 冻结基线确认

已完整读取 P0 / P1 / P2 关闭报告与最终设计，并对照当前源码。

```text
P0 / P1 / P2 FROZEN BASELINE CONFIRMED

P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
```

生产绑定（`config.local.json`，2026-09-20 关闭后现场）：

```text
LISTEN_LIST（投影）
  ceshi → 企业_1
  哈    → 企业_1
  QIYE  → QIYE

CONVERSATIONS（权威源）
  ceshi  conv_b35d9b7aaba2  PRIVATE  wxid_rvzydi2xoif022     agt_679873182096
  哈     conv_2f82b3dbce7e  GROUP    51989154176@chatroom    agt_679873182096
  QIYE   conv_6fbe0f455b94  GROUP    58847495172@chatroom    agt_38b43979a544

AGENT_CONFIGS
  agt_679873182096  chat_prompt_name=企业_1  extractor_prompt_name=null
  agt_38b43979a544  chat_prompt_name=QIYE   extractor_prompt_name=null

MODEL = coding-glm-4.7-free
MAX_GROUPS = 5
ACCEPT_ALL_GROUP_CHAT_MESSAGES = false
ENABLE_GROUP_AT_REPLY = true
extractor_prompt_name = null   ← 全部 Agent 仍为预留空值
```

本轮遵守：

- 未修改 Self / Dedupe / Outbound Guard / Stop Bot / PlainText Formatter / Message Gateway / Conversation Migration / Conversation ID / AgentConfig / Prompt Binding / Prompt Integrity / wxid 落盘。
- 未把 Topic JSON 写入 `QIYE.md` / `企业_1.md`。
- 未自动进入 P4 Task / Risk / Decision。

---

## 1. 当前真实链路（已确认）

```text
微信本地库轮询（wechatauto Listener）
    ↓
wxbot.WxMessage
    ↓
message.listener.message_listener
    ↓
inbound_from_wx_message  →  InboundMessage（运行时对象）
    ↓
BotRuntime.evaluate_inbound
        stopped → outbound → self → system → dedupe → decide_trigger
    ↓
    NO_ACTION  →  丢弃，不进处理队列
    REPLY      →  handle_wxauto_message
                      ↓
                 user_queues[display_name]   ← 按 nickname 分键，7 秒合并
                      ↓
                 process_user_messages
                      ↓
                 Conversation（按 display_name 查找）
                      ↓
                 AgentConfig
                      ↓
                 Chat Prompt  prompts/{chat_prompt_name}.md
                      ↓
                 get_deepseek_response（主模型 MODEL）
                      ↓
                 WeChatPlainTextFormatter
                      ↓
                 register_outbound + wx.SendMsg
```

对应代码：

| 层 | 文件 | 现状 |
|---|---|---|
| 网关准入 | `bot_runtime.py` `evaluate_inbound` | P0 冻结。输出 `NO_ACTION` / `REPLY`。`UPDATE_ONLY` 仅常量预留 |
| Trigger | `message/trigger.py` | 不实现 Topic。`UPDATE_ONLY` 未从任何路径返回 |
| 入站对象 | `message/identity.py` `InboundMessage` | 运行时 dataclass。`as_dict()` 只带 `content_preview`，不落盘 |
| 会话查找 | `memory_store.py` `resolve_chat_prompt` | 用 **display_name** 匹配 `Conversation`，再取 `agent_config_id` |
| Chat Prompt | `agent_store.py` | `prompts/{name}.md`。失败码明确，无静默 fallback |
| Extractor | `AgentConfig.extractor_prompt_name` | **恒为 null**。无文件、无 loader、无 LLM 调用 |
| 回复 | `message/processor.py` | 只走 Chat。日志 extra 含 conversation_id / prompt_hash |

**结论：当前项目没有 Topic Engine。**  
P0 为它预留了 `UPDATE_ONLY` 空位；P2 为它预留了 `extractor_prompt_name=null`。两者都未接线。

---

## 2. 已存在、容易被误当成 Topic 的能力

| 能力 | 是不是 Topic | 说明 |
|---|---|---|
| Chat Prompt 里的「主题/任务/风险」口吻 | **否** | `QIYE.md` / `企业_1.md` 是给用户看的回复人格。真机 `chat_contexts.json` 里出现过模型在 **display_reply** 里手写 JSON，那是 Chat 幻觉，不是 Extractor |
| `chat_contexts.json` | **否** | LLM 对话窗口，按 nickname 分键，会裁剪，不是消息档案 |
| `Memory_Temp/*_log.txt` | **否** | 记忆总结原料，按 `nickname_prompt` 命名，无 message id |
| `CoreMemory/*_core_memory.json` | **否** | 摘要 + 重要度，无 Topic 聚类，无 evidence |
| P0 DedupeIndex | **否** | 防微信重复消费，TTL 内存，不是业务幂等 |
| `audit.py` | **否** | 管理面操作审计（改配置 / 紧急停止），不是 Topic 处理日志 |
| 论坛 / 提醒 | **否** | 与会话主题无关 |

`chat_contexts.json` 现场片段（ceshi）曾出现 Chat 模型输出：

```text
"decision": "REPLY",
"topics": [],
"tasks": [],
"risks": [],
"decisions": []
```

这恰好证明：**不能把 Topic JSON 交给 Chat Prompt。**  
P0 Formatter 会撕 Markdown；用户也会看到内部结构。P3 必须另建 Extractor。

---

## 3. Conversation 主键 vs 运行时 conversation_id（关键缺口）

P1 已落地内部主键：

```text
Conversation.id = conv_b35d9b7aaba2   ← 业务必须挂这里
display_name    = ceshi               ← 仅展示 / AddListenChat
platform_conversation_id = wxid_...   ← 微信侧稳定 id
```

P0 `InboundMessage.conversation_id` **不是** 这个值。生成规则：

```text
conversation_id = chat_wxid or chat_name
```

即：优先微信 wxid / `@chatroom`，否则 nickname。  
`message_id` 也是 `platform_message_id` 或 `conversation_id:create_time`。

因此：

```text
P0 InboundMessage.conversation_id   ≠   P1 Conversation.id
```

禁止把 `InboundMessage.conversation_id` 直接写成 `Topic.conversation_id`。  
P3 必须新增 **解析层**（不改 InboundMessage 字段）：

```text
InboundMessage.chat_wxid / chat_name
        ↓  lookup
Conversation.id  (conv_xxxxx)
        ↓
Topic.conversation_id
```

`conversation_store` 现有 `find_conversation_by_display_name`，**没有** `find_by_platform_conversation_id`。实施时需要只读查找函数，不得改 P0 结构。

残留（P1 关闭时已声明，不阻塞 P1，但影响 P3 接线）：

- `chat_contexts` / 记忆文件 / `user_queues` 仍按 nickname 分键
- 微信操作层仍 `AddListenChat(nickname=display_name)`

P3 **不修复** 这些残留。Topic 自己必须挂 `Conversation.id`。

---

## 4. Message 持久化现状

**没有**可长期查询的 Message 实体。

存在的只是：

1. **InboundMessage** — 运行时；过网关后不写入独立 store。`as_dict()` 甚至不含完整 `content`（只有 preview）。
2. **user_queues** — 内存；`QUEUE_WAITING_TIME=7` 秒后 `" ".join(messages)` 合并进 Chat。
3. **chat_contexts.json** — 按 nickname 的 role/content 列表；`MAX_GROUPS=5` → 最多约 10 条（不含 system）。
4. **记忆 log** — 文本行，无稳定 message id。

引用消息：`listener` 把 quote 展成 `[引用<...>消息]: ...` 字符串，**没有** `reply_to_message_id` 字段。

P3 必须设计最小 `MessageRecord`，从 InboundMessage **投影**，禁止重构 InboundMessage。

---

## 5. Prompt Loader 与子目录

Chat Prompt 解析：

```text
os.path.join(root_dir, "prompts", "%s.md" % prompt_name)
```

WebUI 列表 `list_prompt_names()`：

- `os.listdir("prompts")`
- 只收 **当前目录文件** `*.md`
- **不递归子目录**

因此：

- `prompts/extractors/TOPIC_EXTRACTOR.md` **不会**出现在 Chat Prompt 下拉框（有利隔离）。
- 现有 Chat Prompt loader **读不到**子目录。不要为目录结构去重构 Prompt 系统。
- Extractor 需要 **独立 resolve 函数**，不要复用 `resolve_chat_prompt`。
- 若把 `TOPIC_EXTRACTOR.md` 直接放 `prompts/` 根目录，它会进入 Chat 下拉框，存在误绑风险。

现场 Prompt 文件：`AI.md`、`QIYE.md`、`企业_1.md`。无 Extractor 文件。

---

## 6. 存储现状

| Store | 用途 | 适合存 Topic？ |
|---|---|---|
| `config.local.json` | 配置 + CONVERSATIONS + AGENT_CONFIGS + 模型 | **不适合**。Topic/Message 是持续业务数据，会膨胀，且与密钥同文件 |
| `chat_contexts.json` | Chat 窗口 | 否 |
| `CoreMemory/*.json` | 记忆摘要 | 否 |
| `store_io.py` | 带锁原子写 JSON | **可复用机制**，不是数据模型 |
| `audit.jsonl` | 管理面审计 | 可借鉴 jsonl 形态，不要混写 |
| 项目内业务 SQLite | **不存在** | wxbot 只用 sqlite3 **读微信客户端库** |
| PromptVersion 表 | P2 明确未建 | 无 |

数据量（Demo / 当前现场）：3 个 Conversation，监听对象个位数。Topic 实体本身不大；**会增长的是 MessageRecord**。

---

## 7. 模型调用现状

| 用途 | 配置 | 调用入口 |
|---|---|---|
| 主聊天 | `MODEL=coding-glm-4.7-free` | `get_deepseek_response` + Chat Prompt + 上下文 |
| 辅助判断 | `ASSISTANT_MODEL=gpt-4o-mini`（已启用） | `get_assistant_response`，默认 **不带** Chat Prompt |
| 记忆总结 | 可走辅助模型 | `store_context=False` |
| Topic Extractor | **不存在** | — |

`AgentConfig.model_config = "INHERIT"`。无 Model Router。

Chat 路径失败会返回用户可见文案（Prompt 不可用 / AI 暂时不可用）。  
Topic 若误走这条路径，会把 Extractor 错误打进微信。必须物理隔离。

---

## 8. Trigger 与「合法消息」边界

群默认：

```text
ACCEPT_ALL_GROUP_CHAT_MESSAGES = false
ENABLE_GROUP_AT_REPLY = true
```

未 @ 机器人的群消息：`decide_trigger` → `NO_ACTION` / `unauthorized`。  
`message_listener` 在 `action != REPLY` 时 **直接 return**，不进 handler / 队列。

智群 Demo 第一阶段明确：**Agent 不主动回复**，但必须理解整段群讨论。  
若 Topic Engine 只挂在 `REPLY` 之后，Demo 样本几乎全部看不见。

P0 已预留 `UPDATE_ONLY`，但 **禁止本轮改 Trigger 决策表**。  
P3 调用点必须是网关之后的 **旁路**，不能变成新的回复判断器。详见设计文档。

---

## 9. 审计结论（给后续文档用）

1. **没有** Topic 类似能力。只有预留字段与 Chat 幻觉。
2. **没有** Message 业务持久化。必须新增 MessageRecord。
3. **不能**把 Topic 塞进 `config.local.json`。
4. Topic 必须绑 `Conversation.id`；运行时要用查找层，禁止改 P0 InboundMessage。
5. Chat Prompt loader 不支持子目录；Extractor 用独立文件 + 独立 loader。
6. Topic 失败必须与 Chat 失败解耦。
7. P0 Dedupe 不够；需要业务层 processing 幂等。
8. 本轮只设计 + 离线 dataset，不上生产群行为。
