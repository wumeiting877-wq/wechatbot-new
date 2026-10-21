# P5-G4 实施报告

> 日期：2026-09-22  
> 项目：wechatbot-new  
> 阶段：**P5-G4**（Topic 成功后独立接入 Risk Engine + Real LLM + Live）  
> Gate 0：`P5-G4-G0-CURRENT-STATE-AUDIT.md` = PASS（不必改 listener）

```text
P0 / P1 / P2     = CLOSED（本轮未解冻）
P3 Topic Engine  = COMPLETE
P4 Task Engine   = COMPLETE
P5-G0 / G1 / G2 / G3 = COMPLETE
P5-G4            = COMPLETE
```

未改 Trigger / Self / Dedupe / Outbound / `evaluate_inbound` / Topic decision schema / Task decision schema / Decision decision schema / Chat Prompt / Topic Prompt / Task Prompt / Decision Prompt。  
模块默认 `TOPIC_ENGINE_ENABLED` / `TASK_ENGINE_ENABLED` / `DECISION_ENGINE_ENABLED` / `RISK_ENGINE_ENABLED` 仍为 **false**。未写生产长期开启指令。未实现 severity / 自动 RESOLVED / Risk 通知 / Dashboard。DJ-R8 继续 Deferred。

---

## 1. 新增文件

```text
risk_sidepath.py
tests/test_risk_sidepath.py
tests/test_risk_live_adapter.py
```

文档：

```text
WenDang/P5-G4-G0-CURRENT-STATE-AUDIT.md
WenDang/P5-G4-IMPLEMENTATION-REPORT.md
WenDang/P5-G4-AUTOMATED-TEST-REPORT.md
WenDang/P5-G4-REAL-LLM-TEST-REPORT.md
WenDang/P5-G4-LIVE-WECHAT-TEST-REPORT.md
WenDang/P5-G4-REGRESSION-REPORT.md
WenDang/P5-G4-DEFERRED-ISSUES.md
WenDang/P5-G4-CLOSURE-REPORT.md
```

未新增 listener 第四条 Risk Side-path。

## 2. 修改文件

| 文件 | 作用 |
|---|---|
| `topic_sidepath.py` | **最小解冻**：`__init__` 可注入 `risk_sidepath`；Topic 成功路径末尾 `_maybe_enqueue_risk`（与 Task / Decision 并列、独立 try/except）；显式注入时 `shutdown` 一并停 Risk |
| `risk_engine.py` | 模块注释改为 G4 由 Side-path 投递；`engine_source_forbids_wechat_sidepath` 纳入 `risk_sidepath` 源码扫描。**未改** `process_record` 语义 |
| `risk_extractor_client.py` | 注释：G4 生产路径使用本 Client。**未改** parser / timeout / `store_context=false` |
| `tests/test_risk_engine_offline.py` | G3「risk_sidepath 不存在」改为存在且隔离扫描 |
| `tests/test_decision_engine_offline.py` | Decision 仍不引用 Risk / risk_sidepath |
| `tests/test_decision_live_adapter.py` | M01：Decision 不调用 RiskEngine；临时目录无 risk_store |

未修改：

```text
message/listener.py
message/trigger.py
message/identity.py
message/dedupe.py
message/outbound.py
message/reply_format.py
bot_runtime.py
topic_engine.py
topic_store.py
topic_extractor_client.py
prompts/QIYE.md
prompts/企业_1.md
prompts/extractors/TOPIC_EXTRACTOR.md
prompts/extractors/TASK_EXTRACTOR.md
prompts/extractors/DECISION_EXTRACTOR.md
prompts/extractors/RISK_EXTRACTOR.md
task_engine.py
task_store.py
task_sidepath.py
task_extractor_client.py
decision_engine.py
decision_store.py
decision_sidepath.py
decision_extractor_client.py
config.local.json
```

`DEFAULT_EXTRACTOR_PROMPT_NAME` 仍为 `TOPIC_EXTRACTOR`。  
Risk Engine 仍显式 `resolve_extractor_prompt("RISK_EXTRACTOR")`。

## 3. 挂钩位置

```text
listener
  evaluate_inbound
  try_enqueue_topic_sidepath     # 仅此一条旁路入口
        ↓
Topic worker SUCCESS
  ├→ try_enqueue_task_after_topic      独立 Task Queue
  ├→ try_enqueue_decision_after_topic  独立 Decision Queue
  └→ try_enqueue_risk_after_topic      独立 Risk Queue
        ↓
   Risk worker → RiskEngine.process_record(conversation, topic, message)
```

Risk 运行闸门：

```text
Topic SUCCESS ∈ {NEW_TOPIC, EXISTING_TOPIC, TOPIC_UPDATE}
+ topic_id != null
+ RISK_ENGINE_ENABLED=true
```

Task / Decision 的 SUCCESS / FAILED / DISABLED **不是** Risk 闸门。

## 4. 独立 Queue

```text
queue.Queue(maxsize=32)
单 RiskSidepathWorker
put_nowait
```

Queue Full → `RISK_QUEUE_FULL` audit，丢弃本次 Risk；Topic SUCCESS 保留；Task / Decision / Chat / listener 不阻塞。  
Stop hook 复用 `register_stop_hook` / `register_emergency_hook`。

## 5. 四开关独立

```text
TOPIC_ENGINE_ENABLED
TASK_ENGINE_ENABLED
DECISION_ENGINE_ENABLED
RISK_ENGINE_ENABLED
```

读取顺序：`runtime_control` > 环境变量 > 模块常量。默认全部 **false**。

```text
TOPIC=false RISK=true  → 无 Topic 输入，Risk 不运行
TOPIC=true  RISK=false → Topic / Task / Decision 按自己开关；Risk 不写
TOPIC=true  TASK=false RISK=true → 明确 Risk 仍可 NEW_RISK，task_id=""
TOPIC=true  DECISION=false RISK=true → 明确 Risk 仍可 NEW_RISK
```

## 6. Failure Isolation

Risk timeout / HTTP / invalid JSON / empty / invalid risk_id / invalid evidence / worker exception：

```text
Risk = FAILED
无脏 Risk
Topic / Task / Decision 不变
Chat / listener 不阻塞
```

TaskStore unavailable → `candidate_tasks=[]`，Risk 继续，`task_id=""`。

## 7. 未做（禁止项）

```text
severity / severity_text
自动 RESOLVED / MITIGATED / CLOSED
Risk 自动通知 / 催办 / Dashboard
修改 DECISION_EXTRACTOR（DJ-R8 继续 Deferred）
修改 listener / Trigger
```
