# P6-G5 Deferred Issues

> 日期：2026-09-22  
> 不阻塞 P6-G5 COMPLETE。

---

## D1. Processing 缺失恢复

`NOT_FOUND` 禁止自动当首次执行、禁止自动创建 processing。  
若 MessageRecord 在、processing 丢了，恢复继续后续 Gate。

---

## D2. 人工入口

第一版只有内部 `retry_topic`。  
WebUI Retry 按钮 / 失败列表 / REST / 微信命令另开 Gate。

---

## D3. 自动重试

无 cron / scheduler / max_retries / backoff。  
若要自动恢复，另开 Gate。需要新 Queue 时按 STOP 规则先报告。

---

## D4. Topic Retry Queue

本阶段明确不新增第五条 Queue。  
若未来必须异步化显式 retry，先写设计原因，不要默认加 worker。

---

## D5. Dashboard / Reminder / 新业务 Engine

不在本 Gate 范围。
