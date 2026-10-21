# P7-G1 Action Audit Report

> 日期：2026-09-23

---

## 文件

```text
data/operations/operations_action_audit.jsonl
```

追加方式与现有 JSONL 相同：目录自动创建，`FileLock` 保护追加。不写入 Topic / Task / Decision / Risk 的 engine audit，也不改那些 schema。

---

## 事件

```text
MANUAL_RETRY_REQUESTED
MANUAL_RETRY_RESULT
```

字段：

```text
ts
engine
conversation_id
message_id
version
before_state
executed
retry_result
after_state
error
error_code
session_present
```

`before_state` / `after_state` 记的是状态码，不是 processing 全文。没有 session 用户名，所以没有 `actor`。`session_present` 只表示当时 `session['logged_in']` 是否为真。

登录开关关闭而被拒绝的 POST，也会留下这两条，`executed=false`，`error_code=AUTH_REQUIRED`。

---

## 不是真值

Operations Read Model 不读取这个文件。缺 processing 不能用审计记录补成 SUCCESS 或 FAILED。P6-G6 的 NOT_FOUND 规则不变。
