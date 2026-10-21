# P1 / P2 当前状态审计

> 日期：2026-09-20  
> 项目：wechatbot-new  
> 范围：P1「群 / 监听对象」+ P2「Agent / Prompt 绑定」  
> 方式：READ / AUDIT + 隔离运行时测试  
> **P0 STATUS = CLOSED**（依据 `P0-CLOSURE-REPORT.md`；本轮未改 P0 业务代码）

---

## 0. 审计前提

已读取：

- `WenDang/P0-CLOSURE-REPORT.md`
- `WenDang/P0-REMAINING-RISKS.md`
- `WenDang/P0-MESSAGE-GATEWAY-DESIGN.md`
- `WenDang/P0-IMPLEMENTATION-REPORT.md`
- `智群-企业消息协同智能体-Demo与开发实施方案-V1.0 (1).md` 第 35、36 节

确认：

```text
P0 STATUS = CLOSED
P0 已冻结
真实微信最终回归 12 项 PASS
相关自动测试 59 tests, OK
```

本轮未进入 P3～P8，未改 Self / Dedupe / Outbound Guard / Loop Guard / Stop Kill Switch / Message Gateway / 微信纯文本 formatter / Stop-Start 生命周期。

现场探测（2026-09-20 10:31 后）：

```text
GET /bot_status  → 200
state            → STOPPED
wechat           → disconnected
listen_count     → 3
pid              → null
GET /api/prompts → {"ok": true, "prompts": ["AI", "QIYE", "企业_1"]}
```

因此 **TEST-P2-01～03 真机发送未执行**。未伪造 PASS。运行时绑定由隔离测试 + 历史 `chat_contexts.json` 交叉确认。

---

## 1. 当前 LISTEN_LIST 真实结构

`config.local.json` 现场值：

```json
"LISTEN_LIST": [
  ["ceshi", "企业_1"],
  ["哈", "企业_1"],
  ["QIYE", "QIYE"]
]
```

结构是二维数组，每一行：

```text
[ nickname_or_group_name, prompt_filename_without_md ]
```

没有第三列。没有：

```text
id / platform / platform_conversation_id / conversation_type
enabled / agent_id / permission_scope / reply_policy
created_at / updated_at
```

类型：`list[list[str, str]]`。私聊与群聊使用 **同一结构**。占位文案是「微信昵称 / 群名称」。

---

## 2. LISTEN_LIST 完整链路

```text
prompts/*.md
        │
        ▼
webui_data.list_prompt_names()
        │
        ▼
GET /api/prompts  +  templates/config_editor.html 首屏 Jinja
        │
        ▼
static/js/prompt_options.js
  fillPromptSelect(select[name=prompt_file])
        │
        ▼
机器人管理 / 监听对象表格
  input[name=nickname] + select[name=prompt_file]
  状态列写死「已启用」（不是开关）
        │
        ▼
前端 PromptOptions.validateListenRows()
        │
        ▼
POST /submit_config
  若 bot_process 仍在跑 → 400 BOT_RUNNING（必须先 Stop）
  listen_list_from_form(nicknames, prompt_files)
        │
        ▼
app_config.save_config() → config.local.json LISTEN_LIST
  若某行 Prompt 变更 → 删除 chat_contexts.json 中该 nickname 的上下文
        │
        ▼
Bot 启动  from config import *
  user_names     = [entry[0] for entry in LISTEN_LIST]
  prompt_mapping = {entry[0]: entry[1] for entry in LISTEN_LIST}
        │
        ▼
启动预检查
  prompts/{prompt_file}.md 不存在 → FileNotFoundError，拒绝启动
        │
        ▼
wx.AddListenChat(nickname=user_name, callback=message_listener)
  wxbot._resolve_uname(nickname)
    search_contact(nickname)
    精确匹配 nick_name 或 remark → username(wxid / xxx@chatroom)
  self.listen[nickname] = (chat, callback)     ← 监听字典 key 仍是 nickname
        │
        ▼
message_listener(msg, chat)
  who = chat.who                               ← nickname
  inbound.conversation_id = chat_wxid or chat_name   ← P0 消息层有 wxid
  evaluate_inbound(listen_users=user_names)    ← 匹配的仍是 nickname
        │
        ▼
handle_wxauto_message / process_user_messages
  user_id = who = nickname
        │
        ▼
get_deepseek_response(message, user_id)
  get_user_prompt(user_id)
    prompt_file = prompt_mapping.get(user_id, user_id)
    每次读取 prompts/{prompt_file}.md
    作为 LLM system message
```

