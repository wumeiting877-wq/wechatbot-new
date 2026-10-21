# P6-G2 Closure Report

> 日期：2026-09-22  
> 指令：P6-G2 Downstream Failure Recovery  
> 不进入 Dashboard / Reminder / 新业务 Engine。

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
```

---

## 硬门槛

已证明：

```text
Topic SUCCESS
+ 某一个 downstream FAILED
→ 只重试失败的那个 Engine
```

且：

```text
Topic Extractor delta    = 0
其它两个 downstream      = 0
Chat delta               = 0

retry SUCCESS 后再 retry = REJECTED / Extractor 0
retry FAILED             = 不递归，一次一发
Topic replay             = 仍 0 新 fan-out（1/1/1）
N2                       = 同正文不同 pid → 两条 MessageRecord
P6-G0 生命周期           = 未改 bot_lifecycle / webui
旧 540                   = 全 PASS
四 Engine 开关           = 仍 false
```

---

## 实现要点

- 未改三个下游 Engine / Store schema / Topic Engine。
- Store 天然支持 FAILED 覆盖；Engine 天然允许 FAILED 后再 `process_record`。
- 新增薄封装 `downstream_retry.py`：eligibility + 一次 `process_record` + audit。
- 无 Retry Queue / worker / 自动重试 / WebUI。

---

## 测试

```text
P6-G2 新增 15 tests OK
unittest discover = 555 OK
（540 基线 + 15）
```

---

## 文档

```text
WenDang/P6-G2-G0-CURRENT-STATE-AUDIT.md
WenDang/P6-G2-CURRENT-STATE-AUDIT.md
WenDang/P6-G2-FAILED-RETRY-TRACE.md
WenDang/P6-G2-RETRY-DESIGN.md
WenDang/P6-G2-IMPLEMENTATION-REPORT.md
WenDang/P6-G2-TEST-REPORT.md
WenDang/P6-G2-REGRESSION-REPORT.md
WenDang/P6-G2-DEFERRED-ISSUES.md
WenDang/P6-G2-CLOSURE-REPORT.md
```

未触发 STOP，无 `P6-G2-BLOCKER-REPORT.md`。

---

## 本轮结束

等待下一步指令。不进入 Dashboard、Reminder 或新的业务 Engine。
