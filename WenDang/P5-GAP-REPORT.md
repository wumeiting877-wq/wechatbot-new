# P5 Gap Report

> 日期：2026-09-22  
> 阶段：P5-G0  
> 依据：`P5-CURRENT-STATE-AUDIT.md`、`P5-DECISION-DATA-MODEL-DESIGN.md`、`P5-RISK-DATA-MODEL-DESIGN.md`、`P5-DECISION-ENGINE-DESIGN.md`、`P5-RISK-ENGINE-DESIGN.md`、`P5-EXTRACTOR-ARCHITECTURE-DESIGN.md`、`P5-TEST-DATASET.md`  
> 分类：BLOCKER / REQUIRED / OPTIONAL / FUTURE / LIMITATION  
> BLOCKER = 不解决就不能进入 **下一个 P5 实施 Gate（P5-G1）**  
> 本轮 **未写生产业务代码**。下列不是测试 FAIL，是现状缺口与设计结论。

---

## 1. P5-G0 必须回答的 25 问

### 1. Decision 当前是否存在？

**否。** 无实体、无 Store、无 Prompt、无 Processing。Chat「结论」只是自然语言。

### 2. Risk 当前是否存在？

**否。** 同上。Chat「风险」只是自然语言。`FORBIDDEN_TASK_KEYS.risk_ids` 不是实体。

### 3. Decision 应绑定 Conversation + Topic 吗？

**是。MUST 两者。** 分区方式与 P3/P4 一致。Decision 本质属于 Topic，不属 Task。v1 禁止 `task_id`。

### 4. Risk 是否需要 task_id？

**OPTIONAL 可空。** MUST 仍是 `conversation_id` + `topic_id`。有可命中的 OPEN Task 才填。不作为运行依赖。

### 5. 建议与 Decision 的判定边界是什么？

建议（「我建议…先进异常池」）不是 Decision。  
只有明确确认 / 拍板（「可以，就按照…执行」「这个方案确定了」「那就这么定…」）才 NEW_DECISION。  
CREATED_BY = 确认句；建议句最多 RELATED。  
单独「行。」宁可不建。

### 6. 当前问题与 Risk 的判定边界是什么？

当前问题（「ERP 同步失败了」）不是 Risk。  
Risk 必须同时有未来不利结果 + 条件/原因/来源。  
「感觉有点危险」不建。「最好准备离线包」是建议，不建。

### 7. Decision 是否应该不可变？

**正文不可原地覆盖。** 不提供 DECISION_UPDATE。

### 8. Decision 修改如何保留历史？

新建 Decision + `supersedes_decision_id`。旧行保持 RECORDED，不自动写 SUPERSEDED。

### 9. Risk v1 是否只允许 OPEN？

**是。** 自动创建只写 OPEN。禁止自动 MITIGATED / RESOLVED / CLOSED。

### 10. Decision v1 写什么状态？

**只写 RECORDED。** 不自动 SUPERSEDED / CANCELLED。

### 11. 是否需要 severity？

**v1 不需要。FUTURE。** 无企业定级标准，模型不得给 HIGH/CRITICAL。`confidence` 只表示抽取把握。

### 12. Decision Evidence 如何设计？

`DecisionMessageLink`：v1 使用 CREATED_BY（确认句）+ RELATED（建议/方案上文）。  
CONFIRMED_BY / UPDATED_BY / SUPERSEDED_BY 不进 v1。  
`message_id` 指向 Topic Store MessageRecord，不复制正文。

### 13. Risk Evidence 如何设计？

`RiskMessageLink`：CREATED_BY + RELATED + UPDATED_BY。  
MITIGATION_EVIDENCE / RESOLUTION_EVIDENCE 不进 v1。

### 14. 一 Message 是否支持多 Decision？

**支持。** 上限 5。通常 0 或 1。

### 15. 一 Message 是否支持多 Risk？

**支持。** 上限 5。通常 0 或 1。同一条件+同一影响不拆。

### 16. 一 Message 是否允许 Task + Decision + Risk 同时存在？

**允许。** 三个独立 Extractor。M01 / M02 / M03 覆盖两两组合。三者不互为闸门。

### 17. Decision / Risk 是否都必须依赖 Topic success？

**是。** Topic FAILED / UNRELATED / 无 topic_id → 两者都不跑。禁止自己猜 Topic。

### 18. Task FAILED 是否阻塞 Risk？

**否。** Topic SUCCESS + Task FAILED + 明确 Risk 原文 → Risk 继续。`candidate_tasks` 可为空。

Decision 同样不看 Task 成败。

### 19. 是否采用一个统一 Action Extractor？

**否。** 会解冻 / 改写已 COMPLETE 的 Task Engine 与 TASK_EXTRACTOR。

### 20. 是否采用两个独立 Extractor？

**是。** `DECISION_EXTRACTOR.md` 与 `RISK_EXTRACTOR.md` 独立；Task Extractor 保持不动。共三套下游 Extractor。

### 21. Decision / Risk Store 是否独立？

**是。** `data/decision_store/` 与 `data/risk_store/` 分开。不放进 Topic Store，不用 `action_store`。

### 22. 是否需要 SQLite？

**否。** 延续独立 JSON Store。不为 G1 引入 SQLite。

### 23. Processing 幂等怎么做？

