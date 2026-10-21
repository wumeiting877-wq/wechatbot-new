# P4-G1 实施报告

> 日期：2026-09-21  
> 项目：wechatbot-new  
> 阶段：**P4-G1**（Task Engine 离线最小实现 + 自动化验收）  
> 对照：`P4-TASK-DATA-MODEL-DESIGN.md`、`P4-TASK-ENGINE-DESIGN.md`、`P4-TASK-EXTRACTOR-PROMPT-DESIGN.md`

```text
P0 / P1 / P2 / P3 = CLOSED / COMPLETE（本轮未解冻）
P4-G0             = COMPLETE（设计基线）
P4-G1             = COMPLETE（离线实施）
```

---

## 1. 新增文件

```text
task_store.py
task_engine.py
task_extractor_client.py
prompts/extractors/TASK_EXTRACTOR.md

tests/test_task_store.py
tests/test_task_extractor.py
tests/test_task_engine_offline.py
```

文档：

```text
WenDang/P4-G1-G0-CURRENT-STATE-CHECK.md
WenDang/P4-G1-IMPLEMENTATION-REPORT.md
WenDang/P4-G1-TEST-REPORT.md
WenDang/P4-G1-REGRESSION-REPORT.md
WenDang/P4-G1-DEFERRED-ISSUES.md
WenDang/P4-G2-READINESS.md
```

未新增 `task_sidepath.py`。G1 不挂钩生产。

## 2. 修改文件

**冻结层：零修改。**

未改：

```text
message/*
bot_runtime.py
topic_store.py
topic_engine.py
topic_sidepath.py
topic_extractor_client.py
prompts/QIYE.md
prompts/企业_1.md
prompts/extractors/TOPIC_EXTRACTOR.md
conversation_store.py
agent_store.py
llm_client.py
config.local.json
```

`DEFAULT_EXTRACTOR_PROMPT_NAME` 仍为 `TOPIC_EXTRACTOR`。  
Task Engine 显式 `resolve_extractor_prompt("TASK_EXTRACTOR")`。

## 3. Task Store 路径

```text
data/task_store/
  conversations/{conversation_id}/
    tasks.json
    links.json
    processed.json
  task_engine_audit.jsonl
```

独立 JSON Store，复用 `store_io` 原子写 / FileLock。  
不上 SQLite / PostgreSQL / Redis / ORM。  
不写入 `topics.json`、`config.local.json`、`chat_contexts.json`、`CoreMemory`、`recurring_reminders.json`。

删除会话 Task 数据：`TaskStore.delete_conversation_task_data(conversation_id)`（不改 P3 delete）。

---

## 4. Task 数据模型

字段：

```text
id, conversation_id, topic_id
title, description
status                  # v1 只写 OPEN
assignee_text
due_text, due_at=""     # LLM / Engine 不写绝对时间
created_msg_id
confidence
created_at, updated_at
schema_version=1
```

规则：

- `conversation_id` 必须 `conv_*`
- `topic_id` 必须 `topic_*`
- 创建前 `require_topic`：Topic 必须存在且属于当前 Conversation
- 禁止 nickname / display_name 作外键
- 禁止 `assignee_id` / `assignee_wxid` / `assignee_type`
- 没有 Evidence（`created_msg_id`）不允许写入
- v1 禁止写入 `IN_PROGRESS` / `DONE` / `CANCELLED`

Task ID：

```text
task_id = "task_" + sha1(conversation_id|topic_id|created_msg_id|ordinal|created_at)[:12]
```

同一 Message 多 Task：`ordinal = 0, 1, 2…`。碰撞后缀 `_2`。禁止 title hash。

## 5. TaskMessageLink

```text
id, task_id, message_id
relation ∈ { CREATED_BY, UPDATED_BY, RELATED }
confidence, created_at
联合唯一 (task_id, message_id, relation)
```

v1 不实现 `COMPLETION_EVIDENCE`。  
NEW_TASK：当前消息 `CREATED_BY`，其它合法 evidence `RELATED`。  
TASK_UPDATE：当前消息 `UPDATED_BY`。

## 6. TaskProcessingRecord

```text
message_id + task_processing_version     # 唯一键
conversation_id, topic_id
extractor_prompt_name, extractor_prompt_hash
decision_summary, task_ids
processed_at, error
```

- 成功（`NEW_TASK` / `TASK_UPDATE` / `UNRELATED` / `SKIPPED`）重放跳过
- `FAILED` 允许同 version 重试
- Prompt hash 改变默认不自动重跑
- 不复用 P0 Dedupe，不复用 TopicProcessingRecord

---

## 7. assignee_text 规则

只存原文负责人文字。

允许：

1. 输入消息正文中的连续片段（如「王强」）
2. 等于 `current_message.sender_name`，且正文存在「我 + 明确动作」（排除「我建议」）

禁止：

- 发送者默认等于负责人（周敏下令 ≠ 周敏执行）
- 凭空生成人名
- 无负责人且非「我 + 动作」时建 `assignee_text=""` 孤儿 Task

非法负责人：整单 decision 校验失败，不落盘。

