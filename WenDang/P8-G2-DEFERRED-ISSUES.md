# P8-G2 Deferred Issues

> 日期：2026-09-23  
> 这些项不在本 Gate。分类器没有被用来临时顶上。

---

## 1. 继续 Deferred

```text
MY_TASKS                 没有 assignee_id / wxid / sender 映射
TASKS_BY_ASSIGNEE        不用 assignee_text 模糊匹配，不用模型猜人
RECENT_DECISIONS         「刚才确定了什么」仍是 LIST_DECISIONS，没有时间窗
CROSS_CONVERSATION_QUERY 仍是 OUT_OF_SCOPE
写 Command 落库           创建 / 完成 / 关闭 / 修改 / 指派 / 删除仍是固定拒绝
Query Queue / Worker
Reminder
自动 Retry
新的业务 Engine
```

身份问句现在有固定回复，不再掉进 Chat。这不是身份映射，也不是 `LIST_TASKS`。

## 2. 会话忙

Chat 正占用 `try_acquire_session` 时，规则查询和分类查询都被消费：本轮不发送，不退回 Chat，不进旁路。没有 pending queue。和 P8-G1 相同。

## 3. 候选门故意偏严

「目前 / 现在 / 情况」单独不打开分类器。漏掉的问法仍回原 Chat。误判成 Query 会跳过一次提取，所以宁可不进分类器。

「风险呢」「决定呢」不进分类器。

## 4. Live 空回复

可选 smoke 里，「任务怎么样了」的模型 `content` 为空，被当成 `CLASSIFIER_INVALID`，走固定指引，不进旁路。没有为了这一条放宽 JSON 规则，也没有改成回 Chat。详见 `P8-G2-LIVE-CLASSIFIER-SMOKE.md`。
