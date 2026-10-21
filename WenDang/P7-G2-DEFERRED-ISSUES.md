# P7-G2 Deferred Issues

> 日期：2026-09-23  
> 这些保持不做。本 Gate 没有用猜测把它们补上。

---

## P6-G6 仍是 TYPE C

```text
P6-G6 = BLOCKED / TYPE C
```

processing 缺失时，页面展示已有痕迹，状态保持 `NOT_FOUND_UNKNOWN`。没有恢复，没有自动重跑，没有把 CREATED_BY、RELATED 或 FAILED audit 写成原 decision。

---

## 数据仍缺的字段

```text
processing 没有 error_code
Topic 实体没有 created_msg_id
Task 没有名为 assignee 的字段，实际是 assignee_text
Decision 不允许 UPDATED_BY
status.json 不一定有 listen_count
```

缺了就显示「未提供」或「无记录」。不为诊断改 schema。

诊断与读模型一样只读 processing version 1。更早或更新的 version 不会单独开一栏，否则会和三态不一致。

Engine audit 没有按 message 建索引。服务读完文件后只返回该消息最近 20 条。这是读取上限，不是新的存储结构。

---

## 安全

没有 RBAC。详情 GET 沿用 `login_required`。人工重试在 `ENABLE_LOGIN_PASSWORD=false` 时仍是 403。

当前没有 CSRF token。本 Gate 没有新增 POST，因此没有做 CSRF 框架。

---

## 继续不做

```text
自动 retry / cron / backoff / 批量 retry
Reminder / 催办 / 日报 / 周报
新的 AI Engine
Dashboard 大改版
详情页上的第二套重试按钮
```

列表页的单条人工重试保持 P7-G1。
