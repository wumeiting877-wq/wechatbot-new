# P6-G6 Implementation Report

> 日期：2026-09-23

```text
NO PRODUCTION CODE CHANGE
```

TYPE C。没有新增 `processing_recovery.py`，没有修改：

```text
topic_engine.py / topic_store.py
task_engine.py / task_store.py
decision_engine.py / decision_store.py
risk_engine.py / risk_store.py
topic_retry.py / downstream_retry.py
```

四个 Engine 模块常量仍为 `false`。

新增的是故障注入探针和锁定测试：

```text
tests/_p6g6_probe_missing_processing.py
tests/test_p6g6_missing_processing.py
```

探针不进入 `unittest discover`。测试锁定：

```text
NOT_FOUND 不自动执行
CASE A 仍是 FAILED，走既有 retry
CASE B 的 processing 缺失可达，retry 继续 NOT_FOUND
SUCCESS 不被覆盖
STOPPED 拒绝且不写
```
