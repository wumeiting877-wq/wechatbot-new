# P7-G1 Manual Retry Design

> 日期：2026-09-23

---

## 边界

```text
Operations Read Model = 只读
Operations Action Service = 命令
唯一执行入口 = retry_topic / retry_downstream
```

Action Service 不调用 Extractor，不调用 `Engine.process_record`，不 `write_processing`，不创建 Topic / Task / Decision / Risk，不 `send_reply`。

---

## 请求身份

```text
ManualRetryRequest {
    engine
    conversation_id
    message_id
    version
}
```

不传正文、标题或 decision。`retry_type` 由服务器按 engine 决定。`topic_id` 不从客户端读取，downstream retry 用 processing 里已有的 topic。

---

## 顺序

```text
POST
→ login_required
→ ENABLE_LOGIN_PASSWORD 必须打开
→ JSON
→ 取得 engine + conversation_id + message_id + version 的进程内锁
→ 重新读取消息；不存在则 404
→ 重新分类 Operations 状态
→ 确认 FAILED_RETRYABLE、retryable、retry_type、version
→ 确认 Runtime 正在接收工作
→ 确认目标 Engine 开关为开
→ retry_topic 或 retry_downstream
→ 再次 get_message，得到 after_state
→ 释放锁
```

先读再等锁是禁止的。锁内的第一次分类才算数。

---

## HTTP

```text
200  已经调用 retry，并带回 before / after（仍失败也是 200）
409  NOT_RETRYABLE / NOT_FOUND_UNKNOWN / ENGINE_DISABLED
423  STOPPED
404  消息或会话不存在
403  登录开关关闭，拒绝匿名写
415  不是 JSON
400  身份字段不完整
```

响应至少包含：

```text
engine, conversation_id, message_id
before_state, retry_result, after_state
executed, error_code, error
```

`after_state` 来自调用后的 Store 重读，不从 retry 返回值推断。

---

## 并发

同一 `engine + conversation_id + message_id + version` 使用一把进程内 `threading.Lock`。不引入 Redis、分布式锁、新数据库或 worker。

Flask 是单进程多线程，所以这把锁只覆盖当前 WebUI 进程。

---

## 页面

只有 `FAILED_RETRYABLE` 渲染「重试」。SUCCESS、UNRELATED、SKIPPED、NOT_FOUND_UNKNOWN 不渲染按钮，也不渲染禁用按钮。

确认文案按 engine 分开：Topic 说明成功后可能按既有规则 fan-out；Task / Decision / Risk 说明只重跑当前这一路。

提交期间按钮禁用，文案为「正在重试…」。完成后请求详情 API，刷新四列状态。

---

## 审计

`data/operations/operations_action_audit.jsonl` 记录 `MANUAL_RETRY_REQUESTED` 与 `MANUAL_RETRY_RESULT`。它不是 processing 真值，Read Model 不读它。
