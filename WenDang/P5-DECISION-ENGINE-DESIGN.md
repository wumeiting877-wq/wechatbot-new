# P5 Decision Engine 设计

> 日期：2026-09-22  
> 阶段：P5-G0  
> 对照：`P5-DECISION-DATA-MODEL-DESIGN.md`、`P5-EXTRACTOR-ARCHITECTURE-DESIGN.md`、`P4-TASK-ENGINE-DESIGN.md`  
> 本文件是设计。**禁止本轮实施生产引擎、禁止接微信、禁止改 Topic / Task / listener / Trigger。**

---

## 1. 唯一职责

```text
已形成的 Topic
    + 当前 MessageRecord
    + 该 Topic 的消息 Evidence
    + 该 Topic 已有 Decision
        ↓
Decision Extractor
        ↓
0..N 个 NEW_DECISION / UNRELATED
        ↓
Decision Store + Audit
```

不负责：

- Topic 分类、Task 创建、Risk 抽取
- 是否回复微信（P0 Trigger）
- 把建议提升为决定
- 自动 SUPERSEDED / CANCELLED
- 催办、`send_reply`、`wx.SendMsg`、Dashboard

Decision 结果不得绕过 Trigger 发微信，不得改 Topic / Task / verdict。

---

## 2. 在链路上的位置

沿用 P4 已验证的「Topic 成功之后的隔离旁路」，再扇出一条独立观察者：

```text
evaluate_inbound                         （冻结）
    ↓
Topic Side-path worker                   （P3 冻结；G1 不改）
    TopicEngine.process_*
        成功且 decision ∈ { NEW_TOPIC, EXISTING_TOPIC, TOPIC_UPDATE }
        且 topic_id 非空
            ├→ TaskEngine     （P4 已有，独立 queue）
            ├→ DecisionEngine （P5，独立 queue；G1 离线直调）
            └→ RiskEngine     （P5，独立 queue；不在 Decision Gate 实施）
        其它（UNRELATED / SKIPPED / FAILED / DISABLED）
            → 不跑 Decision
```

| Topic 结果 | Decision |
|---|---|
| NEW_TOPIC / EXISTING_TOPIC / TOPIC_UPDATE + topic_id | 允许跑 |
| UNRELATED / SKIPPED | 不跑 |
| FAILED / timeout | 不跑；Topic 日后重试成功后再跑 |
| DISABLED | 不跑 |
| Topic 误分类 | 跑，但继承错误 topic_id（LIMITATION） |

| Task 结果 | Decision |
|---|---|
| 成功 / FAILED / DISABLED / 未跑 | **均不作为闸门** |

Decision Engine 失败不影响 Topic / Task / Chat。  
Topic 失败不允许 Decision 补跑或自造 Topic。

G1：测试直接 `DecisionEngine.process_record(...)`，fixture 预置 Topic + Message + Link。  
G2：才允许按 P4-G2 模式在 `topic_sidepath._maybe_enqueue_task` 旁增加 `_maybe_enqueue_decision`。本轮禁止。

---

## 3. 依赖链选择

任务书要求比较 A / B / C。

### 方案 A（推荐）

```text
Topic
 ├→ Task
 ├→ Decision
 └→ Risk
```

三条独立下游。彼此不决定对方是否运行。

### 方案 B：Risk 依赖 Task

不作为 Decision 设计的一部分。Decision 更不应依赖 Task。

### 方案 C：Risk 依赖 Decision

不采用。风险陈述经常不经过拍板（「如果今天修不好会影响演示」）。Decision Engine 不得成为 Risk 闸门，也不得被 Risk 闸门。

**Decision 只依赖 Topic 成功 + topic_id。**

---

## 4. 处理流水线（G1 要实现的逻辑，本轮不写代码）

```text
1. 校验 conversation_id、topic_id、MessageRecord 已存在
2. Topic 必须存在且为本会话
3. 若 DecisionProcessing 已成功 → return replayed
4. 方向 OUTBOUND → SKIPPED（不抽机器人自己的话）
5. 规则预筛
      纯 acknowledgement / 空 / 纯表情 → UNRELATED，不调 LLM
      注意：「行。」单独命中预筛时按 UNRELATED（见 D03）
6. 组装输入
      current_message
      recent_topic_messages ≤ 12（TopicMessageLink ∩ MessageRecord，不含当前）
      existing_decisions ≤ 10（本 topic RECORDED，优先未被 supersede 的）
      conversation / topic 摘要
      禁止全群历史、其它 Topic、Chat context
7. Decision Extractor
8. Validate decisions[]
9. Apply：仅 NEW_DECISION / UNRELATED
10. Write DecisionProcessing + audit（preview ≤80）
```

任一步 Extractor/校验失败：写 FAILED，不写脏 Decision，**不影响 Topic / Task**。

