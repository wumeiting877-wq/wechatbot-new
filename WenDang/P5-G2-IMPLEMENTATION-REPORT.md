# P5-G2 实施报告

> 日期：2026-09-22  
> 项目：wechatbot-new  
> 阶段：**P5-G2**（Topic 成功后独立接入 Decision Engine）  
> Gate 0：`P5-G2-G0-CURRENT-STATE-AUDIT.md` = PASS（不必改 listener）

```text
P0 / P1 / P2     = CLOSED（本轮未解冻）
P3 Topic Engine  = COMPLETE
P4 Task Engine   = COMPLETE
P5-G0 / G1       = COMPLETE
P5-G2            = COMPLETE（Gate 1 + Gate 2 + 真机 DJ-R1～R14 + Gate 4 回归）
```

未改 Trigger / Self / Dedupe / Outbound / `evaluate_inbound` / Topic decision schema / Task Engine / Chat Prompt / Topic Prompt / Task Prompt。  
模块默认 `TOPIC_ENGINE_ENABLED` / `TASK_ENGINE_ENABLED` / `DECISION_ENGINE_ENABLED` 仍为 **false**。未写生产长期开启指令。未实现 Risk。

---

## 1. 新增文件

```text
decision_sidepath.py
tests/test_decision_sidepath.py
tests/test_decision_live_adapter.py
```

文档：

```text
WenDang/P5-G2-G0-CURRENT-STATE-AUDIT.md
WenDang/P5-G2-IMPLEMENTATION-REPORT.md
WenDang/P5-G2-AUTOMATED-TEST-REPORT.md
WenDang/P5-G2-REAL-LLM-TEST-REPORT.md
WenDang/P5-G2-LIVE-WECHAT-TEST-REPORT.md
WenDang/P5-G2-REGRESSION-REPORT.md
WenDang/P5-G2-DEFERRED-ISSUES.md
WenDang/P5-G2-CLOSURE-REPORT.md
```

未新增 listener 第三条 Decision Side-path。未进入 Risk。

## 2. 修改文件

| 文件 | 作用 |
|---|---|
| `topic_sidepath.py` | **最小解冻**：`__init__` 可注入 `decision_sidepath`；Topic 成功路径末尾 `_maybe_enqueue_decision`（与 Task 并列、独立 try/except）；显式注入时 `shutdown` 一并停 Decision |
| `decision_engine.py` | 模块注释改为 G2 由 Side-path 投递；`engine_source_forbids_wechat_sidepath` 纳入 `decision_sidepath` 源码扫描。**未改** `process_record` 语义 |

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
task_engine.py
task_store.py
task_sidepath.py
task_extractor_client.py
config.local.json
```

`DEFAULT_EXTRACTOR_PROMPT_NAME` 仍为 `TOPIC_EXTRACTOR`。  
Decision Engine 仍显式 `resolve_extractor_prompt("DECISION_EXTRACTOR")`。

## 3. 挂钩位置

```text
listener
  → try_enqueue_topic_sidepath          # P3-G2 已有，本轮未再插入
      → Topic worker
          → TopicEngine.process_inbound
          → TOPIC_PROCESS_SUCCESS
          ├→ try_enqueue_task_after_topic       # P4-G2 已有
          └→ try_enqueue_decision_after_topic   # 本轮新增，失败隔离
                → Decision queue put_nowait
                → Decision worker
                → DecisionEngine.process_record(conversation, topic, message)
```

Topic 成功且允许触发 Decision 的 decision：

```text
NEW_TOPIC / EXISTING_TOPIC / TOPIC_UPDATE
且 topic_id != null
```

禁止触发：

```text
UNRELATED / SKIPPED / FAILED / DISABLED / CONVERSATION_NOT_RESOLVED / 无 topic_id
```

`conversation` 来自 Topic worker payload（已 `resolve_topic_conversation`）。  
`topic` / `message` 通过 `TopicStore.get_topic` / `get_message` 读取。不改 listener。  
Decision **不**读取 Task 结果，**不**复用 Task queue。

## 4. 为什么不同步等 Decision LLM

Topic worker concurrency=1。Decision Extractor timeout 默认 20s。同步等待会让 Topic 队列积压、Stop 变慢。

因此：

```text
Topic 成功 → put_nowait（通常 < 1ms）→ Topic worker 继续
Decision LLM 在独立 DecisionSidepathWorker 执行
```

Queue：`queue.Queue(maxsize=32)`，单 worker。满则 `DECISION_QUEUE_FULL`，丢弃本次 Decision，不影响 Topic / Task / Chat。

## 5. 三开关独立

```text
topic_engine.py      TOPIC_ENGINE_ENABLED    = False
task_engine.py       TASK_ENGINE_ENABLED     = False
decision_engine.py   DECISION_ENGINE_ENABLED = False

runtime_control/DECISION_ENGINE_ENABLED  >  环境变量  >  模块常量
```

| Topic | Decision | 结果 |
|---|---|---|
| false | true | 无 Topic 输入 → Decision 不运行 |
| true | false | Topic 正常；Task 按自己开关；Decision enqueue=0 |
| true | true | Topic → Decision；Task 开关不影响 Decision |

DS8 证明：Task worker exception / FAILED 时 Decision 仍可 enqueue 并成功写入。

## 6. Decision 不得发微信 / 不得改 Topic / Task

`decision_engine.py` / `decision_store.py` / `decision_extractor_client.py` / `decision_sidepath.py` 源码均无：

```text
send_reply(
wx.SendMsg(
SendMsg(
from message.listener
```

Decision 只写 Decision Store + Audit。v1 不写 SUPERSEDED / CANCELLED 状态，不原地覆盖旧 `decision_text`。

## 7. Stop

`DecisionSidepath.attach_runtime` 注册 `register_stop_hook` / `register_emergency_hook`。  
`shutdown` 置停并清空 bounded queue。  
Topic `shutdown` 在显式注入时一并停 Decision。  
不要求强杀正在执行的 LLM 线程；Stop 后新微信业务不得再写成 Decision。
