# P5-G1 实施报告

> 日期：2026-09-22  
> 阶段：P5-G1 Decision Engine Offline  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 对照：`P5-G1-G0-CURRENT-STATE-CHECK.md`、`P5-DECISION-DATA-MODEL-DESIGN.md`、`P5-DECISION-ENGINE-DESIGN.md`、`P5-EXTRACTOR-ARCHITECTURE-DESIGN.md`

---

## 1. 本轮做了什么

在已经形成的 Topic 上，离线识别「大家最终确认采用了什么」，并保存为结构化、可追溯、不可静默覆盖的 Decision。

新增文件：

```text
decision_store.py
decision_extractor_client.py
decision_engine.py
prompts/extractors/DECISION_EXTRACTOR.md
tests/test_decision_store.py
tests/test_decision_extractor.py
tests/test_decision_engine_offline.py
```

未接微信。未改 listener / Trigger / Topic / Task 语义。未实现 Risk Engine。

---

## 2. Decision Store

路径：

```text
data/decision_store/
  conversations/{conversation_id}/
    decisions.json
    links.json
    processed.json
  decision_engine_audit.jsonl
```

实体：

| 对象 | 要点 |
|---|---|
| Decision | `conv_*` + `topic_*`；禁止 `task_id`；v1 只写 `RECORDED` |
| DecisionMessageLink | `CREATED_BY` / `RELATED`；禁止 `UPDATED_BY` / `CONFIRMED_BY` / `SUPERSEDED_BY` |
| DecisionProcessingRecord | 主键 `message_id + decision_processing_version`；成功 skip；FAILED 可同 version 重试 |

ID：

```text
dec_ + sha1(conversation_id|topic_id|created_msg_id|ordinal|created_at)[:12]
```

创建前校验 Topic 存在且属于当前 Conversation。CREATED_BY 必须指向 Topic Store 的 MessageRecord。无 Evidence 不落盘。

正文不可原地覆盖：改方案 = 新 Decision + `supersedes_decision_id`；旧行保持 `RECORDED` 且原文不变。

---

## 3. Decision Extractor

`prompts/extractors/DECISION_EXTRACTOR.md` 独立存在，不进入 Chat 下拉。

规则已写入 Prompt：

```text
你不是聊天机器人
不要重新做 Topic 分类
建议不是 Decision
收到/好的/嗯/行。不是 Decision
问题事实不是 Decision
Task 指派不是 Decision
Risk 陈述不是 Decision
确认句才是 CREATED_BY
方案改口 → NEW_DECISION + supersedes_decision_id
禁止 DECISION_UPDATE
禁止自动 SUPERSEDED/CANCELLED
不确定 → UNRELATED
```

`decision_extractor_client.py` 有独立 `parse_decision_extractor_json` / normalize / validate / allowed keys。  
不复用 Topic parser、不复用 Task parser。

离线主路径：`HeuristicDecisionExtractor`。真实 LLM 留到 P5-G2。  
底层可复用 `get_extractor_response`（`store_context=false`；temperature=0.2；max_tokens=1400；timeout≈20s）。

---

## 4. Decision Engine

离线入口：`DecisionEngine.process_record(conversation, topic, message)`。

```text
DECISION_ENGINE_ENABLED = false
```

测试传入 `enabled=True`。

流水线：校验 Conversation / Topic / Message / Topic Evidence → 成功 Processing 重放 skip → OUTBOUND SKIPPED → 规则预筛 → 窗口 ≤12 / existing_decisions ≤10 → Extractor → **全部 Validate 后再一次 Apply** → Processing + Audit。

预筛精确匹配应答（收到 / 行。 / 可以。），**不会**把「可以，就按照异常池方案执行。」短路掉。

引擎始终把当前消息写成 CREATED_BY；建议句最多 RELATED。

---

## 5. 明确未做

```text
decision_sidepath.py
真实 Decision LLM
真机 Decision
Risk Engine
Decision UI
自动 CANCELLED / 写 SUPERSEDED 状态
跨 Topic Decision
Dashboard / Reminder
修改 listener / topic_sidepath / task_sidepath
```

---

## 6. 冻结层

未修改：

```text
message/*
bot_runtime.py
topic_*.py
task_*.py
prompts/QIYE.md
prompts/企业_1.md
TOPIC_EXTRACTOR.md
TASK_EXTRACTOR.md
conversation_store.py
agent_store.py
llm_client.py
tests/fixtures/p5/risk_cases.json
```

原则：**P5-G1 = 新增，不重构。**
