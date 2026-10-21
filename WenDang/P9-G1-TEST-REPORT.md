# P9-G1 Test Report

> 日期：2026-09-23
> 命令：`.\.venv\Scripts\python.exe -m unittest tests.test_p9g1_task_lifecycle -v`
> 结果：`Ran 17 tests in 0.289s`，`OK`

| 测试 | 结果 |
| --- | --- |
| LIFECYCLE-01 OPEN → `complete_task` → DONE。processing 与消息 links 字节不变。随后只改描述，status 仍是 DONE | PASS |
| LIFECYCLE-02 `updated_at` 改变，`created_at` 仍是 `2026-09-01T00:00:00Z` | PASS |
| LIFECYCLE-03 再次完成得到 `ALREADY_IN_STATE`。文件字节与 `updated_at` 不变。无生命周期日志 | PASS |
| LIFECYCLE-04 DONE → OPEN 为 `INVALID_TRANSITION`，文件字节不变 | PASS |
| LIFECYCLE-05 OPEN → IN_PROGRESS 为 `INVALID_TRANSITION`。已是 IN_PROGRESS 时，期望 IN_PROGRESS 再到 DONE 仍非法；`complete_task` 得到 `STALE_STATE` | PASS |
| LIFECYCLE-06 OPEN → CANCELLED 为 `INVALID_TRANSITION`。DONE / IN_PROGRESS / CANCELLED 的其余非法配对同样拒绝且不写文件 | PASS |
| LIFECYCLE-07 `create_task(status=DONE/IN_PROGRESS/CANCELLED)` 为 `INVALID_STATUS`。已有 OPEN 任务的文件字节不变 | PASS |
| LIFECYCLE-08 `update_task(status=DONE)` 为 `INVALID_STATUS`，文件字节不变 | PASS |
| LIFECYCLE-09 不存在的 `task_id` 为 `TASK_NOT_FOUND`，文件字节不变。会话文件不存在时也不创建 | PASS |
| LIFECYCLE-10 损坏 JSON 与 `tasks` 不是列表时为 `CORRUPT`，原字节保留，不留下 `.tmp` | PASS |
| LIFECYCLE-11 OPEN → DONE 之后 `task_person_links.json` 字节不变，`person_id` 仍是 `person_001` | PASS |
| LIFECYCLE-12 「我有什么任务」仍返回已链接的 DONE 与 OPEN。回复含 `状态：DONE`。分类器调用 0。`LIST_TASKS` 与 `TASKS_BY_ASSIGNEE` 同样读到两条 | PASS |
| LIFECYCLE-13 「帮我把任务改成完成」回复 Command 固定句。`complete_task` 与 `transition_task_status` 调用均为 0。任务仍是 OPEN | PASS |
| LIFECYCLE-14 「接口联调今天已经完成了」路由为 `NOT_QUERY`。生命周期调用 0。任务仍是 OPEN。离线 Heuristic 仍是 `UNRELATED`。Extractor 提示词原句仍在。`task_engine.py` 无生命周期引用 | PASS |
| LIFECYCLE-15 两个 `complete_task` 并发：一个 `TRANSITIONED`，一个 `ALREADY_IN_STATE`，最终 status 为 DONE。第三次不再写文件。当前已是 `CANCELLED` 时期望 OPEN 的完成得到 `STALE_STATE`，status 不被盖成 DONE | PASS |
| 写失败 | `os.replace` 失败时结果为 `WRITE_FAILED`，原文件与 OPEN 保留，临时文件被清掉 | PASS |
| 源码约束 | `task_lifecycle.py` 不含模型、抽取、发送、查询、身份解析、`wx`、`commit_apply`、审计或 processing 写入。Engine、Query、Sidepath、协作路由源码不含 `task_lifecycle` / `complete_task` | PASS |
