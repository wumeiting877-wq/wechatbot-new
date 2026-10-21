# P1 / P2 实施报告

> 日期：2026-09-20  
> 项目：wechatbot-new  
> 范围：P1 Conversation + P2 Agent / Prompt Binding  
> 对照：`P1-P2-NEXT-IMPLEMENTATION-PLAN.md`  
> **P0 STATUS = CLOSED（本轮未解冻 P0 业务文件）**  
> **P1 STATUS = CLOSED**  
> **P2 STATUS = CLOSED**  
> 关闭报告：`WenDang/P1-P2-CLOSURE-REPORT.md`  
> 未进入 P3 Topic Engine

---

## 1. 目标与结果

本轮关闭进 P3 前的 3 个 BLOCKER 的**代码与自动测试**：

| BLOCKER | 本轮结果 |
|---|---|
| B1 业务 Conversation 主键不再用 nickname | **自动测试 PASS**。内部 `conversation.id` 已落地；ID 不随 display_name 重生 |
| B2 Prompt 丢失禁止静默 fallback | **自动测试 PASS**。已去掉「你是一个乐于助人的助手。」；缺 Prompt 不调用主 LLM |
| B3 Conversation → AgentConfig → Chat Prompt | **自动测试 PASS**。Extractor 仅预留 `extractor_prompt_name=null`，未实现 Topic Extractor |

未进入 P3 Topic Engine。

---

## 2. P0 冻结遵守情况

未修改：

```text
message/identity.py
message/dedupe.py
message/outbound.py
message/trigger.py
message/reply_format.py
message/listener.py
message/pipeline.py
bot_runtime.py
wxbot.py 的 Self 逻辑
webui_bot_process.py
```

允许的调用 / 最小改动：

- `bot.py`：启动装配、LISTEN_LIST 投影、`AddListenChat` 成功后**一次**回写 wxid
- `message/processor.py`：LLM 日志 extra 增加 binding 字段，不改发送与准入
- `llm_client.py` / `memory_store.py`：去掉错误 Prompt fallback

P0 59 tests 复跑：**OK**。

---

## 3. 新增文件

| 文件 | 职责 |
|---|---|
| `conversation_store.py` | Conversation 模型、LISTEN_LIST 迁移、投影、ID 稳定、wxid 回写、重名校验 |
| `agent_store.py` | AgentConfig、Chat/Extractor 边界、Prompt 解析、hash、引用检查 |
| `tests/test_conversation_store.py` | TEST-01～06 |
| `tests/test_agent_prompt_binding.py` | TEST-07～12 |

---

## 4. 修改文件（非 P0）

| 文件 | 动作 |
|---|---|
| `app_config.py` | 默认 `CONVERSATIONS=[]`、`AGENT_CONFIGS=[]` |
| `config.example.json` | 同上 |
| `config_editor.py` | 表单解析 enabled / conversation_id；保存时以 CONVERSATIONS 为权威源并投影 LISTEN_LIST；拒绝重复 display_name |
| `bot.py` | `refresh_conversation_runtime()`；启动预检查不再用 nickname 当文件名；AddListenChat 后回写平台身份 |
| `memory_store.py` | `load_chat_prompt` / `get_user_prompt` 走 AgentConfig，未映射不再 `get(user_id, user_id)` |
| `llm_client.py` | 捕获 `PromptResolveError`，返回统一系统文案，不调用主 LLM |
| `webui_data.py` | 删除引用中的 Prompt → 409 `PROMPT_IN_USE`；禁止直接 rename（方案 A） |
| `templates/config_editor.html` | 启用 checkbox、类型、隐藏 conversation_id |
| `static/js/config_editor.js` | 动态行带 enabled；保存前同步 hidden；删除 409 文案 |
| `static/js/prompt_options.js` | 前端拒绝重复名称 |
| `message/processor.py` | 日志 extra：conversation_id / agent_config_id / prompt_name / prompt_hash |

---

## 5. 数据模型（第一阶段）

Conversation 权威源写入 `config.local.json` 的 `CONVERSATIONS`。  
LISTEN_LIST 仅由 Adapter 投影，供现有 Bot / P0 接口使用。

```text
Conversation
    id, platform=WECHAT, platform_conversation_id
    conversation_type = UNKNOWN | PRIVATE | GROUP
    display_name, enabled
    agent_config_id
    reply_policy=INHERIT, permission_scope=DEFAULT
    metadata.nickname / source=listen_list_v1

AgentConfig
    id, name, agent_type=PROJECT_COLLABORATION
    chat_prompt_name, chat_prompt_hash
    extractor_prompt_name = null    ← 边界，本轮不实现 Extractor
```

第一阶段只实现 WECHAT。未实现其它平台。

---

## 6. 运行时链路（实施后）

```text
CONVERSATIONS (SoT)
      ↓ project_listen_list(enabled=true)
LISTEN_LIST / user_names / prompt_mapping
      ↓
wx.AddListenChat(nickname=display_name)     ← P0 接口不变
      ↓ 启动装配一次
platform_conversation_id = chat._wxid
conversation_type = PRIVATE | GROUP
      ↓
get_user_prompt / load_chat_prompt
      Conversation → AgentConfig → prompts/{chat_prompt_name}.md
      失败：AGENT_CONFIG_NOT_FOUND | CHAT_PROMPT_NOT_BOUND
            | PROMPT_FILE_NOT_FOUND | PROMPT_EMPTY
      不调用主 LLM，不切换默认助手
```

---

## 7. 未做（按计划）

- Topic Engine / Extractor Prompt 正文
- 数据库 PromptVersion
- 大规模 UI / 企业控制台
- 运行中热更新 LISTEN_LIST
- 每 Conversation 独立群触发
- 重写 QIYE.md / 企业_1.md

---

## 8. 关闭门槛对照

| 条件 | 自动测试 | 真机 |
|---|---|---|
| Conversation internal id | PASS | — |
| ID 不随 nickname 改变 | PASS | — |
| platform_conversation_id 落盘 | 单元 PASS（启动回写代码已接） | 需 Start Bot |
| PRIVATE / GROUP 落盘 | 单元 PASS | 需 Start Bot |
| enabled 投影 | PASS | 未跑 |
| nickname 重复拒绝 | PASS | — |
| LISTEN_LIST compatibility | PASS | — |
| AgentConfig + 共享 | PASS | — |
| Prompt 不再静默 fallback | PASS | — |
| Prompt 删除 409 | PASS | — |
| Prompt hash | PASS | — |
| A/B Prompt 真机 | 隔离 PASS | **PASS**（13:56 ceshi=`A-链路正常`，哈=`B-链路正常`） |
| 交换 Prompt 真机 | 隔离 PASS | **PASS**（14:00 互换） |
| enabled 真机 | 单元 PASS | **PASS**（监听 2→3） |
| 缺 Prompt 真机 | 单元 PASS | **PASS**（`PROMPT_FILE_NOT_FOUND`，系统文案） |
| P0 全部回归 | **59 tests OK** | **PASS**（本轮 smoke） |

现场：`Bot=STOPPED`，WebUI `web_pid=19896` 存活，生产绑定已恢复。  
**P1 / P2 CLOSED。禁止进入 P3。**
