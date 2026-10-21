# P9-G2 Closure Report

> 日期：2026-09-23
> 结论：`P9-G2 = COMPLETE`
> 下一 Gate：`P9-G3 — Business Action Foundation`。本轮不实现，也不接微信。

## 1. 合同

```text
TASK_ID        当前会话精确命中 → RESOLVED
EXACT_TITLE    当前会话全字相等且唯一 → RESOLVED
重复标题       AMBIGUOUS，状态不参与消歧
其它会话       不返回该 Task
包含 / 相近标题 NOT_FOUND
CURRENT_TASK   UNSUPPORTED_REFERENCE
```

跨会话的 `status` 固定为 `NOT_FOUND`。不扫描其它会话目录。当前文件里的行若声明了别的 `conversation_id`，`reason` 为 `CONVERSATION_MISMATCH`，任务正文仍不返回。

Resolver 只读 `tasks.json`。损坏文件为 `CORRUPT`，缺文件为 `NOT_FOUND` 且不创建。

`DONE` 任务可以被解析。能否完成交给 `TaskLifecycleService.complete_task`。

## 2. 冻结面

```text
Resolver = READ ONLY
Resolver = 0 LLM
Resolver = 0 lifecycle write
```

微信「帮我把任务改成完成」仍回复「当前不能在这里修改任务、风险或决定。」

「接口联调今天已经完成了」仍是 `NOT_QUERY`，任务保持 `OPEN`。

Query Formatter、`LIST_TASKS`、`MY_TASKS` 未增加 `task_id`。四个 Engine 开关仍为 `false`。

## 3. 回归

```text
P9-G2 新测试 25 PASS
P9-G1 17 PASS
P8 + Task Store / Engine / Sidepath 196 PASS
Non-Live 809 PASS = 旧 784 + 新 25
Real Extractor 42 未运行
```

## 4. 停止

本轮不建立 ActionRequest、Preview、Confirmation、BusinessActionAudit。那些从 P9-G3 再开始。
