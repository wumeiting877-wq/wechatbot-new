# P8-G4 Gate 0 Identity Audit

> 日期：2026-09-23  
> 方式：只读代码与配置。没有改 Task schema，没有新增身份字段。

---

## 1. 结论先行

系统里没有一条已经证明的：

```text
sender identity ↔ task assignee identity
```

入站消息可以带上微信侧的 `sender_wxid`。任务只保存 `assignee_text`。这两者没有共同的人员主键，也没有人员目录把它们接起来。

因此本 Gate 不能实现 `MY_TASKS` / `TASKS_BY_ASSIGNEE`。

---

## 2. Identity Source Matrix

| 来源 | 字段 | 稳定性 | 是否唯一 | 能否与 Task 对接 |
| --- | --- | ---: | ---: | ---: |
| InboundMessage | sender_wxid | 有值时是微信账号 id；允许为空 | 有值时标识这条消息的发送账号；不表示任务负责人 | 否。Task 禁止 `assignee_wxid` |
| InboundMessage | sender_id | 微信本地整数。`2` 被 P0 明确标成未确认身份 | 否。不能单独当人 | 否 |
| InboundMessage | sender_name | 昵称。空则回落到聊天窗口名 | 否 | 否。与 `assignee_text` 字符串相同也不证明是同一个人 |
| InboundMessage | chat_wxid / conversation_id | 会话窗口。群是 `@chatroom`，私聊可能是对方 wxid | 标识会话，不标识群成员 | 否。Query 已经按 Conversation 限定，这不是负责人键 |
| RuntimeIdentity | bot_wxid / bot_name / login_account | 只描述机器人自己 | 只用于 self 判断 | 否 |
| 监听对象 LISTEN_LIST | `[窗口名, prompt]` | 窗口昵称，会变 | 否。一行是一个被监听的聊天，不是一个人 | 否 |
| CONVERSATIONS | id | 首次由平台+窗口名哈希，之后不随昵称重生 | 会话主键 | 否。对的是会话，不是负责人 |
| CONVERSATIONS | platform_conversation_id | 启动时从监听窗口回写的 wxid | 会话的微信 id | 否。群 id 下面有多人；没有成员表 |
| CONVERSATIONS | display_name / metadata.nickname | 窗口显示名 | 否 | 否 |
| CONVERSATIONS | agent_config_id / prompt_name | 提示词绑定 | 绑定的是会话 | 否 |
| MessageRecord | sender_wxid / sender_name / sender_id | 入站投影，原样记下发送者 | 发送者 ≠ 负责人 | 否。`created_msg_id` 指向创建这条任务的消息，发送者常常是布置人 |
| Task | assignee_text | 自由文本。只做 strip | 否 | — |
| Task | assignee_id / assignee_wxid | 不存在。写入前被删掉 | — | 不能对接，因为字段被禁止 |
| HeuristicTaskExtractor `_KNOWN_NAMES` | 王强、李娜、赵凯、周敏、陈总、张三 | 离线夹具里的汉字表 | 否。没有 wxid，用开头或前 8 字包含来切名字 | 否。不是人员目录，生产抽取走 LLM |
| Decision | decided_by_id / assignee_text | 写入前被删掉 | — | 否 |
| Risk | owner_id / owner_text | 写入前被删掉 | — | 否 |
| user_queues / reminders | user_id | 聊天窗口名 | 否 | 否 |
| config.json | — | 仓库里没有这个文件 | — | — |
| 人员表 / 通讯录 / 员工号 | — | 代码和配置里都没有 | — | — |

`config.local.json` 里实际只有三个监听窗口：`ceshi`（私聊 wxid）、`哈`（群）、`智群 · 企业消息协同智能体`（群）。每条只有窗口名、会话类型、平台会话 id 和提示词。没有成员、没有员工号、没有 wxid 到姓名的对照表。

---

## 3. 入站身份从哪里来

`message/listener.py` 把 wxauto 消息交给 `inbound_from_wx_message`。

`message/identity.py` 的抽取规则：

```text
sender_wxid = msg.sender_wxid 或 msg.sender_username，再 strip
sender_id   = msg.sender_id，没有则用 raw_sender_id
sender_name = msg.sender，空则改用聊天窗口名 chat.who
conversation_id = chat_wxid，没有则用窗口名
```