补充：`keep_alive` 每 5 秒按 `user_names` 对比 `wx.listen.keys()`，丢失则用同一 nickname 再 `AddListenChat`。

---

## 3. 对 P1 十四个问题的直接回答

| # | 问题 | 答案 |
|---|---|---|
| 1 | LISTEN_LIST 当前实际数据结构？ | `[[str nickname, str prompt_name], ...]` |
| 2 | 私聊与群聊是否同一结构？ | 是。配置层不区分。运行时用 `chat._wxid.endswith("@chatroom")` 或 `ChatInfo.chat_type` 判断 |
| 3 | 是否有唯一 ID？ | 配置层无。P0 入站消息有 `chat_wxid` / `platform_message_id`，但 **不回写配置** |
| 4 | 是否完全依赖 nickname？ | 配置、监听注册、队列、上下文、Prompt key **全部依赖 nickname**。底层解析能拿到 wxid，但只用一次 |
| 5 | nickname 修改后会怎样？ | 配置对不上 → `AddListenChat` 失败并 `sys.exit(1)`；或匹配到同名另一个会话。旧 `chat_contexts.json` 键成为孤儿 |
| 6 | 是否保存平台身份？ | 否。`platform` 不存在。解析到的 `username` / `@chatroom` 不落盘 |
| 7 | 是否保存 conversation type？ | 否。运行时缓存 `group_chat_cache[user_name]=bool`，进程内有效 |
| 8 | 是否保存 enabled？ | 否。UI「状态」列写死「已启用」 |
| 9 | 能否暂停单个监听对象？ | **不能**。只能从 LISTEN_LIST 删除整行，或全局 Stop Bot |
| 10 | 能否给不同监听对象配不同策略？ | Prompt 可以不同。群触发 / 回复频率 / 冷却是 **全局** `ENABLE_GROUP_AT_REPLY` 等，不是按对象 |
| 11 | 是否存在重复监听对象？ | 当前三行 nickname 互不相同。表单 **允许** 重复 nickname；`prompt_mapping` 字典后者覆盖前者 |
| 12 | 是否存在 nickname 冲突？ | 当前数据无冲突。`AddListenChat` 对已监听的同一 nickname 返回失败「该聊天已监听」 |
| 13 | 群名重复导致错误匹配风险？ | **有**。`_resolve_uname` 在 `search_contact` 结果里取 **第一个** `nick_name` 或 `remark` 精确相等的 `username` |
| 14 | 当前 Prompt 到底绑定在哪里？ | 绑定在 `LISTEN_LIST[i][1]`，运行时 `prompt_mapping[nickname]`。不是 AgentConfig |

---

## 4. 当前结构图

```text
┌─────────────────────────────────────────────────────────────┐
│ config.local.json                                           │
│   LISTEN_LIST: [[nickname, prompt_name], ...]               │
│   群策略全局: ACCEPT_ALL / ENABLE_GROUP_AT_REPLY / 关键词     │
└───────────────────────────┬─────────────────────────────────┘
                            │ Bot 启动 import 一次
                            ▼
┌──────────────┐   nickname    ┌──────────────────────────────┐
│ user_names[] │──────────────►│ wx.listen[nickname]          │
│              │               │   chat._wxid  （仅内存）       │
└──────┬───────┘               └──────────────┬───────────────┘
       │                                      │
       │ prompt_mapping[nickname]=prompt_name │ who=nickname
       ▼                                      ▼
┌──────────────────────┐            ┌─────────────────────────┐
│ prompts/{name}.md    │◄───────────│ get_user_prompt(who)    │
│ 文件名即 Prompt ID    │  每次LLM读  │ LLM system message      │
└──────────────────────┘            └─────────────────────────┘

P0 消息层另有一条身份线（不驱动配置）：

  chat._wxid  →  InboundMessage.conversation_id
              →  Dedupe / Outbound Guard
              ✗ 不用于 LISTEN_LIST / Prompt 查找
```

---

## 5. 「昵称作为主键」风险 — CONFIRMED

下列全部以 nickname 为 key：

| 用途 | 字段 |
|---|---|
| 配置主键 | `LISTEN_LIST[][0]` |
| Prompt 查找 | `prompt_mapping[nickname]` |
| 微信监听注册 | `wx.listen[nickname]`、`AddListenChat(nickname=...)` |
| 触发名单 | `listen_users=user_names`，`decide_should_process(who)` |
| 消息队列 | `user_queues[who]` |
| 会话上下文 | `chat_contexts.json["ceshi"]` |
| 记忆日志 | `{user}_{prompt_name}_log.txt` |
| 自动消息计时器 | `user_timers[user]` |

