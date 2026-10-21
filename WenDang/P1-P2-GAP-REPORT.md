# P1 / P2 Gap Report

> 日期：2026-09-20  
> 依据：`P1-P2-CURRENT-STATE-AUDIT.md`、`P1-CONVERSATION-MODEL-DESIGN.md`、`P2-AGENT-PROMPT-BINDING-AUDIT.md`  
> 分类：BLOCKER / REQUIRED / OPTIONAL / FUTURE  
> BLOCKER = 不解决不能进入 P3 Topic Engine

---

## 1. 测试矩阵

| 编号 | 项 | 结果 | 说明 |
|---|---|---|---|
| TEST-P1-01 | ceshi 监听配置加载 | **PASS** | `config.local.json` 含 ceshi；`/bot_status.listen_count=3` |
| TEST-P1-02 | 两个以上监听对象同时存在 | **PASS** | ceshi、哈、QIYE |
| TEST-P1-03 | 暂停其中一个不影响另一个 | **GAP** | 无 per-object enabled。只能删行或全局 Stop。未伪造通过 |
| TEST-P1-04 | 私聊与群聊配置能区分 | **GAP** | 同一 `[nickname, prompt]` 结构。运行时可识别 `@chatroom`，配置不保存 type |
| TEST-P1-05 | 重名 / 昵称变化 | **RISK CONFIRMED** | identity == nickname。`search_contact` 取第一条精确匹配 |
| TEST-P2-01 | ceshi→QIYE_A 真机 | **NOT RUN** | Bot STOPPED，微信 disconnected。隔离绑定 PASS。现场实际是 ceshi→企业_1 |
| TEST-P2-02 | 另一对象→QIYE_B | **NOT RUN** 真机；隔离 **PASS** | |
| TEST-P2-03 | 交换 Prompt | 隔离 **PASS**；生产需停机保存 | |
| TEST-P2-04 | 刷新 WebUI | **PASS** | |
| TEST-P2-05 | 重启机器人绑定保持 | 配置层 **PASS**；本轮未 Start | |
| TEST-P2-06 | 改 Prompt 内容 | **立即生效**（下次 LLM） | 绑定变更需重启 |
| TEST-P2-07 | 删除正在绑定的 Prompt | **GAP** | UI 不静默改绑；运行时静默默认助手 |
| TEST-P2-08 | Prompt 文件不存在 | 启动 **PASS**（拒绝）；运行时 **FAIL** | |

---

## 2. BLOCKER（进 P3 前必须处理）

P3 Topic Engine 要把状态挂到「某一个会话」。当前会话主键是会变的 nickname，且缺文件时会换错大脑。这两件事会让 Topic 数据从第一天就脏。

### B1. 业务层会话主键仍是 nickname

```text
LISTEN_LIST / user_names / prompt_mapping
user_queues / chat_contexts / 记忆文件名
全部 = display name
```

P0 消息层已有 `chat_wxid`，配置层不用。

进入 P3 前最低限度：

- 内部 `conversation.id`
- 能存 `platform_conversation_id`（wxid）
- Topic 将来挂 id，不挂昵称

### B2. 运行时缺 Prompt 静默 fallback

`llm_client.get_deepseek_response` 在 `FileNotFoundError` 时改用「你是一个乐于助人的助手。」

Topic / 协同回复若走到这条路径，会用错误人格继续说话，且日志不像启动失败那样硬。

进入 P3 前：缺 Prompt 必须 NO_ACTION 或明确错误回复，禁止换默认助手。

这不是改 P0 网关，只改 `llm_client.py` 的 catch。不要顺手改 Self/Dedupe。

### B3. Agent 与 Prompt 仍是同一个文件名

P3 Extractor 若继续把「聊天回复」和「Topic JSON」塞进同一 md，会污染微信回复（P0 formatter 也会撕 JSON/Markdown）。

进入 P3 前最低限度：

- Conversation → AgentConfig（可先 1:1 从 Prompt 名生成）
- Chat Prompt 与后续 Extractor Prompt **分开命名**，即使 Extractor 本阶段还不写代码

---

## 3. REQUIRED（P1/P2 本阶段应完成）

### R1. Conversation 兼容层

- `CONVERSATIONS` 写入 `config.local.json`
- LISTEN_LIST Adapter 双向投影
- 不删旧字段

### R2. enabled

- 单对象暂停
- 投影时过滤 `enabled=false`
- UI 把写死的「已启用」换成真实开关
- 保存仍走 Stop → 保存 → Start

### R3. 持久化平台身份与类型

- AddListenChat 成功后回写 wxid 与 PRIVATE/GROUP
- 不改 AddListenChat 的 nickname 参数

### R4. nickname 冲突校验

