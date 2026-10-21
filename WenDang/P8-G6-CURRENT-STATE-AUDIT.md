# P8-G6 Current State Audit

> 日期：2026-09-23  
> 进入本 Gate 时的基线。

---

## 1. 已关闭范围

```text
P0–P5 = CLOSED / COMPLETE
P6-G0 … P6-G5 = COMPLETE
P6-G6 = BLOCKED / TYPE C
P7-G0 … P7-G2 = COMPLETE
P8-G0 … P8-G3 = COMPLETE
P8-G4 = BLOCKED / TYPE C
P8-G5 = COMPLETE / MODEL-A
```

进入时 Non-Live = 735 OK。四个 Engine 开关均为 `false`。

## 2. 已有身份能力

```text
identity_store.py
identity_resolver.py
data/identity/people.json
data/identity/wechat_bindings.json
data/identity/assignee_aliases.json
```

已经能确定性完成 `wxid → person_id` 和精确别名 → `person_id`。解析失败不新建人员。损坏文件不重置。

P8-G5 明确没有 Task 绑定。个人查询当时仍是固定拒绝，分类器不能输出 `MY_TASKS`。

## 3. 查询链

```text
message listener
→ collaboration_query.handle_collaboration_route
→ query_router.route_hybrid
→ AgentReplyPlan
→ agent_reply_delivery（pending / FIFO / max 3 / TTL 60s / Stop clear）
→ QueryService.execute
→ query_formatter
```

身份句在 `route_hybrid` 里先于分类器返回 `UNSUPPORTED_IDENTITY`。分类器枚举仍是：

```text
LIST_TOPICS
LIST_TASKS
LIST_DECISIONS
LIST_RISKS
OPEN_RISKS
TOPIC_SUMMARY
NOT_QUERY
```

## 4. Task 侧

Task 文件没有 `person_id`。`FORBIDDEN_TASK_KEYS` 含 `assignee_id`、`assignee_wxid`。`assignee_text` 仍是自由文本。

本 Gate 开始前不存在 `task_person_links.json`。
