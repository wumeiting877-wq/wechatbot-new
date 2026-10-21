# P9-G5 Regression Report

> 日期：2026-09-24

## Gate 链

```text
P9-G1 + P9-G2 + P9-G3 + P9-G4 + P9-G5
Ran 132 tests
OK
```

其中：P9-G1 17、P9-G2 25、P9-G3 32、P9-G4 39、P9-G5 19。

## P8 + Task

```text
Ran 196 tests
OK
```

模块为 P8-G1…G6、Task Store、Task Engine Offline、Task Sidepath，计数与冻结基线一致。

## Non-Live

从 `tests` discover，排除四个明确的 Real Extractor 类：

```text
RealTaskExtractorTests
RealTopicExtractorTests
RealDecisionExtractorTests
RealRiskExtractorTests
```

结果：

```text
discovered 941
kept 899
skipped_live 42
Ran 899 tests
failures 0
errors 0
OK
```

```text
899 = 旧 880 + P9-G5 新增 19
```

旧行为 880 条全部保留。Real Extractor 42 条未作为本 Gate 关闭测试，未修改 expectation。

## Engine

```text
TOPIC_ENGINE_ENABLED=false
TASK_ENGINE_ENABLED=false
DECISION_ENGINE_ENABLED=false
RISK_ENGINE_ENABLED=false
```
