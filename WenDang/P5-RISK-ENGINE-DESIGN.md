# P5 Risk Engine 设计

> 日期：2026-09-22  
> 阶段：P5-G0  
> 对照：`P5-RISK-DATA-MODEL-DESIGN.md`、`P5-DECISION-ENGINE-DESIGN.md`、`P5-EXTRACTOR-ARCHITECTURE-DESIGN.md`  
> 本文件是设计。**禁止本轮实施生产引擎。** 推荐在 Decision Offline（G1）之后单独做 Risk Offline（G3）。

---

## 1. 唯一职责

```text
已形成的 Topic
    + 当前 MessageRecord
    + 该 Topic 的消息 Evidence
    + 该 Topic 已有 OPEN Risk
    + （可选）该 Topic 已有 OPEN Task
        ↓
Risk Extractor
        ↓
0..N 个 NEW_RISK / RISK_UPDATE / UNRELATED
        ↓
Risk Store + Audit
```

不负责：Topic 分类、Task 是否创建、Decision 是否记录、风险定级、自动消除风险、发微信、催办。

---

## 2. 依赖链：Risk 不依赖 Task / Decision 成功

### 方案 A（推荐）

```text
Topic 成功
 ├→ Task
 ├→ Decision
 └→ Risk
```

Risk 与 Task / Decision **并行观察**。可以引用 `task_id`，但 **不得**要求 Task 成功才运行。

反例已足够：

```text
如果今天修不好，会影响明天演示。
```

没有明确 Task，仍然是 Risk。

### 方案 B：Topic → Task → Risk

不采用 v1。Task LLM 故障会阻断主题风险，和 P4「Task 失败不影响 Topic」的隔离原则相反。

### 方案 C：Topic → Decision → Risk

不采用。多数风险不是「确认方案之后才存在的风险」。

### Topic 依赖（必须）

```text
Topic FAILED / UNRELATED / SKIPPED / 无 topic_id
  → Risk 不跑
  → 不写 Risk 成功幂等
```

禁止 Risk 自己猜 Topic。

### Task FAILED 对 Risk 的影响

```text
Topic SUCCESS
Task FAILED
Risk 原文明确存在
  → Risk 必须允许继续运行     YES
```

此时 `candidate_tasks=[]`，`task_id` 为空，只要 condition + impact 成立仍 NEW_RISK。

---

## 3. 在链路上的位置

与 Decision 相同的扇出点，**独立 queue / 独立开关 / 独立 processing**。

```text
Topic 成功且 topic_id 非空
    └→ Risk Side-path（G4 才挂；G3 离线直调）
```

G3 不改 `topic_sidepath.py`。  
G4 增加 `_maybe_enqueue_risk`，失败隔离，不得回滚 Topic / Task / Decision。

不要把 Risk 挂在 Task worker 成功回调里——那会在 TASK_ENGINE_ENABLED=false 时丢掉全部主题风险。

---

## 4. 处理流水线（G3 逻辑，本轮不写代码）

```text
1. 校验 conversation / topic / MessageRecord
2. RiskProcessing 已成功 → replayed
3. OUTBOUND → SKIPPED
4. 规则预筛：收到 / 空 / 表情 → UNRELATED
5. 组装输入
      recent_topic_messages ≤ 12
      existing_risks ≤ 10 OPEN
      candidate_tasks ≤ 10 OPEN（读 TaskStore；失败则 []，不中止）
6. Risk Extractor
7. Validate 全部后再写盘
8. NEW_RISK / RISK_UPDATE / UNRELATED
9. Processing + audit
```

读 TaskStore 异常：记 audit，`candidate_tasks=[]`，**继续**。不得把 Task Store 故障升级成 Risk FAILED，除非 Topic/Message 本身不可用。

---

## 5. Extractor 输入上限

| 输入 | 上限 | 原因 |
|---|---|---|
| `conversation` | 1 | |
| `topic` | 1 | |
| `current_message` | 1 | content ≤ 800 |
| `recent_topic_messages` | **≤ 12** | 本 Topic Link |
| `existing_risks` | **≤ 10** | OPEN only |
| `candidate_tasks` | **≤ 10** | 当前 Topic OPEN Task；可选 |
| 全群历史 / 其它 Topic / Chat context | **禁止** | |
| existing_decisions | **禁止 v1** | 避免 Risk 变相依赖 Decision |

