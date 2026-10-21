# P7-G2 API Report

> 日期：2026-09-23

---

## 新增

```text
GET /api/operations/messages/<message_id>/diagnostics
GET /operations/messages/<message_id>
```

Query：`conversation_id`。不传时按消息 id 在已有会话里查找，与读模型的 `get_message` 相同。

找不到消息时 JSON 返回 404：

```json
{"error": "message not found", "message_id": "<id>"}
```

页面同样 404，并显示「无记录」。

POST 到诊断 URL 由 Flask 返回 405。没有新增 POST。

---

## 访问边界

两个新路由都使用现有 `login_required`。本 Gate 不新增认证。

P7-G1 仍是：

```text
POST /api/operations/messages/<message_id>/retry
ENABLE_LOGIN_PASSWORD=false → 403
```

诊断 GET 不放宽这条写保护。`operations_action_routes.py` 未改。

---

## 响应里和三态有关的部分

`operations_state.topic|task|decision|risk` 与读模型单条接口同一套字段。诊断块里的 `state` / `decision` / `retryable` / `retry_type` 与之相等。

`NOT_FOUND_UNKNOWN` 时 `retryable` 为 false。响应里没有 Repair、Reprocess，也没有第二个重试 URL。

---

## CSRF

本 Gate 新增的都是 GET。当前应用仍然没有 CSRF token。这延续 P7-G1 的记录，不在本 Gate 做 CSRF 框架。
