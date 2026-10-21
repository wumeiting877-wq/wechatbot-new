# P5-G4 Gate 0：当前真实源码与进程审计

> 日期：2026-09-22  
> 性质：**READ ONLY**（本文件写完前未修改业务代码）。  
> 依据：`P5-G3-IMPLEMENTATION-REPORT.md`、`P5-G3-TEST-REPORT.md`、`P5-G3-REGRESSION-REPORT.md`、`P5-G3-DEFERRED-ISSUES.md`、`P5-G4-READINESS.md`、`P5-G2-G0-CURRENT-STATE-AUDIT.md`、真实源码与本机进程。

```text
P0 STATUS          = CLOSED
P1 STATUS          = CLOSED
P2 STATUS          = CLOSED
P3 Topic Engine    = COMPLETE
P4 Task Engine     = COMPLETE
P5-G0 / G1 / G2 / G3 = COMPLETE
P5-G4              = NOT STARTED
```

---

## 冻结基线核对

| 项 | 文档 | 本轮核对 |
|---|---|---|
| P0 | CLOSED | 保持。禁止改 identity / dedupe / outbound / trigger / `evaluate_inbound` |
| P1 / P2 | CLOSED | 保持。禁止改 Chat Prompt 正文 |
| P3-G2 | COMPLETE | `topic_sidepath.py` 已在 `listener` 的 `evaluate_inbound` 之后挂钩 |
| P4-G2 | COMPLETE | Topic 成功后 `_maybe_enqueue_task` → 独立 Task Queue |
| P5-G2 | COMPLETE | Topic 成功后 `_maybe_enqueue_decision` → 独立 Decision Queue |
| P5-G3 | COMPLETE，Risk Offline 68 OK | `risk_store.py` / `risk_engine.py` / `risk_extractor_client.py` / `RISK_EXTRACTOR.md` 存在 |
| G3 回归 | Decision 57 / P4 50 / P3 39 / P0 59 / P1-P2 103 | 文档记录；Gate 1 后再实测 |
| G4 就绪 | `P5-G4-READINESS.md` = YES（离线） | 与源码一致：Risk Engine 离线可用，**生产未挂钩** |
| DJ-R8 | NON-BLOCKER / DEFERRED | **禁止**为 Risk 改 `DECISION_EXTRACTOR` |
| D-N2 | 疑似双 listener | 本轮 Gate 0 增加单 Bot / 单 listener 进程核对 |

G3 文档与真实源码 **没有严重不一致**。不构成 BLOCKER。

```text
G4 Gate 0 = PASS
允许进入 Gate 1（只挂 Risk Side-path，Heuristic / Mock，不接真实 LLM，不接真机）
不必修改 listener.py / trigger.py / bot_runtime.py / InboundMessage
不必修改 Topic / Task / Decision decision schema
```

---

## 单 Bot / 单 listener 进程核对（G4 额外 Gate 0）

审计时刻：2026-09-22 15:51（status.json `updated_at` 对齐）。

### 进程树

| PID | 角色 | CommandLine | 判定 |
|---|---|---|---|
| 27624 | WebUI | `.venv\Scripts\python.exe config_editor.py` | 配置页，不是 Bot |
| 15396 | WebUI 子解释器 | 系统 `python.exe config_editor.py`（父=27624） | 仍是 WebUI |
| 9092 | Bot 启动包装 | `.venv\Scripts\python.exe bot.py`（父=15396） | 同一 Bot 树的 wrapper |
| 20324 | Bot worker | 系统 `python.exe bot.py`（父=9092） | **唯一 Bot 身份 PID**（与 P5-G2 真机 PID 相同） |

未发现第二个独立项目目录的 `bot.py`。Edge / Chrome `--top-chrome-webui` 渲染进程不是微信 Bot。

### runtime_control

```text
state                  = STOPPED
wechat                 = disconnected
ai                     = ok
pid                    = 20324
TOPIC_ENGINE_ENABLED   = false
TASK_ENGINE_ENABLED    = false
DECISION_ENGINE_ENABLED= false
RISK_ENGINE_ENABLED    = （文件不存在，模块默认 false）
today_received         = 2
today_replied          = 2
dropped_stopped        = 1
```

与 P5-G2 Closure 一致：Bot 已 STOP；开关默认 false。  
残留：G2 STOP 后 `bot.py` 进程树仍在（9092 / 20324），但 `state=STOPPED` 且 `wechat=disconnected`，**当前不接受新业务**。这不是第二套并行 listener。

真机启动前必须先结束该残留树，再只拉起 **一个** `bot.py`，避免 D-N2 再现。本轮 **不改** `listener.py` / `bot_runtime.py`。

```text
Single Bot Process = PASS
Single Listener    = PASS
```

| 检查项 | 结果 |
|---|---|
| 1. 多个 Python bot 进程 | 同一棵树：wrapper 9092 + worker 20324。**不是**两个独立 Bot |
| 2. 两个 listener 同时监听同一微信 | **否**。wechat=disconnected；STOP 后不 admit |
| 3. 残留 WebUI | **有**（27624 / 15396），只是配置页 |
| 4. STOP 后未退出的 worker | **有残留进程**，但 STOPPED / disconnected |
| 5. 同一 inbound 进入两个 Topic Extractor | 当前 STOPPED，不会发生。真机前清残留即可 |
| 6. 两个相同项目实例 | **否**。仅 `F:\XM\X_9 wechatbot-new\wechatbot-new` |
| 7. 当前 Bot PID | **20324** |
| 8. 其它 PID | WebUI / 浏览器，不是 Bot |

