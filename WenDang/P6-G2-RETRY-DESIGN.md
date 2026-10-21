# P6-G2 Retry Design

> 日期：2026-09-22  
> 第一版：显式 / 独立 / 可审计 / 有限 / 幂等 / 同步内部 capability。

---

## 1. 两种语义（必须分开）

### Topic replay（P6-G1 冻结）

```text
Topic 已 SUCCESS
同 MessageRecord 再跑 Topic
→ replayed=true
→ Task/Decision/Risk enqueue = 0
```

不是下游补偿。本阶段禁止重新打开 fan-out。

### Downstream retry（本 Gate）

```text
Topic = SUCCESS
某一路 processing = FAILED
显式 retry 该 Engine
→ 只重跑这一路
→ 不重跑 Topic / 另外两路 / Chat
```

---

## 2. 为什么不改 Engine

Gate 1 已证明：

```text
FAILED ≠ successful processing
write_processing 在非成功时覆盖同 key
process_record 会再次调用 Extractor
```

改 Engine 或升 version 会违反「优先复用」。

---

## 3. Retry Identity

不使用正文 / title / 模糊匹配。

```text
RetryRequest
{
  engine: "task" | "decision" | "risk",
  conversation_id,
  message_id,
  topic_id,          # 可从 processing 补齐；若与 processing 不一致 → IDENTITY_MISMATCH
  version             # 默认 Store DEFAULT_PROCESSING_VERSION = 1
}
```

不新增 schema。字段全部来自现有 processing 记录。

---

## 4. Eligibility

只允许：

```text
decision_summary / decision 的每一段都是 FAILED
```

拒绝：

```text
NEW_TASK TASK_UPDATE NEW_DECISION NEW_RISK RISK_UPDATE
UNRELATED SKIPPED
SUCCESS 语义下的任何 successful processing
不存在 processing → NOT_FOUND（禁止自动创建）
非法 engine（含 topic / chat）→ INVALID_ENGINE
engine.enabled=false → ENGINE_DISABLED
Runtime 不接活 → STOPPED
```

UNRELATED 在 Store 中属于 SUCCESS_DECISIONS，**不是** retryable。

---

## 5. 最小服务

文件：`downstream_retry.py`

```text
DownstreamRetryService.retry_downstream(...)
retry_downstream(..., service=...)
```

流程：

```text
validate engine
resolve Engine + Store
ENGINE_DISABLED?
load processing → NOT_FOUND?
identity / topic_id
Runtime STOPPED?
eligibility
load TopicRecord + MessageRecord
audit REQUESTED
Engine.process_record  恰好一次
audit SUCCESS | FAILED
return
```

没有：

```text
Queue / Thread / Scheduler / cron
max_retries / backoff / retry_count
WebUI / REST / 微信命令
```

---

## 6. 一次一发

```text
一次显式请求 = 最多一次 process_record
FAILED 后不自动再跑
SUCCESS 后再请求 = REJECTED，Extractor delta = 0
```

Retry 不强迫 `NEW_TASK`。Extractor 返回什么，processing 就写什么。

---

## 7. 独立不变式

retry Task：

```text
Task Extractor    +1（若执行）
Decision Extractor +0
Risk Extractor     +0
Topic Extractor    +0
Chat               +0
```

Decision / Risk 同理。任一路 retry FAILED 不影响另外两路已有实体。

---

## 8. Runtime

```text
传入 runtime 且 is_accepting_work()==False
→ STOPPED（STOPPING 同样）
禁止在 Bot 已 Stop 时偷偷跑 LLM

runtime is None
→ 允许
原因：离线内部 capability；不绑定默认 STOPPED 的全局单例
```

这是设计选择，不是 Blocker。生产若连接真 LLM，调用方传入 Runtime。

---

## 9. Engine 开关

```text
检查 engine.enabled
false → ENGINE_DISABLED
不把模块常量改成 true
不经过 Side-path 入队来「顺便」enabled=True
```

测试注入 `enabled=True` 的 Engine，与 P6-G1 Side-path 测试相同。

---

## 10. Audit

写入目标 Engine 的现有 `*_engine_audit.jsonl`，并保留内存 `audit_events`。

```text
DOWNSTREAM_RETRY_REQUESTED
DOWNSTREAM_RETRY_SUCCESS
DOWNSTREAM_RETRY_FAILED
DOWNSTREAM_RETRY_REJECTED
```

字段：`engine conversation_id message_id topic_id previous_status result error_code`。

---

## 11. 明确不做（本 Gate）

```text
自动定时 Retry
Dashboard / Retry 按钮
微信命令
失败通知 / 催办
Retry Queue
max_retries=3
重开 Topic replay fan-out
改四个 EXTRACTOR schema
```