## 8. due_text 规则

LLM / Heuristic 只填 `due_text`（今天 16 点前、中午前、明天 12 点前、周五、月底前、尽快）。  
禁止输出 / 写入 `due_at`（字段保留为空字符串）。  
G1 不把「明天」换算成日期。  
TASK_UPDATE 空字段不覆盖已有 `due_text` / `assignee_text`。v1 不支持显式清除。

---

## 9. Prompt 隔离

| | Chat | Topic Extractor | Task Extractor |
|---|---|---|---|
| 文件 | `prompts/QIYE.md` | `prompts/extractors/TOPIC_EXTRACTOR.md` | `prompts/extractors/TASK_EXTRACTOR.md` |
| Loader | `resolve_chat_prompt` | `resolve_extractor_prompt("TOPIC_EXTRACTOR")` | `resolve_extractor_prompt("TASK_EXTRACTOR")` |
| Agent 默认 | `chat_prompt_name` | `extractor_prompt_name=TOPIC_EXTRACTOR` **未改** | Engine 显式文件名 |

`list_prompt_names()` 不递归，`TASK_EXTRACTOR` 不进 Chat 下拉。  
Task schema 未写入 QIYE / 企业_1 / TOPIC_EXTRACTOR。

## 10. Task Extractor Client

独立 `parse_task_extractor_json` / `normalize_decision` / allowed keys。  
**未**复用 `topic_extractor_client.parse_extractor_json`（会剥离 assignee/due）。

底层可复用 `get_extractor_response`：`store_context=false`，`temperature=0.2`，`max_tokens=1600`，独立 `TASK_EXTRACTOR_TIMEOUT_SEC`（不复用 Topic timeout 文件）。

剥离：`due_at` / `assignee_id` / `status` / `risks` / `progress` / `reminder` 等。  
`TASK_COMPLETE` / `DONE` 作为 decision → `INVALID_DECISION`，绝不自动 DONE。

G1 离线红线使用 `HeuristicTaskExtractor`。生产默认 `TaskExtractorClient`。Heuristic 不接微信。

输出 schema：`decisions` 1..5 条；无事项时一条 `UNRELATED`。

## 11. Task Engine 流水线

入口：`TaskEngine.process_record(conversation, topic, message)`。

```text
TASK_ENGINE_ENABLED = false          # 模块默认
enabled=True                         # 仅测试显式打开
```

流水线：

```text
1  校验 Conversation（conv_*）
2  校验 Topic 存在且属本会话
3  校验 MessageRecord 已在 Topic Store
4  校验 Topic 与 Conversation 一致
5  校验 Message 已有当前 Topic Evidence（TopicMessageLink）
6  TaskProcessing 已成功 → replay skip
7  OUTBOUND → SKIPPED
8  Rule Prefilter（空 / 收到 / 好的 / 嗯 / 1 / ok / 谢谢 / 纯表情 / [图片]）
   「收到，16 点前给结果」不是纯 ack，进入 Extractor
9  recent_topic_messages ≤ 12（仅本 Topic 已链接消息）
10 existing_tasks ≤ 10（本 Topic OPEN）
11 Build Task Extractor Input
12 Extractor
13 Validate 全部 decisions
14 全部合法后 Apply（commit_apply 内存合并再写盘，失败回滚）
15 Write TaskProcessing
16 Write Audit
```

**先完整 Validate，再写盘。** 避免 decision 1 已写、decision 2 FAIL 留半套。

NEW_TASK → `status=OPEN`。  
TASK_UPDATE → 不改 status / topic_id / conversation_id。  
UNRELATED → 零 Task 写入，仍写成功 Processing。

`1 Message → 0..5 Task`。同一人连续步骤合并为 1 个 Task。

---

## 12. Topic → Task 依赖

```text
Topic 成功 + 合法 topic_id + 当前 Message 有 Topic Evidence
→ 才允许 Task
```

不得在无 Topic 时猜归属。不得在 Topic FAILED 时继续跑。  
G1 离线由测试预置 Topic Store；不改 Topic Engine。

## 13. Failure Isolation

Extractor timeout / exception / invalid JSON / invalid task_id / invalid evidence / invalid assignee / Prompt missing / Prompt empty / Store write failure：

```text
Task = FAILED
isolated = True
不修改 Topic / Topic Link / TopicProcessing
不抛向 Chat
禁止 send_reply / wx.SendMsg
```

进程不崩。FAILED 可同 version 重试成功。

## 14. Idempotency

相同 Message 成功 Processing 重放 → 跳过，不重复 Task / Link。  
一条 Message 两 Task 重放 → 仍两条。  
TASK_UPDATE 重放 → 不重复 Link、不重复改 due。  
FAILED → 可重试。

---

## 15. 未做（明确）

```text
未接 listener / Topic Side-path
未改 P3 语义
未进入 Risk / Decision / Progress / 日报
未融合 Reminder，未催办，未发微信
未做 Dashboard / RAG / Embedding / SQLite
未自动 DONE / CANCELLED / IN_PROGRESS
未解析 due_at
未做企业通讯录 / assignee_id
```