独立 `DecisionProcessingRecord` / `RiskProcessingRecord`。  
主键 `message_id + *_processing_version`。  
成功跳过；FAILED 可同 version 重试。  
不复用 P0 Dedupe / TopicProcessing / TaskProcessing。

### 24. Prompt 升级后是否重跑？

**默认不重跑。** hash 变了只记录在新处理里；升 `decision_processing_version` 或 `risk_processing_version` 才重抽。

### 25. P5 下一步实施顺序是什么？

```text
P5-G1 Decision Engine Offline
P5-G2 Decision Side-path + Real LLM + Live
P5-G3 Risk Engine Offline
P5-G4 Risk Side-path + Real LLM + Live
```

不要下一阶段同时实现 Decision + Risk。详见 `P5-NEXT-IMPLEMENTATION-PLAN.md`。

---

## 2. BLOCKER

**无。**

STOP 十一条均不成立（见审计 §5）。可以在收到指令后进入 P5-G1。  
不生成 `P5-G0-BLOCKER-REPORT.md`。

---

## 3. REQUIRED（进入 G1 前必须按设计做，不是 G0 阻塞）

| ID | 项 | 说明 |
|---|---|---|
| R1 | 独立 Decision JSON Store | `data/decision_store/`；Evidence 指向 MessageRecord |
| R2 | 独立 Decision Extractor | 新 Prompt + 新 parser；不改三个已有 Prompt |
| R3 | DecisionProcessing 独立幂等 | 不复用 Topic/Task processing |
| R4 | 默认开关 false | `DECISION_ENGINE_ENABLED = false` |
| R5 | G1 只做 Decision 离线 | 不接微信、不改 listener/Trigger/Topic/Task 语义 |
| R6 | 建议不建、确认才建、CREATED_BY=确认句 | CASE D01/D02 |
| R7 | 正文不可覆盖 | D05 新行 + supersede |
| R8 | 只写 RECORDED | 不自动 SUPERSEDED |

Risk 的对应项是 **G3 REQUIRED**，不是 G1 REQUIRED。

---

## 4. OPTIONAL

| ID | 项 | 说明 |
|---|---|---|
| O1 | Decision Heuristic extractor | G1 可用规则跑红线，真实 LLM 放到 G2 |
| O2 | 「当前有效决定」只读过滤 | 排除已被 supersede 的 RECORDED |
| O3 | Decision audit 事件码与 P4 对齐 | ENQUEUED / SUCCESS / FAILED |
| O4 | G1 同步跑 M01/M03 的 Decision 半边 | Risk 半边忽略 |

---

## 5. FUTURE

| ID | 项 |
|---|---|
| F1 | 写入 SUPERSEDED / CANCELLED 状态 |
| F2 | DECISION_UPDATE 就地改文 |
| F3 | Decision.task_id |
| F4 | Risk severity / severity_text |
| F5 | Risk 自动 RESOLVED / MITIGATED |
| F6 | MITIGATION_EVIDENCE / RESOLUTION_EVIDENCE |
| F7 | 统一 Action Extractor |
| F8 | SQLite / ORM / 跨会话 JOIN |
| F9 | Dashboard / 决策中心 / 风险中心 |
| F10 | Reminder / 催办 / 发微信 |
| F11 | 升 processing_version 的批量重抽 |
| F12 | 同消息新建 Task 回填 Risk.task_id（需串行或二次扫描） |
| F13 | P3 多主 Topic，避免 Decision/Risk 挂错主题 |

---

## 6. LIMITATION（v1 接受）

| ID | 项 | 说明 |
|---|---|---|
| L1 | P3 单主 Topic | 双主题消息的 Decision/Risk 全挂当前主 Topic |
| L2 | 「行。」不建 Decision | 可能漏掉极简口头同意 |
| L3 | 旧 Decision 仍显示 RECORDED | 有效性靠 supersede 指针，查询层 G1 可不做 UI |
| L4 | Risk 看不到本条新建 Task | task_id 常空 |
| L5 | 删除 Task 不级联 Risk | task_id 可能悬空 |
| L6 | `reply_to_message_id` 真机常空 | 靠 12 条 Topic 窗口，不靠引用链 |
| L7 | OPEN Risk / RECORDED Decision 会累积 | 与 P4 OPEN Task 累积同类 |
| L8 | 三次 LLM 调用成本 | 用预筛和独立开关控制 |
| L9 | Chat 仍可能口头「总结风险」 | 与 Store 无关；不改 Chat Prompt |
| L10 | Topic 误分类遗产 | Decision/Risk 继承错误 topic_id |

---

## 7. 与冻结层的关系

| 冻结层 | G1 必须改？ |
|---|---|
| P0 identity/dedupe/outbound/trigger/listener | **否** |
| Topic 数据模型 / decision schema / TOPIC_EXTRACTOR | **否** |
| Task 数据模型 / decision schema / TASK_EXTRACTOR | **否** |
| Chat Prompt | **否** |
| `topic_sidepath.py` | **G1 否**；G2 才允许追加 enqueue（P4-G2 先例） |

---

## 8. 结论

```text
开放 BLOCKER              = 无
P5-G0                     = 设计完成，可 STOP
推荐下一阶段              = P5-G1 Decision Engine Offline
Decision Engine           = NOT IMPLEMENTED
Risk Engine               = NOT IMPLEMENTED
P0/P1/P2/P3/P4 baseline   = PRESERVED
```
