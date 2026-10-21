# P6-G6 Test Report

> 日期：2026-09-23  
> 文件：`tests/test_p6g6_missing_processing.py`  
> 结果：18 OK

假 Extractor，`TemporaryDirectory`，在 `process_record` 上替换 `write_processing`。未调用微信，未调用真 LLM。

| ID | 测试 | 结果 |
|---|---|---|
| MP-01 | 只有 MessageRecord，无 processing、无实体 → `retry_topic` = `NOT_FOUND`，Extractor 调用数不变 | PASS |
| MP-02 | 四路 SUCCESS 写入失败、isolate 成功 → processing=`FAILED` | PASS |
| MP-02 | Task 的 FAILED 走既有 `retry_downstream`，实体仍是 1 个，processing 回到 `NEW_TASK` | PASS |
| MP-03 | 四路两次写入都失败 → processing 不存在，实体和 CREATED_BY 在，audit=`FAILED` | PASS |
| MP-03 | 该状态 `retry_topic` / `retry_downstream` 仍是 `NOT_FOUND`，不执行 | PASS |
| MP-04 | Topic 缺失窗口后再 `process_record` → 第二个 Topic 后缀 `_2`，两条 CREATED_BY | PASS |
| MP-04 | UNRELATED 双写失败与 apply 前失败：无 Link、无 processing、audit 都是 `FAILED` | PASS |
| MP-04 | EXISTING_TOPIC 双写失败与 evidence RELATED：Link 都是 `RELATED`，processing 都不存在 | PASS |
| MP-05 | `NEW_TASK` 与 `NEW_TASK,UNRELATED` 落盘都是 1 Task + 1 CREATED_BY，processing 都不存在 | PASS |
| MP-06 | Decision 缺失窗口：实体在，`decision_ids` 只出现在失败前的调用参数里，processing 不存在 | PASS |
| MP-07 | Risk 缺失窗口：同上 | PASS |
| MP-08 | SUCCESS 已存在 → retry `NOT_RETRYABLE`，processing 字节级不变，不覆盖 | PASS |
| MP-09 | 已有 FAILED → 走既有 retry，不走 recovery | PASS |
| MP-10 | 同正文、不同 `platform_message_id` → 两条 Message、两条 processing | PASS |
| MP-11 | Topic SUCCESS 再入 → `replayed=true`，Task fan-out 计数不增加 | PASS |
| MP-12 | Task CASE B 后用同一 decision 再执行 → 仍 1 个逻辑实体，无 `_2` | PASS |
| MP-13 | Runtime `STOPPED` → Topic 与 Task retry 都是 `STOPPED`，processing 不变，不写实体 | PASS |
| flags | 四个 `*_ENGINE_ENABLED` 为 false；不存在 `processing_recovery.py` | PASS |

没有删除、skip 或修改旧测试 expectation。
