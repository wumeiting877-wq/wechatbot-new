# P8-G1 Test Report

> 日期：2026-09-23  
> 套件：`tests/test_p8g1_collaboration_query.py`  
> 结果：42 tests，OK，0.687s。不调用 DeepSeek、OpenAI、Real Extractor。

---

## 1. Query Service

| 编号 | 测试 | 结果 |
| --- | --- | --- |
| QUERY-01 | LIST_TOPICS，status 保持 ACTIVE | PASS |
| QUERY-02 | LIST_TASKS，不按 status 过滤，展示 OPEN | PASS |
| QUERY-03 | LIST_DECISIONS，去掉被 supersede 指向的决定，created_at 降序，status 仍为 RECORDED | PASS |
| QUERY-04 | LIST_RISKS 返回全部 | PASS |
| QUERY-05 | OPEN_RISKS 只留 OPEN | PASS |
| QUERY-06 | 单个主题的 TOPIC_SUMMARY | PASS |
| QUERY-07 | 标题全字相等 | PASS |
| QUERY-08 | 多个主题 AMBIGUOUS，不挑最近的 | PASS |
| QUERY-09 | 空结果是「未查询到已记录」 | PASS |
| QUERY-10 | DTO 不含 severity / owner / due / due_at | PASS |

主题摘要里的决定同样去掉被 supersede 指向的旧记录。

## 2. 会话范围

| 编号 | 结果 |
| --- | --- |
| QUERY-SCOPE-01 conv_A 的 LIST_TASKS 只有 A | PASS |
| QUERY-SCOPE-02 A 的风险结果没有 B 的 id，混入 A 文件但 conversation_id 不符的行被丢弃 | PASS |
| QUERY-SCOPE-03 不存在的 topic_id → NOT_FOUND，不读任务表来补 | PASS |
| QUERY-SCOPE-04 「看看另一个群有什么任务」→ OUT_OF_SCOPE，四个 list_* 都是 0 次 | PASS |
| QUERY-SCOPE-05 解析失败或 conversation_id 为空 → CONVERSATION_NOT_RESOLVED，list_* 为 0 | PASS |

## 3. Router

| 编号 | 结果 |
| --- | --- |
| ROUTER-01 @Agent 现在有哪些任务 → LIST_TASKS，旁路 0，Chat 0，send_reply 1 | PASS |
| ROUTER-02 有什么风险 → OPEN_RISKS | PASS |
| ROUTER-03 有哪些决定 → LIST_DECISIONS，正文没有「刚才」 | PASS |
| ROUTER-04 有哪些主题 → LIST_TOPICS | PASS |
| ROUTER-05 主题 XXX 什么情况 → TOPIC_SUMMARY | PASS |
| ROUTER-06 你好 → NOT_QUERY，旁路调用 1，原 handler 1 | PASS |
| ROUTER-07 未 @ 群消息不进 classify，旁路仍被调用 | PASS |
| ROUTER-08 /list 不被查询接管 | PASS |

身份句「我有什么任务」「张三负责什么」「张三有哪些任务」都不是 LIST_TASKS。

## 4. Command、停止、发送、旁路

| 编号 | 结果 |
| --- | --- |
| COMMAND-01 帮我创建一个任务 | PASS。固定文案，旁路 0，Chat 0，JSON 字节不变 |
| COMMAND-02 把风险关掉 | PASS |
| COMMAND-03 把任务改成完成 | PASS |
| QUERY-STOP-01 Runtime STOPPED | PASS。classify 0，Service 0，send_reply 0 |
| QUERY-SEND-01 | PASS。走 send_reply，源码没有 SendMsg |
| 旁路打开（DI `enabled=True`）时 Query / Command 的 Topic enqueue = 0 | PASS |
| NOT_QUERY「你好」enqueue = 1，并进入原 handler | PASS |
| allow_reply 拒绝时不退回 Chat | PASS |
| 会话锁被占用时不并行发送，也不退回 Chat | PASS |
| 查询不写 chat_contexts、user_queues、记忆日志 | PASS |
| 查询前后 topics/tasks/decisions/risks/processed/links 字节不变 | PASS |

旁路测试使用 `HeuristicTopicExtractor`。没有打开真实 Extractor。结束后四个 Engine 常量仍为 false，`is_topic_engine_enabled()` 为 false。

## 5. 源码约束

`query_router`、`query_service`、`query_formatter`、`collaboration_query` 的源码不含 `Engine(`、`Extractor`、`write_processing`、`commit_apply`、`retry_topic`、`retry_downstream`、`get_processing`、`get_deepseek`、`SendMsg`。

`collaboration_query` 只调用 `resolve_topic_conversation`，不调用 Topic Engine 流水线。
