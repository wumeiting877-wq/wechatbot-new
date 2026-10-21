# P9-G1 Closure Report

> 日期：2026-09-23
> 结论：`P9-G1 = COMPLETE`
> 下一 Gate：本轮不选、不执行。候选是 Task Target Resolution，或 Business Action Foundation。

## 1. 合同

```text
CREATE 仍只能 OPEN
update_task 对 status 仍是 INVALID_STATUS
正式入口是 TaskLifecycleService.complete_task
Store 入口是 transition_task_status
v1 新增流转只有 OPEN → DONE
DONE 为终态
```

仍然非法：

```text
OPEN → IN_PROGRESS
OPEN → CANCELLED
DONE → OPEN
DONE → IN_PROGRESS
DONE → CANCELLED
IN_PROGRESS → DONE
IN_PROGRESS → CANCELLED
CANCELLED → OPEN
```

再次完成已经是 `DONE` 的任务：`ALREADY_IN_STATE`，不写文件，不改 `updated_at`。

期望 `OPEN` 时任务已变成别的状态、且还不是 `DONE`：`STALE_STATE`，不覆盖。

`TaskIdentityLink` 字节在 `OPEN → DONE` 后保持不变。processing 不写。损坏的 `tasks.json` 返回 `CORRUPT`，原文件保留。

## 2. 冻结面

P8 Query 仍返回 `DONE` 任务，Formatter 显示 `状态：DONE`。

微信「帮我把任务改成完成」仍回复「当前不能在这里修改任务、风险或决定。」生命周期调用为 0，任务保持 `OPEN`。

「接口联调今天已经完成了」不改 Task status。离线 Extractor 行为仍是 `UNRELATED`。

`task_engine.py` 无 diff。四个 Engine 开关仍为 `false`。

## 3. 回归

```text
P9-G1 新测试 17 PASS
P8 + Task Store / Engine / Sidepath 196 PASS
Non-Live 784 PASS = 旧 767 + 新 17
Real Extractor 42 未运行
```

## 4. 停止

本轮不接微信 Command，不实现目标解析，不改 Risk / Decision / Topic 状态。
