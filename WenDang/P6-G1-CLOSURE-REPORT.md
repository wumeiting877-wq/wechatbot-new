# P6-G1 Closure Report

> 日期：2026-09-22  
> 指令：P6-G1 Replay / Fan-out Idempotency  
> 不进入新的业务 Engine。

```text
P0 = CLOSED
P1 = CLOSED
P2 = CLOSED
P3 Topic Engine = COMPLETE
P4 Task Engine  = COMPLETE
P5-G0 = COMPLETE
P5-G1 = COMPLETE
P5-G2 = COMPLETE
P5-G3 = COMPLETE
P5-G4 = COMPLETE
P6-G0 = COMPLETE
P6-G0 BLOCKER = CLOSED

P6-G1 = COMPLETE
```

---

## 硬门槛

同一 `MessageRecord`：

```text
Topic Extractor successful call <= 1

首次 Topic SUCCESS:
  Task fan-out     = 1
  Decision fan-out = 1
  Risk fan-out     = 1

Topic replay (replayed=true):
  Task fan-out     = 0
  Decision fan-out = 0
  Risk fan-out     = 0
```

同时：

```text
EXISTING_TOPIC 非 replay 行为保持     PASS（REPLAY-04 + 既有 ts/ds/rs）
TOPIC_UPDATE 非 replay 行为保持       PASS（REPLAY-03 + 既有 ts/ds/rs）
N2 行为保持                           PASS（REPLAY-07 + P6-G0 N2）
P0 DUPLICATE 不入 Topic               PASS（未改 Dedupe）
P6-G0 生命周期保持                    PASS（未改 bot_lifecycle / webui_bot_process）
P0–P5 行为保持                        PASS（原 530）
原 530 tests 全 PASS                  540 = 530 + 10
四 Engine 开关仍 false                PASS
```

---

## 修复落点

仅 `topic_sidepath.py`：`replayed=true` → `TOPIC_REPLAY` audit，`fanout_skipped=true`，不调用三个 `_maybe_enqueue_*`。

Gate 3 确认：replay = Topic 幂等跳过，**不是**下游补偿。未 STOP。

---

## 回归 / 开关

```text
unittest discover = 540 OK
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

无真机、无 Real LLM。无 `force_reprocess`。

---

## 文档

```text
WenDang/P6-G1-G0-REPLAY-CURRENT-STATE-AUDIT.md
WenDang/P6-G1-CURRENT-STATE-AUDIT.md
WenDang/P6-G1-G1-REPLAY-TRACE.md
WenDang/P6-G1-REPLAY-TRACE.md
WenDang/P6-G1-IMPLEMENTATION-REPORT.md
WenDang/P6-G1-TEST-REPORT.md
WenDang/P6-G1-REGRESSION-REPORT.md
WenDang/P6-G1-DEFERRED-ISSUES.md
WenDang/P6-G1-CLOSURE-REPORT.md
```

等待下一步指令。
