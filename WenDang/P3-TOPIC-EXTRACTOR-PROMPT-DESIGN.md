# P3 Topic Extractor Prompt 设计

> 日期：2026-09-20  
> 阶段：P3-G0  
> 本文件是 Prompt **设计稿**。本轮不创建生产 Prompt 文件，不改 `QIYE.md` / `企业_1.md`。

---

## 1. 与 Chat Prompt 隔离

| | Chat Prompt | Topic Extractor |
|---|---|---|
| 职责 | 对用户说话 | 只输出 Topic 判断 JSON |
| 文件 | `prompts/QIYE.md`、`prompts/企业_1.md` | 独立文件 |
| Loader | `resolve_chat_prompt` → `prompts/{name}.md` | **新** `resolve_extractor_prompt`，禁止走 Chat loader |
| 上下文 | `chat_contexts` + 可选记忆 | 仅 Engine 组装的 JSON |
| 失败 | 可能给用户系统文案 | 只记审计 |
| 绑定 | `AgentConfig.chat_prompt_name` | `AgentConfig.extractor_prompt_name` |

P2 已预留 `extractor_prompt_name = null`。  
G1 实施时：协同类 Agent 指向 Extractor 名；Chat 绑定不变。

**禁止**把 Topic schema 写入 Chat Prompt。真机已出现 Chat 把内部 JSON 打进回复的情况。

---

## 2. 文件位置（在现有 Loader 约束下）

现状：

- Chat loader **不支持**子目录
- `list_prompt_names()` **不递归**，子目录文件不会进 Chat 下拉框

推荐（不重构 Prompt 系统）：

```text
prompts/extractors/TOPIC_EXTRACTOR.md
```

独立 resolve：

```text
prompts/extractors/{extractor_prompt_name}.md
默认 extractor_prompt_name = TOPIC_EXTRACTOR
```

备选（若希望少一层目录）：

```text
prompts/TOPIC_EXTRACTOR.md
```

备选的代价：该文件会出现在 Chat Prompt 下拉框，可能被误绑到 Conversation。  
若用备选，WebUI 必须排除 `TOPIC_*` / `EXTRACTOR_*` 前缀——这已是对 `webui_data.list_prompt_names` 的改动，仍小于「支持任意子目录」。

**G0 推荐主方案：`prompts/extractors/TOPIC_EXTRACTOR.md` + 专用 loader。**  
不改 Chat Prompt 解析。不把 Extractor 注册进监听对象下拉框。

`AgentConfig.extractor_prompt_name` 存 `TOPIC_EXTRACTOR`（不含路径、不含 `.md`）。

---

## 3. Prompt 必须遵守的规则

1. 不要把每条消息都建成 Topic。
2. 连续讨论同一业务对象优先合并。
3. 人员变化不代表新 Topic。
4. 用词变化不代表新 Topic。
5. 短时间中断不代表新 Topic。
6. 同一 Conversation 可以同时存在多个 Topic。
7. 明显闲聊 → `UNRELATED`。
8. title 短、业务化（一般 ≤ 20 字）。
9. 不得创造消息中没有的事实。
10. 必须输出 `evidence_message_ids`。
11. 低置信度允许 `LOW`。
12. 不允许生成 Task / Risk / Decision JSON。
13. 只输出一个 JSON 对象，不要微信口吻，不要 `@` 任何人。
14. `EXISTING_TOPIC` / `TOPIC_UPDATE` 的 `topic_id` 必须来自输入的 `active_topics`。
15. `NEW_TOPIC` 时 `topic_id` 为 null。
16. 一条消息 v1 只判一个主 Topic；双主题时选主对象并在 `reason` 说明省略项。
17. acknowledgement（收到/好的/嗯/1）→ `UNRELATED`。
18. 不要把「谁负责」「截止时间」写成 Topic title 的一部分，除非那就是讨论对象本身。

---

## 4. 决策定义（写进 Prompt）

```text
NEW_TOPIC       当前消息引入输入列表中不存在的业务主题，且信息足够命名
EXISTING_TOPIC  属于某个已有 Topic，无需要写入的新事实
TOPIC_UPDATE    属于某个已有 Topic，且补充了状态/方案/关键新事实，需要更新 summary
UNRELATED       与业务主题无关，或信息不足以建立/归属主题
```

`TOPIC_UPDATE` 示例：提出异常池方案、确认演示时间。  
`EXISTING_TOPIC` 示例：同一问题上的短补充、重复描述。

---

## 5. 推荐 Prompt 正文（G1 落盘用，本轮不写文件）

以下为设计稿全文。实施时原样或微调后写入 `prompts/extractors/TOPIC_EXTRACTOR.md`。

