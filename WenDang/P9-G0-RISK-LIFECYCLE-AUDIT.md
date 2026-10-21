# P9-G0 Risk Lifecycle Audit

> 扫描：`risk_store.py`、`risk_engine.py`、`risk_sidepath.py`、`risk_extractor_client.py`、`prompts/extractors/RISK_EXTRACTOR.md`
> 结论先写：生产写入只有 OPEN。关闭风险没有正式 Store 操作。

## 1. 状态常量

`risk_store.py`：

```text
RISK_STATUS_OPEN = OPEN
RISK_STATUS_MITIGATED = MITIGATED
RISK_STATUS_RESOLVED = RESOLVED
RISK_STATUS_CLOSED = CLOSED
ALLOWED_WRITE_STATUSES = (OPEN,)
FORBIDDEN_STATUSES = (MITIGATED, RESOLVED, CLOSED)
```

文件头写明：v1 只写 OPEN，不写 MITIGATED / RESOLVED / CLOSED，不写 severity。

## 2. CREATE

`create_risk` → `_normalize_new_risk`：

```text
status 属于 FORBIDDEN_STATUSES，或不在 ALLOWED_WRITE_STATUSES
→ INVALID_STATUS「v1 只允许写入 OPEN」
落盘 status 强制为 OPEN
必须同时有 condition_text 与 impact_text，且有 title
```

`commit_apply` 对新风险再次强制 `status = OPEN`，并丢掉 severity、owner、due 等禁止键。

Risk Engine 的 `NEW_RISK` 写死 `status = OPEN`。description 在这条路径上是空字符串。可选 `task_id` 只有指向同主题已有任务时才被 Store 接受。

Extractor 允许 `NEW_RISK`、`RISK_UPDATE`、`UNRELATED`。`RISK_RESOLVED`、`MITIGATED`、`RESOLVED`、`CLOSED`、`RISK_CLOSED` 会在解析阶段被拒绝。提示词禁止自动把已有 Risk 标成这三种结束态。

```text
CREATE = OPEN ONLY
```

## 3. UPDATE

`update_risk` 允许改：

```text
title
description
condition_text
impact_text
confidence
task_id    仅当当前 task_id 为空，且新值能通过同主题校验
```

拒绝：

```text
status → INVALID_STATUS「RISK_UPDATE 不得改 status」
conversation_id / topic_id → IMMUTABLE_FK
severity、owner、due、mitigation_text 等 → FORBIDDEN_FIELD
```

Engine 的 `RISK_UPDATE` 会传 title、condition_text、impact_text、confidence，以及「当前没有 task_id 时」的 task_id。不传 status，不传 description。

`commit_apply` 的更新若 fields 里含 status，直接 `INVALID_STATUS`，然后仍把该行 status 写回 OPEN。

## 4. 状态流转矩阵

| From | To | 当前 Store 支持 | 当前 Engine 支持 |
| --- | --- | --- | --- |
| OPEN | MITIGATED | 否，`INVALID_STATUS` | 否，Extractor 拒绝该 decision，Engine 不传 status |
| OPEN | RESOLVED | 否，`INVALID_STATUS` | 否 |
| OPEN | CLOSED | 否，`INVALID_STATUS` | 否 |

```text
CURRENT PRODUCTION WRITE = OPEN ONLY
```

没有 `RESOLUTION_EVIDENCE` / `MITIGATION_EVIDENCE`。这两种 relation 被禁止。

## 5. 「把这个风险关掉」

```text
不存在正式 API / Store 操作
```

`update_risk(..., status="CLOSED")` 与 `update_risk(..., status="RESOLVED")` 都会 `INVALID_STATUS`，原记录保持 OPEN。

没有按 risk_id 删除的方法。`delete_conversation_risk_data` 只删整个会话目录，不是关闭一条风险。手改 JSON 不算支持。

微信里「关闭这个风险」「把这个风险关掉」命中 Command，固定回复，不读不写 Risk Store。

```text
NOT_SUPPORTED
卡在 Extractor、Engine、Store、Status contract
Intent 层对固定句型另外直接拒绝
```
