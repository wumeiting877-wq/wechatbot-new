# P8-G1 Query Router Design

> 日期：2026-09-23  
> 实现：`query_router.py`、`collaboration_query.py`，接入点在 `message/listener.py`。  
> P8-G0 的 Hybrid 分类器本 Gate 不实现。规则未命中固定 `NOT_QUERY`。

---

## 1. 接入

只在 `evaluate_inbound` 成功且 `verdict.action == REPLY` 时进入。

```text
evaluate_inbound
↓
action == REPLY ?
    ├─ Query / Command / OUT_OF_SCOPE
    │     send_reply
    │     return          不调用 try_enqueue_topic_sidepath
    └─ NOT_QUERY
          继续原 try_enqueue_topic_sidepath
          继续原 handle_wxauto_message
action != REPLY
    不进 Router
    原旁路调用保持
```

Stopped 状态在 listener 更前面 return。Router、Query Service、`send_reply` 都不会被调用。

去掉 `@{bot_name}` 之后，文本 trim 后以 `/` 开头，判为 `NOT_QUERY`，交给原 handler。

## 2. 规则顺序

规则偏严：认不出就回原 Chat。误判成 Query 或 Command 会跳过业务旁路。

```text
1. 空文本、以 / 开头                 NOT_QUERY
2. 明确指向别的群 / 别的项目的查询     OUT_OF_SCOPE
3. 我的任务、某人负责、某人的任务       NOT_QUERY
4. 整句就是写指令                     COMMAND
5. 主题「标题」/ 这个主题 / 标题这个主题   TOPIC_SUMMARY
6. 整句命中任务 / 风险 / 决定 / 主题列表
7. 其余                               NOT_QUERY
```

第 2 步在身份规则之前。否则「看看另一个群有什么任务」会被「……有什么任务」当成身份查询。

跨会话必须同时有范围词和查询词。只是提到「另一个群今天必须完成接口联调」仍是 `NOT_QUERY`。

范围词包括：另一个群、其他群、别的会话、另一个项目，以及「查 / 看看」配合 `项目` + 字母（项目B）。

写指令必须整句匹配，例如：

```text
帮我创建一个任务
把任务改成完成
把风险关掉
关闭这个风险
修改这个决定
给张三分配任务
```

「今天必须完成接口联调」不是整句写指令，保持 `NOT_QUERY`。

## 3. v1 意图

| 说法 | 类型 |
| --- | --- |
| 现在有哪些任务 / 有哪些任务 / 当前任务有哪些 / 查看任务 | LIST_TASKS |
| 目前有哪些风险 / 现在有什么风险 / 有什么风险 / 查看风险 | OPEN_RISKS |
| 全部风险 / 所有风险 | LIST_RISKS |
| 有哪些决定 / 确定了什么 / 刚才确定了什么 | LIST_DECISIONS |
| 现在有哪些主题 / 有哪些主题 / 查看主题 | LIST_TOPICS |
| 主题「XXX」现在什么情况 / XXX这个主题现在什么情况 / 这个主题现在什么情况 | TOPIC_SUMMARY |

「刚才确定了什么」只决定意图是 `LIST_DECISIONS`。时间窗不存在。Formatter 按 `created_at` 从新到旧列出，文案不写「刚才」。

员工问风险时默认 `OPEN_RISKS`。`LIST_RISKS` 只在明确说全部 / 所有时使用。

## 4. 身份查询

```text
我有什么任务
我的任务
张三负责什么
张三有哪些任务
```

结果是 `NOT_QUERY`，不改写成 `LIST_TASKS`，不用 `sender_name` 填 `assignee_text`。

## 5. 已识别之后

```text
Query     Query Service → Formatter → send_reply → return
Command   固定文案「当前不能在这里修改任务、风险或决定。」→ send_reply → return
OUT_OF_SCOPE
          固定文案「当前只能查询本会话已记录的内容。」→ send_reply → return
          不调用任何 list_*
```

三条都不进 Topic 旁路，不进 `handle_wxauto_message`，不写 `user_queues` / `chat_contexts`，不调用 `get_deepseek_response`。

`send_reply` 之前调用 `runtime.allow_reply` 和 `runtime.try_acquire_session`。这是 Chat 正在用的同一把会话锁。会话已被占用时，本轮不发送，也不退回 Chat。

## 6. 分类器空位

`classify_unmatched_as_not_query` 固定返回 `NOT_QUERY`。没有模型调用，没有 Extractor，没有 Engine。
