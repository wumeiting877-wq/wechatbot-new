# P6-G6 Current State Audit

> 日期：2026-09-23  
> 结论：TYPE C，`P6-G6 = BLOCKED`  
> 生产代码：无变更

写入时序见 `P6-G6-G0-CURRENT-STATE-AUDIT.md`。  
探针见 `P6-G6-MISSING-PROCESSING-TRACE.md`。

---

## 一句话

processing 缺失不等于“从未执行”。  
业务 apply 和 `write_processing` 不在同一个 commit。两次 processing 写入都失败时，实体可以留下，processing 可以完全没有。  
同一形状又不能还原原 decision，所以不能 reconcile，也不能把 `NOT_FOUND` 改成首次执行。

---

## 四路最终状态（CASE B，探针实测）

```text
MessageRecord     存在
Topic/Task/Decision/Risk 实体   存在（对应那一路）
CREATED_BY        存在
processing        不存在
audit             FAILED，不是原 decision
retry             NOT_FOUND，executed=false
```

CASE A（只有第一次 SUCCESS 写入失败）四路都留下 `processing=FAILED`，继续用 P6-G2 / P6-G5。

---

## 冻结项仍然成立

```text
Topic FAILED        → retry_topic
downstream FAILED   → 只重试那一路
SUCCESS replay      → 0 新 fan-out
NOT_FOUND           → 拒绝，不自动首次执行
version             → 1
Engine flags        → false
无 Recovery Queue / WebUI / 微信命令
```
