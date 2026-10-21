# P8-G3 Deferred Issues

> 日期：2026-09-23  
> 这些不是本 Gate 的失败，也不要在这一步顺手做。

---

## 1. 明确不做

```text
MY_TASKS
负责人身份映射
写 Command 落库
跨会话 Query
Reminder
自动 Retry
新 Engine
通用 Query Worker
Redis / Kafka / 数据库队列 / Scheduler
```

P6-G6 仍是 `BLOCKED / TYPE C`。

## 2. 已知但不在本 Gate

```text
任务怎么样了 → CLASSIFIER_INVALID
```

Live smoke 的分类失败。本 Gate 不改 classifier prompt。

四个 Real Extractor 的 `Connection error` / `EXTRACTOR_TIMEOUT` 仍是：

```text
KNOWN LIVE DEPENDENCY FAILURE
```

## 3. 交付层留下的边界

第一次到达时 `allow_reply` 就失败的 Query，仍然不入队。这是 P8-G1 的冷却行为。只有已经因为 session 忙而入队的回复，才会在冷却结束后由现有的空闲检查补发。

生产环境的 `send_reply` 先进入发送队列，`note_replied` 发生在真正发出之后。同一轮 flush 因此可能在冷却记录落地前连续提交最多 3 条。微信发送仍由原来的 send queue 串行执行。本 Gate 不改 `send_reply`，也不为了拉开间隔去 sleep。

超过 3 条或超过 60 秒，只丢弃并打日志，不给用户另发一条说明。

pending 不持久化。进程退出或 Stop 之后不会补发旧问题。
