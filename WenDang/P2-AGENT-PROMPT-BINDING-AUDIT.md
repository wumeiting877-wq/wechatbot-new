# P2 Agent / Prompt 绑定审计

> 日期：2026-09-20  
> 对照：实施方案第 36、16 节；`P1-P2-CURRENT-STATE-AUDIT.md`  
> 本轮不拆 QIYE.md，不引入数据库版本表

---

## 1. 现在这套东西是什么

结论：

```text
当前 = Prompt 文件绑定
不是 Agent 配置
```

关系实际上是：

```text
nickname
    → prompt_mapping[nickname]
    → prompts/{filename}.md
    → get_user_prompt()
    → LLM system message
```

用户在 WebUI 选择的是 **文件名**。没有 Agent 实体，没有版本，没有 role / model / trigger / permission 分字段。

---

## 2. 真实运行时链路（不能只看下拉框）

```text
Conversation / 监听对象          今天是 nickname
        ↓
prompt_mapping.get(user_id)
        ↓
Prompt name = LISTEN_LIST[][1]     例如 企业_1
        ↓
prompts/企业_1.md
        ↓
memory_store.get_user_prompt(user_id)
  - 每次 LLM 调用打开文件
  - 无正文缓存
  - 可选合并 CoreMemory JSON
  - 找不到文件 → FileNotFoundError
        ↓
llm_client.get_deepseek_response(..., store_context=True)
  - system = user_prompt
  - 若 FileNotFoundError → 改写为「你是一个乐于助人的助手。」  ← 危险
        ↓
主模型请求
```

后端 **会** 使用用户选择的 Prompt。依据：

1. 代码：`get_user_prompt` → `messages_to_send` 的第一条 system。  
2. 现场配置：`ceshi → 企业_1`。  
3. `chat_contexts.json["ceshi"]` 助手以「企业战略与业务分析顾问」自称，与 `企业_1.md` 一致，与 `QIYE.md` 不一致。  
4. 隔离测试：`QIYE_A` / `QIYE_B` 两路内容互不串。

**纠正一个前提**：任务书写「当前已经存在 ceshi → QIYE」。现场不是。

```text
ceshi → 企业_1     真实运行绑定
QIYE  → QIYE       另一个监听对象绑了 QIYE.md
```

`QIYE.md` 目前只有约 44 行，在「禁止 Markdown」处截断，不像完整的项目协同 Agent Prompt。

---

## 3. 谁读取、何时读取、是否缓存

| 路径 | 时机 | 缓存 |
|---|---|---|
| `bot.py` 启动预检查 | 进程启动 | 只检查存在，不读内容 |
| `get_user_prompt` | 每次主模型 `store_context=True` | **无缓存，每次读盘** |
| `memory_store` 记忆写入 | `SAVE_MEMORY_TO_SEPARATE_FILE=false` 时追加进 md | 会改 Prompt 文件本身 |
| `forum_routes.load_character_prompt` | 趣味实验室 | 按 Prompt 文件名当角色，与微信监听是另一条链 |
| WebUI `GET /edit_prompt/<filename>` | 编辑页 | 当时读一次 |

当前 `SAVE_MEMORY_TO_SEPARATE_FILE=true`，记忆走 `CoreMemory/`，不写回 md。这条危险路径仍存在于代码中。

修改 Prompt 内容：不必重启 Bot，下一轮回复用新正文。  
修改绑定关系：必须停 Bot 再保存。

---

## 4. 如何按监听对象选择、是否可能拿错

选择规则：

```text
prompt_file = prompt_mapping.get(user_id, user_id)
```

`user_id` 是 `chat.who`（nickname）。

拿错 Prompt 的真实条件：

