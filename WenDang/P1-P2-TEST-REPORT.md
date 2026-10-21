# P1 / P2 测试报告

> 日期：2026-09-20  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> **P0 STATUS = CLOSED**（冻结，本轮未改 P0 业务文件）  
> **P1 STATUS = CLOSED**  
> **P2 STATUS = CLOSED**  
> 关闭依据：`WenDang/P1-P2-CLOSURE-REPORT.md`  
> 未进入 P3 Topic Engine

---

## 1. 命令

```text
.\.venv\Scripts\python.exe -m unittest ^
  tests.test_conversation_store ^
  tests.test_agent_prompt_binding ^
  tests.test_p1_p2_audit ^
  tests.test_config_save ^
  tests.test_webui_data ^
  tests.test_p0_message_runtime ^
  tests.test_runtime_admit ^
  tests.test_pipeline ^
  tests.test_wechat_reply_format ^
  tests.test_webui_bot_process ^
  tests.test_llm_client
```

真机验收后复跑：**103 tests, OK**（未低于基线）。

`test_chat_contexts_keyed_by_nickname` 读取 gitignored 的实机 `chat_contexts.json`。按协议改绑 Prompt 会清 nickname 上下文，ceshi 历史从「企业战略与业务分析顾问」变为 A/B 哨兵。断言改为：nickname 主键 + 不串 QIYE 人格；若上下文含 A/B 哨兵则不再要求 企业_1 自称。不是放宽 Prompt fallback。

单独复跑 P0 原清单：

```text
.\.venv\Scripts\python.exe -m unittest ^
  tests.test_p0_message_runtime ^
  tests.test_runtime_admit ^
  tests.test_pipeline ^
  tests.test_wechat_reply_format ^
  tests.test_webui_bot_process ^
  tests.test_webui_data
```

结果：**59 tests, OK**。P0 原 59 项全部继续 PASS。

---

## 2. TEST-01 ～ TEST-13

| 编号 | 项 | 结果 |
|---|---|---|
| TEST-01 | LISTEN_LIST 三行迁移出 3 个 Conversation | **PASS** |
| TEST-02 | migration 执行 10 次仍是 3 个 | **PASS** |
| TEST-03 | display_name 修改前后 id 不变 | **PASS** |
| TEST-04 | 重复 display_name 拒绝保存 | **PASS** |
| TEST-05 | enabled=false 不进入 projected LISTEN_LIST | **PASS** |
| TEST-06 | PRIVATE / GROUP 按 wxid 回写 | **PASS**（单元 + 真机 TEST-LIVE-07） |
| TEST-07 | ceshi 与 哈共享 企业_1，仅一个 AgentConfig | **PASS** |
| TEST-08 | Prompt 不存在禁止 LLM 调用 | **PASS**（单元 + 真机 TEST-LIVE-09） |
| TEST-09 | 不得出现「你是一个乐于助人的助手。」 | **PASS**（单元 + 真机 TEST-LIVE-09） |
| TEST-10 | 引用中的 Prompt 删除 409 | **PASS**（单元 + 真机 TEST-LIVE-08） |
| TEST-11 | Prompt 内容改变 hash 改变 | **PASS** |
| TEST-12 | 日志含 conversation_id / agent_config_id / prompt_name / prompt_hash | **PASS**（单元 + 真机 CHAT_PROMPT extra） |
| TEST-13 | 现有 P0 tests 全部继续 PASS | **PASS**（59 OK） |

---

## 3. 真机验收（成功轮：2026-09-20 13:54–14:16）

上一轮 13:34–13:45 因主模型未配置，A/B 回复记 **NOT RUN**，生产已恢复。本轮主模型已配置（`coding-glm-4.7-free`，events：`AI 服务：主模型已配置`）。不粘贴密钥。

### 3.1 测试前状态

备份：

- `WenDang/_p1p2_live_backup_20260920-133407/`（生产 LISTEN/CONV/AGENT）
- `WenDang/_p1p2_live_backup_20260920-135355/`（用户写入主模型后）

正式 Prompt 未改：`QIYE.md`、`企业_1.md`。  
临时 Prompt（验收后已删）：`P1P2_TEST_A.md`、`P1P2_TEST_B.md`。

测试期绑定（已撤销）：

```text
ceshi  PRIVATE  conv_b35d9b7aaba2  → agt_6403ddd8c317 → P1P2_TEST_A
哈     GROUP    conv_2f82b3dbce7e  → agt_679873182096 → P1P2_TEST_B
QIYE   GROUP    conv_6fbe0f455b94  → agt_38b43979a544 → QIYE
```

ceshi / 哈拆开共享 Agent，否则改一个 Prompt 会连带改另一个。

### 3.2 Start / Stop

```text
13:54:47  STOPPED → STARTING（进程启动）；主模型已配置 coding-glm-4.7-free
13:54:53  微信连接：正常 扶级；监听对象数量：3；STARTING → RUNNING
13:58:27  RUNNING → STOPPING → STOPPED（交换绑定前）
13:59:14  STOPPED → STARTING → 13:59:19 RUNNING，监听 3
14:02:08  STOPPED；14:02:26 STARTING → 14:02:31 RUNNING，监听 2（哈 enabled=false）
14:04:19  STOPPED；14:04:44 STARTING → 14:04:49 RUNNING，监听 3（哈恢复）
14:12:42  RUNNING → STOPPING → STOPPED
```

WebUI `web_pid=19896` 全程存活。Stop 后 `state=STOPPED`，`alive=false`。

### 3.3 TEST-LIVE 逐项

