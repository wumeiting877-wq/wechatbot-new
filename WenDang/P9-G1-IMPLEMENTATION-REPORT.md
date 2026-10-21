# P9-G1 Implementation Report

> 日期：2026-09-23

## 1. 新增

`task_lifecycle.py`

```text
TaskLifecycleService.complete_task(conversation_id, task_id)
```

内部只调用 `TaskStore.transition_task_status`，期望 `OPEN`，目标 `DONE`。只有结果为 `TRANSITIONED` 时写日志 `Task lifecycle transitioned`。

`task_store.py` 新增：

```text
ALLOWED_TASK_TRANSITIONS_V1 = (OPEN, DONE)
transition_task_status(conversation_id, task_id, expected_status, target_status)
TaskTransitionResult
```

锁内重读 `tasks.json`。允许的配对才修改 `status` 与 `updated_at`，然后用同目录临时文件加 `os.replace` 提交。调用方已经持有 `tasks.json.lock`，替换函数不再加第二把锁。

## 2. 保持原合同的路径

`update_task` 对非空 `status` 仍抛 `INVALID_STATUS`。

`create_task` / `_normalize_new_task` 仍只接受 `OPEN`。

`commit_apply` 未改，也未被生命周期调用。

未改：

```text
task_engine.py
task_sidepath.py
prompts/extractors/TASK_EXTRACTOR.md
query_service.py
query_formatter.py
query_router.py
collaboration_query.py
task_identity_link.py
identity_store.py
risk_store.py
decision_store.py
topic_store.py
```

processing、P6-G6、P0、四个 Engine 常量都未改。

## 3. 测试

新增 `tests/test_p9g1_task_lifecycle.py`。覆盖 LIFECYCLE-01 到 LIFECYCLE-15，另加写失败保留原文件，以及服务源码不得包含模型、抽取、发送、查询、身份解析和 `commit_apply`。
