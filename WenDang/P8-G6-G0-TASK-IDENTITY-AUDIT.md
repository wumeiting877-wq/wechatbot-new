# P8-G6 Gate 0 — Task 生命周期审计

> 日期：2026-09-23  
> 范围：只读。本文件先于 TaskIdentityLink 写入。  
> 结论：可以在 Task 成功语义完成之后做 best-effort 链接。不需要改 Task schema。

---

## 1. 稳定 task_id 在哪里取得

生产路径是 `TaskEngine._apply_decisions` → `TaskStore.commit_apply`。

`commit_apply` 在内存里合并新任务、更新和消息链接，再一次性写 `tasks.json` / `links.json`。同 id 撞上不同消息时会加 `_2` 后缀。返回值里的 `task_ids` 已经是最终 id。

`TaskEngine._finalize` 随后把这组最终 id 写入 `TaskProcessingRecord`。因此：

```text
commit_apply 成功
↓
返回的 task_ids
↓
才是可以拿去绑定的稳定 task_id
```

`create_task` 是遗留直连入口，也会在冲突时改后缀，但生产 Engine 不走它。身份链接只认 `commit_apply` 之后新出现的 id。

## 2. assignee_text 能否被更新

能。

`TaskStore.update_task` 允许非空 `assignee_text` 覆盖原值。空字符串会被忽略，所以不能靠空值把负责人清掉。

`commit_apply` 的 updates 会按字段原样写入，包括 `assignee_text`。

`TaskEngine` 在 `TASK_UPDATE` 里，只要抽取结果给出非空负责人，就会把 `assignee_text` 放进更新字段。

## 3. 负责人文本变了，旧链接怎么办

第一版不自动换人，也不删除旧链接。

```text
已有 TaskIdentityLink
+
assignee_text 后续变化
→ 保留旧 person_id
→ 日志：manual confirmation required
```

更新路径不会因为新的 `assignee_text` 再写一条链接。没有旧链接时，也不在更新时补绑。

## 4. 链接插入会不会改变 Task 成功语义

不会，只要链接发生在 Task 成功语义已经落盘之后，并且异常被吃掉。

实际顺序：

```text
commit_apply 成功
↓
_finalize 写 processing / audit，并返回 EngineResult
↓
_attach_identity_links
```

`_attach_identity_links` 包在自己的 `try/except` 里。它不参与 `commit_apply` 的任务回滚，也不改 processing。

## 5. Task 成功、链接失败时，Task 是否仍必须成功

必须成功。

链接失败不会：

```text
回滚 tasks.json
把 processing 改成 FAILED
删除 Task
```

对应测试：`test_link_failure_keeps_task_success`。处理记录仍是成功，任务还在，链接文件没有被写成半条。

## 6. 因此允许的自动绑定

只对本次 `commit_apply` 里真正新出现的 task_id：

```text
assignee_text.strip()
↓
resolve_exact_alias
↓
唯一 person_id 且人员 ACTIVE
↓
source = EXACT_EXPLICIT_ALIAS
```

`李明负责`、`由李明`、`@李明`、`研发部李明` 在别名只有 `李明` 时都是 `NOT_FOUND`，不写链接。

历史任务不在这次新 id 集合里，保持未绑定。
