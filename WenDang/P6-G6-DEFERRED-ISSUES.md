# P6-G6 Deferred Issues

> 日期：2026-09-23  
> 本 Gate 不修这些。TYPE C 禁止用猜测把它们补上。

---

## D1 — Topic 缺失后再执行会分配 `_2`

CASE B 之后直接 `process_record`，`create_topic` 因同一 `created_msg_id + created_at` 碰撞而追加 `_2`。  
同一消息留下两条 `CREATED_BY`。  
`retry_topic` 当前返回 `NOT_FOUND`，没有触发这条路径。  
要修它必须先有不靠猜测的身份，或者改变 Topic 创建幂等。后者超出本 Gate，而且本 Gate禁止改确定性 id 规则来“顺便修好”。

---

## D2 — Topic CASE A 的 FAILED processing 不带 topic_id

isolate 写 FAILED 时没有把已经创建的 `topic_id` 放进去。  
这是既有 `_isolate` 签名，不是本 Gate 引入的。  
FAILED 仍由 P6-G5 `retry_topic` 处理。不在这里改 retry 契约。

---

## D3 — 业务文件与 processing 不是一个 commit

Topic 的 topics / links / processed / audit 各自写入。  
下游 `commit_apply` 只覆盖实体文件和 links，processing 在其后。  
把它们收成一个事务需要 WAL / Saga 或 schema 变更。停止条件明确禁止为了本 Gate 引入这些。

---

## D4 — Audit 在成功 apply 之后记 FAILED

CASE B 的 audit decision 是 `FAILED`，与已经写入的业务结果不一致。  
不能拿它做恢复依据。本 Gate 不改 audit 顺序。

---

## 未进入

```text
Dashboard
Reminder
WebUI Retry
自动 Retry
新的业务 Engine
```
