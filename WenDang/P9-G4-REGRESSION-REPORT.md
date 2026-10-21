# P9-G4 Regression Report

> 日期：2026-09-24

## Gate 与冻结链

```text
P9-G4 + P9-G3 + P9-G2 + P9-G1
Ran 113 tests
OK
```

其中 P9-G4 39、P9-G3 32、P9-G2 25、P9-G1 17。

```text
P8 + Task Store / Engine / Sidepath
Ran 196 tests
OK
```

## Non-Live

discover 起点为 `tests`，排除：

```text
RealTaskExtractorTests
RealTopicExtractorTests
RealDecisionExtractorTests
RealRiskExtractorTests
```

结果：

```text
kept 880
skipped_live 42
Ran 880 tests in 44.079s
OK
```

```text
880 = 旧 841 + P9-G4 新增 39
```

Real Extractor 42 条未运行，未修改 expectation。四个 Engine flags 仍为 false。