---

## 1. Topic success 后当前 Task / Decision 如何并列 enqueue？

`topic_sidepath.py` 单 worker `_loop` → `_process(payload)`：

```text
result = engine.process_inbound(...)
TOPIC_PROCESS_SUCCESS
self._maybe_enqueue_task(payload, result)
self._maybe_enqueue_decision(payload, result)
```

两者各自独立 `try/except`，调用：

```text
try_enqueue_task_after_topic(...)      → Task Queue (maxsize=32) + Task worker
try_enqueue_decision_after_topic(...)  → Decision Queue (maxsize=32) + Decision worker
```

Topic worker 只 `put_nowait`，**看不到** Task / Decision 的 SUCCESS / FAILED。  
当前成功路径 **没有** Risk 调用。`risk_sidepath.py` 尚不存在。

---

## 2. 是否可在同一 fan-out 点增加 Risk？

**能。** 推荐在 `_maybe_enqueue_decision` 之后（或并列）增加 `_maybe_enqueue_risk`，独立 `try/except`：

```text
Topic success
    ├→ try_enqueue_task_after_topic
    ├→ try_enqueue_decision_after_topic
    └→ try_enqueue_risk_after_topic
```

禁止挂在 Task SUCCESS 或 Decision SUCCESS 之后。  
不必改 listener。

---

## 3. 是否无需修改 listener？

**是。** `message/listener.py` 只调用 `try_enqueue_topic_sidepath`。  
Risk 从 Topic worker 成功路径 fan-out，与 Task / Decision 同一模式。

---

## 4. RiskEngine 入口是否仍是 `process_record(conversation, topic, message)`？

**是。** `risk_engine.RiskEngine.process_record(conversation, topic, message) -> EngineResult`  
G3 离线已验证。G4 Side-path worker 应直调此入口，不改语义。

---

## 5. Topic Store 是否能补全 Topic + MessageRecord？

**能。** 不必解冻 `topic_store.py`：

```text
TopicStore.get_topic(conversation_id, topic_id)
TopicStore.get_message(conversation_id, message_id)
```

`topic_engine.EngineResult` 已有 `decision` / `topic_id` / `message_id` / `conversation_id`。

---

## 6. TaskStore 是否可以可选读取 OPEN Tasks？

**能。** `RiskEngine._read_candidate_tasks` 已实现：`task_store is None` → `[]`；`list_open_tasks` 失败 → `[]` + audit `CANDIDATE_TASKS_UNAVAILABLE`，**不升级为 Risk FAILED**。

---

## 7. TaskStore 失败时是否能继续 Risk？

**能。** G3 `test_taskstore_unavailable_does_not_block_risk` 已 PASS。G4 不得把 TaskStore 变成运行闸门。

---

## 8. 是否需要独立 Risk Queue？

**需要。** 禁止复用 Task Queue / Decision Queue。  
推荐：`queue.Queue(maxsize=32)` + 单 `RiskSidepathWorker` + `put_nowait`。  
Queue Full → `RISK_QUEUE_FULL` audit，丢弃本次 Risk，保留 Topic / Task / Decision / Chat。

---

## 9. Stop hook 模型是否可以复用？

**能。** `DecisionSidepath.attach_runtime` → `register_stop_hook` / `register_emergency_hook`。  
Risk 复用同一模型：Stop 后不接受新 Risk、清空队列、不写新业务。  
禁止改 `bot_runtime.py`。

---

## 10. 是否无需修改 Topic / Task / Decision decision schema？

**无需修改。**

Risk 唯一运行闸门：

```text
Topic SUCCESS ∈ {NEW_TOPIC, EXISTING_TOPIC, TOPIC_UPDATE}
+ topic_id != null
+ RISK_ENGINE_ENABLED=true
```

禁止：UNRELATED / SKIPPED / FAILED / DISABLED / CONVERSATION_NOT_RESOLVED / 无 topic_id。  
Task / Decision 的 SUCCESS / FAILED / DISABLED **不是** Risk 闸门。

---

## STOP 条件检查

| 条件 | 是否出现 |
|---|---|
| 必须修改 listener | **否** |
| 必须修改 Trigger | **否** |
| 必须改变 Topic / Task / Decision decision | **否** |
| 必须 Task SUCCESS 才能 Risk | **否**（fan-out 在 Topic worker，看不到 Task 结果） |
| 必须 Decision SUCCESS 才能 Risk | **否** |
| 无法保证 Single Bot / Single Listener | **否**（PASS；真机前清残留进程） |

**不必生成 `P5-G4-BLOCKER-REPORT.md`。**

---

## 本轮允许改动边界（Gate 1 起）

```text
新增  risk_sidepath.py
新增  tests/test_risk_sidepath.py
新增  tests/test_risk_live_adapter.py

最小解冻 topic_sidepath.py
  __init__ 可注入 risk_sidepath
  Topic 成功路径并列 _maybe_enqueue_risk
  显式注入时 shutdown 一并停 Risk

risk_engine.py 仅源码 guard / 注释（纳入 risk_sidepath 扫描）
G3 时代「risk_sidepath.py 不存在」断言改为：Decision 不调用 Risk；Risk Side-path 存在且隔离

禁止改 listener / Trigger / Topic Engine / Task Engine / Decision Engine 语义
禁止改 DECISION_EXTRACTOR / TASK_EXTRACTOR / TOPIC_EXTRACTOR / Chat Prompt
禁止 severity / 自动 RESOLVED / 自动通知
```

DJ-R8 继续 Deferred。不重开 Decision 语义。
