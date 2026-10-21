# P4-G1 测试报告

> 日期：2026-09-21  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 权威 fixture：`tests/fixtures/task_engine/zhiqun_task_cases.json`（未替换、未放宽语义）  
> Extractor：离线 `HeuristicTaskExtractor`（G1 允许；真实模型联调不是 G1 必须项）

```text
.\.venv\Scripts\python.exe -m unittest ^
  tests.test_task_store ^
  tests.test_task_extractor ^
  tests.test_task_engine_offline
```

结果：**50 tests, OK**

---

## CASE-T01～T10

| CASE | 结果 | 观察 |
|---|---|---|
| **CASE-T01** | **PASS** | 1 个 OPEN Task；`assignee_text=王强`；`due_text` 含「今天 16 点前」；负责人不是周敏；`status=OPEN`；`due_at=""`；规则+回归未拆成两个 Task |
| **CASE-T02** | **PASS** | 「需要再跑一次回归。」→ 0 Task，`UNRELATED` |
| **CASE-T03** | **PASS** | 1 Task；`assignee_text=李娜`；`due_text=""`；`status=OPEN` |
| **CASE-T04** | **PASS** | 2 个 NEW_TASK：王强→供应商编码，李娜→权限；均绑定 `topic_demo_erp`；未新建 Topic |
| **CASE-T05** | **PASS** | NEW_TASK=0，TASK_UPDATE=1，`task_id=task_demo_nullrule`；OPEN 总数仍 1；`due_text` 含「17 点」 |
| **CASE-T06** | **PASS** | 「收到。」预筛 `UNRELATED`/`SKIPPED`，0 新 Task，未调 Extractor，未改已有 Task |
| **CASE-T07** | **PASS** | 「ERP 同步失败了。」问题事实 → 0 Task，`UNRELATED` |
| **CASE-T08** | **PASS** | 「我建议…异常池」→ 0 新 Task，未把建议抽成待办 |
| **CASE-T09** | **PASS** | NEW_TASK=0；决策为 `TASK_UPDATE`（允许）；assignee 仍为王强，未写成周敏；未新建「按方案做」 |
| **CASE-T10** | **PASS** | 「空值规则已经处理完了。」NEW_TASK=0，DONE=0，`status` 仍 OPEN，`UNRELATED` |

可选 **CASE-T09b**：无已有 Task 时单独「按照这个方案做」→ 0 Task，`UNRELATED`。**PASS**（不阻塞 T09）。

预筛补充：「收到，16 点前给结果」**不是**纯 ack，进入 Extractor。**PASS**。

---

## Failure Injection

| 注入 | 结果 | 观察 |
|---|---|---|
| Extractor timeout | **PASS** | `FAILED` / `EXTRACTOR_TIMEOUT`；无脏 Task；Topic fixture 不变 |
| Extractor exception | **PASS** | `FAILED`；Topic 不变 |
| invalid JSON | **PASS** | `JSON_PARSE_ERROR`；无 Task |
| invalid task_id | **PASS** | `INVALID_TASK_ID`；不新建该 id |
| invalid evidence id | **PASS** | `INVALID_EVIDENCE_ID`；不写 Task |
| invalid assignee_text | **PASS** | `INVALID_ASSIGNEE`；不默默写入 |
| Prompt missing | **PASS** | `EXTRACTOR_PROMPT_NOT_FOUND`；不调 LLM |
| Prompt empty | **PASS** | `EXTRACTOR_PROMPT_EMPTY`；不调 LLM |
| Store write failure | **PASS** | `STORE_WRITE_FAILURE`；无脏 Task；Topic 不变 |
| 进程不崩 | **PASS** | `process_record` 不向调用方抛异常，`isolated=True` |
| FAILED 可重试 | **PASS** | 同 version 重试后 `NEW_TASK` 成功 |

无 Topic Evidence 的 Message → `TOPIC_EVIDENCE_MISSING`，不猜 Topic。**PASS**。

---

## Idempotency

| 场景 | 结果 |
|---|---|
| 相同 Message 重放 → Task 不重复 | **PASS** |
| 一条 Message 两 Task 重放 → 仍两条 | **PASS** |
| TASK_UPDATE 重放 → 不重复 Link / 不重复改 due | **PASS** |
| 成功 Processing → skip | **PASS** |
| FAILED → 可重试成功 | **PASS** |

Store 层另证：成功 Processing 重放保留原记录；FAILED 可覆盖为成功。

---

## Prompt Isolation

| 项 | 结果 |
|---|---|
| `TASK_EXTRACTOR.md` 独立存在，含 NEW_TASK / TASK_UPDATE / UNRELATED | **PASS** |
| `DEFAULT_EXTRACTOR_PROMPT_NAME = TOPIC_EXTRACTOR` 未改 | **PASS** |
| QIYE / 企业_1 无 Task schema | **PASS** |
| `TOPIC_EXTRACTOR.md` 无 NEW_TASK / assignee_text，仍禁止 tasks | **PASS** |
| `TASK_EXTRACTOR` 不在 Chat `list_prompt_names()` | **PASS** |
| 独立 parser 保留 `assignee_text` / `due_text`，剥离 `due_at` / `assignee_id` / `status` | **PASS** |
| `TASK_COMPLETE` / `DONE` decision 判非法 | **PASS** |
| Client：`store_context=false`，`temperature=0.2`，`max_tokens=1600` | **PASS** |

---

## Source Code Send Guard

`task_engine.py` / `task_extractor_client.py` / `task_store.py` 源码级断言：

```text
send_reply(
wx.SendMsg(
SendMsg(
from message.listener
```

均不出现。`engine_source_forbids_wechat_sidepath() = True`。**PASS**

Task Engine 只写 Store + Audit。

---

## Gate 1 Store 单测（不调用 LLM）

Task 正常创建；`conversation_id`/`topic_id` 正确；无 Topic 禁止写；Link 不重复；Processing 重放跳过；FAILED 可重试；同 Message 多 Task ID 不冲突；更新不新增重复 Task；`delete_conversation_task_data` 可删；不同 Conversation 隔离；v1 不能写 DONE。全部 **PASS**。

---

## 开关

```text
TASK_ENGINE_ENABLED default  = false   PASS
TOPIC_ENGINE_ENABLED default = false   PASS（未改）
未接 listener                PASS
```

---

## 结论

```text
CASE-T01..T10     = PASS
Failure Injection = PASS
Idempotency       = PASS
Prompt Isolation  = PASS
Source Send Guard = PASS
Task Store        = PASS
```

未删测、未 skip、未放宽 P4 fixture 语义。
