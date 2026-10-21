# P7-G0 Deferred Issues

> 日期：2026-09-23

---

## 留给 P7-G1

人工 Retry Action。必须继承：

```text
NOT_FOUND_UNKNOWN → retry_type = NONE
禁止自动把缺失 processing 补成 SUCCESS
禁止 NOT_FOUND 自动调用 Engine
```

FAILED 才允许讨论显式 retry。本 Gate 只显示 `retryable`。

---

## 继续不做

```text
自动 retry / cron / retry queue / backoff
Reminder / 催办 / 日报 / 周报
新的 AI Engine
Dashboard 大改版
RBAC
```

---

## 数据缺口（不补字段）

```text
processing 没有 error_code
status.json 没有 listen_count
```

读模型把 `error_code` 留空，不解析 `error` 字符串。`listen_count` 缺席时为 null。

已存在但无法识别的 decision 归入 `NOT_FOUND_UNKNOWN`，`retryable=false`，notice 写明 outcome unrecognized。不新增第四个状态名。

P6-G6 TYPE C 仍然 BLOCKED。本 Gate 把它变成产品规则，不实现 recovery。