| 项 | 结果 | 证据 |
|---|---|---|
| Start：STOPPED → STARTING → RUNNING | **PASS** | 13:54:47–53；微信 扶级 |
| TEST-LIVE-01 A Prompt：ceshi「测试P1P2」只回 `A-链路正常` | **PASS** | 13:56:23 INBOUND EXTERNAL；CHAT_PROMPT `conv_b35d9b7aaba2` / `agt_6403ddd8c317` / `P1P2_TEST_A` / `3b37c5035b63…`；13:56:41 outbound `A-链路正常`；13:56:56 发送成功 |
| TEST-LIVE-02 B Prompt：哈 @扶级「测试P1P2」只回 `B-链路正常` | **PASS** | 13:56:58 INBOUND EXTERNAL `@扶级 测试P1P2` at_triggered；CHAT_PROMPT `conv_2f82b3dbce7e` / `agt_679873182096` / `P1P2_TEST_B` / `afc3452bdde9…`；13:57:12 outbound `B-链路正常` |
| TEST-LIVE-03 交换绑定后回复互换 | **PASS** | Stop→换 agent_config_id→Start。14:00:11 ceshi → B / `agt_679873182096`；14:00:45 哈 → A / `agt_6403ddd8c317`。id 未重生 |
| TEST-LIVE-04 哈 enabled=false | **PASS** | 14:02:31 监听数量 2。14:02:31–14:04:19 无 哈 事件、无 B 回复。ceshi 仍回复（入站为 image，仍回 `B-链路正常`） |
| TEST-LIVE-05 哈 enabled=true 恢复且不影响 A | **PASS** | 14:04:49 监听 3。14:09:05 ceshi 仍 `B-链路正常`；14:09:25 哈 @扶级 回 `A-链路正常`（交换后绑定仍在） |
| TEST-LIVE-06 Conversation.id 稳定 | **PASS**（保存逻辑） | 未改真实微信昵称。全程三个 id 未重生。单元 TEST-03 仍 PASS |
| TEST-LIVE-07 wxid / type 落盘 | **PASS** | 见 3.4 |
| TEST-LIVE-08 引用中删除 Prompt | **PASS** | 同日 13:44 `POST /delete_prompt/P1P2_TEST_A.md` → HTTP **409** `PROMPT_IN_USE`（当时仍被 `agt_6403ddd8c317` 引用）。本轮恢复生产后删除 → **204** |
| TEST-LIVE-09 缺 Prompt 不得 fallback | **PASS** | RUNNING 时拿掉 `P1P2_TEST_B.md`。14:12:12 `PROMPT_FILE_NOT_FOUND`；outbound「当前智能体配置不可用，请检查 Prompt 配置。」；main_llm 步 5.99ms，无 `main/main_chat 成功`、无 token 成功；无「你是一个乐于助人的助手。」 |
| P0 真机 smoke | **PASS** | 见 3.5 |

### 3.4 TEST-LIVE-07 落盘（读 `config.local.json`）

```json
{
  "id": "conv_b35d9b7aaba2",
  "display_name": "ceshi",
  "platform_conversation_id": "wxid_rvzydi2xoif022",
  "conversation_type": "PRIVATE"
}
{
  "id": "conv_2f82b3dbce7e",
  "display_name": "哈",
  "platform_conversation_id": "51989154176@chatroom",
  "conversation_type": "GROUP"
}
{
  "id": "conv_6fbe0f455b94",
  "display_name": "QIYE",
  "platform_conversation_id": "58847495172@chatroom",
  "conversation_type": "GROUP"
}
```

### 3.5 P0 真机 smoke（本轮 A/B 会话）

| 项 | 结果 |
|---|---|
| ceshi inbound EXTERNAL NEW REPLY | **PASS**（13:56:23 等） |
| 机器人自回复 OUTBOUND SELF NO_ACTION | **PASS**（如 13:56:58 `direction_outbound`） |
| 一次回复一次 outbound | **PASS** |
| 明文 A/B，无 Markdown 包装 | **PASS** |
| Start 可拉起 / Stop 到 STOPPED | **PASS** |
| Stop 后 WebUI 仍存活 | **PASS**（`web_pid=19896`） |
| Stop 后再发不回 | **PASS**（14:12:42 后无真机回复；用户确认 sent_no_reply） |

---

## 4. 测试后恢复

已从 `PRETEST_SNAPSHOT` 恢复 CONVERSATIONS / AGENT_CONFIGS / LISTEN_LIST，保留当前模型 `coding-glm-4.7-free` 与 `DEEPSEEK_BASE_URL=https://aihubmix.com/v1`。未清空主模型密钥。

当前生产：

```text
ceshi → 企业_1   conv_b35d9b7aaba2  PRIVATE  wxid_rvzydi2xoif022     agt_679873182096
哈    → 企业_1   conv_2f82b3dbce7e  GROUP    51989154176@chatroom    agt_679873182096
QIYE  → QIYE     conv_6fbe0f455b94  GROUP    58847495172@chatroom    agt_38b43979a544
enabled 均为 true
P1P2_TEST_A / P1P2_TEST_B 已不在 CONVERSATIONS / AGENT_CONFIGS / LISTEN_LIST
prompts/ 仅剩 AI.md、QIYE.md、企业_1.md
GET /api/prompts → ["AI","QIYE","企业_1"]
Bot = STOPPED，WebUI web_pid=19896 仍存活
```

---

## 5. 关闭判定

```text
P1 STATUS = CLOSED
P2 STATUS = CLOSED
已写入 P1-P2-CLOSURE-REPORT.md
禁止进入 P3 Topic Engine
```
