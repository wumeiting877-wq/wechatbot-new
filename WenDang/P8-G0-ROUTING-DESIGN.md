# P8-G0 Routing Design

> 日期：2026-09-23  
> 接入点见 Chat Routing Audit。这里定义 Intent、路由表，以及 Query / Chat / Command 的边界。

---

## 1. 目标结构在代码中的位置

```text
WeChat
↓
message_listener
↓
P0：evaluate_inbound（Trigger / Self / Outbound / Dedupe）
↓
仅当 action == REPLY
↓
Agent Message Router          ← P8-G1 插在 try_enqueue_topic_sidepath 之前
        │
        ├── Collaboration Query
        │        Query Intent
        │        Query Service
        │        四个 Store 的已有 list_* / get_*
        │        Reply Formatter
        │        send_reply
        │
        ├── Command（写）
        │        固定 NOT SUPPORTED 文案
        │        send_reply
        │        不入旁路，不进 Chat
        │
        └── Normal Chat
                 try_enqueue_topic_sidepath（现有）
                 handle_wxauto_message
                 process_user_messages
                 get_deepseek_response
                 send_reply
```

`action != REPLY` 时不进入这个 Router。未 `@` 的群消息继续只走现有旁路资格判断，不会被 Query。

Router 自己不发微信。发送只调用 `send_reply`。

---

## 2. Routing Matrix

| 输入 | Query? | Route |
| --- | --- | --- |
| @Agent 现在有哪些任务 | YES | LIST_TASKS |
| @Agent 当前有什么风险 | YES | OPEN_RISKS |
| @Agent 刚才确定了什么 | YES | LIST_DECISIONS |
| @Agent 现在有哪些主题 | YES | LIST_TOPICS |
| @Agent 这个主题现在什么情况 | YES | TOPIC_SUMMARY；绑不上则为 AMBIGUOUS |
| @Agent 你好 | NO | Normal Chat |
| 普通群消息：今天要完成接口 | NO | 不进 Router。Engine 打开时仍可能进业务旁路 |
| @Agent 帮我新建一个任务 | NO | Command，NOT SUPPORTED |
| @Agent 把这个风险关掉 | NO | Command，NOT SUPPORTED |
| @Agent 看看另一个群的任务 | NO | OUT_OF_SCOPE，不搜索 |
| 私聊（已在监听名单）现在有哪些任务 | YES | LIST_TASKS，范围是该私聊的 Conversation.id |
| 私聊（不在监听名单） | NO | 现有 NO_ACTION，不 Query |
| /总结 、/重启 | NO | 现有 `/` 命令。Query Router 不接管 |

“暂不属于 Query”的写句子不进 Normal Chat。若放回 Chat，模型可能声称已经改完，Engine 打开后还可能把这句话提取成新实体。

---

## 3. Intent 识别：采用 Hybrid，本 Gate 不实现

### 方案 A 纯规则

关键词“任务 / 风险 / 决定 / 主题”即可命中。确定、不调用 LLM、可单测。漏掉改写句。

### 方案 B 独立 Query Classifier

只允许输出：

```text
LIST_TASKS
LIST_RISKS
LIST_DECISIONS
LIST_TOPICS
TOPIC_SUMMARY
OPEN_RISKS
NOT_QUERY
COMMAND_NOT_SUPPORTED
OUT_OF_SCOPE
```

以及可选的 `topic_title` 原文片段。不允许输出 answer 或实体内容。覆盖更好，但依赖模型。

### 方案 C Hybrid（采用）

```text
高置信规则命中 Query 或 Command 或 跨会话说法
    → 直接定类型
规则未命中，但句子同时像提问、又含任务/风险/决定/主题
    → 小型 Classifier，枚举如上
仍不明确
    → NOT_QUERY，走原 Chat
```

规则要偏严。把业务讨论误判成 Query，会让这句话跳过旁路，损失一次提取。把查询误判成 Chat，则退回今天的行为，可以接受。

Classifier 与 Topic / Task / Decision / Risk Extractor 分开，不复用它们的 prompt，也不复用它们的 decision 枚举。那些 Extractor 回答的是“这句话要不要新建实体”。Query Intent 回答的是“用户想查看哪一类已有实体”。

P8-G1 可以先只做规则，把 Classifier 留成未命中时的空位（空位一律 NOT_QUERY）。契约里的枚举现在就固定，避免以后把答案生成塞进分类器。

---

## 4. Query 与 Command

P8 只读。

```text
READ     现在有哪些任务 / 风险 / 决定 / 主题
WRITE    创建、完成、关闭、修改、指派
```

WRITE 的 v1 行为：

```text
不调用 Query Service
不调用 Engine
不写 Store
send_reply：当前不能在这里修改任务、风险或决定。
```

现有以 `/` 开头的运维文本命令仍走 `handle_wxauto_message`，不属于本 Router。Query 分支要放在 `/` 命令处理之前时，规则不得把 `/重启` 这类句子认成 Query。更简单的做法是：Router 只处理去掉 `@` 之后、且不以 `/` 开头的文本；以 `/` 开头的 `REPLY` 直接落入今天的 handler。

---

## 5. 已识别 Query 的业务副作用

```text
明确的 Query 或 Command
    → 对应回复
    → 不调用 try_enqueue_topic_sidepath
    → 不进入 handle_wxauto_message
    → 不写入 chat_contexts
    → 不作为新的业务语义输入
```

影响：

```text
@Agent 你好                 仍走原 Chat 和原旁路资格
P0 Trigger / Dedupe / Self  在 Router 之前已经算完，不改
未识别的群消息               旁路规则不变
```

查询句本身不会变成 MessageRecord。这是有意的：避免“有哪些风险”被提取成风险。

---

## 6. Intent 与员工问题

```text
Q1 现在有哪些任务？           LIST_TASKS
Q2 目前有哪些风险？           OPEN_RISKS
Q3 刚才确定了什么？           LIST_DECISIONS
                              不命名为 RECENT_DECISIONS
Q4 现在有哪些主题？           LIST_TOPICS
Q5 这个主题现在是什么情况？    TOPIC_SUMMARY
                              不能唯一绑定时 AMBIGUOUS
```

不在 v1：

```text
MY_TASKS
TASKS_BY_ASSIGNEE
跨会话
自由自然语言生成 Store 查询
```
