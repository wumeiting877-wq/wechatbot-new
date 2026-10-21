# P1 / P2 下一轮实施计划

> 日期：2026-09-20  
> 状态：等待下一阶段实施指令。本文件不是开工许可。  
> 约束：P0 冻结；不进入 P3～P8；不删 LISTEN_LIST；不大规模改 UI

---

## 1. 目标（实施阶段才做）

```text
谁在被监听
    → Conversation（内部 id + 可选 wxid）
    → 绑定哪个 AgentConfig
    → Agent 使用哪个 Prompt（文件 + hash）
    → 运行时真正生效，缺文件不得换默认助手
```

完成标志：

- 现有 `["ceshi","企业_1"]` 等配置经 Adapter 仍能启动  
- 可暂停单个监听对象  
- 两个对象绑不同 Prompt，真机回复可区分  
- P0 单测 59 项仍 OK，不改 P0 业务文件  

---

## 2. 明确不改的文件（P0 冻结）

除非出现 P0 回归 Bug，否则不要动：

```text
message/identity.py
message/dedupe.py
message/outbound.py
message/trigger.py
message/reply_format.py
message/listener.py          # 可调用，不要改准入顺序
message/pipeline.py          # P0 决策函数；listen_users 语义保持 nickname
bot_runtime.py               # evaluate_inbound / Stop
wxbot.py                     # 仅允许只读使用 chat._wxid；不要改 Self 规则
webui_bot_process.py
tests/test_p0_message_runtime.py
tests/test_runtime_admit.py
tests/test_wechat_reply_format.py
tests/test_webui_bot_process.py
```

`bot.py` 允许 **调用** 现有 `AddListenChat` / `user_names` 投影，禁止重写消息网关与发送 formatter。

---

## 3. 建议实施顺序（四步，仍属 P1/P2）

### 步骤 A — Compatibility Adapter（P1 核心）

新增 Conversation JSON + 从 LISTEN_LIST 导入。

建议文件：

| 文件 | 动作 |
|---|---|
| `conversation_store.py` | **新增**。load/save/migrate_from_listen_list/project_listen_list |
| `app_config.py` | 增加 `CONVERSATIONS` 默认 `[]`；校验；**不要**把 LISTEN_LIST 移出 |
| `config.example.json` | 示例增加空 `CONVERSATIONS` |
| `config_editor.py` | `listen_list_from_form` 保存后跑 migrate；拒绝重复 nickname |
| `tests/test_conversation_store.py` | **新增** |

启动投影（`bot.py` 仅改启动装配，不改 P0 循环）：

```text
conversations = load_conversations()
user_names = [c.display_name for c in conversations if c.enabled]
prompt_mapping = {c.display_name: prompt_name(c) for c in conversations if c.enabled}
```

`keep_alive` / `AddListenChat` 继续吃 `user_names`。

### 步骤 B — enabled + 类型/wxid 回写

| 文件 | 动作 |
|---|---|
| `templates/config_editor.html` | 「已启用」改成 checkbox `enabled`，不做大改版 |
| `static/js/config_editor.js` | 动态行带上 enabled；校验不变 |
| `bot.py` `main()` | `AddListenChat` 成功后把 `chat._wxid`、group/private 写回 Conversation（启动阶段一次） |
| `wxbot.py` | **尽量不改**。若必须从返回的 Chat 读 `_wxid`，只读 |

暂停语义：不投影 → 不监听。不要改 `evaluate_inbound`。

### 步骤 C — AgentConfig + Prompt 完整性（P2 核心）

| 文件 | 动作 |
|---|---|
| `agent_store.py` | **新增**。从现有 prompt 名生成一个 `PROJECT_COLLABORATION` AgentConfig |
| `app_config.py` | `AGENT_CONFIGS` |
| `memory_store.py` `get_user_prompt` | mapping 未命中时 **报错**，不要 `get(..., user_id)` |
| `llm_client.py` | 去掉「你是一个乐于助人的助手。」fallback；返回明确错误或让上层不发送 |
| `webui_data.py` `delete_prompt` / `edit_prompt` | 引用中的 Prompt 禁止删；重命名同步引用或 409 |
| `message/processor.py` | 日志 extra 增加 prompt_name / hash（不要改发送与 P0 准入） |

