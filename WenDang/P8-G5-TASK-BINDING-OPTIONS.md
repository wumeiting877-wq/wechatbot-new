# P8-G5 Task Binding Options

> 日期：2026-09-23  
> 结论：优先独立 TaskIdentityLink。本 Gate 不实现。

---

## 1. 为什么现在不绑任务

人员、微信账号、精确别名可以单独证明。任务绑定还要回答：

```text
历史 Task 如何迁移
新 Task 何时写链接
解析失败时链接写不写
alias 后来改了，旧链接怎么办
```

这些还没有运行证据。把 `person_id` 写进 Task，会把身份问题带进 P4 Task Engine。

## 2. 方案 A — 改 Task schema

```text
Task
    assignee_text
    assignee_person_id
```

稳定，读取时少一次查找。

代价：

```text
Task schema migration
Task Engine
Extractor / Store 的禁止键
历史数据迁移
P4 回归面扩大
```

`TaskStore.FORBIDDEN_TASK_KEYS` 现在明确去掉 `assignee_id` 和 `assignee_wxid`。方案 A 要改这条冻结边界。

## 3. 方案 B — 独立 TaskIdentityLink

```text
TaskIdentityLink {
    task_id
    conversation_id
    person_id
    source
    created_at
}
```

候选文件是 `data/identity/task_person_links.json`。它不修改 Task JSON 的字段。

允许的 `source`：

```text
MANUAL
TRUSTED_DIRECTORY
EXACT_EXPLICIT_ALIAS
```

禁止的来源：

```text
FUZZY
LLM
NICKNAME_GUESS
CONTEXT_GUESS
```

只有管理员显式登记的精确 alias，才可能在未来生成 `EXACT_EXPLICIT_ALIAS` 链接。`assignee_text` 先 strip，再全等查找。`李明负责` 在 alias 仅为 `李明` 时不能生成链接。

## 4. 比较

|  | 方案 A | 方案 B |
| --- | --- | --- |
| Task 文件 | 要加字段并迁移 | 保持现在的 schema |
| 与 Task Engine 的关系 | 写入路径要一起改 | 可以后接，本 Gate 不接 |
| 身份模块出错时 | 影响任务落盘 | 任务文件仍只含 assignee_text |
| 历史数据 | 必须改每一条 Task | 可以只追加链接，原 Task 不动 |
| 查询 | 仍要等下一 Gate | 仍要等下一 Gate |

方案 B 更符合「先证明身份目录，再碰任务」。

## 5. 本 Gate 的决定

采用方案 B 作为后续设计，本 Gate 不写链接文件，也不做迁移。

历史任务禁止这种上线动作：

```text
扫描全部 assignee_text → 猜测 person → 直接写链接
```

以后若要迁移，最多先出预览，例如：

```text
可确定绑定：18
无法绑定：7
歧义：2
```

人工确认之后才能写。

`MY_TASKS` 放到 P8-G6。那时再决定链接由谁在什么时机写入。
