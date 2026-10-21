# P6-G0 回归报告 V2

> 日期：2026-09-22  
> 解释器：项目 `.venv\Scripts\python.exe`  
> 相对 V1（334 OK）：本轮新增生命周期 / N2 / OBS 测试；未删旧测试、未 skip、未改旧期望。

---

## 完整 discover

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

```text
Ran 530 tests in 237.064s
OK
```

其中 Real* Extractor 类 42 个（需 Key，本机有 Key 故实际打了 LLM）。  
非 Real = 488。V1 的 334 是当时过滤后的离线包；本轮 **超集全绿**，因此原 334 全部 PASS。

---

## 新增（相对 V1）

| 来源 | 约计数 | 结果 |
|---|---|---|
| `tests.test_bot_lifecycle` | 21 | PASS |
| P0 N2 | 1 | PASS |
| Topic sidepath N2 | 1 | PASS |
| llm_client OBS | 1 | PASS |
| webui preflight | 1 | PASS |

Targeted 先跑 49 OK（含上述相关旧测试），再跑全量。

---

## 冻结包抽查

| 包 | 结果 |
|---|---|
| P0 `test_p0_message_runtime` `test_runtime_admit` | PASS |
| P1/P2 `test_p1_p2_audit` | PASS |
| Topic store/engine/sidepath/isolation | PASS |
| Task store/engine/sidepath/isolation | PASS |
| Decision store/engine/sidepath/isolation | PASS |
| Risk store/engine/sidepath/isolation | PASS |
| WebUI process helper | PASS |

任何旧 FAIL：无。未通过删测试/改期望变绿。

---

## 开关核验（回归后 + 真机 Stop 后）

```text
runtime_control/TOPIC_ENGINE_ENABLED    = false
runtime_control/TASK_ENGINE_ENABLED     = false
runtime_control/DECISION_ENGINE_ENABLED = false
runtime_control/RISK_ENGINE_ENABLED     = false
模块常量四个 Engine                       = False
```

本轮没有把生产开关写成长期 true。

---

## 未改冻结区

message Trigger / Self / P0 Dedupe key / Outbound / Chat Prompt / 四个 EXTRACTOR decision schema / 四引擎业务决策 / Risk severity / 自动 RESOLVED / Dashboard / DJ-R8 / RK-R9。
