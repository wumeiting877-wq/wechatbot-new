# P6-G3 Regression Report

> 日期：2026-09-22  
> 命令：`.\.venv\Scripts\python.exe -m unittest discover -s tests`

```text
Ran 568 tests in 220.839s
OK
```

基线 555 全部保留。新增 13（P6-G3 CONSIST + 碰撞/开关锁定）。  
无 skip，无改旧 expectation。

---

## 定向回归

```text
tests.test_p6g2_downstream_retry
tests.test_task_store
tests.test_decision_store
tests.test_risk_store
tests.test_task_engine_offline
tests.test_decision_engine_offline
tests.test_risk_engine_offline
```

```text
Ran 152 tests
OK
```

P6-G2 FAILED retry、Topic replay、N2、Stop / disabled 仍 PASS（CONSIST-06～10 再次锁定）。

---

## 未改动的表面

```text
Topic Engine / Topic Store / Topic Side-path
bot_lifecycle / webui
downstream_retry eligibility（仍仅 FAILED）
四 Engine 模块开关 = false
```

---

## 开关抽查

```text
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

---

## 结论

```text
原 555 PASS
P6-G3 13 PASS
discover = 568 OK
```