- 保存时拒绝重复 display_name（WECHAT 第一阶段）
- 明确报错，不要靠 dict 后者覆盖

### R5. Prompt 绑定完整性

- 删除 Prompt：若仍被 AgentConfig / LISTEN_LIST 引用 → 409，禁止删
- 重命名 Prompt：同步更新引用，或禁止重命名改为「另存」
- `prompt_mapping.get(user_id, user_id)` 去掉「用 nickname 当文件名」的隐式 fallback

### R6. 轻量 AgentConfig

- 一种 `PROJECT_COLLABORATION`
- 多个 Conversation 可共享同一 AgentConfig（ceshi 与 哈 已共享 企业_1）
- Prompt 文件仍是编辑源

### R7. 轻量 Prompt hash

- 保存 md 时记 hash
- LLM / pipeline 日志带 prompt_name + hash
- 不上数据库也可

### R8. 真机 A/B Prompt 回归

下一轮实施后必须补：

```text
对象A → PromptA → 回复含 A-链路正常
对象B → PromptB → 回复含 B-链路正常
交换后再测
```

本轮因 Bot 停止、微信断开未做。列为 P1/P2 关闭门槛，不是本审计伪造项。

---

## 4. OPTIONAL

| ID | 项 | 理由 |
|---|---|---|
| O1 | 运行中热更新 LISTEN_LIST | 现网 Stop 再保存可接受 |
| O2 | 每 Conversation 独立群触发 | 全局策略目前够 Demo |
| O3 | Prompt 管理从 Jinja 列表改为纯 API | 已有 `/api/prompts` |
| O4 | 禁止记忆写回 md 的代码路径 | 现配置已走 JSON |
| O5 | 补全截断的 QIYE.md | 实施 P2 时按 Chat Prompt 职责补，不要塞 Extractor |
| O6 | 会话上下文记录 prompt_hash | 有日志即可先活 |

---

## 5. FUTURE（企业化 / P3 之后）

| ID | 项 |
|---|---|
| F1 | WEWORK / 其它 platform 实现 |
| F2 | 多 Agent 类型（客户/会议/售后/研发） |
| F3 | 数据库版 PromptVersion |
| F4 | permission_scope 引擎 |
| F5 | 企业控制台：总览/主题/任务/风险/决策/日报 |
| F6 | 群内查询、主动提醒升级、RAG |
| F7 | 修复 wechatauto 同名取第一条（底层） |

---

## 6. 十问（必须明确）

### 1. P1 当前完成了什么 / 缺什么

已具备：多监听对象、每对象一个 Prompt 文件名、WebUI 维护、启动注册监听、运行时群/私聊识别、全局群策略。

缺失：Conversation id、平台身份落盘、type 落盘、enabled、每对象策略、冲突校验、适配器。

### 2. P2 当前已具备什么

Prompt 目录、API 列表、LISTEN_LIST 绑定、运行时读对应 md 进 LLM、启动缺文件拒绝、UI 缺文件不改绑。

不具备：AgentConfig、版本、删除/改名完整性、运行时禁止 fallback。

### 3. LISTEN_LIST 是否还能当核心模型

**不能作为核心模型继续演进。**  
**可以作为兼容投影继续存在。**

### 4. 是否应该引入 Conversation

**应该。** 第一阶段 WECHAT + PRIVATE/GROUP。见设计文档。

### 5. nickname 是否存在身份风险

**存在，CONFIRMED。** 底层有 wxid，配置没用。

### 6. Agent 与 Prompt 是否混为一体

**是。** 文件名 = 角色 = Agent = 绑定目标。论坛还把同一文件当 NPC 人设。

### 7. Prompt 绑定是否真实运行生效

**是。** ceshi 跑的是 `企业_1.md`，不是 QIYE。隔离 A/B 测试通过。真机 QIYE_A/B 本轮未发送。

### 8. Prompt 是否需要版本机制

**需要轻量 hash + ACTIVE，不需要本轮上数据库。**

### 9. 进入 P3 前有哪些 BLOCKER

- B1 内部会话 ID + 持久化 wxid  
- B2 去掉运行时默认助手 fallback  
- B3 Conversation→AgentConfig→Chat Prompt，Extractor 不进同一文件  

### 10. 下一轮具体改哪些文件

见 `P1-P2-NEXT-IMPLEMENTATION-PLAN.md`。

---

## 7. 不在本 Gap 内的事项

以下保持冻结或以后再做：

- P0 消息网关 / Stop / formatter  
- Topic Engine  
- Task / Risk / Decision 库  
- 日报 / 主动提醒产品化  
- 多 Agent 调度  
- 大规模 UI 改版  
- 企业微信接入  
- RAG / 知识库
