# P2 Agent / Prompt 完整性报告

> 日期：2026-09-20  
> 对照：`P2-AGENT-PROMPT-BINDING-AUDIT.md`  
> 本轮不实现 Topic Extractor，不建数据库 PromptVersion  
> **P2 STATUS = CLOSED**（真机见 `P1-P2-CLOSURE-REPORT.md`）

---

## 1. 绑定关系

```text
Conversation
    → AgentConfig (PROJECT_COLLABORATION)
        → chat_prompt   (prompts/{name}.md + sha256)
        → extractor_prompt_name = null   （预留，未接入 LLM）
```

多个 Conversation 可共享同一 AgentConfig。

真实数据：

```text
ceshi ──┐
        ├── AgentConfig(企业_1)
哈    ──┘
QIYE ──── AgentConfig(QIYE)
```

TEST-07：ceshi 与 哈只有一个 AgentConfig。**PASS**。幂等：再跑 `ensure_agents_for_conversations` 不会复制。

---

## 2. 静默 fallback 已取消

已删除 `llm_client` 中：

```text
FileNotFoundError → "你是一个乐于助人的助手。"
```

`get_user_prompt` 不再：

```text
prompt_mapping.get(user_id, user_id)
```

失败码：

| 条件 | 错误码 |
|---|---|
| Conversation 无 AgentConfig / 未映射 | `AGENT_CONFIG_NOT_FOUND` |
| Agent 无 chat_prompt_name | `CHAT_PROMPT_NOT_BOUND` |
| md 不存在 | `PROMPT_FILE_NOT_FOUND` |
| md 为空 | `PROMPT_EMPTY` |

以上情况：

- 不调用主 LLM
- 不切换默认助手
- 返回统一系统文案：`当前智能体配置不可用，请检查 Prompt 配置。`（非 LLM 生成）

TEST-08 / TEST-09：**PASS**。

---

## 3. 删除保护与改名

删除正在被 AgentConfig（或 LISTEN_LIST 投影）引用的 Prompt：

```text
HTTP 409
error = PROMPT_IN_USE
message = 该 Prompt 正被以下 Agent 使用，不能删除。
```

TEST-10：**PASS**（单元）。

真机 TEST-LIVE-08（Bot STOPPED，临时 Prompt 仍被 `agt_6403ddd8c317` 引用）：

```text
POST /delete_prompt/P1P2_TEST_A.md
HTTP 409
error = PROMPT_IN_USE
message = 该 Prompt 正被以下 Agent 使用，不能删除。
agents = ["智群 · 项目协同 Agent · P1P2_TEST_A"]
```

当时文件仍在。恢复生产绑定、解除引用后才删除 `P1P2_TEST_A` / `P1P2_TEST_B`。正式 `QIYE.md` / `企业_1.md` 未改、未删。

TEST-LIVE-01 / 02 / 03（A/B 真机回复与交换绑定）：**PASS**（2026-09-20 13:56–14:00，主模型 `coding-glm-4.7-free`）。  
TEST-LIVE-09（缺 Prompt 无 fallback 真机）：**PASS**。14:12:12 `PROMPT_FILE_NOT_FOUND`；outbound「当前智能体配置不可用，请检查 Prompt 配置。」；无 `main/main_chat 成功`。单元 TEST-08 / TEST-09 仍 **PASS**。

Prompt 改名：方案 A。

- 后端拒绝 rename
- 编辑页文件名只读
- 需要新名字：另存为新 Prompt

避免「文件改名成功但 AgentConfig 仍指向旧名」。

---

## 4. Prompt hash

保存 Prompt 时计算 SHA-256，写入引用该文件的 `AgentConfig.chat_prompt_hash`。

每次主聊天 LLM 调用，日志 extra 包含：

```text
conversation_id
agent_config_id
prompt_name
prompt_hash
```

TEST-11 / TEST-12：**PASS**（单元）。未建 PromptVersion 表。  
真机 CHAT_PROMPT extra：

```text
ceshi  conversation_id=conv_b35d9b7aaba2 agent_config_id=agt_6403ddd8c317
       prompt_name=P1P2_TEST_A prompt_hash=3b37c5035b63539a8e348cabf51d7609ba777c61220a289785d36cb71ed30c10
哈     conversation_id=conv_2f82b3dbce7e agent_config_id=agt_679873182096
       prompt_name=P1P2_TEST_B prompt_hash=afc3452bdde9c402339e657e64d6b0b4bba5a75cfdb30d7dbb86aeadaa3bc645
```

---

## 5. Chat Prompt 职责边界

本轮未重写 QIYE.md / 企业_1.md。

代码继续负责：

- Self / Dedupe / Outbound Guard / Stop / Markdown Formatter / Message Trigger

Chat Prompt 只应负责角色、回答内容、风格、业务原则。

Topic / Task / Risk JSON **未**写入 Chat Prompt。Extractor 字段为 null，未创建 Extractor 文件，未接入 LLM。