1. 两个监听对象 nickname 相同 → 字典后者覆盖，两人都用最后一个 Prompt。  
2. 未命中 mapping 时 **用 user_id 当文件名**。监听对象叫 `QIYE` 且误删绑定，会去读 `prompts/QIYE.md`，看起来像「碰巧对了」。  
3. 运行中删除 md 后，llm_client **不用映射里的名字，改用通用助手**。这是拿错，而且是静默拿错。  
4. 重命名 md（Prompt 管理允许改文件名）不会改 LISTEN_LIST。绑定变成「原 Prompt 已不存在」；若强行启动，预检查失败。运行中改名等于删除。

---

## 5. Fallback / 默认 Prompt

| 层 | 行为 |
|---|---|
| WebUI 下拉 | 缺文件显示「原 Prompt 已不存在」，不改绑其它选项 |
| 启动预检查 | 缺文件 `FileNotFoundError`，进程退出 |
| `get_user_prompt` | 缺文件抛错，无默认文件 |
| `get_deepseek_response` | 捕获后 system=`你是一个乐于助人的助手。` |

对照验收「不得默默使用错误 Prompt」：

```text
启动路径     合格（拒绝启动）
运行时路径   不合格（静默 fallback）
未映射 user  不合格（用 nickname.md，可能碰巧命中）
```

---

## 6. 版本

不存在：

- PromptVersion 表  
- content_hash  
- status DRAFT/ACTIVE/ARCHIVED  
- 某条回复使用了哪一版 Prompt 的记录  

`chat_contexts.json` 只存 user/assistant 文本，没有 `prompt_name` / `prompt_hash`。  
旧会话不知道当时用的哪份 Prompt。换绑时 WebUI 会清该 nickname 的上下文，但不清历史文件备份。

---

## 7. 对十二条问题的回答

| # | 问题 | 答案 |
|---|---|---|
| 1 | Prompt 是否用文件名当 ID？ | 是。`QIYE.md` → id=`QIYE` |
| 2 | 删除 .md 后已有绑定怎么办？ | UI 保留旧值并标「已不存在」。启动失败。运行中 → 默认助手 |
| 3 | Prompt 改名怎么办？ | `os.rename`，LISTEN_LIST 不更新，等价于删除旧名 |
| 4 | 内容修改是否有版本？ | 无。覆盖写 |
| 5 | 旧会话是否知道当时 Prompt？ | 否 |
| 6 | 有没有 Prompt Version？ | 无 |
| 7 | 能否知道某条回复用了哪一版？ | 不能 |
| 8 | 多个 Agent 能否共享 Prompt？ | 多个监听对象可指向同一文件（ceshi 与 哈 都是 企业_1）。没有 Agent 实体，只是共享文件 |
| 9 | Agent 与 Prompt 是不是同一个概念？ | **当前被当成同一个**。文件名既是角色又是 Agent |
| 10 | QIYE 是否职责过多？ | 文件本身很短，但产品定位已把回复风格、少打扰、禁 Markdown、任务/风险口吻写进 Chat Prompt。见第 9 节 |

---

## 8. 推荐抽象（演进，本轮不落地）

不要长期保持：

```text
Conversation → Prompt 文件
```

目标：

```text
Conversation
    → AgentConfig
        → PromptVersion (ACTIVE)
```

### AgentConfig（第一阶段只一种类型）

```text
id
name                          智群 · 项目协同 Agent
agent_type                    PROJECT_COLLABORATION
enabled
current_prompt_version_id
reply_policy                  INHERIT
model_config                  第一阶段仍可指向全局 MODEL
temperature                   可选覆盖，默认继承全局
context_policy                第一阶段沿用 MAX_GROUPS
created_at / updated_at
```

不要现在做：客户 Agent / 会议 Agent / 售后 Agent / 多 Agent 调度。

### PromptVersion（轻量，不要先上数据库）

```text
id                            pv_{prompt}_{short_hash}
agent_config_id
version                       单调整数
content                       或只存 hash，正文仍在 md
source_file                   prompts/QIYE.md
content_hash                  sha256
status                        DRAFT | ACTIVE | ARCHIVED
created_at
```

建议落地顺序：

