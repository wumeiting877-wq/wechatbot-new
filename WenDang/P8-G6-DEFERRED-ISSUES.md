# P8-G6 Deferred Issues

> 日期：2026-09-23  
> 这些留在本 Gate 之外。没有把它们做成静默行为。

---

## 1. 失败的 best-effort 不会在重放时再试

Task processing 一旦成功，重放会在 `_process_record` 开头返回，不再进入 `commit_apply`，因此也不会再次 best-effort 链接。

任务仍然成功。漏掉的链接要用 `link_task_to_person(..., source="MANUAL")` 补。本 Gate 不自动重试。

## 2. 没有解绑和改派

链接冲突只返回 `CONFLICT`。错误链接的人工修复留到后续。

## 3. 负责人文本变化只记日志

日志是：

```text
TaskIdentityLink kept after assignee_text change; manual confirmation required
```

没有运营队列，没有 UI。

## 4. 明确不做

```text
历史任务自动迁移
人员 / 任务绑定页面
跨会话查询
写 Command
组织权限
Reminder
新业务 Engine
用 canonical_name 自动补别名
```

`preview_task_identity_links()` 可以看数量。它不写文件。
