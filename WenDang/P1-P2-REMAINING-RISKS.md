# P1 / P2 剩余风险

> 日期：2026-09-20  
> 自动测试：103 OK；P0 原 59 OK。  
> 真机验收（13:54–14:16）已通过，P1 / P2 **CLOSED**。  
> 下列为关闭后仍存在的残留，**不阻塞本关闭，也不构成进入 P3 的许可**。

---

## 1. 已关闭门槛（本轮真机）

- A/B Prompt 真机回复：ceshi=`A-链路正常`，哈 `@扶级`=`B-链路正常`
- 交换绑定后回复互换
- 哈 `enabled=false` → 监听 2、无 哈 事件；恢复后两边都回
- 缺 `P1P2_TEST_B.md` → `PROMPT_FILE_NOT_FOUND`，系统文案，无主 LLM token 成功
- wxid / type 落盘；PROMPT_IN_USE 409
- P0 真机 smoke；103 + 59 复跑 OK
- 生产绑定已恢复，临时 Prompt 已删

---

## 2. 已知残留（不阻塞 CLOSED）

1. **微信操作层仍用 display_name**  
   `AddListenChat(nickname=display_name)` 未改。同名联系人 `search_contact` 仍取第一条。内部 id 已存在，底层匹配风险还在。

2. **chat_contexts / 记忆文件仍按 nickname 分键**  
   业务主键已是 `conversation.id`。改 display_name 后旧上下文可能对不上。改绑 Prompt 时仍按 nickname 清上下文。本轮 A/B 已清空 ceshi 的 企业_1 历史自称。

3. **CONVERSATIONS 已在生产落盘**  
   `config.local.json` 含 CONVERSATIONS / AGENT_CONFIGS。LISTEN_LIST 仍是投影。

4. **keep_alive 丢监听时仍按 nickname 再 AddListenChat**  
   与 P0 一致。不会在该路径写配置。

5. **统一错误文案会发给用户**  
   Prompt 失败时返回「当前智能体配置不可用，请检查 Prompt 配置。」，不经 LLM。若产品希望完全 NO_REPLY，可再改 `processor` 识别该哨兵。

6. **记忆日志文件名仍可能 `prompt_mapping.get(user, user)`**  
   已切断 LLM 人格 fallback。记忆文件命名的 nickname fallback 不是 B2。

7. **WebUI 在 STOPPED 点「启动机器人」会先 saveConfig**  
   表单里空的 API Key 可能把 `.env` 写成未配置。真机 Start 应用 `POST /start_bot`，不要只点会清空密钥的 Start。

8. **ceshi 与 哈默认共享同一个 AgentConfig（企业_1）**  
   通过 WebUI 只改其中一个的 Prompt 会改到共享 Agent。A/B 隔离必须先拆开 `agent_config_id`。生产已恢复为共享 企业_1。

9. **未改真实微信昵称**  
   Conversation.id 稳定性由保存逻辑与单元 TEST-03 证明，没有在微信里改 ceshi 的显示名。

---

## 3. 明确未做

- Topic Engine / Extractor
- 数据库 PromptVersion
- 多平台
- 每群独立 Trigger
- 企业控制台改版
- 重写 QIYE.md

---

## 4. 下一步

P1 / P2 已 CLOSED。  
**禁止进入 P3 Topic Engine**，除非另开明确任务。
