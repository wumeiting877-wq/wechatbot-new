# P9-G2 Current State Audit

> 进入本 Gate 时的目标解析缺口。生命周期合同见 `P9-G1-CLOSURE-REPORT.md`。P9-G0 已确认没有当前任务指针。

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
```

进入时 Non-Live = 784 OK。四个 Engine 常量均为 `false`。

## 2. 已有生命周期

```text
TaskLifecycleService.complete_task(conversation_id, task_id)
```

合法流转只有 `OPEN → DONE`。`DONE` 是终态。

`update_task(status=...)` 仍抛 `INVALID_STATUS`。

当时没有函数把 selector 收成 `task_id`。`complete_task` 要求调用方已经拿着 `task_id`。

## 3. Store 能读到什么

`TaskStore.get_task` / `list_tasks` 只打开当前会话目录里的 `tasks.json`。它们走 `read_json`。文件不存在时返回空列表。JSON 解析失败时也返回空列表，不把文件标成损坏。

因此直接用 `list_tasks` 做目标解析，会把损坏文件看成「没有这条任务」。

会话目录之外的任务不会出现在这次读取里。`TaskIdentityLinkStore._other_conversation` 会枚举其它会话来判断链接冲突。那是身份链接的写入检查，不是目标解析，本 Gate 不调用它。

## 4. 标题与指针

`Task.title` 写入时去掉首尾空白，最长 40 字。创建时没有唯一约束，同名任务可以并存。

当时不存在：

```text
当前会话 title 全字相等 → 唯一 Task
重复标题 → AMBIGUOUS
```

也没有这些字段：

```text
current task
last referenced task
stable short reference
```

主题查询的 `_bind_topic` 会在会话里只有一个主题、且用户没有点名时选中它。任务没有对应函数。本 Gate 不能把「只有一个 Task」当成「这个任务」。

## 5. 微信侧

`query_formatter` 的任务列表输出序号、标题、负责人、状态、时间说明。不输出 `task_id`。

「帮我把任务改成完成」仍是 Command，固定回复「当前不能在这里修改任务、风险或决定。」

「接口联调今天已经完成了」仍是 `NOT_QUERY`。

`query_router._is_command` 的模板没有按标题点名任务的分支。
