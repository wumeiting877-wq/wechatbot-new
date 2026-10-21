# P8-G5 Regression Report

> 日期：2026-09-23

P8-G1 到 P8-G4 共 92 条通过。非 live 735 条通过。旧的 715 条没有新增失败。

---

## 1. P8-G1 到 P8-G4

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g1_collaboration_query tests.test_p8g2_query_intent tests.test_p8g3_query_delivery tests.test_p8g4_identity
Ran 92 tests in 1.817s
OK
```

```text
tests.test_p8g1_collaboration_query   42 OK
tests.test_p8g2_query_intent          25 OK
tests.test_p8g3_query_delivery        22 OK
tests.test_p8g4_identity               3 OK
```

个人身份查询仍是固定拒绝。P8-G4 的同名不猜、自由文本不匹配仍然成立。

## 2. 本 Gate

```text
tests.test_p8g5_identity_model        20 OK
```

## 3. Non-Live

按 `discover -s tests` 加载，排除四个 `Real*ExtractorTests`：

```text
kept 735
skipped_live 42
Ran 735 tests in 43.732s
OK
failures 0
errors 0
```

735 = 进入本 Gate 前的 715 + 本 Gate 20 条。

## 4. Live Extractor

42 条 Real Extractor 本 Gate 不运行，也不修改。原 live dependency 问题仍单独记录。

## 5. Engine

测试结束时四个开关仍为 `false`。没有改 P0，没有改 P6-G6 processing，没有改 Task schema。
