# P7-G2 Current State Audit

> 日期：2026-09-23  
> 只读确认。本文件写于实现之前的代码扫描，结论在实现后仍然成立。

---

## 冻结基线

```text
P0–P5 = CLOSED / COMPLETE
P6-G0 … P6-G5 = COMPLETE
P6-G6 = BLOCKED / TYPE C
P7-G0 = COMPLETE
P7-G1 = COMPLETE
```

进入本 Gate 时 `unittest discover` 为 648 OK。四个 Engine 模块常量与 `is_*_engine_enabled()` 都是 false。

---

## 已有只读面

`OperationsReadModel` 已经把每条消息的四路 processing 分成：

```text
SUCCESS
FAILED_RETRYABLE
NOT_FOUND_UNKNOWN
```

processing 不存在时 `retryable` 为 false，`retry_type` 为 `NONE`。列表页 `/operations` 对 `FAILED_RETRYABLE` 有单条重试，对 `NOT_FOUND_UNKNOWN` 没有按钮。

P7-G1 的写入口只有：

```text
POST /api/operations/messages/<message_id>/retry
```

登录开关关闭时该 POST 返回 403。本 Gate 不改这条规则。

---

## 缺口

列表和 `/api/operations/messages/<id>` 只带回状态、decision、error、最近一条 audit 摘要。管理员看不到：

```text
完整消息正文
Processing 全字段
按 relation 分开的 Evidence
与本消息确定相关的 Entity
最近若干条 Engine Audit
人工重试审计
```

因此无法区分「有业务写入痕迹但 processing 缺失」和「当前找不到相关业务记录」。两种情况在读模型里都是 `NOT_FOUND_UNKNOWN`，这个分类必须保持。

---

## 本 Gate 不碰的契约

```text
不改四份 schema
不把 NOT_FOUND 改成可执行
不根据 Entity / CREATED_BY / RELATED / FAILED audit 回填 decision
不新增 POST
不运行 Engine / LLM
不写 Store
```
