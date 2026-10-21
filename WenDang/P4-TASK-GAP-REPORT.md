# P4 Task Engine Gap Report

> 日期：2026-09-21  
> 阶段：P4-G0  
> 依据：`P4-TASK-CURRENT-STATE-AUDIT.md`、`P4-TASK-DATA-MODEL-DESIGN.md`、`P4-TASK-ENGINE-DESIGN.md`、`P4-TASK-EXTRACTOR-PROMPT-DESIGN.md`、`P4-TASK-TEST-DATASET.md`  
> 分类：BLOCKER / REQUIRED / OPTIONAL / FUTURE / LIMITATION  
> BLOCKER = 不解决就不能进入 **P4-G1 实施**  
> 本轮 **未写生产业务代码**。下列不是测试 FAIL，是现状缺口与设计结论。

---

## 1. P4-G0 必须回答的 15 问

### 1. 当前项目是否已有真正 Task 能力？

**否。**

只有：Chat 口吻里的「整理任务」、个人 Reminder（会发微信）、Topic 文本里出现的动作词。  
没有 Task Store、没有 TASK_EXTRACTOR、没有 assignee/due 落盘。Topic Extractor 还主动剥离这些字段。

### 2. Task 应该绑定 Topic 还是 Conversation？

**两者都要。**

- `topic_id`：领域归属。研究问题是「已形成 Topic 中的工作事项」。同一会话真机已有多个 Topic。
- `conversation_id`：Topic Store / 未来 Task Store 都按 `conv_*` 分目录；没有它无法定位文件，也无法级联删除。

只绑其一都不成立。详见数据模型 §2。

### 3. Task 与 Message 的 Evidence 如何设计？

新建 `TaskMessageLink`：`CREATED_BY` + `UPDATED_BY` + `RELATED`。  
`COMPLETION_EVIDENCE` 不进 v1。  
`message_id` 指向 Topic Store 的 MessageRecord，不复制正文。  
没有 Link 的 Task 不允许写入。

### 4. 一条 Message 是否支持多个 Task？

**P4 v1 支持。** 上限 5。CASE-T04 期望 2 条。  
同一人连续步骤合并为 1 条。  
全部挂 **当前** `topic_id`（P3 单主 Topic 遗产，见 LIMITATION）。

### 5. assignee 第一版如何保存？

**`assignee_text` 原文。**  
无通讯录，禁止 `assignee_id`。禁止把发送者默认当负责人。  
无负责人且非「我 + 具体动作」→ 不建 Task（CASE-T02）。

### 6. due 第一版如何保存？

**`due_text` 原文，可空。**  
无截止仍可建 Task（CASE-T03）。

### 7. 是否需要绝对时间解析？

**v1 不需要写入。**  
预留 `due_at` 字段但默认空。LLM 禁止填。确定性解析器属 OPTIONAL/FUTURE。  
Reminder 的 LLM 时间解析禁止搬用。

### 8. Task v1 是否自动 DONE？

**否。** 只写 `OPEN`。完成陈述 → UNRELATED（CASE-T10）。  
对齐 P3 不自动 RESOLVED。

### 9. Task update 如何命中已有 Task？

输入 `existing_tasks` ≤ 10（本 Topic OPEN）。  
`TASK_UPDATE.task_id` 必须在该列表。  
引擎不做模糊合并；靠 Prompt + CASE-T05。

### 10. Task Store 用 JSON 还是 SQLite？

**独立 JSON Store：** `data/task_store/`。  
不上 SQLite，不放进 Topic 目录，不塞 `config.local.json`。

### 11. Task Processing 幂等如何实现？

`TaskProcessingRecord(message_id, task_processing_version)`。  
成功跳过；FAILED 可重试；Prompt 升级默认不重跑。  
不使用 P0 Dedupe，不复用 TopicProcessingRecord。

### 12. Task Extractor 如何和 Topic / Chat 隔离？

`prompts/extractors/TASK_EXTRACTOR.md` + 独立 parser client。  
不写 QIYE.md / TOPIC_EXTRACTOR.md。  
`store_context=false`。默认 Agent Extractor 名仍为 TOPIC_EXTRACTOR。

### 13. Task Engine 失败是否影响 Topic？

**否。** 隔离 FAILED。不改 Topic / Topic Link / TopicProcessing。

### 14. Topic 失败是否允许 Task 运行？

**否。** 无成功 `topic_id` 不跑。Topic 重试成功后再跑（当时尚无 Task 成功 processing）。

### 15. P4-G1 开工前有哪些 BLOCKER？

**无开放 BLOCKER。**  
P3 Evidence 足够抽工作事项；负责人可用原文表达；没有另一套 Task Engine；G1 离线不必改冻结的 P0/P1/P2/P3 模块。

未生成 `P4-G0-BLOCKER-REPORT.md`。

---

