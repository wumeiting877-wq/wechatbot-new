# P7-G2 Test Report

> 日期：2026-09-23

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_p7g2_diagnostics.py
Ran 17 tests in 1.312s
OK
```

使用 TemporaryDirectory、Store fixture 和 Flask test client。没有真机，没有为这组测试调用 LLM。

| ID | 结果 |
| --- | --- |
| DIAG-01 | SUCCESS 展示 processing、实体、CREATED_BY 与 UPDATED_BY；正文不截断；时间来源分开 |
| DIAG-02 | FAILED_RETRYABLE 展示 `error` 原文，processing 记录没有 `error_code` |
| DIAG-03 | 有实体时状态仍是 NOT_FOUND_UNKNOWN，不升成 SUCCESS |
| DIAG-04 | 有 CREATED_BY 时仍是 UNKNOWN，标记里没有 NEW_TOPIC |
| DIAG-05 | audit FAILED 只产生 AUDIT_FAILED_PRESENT，状态不是 FAILED_RETRYABLE |
| DIAG-06 | 0 实体 / 0 证据 / 0 audit 仍是 UNKNOWN；文案是「未发现业务处理记录」，没有「确认从未执行」 |
| DIAG-07 | RELATED 只说明消息与实体有关，不出现 EXISTING_TOPIC |
| DIAG-08 | `created_msg_id` + CREATED_BY 只产生「存在创建证据」，不出现 NEW_TASK |
| DIAG-09 | MANUAL_RETRY_REQUESTED / RESULT 可见；risk 仍是 UNKNOWN；不写 processing |
| DIAG-10 | 四路分别是 SUCCESS、UNKNOWN、FAILED_RETRYABLE、UNKNOWN |
| DIAG-11 | 只返回当前会话、当前消息的 Evidence |
| DIAG-12 | GET 200，缺失 404，POST 405；列表有「查看详情」；路由带 login_required |
| DIAG-13 | UNKNOWN 页面有调查文案，没有按钮、/retry、Repair、Reprocess |
| DIAG-14 | 再跑 `test_p7g0_operations_read_model`，三态套件通过 |
| DIAG-15 | 再跑 `test_p6g6_missing_processing`，TYPE C 套件通过；CREATED_BY + audit 仍是 UNKNOWN |

另有两条：

```text
诊断服务源码不含写入、重试、Engine(、Extractor、send_reply
同一消息 25 条 audit 只返回最近 20 条；更早的 FAILED 仍只作为标记，状态保持 UNKNOWN
```

每条测试结束都确认四个 Engine 模块常量和 `is_*_engine_enabled()` 为 false。
