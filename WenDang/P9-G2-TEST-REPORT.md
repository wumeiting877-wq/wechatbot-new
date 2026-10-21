# P9-G2 Test Report

> 日期：2026-09-23
> 命令：`.\.venv\Scripts\python.exe -m unittest tests.test_p9g2_task_target -v`
> 结果：`Ran 25 tests in 0.143s`，`OK`

| 测试 | 结果 |
| --- | --- |
| TARGET-01 当前会话 `task_001` 按 id 解析为 `RESOLVED` | PASS |
| TARGET-02 `task_xxx` 为 `NOT_FOUND`，文件字节不变 | PASS |
| TARGET-03 `task_001` 只存在于 `conv_B` 时，在 `conv_A` 解析不返回该任务，不枚举、不打开 `conv_B`，也不创建 `conv_A` 的文件 | PASS |
| TARGET-04 标题 `接口联调` 唯一命中 `task_001`。selector 首尾空白被 strip。改返回副本不写文件 | PASS |
| TARGET-05 存储标题 `新华接口联调`、selector `接口联调` 为 `NOT_FOUND` | PASS |
| TARGET-06 两条同名 `OPEN` 为 `AMBIGUOUS`。候选含双方 `task_id` / 标题 / 状态 / 负责人，不选取其中一条 | PASS |
| TARGET-07 同名一条 `OPEN`、一条 `DONE` 仍为 `AMBIGUOUS` | PASS |
| TARGET-08 `CURRENT_TASK` 在只有一个 Task 时为 `UNSUPPORTED_REFERENCE`，且不打开 `tasks.json` | PASS |
| TARGET-09 `接口对接`、`接口联调工作` 相对 `接口联调` 为 `NOT_FOUND` | PASS |
| TARGET-10 按 id、按标题、缺失 id、`CURRENT_TASK` 之后，`tasks.json`、`links.json`、`processed.json`、`task_person_links.json` 字节不变。读取只打开当前 `tasks.json` | PASS |
| TARGET-11 损坏 JSON 为 `CORRUPT` / `TASKS_UNREADABLE`。`tasks` 不是列表为 `CORRUPT` / `TASKS_STRUCTURE_INVALID`。原字节保留 | PASS |
| TARGET-12 Resolver 调用期间 `complete_task`、`transition_task_status`、`update_task`、`atomic_write_json` 均为 0 | PASS |
| TARGET-13 「帮我把任务改成完成」仍是 Command 固定回复。Resolver 与生命周期调用为 0。任务保持 `OPEN` | PASS |
| TARGET-14 「接口联调今天已经完成了」为 `NOT_QUERY`。Resolver 与生命周期调用为 0。任务保持 `OPEN` | PASS |
| 唯一 `DONE` 标题仍 `RESOLVED` | PASS |
| 同一 `task_id` 两行时 `AMBIGUOUS`，不返回第一行 | PASS |
| 当前文件中的行声明属于 `conv_B` 时 `NOT_FOUND`，`reason=CONVERSATION_MISMATCH` | PASS |
| 同名任务已有 `TaskIdentityLink` 时仍 `AMBIGUOUS`，链接文件字节不变 | PASS |
| 非法 selector、空标题、非法 id、非法会话为 `INVALID_SELECTOR` | PASS |
| 会话没有 `tasks.json` 时 `NOT_FOUND` 且不创建。`{"tasks": []}` 也是 `NOT_FOUND` | PASS |
| 解析出的 `task_id` 随后交给 `complete_task` 可以得到 `TRANSITIONED`。解析本身不调用生命周期 | PASS |
| 其它会话的同名任务不进入 `candidates`。当前会话只剩一条时 `RESOLVED` 为这一条 | PASS |
| 源码约束，以及路由 / 查询 / 生命周期 / Engine 未引用 Resolver | PASS |
| selector 只 strip。引号、存储标题尾部空白、大小写不同均为 `NOT_FOUND` | PASS |
| `LAST_TASK`、`RECENT_TASK`、`FUZZY_TITLE`、`SEMANTIC_TITLE`、`INDEX_FROM_CHAT` 为 `UNSUPPORTED_REFERENCE` | PASS |
