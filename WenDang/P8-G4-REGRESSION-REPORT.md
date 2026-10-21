# P8-G4 Regression Report

> 日期：2026-09-23

定向 92 条通过。原有非 live 712 条没有新增失败。

---

## 1. 定向

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g1_collaboration_query tests.test_p8g2_query_intent tests.test_p8g3_query_delivery tests.test_p8g4_identity
Ran 92 tests in 2.423s
OK
```

```text
tests.test_p8g1_collaboration_query   42 OK
tests.test_p8g2_query_intent          25 OK
tests.test_p8g3_query_delivery        22 OK
tests.test_p8g4_identity               3 OK
```

P8-G1 的列表查询、范围和停止仍然成立。P8-G2 的身份固定句和分类器边界没有被放宽。P8-G3 的 pending 交付没有被另造一套。

## 2. Non-Live

按 `discover -s tests` 加载，排除四个 `Real*ExtractorTests`：

```text
Ran 715 tests in 47.569s
OK
failures 0
errors 0
```

715 = 进入本 Gate 前的 712 + 本 Gate 3 条。旧 712 条没有新增失败。

## 3. Live Extractor

42 条 Real Extractor 本 Gate 不运行，也不修改。原 live dependency 问题仍单独记录。

## 4. Engine

测试结束时四个开关仍为 `false`。没有改 P0，没有改 P6-G6 processing。