1. 保留 `prompts/*.md` 为编辑源。  
2. 每次保存 md 时算 hash；与 ACTIVE 不同则生成新 version 元数据（`prompts/QIYE.meta.json` 或集中 `prompt_versions.json`）。  
3. LLM 调用时在 trace / runtime 日志写下 `prompt_name` + `content_hash`。不必改 P0 网关，可写现有 `runtime.log_event` extra。  
4. 会话上下文仍可不存全文；hash 足够追溯。

---

## 9. QIYE.md 职责拆分（只给结论，不改文件）

`prompts/QIYE.md` 现有内容承担：

| 片段 | 职责 | 分类 |
|---|---|---|
| 「智群 · 企业消息协同智能体」 | 角色身份 | C. Agent Chat Prompt |
| 帮助理解讨论、查询、整理任务/风险/结论 | 产品能力声明，无 JSON schema | C 现在；D 将来 Extractor |
| 回复稳定 / 少打扰 / 不臆测 | 回复风格 + 部分 Trigger 口吻 | C；Trigger 真正规则在代码 |
| 不重复回复 | 与 P0 Dedupe/Outbound 重复 | **A. 应由 P0 负责**，Prompt 不应当主闸 |
| 不输出不适合微信的格式；禁 `** # ``` | 与 P0 `WeChatPlainTextFormatter` 重复 | **E. Formatter** |
| 一次回答一份完整回复、禁止拆条 | 发送策略 | E + 现有一次发送逻辑（已是 P0） |
| 文件在禁止 Markdown 列表处截断 | 未完成稿 | 补全属于 Chat Prompt，不要塞 Topic JSON |

未出现在 QIYE.md、但容易被误塞进 Prompt 的项：

| 职责 | 分类 |
|---|---|
| Self 判断 | A. P0 `is_self_message` |
| Dedupe | A. P0 |
| Outbound 回流 | A. P0 |
| Stop Kill Switch | A. P0 |
| 私聊名单 / 群 @ 关键词 | B. 现有 Trigger / group_rules（P0 已接入） |
| Topic / Task / Risk JSON | D. 后续 Extractor（P3+），不要写进 Chat Prompt |
| 微信表格转纯文本 | E. 已实现 Formatter |

`企业_1.md`（ceshi 正在用的）额外问题：明确要求加粗、分点、对比表格。P0 formatter 会把这些清掉，造成「Prompt 要 Markdown、通道撕 Markdown」。这是 Agent Chat Prompt 与 Formatter 冲突，P2 实施时应让项目协同 Prompt 对齐纯文本，而不是改 Formatter。

---

## 10. 测试对照

| 编号 | 期望 | 本轮结果 |
|---|---|---|
| TEST-P2-01 | ceshi→QIYE_A 真机出 A | **未跑真机**（Bot STOPPED / 微信断开）。隔离测试 PASS：映射到 QIYE_A 必读 A。历史真机显示 ceshi 跑的是 企业_1 |
| TEST-P2-02 | 另一对象→QIYE_B | 隔离 PASS。真机未跑 |
| TEST-P2-03 | 交换 Prompt | 隔离 PASS（改 mapping 后立即互换）。生产绑定互换需 Stop+保存+Start |
| TEST-P2-04 | 刷新 WebUI 绑定保持 | **PASS**。`config.local.json` + `/api/prompts` + `listen_count=3` |
| TEST-P2-05 | 重启 Bot 绑定保持 | **配置层 PASS**。绑定在 json，与进程无关。本轮未再 Start Bot |
| TEST-P2-06 | 改 Prompt 内容何时生效 | **立即生效（下一次 LLM）**。绑定变更需重启 |
| TEST-P2-07 | 删除正在绑定的 Prompt | UI 不静默改绑。运行时 **会静默 fallback**。标记 GAP |
| TEST-P2-08 | 文件不存在 | 启动拒绝。运行时默认助手。对照「必须明确错误」：**运行时不合格** |

隔离测试文件：`tests/test_p1_p2_audit.py`，15 tests OK。未改 P0 测试。