**给 Risk Extractor 当前 Topic 的 OPEN Tasks：要给，最多 10 条。**  
排序可与 P4 相同：正文点名命中 `assignee_text` 优先，其次 `updated_at`。  
不把 `TaskMessageLink` 整表塞进 Prompt。

---

## 6. Extractor 输出 Schema（v1 最终）

```json
{
  "risks": [
    {
      "decision": "NEW_RISK | RISK_UPDATE | UNRELATED",
      "risk_id": null,
      "title": "",
      "condition_text": "",
      "impact_text": "",
      "task_id": null,
      "confidence": "HIGH | MEDIUM | LOW",
      "evidence_message_ids": [],
      "reason": ""
    }
  ]
}
```

- `risks` 1..5；无风险时一条 UNRELATED
- NEW_RISK：`risk_id` null；`title` / `condition_text` / `impact_text` 必填
- RISK_UPDATE：`risk_id` ∈ existing_risks
- `task_id` 可空；非空必须 ∈ candidate_tasks
- 禁止 `severity`、`status`、`RESOLVED`、`MITIGATED`、`CLOSED`
- `confidence` ≠ 风险等级

---

## 7. 当前问题 vs Risk 判定

NEW_RISK 必须同时有：

```text
未来不利结果     impact_text
条件/原因/来源   condition_text
```

| 句子 | 结果 |
|---|---|
| 如果今天还修不好，会影响明天现场演示 | NEW_RISK |
| ERP 同步失败了 | UNRELATED（当前问题） |
| 最好准备一个离线包 | UNRELATED（建议，无未来不利结果结构） |
| 现场 Wi-Fi 现在不稳定，如果断网会导致系统无法演示 | NEW_RISK（当前事实 + 未来影响） |
| 感觉有点危险 | UNRELATED（无条件无影响） |
| Wi-Fi 已经恢复了 | UNRELATED（不自动 RESOLVED） |
| 赵凯明天准备离线包 | UNRELATED（这是 Task） |
| 收到 | UNRELATED |

「最好准备离线包」即使隐含「否则可能演不了」，v1 仍不建：没有明确不利结果，且建议更接近 Task/Decision 的上游，不让 Risk 引擎脑补。

---

## 8. 状态保守原则

```text
NEW_RISK → 只写 OPEN
RISK_UPDATE → 不改 status
```

禁止自动 MITIGATED / RESOLVED / CLOSED。

---

## 9. 与同一消息上其它 Engine 的关系

允许：

```text
1 Message → 1 Task + 1 Risk     （M02）
1 Message → 1 Decision + 1 Risk （M01）
1 Message → Task + Decision + Risk
```

v1 LIMITATION：Risk 的 `candidate_tasks` 看不到 **本条消息正在创建的 Task**（并行旁路）。M02 的 `task_id` 允许为空；若窗口里已有可命中的旧 Task 则可填。不要为了对齐 task_id 而串行等待 Task Engine。

---

## 10. 开关与隔离

```text
RISK_ENGINE_ENABLED = false
```

独立于 Topic / Task / Decision 开关。  
失败隔离、独立 processing、禁止发微信。  
G4 使用独立 bounded queue；满则丢弃 Risk，永不阻塞 Topic worker。

---

## 11. 为何 Decision 先做、Risk 后做

Decision 的言语行为链短：

```text
建议 → 明确确认 → Decision
```

边界可用「有没有拍板句」卡住。

Risk 往往要同时处理：当前事实、未来影响、条件、可选 Task 上下文、与「建议/担忧」的噪声。误报对企业更敏感（模型定级已被禁止，但仍会制造「存在风险」清单）。

因此实施顺序：

```text
P5-G1 Decision Offline
P5-G2 Decision Side-path + Real LLM + Live
P5-G3 Risk Engine Offline
P5-G4 Risk Side-path + Real LLM + Live
```

本轮不进入 G1。

---

## 12. 本轮明确不实施

```text
risk_engine.py
risk_store.py
risk_sidepath.py
prompts/extractors/RISK_EXTRACTOR.md
```
