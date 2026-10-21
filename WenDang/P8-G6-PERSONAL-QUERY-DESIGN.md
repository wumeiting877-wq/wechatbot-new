# P8-G6 Personal Query Design

> 日期：2026-09-23

---

## 1. 内部类型

```text
MY_TASKS
TASKS_BY_ASSIGNEE
```

它们由身份规则进入，不进入分类器枚举。分类器若输出 `MY_TASKS`，仍是 `CLASSIFIER_INVALID`。

`classify_agent_message` 对「我有什么任务」「张三负责什么」仍返回 `NOT_QUERY`。`route_hybrid` 仍先标成 `UNSUPPORTED_IDENTITY`，分类器调用次数为 0。真正的查询类型在协作层按解析结果写入 `AgentReplyPlan`。

## 2. 认人

`MY_TASKS`：

```text
sender_wxid
→ resolve_wxid
→ person_id
```

wxid 为空，或解析为 `NOT_FOUND`：

```text
当前无法确定你的人员身份，因此暂时不能查询“我的任务”。
```

不使用 `sender_name`。

`AMBIGUOUS`：

```text
当前人员身份存在冲突，无法安全查询个人任务。
```

`TASKS_BY_ASSIGNEE` 只拿路由抽出的精确姓名，再 `resolve_exact_alias`。`canonical_name` 不是别名。没有别名则：

```text
当前无法确定人员身份，因此暂时不能查询该人员的任务。
```

身份文件损坏：

```text
当前人员身份暂时无法确认，因此不能查询个人任务。
```

不回退昵称，不返回全部任务。

## 3. 查任务

`person_id` 在收到查询时写入 `AgentReplyPlan`。补发不再解析 wxid 或别名，也不再调用分类器。发送前重新读人员和链接：

```text
conversation_id + person_id
→ TaskIdentityLink
→ task_id
→ 当前会话的 Task Store
```

人员若已 `DISABLED`：

```text
当前人员身份已停用，暂不支持按该身份查询任务。
```

历史链接保留。

没有链接的任务，即使 `assignee_text` 相同，也不进入结果。QueryService 不按 `assignee_text` 过滤。

结果只属于当前 `Conversation.id`。

## 4. 文案

有结果时必须出现「本会话」和「已确认负责人绑定」。姓名只用 `Person.canonical_name` 显示。

空结果：

```text
当前未查询到你在本会话已确认负责人绑定的任务。
```

不说「你没有任务」。

## 5. 交付

复用 P8-G3：`AgentReplyPlan`、pending、FIFO、最多 3 条、TTL 60 秒、Stop / Emergency 清空。不新建个人任务队列。
