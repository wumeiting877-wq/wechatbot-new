# P5-G3 实施报告

> 日期：2026-09-22  
> 阶段：P5-G3 Risk Engine Offline  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 对照：`P5-G3-G0-CURRENT-STATE-CHECK.md`、`P5-RISK-DATA-MODEL-DESIGN.md`、`P5-RISK-ENGINE-DESIGN.md`、`P5-EXTRACTOR-ARCHITECTURE-DESIGN.md`

---

## 1. 本轮做了什么

在已经形成的 Topic 上，离线识别「当前消息是否明确表达了一个未来可能发生的不利结果」，并保存为结构化、可追溯、保守状态的 Risk。

新增文件：

```text
risk_store.py
risk_extractor_client.py
risk_engine.py
prompts/extractors/RISK_EXTRACTOR.md
tests/test_risk_store.py
tests/test_risk_extractor.py
tests/test_risk_engine_offline.py
WenDang/P5-G3-G0-CURRENT-STATE-CHECK.md
```

补充 fixture（不改 R01～R08 语义）：

```text
tests/fixtures/p5/risk_cases.json  新增 CASE-R09 RISK_UPDATE
```

未接微信。未改 listener / Trigger / Topic / Task / Decision 生产代码。未实现 Risk Side-path。未跑真实 Risk LLM。

---

## 2. Risk Store

路径：

```text
data/risk_store/
  conversations/{conversation_id}/
    risks.json
    links.json
    processed.json
  risk_engine_audit.jsonl
```

实体：

| 对象 | 要点 |
|---|---|
| Risk | `conv_*` + `topic_*` 必填；`task_id` 可空；v1 只写 `OPEN`；禁止 severity |
| RiskMessageLink | `CREATED_BY` / `RELATED` / `UPDATED_BY`；禁止 `MITIGATION_EVIDENCE` / `RESOLUTION_EVIDENCE` |
| RiskProcessingRecord | 主键 `message_id + risk_processing_version`；成功 skip；FAILED 可同 version 重试 |

ID：

```text
risk_ + sha1(conversation_id|topic_id|created_msg_id|ordinal|created_at)[:12]
```

同 Message 多 Risk：`ordinal=0..4`。禁止 title hash。

创建前校验 Topic 存在且属于当前 Conversation。CREATED_BY 必须指向 Topic Store 的 MessageRecord。无 Evidence 不落盘。`condition_text` 与 `impact_text` 任一为空不得创建。

---

## 3. task_id 策略（实测）

```text
推荐策略已落地：非法 / 无法校验的 task_id → 清空为 ""
Risk 本体只要 condition + impact 合法仍创建 / 更新
```

细则：

1. Extractor 输出空 / null → 写入 `""`
2. 非空但 `∉ candidate_tasks` → **清空**，不 FAILED
3. 非法格式（非 `task_*`）→ Store **不伪造**，写入 `""`
4. TaskStore 读取失败 → `candidate_tasks=[]`，`task_id=""`，Risk 继续
5. 不得写入不存在的 Task 外键，不修改 Task Store

---

## 4. Risk Extractor

`prompts/extractors/RISK_EXTRACTOR.md` 独立存在，不进入 Chat 下拉。

规则已写入 Prompt：

```text
你不是聊天机器人
你不是风险定级委员会
不要重新做 Topic 分类
当前问题不是 Risk
建议不是 Risk
模糊担忧不是 Risk
Task 指令不是 Risk
Decision 本身不是 Risk
Risk 必须同时有 condition_text + impact_text
已恢复不是 RESOLVED
禁止 severity
禁止自动 MITIGATED / RESOLVED / CLOSED
task_id 可空
不确定 → UNRELATED
```

parser 独立：`parse_risk_extractor_json` / `normalize_risk`。  
`RISK_RESOLVED` / `MITIGATED` / `RESOLVED` / `CLOSED` → `INVALID_DECISION`。  
`severity` / `status` 等禁止键剥离。

离线主路径：`HeuristicRiskExtractor`。  
`RiskExtractorClient` 已具备 `store_context=false` 的 LLM transport，G4 再接真实模型。

---

## 5. Risk Engine

离线入口：

```text
RiskEngine.process_record(conversation, topic, message)
```

```text
RISK_ENGINE_ENABLED = false   # 模块默认
离线测试 enabled=True
```

流水线：校验 Conversation / Topic / MessageRecord / Topic Evidence → 成功 Processing skip → OUTBOUND skip → 规则预筛 → 窗口 ≤12 / ≤10 / ≤10 → 读 candidate_tasks（失败则 `[]` 并 audit，**不** FAILED）→ Extractor → 全部 Validate → 一次 Apply → Processing + Audit。

规则预筛：空内容 / 收到 / 好的 / 嗯 / ok / 谢谢 / 纯表情 / `[图片]`。  
**不**用「失败 / 危险 / 风险」关键词直接建 Risk。

---

## 6. 必要的冻结测试守卫调整

G1/G2 曾断言「Risk 文件不存在」。G3 落地后这两处改为「Decision 不调用 Risk / Side-path 仍未接」，**Decision Offline 仍为 57**：

```text
tests/test_decision_engine_offline.py
  test_risk_engine_not_implemented
    → 断言 risk_sidepath.py 不存在；Decision Engine 源码不含 RiskEngine / risk_engine / risk_store

tests/test_decision_live_adapter.py
  test_m01_decision_yes_risk_not_run
    → Decision 仍建 1 条；不调用 RiskEngine；临时目录无 risk_store；无 risk_sidepath.py
```

未改 `decision_engine.py` / `decision_store.py` / `decision_extractor_client.py` / `DECISION_EXTRACTOR.md`。

---

## 7. 明确未做

```text
risk_sidepath.py
真实 Risk LLM
Live Risk
severity
自动 MITIGATED / RESOLVED / CLOSED
Reminder / Dashboard / 发微信
修改 listener / Trigger / Topic / Task / Decision Engine
```

---

## 8. 结论

```text
P5-G3 STATUS = COMPLETE
Risk Engine offline implementation = PASS
Production Risk side-path = NOT ENABLED
RISK_ENGINE_ENABLED default = false
```
