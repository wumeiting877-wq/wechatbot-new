# P9-G3 Current State Audit

> 进入本 Gate 时，完成任务还不能形成一条可确认、可幂等、可追踪的业务动作。

## 1. 基线

```text
P0–P5 = CLOSED / COMPLETE
P6-G0 … P6-G5 = COMPLETE
P6-G6 = BLOCKED / TYPE C
P7-G0 … P7-G2 = COMPLETE
P8-G0 … P8-G3 = COMPLETE
P8-G4 = BLOCKED / TYPE C
P8-G5 = COMPLETE / MODEL-A
P8-G6 = COMPLETE
P9-G0 = COMPLETE
P9-G1 = COMPLETE
P9-G2 = COMPLETE
```

进入时 Non-Live = 809 OK。四个 Engine 常量均为 `false`。

## 2. 已有能力

P9-G1：

```text
TaskLifecycleService.complete_task(conversation_id, task_id)
```

合法流转只有 `OPEN → DONE`。`DONE` 再次进入得到 `ALREADY_IN_STATE`，不写文件。期望 `OPEN` 但当前已是其它非 `DONE` 状态时得到 `STALE_STATE`，不覆盖。

P9-G2：

```text
TaskTargetResolver
```

当前会话内支持 `TASK_ID` 和 `EXACT_TITLE`。重复命中为 `AMBIGUOUS`，不选取。跨会话不返回。`CURRENT_TASK` 等为 `UNSUPPORTED_REFERENCE`。解析不写任务，不调用生命周期。

## 3. 当时没有的层

没有结构化 `ActionRequest`。没有 Preview。没有必须显式调用的 `confirm_action`。没有按 `conversation_id + message_id + action_type + target_task_id` 稳定下来的 `action_id`。没有独立于运维重试审计的 Business Action 记录。

因此调用方即使已经拿着 `task_id`，也还没有「先展示、再确认、再只执行一次」的边界。`prepare` 与 `apply` 还不是两个动作。

## 4. 仍然冻结的入口

微信「帮我把任务改成完成」仍由 Command 路由回复「当前不能在这里修改任务、风险或决定。」生命周期调用为 0。

「接口联调今天已经完成了」仍是普通聊天，不改 Task。

`update_task` 对 `status` 仍是 `INVALID_STATUS`。P9-G1 记录的整表写并发窗口没有在本 Gate 之前被收掉。
