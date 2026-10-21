# P5-G1 延期事项

> 日期：2026-09-22  
> 阶段：P5-G1 COMPLETE 之后，等待 P5-G2 指令  
> 本文件只记录明确不做或留给后续 Gate 的事项。不是 BLOCKER。

---

## 本轮有意不做

| ID | 项 | 说明 |
|---|---|---|
| D1 | Decision Side-path | G2 才允许按 P4-G2 模式在 Topic 成功后 enqueue。G1 禁止改 `topic_sidepath.py` / listener |
| D2 | 真实 Decision LLM | 离线主路径使用 `HeuristicDecisionExtractor`。真实 `get_extractor_response` 联调留到 G2 |
| D3 | 真机 Decision | 不接微信，不改生产群行为 |
| D4 | Risk Engine | 禁止创建 `risk_engine.py` / `risk_store.py` / `RISK_EXTRACTOR.md`。M01 只断言 Decision 半边 |
| D5 | Decision UI / Dashboard | 规划中的决策中心页面不在 v1 |
| D6 | 自动写 SUPERSEDED 状态 | 替换关系只用 `supersedes_decision_id`；旧行保持 `RECORDED` |
| D7 | 自动 CANCELLED | v1 无取消决定状态机 |
| D8 | DECISION_UPDATE 就地改文 | 正文不可原地覆盖 |
| D9 | Decision.task_id | Decision 属于 Topic，不属于 Task |
| D10 | 跨 Topic Decision | Extractor 不得自己做 Topic 分类 |
| D11 | Reminder / 催办 / 发微信 | Decision Engine 只写 Store + Audit |
| D12 | 升 `decision_processing_version` 的批量重抽 | Prompt hash 变化默认不重跑 |

---

## 已知 LIMITATION（v1 接受）

| ID | 项 | 说明 |
|---|---|---|
| L1 | 「行。」不建 Decision | 可能漏掉极简口头同意。要支持必须升 Prompt 并新增 CASE |
| L2 | 旧 Decision 仍显示 RECORDED | 有效性靠 supersede 指针；G1 无查询 UI |
| L3 | P3 单主 Topic | 双主题消息的 Decision 全挂当前主 Topic |
| L4 | Heuristic ≠ 生产模型 | G2 必须用真实 LLM 再跑 D01～D08 |
| L5 | OPEN/RECORDED 会累积 | 与 P4 OPEN Task 同类，v1 不自动过期 |

---

## 推荐下一阶段

```text
P5-G2  Decision Side-path + Real LLM + Live
```

不要默认下一阶段同时实现 Risk。
