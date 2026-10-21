# P6-G5 Retry Design

> 日期：2026-09-22  
> 第一版：显式 / 独立 / 可审计 / 有限 / 幂等 / 同步内部 capability。

---

## 1. 三种语义（必须分开）

### A. Topic FAILED retry（本 Gate）

```text
processing = FAILED
显式 retry Topic
→ 重新执行 Topic Extractor
→ SUCCESS 且 replayed=false 时走既有 fan-out
```

### B. Topic SUCCESS replay（P6-G1 冻结）

```text
processing ∈ SUCCESS_DECISIONS
同 MessageRecord 再跑 Topic
→ replayed=true
→ Task/Decision/Risk enqueue = 0
```

不是补偿。禁止重新打开 fan-out。

### C. Downstream retry（P6-G2 冻结）

```text
Topic = SUCCESS
某一路 processing = FAILED
显式 retry_downstream(task|decision|risk)
→ 只重跑这一路
```

Topic retry **不得代替** downstream retry。

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

不使用正文 / title / 时间 / 模糊匹配。

```text
RetryRequest
{
  conversation_id,
  message_id,
  version             # 默认 TopicStore DEFAULT_PROCESSING_VERSION = 1
}
```

不要求 topic_id：FAILED 时通常还没有 Topic。

---

## 4. Eligibility

只允许：

```text
Topic processing.decision == FAILED
```

拒绝：

```text
NEW_TOPIC EXISTING_TOPIC TOPIC_UPDATE
UNRELATED SKIPPED
不存在 processing → NOT_FOUND（禁止自动创建、禁止当首次执行）
Topic Engine / Sidepath disabled → ENGINE_DISABLED
Runtime 不接活 → STOPPED
MessageRecord 不存在 → MISSING_MESSAGE
```

UNRELATED / SKIPPED 属于 `SUCCESS_DECISIONS`，**不是** retryable。

---

## 5. 最小服务

文件：`topic_retry.py`

```text
TopicRetryService.retry_topic(...)
retry_topic(..., service=...)
```

流程：

```text
sidepath.enabled / engine.enabled
load processing → NOT_FOUND?
Runtime STOPPED?
eligibility FAILED?
load MessageRecord
audit REQUESTED
TopicSidepath.process_record_and_fanout  恰好一次
audit SUCCESS | FAILED
return
```

没有：

```text
Topic Retry Queue / Thread / Scheduler / cron
max_retries / backoff / retry_count
WebUI / REST / 微信命令
```

---

## 6. 复用 fan-out

`TopicSidepath` 抽出：

```text
process_record_and_fanout(record, conversation, runtime)
_apply_topic_engine_result   # FAILED / replayed 判断与审计
_fanout_topic_result         # 仅 SUCCESS 且 replayed=false
                             # 调用既有 _maybe_enqueue_*
```

worker `_process` 与 retry 共用。

```text
replayed=true → helper 根本不 fan-out
FAILED / error_code → 0 fan-out
NEW_TOPIC / EXISTING_TOPIC / TOPIC_UPDATE → 既有 allow 规则
UNRELATED / SKIPPED → allow 规则拒绝，下游 enqueue = 0
下游 enabled=false → 该路 skip，其它路照常
```

不得复制：

```text
topic_result_allows_task
topic_result_allows_decision
topic_result_allows_risk
```

---

## 7. 一次一发

```text
一次显式请求 = 最多一次 TopicEngine.process_record
FAILED 后不自动再跑
SUCCESS 后再请求 = REJECTED，Extractor delta = 0
```

Retry 不强迫 `NEW_TOPIC`。Extractor 返回什么，processing 就写什么。

---

## 8. Runtime / enabled

与 P6-G2 一致：

```text
is_accepting_work() == false
（STOPPING / STOPPED / ERROR / STARTING）
→ STOPPED，不跑 Topic LLM
```

```text
TOPIC_ENGINE_ENABLED=false 且无 DI
→ ENGINE_DISABLED
不得偷偷构造 enabled=True 的 Engine
测试可以依赖注入启用 Engine / Sidepath
```

---

## 9. 审计

```text
TOPIC_RETRY_REQUESTED
TOPIC_RETRY_SUCCESS
TOPIC_RETRY_FAILED
TOPIC_RETRY_REJECTED
```

字段：

```text
conversation_id
message_id
version
previous_status
result
topic_id
decision
error_code
```
