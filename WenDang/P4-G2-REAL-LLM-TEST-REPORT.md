# P4-G2 真实 LLM 测试报告

> 日期：2026-09-21  
> 必须区分 Heuristic 与真实 MODEL。禁止记录 API Key。

---

## Heuristic（Gate 1，非本轮新语义）

`tests.test_task_engine_offline`：**29 PASS**（计入 P4 Offline 50）  
`tests.test_task_sidepath`：**13 PASS**（挂载语义）

T01～T10 在 Heuristic 下已由 P4-G1 证明。本轮 Gate 2 必须用真实 MODEL 再跑。

---

## 真实 MODEL 调用链

```text
prompts/extractors/TASK_EXTRACTOR.md
        ↓
TaskExtractorClient
        ↓
llm_client.get_extractor_response
        ↓
生产 MODEL + 主模型 client
        ↓
TaskEngine.process_record
```

Chat 仍走 `get_deepseek_response` + `QIYE.md`。未改 Chat 模型行为。

| 项 | 值 |
|---|---|
| model name | `deepseek-v4-flash` |
| prompt name | `TASK_EXTRACTOR` |
| prompt hash | `76efbe59a2a5d932de0814c2712ddaffa8a14c55df4364c863862e6918009050` |
| temperature | 0.2 |
| max_tokens | 1600 |
| timeout | 20s（独立 `TASK_EXTRACTOR_TIMEOUT_SEC`） |
| store_context | false |

未记录 Key / Authorization / `.env`。

命令：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_task_live_adapter.RealTaskExtractorTests -v
```

结果：**11 tests, OK**，约 60s。

隔离 + 失败注入（不调真实模型）：

```text
.\.venv\Scripts\python.exe -m unittest ^
  tests.test_task_live_adapter.TaskExtractorIsolationTests ^
  tests.test_task_live_adapter.TaskFailurePreservesTopicTests -v
```

结果：**12 tests, OK**。

---

## T01～T10（真实模型）

| CASE | 输入要点 | 结果 | 观察 |
|---|---|---|---|
| **T01** | 王强今天 16 点前把空值处理规则做完，再跑一次回归 | **PASS** | 1 Task；assignee=王强；due 含「16 点」；不是周敏 |
| **T02** | 需要再跑一次回归 | **PASS** | 0 Task |
| **T03** | 李娜把权限问题修一下 | **PASS** | 1 Task；李娜；due 空 |
| **T04** | 王强处理供应商编码，李娜修权限 | **PASS** | 2 Tasks；均绑 `topic_demo_erp` |
| **T05** | 改到 17 点前 | **PASS** | TASK_UPDATE；NEW=0；OPEN 仍 1；due 含「17 点」 |
| **T06** | 收到 | **PASS** | 0 新 Task |
| **T07** | ERP 同步失败了 | **PASS** | 0 Task（问题事实） |
| **T08** | 我建议…先进异常池 | **PASS** | 0 NEW_TASK |
| **T09** | 可以，先按照这个方案做… | **PASS** | NEW_TASK=0；未把周敏写成负责人 |
| **T10** | 空值规则已经处理完了 | **PASS** | status 仍 OPEN；DONE=0 |

每条真实跑都断言 Topic JSON 快照不变。

---

## 失败注入（Topic 必须保留）

| 注入 | 结果 | error_code |
|---|---|---|
| timeout | **PASS** | `EXTRACTOR_TIMEOUT` |
| HTTP error | **PASS** | `EXTRACTOR_EXCEPTION` |
| invalid JSON | **PASS** | `JSON_PARSE_ERROR` |
| empty output | **PASS** | `JSON_PARSE_ERROR` / empty |
| invalid task_id | **PASS** | `INVALID_TASK_ID` |
| invalid assignee | **PASS** | `INVALID_ASSIGNEE` |
| invalid evidence | **PASS** | `INVALID_EVIDENCE_ID` |

全部：`Task=FAILED`，`isolated=True`，无脏 Task，Topic / Link 快照不变，worker / `process_record` 不崩。

---

## Gate 2 判定

未出现：问题事实→Task、建议→Task、大量无负责人 Task、完成陈述→DONE、一条拆十条。

```text
Gate 2 Real Task LLM = PASS
T01～T10 Real Model  = PASS
允许进入真机（环境具备时）
```
