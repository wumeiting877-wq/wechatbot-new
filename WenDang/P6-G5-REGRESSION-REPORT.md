# P6-G5 Regression Report

> 日期：2026-09-22

---

## 完整 discover

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

```text
Ran 595 tests in 112.287s
OK
```

基线 579 + 本 Gate 16 个新测试 = 595。  
未删旧测试，未 skip，未改旧 expectation。

探针 `_p6g5_probe_*.py` 不进入 discover（文件名不以 `test` 开头）。

---

## 冻结套件（额外复跑）

```text
tests.test_p6g1_replay_idempotency     OK
tests.test_p6g2_downstream_retry       OK
tests.test_p6g3_apply_finalize_consistency OK
tests.test_p6g4_collision_evidence     OK
tests.test_bot_lifecycle               OK
tests.test_topic_sidepath              OK
```

---

## 四 Engine 开关

模块常量仍为：

```text
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

测试内 DI `enabled=True`，不改模块默认。

---

## 未改文件（回归相关）

```text
downstream_retry.py
task_store.py decision_store.py risk_store.py
topic_engine.py topic_store.py
P0 Dedupe / listener / keep_alive / Stop / Start
```
