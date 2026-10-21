# P6-G3 Closure Report

> 日期：2026-09-22  
> 指令：P6-G3 Apply / Finalize Consistency  
> 不进入 Dashboard / Reminder / 自动 Retry / 人工 Retry UI / 新业务 Engine。

```text
P0 = CLOSED
P1 = CLOSED
P2 = CLOSED

P3 Topic Engine = COMPLETE
P4 Task Engine  = COMPLETE
P5 Decision Engine = COMPLETE
P5 Risk Engine = COMPLETE

P6-G0 = COMPLETE
P6-G1 = COMPLETE
P6-G2 = COMPLETE

P6-G3 = COMPLETE
```

---

## 硬门槛

已证明：

```text
apply 已成功
+ finalize / processing 写入异常
+ 显式 retry_downstream
```

之后：

```text
不会生成第二个逻辑 Task
不会生成第二个逻辑 Decision
不会生成第二个逻辑 Risk
Evidence 三元组不重复
processing 可从 FAILED 恢复到 SUCCESS（NEW_TASK / NEW_DECISION / NEW_RISK）
```

且同时保持：

```text
P6-G2 FAILED retry     PASS（CONSIST-06）
P6-G1 Topic replay     PASS（CONSIST-08，fan-out 0 新增）
P6-G0 生命周期         未改
N2                     PASS（CONSIST-09）
原 555                 全 PASS
四 Engine flags        = false
```

修复前探针曾证明不安全（Task/Risk suffix `_2`，Decision processing 卡死）。  
修复后同一注入路径安全。不是“从未验证就宣称幂等”。

---

## 实现要点

- 未改三个 Engine、未改 Topic、未改 Retry Queue。
- 未改 entity id 生成公式。
- 仅 `commit_apply`：同确定性 id + 同 `created_msg_id`/`topic` → skip。
- 未把 FAILED 无条件改成 SUCCESS。

---

## 测试

```text
P6-G3 新增 13 tests OK
unittest discover = 568 OK
（555 基线 + 13）
```

---

## 文档

```text
WenDang/P6-G3-G0-CURRENT-STATE-AUDIT.md
WenDang/P6-G3-CURRENT-STATE-AUDIT.md
WenDang/P6-G3-POST-APPLY-FAILURE-TRACE.md
WenDang/P6-G3-CONSISTENCY-DESIGN.md
WenDang/P6-G3-IMPLEMENTATION-REPORT.md
WenDang/P6-G3-TEST-REPORT.md
WenDang/P6-G3-REGRESSION-REPORT.md
WenDang/P6-G3-DEFERRED-ISSUES.md
WenDang/P6-G3-CLOSURE-REPORT.md
```

未触发 STOP，无 `P6-G3-BLOCKER-REPORT.md`。

本轮结束。等待下一步指令。
