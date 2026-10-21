# P8-G0 Deferred Issues

> 日期：2026-09-23  
> 下列项不是 P8-G0 的缺口。第一版 Query 在没有它们的情况下可以做。

---

## 身份类

```text
MY_TASKS
    入站 sender_id / sender_wxid / sender_name
    与 Task.assignee_text 没有确定性映射

TASKS_BY_ASSIGNEE
    Store 禁止 assignee / assignee_id / assignee_wxid
    assignee_text 不能做“张三”精确身份匹配
    禁止昵称模糊匹配和 LLM 猜测
```

要做这两类，需要单独的身份契约。那不是 P8 v1，也不在本 Gate 改 Task schema。

---

## 时间与状态

```text
RECENT_DECISIONS
    created_at 只能排序，不能定义“刚才”
    员工那句问法在 v1 落到 LIST_DECISIONS

Task 状态过滤
    常量有 IN_PROGRESS / DONE / CANCELLED
    允许写入和更新的只有 OPEN
    v1 不提供 TODO / DOING / DONE 查询

Decision Open/Closed
    落盘 status 为 RECORDED
    不把 supersedes 指针显示成 SUPERSEDED

Risk MITIGATED / RESOLVED / CLOSED
    常量存在，v1 禁止写入，update 禁止改 status
    员工问风险使用 OPEN_RISKS
```

---

## 查询能力

```text
CROSS_CONVERSATION_QUERY
SEMANTIC_QUERY
FREEFORM_STORE_QUERY
把四个 Store 全量塞进 Chat Prompt
用 LLM 生成微信正文
TOPIC_SUMMARY 读聊天记录再总结
Query Queue / Worker
```

跨会话在路由上是 `OUT_OF_SCOPE`，不是以后偷偷扫描。

`TOPIC_SUMMARY` 在多个主题且没有精确标题时是 `AMBIGUOUS`，不猜测“这个”。

---

## 写操作

```text
创建任务
完成任务
关闭风险
修改决定
指派负责人
```

属于 Command。v1 固定不支持。不进 Query Service，也不进 Chat LLM。

现有 `/` 文本命令保持原实现，不并入 Query。

---

## 仍留在原系统里的已知限制

```text
P6-G6  missing processing
    Query 看见实体时不补 processing，不自动 Retry

四个 Engine 默认关闭
    本 Gate 不打开
    Engine 打开后，未识别成 Query 的 REPLY 仍会进 Topic 旁路
    这是现有 classify_topic_skip 的行为，P8-G1 只对已识别 Query/Command 跳过入队

10 条 Real Extractor live failure
    属于既有 live adapter，不在 P8 修复
```

---

## 明确不阻塞 P8-G1

不需要：

```text
改 Topic / Task / Decision / Risk schema
改 P0 Dedupe
改 Engine decision schema
改 processing schema
跨会话全局搜索
新的 Queue 或 Worker
```
