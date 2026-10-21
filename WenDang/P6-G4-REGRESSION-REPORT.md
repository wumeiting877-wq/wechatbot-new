# P6-G4 Regression Report

> 日期：2026-09-22  
> 命令：`.\.venv\Scripts\python.exe -m unittest discover -s tests`

```text
Ran 579 tests in 124.427s
OK
```

基线 568 全部保留。新增 11（P6-G4 REF-01～10 + id 生成器锁定）。  
无 skip，无改旧 expectation。

---

## 定向回归

```text
tests.test_p6g3_apply_finalize_consistency
tests.test_p6g2_downstream_retry
tests.test_p6g1_replay_idempotency
tests.test_bot_lifecycle
```

```text
Ran 59 tests
OK
```

另：`tests.test_p6g4_collision_evidence` 11 OK。

---

## 冻结项

| 冻结 | 结果 |
|---|---|
| P6-G3 CONSIST-01～10，post-apply failure → retry 不 duplicate | PASS |
| P6-G3 真碰撞仍 suffix | PASS |
| P6-G2 FAILED → explicit retry → only one downstream | PASS |
| P6-G1 Topic replay → 0 new fan-out | PASS |
| P6-G0 Stop → keep_alive 不重生；Restart 单实例 | PASS |
| N2 同文不同 pid | PASS（含在 discover / CONSIST-09） |
| `downstream_retry.py` eligibility 未改 | 本轮未改该文件 |
| 四 Engine flags = false | PASS |

---

## 未改动的表面

```text
Topic Engine / Topic Store / Topic Side-path
make_task_id / make_decision_id / make_risk_id
create_task / create_decision / create_risk 的 suffix 策略
WebUI Retry / Dashboard / Reminder / Auto Retry
生命周期 / keep_alive
```