先完整 Validate，再写盘（与 P4 相同：避免 decision 1 已写、decision 2 FAIL 留半套）。

---

## 5. Extractor 输入上限

| 输入 | 上限 | 原因 |
|---|---|---|
| `conversation` | 1 | id / type / display_name |
| `topic` | 1 | 不重新分类 |
| `current_message` | 1 | content ≤ 800 字 |
| `recent_topic_messages` | **≤ 12** | 与 P3/P4 同量级；只含本 Topic 已链接消息 |
| `existing_decisions` | **≤ 10** | 供 supersede 命中。只 RECORDED |
| 全会话消息 | **禁止** | 多 Topic 已证实 |
| Chat context / QIYE 回复 | **禁止** | |
| existing_tasks | **禁止 v1** | Decision 不绑 Task |
| sibling topics | **禁止** | |

---

## 6. Extractor 输出 Schema（v1 最终）

不采用任务书候选中的 `DECISION_UPDATE`。不可变事实用 NEW + supersede。

```json
{
  "decisions": [
    {
      "decision": "NEW_DECISION | UNRELATED",
      "decision_id": null,
      "supersedes_decision_id": null,
      "title": "",
      "decision_text": "",
      "confidence": "HIGH | MEDIUM | LOW",
      "evidence_message_ids": [],
      "reason": ""
    }
  ]
}
```

规则：

- `decisions` 1..5 条。无确认时一条 `UNRELATED`
- `NEW_DECISION`：`decision_id` 必须为 null；`title` 与 `decision_text` 必填
- `supersedes_decision_id` 可空；非空必须 ∈ `existing_decisions.id`
- `UNRELATED`：不得携带 `decision_id` / 伪造 title
- `evidence_message_ids` 必须来自输入，且含 `current_message.id`
- 禁止输出 `status`、`SUPERSEDED`、`CANCELLED`、`DECISION_UPDATE`、`task_id`、`severity`
- 出现非法 extractor decision → 整单 `INVALID_DECISION`，不落盘

CREATED_BY = 当前确认句。  
RELATED = evidence 中的建议/方案句（非当前消息）。

---

## 7. 建议 vs Decision 判定

必须同时满足才 NEW_DECISION：

1. 当前句是 **明确确认 / 拍板**，不是单纯建议、不是单纯「收到」
2. 被确认的内容能从 **当前句或 Topic 窗口** 指认，引擎不编造方案名
3. 不是 Task 指派本身（「王强今天 17 点前处理完」没有确认方案）
4. 不是当前问题事实（「ERP 同步失败了」）

确认言语行为（正向例子）：

```text
可以，就按照异常池方案执行。
这个方案确定了。
那就这么定，现场演示使用 demo-viewer 账号。
刚才那个方案改了，改成全量同步。
```

不是 Decision：

```text
我建议供应商编码缺失的数据先进异常池。
行。
收到
王强今天 17 点前处理完。
ERP 同步失败了。
```

### D03「行。」：宁可不建

即使上文有完整方案，单独「行。」/「好」/「可以。」（无方案复述、无「就按…执行」「确定了」「那就这么定」）→ **UNRELATED**。

理由：与 acknowledgement 预筛重叠；企业群里「行」经常只是听到了。v1 宁可漏，不可把应答写成企业事实。

「可以，就按照异常池方案执行」因为 **复述了方案并给出执行确认**，才建。

---

## 8. 状态保守原则

```text
NEW_DECISION → 只写 RECORDED
```

禁止引擎因为 supersede 去改旧行 status。  
旧行保持 RECORDED + 新行带 `supersedes_decision_id`。

---

## 9. 开关与隔离

```text
DECISION_ENGINE_ENABLED = false     # 模块默认
```

读取顺序与 P3/P4 对齐（G2 实施时）：`runtime_control/DECISION_ENGINE_ENABLED` > 环境变量 > 模块常量。

关闭时：Topic / Task 不受影响。  
Decision LLM timeout：只写 Decision FAILED，不得阻塞 Topic worker / listener / Chat。  
独立 bounded queue + 单 worker（G2）。G1 无 queue。

禁止符号：`send_reply`、`wx.SendMsg`、改 `evaluate_inbound`、改 Trigger。

---

## 10. 一 Message 多 Decision 与混合

- 一 Message 可以 0..N Decision（上限 5）
- 一 Message 可以同时被 Task Engine 建成 Task、被 Decision Engine 建成 Decision（M03）。二者独立跑，互不读取对方 **本条消息的新产出**
- Decision 不读取 Risk 产出

---

## 11. 本轮明确不实施

```text
decision_engine.py
decision_store.py
decision_sidepath.py
prompts/extractors/DECISION_EXTRACTOR.md   # G1 才落地；正文稿见 Extractor 架构文档
```

G0 只保留设计与 fixture。
