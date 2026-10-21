# P8-G5 Deferred Issues

> 日期：2026-09-23

身份目录已经独立存在。下面这些仍然不做。

---

## 1. 下一 Gate 才考虑

```text
P8-G6
MY_TASKS
TASKS_BY_ASSIGNEE
```

即使 `person_001` 和 wxid 已经绑好，当前查询仍固定拒绝。

## 2. 任务链接

方案 B `TaskIdentityLink` 只完成比较，没有写 `task_person_links.json`。

还没做：

```text
新任务何时写链接
EXACT_EXPLICIT_ALIAS 的写入时机
链接失败时的固定回复
alias 变更后旧链接是否保留
历史任务迁移预览
人工确认后的写入
```

禁止在上线时扫描旧 `assignee_text` 并直接写链接。

## 3. 目录管理

```text
人员管理页面
配置后台里的人员编辑
企业通讯录 / HR / 企业微信同步
alias 修改和作废
把已绑定 wxid 转到另一个 person
DISABLED 人员在未来查询里是否拒绝
```

`DISABLED` 现在只保留行。Resolver 仍返回这个人。查询没有使用这个结果。

## 4. 继续冻结

```text
RECENT_DECISIONS
CROSS_CONVERSATION_QUERY
写 Command
按人扫描全部会话
组织权限
Reminder
自动 Retry
P6-G6 processing
四个 Engine
42 条 Real Extractor
```
