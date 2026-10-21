# P9-G3 Closure Report

> 日期：2026-09-23
> 结论：`P9-G3 = COMPLETE`
> 下一 Gate：本轮不执行。候选是 P9-G4 — Task Command Intent & Confirmation Conversation。

## 1. 合同

```text
COMPLETE_TASK 是唯一 Action
ActionRequest 为结构化输入
Target Resolver 唯一解析
↓
Preview
↓
confirm_action(action_id, actor_ref)
↓
TaskLifecycleService.complete_task
```

准备阶段 Task 写入为 0。没有确认时 Task 写入为 0。

同一个 `conversation_id + message_id + action_type + target_task_id` 只有一个 `action_id`。重复确认不重复执行。Actor 不匹配不执行。

`OPEN → DONE` 记为 `EXECUTED`。确认前已经是 `DONE` 记为 `SUCCEEDED_NOOP`。`STALE_STATE`、`WRITE_FAILED`、`TASK_NOT_FOUND` 记为 `FAILED`，不覆盖，不自动重试。

Action Record 负责恢复和幂等。Business Action Audit 负责事件历史。Audit 写失败不回滚已经成功的 Task。

## 2. 冻结面

```text
0 LLM
0 微信 Command
0 Query 写入
0 Processing 写入
0 IdentityLink 变更
```

微信「帮我把任务改成完成」仍回复「当前不能在这里修改任务、风险或决定。」

P8 Query 仍返回 `DONE`，Formatter 仍显示 `状态：DONE`。Query 不读 Business Action Audit。

四个 Engine 开关仍为 `false`。

## 3. 回归

```text
P9-G3 新测试 32 PASS
P9-G1 17 PASS
P9-G2 25 PASS
P8 + Task Store / Engine / Sidepath 196 PASS
Non-Live 841 PASS = 旧 809 + 新 32
Real Extractor 42 未运行
```

## 4. 停止

本轮不解析自然语言命令，不把 Preview 或确认发到微信，不增加其它 Action Type。
