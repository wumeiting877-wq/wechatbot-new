# P8-G6 TaskIdentityLink Design

> 日期：2026-09-23  
> 方案：P8-G5 选定的方案 B。不改 Task schema。

---

## 1. 记录

文件：`data/identity/task_person_links.json`

```text
TaskIdentityLink {
    conversation_id
    task_id
    person_id
    source
    created_at
}
```

来源只允许：

```text
MANUAL
TRUSTED_DIRECTORY
EXACT_EXPLICIT_ALIAS
```

写入沿用 IdentityStore 的 FileLock、临时文件、`os.replace`。JSON 损坏时抛 `CORRUPT`，原字节保持，不重置成空文件。

## 2. 唯一性

```text
conversation_id + task_id → 最多一个 person_id
```

再次绑定同一人：返回原记录，不改 `source`，不改 `created_at`。  
绑定另一个人：`CONFLICT`，不覆盖。

本版没有 `unlink_task`，也没有 `reassign_task_person`。

## 3. 引用完整性

写入前确认：

```text
Person 存在且 status == ACTIVE
Task 存在
Task.conversation_id == link.conversation_id
```

否则：

```text
PERSON_NOT_FOUND
PERSON_DISABLED
TASK_NOT_FOUND
CONVERSATION_MISMATCH
```

`DISABLED` 人员可以留下历史链接，但不能新建。

`EXACT_EXPLICIT_ALIAS` 还要求 `Task.assignee_text.strip()` 经 `resolve_exact_alias` 得到同一个 `person_id`。别名不是这段文本的全等值时返回 `NOT_FOUND`，不写文件。

## 4. 新任务

只在 `_finalize` 成功返回之后：

```text
本次 commit 里新出现的 task_id
↓
精确别名唯一且人员 ACTIVE
↓
best-effort EXACT_EXPLICIT_ALIAS
```

失败只记日志。历史任务不扫描、不批量写入。

`preview_task_identity_links()` 只读，输出：

```text
EXACT_RESOLVABLE
UNRESOLVED
AMBIGUOUS
ALREADY_LINKED
```

Preview 不等于 Apply。

## 5. 更新

`assignee_text` 变化且旧链接还在：保留链接，打人工确认日志。不删除，不换人。
