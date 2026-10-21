# P9-G0 Target Resolution Audit

> 结论先写：没有当前任务指针，没有上次提到的任务，没有按标题解析任务的函数，微信回复不展示 `task_id`。

```text
TARGET_RESOLUTION GAP
```

## 1. 现有指针

在 Task / Query / 会话状态里搜索 `current task`、`last referenced task`：没有这种字段。

主题查询有精确绑定，任务没有：

```text
QueryService._bind_topic
topic_id 优先
否则 title 全字相等
0 条 → NOT_FOUND
多于 1 条 → AMBIGUOUS
一个会话里有多个主题且用户没点名 → AMBIGUOUS
```

这只服务 `TOPIC_SUMMARY`。它不返回「当前任务」。

`LIST_TASKS` 把本会话任务全部列出。`MY_TASKS` / `TASKS_BY_ASSIGNEE` 按 `TaskIdentityLink` 过滤。都不是把「这个任务」收成一条。

## 2. 禁止模型猜「这个任务」

当前 Extractor 的 `TASK_UPDATE` 要求 `task_id` 属于本次 `existing_tasks`。那是旁路抽取在候选 id 里选型，不是微信命令的目标解析，而且四个 Engine 现在关闭。

未来 Command 在同一会话有多条任务时：

```text
把这个任务完成 → AMBIGUOUS
```

不允许用最新一条、标题最像、或模型猜测来选。本 Gate 不实现该规则，只锁定缺口。

## 3. Task.title 全字匹配

`Task.title` 会写入，最长 40 字。创建时没有唯一约束。两条任务可以同名。

当前没有函数做：

```text
conversation 内 title 全字相等 → 唯一任务
重复标题 → AMBIGUOUS
```

标题全字匹配可以作为以后的解析手段。重复标题必须 `AMBIGUOUS`。现在这条函数不存在，所以还不能说「已经能按标题点名」。

列表里的 `1.` `2.` 是当次回复的序号，不是稳定编号。顺序变了序号就变。不能把序号当成目标。

## 4. task_id 是否出现在微信回复里

内部 id 形如 `task_` 加 12 位哈希（`make_task_id`）。

`query_formatter._format_tasks` 与个人任务格式化只输出：

```text
序号. 标题
负责人 / 状态 / 时间说明
```

不输出 `task_id`。主题歧义列表仅在标题为空时回退到 id。任务列表没有这个回退。

```text
微信回复当前不展示 task_id
```

短编号 `T-01`：本 Gate 只评估，不实现。

评估：

```text
用户看不见 task_ 哈希，也不能靠列表序号当 id。
若以后要在聊天里点名某一条，需要稳定、可见、会话内唯一的短编号。
短编号必须单独映射到 task_id。
同名标题仍然 AMBIGUOUS，短编号不能靠模型现编。
```

## 5. 改派依赖的身份边界

「把任务改给张三」若要成为真正改派，必须走：

```text
IdentityResolver
exact alias
person_id
```

然后处理 `TaskIdentityLink`。不得退回 `assignee_text` 模糊匹配。P8-G5 / P8-G6 的身份边界保持冻结。

当前 Engine 若改 `assignee_text`：

```text
旧链接保留
日志要求人工确认
已绑定其他 person_id 时 link_task_to_person 抛 CONFLICT
没有解绑接口
```

所以改文本不等于改派。`REASSIGN_TASK` 是高风险动作，见能力矩阵。
