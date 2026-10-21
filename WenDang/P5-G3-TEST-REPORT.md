# P5-G3 测试报告

> 日期：2026-09-22  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 命令：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_risk_store tests.test_risk_extractor tests.test_risk_engine_offline
```

结果：**68 tests, OK**（1.472s / 复跑 1.653s）

离线主路径：`HeuristicRiskExtractor`。未调用真实 Risk LLM。未接微信。

---

## 权威 Fixture CASE

| CASE | 期望 | 结果 |
|---|---|---|
| **R01** 明确 Risk「如果今天还修不好，会影响明天现场演示。」 | NEW_RISK=1，status=OPEN，condition 含今天/修不好，impact 含明天/现场演示，无 severity | **PASS** |
| **R02** 「ERP 同步失败了。」 | 0 Risk（当前问题） | **PASS** |
| **R03** 「最好准备一个离线包。」 | 0 Risk（建议，不脑补） | **PASS** |
| **R04** 「现场 Wi-Fi 现在不稳定，如果断网会导致系统无法演示。」 | 1 Risk，condition 含 Wi-Fi/断网，impact 含无法演示，OPEN | **PASS** |
| **R05** 「感觉有点危险。」 | 0 Risk（模糊担忧） | **PASS** |
| **R06** 已有 OPEN Risk + 「Wi-Fi 已经恢复了。」 | 0 NEW_RISK，0 RISK_RESOLVED，原 status 仍 OPEN | **PASS** |
| **R07** 「赵凯明天准备离线包。」 | 0 Risk（Task 指令） | **PASS** |
| **R08** 「收到。」 | 0 Risk（规则预筛 UNRELATED，不调 Extractor） | **PASS** |
| **M01** 「就按照异常池方案执行，如果今晚处理不完，会影响明天演示。」 | Risk=YES，condition 含处理不完，impact 含演示 | **PASS** |
| **M02** 「王强今天 17 点前处理，如果处理不完会影响今晚回归。」 | Risk=YES，task_id 允许为空（本轮为空） | **PASS** |
| **R09** 同一担忧更具体（补充 CASE） | RISK_UPDATE，Risk 数量仍 1，status 仍 OPEN，condition/impact 更新 | **PASS** |

R01～R08 语义未改。R09 为 G0 fixture 缺失的 RISK_UPDATE 专用 CASE。

---

## TaskStore Failed / Unavailable → Risk Still Works

| 场景 | 结果 |
|---|---|
| `list_open_tasks` 抛异常 | Risk = NEW_RISK，`task_id=""`，`candidate_tasks=[]`，audit `CANDIDATE_TASKS_UNAVAILABLE`，**不是 FAILED** | **PASS** |
| `task_store=None` | 同上，仍可建 Topic Risk | **PASS** |
| 非法 `task_id=task_invented` | 清空 task_id，Risk 仍创建 | **PASS** |

策略写死为：**丢弃非法 task_id，继续按 Topic Risk 落盘。**

---

## Failure Injection

| 注入 | Risk | 脏数据 | Topic / Task / Decision | 进程 |
|---|---|---|---|---|
| Extractor timeout | FAILED / EXTRACTOR_TIMEOUT | 无 | 不变 | 不崩 | **PASS** |
| Extractor exception | FAILED | 无 | 不变 | 不崩 | **PASS** |
| invalid JSON | FAILED / JSON_PARSE_ERROR | 无 | 不变 | 不崩 | **PASS** |
| empty output | FAILED / EXTRACTOR_EMPTY | 无 | 不变 | 不崩 | **PASS** |
| invalid risk_id | FAILED / INVALID_RISK_ID | 无 | 不变 | 不崩 | **PASS** |
| invalid evidence id | FAILED / INVALID_EVIDENCE_ID | 无 | 不变 | 不崩 | **PASS** |
| 第二条 invalid 半套 | FAILED，0 Risk | 无 | 不变 | 不崩 | **PASS** |
| Prompt missing | FAILED / EXTRACTOR_PROMPT_NOT_FOUND，不调 LLM | 无 | 不变 | 不崩 | **PASS** |
| Prompt empty | FAILED / EXTRACTOR_PROMPT_EMPTY，不调 LLM | 无 | 不变 | 不崩 | **PASS** |
| Store write failure | FAILED / STORE_WRITE_FAILURE | 无脏 Risk | Topic 不变 | 不崩 | **PASS** |
| TaskStore read exception | **不 FAILED**，继续 NEW_RISK | 无 | 不变 | 不崩 | **PASS** |

失败 Processing 同 version 可重试成功：**PASS**。

---

## Idempotency

| 项 | 结果 |
|---|---|
| 相同 Message 重放 → Risk 不重复 | **PASS** |
| 同 Message 多 Risk 重放 → 数量不增加 | **PASS** |
| RISK_UPDATE 重放 → 不重复 Link / 不重复 Risk | **PASS** |
| 成功 Processing → skip | **PASS** |
| FAILED → 同 version 可重试 | **PASS** |

---

## Prompt Isolation

| 项 | 结果 |
|---|---|
| `RISK_EXTRACTOR.md` 独立存在 | **PASS** |
| 不进入 Chat 下拉（`list_prompt_names`） | **PASS** |
| QIYE / 企业_1 未改（无 NEW_RISK schema） | **PASS** |
| TOPIC_EXTRACTOR 未改 | **PASS** |
| TASK_EXTRACTOR 未改 | **PASS** |
| DECISION_EXTRACTOR 未改 | **PASS** |
| `DEFAULT_EXTRACTOR_PROMPT_NAME` 仍为 `TOPIC_EXTRACTOR` | **PASS** |
| parser 不复用 Topic / Task / Decision parser | **PASS** |

---

## Source Send Guard

`risk_store.py` / `risk_engine.py` / `risk_extractor_client.py` 禁止：

```text
send_reply(
wx.SendMsg(
SendMsg(
from message.listener
```

`risk_sidepath.py` **不存在**。Risk Engine 只写 Store + Audit。**PASS**

---

## Store 单测（不调用 LLM）

正常 NEW_RISK、conversation_id/topic_id 正确、Topic 不存在禁止创建、Topic 属其它 Conversation 禁止创建、task_id 可空、合法 task_id 可写、非法 task_id 不伪造、CREATED_BY 正确、RELATED 不重复、UPDATED_BY 正确、status 只能 OPEN、禁止 severity、成功 Processing replay skip、FAILED 可重试、同 Message 多 Risk ID 不冲突、不同 Conversation 隔离、`delete_conversation_risk_data` 正确。全部 **PASS**。

---

## 开关与范围

```text
RISK_ENGINE_ENABLED default = false   PASS
enabled 默认不落盘                    PASS
未接 listener                         PASS
未改 topic_sidepath                   PASS
```
