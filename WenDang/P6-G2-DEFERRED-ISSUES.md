# P6-G2 Deferred Issues

> 日期：2026-09-22  
> 不阻塞 P6-G2 COMPLETE。

---

## D1. 人工入口

第一版只有内部 `retry_downstream`。  
WebUI Retry 按钮 / 失败列表 / REST 另开 **P6-G3**（若需要）。

---

## D2. 自动重试

无 cron / scheduler / max_retries / backoff。  
若要自动恢复，另开 Gate。需要 schema 时按本阶段 STOP 规则先报告。

---

## D3. apply 成功但 finalize 失败

当前 Isolate 发生在 Extractor/validate 异常，apply 未执行。  
若未来 `commit_apply` 已写实体、随后 `_finalize` 崩溃，可能出现「实体已在 + processing=FAILED」。再次 retry 可能按确定性 id 生成带 suffix 的新 Task。

不改 Engine。记录在案。

---

## D4. Runtime 未传入

设计选择：`runtime=None` 时允许离线 retry，不绑定默认 `STOPPED` 的全局单例。  
生产接 LLM 时调用方应传入 Runtime。是否强制 Runtime 另议。

---

## D5. 不存在 processing 的「补跑」

`NOT_FOUND` 拒绝，不自动当第一次 process。  
若产品要「从未跑过的下游补跑」，那是首次执行，不是 FAILED retry，另开 Gate。

---

## D6. Topic 失败恢复

本阶段只恢复下游。Topic FAILED 仍按 P6-G1：0 fan-out。Topic 层补偿不在范围。