Prompt 元数据轻量方案：

```text
prompts/QIYE.md
prompts/_meta.json   或 config.local.json 内 PROMPT_VERSIONS
```

先不要 SQLite。

### 步骤 D — 真机 A/B 与回归

1. 新增测试用 Prompt：`QIYE_A.md` / `QIYE_B.md`（可测完删除或留在仓库并标明测试）。  
2. Stop Bot → 两个真实可聊对象分别绑定 A/B → Start。  
3. 真机发消息，确认回复文本。  
4. 交换绑定，再测。  
5. 刷新 WebUI、重启 Bot。  
6. 跑：

```text
python -m unittest tests.test_p0_message_runtime tests.test_runtime_admit tests.test_pipeline tests.test_wechat_reply_format tests.test_webui_bot_process tests.test_webui_data tests.test_p1_p2_audit tests.test_conversation_store
```

P0 59 项必须仍 OK。

---

## 4. 下一轮文件清单（按优先级）

**新增**

```text
conversation_store.py
agent_store.py
tests/test_conversation_store.py
tests/test_agent_prompt_binding.py     # 可扩当前 test_p1_p2_audit.py
```

**修改（非 P0）**

```text
app_config.py
config_editor.py
config.example.json
bot.py                 # 仅启动装配 / 投影 / wxid 回写
memory_store.py        # 去掉隐式 filename fallback
llm_client.py          # 去掉静默默认 Prompt
webui_data.py          # 删除/重命名保护
templates/config_editor.html
static/js/config_editor.js
static/js/prompt_options.js   # 若表单增加 enabled
tests/test_config_save.py
tests/test_webui_data.py
```

**只读 / 调用，不重构**

```text
wxbot.AddListenChat
message.listener.message_listener
bot_runtime.evaluate_inbound
```

**不要创建**

```text
主题中心 / 任务中心 / 风险中心 / 决策中心 / 日报中心 页面
Topic Engine
企业微信 adapter
```

---

## 5. UI 改动上限

允许：

- 监听对象表增加启用开关、只读类型（群/私聊，若已回写）
- Prompt 删除失败时的明确错误文案

不允许：

- 侧栏改名为企业控制台
- 新增大板块导航
- 把趣味实验室做成 Agent 商店
- 重做快速配置流程（除非 Adapter 需要多提交一个隐藏 id）

---

## 6. 风险控制

1. 投影后的 `listen_users` 必须仍是 **display_name / nickname**，与 `chat.who` 一致。  
2. 回写 wxid 失败时保留 nickname 行为，明确打日志，不要改 Self 判断。  
3. 迁移必须幂等：多次启动不得把同一 ceshi 生成多个 Conversation。  
4. 两个监听对象共享同一 Prompt 时，生成 **一个** AgentConfig、两个 Conversation。  
5. 不把 QIYE.md 拆进多个文件，除非步骤 C 明确「Chat Prompt 仍是这一份；Extractor 另建空文件占位」。占位文件不要接入 LLM。

---

## 7. 本轮已完成的审计产物

```text
WenDang/P1-P2-CURRENT-STATE-AUDIT.md
WenDang/P1-CONVERSATION-MODEL-DESIGN.md
WenDang/P2-AGENT-PROMPT-BINDING-AUDIT.md
WenDang/P1-P2-GAP-REPORT.md
WenDang/P1-P2-NEXT-IMPLEMENTATION-PLAN.md
tests/test_p1_p2_audit.py          # 15 tests OK，未改 P0
```

现场快照：

```text
P0 = CLOSED
LISTEN_LIST = [["ceshi","企业_1"],["哈","企业_1"],["QIYE","QIYE"]]
Bot = STOPPED
wechat = disconnected
```

---

## 8. 停止条件

P1/P2 现状已查清。  
Prompt 绑定运行时路径已用隔离测试 + 历史会话证实。  
Conversation / AgentConfig 演进方案已定。  
P3 前置 BLOCKER 已列出。

**停止。等待实施指令。不要自动进入 P3。**