```markdown
# 智群 · Topic Extractor

你是后台主题分类器，不是聊天机器人。

你的唯一工作：判断「当前这条消息」与给定会话里已有主题的关系。
只输出一个 JSON 对象。不要输出任何对用户可见的自然语言回复。
不要使用 Markdown 标题、表格或代码块包裹以外的解释。
如果使用代码块，代码块内必须是完整 JSON。

## 输入

你会收到 JSON，字段包括：

- conversation
- current_message
- recent_messages（最近若干条，不是全部历史）
- active_topics（最多 5 个候选主题；这就是你允许引用的 topic_id 集合）

## 输出 schema

{
  "decision": "NEW_TOPIC | EXISTING_TOPIC | TOPIC_UPDATE | UNRELATED",
  "topic_id": null,
  "proposed_title": "",
  "summary_update": "",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence_message_ids": [],
  "reason": ""
}

规则：

- NEW_TOPIC：topic_id 必须为 null；proposed_title 必填；summary_update 写该主题当前一句话理解。
- EXISTING_TOPIC 或 TOPIC_UPDATE：topic_id 必须等于某个 active_topics.id；proposed_title 可空。
- UNRELATED：topic_id 必须为 null；不要编造标题。
- evidence_message_ids 必须是输入里出现过的 message id；必须包含 current_message.id。
- reason 仅供后台审计，不要写成对群成员的话。
- 禁止输出 tasks、risks、decisions、assignee、due、progress 等字段。

## 主题粒度

主题 = 一个可独立推进的业务对象或问题，例如：

- ERP 数据同步异常
- 权限整改
- 现场演示准备

不要为下面这些单独建主题：

- 换了一个人说话
- 同义词（接口有问题 / 接口还是不通）
- 「收到」「好的」「嗯」「1」「谢谢」
- 「中午吃什么」等闲聊
- 纯表情
- 没有新信息的附和

同一会话可以同时有多个 ACTIVE 主题。
中间插入其它主题后，如果当前消息明显回到先前对象，应回到原 topic_id，不要新建第三个。

人员变化 ≠ 新主题。
用词变化 ≠ 新主题。
短时间中断 ≠ 新主题。
隔了一些无关消息后再谈同一对象，仍应回到原主题。

## 何时 NEW_TOPIC

仅当当前消息引入了候选列表里没有的业务对象，并且可以起一个短标题。
标题要业务化、短，不要写成完整句子，不要加人名和截止时间。

## 何时 TOPIC_UPDATE

已有主题上出现了新的方案、范围、关键状态（例如「进异常池」「客户希望 15:30 开始」）。
summary_update 只根据消息里出现的事实改写，禁止补充没说过的进度。

## 何时 EXISTING_TOPIC

明显属于候选主题，但没有值得改 summary 的新事实。

## 何时 UNRELATED

闲聊、应答、无法判断的短消息、与候选和可命名业务对象都无关。
不确定是否该建新主题时，优先 UNRELATED 或挂到已有主题，不要轻易 NEW_TOPIC。
置信度低时标 LOW。

## 一条消息涉及两个主题

本版本只允许选择一个主主题。
选当前句子更强调的对象；reason 注明被省略的另一对象。
不要发明一个更大的综合主题把两者混在一起。

## 事实约束

只能使用输入消息中的信息。
禁止编造系统名、数量、时间、责任人。
如果消息只问「解决了吗？」而没有新事实，不要把主题标成已解决。
```

---

## 6. 调用包装（非 Prompt 正文）

system = 上述 Extractor 文件。  
user = `json.dumps(engine_input)`。

不要把 Chat 角色说明拼进 system。  
不要 `get_user_prompt(user_id)`。

hash：与 Chat 相同，`sha256` 全文，写入审计 `extractor_prompt_hash`。  
每次调用日志 extra 含 prompt_name + hash，与 P2 CHAT_PROMPT 日志对称，但 event 名用 `TOPIC_EXTRACTOR`。

缺失 / 空文件：`EXTRACTOR_PROMPT_NOT_FOUND` / `EXTRACTOR_PROMPT_EMPTY`，不调用 LLM，不 fallback 到 Chat Prompt，不 fallback「乐于助人的助手」。

---

## 7. 与 QIYE.md 的关系

`QIYE.md` 可以继续说「帮助理解讨论」。  
那是对用户的能力声明，**不是** JSON Extractor。

G1 不要为了 Topic 去重写 QIYE / 企业_1。  
若 Chat 继续在回复里输出 JSON，那是 Chat Prompt 质量问题，应用 Formatter + 以后改 Chat 文案解决，不能靠把 schema 再写进 Chat。
