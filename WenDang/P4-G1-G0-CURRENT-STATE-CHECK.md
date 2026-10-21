# P4-G1 Gate 0 当前状态核对

> 日期：2026-09-21  
> 阶段：P4-G1 实施前 READ ONLY  
> 方式：对照 P4-G0 七份设计文档与当前真实源码，未改业务代码。  
> 范围：Task Engine **离线最小实现**。不接微信，不改 listener / Topic Side-path，不进入 Risk / Decision。

---

## 0. 冻结基线

```text
P0 STATUS            = CLOSED
P1 STATUS            = CLOSED
P2 STATUS            = CLOSED

P3-G0 STATUS         = COMPLETE
P3-G1 STATUS         = COMPLETE
P3-G2 STATUS         = COMPLETE

P4-G0 STATUS         = COMPLETE
P4-G1                = 本轮开始实施（Gate 0 只读核对）
```

依据：`P0-CLOSURE-REPORT.md`、`P1-P2-CLOSURE-REPORT.md`、`P3-G2-CLOSURE-REPORT.md`、`P4-NEXT-IMPLEMENTATION-PLAN.md`。

生产默认：

```text
TOPIC_ENGINE_ENABLED = false   （topic_engine.py 模块常量）
TASK_ENGINE          = 尚未实施
```

---

## 1. 必须确认的 10 项

| # | 核对项 | 源码证据 | 结论 |
|---|---|---|---|
| 1 | 不存在 `task_engine.py` | 仓库检索 0 个生产实现文件 | **确认** |
| 2 | 不存在 `task_store.py` | 同上 | **确认** |
| 3 | 不存在 `task_extractor_client.py` | 同上 | **确认** |
| 4 | 不存在生产 `TASK_EXTRACTOR.md` | `prompts/extractors/` 仅有 `TOPIC_EXTRACTOR.md` | **确认** |
| 5 | P3 Topic 数据模型未被修改 | `topic_store.py` 仍无 assignee/due/tasks；Topic 字段与 P3-G1 一致 | **确认** |
| 6 | P3 Topic Store 公开接口仍能读 Topic / Message / Link | `get_topic` / `list_messages` / `get_message` / `links_for_topic` 均存在 | **确认** |
| 7 | P0/P1/P2/P3 冻结文件无本轮未授权 diff | Gate 0 未改这些文件；路径仍为 P3 关闭时的模块 | **确认** |
| 8 | Task fixture 仍存在 | `tests/fixtures/task_engine/zhiqun_task_cases.json`（CASE-T01～T10 + T09b） | **确认** |
| 9 | 无第二套 Task Engine | Reminder / Chat 口吻「任务」不是 Engine；无并行 task_* 模块 | **确认** |
| 10 | 无需修改 P3 即可完成离线 G1 | 离线入口可 `process_record(conversation, topic, message)`；Message/Topic/Link 由 fixture 写入 Topic Store 只读消费 | **确认** |

冻结文件（本轮原则上禁止修改，Gate 0 未改）：

```text
message/identity.py
message/dedupe.py
message/outbound.py
message/trigger.py
message/reply_format.py
message/listener.py
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
```

`resolve_extractor_prompt("TASK_EXTRACTOR")` 已按文件名读取 `prompts/extractors/{name}.md`。  
`DEFAULT_EXTRACTOR_PROMPT_NAME = "TOPIC_EXTRACTOR"` 保持。  
`get_extractor_response` 已是 `store_context=false` 的独立调用，Task parser 不得复用 `parse_extractor_json`（会剥离 assignee/due）。

---

## 2. 与 P4-G0 设计的一致性

| 设计文件 | 对照结果 |
|---|---|
| `P4-TASK-CURRENT-STATE-AUDIT.md` | 仍无真正 Task 能力；Topic Store Evidence 足够 |
| `P4-TASK-DATA-MODEL-DESIGN.md` | 独立 JSON Store `data/task_store/`；`assignee_text` / `due_text`；v1 只写 OPEN |
| `P4-TASK-ENGINE-DESIGN.md` | 离线流水线；Topic 成功闸门；失败隔离；不发微信 |
| `P4-TASK-EXTRACTOR-PROMPT-DESIGN.md` | 正文稿可原样落地；三套 Prompt 物理隔离 |
| `P4-TASK-TEST-DATASET.md` | CASE-T01～T10 与 fixture 语义一致 |
| `P4-TASK-GAP-REPORT.md` | 开放 BLOCKER = 无 |
| `P4-NEXT-IMPLEMENTATION-PLAN.md` | G1 允许新增 Store / Client / Engine / Prompt / 测试 |

结构级偏差：**无**。

---

## 3. 已知且不阻塞 G1 的限制（不修）

1. 真机 Task Side-path 需要改 `topic_sidepath.py` 或 `listener.py` → **G1 不做**。  
2. 无企业通讯录 → 只存 `assignee_text`。  
3. 不解析 `due_at`。  
4. P3 单主 Topic 遗产：CASE-T04 两个 Task 同挂当前 `topic_id`。  
5. `TOPIC_ENGINE_ENABLED=false` 时生产无新 MessageRecord → 真机无 Task 输入（G1 离线预置）。  
6. Reminder 不是 Task，两套存储永久分开。

---

## 4. Gate 0 结论

```text
GATE 0 = PASS
P4-G1-BLOCKER-REPORT.md = 不生成
允许继续 G1 实施
```

理由：当前确实没有 Task Engine；P0/P1/P2/P3 冻结基线仍在；真实代码与 P4-G0 文档一致；离线 G1 不需要解冻 P3。
