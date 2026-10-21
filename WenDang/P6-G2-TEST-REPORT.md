# P6-G2 Test Report

> 日期：2026-09-22  
> 文件：`tests/test_p6g2_downstream_retry.py`  
> 命令：`.\.venv\Scripts\python.exe -m unittest tests.test_p6g2_downstream_retry -v`

```text
Ran 15 tests in 1.166s
OK
```

不连真机。不连 Real LLM。fake Extractor + counter + Store fixture + TemporaryDirectory。

---

## CASE

| ID | 场景 | 期望 | 结果 |
|---|---|---|---|
| RETRY-01 | Task FAILED → retry SUCCESS | Task Extractor +1；Topic/Decision/Risk +0；Chat +0；processing 覆盖为 NEW_TASK；再 retry 拒绝 | **PASS** |
| RETRY-02 | Decision FAILED → retry SUCCESS | Decision +1；其它 Extractor +0；Chat +0 | **PASS** |
| RETRY-03 | Risk FAILED → retry SUCCESS | Risk +1；其它 +0；Chat +0 | **PASS** |
| RETRY-04 | FAILED → retry FAILED | 只执行一次；无递归；audit REQUESTED×1 FAILED×1 | **PASS** |
| RETRY-05 | SUCCESS 不允许 retry | Extractor delta=0；`NOT_RETRYABLE` | **PASS** |
| RETRY-06 | UNRELATED 不允许 retry | reject；Extractor delta=0 | **PASS** |
| RETRY-07 | 不存在 processing | `NOT_FOUND`；不创建 processing | **PASS** |
| RETRY-08 | engine 非法（topic/chat/foo/空） | `INVALID_ENGINE` | **PASS** |
| RETRY-09 | Topic replay | fan-out 仍 0 新（保持 1/1/1）；`TOPIC_REPLAY` | **PASS** |
| RETRY-10 | N2 同正文不同 pid | 两条独立 MessageRecord；enqueue 2/2/2 | **PASS** |
| RETRY-11 | Task retry FAILED 隔离 | Decision/Risk/Topic 不跑；实体数不变；Chat=[] | **PASS** |
| RETRY-12 | STOPPING / STOPPED | `STOPPED`；Extractor 0；恢复 RUNNING 后可 retry | **PASS** |
| FLAGS | 四 Engine 模块常量 | 全 false | **PASS** |
| DISABLED | `engine.enabled=False` | `ENGINE_DISABLED` | **PASS** |
| SOURCE | 无 Queue/Thread/Chat 发送 | 源码约束 | **PASS** |

---

## RETRY-01 计数

Topic SUCCESS + Decision SUCCESS + Risk SUCCESS + Task FAILED 之后：

```text
retry Task
  Task Extractor     +1
  Decision Extractor +0
  Risk Extractor     +0
  Topic Extractor    +0
  Chat               +0
  Task 实体 / link    +1
第三次 retry
  全部 Extractor      +0
```

---

## Gate 1 既有探针（未改 Engine）

```text
Ran 6 tests in 0.180s
OK
```
