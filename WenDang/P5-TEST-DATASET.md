# P5 Decision / Risk 离线测试数据集

> 日期：2026-09-22  
> 阶段：P5-G0  
> 用途：未来 G1 / G3 离线抽取验证。**不**验证催办、微信发送、Dashboard。  
> 不跑真实微信。本轮不跑 Engine。  
> 机器可读副本：`tests/fixtures/p5/decision_cases.json`、`risk_cases.json`、`mixed_cases.json`

每个 CASE 都 **预置** 已形成的 Topic + 必要的 Topic 消息 Evidence。  
Decision CASE 不断言 Task / Risk。  
Risk CASE 不断言 Task / Decision，除非 CASE 明确写了 candidate_tasks。  
混合 CASE 分别断言两套引擎，模拟并行，不要求同一消息上新 Task 能被 Risk 看见。

---

## 1. 固定 Conversation / Topic 种子

与 P4 fixture 对齐，便于以后串 Replay，但 **按 CASE 隔离 run**：

```text
conversation.id            conv_zhiqun_demo01
conversation.display_name  智群Demo
conversation_type          GROUP

Topic A  topic_demo_erp     title=ERP 数据同步异常
Topic B  topic_demo_perm    title=权限整改
Topic C  topic_demo_demo    title=现场演示准备
```

人员只作 `sender_name`。不验收通讯录 ID，不验收 severity。

---

## 2. 共用规则

### Decision

```text
NEW_DECISION 必须：明确确认 / 拍板
单独建议 / 收到 / 行。 / 当前问题 / 纯 Task 指令 → 不建
CREATED_BY = 确认句，不是建议句
v1 只写 status=RECORDED
无 DECISION_UPDATE；改方案 = 新 Decision + supersedes_decision_id
旧 Decision 不被改写正文，不自动 SUPERSEDED
1 消息最多 5 条；通常 0 或 1
```

### Risk

```text
NEW_RISK 必须：未来不利结果 + 条件/原因/来源
当前问题 / 建议 / 模糊担忧 / 纯 Task / 收到 / 已恢复 → 不建
v1 只写 status=OPEN
不自动 RESOLVED
无 severity
task_id 可空
1 消息最多 5 条
```

---

## 3. Decision CASE

### D01 明确决定

**Topic：** A  
上文：

```text
我建议供应商编码缺失的数据先进异常池。
```

当前：

```text
可以，就按照异常池方案执行。
```

| 期望 | 值 |
|---|---|
| Decision | **YES** |
| new_decision_count | 1 |
| status | RECORDED |
| CREATED_BY | 当前确认句 |
| RELATED | 建议句（允许） |
| supersedes_decision_id | 空 |
| 不得把建议句当 CREATED_BY | 是 |

---

### D02 单独建议

当前：

```text
我建议供应商编码缺失的数据先进异常池。
```

| 期望 | 值 |
|---|---|
| Decision | **NO** |
| new_decision_count | 0 |

---

### D03 模糊确认

上文有完整异常池建议。当前：

```text
行。
```

| 期望 | 值 |
|---|---|
| Decision | **NO**（保守：宁可不建） |
| 理由 | 与应答不可分；无方案复述、无拍板套语 |

若未来要支持，必须单独升 Prompt 并新增 CASE，不得在 v1 把「行。」当企业事实。

---

### D04 明确拍板

**Topic：** C

```text
那就这么定，现场演示使用 demo-viewer 账号。
```

| 期望 | 值 |
|---|---|
| Decision | **YES** |
| decision_text | 含 demo-viewer / 现场演示账号 |
| status | RECORDED |

---

### D05 修改决定

**预置：** Decision `dec_demo_incr`  
title=采用增量同步，decision_text=决定使用增量同步，status=RECORDED

当前：

```text
刚才那个方案改了，改成全量同步。
```

| 期望 | 值 |
|---|---|
| 旧 Decision 正文 | **保持不变** |
| 旧 status | 仍为 RECORDED（不自动 SUPERSEDED） |
| new_decision_count | 1 |
| 新 supersedes_decision_id | `dec_demo_incr` |
| 新 decision_text | 含全量同步 |

---

### D06 当前问题事实

```text
ERP 同步失败了。
```

