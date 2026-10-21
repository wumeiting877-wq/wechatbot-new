# P8-G2 Hybrid Intent Design

> 日期：2026-09-23  
> 分类器只识别意图。Query Service、Formatter、会话范围保持 P8-G1。

---

## 1. 模块

```text
query_router.py              规则、候选门、route_hybrid
query_intent_classifier.py   classify(text) → 枚举
llm_client.call_narrow_completion
collaboration_query.py       接入 listener，会话锁仍在发送前
query_formatter.py           只增加固定安全文案
query_service.py             不改
```

`RouteResult` 只有：

```text
route
query_type
classifier_used
classifier_status
topic_title / topic_id     仍只来自确定性规则
identity_scope             self 或 assignee
```

模型原文不进 Formatter。

## 2. 优先级

```text
REPLY
↓
1. 空文本、以 / 开头                 NOT_QUERY，classifier = 0
2. OUT_OF_SCOPE                     classifier = 0
3. 个人 / 他人身份查询               固定安全回复，classifier = 0
   其余「某人负责……」陈述            NOT_QUERY，classifier = 0，继续旁路
4. 写指令                            COMMAND_NOT_SUPPORTED，classifier = 0
5. P8-G1 高置信规则                  对应 Query，classifier = 0
6. looks_like_query_candidate?
      否 → NOT_QUERY，classifier = 0
      是 → Query Intent Classifier
7. 合法枚举 → 现有 Query Service
   NOT_QUERY → 原旁路 + Chat
   失败 / 非法输出 → 固定指引，return handled
```

## 3. 候选门

必须同时有业务对象词和明确询问 / 盘点用语。

对象词：

```text
任务 待办 风险 问题 决定 决策 结论 主题 话题 事情
```

强询问：

```text
哪些 哪几 哪个 什么 多少 看看 看一下 查看
盘一下 盘一盘 梳理一下 怎么样 是什么 有啥
```

「目前」「现在」「情况」单独不够。否则「测试环境目前有风险」会打进模型。这些词可以和强询问同时出现，但不能自己打开候选门。

「没什么 / 没有什么」不算询问。

普通讨论和寒暄没有强询问，分类器调用数是 0。

「任务怎么样了」有强询问和对象词，可以进分类器。分类器若返回 `NOT_QUERY`，继续原旁路。「风险呢」「决定呢」不够明确，不进分类器。

## 4. 分类器输出

只接受：

```json
{"query_type": "LIST_TASKS"}
```

枚举：

```text
LIST_TOPICS
LIST_TASKS
LIST_DECISIONS
LIST_RISKS
OPEN_RISKS
TOPIC_SUMMARY
NOT_QUERY
```

额外字段被丢掉，不进入回复。`topic_title`、`answer`、条目、SQL、conversation id 都不会被采用。

Markdown、自然语言、非法 JSON、空字符串、未知枚举都是 `CLASSIFIER_INVALID`。不猜测成某个 Query。

超时、连接错误、Provider 错误同样不进 Query Service，不进旁路，不进 Chat。固定回复：

```text
暂时无法识别这条查询。
你可以直接问：
“现在有哪些任务？”
“目前有哪些风险？”
“有哪些决定？”
“有哪些主题？”
```

然后 `return handled`。

## 5. 身份查询

问句走固定回复，不进分类器，也不进 Chat：

```text
我有什么任务 / 我的任务
→ 当前暂不支持按个人身份查询任务。
  你可以问“现在有哪些任务？”

张三负责什么 / 张三有哪些任务 / 王磊负责什么
→ 当前暂不支持按人员身份查询任务。
```

`classify_agent_message` 对这些问题仍然返回 `KIND_NOT_QUERY`，所以 P8-G1 那条「不是 LIST_TASKS」的断言保持成立。真正拦住 Chat 的是 `route_hybrid`。

「李明负责补材料」仍然是 `NOT_QUERY`，继续原旁路。不用 `assignee_text` 模糊匹配，也不让模型猜身份。

## 6. TOPIC_SUMMARY

分类器只能给出 `TOPIC_SUMMARY`。主题绑定仍走 P8-G1：当前会话只有一个主题就查，多个主题就 `AMBIGUOUS`。分类器即使带了标题，也不会被使用。

## 7. 测试替身

单元测试注入 Fake Completer，不连接网络。真实模型只出现在可选 smoke，不决定单测结果。

分类器同步调用。没有 Queue、Worker、Redis、Scheduler。
