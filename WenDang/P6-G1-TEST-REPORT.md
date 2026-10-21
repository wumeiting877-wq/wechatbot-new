# P6-G1 Test Report

> 日期：2026-09-22  
> 文件：`tests/test_p6g1_replay_idempotency.py`  
> 命令：`.\.venv\Scripts\python.exe -m unittest tests.test_p6g1_replay_idempotency -v`

```text
Ran 10 tests in 1.396s
OK
```

不连真机。不连 Real LLM。Heuristic + counter + `_process` / `try_enqueue`。

---

## CASE

| ID | 场景 | 期望 | 结果 |
|---|---|---|---|
| REPLAY-01 | 首次 Topic SUCCESS `replayed=false` | Task/Decision/Risk enqueue=1/1/1；Extractor=1 | **PASS** |
| REPLAY-02 | 同 Message 再 processing `replayed=true` | Topic Extractor=0 新调用；enqueue 仍 1/1/1；Store/evidence 不增；`TOPIC_REPLAY` + `fanout_skipped` | **PASS** |
| REPLAY-03 | 首次 `TOPIC_UPDATE` `replayed=false` | 该消息 fan-out +1/+1/+1 | **PASS** |
| REPLAY-04 | 首次 `EXISTING_TOPIC` `replayed=false` | 不等于 replay；fan-out +1/+1/+1 | **PASS** |
| REPLAY-05 | Topic FAILED | 0 fan-out | **PASS** |
| REPLAY-06 | UNRELATED / SKIPPED | 0 fan-out | **PASS** |
| REPLAY-07 | N2 同正文不同 pid | 两次非 replay；Extractor=2；enqueue=2/2/2；两个 MessageRecord | **PASS** |
| REPLAY-08 | Task 失败 / Decision 失败 | 另外两路仍 enqueue，互不闸门 | **PASS** |
| P0 DUP | 同 pid 再进 listener | `SKIP_DUPLICATE`，不入 Topic Queue；fan-out 仍 1/1/1 | **PASS** |
| FLAGS | 四 Engine 模块常量 | 全 false | **PASS** |

---

## Queue / LLM 不变式（REPLAY-01+02）

同一 `MessageRecord.id`：

```text
首次 Topic SUCCESS:
  Task Queue put     = 1
  Decision Queue put = 1
  Risk Queue put     = 1
  Topic Extractor    = 1

Topic replay:
  Task Queue put     = 0 新
  Decision Queue put = 0 新
  Risk Queue put     = 0 新
  Topic Extractor    = 0 新
  Task/Decision/Risk Extractor 新调用 = 0
```

---

## 未改旧期望

未 delete / skip 旧测试。未改 P0 / N2 / P5 Failure Isolation 断言。
