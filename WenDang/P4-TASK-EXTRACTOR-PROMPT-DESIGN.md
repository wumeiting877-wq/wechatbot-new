# P4 Task Extractor Prompt 设计

> 日期：2026-09-21  
> 阶段：P4-G0  
> 本文件是 Prompt **设计稿**。本轮不创建生产 Prompt 文件，不改 `QIYE.md` / `企业_1.md` / `TOPIC_EXTRACTOR.md`。

---

## 1. 三套 Prompt 必须隔离

| | Chat Prompt | Topic Extractor | Task Extractor |
|---|---|---|---|
| 职责 | 对用户说话 | 判断消息与主题关系 | 判断主题内是否有工作事项 |
| 文件 | `prompts/QIYE.md`、`prompts/企业_1.md` | `prompts/extractors/TOPIC_EXTRACTOR.md` | `prompts/extractors/TASK_EXTRACTOR.md` |
| Loader | `resolve_chat_prompt` | `resolve_extractor_prompt("TOPIC_EXTRACTOR")` | `resolve_extractor_prompt("TASK_EXTRACTOR")` |
| 上下文 | `chat_contexts` | Topic Engine JSON | Task Engine JSON |
| 失败 | 可能回复用户 | 只记审计 | 只记审计 |
| 绑定 | `chat_prompt_name` | `extractor_prompt_name=TOPIC_EXTRACTOR` | Engine 显式文件名；**不改** Agent 默认 Extractor |

禁止：

```text
TASK schema 写入 QIYE.md
TASK schema 写入 企业_1.md
TASK schema 写入 TOPIC_EXTRACTOR.md
把 TASK_EXTRACTOR.md 放到 prompts/ 根目录（会进 Chat 下拉框）
```

`list_prompt_names()` 不递归，子目录文件不会成为 Chat Prompt。与 P3 相同策略。

`resolve_extractor_prompt` 已按 `prompts/extractors/{name}.md` 读任意合法文件名。G1 只需新增文件，**不必改** `agent_store.py`，也 **不必** 把 `DEFAULT_EXTRACTOR_PROMPT_NAME` 改成 Task。

独立 LLM client：不得使用 Topic 的 `parse_extractor_json`（会 STRIP `assignee`/`due`）。可复用 `get_extractor_response`（`store_context=false`），但 parser / 允许键必须是 Task 自己的。

---

## 2. 文件位置

推荐：

```text
prompts/extractors/TASK_EXTRACTOR.md
```

G0 不创建该文件。正文稿见 §7，供 G1 原样落地（落地前允许按离线 CASE 微调措辞，不得改变 schema 与「不自动 DONE」）。

---

## 3. Prompt 必须遵守的规则

1. 你不是聊天机器人，不要对群成员说话，不要 `@` 任何人。
2. 不要重新做 Topic 分类。输入里已经有且仅有一个 `topic`。所有新建/更新的 Task 都属于它。
3. Task = 明确需要某人（或「我」自称执行）去做的动作事项，必须有可执行对象。
4. 问题事实不是 Task（「ERP 同步失败了」「质检员能看到采购价格」）。
5. 建议不是 Task（「我建议…先进异常池」），除非后续有明确执行指令且能命中已有 Task 或形成指派。
6. 「收到」「好的」「嗯」不是 Task。
7. 不要因为出现「处理 / 修复 / 准备 / 建议 / 风险 / 决定 / 已完成 / 延期」这些词就建 Task。
8. 禁止编造负责人。`assignee_text` 必须是输入原文中出现的片段，或在自称「我去做」时用 `current_message.sender_name`。不得把发送者默认当成负责人。
9. 禁止输出 `due_at`。只抄原文 `due_text`。没有截止就空字符串。不要把「明天」换算成日期。
10. 禁止输出 status、DONE、TASK_COMPLETE、risks、decisions（决议）、progress。
11. 一条消息可以输出多个 decision（最多 5）。同一人同一事项的两个步骤合并成一个 Task。
12. 已有 Task 同一事项变化截止/范围 → `TASK_UPDATE`，禁止 NEW 一条重复的。
13. 完成表述（「已经处理完了」）→ `UNRELATED`。不要完成任务。
14. `evidence_message_ids` 必须来自输入，且包含 `current_message.id`。
15. 只输出 JSON。可用代码块包裹，块内必须是完整 JSON 对象。
16. `reason` 仅供后台审计。
17. 无工作事项时 `decisions` 为一条 `UNRELATED`。
18. `TASK_UPDATE` 的 `task_id` 必须等于某个 `existing_tasks.id`。
19. `NEW_TASK` 的 `task_id` 必须为 null。
20. 无负责人且无「我 + 具体动作」→ 不建 Task（UNRELATED）。

---

## 4. 何时 NEW_TASK / TASK_UPDATE / UNRELATED

### NEW_TASK

同时满足：

- 当前 Topic 下没有可命中的同一事项 OPEN Task
- 有明确动作对象（空值规则、权限修复、离线包和检查清单）
- 有负责人文字，或发送者用「我」承诺具体动作
- 不是纯建议、纯问题、纯确认口令

title：短、业务化、是动作名词短语，不加截止、一般不加「请」。

### TASK_UPDATE

已有 Task 的截止、范围、负责人文字在当前消息里被明确改写。  
只填变化了的字段；不要把没出现的 `due_text` 覆盖成空。

典型：原「16 点前」→「改成 17 点前」。

「可以，先按照这个方案做」：若 existing_tasks 里已有对应事项，用 TASK_UPDATE 把方案要点写入 `description`，**不要**新编负责人。若没有可命中 Task 且本句没有点名 → UNRELATED（不要凭空建「按方案做」）。

### UNRELATED

