# P4-G2 Readiness

> 日期：2026-09-21  
> 阶段：P4-G1 完成后的技术就绪判断  
> **本文件不授权接真机，不实施 G2。**

---

## 唯一问题

> P4-G1 是否具备进入「Topic 成功后触发 Task Engine」的技术条件？

**是。离线技术条件已具备。生产挂钩仍未启用，必须等待单独的 P4-G2 指令。**

---

## 检查清单

| 项 | 状态 |
|---|---|
| Task Store | **PASS**。独立 JSON；`conv_*` / `topic_*`；删除方法已有 |
| Task Extractor | **PASS**。独立 Prompt + 独立 parser；与 Chat / Topic 隔离 |
| Task Engine | **PASS**。离线 `process_record(conversation, topic, message)` |
| Evidence | **PASS**。`TaskMessageLink`；无 Evidence 不写 Task；必须含当前消息 |
| Assignee rule | **PASS**。只存 `assignee_text`；禁止发送者默认负责人；无主不建 |
| Due rule | **PASS**。只存 `due_text`；`due_at=""`；不换算「明天」 |
| Idempotency | **PASS**。成功 Processing 跳过；FAILED 可重试 |
| Failure Isolation | **PASS**。Task FAILED 不改 Topic / Chat / 微信 |
| Offline Cases T01–T10 | **PASS** |
| Regression P0/P1/P2/P3 | **PASS**（39 / 59 / 103 基线保持） |

---

## G2 仍不具备、不得在本报告里做的事

```text
不得修改 topic_sidepath.py
不得修改 listener.py
不得打开生产 TASK_ENGINE_ENABLED
不得打开生产 TOPIC_ENGINE_ENABLED
不得发微信
不得进入 Risk / Decision
```

G2 若获授权，建议形态（仅备忘，不实施）：

```text
Topic Engine 成功且 topic_id 非空
  → 同一隔离边界内 try/except 调用 TaskEngine.process_record
  → Task 失败只写 Task FAILED
```

前提：单独指令解冻 Side-path 或 listener。  
G1 已证明离线入口不依赖改 P3 决策语义。

---

## 结论

```text
P4-G1 离线技术就绪        = YES
Production Task side-path = NOT ENABLED
P4-G2                     = WAITING FOR INSTRUCTION
```