```text
conversation identity == nickname     CONFIRMED
```

后果：

1. 同名好友：`search_contact` 取第一条精确匹配，可能听错人。  
2. 同名微信群：群 `username` 是 `xxx@chatroom`，但配置不保存，只存群名。  
3. 群改名 / 好友改昵称 / 备注变化：监听注册失败或听错窗口。  
4. 私聊名与群名相同：类型判断依赖 wxid 后缀，配置层无法预知。

**底层其实能拿到更稳定字段**，见下一节。本轮不改微信底层。

---

## 6. wechatauto 当前能提供的稳定字段

`contact.db` / `search_contact` 返回：

```text
username     微信 wxid 或 xxx@chatroom     ← 相对稳定的平台会话 ID
nick_name    昵称 / 群名
remark       备注
alias        微信号（搜索条件，未写入项目配置）
```

`Chat.ChatInfo()`：

```text
chat_name = self.who          # 仍是传入的显示名
chat_type = 'group' if _wxid.endswith('@chatroom') else 'friend'
```

`WxMessage` / P0 `InboundMessage` 已有：

```text
chat_wxid
sender_wxid
platform_message_id = "{chat_wxid}:{local_id}"
conversation_id     = chat_wxid or chat_name
```

结论：第一阶段不必等微信再开新 API。解析瞬间就能得到 `username`。缺的是 **配置层持久化**，不是底层完全没有 ID。

---

## 7. P1 完成情况（不打分）

**已具备**

- 可配置多个监听对象，当前 3 个：`ceshi` / `哈` / `QIYE`
- 每个对象可绑定不同 Prompt 文件名
- WebUI 增删改 + 保存校验（空名称 / 空 Prompt 拒绝提交）
- Bot 启动按名单 `AddListenChat`
- 运行时能区分群 / 私聊（wxid `@chatroom`）
- 全局群触发：@ / 关键词 / 全量
- P0 入站已有 `chat_wxid`（未接到配置）

**缺失**

- Conversation 实体与内部 ID
- 持久化 `platform` / `platform_conversation_id`
- 持久化 `conversation_type`
- 单对象 `enabled` / 暂停
- 每对象 `agent_config_id` / `reply_policy` / `permission_scope`
- nickname 冲突校验
- LISTEN_LIST → Conversation 兼容适配器
- 配置热更新（LISTEN_LIST 不在 `HOT_RELOAD_KEYS`；运行中禁止保存）

---

## 8. P2 完成情况（不打分）

**已具备**

- `prompts/*.md` 作为 Prompt 仓库，文件名即 ID
- `GET /api/prompts` 与 Prompt 管理同一目录
- `LISTEN_LIST → Prompt` 绑定写入 `config.local.json`
- 刷新 WebUI 后绑定仍在（配置层）
- 重启 Bot 后绑定仍在（import 时重读配置）
- **运行时确实使用用户选择的 Prompt**（见第 9 节）
- 启动时缺文件拒绝启动
- 前端删除后显示「原 Prompt 已不存在」，不偷偷改绑

**缺失**

- AgentConfig（Agent ≠ Prompt）
- PromptVersion / content_hash / DRAFT-ACTIVE-ARCHIVED
- 回复记录中的 Prompt 版本
- 重命名 Prompt 后自动改绑定
- 删除正在绑定的 Prompt 时阻止或明确失效
- 运行时缺文件禁止静默 fallback（见 llm_client）
- 每 Agent 的 model / temperature / context_policy / reply_policy

当前形态是 **「Prompt 文件绑定」**，不是 Agent 配置。

---

## 9. Prompt 绑定是否真实运行生效

**是，配置层和运行时都生效。但当前 ceshi 绑定的不是 QIYE。**

证据 A — 配置：

```text
ceshi → 企业_1
哈    → 企业_1
QIYE  → QIYE
```

证据 B — 历史真机会话 `chat_contexts.json["ceshi"]`：

助手自称「企业战略与业务分析顾问」，与 `prompts/企业_1.md` 一致。  
未出现 `prompts/QIYE.md` 中的「智群 · 企业消息协同智能体」。

证据 C — 隔离测试 `tests/test_p1_p2_audit.py`（15 tests, OK）：

- `user_a → QIYE_A` 读到 `A-链路正常`
- `user_b → QIYE_B` 读到 `B-链路正常`
- 交换 mapping 后立即互换
- 修改 md 内容，下一次 `get_user_prompt` 即读到新内容（无内存缓存）

