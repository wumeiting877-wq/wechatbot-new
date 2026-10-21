# P7-G0 API Report

> 日期：2026-09-23

---

## 路由

全部 GET，挂在现有 Flask WebUI 上，装饰器复用 `login_required`。

```text
GET /api/operations/status
GET /api/operations/messages
GET /api/operations/messages/<message_id>
GET /api/operations/issues
GET /operations
```

没有 `POST /retry`。对只读路由发 POST 返回 405。

查询：

```text
/api/operations/messages?limit=100&attention=1
/api/operations/messages/<message_id>?conversation_id=
/api/operations/issues?limit=50
/operations?attention=0
```

未知 message_id 返回 404。

---

## 权限

```text
P7-G0 does not introduce auth
```

沿用 WebUI 现有 `login_required`。它只在 `ENABLE_LOGIN_PASSWORD` 打开时检查 session。没有 RBAC，本 Gate 不假装已经有角色权限。

---

## 详情里的 UNKNOWN

JSON 的 `notice` 至少包含：

```text
processing record not found
automatic retry disabled
manual investigation required
```

页面同一位置展示这些句子，避免被理解成可以点一下重跑。
