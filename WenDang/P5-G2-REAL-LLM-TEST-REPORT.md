# P5-G2 真实 Decision LLM 测试报告

> 日期：2026-09-22  
> 必须区分 Heuristic 与真实 MODEL。禁止记录 API Key。

---

## Heuristic

`tests.test_decision_engine_offline`：**57 PASS**（与 G1 基线一致）  
`tests.test_decision_sidepath`：**15 PASS**（Gate 1 挂载语义，Heuristic）

---

## 真实 MODEL

| 项 | 值 |
|---|---|
| model name | `deepseek-v4-flash` |
| prompt name | `DECISION_EXTRACTOR` |
| prompt hash | `f1d3ff7d583aea2c999c827791bfe16411c257eff49467a6c2021c13b410c1ef` |
| temperature | 0.2 |
| max_tokens | 1400 |
| timeout | 20s |
| store_context | false |

未记录 Key / Authorization / `.env`。

命令：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_decision_live_adapter.RealDecisionExtractorTests -v
```

结果：**11 tests, OK**，约 29.4s。

---

## D01～D08 / M01 / M03（真实模型）

| CASE | 结果 | 说明 |
|---|---|---|
| **D01** 明确确认 | **PASS** | 上文建议 + 「可以，就按照异常池方案执行。」→ 1 `RECORDED`；`CREATED_BY` = 确认句；建议句不是 CREATED_BY |
| **D02** 单独建议 | **PASS** | 「我建议…先进异常池。」→ **0 Decision** |
| **D03** 「行。」 | **PASS** | 即使有完整建议上文 → **0 Decision**（硬门槛） |
| **D04** demo-viewer | **PASS** | 「那就这么定，现场演示使用 demo-viewer 账号。」→ 1 Decision，`decision_text` 含 demo-viewer |
| **D05** 修改决定 | **PASS** | 旧 `dec_demo_incr` 正文「决定使用增量同步。」不变；旧 status 仍 `RECORDED`；新 Decision `supersedes_decision_id=dec_demo_incr`；未原地覆盖 |
| **D06** 问题事实 | **PASS** | 「ERP 同步失败了。」→ **0 Decision** |
| **D07** Task 指令 | **PASS** | 「王强今天 17 点前处理完。」→ **0 Decision** |
| **D08** 收到 | **PASS** | 「收到」→ **0 Decision** |
| **M01** Decision + Risk 文本 | **PASS** | Decision = YES；Risk Engine 未实现、无 risk_store 写入 |
| **M03** Decision + Task 句 | **PASS** | Decision = YES；记录无 `task_id` |

未出现：建议建 Decision、「行。」建 Decision、收到建 Decision、问题事实建 Decision、Task 指令建 Decision、原地覆盖旧正文、自动 SUPERSEDED / CANCELLED。

失败注入已在 `DecisionFailurePreservesTopicAndTaskTests` 覆盖，不调用真实 Key。

---

## Gate 2

```text
Gate 2 真实 Decision LLM = PASS
允许进入真机（需测试号 ceshi 在 QIYE 群发送 DJ-R1～R14）
```

## Gate 4 复跑

真机结束后复跑同一套件：**11 tests, OK**，约 31.4s。模型 / prompt hash 未变。
