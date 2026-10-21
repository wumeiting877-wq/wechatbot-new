# P9-G2 Implementation Report

> 日期：2026-09-23

## 1. 新增

`task_target_resolver.py`

```text
TaskTargetSelector
TargetResolutionResult
TaskTargetResolver
```

读取只发生在当前会话的 `tasks.json`。`CURRENT_TASK` 等不支持的 selector 在打开文件之前返回。

损坏检测与 `transition_task_status` 使用同一结构规则：JSON 解析失败，或 `tasks` 不是对象列表，返回 `CORRUPT`。文件不存在返回 `NOT_FOUND`。两条路径都不写回。

## 2. 未改的路径

未改：

```text
task_store.py
task_lifecycle.py
task_engine.py
task_sidepath.py
task_identity_link.py
identity_store.py
identity_resolver.py
query_router.py
query_formatter.py
query_service.py
collaboration_query.py
prompts/extractors/TASK_EXTRACTOR.md
```

`query_router._is_command` 的模板未扩大。Formatter 未增加 `task_id`。四个 Engine 常量未改。

`task_target_resolver.py` 源码不含这些标记：

```text
LLM
Extractor
send_reply
TaskLifecycleService
transition_task_status
update_task
atomic_write
IdentityResolver
fuzzy
difflib
pinyin
```

`FUZZY_TITLE` 只作为被拒绝的 selector 类型出现。

上面列出的路由、查询、生命周期、Engine、Sidepath 源码不含 `task_target_resolver` 或 `resolve_task_target`。

## 3. 测试

新增 `tests/test_p9g2_task_target.py`。覆盖 TARGET-01 到 TARGET-14，以及只读边界：`DONE` 仍可解析、空文件与缺文件、引号与大小写、跨会话同名不进候选、身份链接不消歧、重复 `task_id` 不取第一行、解析出的 id 可以交给后续 `complete_task`。
