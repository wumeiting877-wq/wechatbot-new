# P8-G6 Implementation Report

> 日期：2026-09-23

---

## 1. 新增

```text
task_identity_link.py
tests/test_p8g6_task_identity_link.py
data/identity/task_person_links.json   （运行时按需生成，不随仓库预置历史迁移）
```

`TaskIdentityLinkStore` 提供 `link_task_to_person`、`preview_task_identity_links`、按人员和会话读取。没有解绑和改派。

## 2. Task Engine

`task_engine.py` 在 `_finalize` 返回之后调用 `_attach_identity_links`。

只把本次提交里新出现的 task_id 交给 `attach_exact_links_for_created_tasks`。`assignee_text` 变化只走 `note_assignee_text_drift`。

Task schema、Extractor schema、processing schema 没有改。`FORBIDDEN_TASK_KEYS` 仍禁止 `assignee_id` / `assignee_wxid`。

## 3. 查询

```text
query_router.py          抽出精确姓名，仍不调用分类器
collaboration_query.py   入站时解析 person_id，写入 AgentReplyPlan
query_service.py         MY_TASKS / TASKS_BY_ASSIGNEE 只走链接
query_formatter.py       个人结果文案
agent_reply_delivery.py  pending 快照带上 person_id
```

身份无法确定时仍是固定回复，不调用 `build_query_service`。身份已确定时才读链接和任务。

P8-G4 的固定拒绝文案改成了本 Gate 规定的「无法确定人员身份」。比较常量的旧测试仍对准同一常量。`tests/test_p8g5_identity_model.py` 里原先写死的「不支持按个人身份查询」改成了新句子，并去掉了「解析函数一被调用就失败」的补丁。未绑定 wxid 仍然不查任务、不调用 QueryService、不建身份目录。

## 4. 没有做

```text
Task.person_id
历史任务批量绑定
unlink / rebind
人员管理 UI
跨会话查询
Command
组织权限
Reminder
自动 Retry
新业务 Engine
```
