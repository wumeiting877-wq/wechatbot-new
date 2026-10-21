# P7-G0 Regression Report

> 日期：2026-09-23

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests
Ran 628 tests in 171.394s
OK
```

613 条既有测试 + 15 条 P7-G0 测试。

P6-G6 missing-processing 套件包含在这次 discover 里，结果为 OK。`NOT_FOUND` 仍拒绝自动执行。

回归后四个开关文件仍是：

```text
TOPIC_ENGINE_ENABLED=false
TASK_ENGINE_ENABLED=false
DECISION_ENGINE_ENABLED=false
RISK_ENGINE_ENABLED=false
```

模块常量同样为 false。