证据 D — 本轮无法做的真机项：

```text
Bot = STOPPED，wechat = disconnected
未改生产 LISTEN_LIST，未启动 Bot，未向微信发 QIYE_A / QIYE_B 探测消息
```

---

## 10. 热更新与缓存（TEST-P2-06）

| 变更 | 何时生效 |
|---|---|
| 修改 `prompts/xxx.md` 内容 | **下一条 LLM 请求立即生效**。`get_user_prompt` 每次打开文件，无 Prompt 正文缓存 |
| 修改 LISTEN_LIST 绑定 | **必须 Stop → 保存 → Start**。运行中 `/submit_config` 返回 400 `BOT_RUNNING`。`user_names` / `prompt_mapping` 是启动时快照 |
| 删除正在使用的 Prompt 文件 | 启动：拒绝启动。运行中：`get_user_prompt` 抛 `FileNotFoundError`，**llm_client 捕获后改用「你是一个乐于助人的助手。」** |

---

## 11. 与现有配置 UI 的关系（只做信息架构，不改版）

| 现有入口 | 建议 |
|---|---|
| 首页 / 运行概览 | **保留**。运维面，不是企业控制台 |
| 机器人管理 → 监听对象 | **升级** 为 Conversation 列表（名称暂可仍叫监听对象） |
| 群聊策略 | **保留全局**；P1 后期再下沉到每 Conversation `reply_policy` |
| 回复策略 | **保留**（打字速度 / 队列等待），属 P0 发送体验 |
| AI 能力 → Prompt 管理 | **保留并改名预期**：Prompt 库；与 Agent 配置分开 |
| 模型配置 | **保留**；将来挂到 AgentConfig.model_config，现在仍全局 |
| 快速配置 | **保留** 为首次绑定向导 |
| 趣味实验室 | **隔离保留**。论坛把 Prompt 当「角色」，与智群 Agent 不是同一产品；不在 P1/P2 废弃，也不升级为企业控制台 |
| 任务中心（自动提醒 / 定时任务 / 指令） | **保留现有能力**。不是 P4 Task Engine，不要改名为任务中心 2.0 |
| 总览 / 主题 / 任务 / 风险 / 决策 / 日报 | **不要创建**（P3～P8） |

---

## 12. P0 回归风险（只记录，不修改）

若下一轮实施 P1/P2 时改错接口，可能打到已冻结的 P0：

1. `evaluate_inbound(..., listen_users=user_names)` 的 `who` 仍是 `chat.who`（nickname）。若把 listen_users 改成 wxid 而 who 仍是昵称，私聊会全部 `unauthorized`。  
2. `Outbound Guard` / `Dedupe` 的 `conversation_id` 已是 `chat_wxid`。不要改回 nickname。  
3. Stop 后禁止保存配置是当前产品行为；若为了「不停机改绑定」放开 `/submit_config`，须另做热更新，且不能绕过 Stop Kill Switch。  
4. `llm_client` 缺 Prompt 时的默认助手文案不是 P0 文件，但错误 Prompt 会让 P0 已验证的回复风格回归失败。

---

## 13. 必须回答的十问（摘要）

1. **P1 完成了什么 / 缺什么**：能听多个微信对象并绑 Prompt；没有 Conversation 模型、没有单对象暂停、身份等于 nickname。  
2. **P2 已具备什么**：Prompt 文件仓库 + LISTEN_LIST 绑定 + 运行时按绑定读文件进 LLM。不是 AgentConfig。  
3. **LISTEN_LIST 还能当核心模型吗**：**不能长期当核心**。可当兼容输入，经 Adapter 生成 Conversation。  
4. **是否应引入 Conversation**：**应该**。第一阶段只实现 WECHAT，类型 PRIVATE / GROUP。  
5. **nickname 是否有身份风险**：**有，CONFIRMED**。底层已能解析 wxid，配置未存。  
6. **Agent 与 Prompt 是否混为一体**：**是**。Prompt 文件名同时承担角色、Agent、绑定目标。  
7. **Prompt 绑定是否真实运行生效**：**是**。ceshi 实际跑的是 `企业_1`，不是 QIYE。  
8. **Prompt 是否需要版本**：**需要轻量版本**（hash + active），现在上数据库成本过高。  
9. **进 P3 前的 BLOCKER**：见 `P1-P2-GAP-REPORT.md`。核心是稳定会话 ID + 禁止静默用错 Prompt。  
10. **下一轮改哪些文件**：见 `P1-P2-NEXT-IMPLEMENTATION-PLAN.md`。

本轮停止。不进入 P3。
