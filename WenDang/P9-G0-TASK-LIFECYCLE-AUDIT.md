# P9-G0 Task Lifecycle Audit

> 扫描：`task_store.py`、`task_engine.py`、`task_sidepath.py`、`task_extractor_client.py`、`prompts/extractors/TASK_EXTRACTOR.md`、`task_identity_link.py`
> 结论先写：创建只允许 OPEN。更新接口拒绝改 status。完成任务当前不可做。

## 1. 状态常量

`task_store.py`：

```text
TASK_STATUS_OPEN = OPEN
TASK_STATUS_IN_PROGRESS = IN_PROGRESS
TASK_STATUS_DONE = DONE
TASK_STATUS_CANCELLED = CANCELLED
ALLOWED_WRITE_STATUSES = (OPEN,)
```

常量有四个。允许写入的集合只有 `OPEN`。

## 2. 创建允许的 status

`create_task` → `_normalize_new_task`：

```text
传入 status 不在 ALLOWED_WRITE_STATUSES → INVALID_STATUS「v1 只允许写入 OPEN」
落盘字段 status 被强制写成 OPEN
due_at 非空会被清成空字符串
```

Task Engine 的 `NEW_TASK` 在组记录时写死：

```text
status = OPEN
due_at = ""
```

```text
CREATE_STATUS = OPEN ONLY
```

Extractor 允许的 decision 只有 `NEW_TASK`、`TASK_UPDATE`、`UNRELATED`。`TASK_COMPLETE`、`DONE`、`IN_PROGRESS`、`CANCELLED` 在禁止列表里。提示词要求：消息说已完成、已修好、关掉吧，也输出 `UNRELATED`，本版本不结束 Task。

## 3. 更新是否允许状态流转

`update_task`：

```text
字段里带有非空 status → INVALID_STATUS「TASK_UPDATE 不得改 status」
不写入新 status
conversation_id / topic_id → IMMUTABLE_FK
非空 due_at → DUE_AT_FORBIDDEN
```

因此这三条都不会发生：

```text
OPEN → IN_PROGRESS   INVALID_STATUS
OPEN → DONE          INVALID_STATUS
OPEN → CANCELLED     INVALID_STATUS
```

Task Engine 的 `TASK_UPDATE` 组装的 fields 只有：

```text
confidence
title            （非空才放）
description      （非空才放）
assignee_text    （非空才放）
due_text         （非空才放）
```

没有 `status`。然后调用 `commit_apply`。

`commit_apply` 的更新循环会把 `fields` 里的键直接赋给任务，自身不再检查 status。这是内部缝，不是生产能力：当前 Engine 不传 status，公开的 `update_task` 会拒绝 status。不能把这条缝当成「已经支持完成」。

## 4. 字段矩阵

| 字段 | 创建 | 更新 | Engine 会写 | 备注 |
| --- | --- | --- | --- | --- |
| title | 会，截断 40 | `update_task` 会，空字符串跳过 | `NEW_TASK` 会写；`TASK_UPDATE` 非空才写 | |
| description | 会，截断 500 | `update_task` 会，空字符串跳过 | `NEW_TASK` 会写；`TASK_UPDATE` 非空才写 | |
| assignee_text | 会 | `update_task` 会，空字符串跳过 | `NEW_TASK` 必有（校验失败则不落盘）；`TASK_UPDATE` 非空才写 | 文本变化不换 `TaskIdentityLink` |
| due_text | 会 | `update_task` 会，空字符串跳过 | `NEW_TASK` 会写；`TASK_UPDATE` 非空才写 | |
| due_at | 创建时强制空 | 非空即 `DUE_AT_FORBIDDEN` | 创建写 `""`；更新不传 | |
| status | 只允许 OPEN，否则 `INVALID_STATUS` | `update_task` 一律 `INVALID_STATUS` | 创建写 OPEN；更新不传 | `commit_apply` 更新循环不二次校验，生产 Engine 不用这条缝 |

`NEW_TASK` 在 Engine 校验里还要求 title 与 assignee_text。assignee_text 必须来自原文或自称发送者。Store 的 `create_task` 允许空负责人。两条路径不一致：微信命令若将来直连 Store，会比 Engine 更松。

禁止写入的任务键包括 `assignee_id`、`assignee_wxid`、`assignee`、`priority`、`progress_percent`。没有单条任务的 delete。`delete_conversation_task_data` 只删除整个会话目录。

## 5. TaskIdentityLink 与改派

`TASK_UPDATE` 若写入了不同的 `assignee_text`，Engine 只把 `task_id` 放进 `assignee_drifts`。

`note_assignee_text_drift` 的行为：

```text
旧 TaskIdentityLink 保留
不改 person_id
不删除链接
只打日志：manual confirmation required
```

`link_task_to_person` 在同一 `conversation_id + task_id` 已绑定另一个 `person_id` 时抛 `CONFLICT`，禁止覆盖。没有 unlink / rebind。

新任务才可能自动绑定，而且只在精确别名解析到一名在职人员时。这不是改派。

```text
李明 → 王强
当前实际行为 = 文本可以在 Engine 更新路径被改掉
旧链接保留
不自动换人
```

本 Gate 锁定这条行为。

## 6. 「把接口联调标记为完成」

```text
NOT_SUPPORTED
```

卡住的层：

| 层 | 结果 |
| --- | --- |
| Intent | 命中固定 Command 模板时直接拒绝，不进 Engine |
| Extractor | `DONE` / `TASK_COMPLETE` 被拒绝；完成陈述要求输出 `UNRELATED` |
| Engine | `TASK_UPDATE` 不传 status；`NEW_TASK` 只写 OPEN |
| Store | `update_task` 对 status 抛 `INVALID_STATUS`；创建只收 OPEN |
| Status contract | 没有 OPEN→DONE 的合法流转 |
| Identity | 与完成无关；改派才碰到链接 |

带标题的句子「把接口联调这个任务标记为完成」甚至匹配不上当前 Command 全字模板，会落到普通聊天。Engine 关闭，普通聊天也不会写 Task。两条路都不完成任务。