## 2. BLOCKER

定义：不解决就不能开始 P4-G1。

| ID | 项 | 状态 |
|---|---|---|
| — | — | **本轮无** |

曾评估、**不构成** G1 BLOCKER 的误报：

| 误报 | 为何不是 BLOCKER |
|---|---|
| 无企业通讯录 | 已决策只存 `assignee_text` |
| `reply_to` 常空 | 用 `recent_topic_messages`，与 P3 相同 |
| Topic 默认关闭 | G1 离线预置 Store，不接微信 |
| 真机挂钩要改 listener / sidepath | 那是以后 Gate，不是 G1（P3-G1 同样先离线） |
| MessageRecord 只在 Topic Engine 入库 | G1 fixture 写入 Topic Store 只读消费；不改 P3 语义 |
| P3 单主 Topic | LIMITATION，不阻塞「主题内能否抽出事项」 |

---

## 3. REQUIRED（G1 必须做）

| ID | 项 |
|---|---|
| R1 | `task_store.py`：Task / TaskMessageLink / TaskProcessingRecord / audit |
| R2 | `prompts/extractors/TASK_EXTRACTOR.md`（按设计稿落地，不改 Chat/Topic Prompt） |
| R3 | `task_extractor_client.py` 独立 parser；禁止复用 Topic STRIP 逻辑当最终 schema |
| R4 | `task_engine.py` 离线流水线：预筛 / 输入上限 / 校验 / apply / 隔离 |
| R5 | 只读使用 TopicStore 公开 API，不修改 `topic_store.py` |
| R6 | 离线测试 CASE-T01～T10 + 失败注入不影响 Topic |
| R7 | `TASK_ENGINE_ENABLED = false` 模块常量；不接 listener |
| R8 | 源码级禁止 `send_reply` / `wx.SendMsg` |
| R9 | 复跑 P0 / P1 / P2 / P3 回归 |

---

## 4. OPTIONAL

| ID | 项 |
|---|---|
| O1 | Heuristic Task Extractor，供无 LLM 的 fixture 红线（对标 P3 Heuristic） |
| O2 | `due_at` 确定性解析器（失败保持空）；**不**让 LLM 填 |
| O3 | CLI replay dump，不要 Web UI |
| O4 | Task 审计预览命令 |

---

## 5. FUTURE

| ID | 项 |
|---|---|
| F1 | Risk / Decision / Progress / Daily Report |
| F2 | 自动 DONE / IN_PROGRESS / CANCELLED 写入 |
| F3 | `COMPLETION_EVIDENCE` |
| F4 | 企业通讯录、`assignee_id`、`assignee_type` |
| F5 | 跨 Topic 改挂；P3 一条消息多 Topic |
| F6 | SQLite |
| F7 | 提醒 / 催办 / 发微信 / Notification |
| F8 | Dashboard / RAG / 多 Agent / Workflow |
| F9 | 真机 Task Side-path（需单独授权解冻 `topic_sidepath` 或 `listener`） |
| F10 | 升 `task_processing_version` 的 Prompt 重抽 |

---

## 6. LIMITATION（v1 接受，写进测试说明）

| ID | 限制 |
|---|---|
| L1 | P3 每条消息只有一个主 Topic。CASE-T04 两个事项会落在同一 `topic_id` |
| L2 | Topic 误分类时 Task 继承错误主题；P4 不修 Topic |
| L3 | 负责人只是文字，不能稳定对人、不能 @ |
| L4 | 无绝对截止时间，不能做到期扫描 |
| L5 | 完成了也不 DONE，OPEN 会累积 |
| L6 | `reply_to_message_id` 真机常空 |
| L7 | `MessageRecord.created_at` 格式不统一 |
| L8 | 生产默认 Topic 关闭 ⇒ 无新 MessageRecord ⇒ 真机无 Task 输入 |
| L9 | 不得把 Reminder 当 Task；两套数据永久分开 |
| L10 | 「我建议」即使后来被确认，T08 当条仍不建 Task；靠 T09 上下文 |
| L11 | G1 不改冻结文件，因此 **不能** 在本阶段验证「Topic worker 之后接 Task」的真机时序 |

---

## 7. 对「重大问题 STOP」清单的逐项回应

| 条款 | 结论 |
|---|---|
| P3 Topic 数据不足以支持 Task | **否**。Message + Link + Topic 足够抽事项 |
| Message Evidence 不足 | **否**。缺的是人员 ID 与绝对时间，不是「哪句话」 |
| 负责人无法可靠表达 | **否**。可靠表达是 `assignee_text`；稳定 ID 才做不到 |
| 现有项目已有另一套 Task Engine | **否** |
| 必须修改 P3 冻结语义 | **G1 否** |
| 必须修改 P0/P1/P2 | **否** |

继续设计/等待 G1 指令。不 STOP 于 BLOCKER。
