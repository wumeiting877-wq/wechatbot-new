# P4 下一步实施计划（等待指令）

> 日期：2026-09-21  
> 阶段：P4-G0 **已完成，在此 STOP**  
> 本文件只划 **P4-G1** 范围。**不要在未收到实施指令时执行。**  
> 禁止自动进入真机挂钩、Risk、Decision、提醒、发微信。

---

## 1. G0 已交付

| 文件 | 内容 |
|---|---|
| `WenDang/P4-TASK-CURRENT-STATE-AUDIT.md` | 冻结基线 + 无真正 Task 能力 + Evidence 足够 |
| `WenDang/P4-TASK-DATA-MODEL-DESIGN.md` | JSON Store、字段取舍、assignee_text、due_text、Link、幂等 |
| `WenDang/P4-TASK-ENGINE-DESIGN.md` | Topic 成功后隔离旁路、1:N、不自动 DONE、不发微信 |
| `WenDang/P4-TASK-EXTRACTOR-PROMPT-DESIGN.md` | 与 Chat / Topic 隔离的 Prompt 方案与正文稿 |
| `WenDang/P4-TASK-TEST-DATASET.md` | CASE-T01～T10 |
| `WenDang/P4-TASK-GAP-REPORT.md` | 15 问 + 无 BLOCKER |
| `tests/fixtures/task_engine/zhiqun_task_cases.json` | 机器可读 fixture |

未实现引擎，未改冻结模块，未改生产群行为，未创建生产 `TASK_EXTRACTOR.md`。

开放 BLOCKER：**无**。

---

## 2. 建议的下一阶段：P4-G1（实施 + 离线验收）

目标：可在 **离线 fixture** 上跑通 Task Engine；默认不启用；不接微信；不改 P3 Topic 语义。

研究问题验收口径：

> 在已经形成的 Topic 中，离线识别工作事项：T01/T03/T04 能建，T02/T06/T07/T08 不建，T05 更新不重复，T09 不凭空补人，T10 不自动 DONE。

### Gate 0 — 现状再次确认（实施第一天，仍只读）

```text
P0/P1/P2/P3 仍 CLOSED
TOPIC_ENGINE_ENABLED 默认 false
冻结文件未出现未授权 diff
fixture 仍可读
```

若有人已改 P3 语义或出现第二套 Task 实现 → STOP，写 BLOCKER，不继续 G1。

### Gate 1 — Task Store

新增：

```text
task_store.py
```

```text
data/task_store/conversations/{conv_id}/
    tasks.json
    links.json
    processed.json
task_engine_audit.jsonl
```

只读调用 TopicStore 取 Message / Topic / TopicLink。  
禁止改 `topic_store.py`。  
不上 SQLite。

### Gate 2 — Task Extractor Prompt + Loader

新增：

```text
prompts/extractors/TASK_EXTRACTOR.md
task_extractor_client.py
```

- 正文以 G0 设计稿为准
- 使用已有 `resolve_extractor_prompt("TASK_EXTRACTOR")`
- **不改** `DEFAULT_EXTRACTOR_PROMPT_NAME`
- **不改** `QIYE.md` / `TOPIC_EXTRACTOR.md`
- 独立 ALLOWED keys；剥离 `due_at` / `TASK_COMPLETE` / risks

可选：Heuristic extractor（O1）。

### Gate 3 — Task Engine

新增：

```text
task_engine.py
tests/test_task_engine_offline.py
```

- `TASK_ENGINE_ENABLED = false`
- `enabled=True` 仅测试传入
- 流水线按引擎设计 §4
- 失败隔离；禁止微信发送符号
- **不修改** `topic_engine.py` / `topic_sidepath.py` / `listener.py`

离线入口：`process_record(conversation, topic, message)` 或等价；测试自己把 fixture 灌进两个 Store。

### Gate 4 — Offline Fixture

以 `tests/fixtures/task_engine/zhiqun_task_cases.json` 为权威期望。  
CASE-T01～T10 全过。T09：禁止 NEW，允许 UPDATE 或 UNRELATED。

### Gate 5 — Regression

```text
P4 Task 离线 CASE
P3 Topic 离线 + sidepath 单测
P0 单测
P1/P2 单测
```

不跑真机微信。不打开 Topic/Task 生产开关。

---

## 3. 允许的最小修改 vs 禁止

### 允许新增

```text
task_store.py
task_engine.py
task_extractor_client.py
prompts/extractors/TASK_EXTRACTOR.md
tests/test_task_store.py          （如需要）
tests/test_task_engine_offline.py
tests/fixtures/task_engine/       （已有 G0 fixture，G1 可补期望）
```

### 禁止修改

```text
message/identity.py
message/dedupe.py
message/outbound.py
message/trigger.py
message/reply_format.py
message/listener.py
bot_runtime.py
topic_store.py
topic_engine.py
topic_sidepath.py
topic_extractor_client.py
prompts/QIYE.md
prompts/企业_1.md
prompts/extractors/TOPIC_EXTRACTOR.md
config.local.json 内塞 TASKS
recurring_reminders.json 当 Task 存储
```

`conversation_store.py` / `agent_store.py`：G1 **默认不改**。Extractor 文件名 loader 已够用。

---

## 4. G1 验收门槛（离线）

```text
CASE-T01  1 OPEN Task，王强，due_text 含 16 点，负责人不是周敏
CASE-T02  0 Task
CASE-T03  1 Task，李娜，due 空
CASE-T04  2 Task
CASE-T05  1 Task，due 含 17 点，不是两条
CASE-T06  0 新 Task
CASE-T07  0 Task
CASE-T08  0 新 Task
CASE-T09  0 新 Task
CASE-T10  仍 OPEN，无 DONE
Extractor 抛错时 Topic fixture 不被改写
无 send_reply / wx.SendMsg
P0 / P1 / P2 / P3 回归仍过
TOPIC_ENGINE_ENABLED 默认仍 false
TASK_ENGINE_ENABLED 默认 false
```

不验收：真机群、绝对 `due_at`、自动催办、Risk/Decision、listener 挂钩。

---

## 5. 再下一阶段（不要现在做）

| 阶段 | 内容 | 前提 |
|---|---|---|
| P4-G2（需新指令） | 可选：Topic 成功后挂钩 Task；真机只入库不回复 | G1 PASS；**单独授权** 改 sidepath 或 listener |
| P4 Risk / Decision | 禁止夹带 | Task 离线稳定 |
| Reminder 融合 | 禁止 | 提醒仍是另一系统 |

G1 之后生产群不得因 Task 多发一条微信。

---

## 6. 实施顺序建议（收到 G1 指令后）

1. Gate 0 只读确认  
2. TaskStore  
3. Prompt 文件 + Task Extractor client  
4. TaskEngine 离线可跑  
5. CASE fixture 单测  
6. 回归 P0/P1/P2/P3  
7. **STOP**。等待是否做 G2 挂钩

先离线、后挂钩。挂钩不是 G1 工作。

---

## 7. STOP

```text
P4-G0 STATUS = COMPLETE
Task Engine 未实施
Risk Engine 未开始
Decision Engine 未开始
P4-G1 = WAITING FOR INSTRUCTION
```
