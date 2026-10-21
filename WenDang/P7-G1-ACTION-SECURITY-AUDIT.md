# P7-G1 Action Security Audit

> 日期：2026-09-23

---

## 身份边界

P7-G1 不新增 RBAC。人工重试沿用现有 WebUI 登录，并比普通写接口多一条硬条件：

```text
ENABLE_LOGIN_PASSWORD 必须为 true
```

原因：开关关闭时 `login_required` 不验 session。若此时仍执行 POST，人工重试就是匿名写接口。本 Gate 在该情况下返回 403，`error_code=AUTH_REQUIRED`，`executed=false`，不调用 retry。

开关打开后，与 `/start_bot` 相同：没有 `session['logged_in']` 不会进入重试。Session 没有用户名，审计只记 `session_present`，不编造 actor。

生产进程绑定 `127.0.0.1`。这是网络边界，不是身份边界，不能代替上面的登录开关。

---

## CSRF

当前项目没有 CSRF token。本 Gate 不另做一套。

人工重试 POST 要求 `Content-Type: application/json`。非 JSON 返回 415，不执行。Session cookie 保持 HttpOnly + SameSite=Lax。

---

## 不信任客户端

服务器不接受客户端传来的 `retry_type`、正文、标题或 `retryable`。

拿到锁之后重新 `get_processing`，用 Operations Read Model 重新分类。只有仍是 `FAILED_RETRYABLE` 且 `retryable=true`，并且 `version` 与 processing 一致，才继续。

```text
engine=topic              → retry_topic
engine=task|decision|risk → retry_downstream
```

`NOT_FOUND_UNKNOWN`、`SUCCESS`、`UNRELATED`、`SKIPPED` 都不调用 retry。

---

## Runtime 与 Engine 开关

Read Model 判定当前不在接收工作（含 STOPPING / STOPPED / ERROR / STARTING，以及 emergency / stop 文件）时，返回 `STOPPED`，HTTP 423，retry 0 次。

目标 Engine 的 `is_*_engine_enabled()` 为 false 时，返回 `ENGINE_DISABLED`，不把 `enabled=True` 写进人工层。

第二层仍是 `retry_topic` / `retry_downstream` 自己的校验。`runtime=None` 不会传给它们，避免它们把空 Runtime 当成可执行。

---

## 结论

匿名写没有打开。登录开关关闭时重试被拒绝。没有新认证系统。
