# P8-G1 Closure Report

> 日期：2026-09-23  
> 结论：P8-G1 = COMPLETE

---

## 硬门槛

| 项 | 结果 |
| --- | --- |
| LIST_TOPICS | PASS |
| LIST_TASKS | PASS |
| LIST_DECISIONS | PASS。supersede 过滤，created_at 降序，status 保持 RECORDED |
| LIST_RISKS | PASS |
| OPEN_RISKS | PASS。员工问风险默认走这里 |
| TOPIC_SUMMARY | PASS。单主题、精确标题、多主题 AMBIGUOUS |
| Query 只读本次解析出的 Conversation.id | PASS |
| Query 不进 Topic 旁路 | PASS。Engine 以 DI 打开时 enqueue = 0 |
| Query 不进 Chat | PASS |
| Query 不写 Store | PASS。六个 JSON 字节不变 |
| Query 不写 Chat Context / 队列 / 记忆日志 | PASS |
| Command 不进旁路、不进 Chat、不写 Store | PASS |
| NOT_QUERY 保持原 Chat + 旁路 | PASS |
| 未 @ 群消息不进 Router | PASS |
| `/` 命令不被接管 | PASS |
| Formatter 不调用 LLM | PASS |
| Stop 阻断 Query | PASS。Router 0，Service 0，send_reply 0 |
| send_reply 是唯一发送路径 | PASS |
| 我的任务 / 某人负责 不误判成 LIST_TASKS | PASS |
| P6-G6 / P7 行为 | 非 live 回归包含这些套件，PASS |
| 四个 Engine 开关 | 均为 false |

没有触发 STOP。不需要改 Store schema、Dedupe、Engine decision、processing，也不需要 Query Queue、跨会话搜索、用 LLM 生成答案，或让查询继续进入 Topic Engine。

## 测试

```text
P8-G1 定向                 42 OK
Non-Live Regression       665 OK
                          623 旧基线 + 42 本 Gate
Real*ExtractorTests       42 条未执行
已知 live 失败            10 条，P7-G2 记录，本 Gate 未改 expectation
                          KNOWN LIVE DEPENDENCY FAILURE
```

## 本 Gate 不做、留给后续

```text
Query Intent LLM
MY_TASKS
负责人身份映射
跨会话查询
写命令
Reminder
自动 Retry
新 Engine
```

等待下一步指令。
