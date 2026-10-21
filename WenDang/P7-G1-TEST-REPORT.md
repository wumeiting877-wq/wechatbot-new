# P7-G1 Test Report

> 日期：2026-09-23

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p7g1_manual_retry
Ran 20 tests
OK
```

没有真实微信，也没有为这 20 条去打真实 LLM。Topic / Downstream 成功路径使用假的 retry service 和计数器。ACTION-12 使用启发式 Extractor，验证 fan-out 仍看既有开关。

| ID | 结果 |
| --- | --- |
| ACTION-01 | Topic FAILED → `retry_topic` 一次 → after SUCCESS |
| ACTION-02 | 只重试 Task |
| ACTION-03 | 只重试 Decision |
| ACTION-04 | 只重试 Risk |
| ACTION-05 | SUCCESS → 409 NOT_RETRYABLE，capability 0 次 |
| ACTION-06 | UNRELATED 不可重试 |
| ACTION-07 | SKIPPED 不可重试 |
| ACTION-08 | NOT_FOUND_UNKNOWN 拒绝，Topic/Downstream 0 次 |
| ACTION-09 | 打开时 FAILED、点击时已是 SUCCESS → 拒绝；version 不一致同样拒绝 |
| ACTION-10 | Runtime STOPPED → 423，0 次 |
| ACTION-11 | Engine 开关关闭 → ENGINE_DISABLED，0 次 |
| ACTION-12 | 下游开关关闭时 fan-out 为 0；打开后按既有规则各入队一次 |
| ACTION-13 | Task 重试不改变 Topic / Decision / Risk processing |
| ACTION-14 | 同 identity 并发，inflight 最大为 1，只有一次 executed |
| ACTION-15 | 只有 FAILED_RETRYABLE 出现重试按钮 |
| ACTION-16 | UNKNOWN 行没有重试按钮 |
| ACTION-17 | 未登录 401；登录开关关闭 403 且 0 次；两者都通过才执行 |
| ACTION-18 | 缺 processing 仍是 NOT_FOUND_UNKNOWN；P6 NOT_FOUND 字符串未改 |

另外：Action Service 源码不含 `TopicEngine(`、`TaskEngine(`、`DecisionEngine(`、`RiskEngine(`、`write_processing`、`commit_apply`、`create_topic`、`create_task`、`create_decision`、`create_risk`、`send_reply`。Wiring 源码不含 `enabled=True`。

测试要打开开关时，临时改 `runtime_control` 里的开关文件，`tearDown` 按原字节写回。环境变量盖不过已存在的开关文件。
