# P9-G1 Gate 0 — Task 状态迁移写锁审计

> 扫描时间：修改生产代码之前
> 扫描对象：`task_store.py`、`store_io.py`、`task_identity_link.py`
> 结论先写：现有 Task 更新不是锁内读改写。`tasks.json` 的成功提交点是 `os.replace`。`TaskIdentityLink` 是另一把锁、另一个文件。本 Gate 的状态迁移不能复用 `update_task` 或 `commit_apply`。

## 1. 一个 status 变更今天怎样落盘

生产代码没有合法的 status 变更。

`update_task` 见到非空 `status` 就抛 `INVALID_STATUS`，并且抛出点在 `_save_tasks` 之前。创建路径 `_normalize_new_task` 只接受 `ALLOWED_WRITE_STATUSES = (OPEN,)`，否则同样是 `INVALID_STATUS`，落盘前就失败。

如果将来有人沿用今天的更新形状去改别的字段，实际步骤是：

```text
list_tasks
  → read_json
  → FileLock(tasks.json.lock)
  → 读完即释放锁
内存里改字段
_save_tasks
  → atomic_write_json
  → 再次 FileLock(tasks.json.lock)
  → 写 tasks.json.tmp
  → os.replace(tmp, tasks.json)
  → 释放锁
```

`commit_apply` 也是先 `list_tasks` / `list_links`，在锁外合并，再 `_commit` → `_save_tasks` + `_save_links`。更新循环把 `fields` 原样赋给任务，自己不再检查 `status`。这是 P9-G0 已经记下的内部缝。本 Gate 不用它实现生命周期。

## 2. read → unlock → write

`update_task` 和 `commit_apply` 都是锁外读、锁内只包住最后一次整文件替换。

两段锁之间，另一条写可以把文件改掉。后拿到锁的那次 `os.replace` 会用自己手里的整表覆盖，包括它读到的旧 `status`。

所以本 Gate 的迁移不能做成：

```text
锁外看见 OPEN
→ 锁内无条件写成 DONE
```

专用入口必须在同一把 `tasks.json.lock` 里重新读、核对 `expected_status`、核对迁移表、再替换文件。

`store_io.update_json` 虽然是锁内读改写，但 JSON 解析失败时会退回 `default` 再写回去。Task 迁移不能用它，否则损坏文件会被写成空表。

## 3. 写失败时原文件是否还在

`atomic_write_text` 的提交点只有 `os.replace`。

```text
先写同目录 tasks.json.tmp
replace 成功：旧内容被整个文件换掉
写 tmp 失败，或 replace 失败：原 tasks.json 不动
finally 删除残留的 tmp
```

`_commit` 在 tasks 已替换、links 再失败时，会再写一次旧 tasks 试图回滚。那是两文件事务的补救，不是单文件 replace 本身的能力。状态迁移只动 `tasks.json` 一次，不借这次回滚。

读路径 `read_json` 遇到解析失败只记日志并返回默认值，不写文件。损坏文件因此还在，但调用方会把它看成空任务列表。迁移如果沿用这个默认值再保存，就会把损坏文件盖成 `{"tasks": []}`。迁移路径必须识别损坏并停止写入。

## 4. TaskIdentityLink 是否独立

独立。

```text
Task 正文：data/task_store/conversations/<conversation_id>/tasks.json
链接：data/identity/task_person_links.json
```

两把锁：`tasks.json.lock` 与 `task_person_links.json.lock`。

链接存储不读取、不修改 Task 的 `status`。Task Store 的 `create_task` / `update_task` / `commit_apply` 也不读取、不修改 `task_person_links.json`。

因此 `OPEN → DONE` 可以只替换任务文件，不必碰 `person_id`，也不必重建链接。

同会话的 `links.json`（消息证据）和 `processed.json`（一条消息的 Engine 处理结果）也是另外的文件。状态迁移不应写它们。

## 5. 本 Gate 要新增的写形状

```text
FileLock(tasks.json.lock)
→ 重新读取 tasks.json
→ 解析失败或 tasks 不是对象列表：停止，不替换
→ 找到 task，否则停止
→ current == target：停止，不替换
→ current != expected：停止，不替换
→ (current, target) 不在 v1 表：停止，不替换
→ 只改 status 与 updated_at
→ tmp + os.replace
→ 释放锁
```

v1 表只有 `OPEN → DONE`。

`update_task` 继续拒绝 `status`。不修改 `commit_apply`。
