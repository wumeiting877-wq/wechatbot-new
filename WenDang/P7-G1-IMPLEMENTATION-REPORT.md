# P7-G1 Implementation Report

> 日期：2026-09-23
> 状态：COMPLETE

---

## 新增

```text
operations_action_service.py   锁、重读、资格、调用 retry、再读 after
operations_action_routes.py    POST /api/operations/messages/<message_id>/retry
operations_action_wiring.py    装配已有 TopicRetryService / DownstreamRetryService
operations_action_audit.py     operations_action_audit.jsonl
tests/test_p7g1_manual_retry.py
```

`config_editor.py` 在只读 Operations 路由之后注册写路由。`operations_routes.py` 仍只有 GET。

---

## 小改

`operations_read_model.py` 的 engine 视图增加只读 `version`。页面用它提交，服务器再与 Store 比对。

`templates/operations.html` 只在失败可重试行放「重试」，并在完成后拉详情 API。

---

## 没有改

```text
topic_retry.py
downstream_retry.py
Topic / Task / Decision / Risk Engine 与 Store schema
四个 ENGINE 模块常量
P6-G6 NOT_FOUND 行为
```

Wiring 用 `is_*_engine_enabled()` 的返回值装配 downstream engine，源码里没有 `enabled=True`。Topic 旁路不传 enabled，沿用开关函数。既有 `TopicSidepath` 在自己的开关通过之后才会构造 Engine，这一层没有被改。

---

## 登录

写接口在 `ENABLE_LOGIN_PASSWORD=false` 时 403，不执行。这是为了避免匿名写，不是新角色系统。
