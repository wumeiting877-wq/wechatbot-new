# P8-G2 Closure Report

> 日期：2026-09-23  
> 状态：COMPLETE

---

## 1. 结论

自然问法在高置信规则未命中、且候选门通过时，进入独立 Query Intent Classifier。分类器只返回枚举。答案仍由 P8-G1 Query Service 读当前会话 Store，再由 Formatter 生成。

常见规则查询的分类器调用数是 0。

## 2. 硬门槛

```text
P8-G1 规则继续优先
常见 Query = 0 classifier call
未命中的自然 Query → classifier → 严格 enum → Query Service → Store → Formatter
Classifier = 0 answer generation
Classifier = 0 Store access
OUT_OF_SCOPE / Command / Identity Query 不会被 classifier 放宽
Classifier failure 不进 Topic 旁路，不进 Chat
Query 仍只读当前 Conversation.id
Query 仍不写 Store
Query 仍不进 Chat
Non-Live：旧 665 PASS，合计 690 PASS
4 Engine flags = false
```

没有触发 STOP。不需要改 Store schema、Chat history、memory、跨会话、Query Queue、P0 去重或 Engine schema。失败路径不是放回 Topic 旁路。

## 3. 证据

```text
tests.test_p8g2_query_intent          25 OK
tests.test_p8g1_collaboration_query   42 OK
Non-Live discover                     690 OK，排除 Real Extractor 42 条
```

文档：

```text
WenDang/P8-G2-CURRENT-STATE-AUDIT.md
WenDang/P8-G2-CLASSIFIER-CALL-PATH-AUDIT.md
WenDang/P8-G2-HYBRID-INTENT-DESIGN.md
WenDang/P8-G2-IMPLEMENTATION-REPORT.md
WenDang/P8-G2-TEST-REPORT.md
WenDang/P8-G2-REGRESSION-REPORT.md
WenDang/P8-G2-DEFERRED-ISSUES.md
WenDang/P8-G2-LIVE-CLASSIFIER-SMOKE.md
WenDang/P8-G2-CLOSURE-REPORT.md
```

## 4. 停止在这里

不进入：

```text
MY_TASKS 身份映射
负责人身份映射
写 Command 落库
跨会话 Query
Query Queue
Reminder
自动 Retry
新的业务 Engine
```

等待下一步指令。