| 期望 | 值 |
|---|---|
| Decision | 0 |

---

### D07 Task 指令

```text
王强今天 17 点前处理完。
```

| 期望 | 值 |
|---|---|
| Decision | 0 |

本句是 Task 语义。Decision Engine 不建；也不要求本 CASE 跑 Task Engine。

---

### D08 收到

```text
收到
```

| 期望 | 值 |
|---|---|
| Decision | 0 |
| 允许规则预筛 UNRELATED 不调 LLM | 是 |

---

## 4. Risk CASE

### R01 明确 Risk

**Topic：** A 或 C（预置 ERP/演示上下文均可）

```text
如果今天还修不好，会影响明天现场演示。
```

| 期望 | 值 |
|---|---|
| Risk | **YES** |
| condition_text | 含今天 / 修不好 |
| impact_text | 含明天 / 演示 |
| status | OPEN |
| severity | 不得出现 |

---

### R02 当前问题

```text
ERP 同步失败了。
```

| 期望 | 值 |
|---|---|
| Risk | **NO** |

---

### R03 建议

```text
最好准备一个离线包。
```

| 期望 | 值 |
|---|---|
| Risk | **NO** |

---

### R04 当前事实 + 未来影响

```text
现场 Wi-Fi 现在不稳定，如果断网会导致系统无法演示。
```

| 期望 | 值 |
|---|---|
| Risk | **YES** |
| condition_text | 含 Wi-Fi / 断网 |
| impact_text | 含无法演示 |
| status | OPEN |

---

### R05 模糊担忧

```text
感觉有点危险。
```

| 期望 | 值 |
|---|---|
| Risk | **不建** |

---

### R06 完成 / 已解决

**预置：** OPEN Risk「断网无法演示」（R04 形态）

当前：

```text
Wi-Fi 已经恢复了。
```

| 期望 | 值 |
|---|---|
| 不自动 RESOLVED | **必须** |
| status 仍 OPEN | 是 |
| RISK_UPDATE 关闭语义 | 禁止 |
| 允许 UNRELATED | 是 |

---

### R07 Task 本身

```text
赵凯明天准备离线包。
```

| 期望 | 值 |
|---|---|
| Risk | 0 |

---

### R08 收到

```text
收到。
```

| 期望 | 值 |
|---|---|
| Risk | 0 |

---

## 5. 混合 CASE

混合 CASE 表达 **一条消息上多种业务语义可以并存**。  
实施时 Task / Decision / Risk 各自跑自己的 Extractor；fixture 按引擎拆期望。

### M01 Decision + Risk

```text
就按照异常池方案执行，如果今晚处理不完，会影响明天演示。
```

| 引擎 | 期望 |
|---|---|
| Decision | YES（确认异常池方案） |
| Risk | YES（今晚处理不完 → 影响明天演示） |
| 1 Message → 1 Decision + 1 Risk | **允许** |

二者不互为闸门。

---

### M02 Task + Risk

```text
王强今天 17 点前处理，如果处理不完会影响今晚回归。
```

当前 Task Engine（P4 已验证）会建 Task。

| 引擎 | 期望 |
|---|---|
| Task | YES（P4 语义，G1 Decision 不必跑） |
| Risk | **YES** |
| Risk.task_id | v1 **允许空**（并行看不到本条新建 Task） |
| 若 candidate_tasks 已有王强空值规则 Task | 允许填该 id |

---

### M03 Task + Decision

```text
那就这么定，王强今天 17 点前处理。
```

| 引擎 | 期望 |
|---|---|
| Decision | YES（那就这么定 —— 需窗口里有可指认方案；若窗口只有空泛讨论且本句未复述方案，允许 UNRELATED。本 CASE fixture 预置异常池建议上文，故期望 YES） |
| Task | YES（王强今天 17 点前处理） |
| 1 Decision + 1 Task | **允许** |
| Decision.task_id | 不存在该字段 |

---

## 6. G1 / G3 如何使用

```text
G1 只跑 decision_cases.json + M01/M03 的 Decision 期望
G3 才跑 risk_cases.json + M01/M02 的 Risk 期望
不要在 G1 要求 Risk Engine 已存在
```

Heuristic 或真实 LLM 都可以，但断言以本文件为准。