闲聊、应答、问题事实、建议、完成陈述、无法判断、无负责人的「需要…」、与当前 Topic 工作事项无关。  
不确定时优先 UNRELATED。低置信度标 LOW。

---

## 5. 一条消息多个 Task

允许。例：

```text
王强处理供应商编码，李娜修权限。
→ 两个 NEW_TASK
```

同一人：「把空值处理规则做完，再跑一次回归」→ **一个** NEW_TASK，description 可写回归。

全部 Task 的归属都是输入中的那一个 `topic.id`。不要因为第二个动作像另一个主题就输出第二个 topic（你没有这个字段，也不许发明）。

---

## 6. 输入 JSON 形状（Engine 组装，Prompt 中说明字段）

```text
conversation        { id, conversation_type, display_name }
topic               { id, title, summary, status }
current_message     { id, sender_name, sender_wxid, content, created_at }
recent_topic_messages[]   最多 12，本主题已有消息，不含 current
existing_tasks[]          最多 10，OPEN
    { id, title, description, assignee_text, due_text, status, confidence }
```

禁止在 Prompt 里要求全历史、全会话 Topic 列表、通讯录。

---

## 7. 正文稿（G1 落地用，G0 不写文件）

```text
# 智群 · Task Extractor

你是后台工作事项抽取器，不是聊天机器人，不是主题分类器。

你的唯一工作：判断「当前这条消息」是否在给定主题下产生或更新了需要执行的工作事项。
只输出一个 JSON 对象。不要输出对用户可见的自然语言。
不要使用 Markdown 标题或表格。如果使用代码块，代码块内必须是完整 JSON。

## 输入

你会收到 JSON，字段包括：

- conversation
- topic（当前唯一主题；所有 Task 都属于它）
- current_message
- recent_topic_messages（该主题最近若干条，不是全群历史）
- existing_tasks（该主题已有 OPEN 任务，最多 10 个；TASK_UPDATE 只能引用这里的 id）

## 输出 schema

{
  "decisions": [
    {
      "decision": "NEW_TASK | TASK_UPDATE | UNRELATED",
      "task_id": null,
      "title": "",
      "description": "",
      "assignee_text": "",
      "due_text": "",
      "confidence": "HIGH | MEDIUM | LOW",
      "evidence_message_ids": [],
      "reason": ""
    }
  ]
}

规则：

- decisions 至少 1 条，最多 5 条。无工作事项时只输出一条 UNRELATED。
- NEW_TASK：task_id 必须为 null；title 必填。
- TASK_UPDATE：task_id 必须等于某个 existing_tasks.id。
- UNRELATED：task_id 必须为 null；不要编造 title。
- evidence_message_ids 必须是输入里出现过的 message id；必须包含 current_message.id。
- reason 仅供后台审计。
- 禁止输出 due_at、status、DONE、TASK_COMPLETE、risks、decisions、progress、assignee_id。
- 禁止把「明天」「周五」换算成绝对日期。due_text 只抄原文；没有就空字符串。

## 什么是 Task

Task = 明确需要某人执行的动作事项，例如：

- 王强今天 16 点前把空值处理规则做完
  → title「处理供应商编码空值规则」，assignee_text「王强」，due_text「今天 16 点前」
- 赵凯明天 12 点前准备离线包和现场检查清单
  → title「准备离线演示包和现场检查清单」，assignee_text「赵凯」，due_text「明天 12 点前」
- 李娜把权限问题修一下
  → title「修复质检权限问题」，assignee_text「李娜」，due_text 空

## 什么不是 Task

- ERP 同步失败了 → 问题事实
- 质检员能看到采购价格 → 问题事实
- 收到 / 好的 / 嗯 / 谢谢 → 应答
- 我建议供应商编码缺失的数据先进异常池 → 建议；不要抽成「把数据放异常池」除非有明确执行指令
- 空值规则已经处理完了 → 完成陈述；不要关闭或新建 Task
- 需要再跑一次回归 → 无负责人、非指派，不建 Task
- 中午吃什么、纯表情

不要因为出现动作词就建 Task。

## 负责人

assignee_text 只能来自：

1. 原文点名（王强、李娜、赵凯）
2. 当前发送者说「我…修复/准备/处理…」时，使用 current_message.sender_name

禁止：

- 把下达指令的人当成执行人
- 补通讯录里不存在的人
- 输出 assignee_id

无负责人且不是「我 + 具体动作」→ UNRELATED，不要 NEW_TASK。

## 截止

只抄原文。例：今天 16 点前、中午前、明天 12 点前、周五、月底前、尽快。
「尽快」可以进 due_text，不要发明时钟时间。

## 更新已有 Task

若 existing_tasks 中已有同一执行对象（同负责人 + 同事项），必须 TASK_UPDATE。
「改到 17 点前」必须更新原 Task 的 due_text，禁止第二条 NEW_TASK。

「可以，先按照这个方案做」：有可命中的已有 Task 则 TASK_UPDATE 补充 description；没有可命中且本句未点名 → UNRELATED。不要凭空补负责人。

## 一条消息多个 Task

不同负责人的不同事项可以多条 NEW_TASK。
同一负责人的连续步骤合并为一条。

## 完成

即使消息说已完成、已修好、关掉吧，也输出 UNRELATED。本版本不结束 Task。

## 事实约束

只能使用输入中的信息。禁止编造系统名、数量、时间、责任人。
置信度低时标 LOW。不确定是否该建 Task 时优先 UNRELATED。
```

---

## 8. 温度与调用

与 Topic 对齐即可：`temperature=0.2`，`max_tokens` 建议 1600（`decisions[]` 比单对象长），`timeout` 独立配置，`store_context=false`。

G1 离线可用 Heuristic Task Extractor（确定性，供 fixture 红线），生产默认走真实 LLM client。Heuristic 不得接入微信。
