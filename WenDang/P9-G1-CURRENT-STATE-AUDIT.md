# P9-G1 Current State Audit

> 进入本 Gate 时的生产合同。写锁细节见 `P9-G1-G0-TASK-TRANSITION-AUDIT.md`。

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
```

进入时 Non-Live = 767 OK。四个 Engine 常量均为 `false`。

## 2. Task 写合同

```text
CREATE → status = OPEN only
UPDATE → status 一律 INVALID_STATUS
```

源码常量有 `OPEN`、`IN_PROGRESS`、`DONE`、`CANCELLED`。`ALLOWED_WRITE_STATUSES` 只有 `OPEN`。

当时不存在合法流转：

```text
OPEN → IN_PROGRESS
OPEN → DONE
OPEN → CANCELLED
```

`commit_apply` 的更新循环会直接赋 `fields`。生产 Engine 不传 `status`。这是内部缝，不是完成任务的合同。

## 3. 旁边三条仍只写初态

```text
Risk     OPEN only
Decision RECORDED only
Topic    创建 ACTIVE，生产 Engine 不改 status
```

## 4. 查询与命令

`LIST_TASKS` 读取会话里的任务，不过滤 status。个人查询只按 `TaskIdentityLink` 取任务，也不按 status 过滤。Formatter 打印存储里的 status 原文。

微信句「帮我把任务改成完成」走 Command，固定回复「当前不能在这里修改任务、风险或决定。」

「接口联调今天已经完成了」不是 Command。Extractor 提示词要求完成陈述输出 `UNRELATED`。`TASK_ENGINE_ENABLED=false`，这条句子不会写 Task。

## 5. 与生命周期无关的存储

```text
tasks.json                         Task 正文
links.json                         消息证据
processed.json                     一条消息的 Task Engine 处理结果
data/identity/task_person_links.json   负责人链接
```

`TaskIdentityLink` 与 Task status 分文件、分锁。processing 不是 Task 的当前生命周期。
