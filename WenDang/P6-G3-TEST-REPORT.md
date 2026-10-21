# P6-G3 Test Report

> 日期：2026-09-22  
> 文件：`tests/test_p6g3_apply_finalize_consistency.py`  
> 命令：`.\.venv\Scripts\python.exe -m unittest tests.test_p6g3_apply_finalize_consistency -v`

```text
Ran 13 tests in 1.387s
OK
```

无 skip。未改旧测试 expectation。

---

## CONSIST-01 ～ 10

| CASE | 测试 | 结果 | 要点 |
|---|---|---|---|
| CONSIST-01 | `test_consist_01_task_post_apply_failure` | PASS | Task 数量=1，无 `_2`，字段/CREATED_BY/RELATED 不变，processing=NEW_TASK |
| CONSIST-02 | `test_consist_02_decision_post_apply_failure` | PASS | Decision 同构；不再 CREATED_BY_REQUIRED |
| CONSIST-03 | `test_consist_03_risk_post_apply_failure` | PASS | Risk 数量=1，无 `_2` |
| CONSIST-04 | `test_consist_04_evidence_not_duplicated_across_three_engines` | PASS | 三路 CREATED_BY=1、RELATED=1，retry 后三元组不变 |
| CONSIST-05 | `test_consist_05_processing_not_stuck_failed` | PASS | 三路 retry 后 `has_successful_processing`，error 清空 |
| CONSIST-06 | `test_consist_06_extractor_failure_then_retry_success` | PASS | apply 未执行：0 实体 → retry → 1 实体 SUCCESS（P6-G2 仍成立） |
| CONSIST-07 | `test_consist_07_success_processing_rejects_retry` | PASS | REJECTED / Extractor delta=0 |
| CONSIST-08 | `test_consist_08_topic_replay_zero_fanout` | PASS | Topic replay fan-out 仍 1/1/1，第二次 0 |
| CONSIST-09 | `test_consist_09_n2_same_text_different_pid` | PASS | 同文不同 pid → 两条 MessageRecord，fan-out 2/2/2 |
| CONSIST-10 | `test_consist_10_stop_and_engine_disabled` | PASS | STOPPED / enabled=false 拒绝；恢复后一次 retry SUCCESS |

附加锁定：

| 测试 | 结果 | 要点 |
|---|---|---|
| `test_true_collision_different_message_still_suffixes` | PASS | 同 id、不同 `created_msg_id` 仍 `_2` |
| `test_flags_remain_disabled` | PASS | 四开关 false |
| `test_retry_source_still_one_shot` | PASS | 无 Queue / Thread / send_reply |

注入方式：临时替换 `engine._finalize`，不是 Extractor boom。

核对项不只实体数量：id、title、assignee / decision_text / condition+impact、`created_at`、CREATED_BY、RELATED、processing ids。

---

## 故障注入证明

修复前探针（`tests/_p6g3_probe_post_apply.py`，不进 discover）：

```text
Task     retry → task_*_2
Decision retry → CREATED_BY_REQUIRED，processing 仍 FAILED
Risk     retry → risk_*_2
```

修复后同一探针：三路实体=1、processing SUCCESS、无 suffix。
