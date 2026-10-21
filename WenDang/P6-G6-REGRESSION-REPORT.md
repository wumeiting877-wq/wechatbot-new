# P6-G6 Regression Report

> 日期：2026-09-23

## 命令

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## 结果

```text
Ran 613 tests in 141.697s
OK
```

```text
595 旧测试 PASS
+ 18 个 P6-G6 测试 PASS
= 613
```

未删除旧测试，未 skip，未修改旧 expectation。

`tests/_p6g6_probe_missing_processing.py` 文件名不以 `test` 开头，不进入 discover。

系统 Python 缺少 flask / werkzeug / openai，不能用来复现这 613。回归使用项目 `.venv`。

## 开关

```text
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

测试里的 `enabled=True` 只作用在注入的 Engine 实例上。
