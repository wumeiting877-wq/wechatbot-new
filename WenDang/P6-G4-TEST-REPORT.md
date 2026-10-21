# P6-G4 Test Report

> 日期：2026-09-22  
> 文件：`tests/test_p6g4_collision_evidence.py`  
> 探针：`tests/_p6g4_probe_collision_evidence.py`  
> 命令：`.\.venv\Scripts\python.exe -m unittest tests.test_p6g4_collision_evidence -v`

```text
Ran 11 tests in 5.200s
OK
```

无 skip。未改旧测试 expectation。

---

## REF-01 ～ 10

| CASE | 测试 | 结果 | 要点 |
|---|---|---|---|
| REF-01 | `test_ref_01_task_true_collision_created_by` | PASS | `task_x` + `task_x_2`；A/B 各挂自己的 CREATED_BY |
| REF-02 | `test_ref_02_decision_true_collision_created_by` | PASS | Decision 同构；不再 CREATED_BY_REQUIRED |
| REF-03 | `test_ref_03_risk_true_collision_created_by` | PASS | Risk 同构 |
| REF-04 | `test_ref_04_related_remap_to_suffix` | PASS | 三路 suffix 的 RELATED.entity_id = final id |
| REF-05 | `test_ref_05_updated_by_remap_task_and_risk` | PASS | Task/Risk：碰撞 commit 内 UPDATED_BY remap；随后对 suffix 再 UPDATE 仍挂 final id。Decision 无 UPDATED_BY |
| REF-06 | `test_ref_06_same_logical_retry_still_skip` | PASS | 同 created_msg_id 再 apply：实体数=1，无 `_2` |
| REF-07 | `test_ref_07_processing_records_final_id` | PASS | 强制碰撞后 processing 记录 `*_2`，不是原 id |
| REF-08 | `test_ref_08_suffix_entity_evidence_complete` | PASS | 每个 suffix 满足 CREATED_BY；无错挂 |
| REF-09 | `test_ref_09_create_star_direct_legacy_suffix` | PASS | 直连仍 suffix；suffix 自带 CREATED_BY；生产模块源码无 create_* |
| REF-10 | `test_ref_10_engine_flags_remain_false` | PASS | 四个 Engine flag 仍 false |

附加：`test_id_generators_unchanged` 锁定 `make_*_id` 未改、`commit_apply` 含 `id_map`。

---

## P6-G3 冻结

`tests.test_p6g3_apply_finalize_consistency` 随定向回归 PASS。  
`test_true_collision_different_message_still_suffixes` 继续 PASS。
