# P6-G1 Gate 1 — Replay Trace（修复前）

> 日期：2026-09-22  
> 离线探针：同一 Inbound → `TopicSidepath._process` 两次。不经 P0。不连真机 / Real LLM。  
> 完整对照：`P6-G1-REPLAY-TRACE.md`

方法：对同一 `InboundMessage`（`platform_message_id=pid-p6g1-m1`）连续 `_process` 两次。  
Extractor = Heuristic + call counter。Sidepath 全部 `enabled=True`（测试覆盖，模块常量仍为 false）。

---

## 第一次（MessageRecord M1，NEW_TOPIC）

```text
Topic Extractor          = 1
Topic Store processing   = 1  decision=NEW_TOPIC
Task enqueue             = 1
Decision enqueue         = 1
Risk enqueue             = 1
replayed                 = false
```

## 第二次（同一 MessageRecord，已有 SUCCESS）

```text
Topic Extractor          = 1   (delta 0)
Topic Store processing   = 1   (未新增)
Task enqueue             = 2   (delta +1)
Decision enqueue         = 2   (delta +1)
Risk enqueue             = 2   (delta +1)
下游 Extractor           = 0 新调用
下游 worker processed    = +1/+1/+1
实体 Topic/Link/Task/Risk = 不增
replayed                 = true
skipped                  = true
decision                 = NEW_TOPIC
same message_id          = true
```

---

## 结论

```text
Topic Extractor = 0 新调用
Task/Decision/Risk enqueue = 1/1/1 新入队
```

**Deferred 问题正式成立。**  
Store 未脏写不能抵消 Queue 二次 put。
