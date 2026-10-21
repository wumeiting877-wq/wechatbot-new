# P5-G4 真实 Risk LLM 测试报告

> 日期：2026-09-22  
> 必须区分 Heuristic 与真实 MODEL。禁止记录 API Key。

---

## Heuristic

`tests.test_risk_engine_offline`：G3 离线红线仍有效（Gate 1 已复跑源码 guard）。  
`tests.test_risk_sidepath`：**17 PASS**（Gate 1 挂载语义，Heuristic）

---

## 真实 MODEL

| 项 | 值 |
|---|---|
| model name | `deepseek-v4-flash` |
| prompt name | `RISK_EXTRACTOR` |
| prompt hash | `f95d92ec311ca82663f4207c1eba69212b57172e174782808cba1f63c5363d70` |
| temperature | 0.2 |
| max_tokens | 1400 |
| timeout | 20s |
| store_context | false |

未记录 Key / Authorization / `.env`。

命令：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_risk_live_adapter.RealRiskExtractorTests -v
```

结果：**12 tests, OK**，约 45.0s。

---

## R01～R09 / M01 / M02（真实模型）

| CASE | 结果 | 说明 |
|---|---|---|
| **R01** 明确 Risk | **PASS** | 「如果今天还修不好，会影响明天现场演示。」→ 1 `OPEN`；condition 含修不好；impact 含演示；无 severity |
| **R02** 当前问题 | **PASS** | 「ERP 同步失败了。」→ **0 Risk**（第一硬门槛） |
| **R03** 建议 | **PASS** | 「最好准备一个离线包。」→ **0 Risk** |
| **R04** Wi-Fi + 未来影响 | **PASS** | 1 Risk，OPEN；condition 含 Wi-Fi/断网；impact 含无法演示 |
| **R05** 模糊担忧 | **PASS** | 「感觉有点危险。」→ **0 Risk** |
| **R06** 已恢复 | **PASS** | 0 NEW_RISK；原 `risk_demo_wifi` 仍 OPEN；无 RESOLVED / MITIGATED / CLOSED |
| **R07** Task 指令 | **PASS** | 「赵凯明天准备离线包。」→ **0 Risk** |
| **R08** 收到 | **PASS** | 「收到。」→ **0 Risk** |
| **R09** RISK_UPDATE | **PASS** | 总数不增加；status 仍 OPEN；`UPDATED_BY` = 当前更新消息 |
| **M01** Decision + Risk 句 | **PASS** | Risk = YES；Decision Store 未被 Risk Engine 写入 |
| **M02** Task + Risk 句 | **PASS** | Risk = YES；`task_id` 可空 |

未出现：当前问题建 Risk、建议建 Risk、模糊担忧建 Risk、Task 指令建 Risk、已恢复自动 RESOLVED、自动 severity、重复新建。

失败注入已在 `RiskFailurePreservesTopicTaskDecisionTests` 覆盖，不调用真实 Key。  
Topic / Task / Decision 快照在失败路径保持不变。

---

## Gate 2 FAIL 条件核对

| 禁止现象 | 是否出现 |
|---|---|
| ERP 同步失败 → Risk | **否** |
| 建议 → Risk | **否** |
| 感觉危险 → Risk | **否** |
| Task 指令 → Risk | **否** |
| 已恢复 → RESOLVED | **否** |
| 自动 severity | **否** |

```text
Gate 2 真实 Risk LLM = PASS
允许进入真机（需测试号 ceshi 在 QIYE 群发送 RK-R1～R17）
```
