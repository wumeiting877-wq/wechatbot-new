# P3-G2 Readiness

> 日期：2026-09-21  
> 只回答：G1 是否具备进入 G2 的技术条件。  
> **本文件不实施 G2。**

---

## 结论

```text
G1 具备进入 G2 的技术条件 = YES
Production WeChat side-path = NOT ENABLED
WAIT FOR P3-G2 INSTRUCTION
```

G2 仍需要单独实施指令，才允许最小插入 `message/listener.py`。即使具备条件，也不得因为本文件自动接线。

---

## 检查表

| 能力 | 状态 | 说明 |
|---|---|---|
| Topic Store | READY | 独立 JSON store，按 `conv_*` 隔离，可级联删除 |
| Extractor | READY | `prompts/extractors/TOPIC_EXTRACTOR.md` + `resolve_extractor_prompt`，与 Chat 隔离 |
| Offline Engine | READY | 完整流水线可 replay fixture，不依赖 listener |
| Evidence | READY | TopicMessageLink N:N，主样本必含消息可追溯 |
| Idempotency | READY | processing 成功跳过；FAILED 可重试；重放不双计 |
| Failure Isolation | READY | 异常停在 Engine 边界；无 send_reply / wx.SendMsg |
| Tests | READY | 离线 39 PASS；P0 59 PASS；P1/P2 103 PASS |

---

## G2 仍未做（有意）

- `message/listener.py` 未调用 Topic Engine
- `TOPIC_ENGINE_ENABLED` 默认 `false`
- 未改 Trigger，未把 Topic 映射成回复
- 未对生产群做真机理解验收
