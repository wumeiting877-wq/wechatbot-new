# P6-G1 Regression Report

> 日期：2026-09-22  
> 相对基线：530 tests OK（P6-G0 COMPLETE）

---

## 命令

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p6g1_replay_idempotency -v
→ 10 tests OK

.\.venv\Scripts\python.exe -m unittest tests.test_topic_sidepath tests.test_p0_message_runtime.P0MessageRuntimeTests.test_n2_same_text_different_platform_message_id_two_new tests.test_bot_lifecycle.N2StoreAntiRegressionTests tests.test_task_sidepath tests.test_decision_sidepath tests.test_risk_sidepath -v
→ 60 tests OK（含 N2 / P0 DUPLICATE / Failure Isolation）

.\.venv\Scripts\python.exe -m unittest discover -s tests -v
→ Ran 540 tests in 253.575s
OK
```

---

## 计数

```text
原 530 全 PASS
+ P6-G1 10 条 PASS
= 540 OK
```

未删测试。未 skip。未改旧 expectation。

---

## 冻结面抽查

| 面 | 结果 |
|---|---|
| P0 DUPLICATE 不入 Topic | `test_s5_duplicate_no_enqueue` / P6-G1 P0 DUP **PASS** |
| N2 同文不同 pid | P0 / lifecycle / topic_sidepath / REPLAY-07 **PASS** |
| EXISTING_TOPIC / TOPIC_UPDATE 首次 fan-out | ts2/ts3、ds2/ds3、rs2/rs3、REPLAY-03/04 **PASS** |
| FAILED / UNRELATED / SKIPPED 0 fan-out | 既有 ts/ds/rs + REPLAY-05/06 **PASS** |
| Failure Isolation | ds8/ds9、rs8/rs9、REPLAY-08 **PASS** |
| P6-G0 生命周期 | `test_bot_lifecycle` 随 discover **PASS** |
| 未改 `bot_lifecycle.py` / `webui_bot_process.py` | 本轮未触碰 |

---

## 开关

```text
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

未写长期生产 enable。未新增 `runtime_control/*_ENGINE_ENABLED` 文件。
