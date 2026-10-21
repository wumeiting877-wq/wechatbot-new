# P6-G5 Test Report

> 日期：2026-09-22  
> 文件：`tests/test_p6g5_topic_retry.py`  
> 无微信、无 Real LLM。Fake Extractor + counter + TemporaryDirectory。

---

## 命令

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p6g5_topic_retry -v
```

```text
Ran 16 tests
OK
```

---

## TOPIC-RETRY-01 ～ 14

| ID | 场景 | 结果 |
|---|---|---|
| 01 | FAILED → retry NEW_TOPIC | Topic Extractor +1，fan-out +1/+1/+1，Chat +0。再次 retry = NOT_RETRYABLE |
| 02 | FAILED → retry EXISTING_TOPIC | `replayed=false`，fan-out +1/+1/+1 |
| 03 | FAILED → retry TOPIC_UPDATE | `replayed=false`，fan-out +1/+1/+1 |
| 04 | FAILED → retry UNRELATED | processing=UNRELATED，fan-out 0；再次 retry = NOT_RETRYABLE，Extractor +0 |
| 05 | FAILED → retry FAILED | Extractor +1，无递归，fan-out 0，Chat 0 |
| 06 | SUCCESS processing retry | NOT_RETRYABLE，Extractor 0，fan-out 0 |
| 07 | 不存在 processing | NOT_FOUND，不创建 |
| 08 | STOPPING / STOPPED / ERROR / STARTING | STOPPED，Extractor 0；恢复 RUNNING 后可 SUCCESS |
| 09 | Topic Engine disabled | ENGINE_DISABLED，Extractor 0 |
| 10 | Task disabled，Decision/Risk 开 | Topic SUCCESS 后 fan-out 0/1/1 |
| 11 | P6-G1 SUCCESS replay | fan-out 无新增，`TOPIC_REPLAY` + `fanout_skipped` |
| 12 | N2 同正文不同 pid | 两条 MessageRecord，两次首次 Topic，fan-out 2/2/2 |
| 13 | P0 DUPLICATE | listener duplicate，不入 Topic Queue |
| 14 | Topic SUCCESS + Task FAILED | `retry_topic` 拒绝；`retry_downstream(task)` 独立成功，Topic Extractor +0 |

另：

```text
test_flags_remain_disabled
test_source_is_sync_internal_capability
```

`topic_retry.py` 无 Queue / Thread / send_reply / 三套 allow 规则副本。

---

## 探针（不进 discover）

```text
tests._p6g5_probe_topic_failed_retry
Ran 3 tests
OK
```