注释写明：不根据昵称或窗口改写 sender。self 判断只用 `direction == OUTBOUND`，或 `sender_wxid` / `sender_id` 等于 `bot_wxid`。`sender_id == 2` 且没有 wxid 时，明确返回 `sender_id_2_unconfirmed_identity`，不当成已证明的自己。

所以：`sender_wxid` 在有值时是稳定的发送账号。它仍然只证明「这条消息是谁发的」，不证明「任务负责人是谁」。

---

## 4. assignee_text 从哪里来

路径：

```text
消息正文 / current_message.sender_name
↓
Task Extractor（生产：LLM；离线夹具：HeuristicTaskExtractor）
↓
normalize_decision：只 strip，删掉 assignee_id / assignee_wxid / assignee
↓
assignee_is_valid：空串放行；否则必须是原文子串，或在「我 + 动作」时等于 sender_name
↓
TaskEngine 写入 Task.assignee_text
↓
TaskStore._normalize_new_task 再 strip，并丢掉禁止键
```

生产提示词 `prompts/extractors/TASK_EXTRACTOR.md` 规定 `assignee_text` 只能来自：

```text
1. 原文点名
2. 发送者说「我…修复/准备/处理…」时，使用 current_message.sender_name
```

并禁止输出 `assignee_id`。没有通讯录可查。提示词里的「王强、李娜、赵凯」是例子，不是系统里的人员主键。

规范化只有 `str.strip()`。没有姓名清洗，没有去掉「负责 / 由 / 部门 / @」，没有拆多人。

因此 `assignee_text` 可以是这些形态，只要校验能通过：

| 形态 | 是否可能落到 Task |
| --- | --- |
| 李明 | 能。原文里有这几个字，或自称时等于 sender_name |
| 李明负责 | 能。只要这四个字出现在输入文本里，校验只要求子串相同 |
| 由李明 | 能。同上 |
| 研发部李明 | 能。同上 |
| @李明 | 能。同上 |
| 空 | 新任务会被 Engine 拒绝。字段本身允许空串；更新时空值会被跳过，旧文本留着 |
| 多人写在一个字段里，例如「王强、李娜」 | 能。schema 是一个字符串。提示词要求不同人拆成多条 Task，但校验不阻止模型把整段人名写进一个字段 |
| 多人拆成多条 Task | 能。一条 Task 仍然只有一段文本 |

离线启发式还会把 `sender_name` 直接写进 `assignee_text`。`sender_name` 本身可能已经回落成窗口名。这更说明它不是身份键。

`assignee_is_valid` 用的是「文本出现在原文里」。这是抽取防编造，不是身份证明。

---

## 5. 稳定负责人 ID

搜索结果：

```text
TaskStore.FORBIDDEN_TASK_KEYS 含 assignee_id、assignee_wxid、assignee
TaskExtractor STRIP_KEYS 含 assignee_id、assignee_wxid、assignee、owner
DecisionStore.FORBIDDEN_DECISION_KEYS 含 assignee、assignee_text、decided_by、decided_by_id
RiskStore.FORBIDDEN_RISK_KEYS 含 owner、owner_id、owner_text
```

Task 落盘字段是：

```text
id, conversation_id, topic_id, title, description, status,
assignee_text, due_text, due_at="", created_msg_id, confidence,
created_at, updated_at, schema_version
```

没有 `person_id`、`employee_id`、`account_id`、`assignee_wxid`。

仓库里没有人员配置、联系人映射、群成员表。`bot.py` 里称为白名单的动态配置是安静时间和自动消息，不是人员名单。

`created_msg_id` 可以回到 MessageRecord，那条记录上的 `sender_wxid` 是发消息的人。任务负责人经常是正文里被点名的另一个人。不能把创建消息的发送者当成负责人。

---

## 6. 当前查询怎么处理这些句子

`query_router.route_hybrid` 在分类器之前把这些句子收成 `UNSUPPORTED_IDENTITY`：

```text
我有什么任务 / 我的任务     identity_scope=self
张三负责什么 / 张三有哪些任务  identity_scope=assignee
```

`collaboration_query` 直接发固定句，不读 Task Store：

```text
当前暂不支持按个人身份查询任务。
你可以问“现在有哪些任务？”

当前暂不支持按人员身份查询任务。
```

`QueryRequest` 没有 `assignee_text` 入参。`LIST_TASKS` 只按当前 `conversation_id` 列任务。

---

## 7. 本 Gate 没有做的事

没有新增字段，没有写 `identity_resolver.py`，没有把 `sender_name` 拿去对 `assignee_text`。
