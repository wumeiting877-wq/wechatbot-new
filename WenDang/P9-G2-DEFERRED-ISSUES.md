# P9-G2 Deferred Issues

> 本 Gate 只交付当前会话内的只读目标解析。下面留到后续 Gate。

## 1. 动作链

```text
自然语言 Command parser
Action Service
Confirmation
BusinessActionAudit
Idempotency
Preview
```

微信仍然不调用 Resolver。完成任务的句子仍是固定拒绝或普通聊天。

## 2. 尚未支持的指向

```text
这个任务          CURRENT_TASK
刚才那个任务      LAST_TASK
最近那个任务      RECENT_TASK
第一个任务        INDEX_FROM_CHAT
任务 1            稳定短编号
```

v1 统一返回 `UNSUPPORTED_REFERENCE`。短编号、Query Formatter 展示 `task_id`，都单独设计。

这些 selector 也不在 v1：

```text
FUZZY_TITLE
SEMANTIC_TITLE
```

标题只接受全字相等。不使用包含、相似度、拼音或模型。

「我的接口联调任务」这种带身份范围的 selector 尚未定义。同名任务现在一律 `AMBIGUOUS`，`TaskIdentityLink` 不参与选择。

## 3. 状态表

```text
OPEN → IN_PROGRESS
OPEN → CANCELLED
```

以及 P9-G1 已经拒绝的其余流转，仍然非法。

```text
Risk close
Decision transition
Topic resolve
Reassign
Delete
```

本 Gate 不改这些对象的状态。

## 4. 读取边界

Resolver 不持有 `tasks.json.lock`。它依赖迁移路径的 `os.replace` 提供完整文件。锁内读取留到以后如果出现解析与迁移交错的真实问题，再收紧。

当前文件里 `conversation_id` 为空的行，视为属于该文件所在会话。生产创建路径总会写上 `conversation_id`。
