# P8-G2 Test Report

> 日期：2026-09-23  
> 套件：`tests/test_p8g2_query_intent.py`  
> 结果：25 tests，OK，0.446s。不连接真实模型。

---

## 1. 规则优先

| 编号 | 输入 | 结果 |
| --- | --- | --- |
| INTENT-01 | 现在有哪些任务 | LIST_TASKS，classifier = 0 |
| INTENT-02 | 目前有哪些风险 | OPEN_RISKS，classifier = 0 |
| INTENT-03 | 有哪些决定 | LIST_DECISIONS，classifier = 0 |
| — | 刚才确定了什么 | LIST_DECISIONS，classifier = 0，没有 RECENT_DECISIONS |

## 2. 分类器回退

Fake Completer 按句子返回枚举。生产解析只取 `query_type`。

| 编号 | 输入 | 结果 |
| --- | --- | --- |
| INTENT-04 | 帮我盘一下现在手上的待办 | LIST_TASKS |
| INTENT-05 | 我们主要有哪些潜在问题需要注意 | OPEN_RISKS |
| INTENT-06 | 之前到底定下来了哪些事情 | LIST_DECISIONS |
| INTENT-07 | 这个群现在主要在推进哪些事情 | LIST_TOPICS |
| INTENT-08 | 帮我看看当前主题整体怎么样 | TOPIC_SUMMARY |

同一组还锁了「哪些风险点」「哪几个事情」「看一下当前主题的整体情况」。`topic_title` 保持空。

## 3. 普通讨论和寒暄

| 编号 | 输入 | 结果 |
| --- | --- | --- |
| INTENT-09 | 今天必须完成接口联调 | NOT_QUERY，classifier = 0，旁路继续 |
| INTENT-10 | 测试环境目前有风险 | NOT_QUERY，classifier = 0 |
| INTENT-11 | 我们决定周五上线 | NOT_QUERY，classifier = 0 |

另外锁定：测试环境现在有风险、这个主题今天继续讨论、你好、在吗、谢谢、好的、收到。classifier = 0。

「任务怎么样了」会进分类器。Fake 返回 `NOT_QUERY` 时旁路继续。「风险呢」「决定呢」不进分类器。

## 4. 安全优先级

| 编号 | 输入 | 结果 |
| --- | --- | --- |
| INTENT-12 | 帮我看看另一个群有哪些任务 | OUT_OF_SCOPE，不读任务表，classifier = 0 |
| INTENT-13 | 我有什么任务 / 我的任务 | 固定个人身份文案，classifier = 0 |
| INTENT-14 | 张三负责什么 / 张三有哪些任务 | 固定人员身份文案，classifier = 0 |
| INTENT-15 | 帮我创建一个任务 / 删除这个任务 | COMMAND 固定文案，classifier = 0 |

「李明负责补材料」仍进旁路，不发身份拒绝文案。

`classify_agent_message("我有什么任务")` 仍是 `KIND_NOT_QUERY`，不是 `LIST_TASKS`。

## 5. 失败

候选句上：

| 编号 | 注入 | 状态 |
| --- | --- | --- |
| CLASSIFY-01 | TimeoutError | TIMEOUT |
| CLASSIFY-02 | ConnectionError | CONNECTION_ERROR |
| CLASSIFY-03 | 非法 JSON / Markdown | CLASSIFIER_INVALID |
| CLASSIFY-04 | `{"query_type":"MY_TASKS"}` | CLASSIFIER_INVALID |
| CLASSIFY-05 | 空字符串 / 自然语言 | CLASSIFIER_INVALID |

这些结果都不进 Query Service，不进旁路，不进 Chat。回复是固定指引。`user_queues`、`chat_contexts`、记忆日志不增加。topics / tasks / decisions / risks / processed / links 字节不变。

## 6. Store 与范围

INTENT-04 的 Fake JSON 带 `"answer":"任务A"`。用户看到的是 Store 里的「完成接口联调」，没有「任务A」，也没有会话 B 的「B的任务」。

`TOPIC_SUMMARY` 的 Fake JSON 带 `"topic_title":"伪造主题"`。单主题回复来自 Store 的「接口联调」。两个主题时走原有 AMBIGUOUS 文案，不采用伪造标题。

## 7. 其他

```text
Runtime STOPPED：route_hybrid、Query Service、send_reply 都是 0
会话锁占用：分类查询被消费，不发送，不退回 Chat
窄调用测试：messages 只有 system + user，timeout=8，temperature=0，max_tokens<=128
线程超时测试：with_options(timeout=0.2, max_retries=0)，不读 chat_contexts
源码：分类器不含 Store / Engine / Extractor / send_reply / get_deepseek_response
```

结束后四个 Engine 常量仍是 `false`。
