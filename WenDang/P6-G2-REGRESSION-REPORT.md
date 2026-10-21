# P6-G2 Regression Report

> 日期：2026-09-22  
> 相对基线：540 tests OK（P6-G1 COMPLETE）

---

## 命令

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p6g2_downstream_retry -v
→ Ran 15 tests in 1.166s
OK

.\.venv\Scripts\python.exe -m unittest discover -s tests
→ Ran 555 tests in 249.420s
OK
```

---

## 计数

```text
原 540 全 PASS
+ P6-G2 15 条 PASS
= 555 OK
```

未删除旧测试。未 skip。未改旧 expectation。

---

## 冻结区

未修改：

```text
listener Trigger Self P0 Dedupe Outbound Chat Prompt
四个 EXTRACTOR decision schema
Topic replay 行为
N2 语义
bot_lifecycle webui_bot_process
Risk severity / 自动 RESOLVED
Dashboard / 提醒 / 日报 / RAG / 企业微信
```

---

## 开关

```text
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

`test_flags_remain_disabled` 与既有 P6-G1 / lifecycle 测试共同锁定。

---

## P6-G1 行为

RETRY-09：同 MessageRecord Topic replay → fan-out 仍 1/1/1（0 新）。  
RETRY-10：同正文不同 `platform_message_id` → 两条独立 MessageRecord。
