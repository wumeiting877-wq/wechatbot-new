# P7-G1 API Report

> 日期：2026-09-23

---

## 路由

```text
POST /api/operations/messages/<message_id>/retry
```

没有 `/retry-topic`、`/retry-task`、`/retry-decision`、`/retry-risk`。

Body：

```json
{
  "conversation_id": "conv_...",
  "engine": "topic|task|decision|risk",
  "version": 1
}
```

客户端如果多传 `retry_type` 或正文，服务器忽略，不拿来决定执行哪一路。

---

## 状态码

```text
200  executed=true，retry 已进入既有 capability
409  NOT_RETRYABLE、NOT_FOUND_UNKNOWN、ENGINE_DISABLED，或第二层拒绝
423  STOPPED
404  消息 / 会话不存在
403  AUTH_REQUIRED，登录开关关闭
415  非 application/json
400  字段不完整或 version 非法
401  测试桩在 session 缺失时拒绝；生产 login_required 在开关打开且未登录时重定向到 /login
```

成功和失败体都带：

```text
engine
conversation_id
message_id
before_state
retry_result
after_state
executed
error_code
error
after_message
```

`after_message` 是重读后的整条消息视图，供页面刷新 Topic / Task / Decision / Risk。`after_state` 是目标 engine 的重读结果。

---

## 错误文案

```text
NOT_FOUND_UNKNOWN  处理状态未知，禁止自动重试，请人工检查。
NOT_RETRYABLE      当前状态已变化，无法重试
STOPPED            Runtime 未在接收工作，禁止人工重试
ENGINE_DISABLED    目标 Engine 未启用，禁止人工重试
AUTH_REQUIRED      当前未开启登录保护，不能执行人工重试。
```
