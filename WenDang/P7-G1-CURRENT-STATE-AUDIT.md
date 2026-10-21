# P7-G1 Current State Audit

> 日期：2026-09-23

---

## 冻结基线

```text
P0–P5 = CLOSED / COMPLETE
P6-G0 … P6-G5 = COMPLETE
P6-G6 = BLOCKED / TYPE C
P7-G0 = COMPLETE
```

P7-G0 回归基线：`unittest discover` 628 OK。

四个模块常量与 `runtime_control` 开关在本 Gate 开始时均为 false。Read Model 三态：

```text
SUCCESS
FAILED_RETRYABLE
NOT_FOUND_UNKNOWN
```

`UNRELATED` 与 `SKIPPED` 属于 SUCCESS。`NOT_FOUND_UNKNOWN` 的 `retryable` 固定为 false，`retry_type` 为 `NONE`。

---

## 已有能力

```text
operations_read_model.py   只读聚合
operations_routes.py       仅 GET
templates/operations.html  三态标签，原先没有重试按钮
topic_retry.py             retry_topic
downstream_retry.py        retry_downstream
```

P7-G0 的 `operations_routes.py` 被测试锁成不能出现 POST，也不能直接调用 `retry_topic` / `retry_downstream`。人工写接口因此放在新模块，不改这条只读路由文件的契约。

---

## 并发

`app.run(..., threaded=True)`。同一进程里两个 POST 可以同时进入。没有 Redis，也没有跨进程锁。同一条 retry identity 需要进程内互斥。

---

## 本 Gate 动过的只读面

Read Model 增加只读字段 `version`。不写 Store，不调用 retry。
