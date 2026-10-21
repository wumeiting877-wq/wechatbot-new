# P7-G1 Gate 0 — Action / Security Audit

> 日期：2026-09-23
> 范围：只读。本文件不改 Engine、Store 或开关。

---

## 1. 当前 WebUI 写操作如何鉴权？

写路由统一挂 `@login_required`（`config_editor.py`）。

`ENABLE_LOGIN_PASSWORD=true` 时，没有 `session['logged_in']` 会重定向到 `/login`。

`ENABLE_LOGIN_PASSWORD=false`（当前默认）时，装饰器不检查 session，视图直接执行。

没有 ADMIN / OPERATOR / VIEWER。Session 里只有登录布尔值，没有用户名。

Flask 启动绑定 `127.0.0.1`，`threaded=True`。

---

## 2. login_required 在 ENABLE_LOGIN_PASSWORD=false 时是什么行为？

不验证身份。函数原样放行。`/start_bot`、`/stop_bot`、`/submit_config` 等既有写接口在这个开关关闭时同样放行，只靠本机回环地址限制网络入口。

---

## 3. 当前是否存在 CSRF 机制？

没有 CSRF token，也没有统一的 CSRF 中间件。

已有相关设置：

```text
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = Lax
SESSION_COOKIE_SECURE = False
```

部分 JSON 写接口（例如 `/api/log`）检查 `Content-Type`。多数管理 POST 是同源 `fetch`，没有单独的 Origin 白名单。

---

## 4. 当前项目是否已有统一 JSON POST 返回格式？

没有。`_json_error` 使用 `ok / error / message / detail`，只覆盖一部分配置接口。Bot 控制接口和 Operations GET 各自 `jsonify`。本 Gate 不新造一套 REST 标准，Operations 写接口沿用「JSON 对象 + HTTP 状态码」，字段按本 Gate 要求的 before / after 结构返回。

---

## 5. retry_topic / retry_downstream 需要哪些真实参数？

```text
retry_topic(conversation_id, message_id, *, version=0, runtime=None, service=TopicRetryService)

retry_downstream(engine, conversation_id, message_id, topic_id="", *, version=0, runtime=None, service=DownstreamRetryService)
```

`service` 必填。`runtime is None` 时，这两个 capability 自己把「未注入 Runtime」当成可以执行。人工层不能传 `None` 去绕过停止状态。

Topic 只认 processing `decision == FAILED`。Downstream 只认 `decision_summary` 拆开后全是 `FAILED`。`UNRELATED` / `SKIPPED` 在 retry capability 里已经是不可重试。缺 processing 返回 `NOT_FOUND`，`executed=false`。

---

## 6. Operations Read Model 如何按 message_id + conversation_id 重新读取最新状态？

`OperationsReadModel.get_message(message_id, conversation_id)` 遍历会话消息，命中后调用 `engine_view`。

`engine_view` 每次调用 `store.get_processing(conversation_id, message_id)`，默认 version 为 1。分类只看这条 processing：

```text
不存在或 decision 无法识别 → NOT_FOUND_UNKNOWN，retryable=false
FAILED → FAILED_RETRYABLE，retryable=true
其余成功决策（含 UNRELATED / SKIPPED）→ SUCCESS，retryable=false
```

不读人工动作审计，不用 audit 补 processing。

P7-G1 只在这个只读视图上增加 `version`（来自 `topic_processing_version` 等已有字段）。不在 Read Model 里执行动作。
