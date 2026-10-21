# P3-G1 延期事项

> 日期：2026-09-21  
> 说明：下列问题在实施中被看到，**不属于本轮**。未顺手重构。

---

## 不属于本轮

| 项 | 说明 |
|---|---|
| P3-G2 listener 旁路 | 明确禁止修改 `message/listener.py`。真实微信旁路等单独指令 |
| P4 Task / Risk / Decision | 禁止本轮开发 |
| Topic UI / 主题中心 / Dashboard | 禁止 |
| 自动 RESOLVED / WAITING / ARCHIVED | v1 只创建 ACTIVE |
| RAG / embedding / 向量库 / SQLite | 禁止 |
| Model Router | 仅预留模型名 `INHERIT` |
| 多 Agent | 禁止 |
| 改写 `QIYE.md` / `企业_1.md` | Chat 幻觉 JSON 仍可能出现，P3 不靠改 Chat Prompt 解决 |
| `chat_contexts` / 记忆 / `user_queues` 仍按 nickname 分键 | P1 残留，P3 不修 |
| `reply_to_message_id` 在真实 listener 常空 | quote 仍是字符串展开；不改 InboundMessage |
| 把 `TOPIC_ENGINE_ENABLED` 写入 `config.local.json` | 本轮只用模块常量，避免改生产配置 schema |
| 为 Chat Prompt 下拉框大改 Prompt 系统 | 已利用 `prompts/extractors/` 不递归特性隔离 |
| `agents_using_prompt` 会把 extractor 名与 chat 名放在同一匹配环 | 历史逻辑；本轮不改 |
| 生产环境真实 LLM Extractor 联调 | G1 离线用 Heuristic / 注入 llm_call；未接 listener，不打生产模型 |

以上全部 **不属于本轮**。
