# P9-G3 Test Report

> 日期：2026-09-23
> 命令：`.\.venv\Scripts\python.exe -m unittest tests.test_p9g3_business_action`
> 结果：`Ran 32 tests in 0.575s`，`OK`

| 测试 | 结果 |
| --- | --- |
| ACTION-01 唯一 `OPEN` 标题准备为 `PREPARED`，`requires_confirmation=true`，生命周期为 0，任务仍 `OPEN` | PASS |
| ACTION-02 两个同名任务为 `ACTION_TARGET_AMBIGUOUS`，不创建 Action，生命周期为 0 | PASS |
| ACTION-03 目标不存在为 `ACTION_TARGET_NOT_FOUND`，不写 Action | PASS |
| ACTION-04 `CURRENT_TASK` / `LAST_TASK` 为 `UNSUPPORTED_REFERENCE`，仍经过 Resolver，不执行 | PASS |
| ACTION-05 已是 `DONE` 时为 `NO_ACTION_NEEDED`，不生成可确认 Preview | PASS |
| ACTION-06 同一 Actor 确认后 `OPEN → DONE`，Action 为 `EXECUTED`。确认期间持有 Action 锁，且不再解析标题 | PASS |
| ACTION-07 只准备不确认，任务保持 `OPEN` | PASS |
| ACTION-08 `wxid_b` 确认为 `ACTOR_MISMATCH`，任务保持 `OPEN`；原 Actor 仍可确认成功 | PASS |
| ACTION-09 同一消息按标题和按 `task_id` 准备，得到同一个 `action_id`，记录只有一份 | PASS |
| ACTION-10 再次确认为 `ALREADY_EXECUTED`，生命周期只调用一次 | PASS |
| ACTION-11 两个线程同时确认，生命周期只进入一次，任务为 `DONE`，终态只有一个 | PASS |
| ACTION-12 准备后被外部完成，再确认得到 `ALREADY_IN_STATE`，Action 为 `SUCCEEDED_NOOP`，任务文件不再改 | PASS |
| ACTION-13 确认前被改成 `IN_PROGRESS`，结果 `STALE_STATE` / `FAILED`，不覆盖；再次确认不再调用生命周期 | PASS |
| ACTION-14 生命周期 `WRITE_FAILED` 时 Action 为 `FAILED`，不标成 `EXECUTED`，不自动重试 | PASS |
| ACTION-15 `actions.json` 为 `{` 或 `{}` 时返回 `CORRUPT`，原字节保留，Resolver 与生命周期为 0 | PASS |
| ACTION-16 完成后 `task_person_links.json` 字节不变 | PASS |
| ACTION-17 `processed.json` 字节不变，不写 processing，不写运维审计 | PASS |
| ACTION-18 删除 Business Action Audit 后，`MY_TASKS`、`LIST_TASKS`、`TASKS_BY_ASSIGNEE` 仍能看到 `DONE` 和 `OPEN` | PASS |
| ACTION-19 微信「帮我把任务改成完成」仍是固定拒绝。Business Action、Resolver、生命周期为 0 | PASS |
| ACTION-20 「接口联调今天已经完成了」为普通聊天。Business Action 为 0，任务保持 `OPEN` | PASS |
| 缺少 Actor 或 `message_id` 时不解析、不创建 Action | PASS |
| 非 `COMPLETE_TASK` 的动作类型被拒绝，不解析、不执行 | PASS |
| `IN_PROGRESS` / `CANCELLED` 准备结果为 `ACTION_NOT_APPLICABLE` | PASS |
| 确认使用 Preview 时保存的 `task_id`；之后出现同名任务也不改目标 | PASS |
| 任务已完成但 Action 终态没写上时，下次确认收成 `SUCCEEDED_NOOP` | PASS |
| Audit 追加失败不回滚 Task，Action 仍是 `EXECUTED` | PASS |
| 确认前任务被删掉时 Action 为 `FAILED` / `TASK_NOT_FOUND` | PASS |
| `SUCCEEDED_NOOP` 再次确认不再调用生命周期 | PASS |
| 标题后来变成歧义时，已有 `PREPARED` 仍可按原 `task_id` 确认 | PASS |
| 未知 `action_id` 为 `ACTION_NOT_FOUND`，不执行 | PASS |
| 准备、成功确认、歧义、Actor 不匹配、`STALE_STATE` 都有可回答谁/何时/哪个 Task/什么动作/结果的审计 | PASS |
| 新模块不含发送、分类器、Extractor 和直接改状态的入口；冻结文件不引用 Business Action | PASS |
