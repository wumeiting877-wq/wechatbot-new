# P9-G2 Task Target Design

> 给定当前 `conversation_id` 和一个已经结构化的 selector，只读解析出唯一 `task_id`。

## 1. 模块

`task_target_resolver.py`

```text
TaskTargetResolver.resolve_task_target(conversation_id, selector)
TaskTargetResolver.resolve_task_by_id(conversation_id, task_id)
TaskTargetResolver.resolve_task_by_exact_title(conversation_id, title)
```

输入必须已经是 `TaskTargetSelector`。自然语言句子留在以后的 Action Router。

Resolver 只调用 `TaskStore.conversation_dir` 定位当前会话的 `tasks.json`，然后自己读取。它不调用 `list_tasks`，因为那条路径会把损坏文件看成空表。

## 2. Selector v1

支持：

```text
TASK_ID
EXACT_TITLE
```

直接返回 `UNSUPPORTED_REFERENCE`，并且不打开 `tasks.json`：

```text
CURRENT_TASK
LAST_TASK
RECENT_TASK
FUZZY_TITLE
SEMANTIC_TITLE
INDEX_FROM_CHAT
```

会话里只有一个 Task 时，`CURRENT_TASK` 仍然是 `UNSUPPORTED_REFERENCE`。

未知类型、自然语言字符串、空标题、不符合 `task_[A-Za-z0-9_]+` 的 id、非法 `conversation_id`，都是 `INVALID_SELECTOR`。

## 3. 结果

```text
TargetResolutionResult
  status
  conversation_id
  selector_type
  task_id
  task
  candidates
  reason
```

`status`：

```text
RESOLVED
NOT_FOUND
AMBIGUOUS
UNSUPPORTED_REFERENCE
INVALID_SELECTOR
CORRUPT
```

`RESOLVED` 带 `task_id` 和任务字典副本。`AMBIGUOUS` 的 `task_id` 与 `task` 为空，`candidates` 保持文件中的顺序。每条候选只有：

```text
task_id
title
status
assignee_text
```

其它状态的 `candidates` 为空。

## 4. TASK_ID

只读当前会话文件。

```text
0 条 → NOT_FOUND
1 条 → RESOLVED
多于 1 条同一 task_id → AMBIGUOUS
```

同一 id 出现多行时不取第一行。`reason` 为 `DUPLICATE_TASK_ID`。

任务若只存在于另一个会话目录：不枚举其它目录，结果是 `NOT_FOUND`，`reason` 为 `NOT_FOUND`。不返回那个任务。

若行写在当前文件里，但 `conversation_id` 字段指向别的会话：该行不进入命中。全部被这条规则排除时，`status` 仍是 `NOT_FOUND`，`reason` 为 `CONVERSATION_MISMATCH`。`CONVERSATION_MISMATCH` 只出现在 `reason`，不进入 `status`。字段为空的行视为属于当前文件。

## 5. EXACT_TITLE

selector 只做 `strip()`。然后与存储的 `task.title` 做全字相等。存储标题不再 strip，大小写不折叠，外层引号不剥掉。

```text
1 条 → RESOLVED
0 条 → NOT_FOUND
多于 1 条 → AMBIGUOUS，reason = DUPLICATE_TITLE
```

`OPEN` 与 `DONE` 同时同名时仍是 `AMBIGUOUS`。`DONE` 且标题唯一时仍是 `RESOLVED`。解析不判断能不能完成。

其它会话的同名任务不进入 `candidates`。

包含关系、相近标题、编辑距离都不构成命中。例如存储标题 `新华接口联调`、selector `接口联调`，结果是 `NOT_FOUND`。

## 6. 文件

| 情况 | 结果 |
| --- | --- |
| 没有 `tasks.json` | `NOT_FOUND`，不创建文件、不创建目录 |
| `{"tasks": []}` | `NOT_FOUND` |
| JSON 无法解析 | `CORRUPT`，`reason=TASKS_UNREADABLE`，原字节保留 |
| `tasks` 不是对象列表 | `CORRUPT`，`reason=TASKS_STRUCTURE_INVALID`，原字节保留 |

读取不持有 `tasks.json.lock`，因此不产生 lock 文件。并发迁移使用 `os.replace`，读者看到的是替换前或替换后的完整文件。解析失败时不回写修复。

调用前后这些文件字节不变：

```text
tasks.json
links.json
processed.json
task_person_links.json
```

不读 processing，不读消息链接，不读 `TaskIdentityLink`。同名任务里即使一条已经链到当前用户，仍然 `AMBIGUOUS`。

## 7. 与生命周期分开

Resolver 不调用 `TaskLifecycleService.complete_task`，也不调用 `transition_task_status`。

后续可以：

```text
resolve_task_target
  → RESOLVED.task_id
  → TaskLifecycleService.complete_task
```

对象已经是 `DONE` 时，解析仍返回 `RESOLVED`。再次完成由生命周期返回 `ALREADY_IN_STATE`。

## 8. 本 Gate 不接入的层

微信 Command、Query Formatter、`LIST_TASKS`、`MY_TASKS` 保持原样。回复里仍不展示 `task_id`。

「帮我把任务改成完成」仍是原来的固定拒绝。

「接口联调今天已经完成了」仍是 `NOT_QUERY`。
