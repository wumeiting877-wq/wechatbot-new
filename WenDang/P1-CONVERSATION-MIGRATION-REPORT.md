# P1 Conversation 迁移报告

> 日期：2026-09-20  
> 对照：`P1-CONVERSATION-MODEL-DESIGN.md`  
> 真实配置：`ceshi→企业_1`，`哈→企业_1`，`QIYE→QIYE`  
> **P1 STATUS = CLOSED**（真机见 `P1-P2-CLOSURE-REPORT.md`）

---

## 1. 权威源

```text
CONVERSATIONS     业务唯一权威源
LISTEN_LIST       兼容投影，禁止作为第二 SoT
```

规则：

- `CONVERSATIONS` 不存在或为空 → 从 `LISTEN_LIST` 生成 Conversation。
- `CONVERSATIONS` 已存在 → 不再从 LISTEN_LIST 重生；LISTEN_LIST 由 `project_listen_list()` 写出。
- 未删除 LISTEN_LIST。

---

## 2. ID 规则

第一次 LISTEN_LIST migration 可用：

```text
id = "conv_" + sha1("WECHAT|" + nickname)[:12]
```

此后：

- ID 是永久内部实体 ID。
- 修改 `display_name`（例如 `ceshi` → `ceshi测试`）**不得**重新 hash。
- 表单携带隐藏 `conversation_id`；保存时按 id 匹配更新。

TEST-03：**PASS**。

---

## 3. 对当前真实 LISTEN_LIST 的映射

输入：

```json
[
  ["ceshi", "企业_1"],
  ["哈", "企业_1"],
  ["QIYE", "QIYE"]
]
```

第一次 migration：

- 3 个 Conversation
- ceshi / 哈 共享同一个 AgentConfig（企业_1）
- QIYE 单独一个 AgentConfig

第二次、第 10 次：仍是这 3 个 id。TEST-01 / TEST-02：**PASS**。

本轮自动测试在内存中完成迁移，**没有把 CONVERSATIONS 写入生产 `config.local.json`**。首次 WebUI 保存或 Bot Start 才会落盘。

---

## 4. enabled 投影

```text
enabled=false  → 不进入 LISTEN_LIST
               → 不进入 user_names / prompt_mapping
               → 不 AddListenChat
```

不改 P0 `evaluate_inbound`。暂停发生在投影阶段。

TEST-05：`哈 enabled=false` 后投影只有 `ceshi`、`QIYE`。**PASS**（单元）。  
真机 TEST-LIVE-04：**PASS**（14:02:31 监听对象数量 2，至 Stop 无 哈 入站/回复）。  
真机 TEST-LIVE-05：**PASS**（14:04:49 监听 3；ceshi 与 哈均再回复）。

---

## 5. wxid / 类型回写

启动装配（`bot.py` main，AddListenChat 成功之后、消息循环之前）：

```text
wxid = chat._wxid
if wxid endswith "@chatroom" → GROUP
else → PRIVATE
platform_conversation_id = wxid
一次 save CONVERSATIONS
```

无法获得 wxid：日志 `CONVERSATION_ID_RESOLVE_FAILED`，不写错误值。

不在 listener / keep_alive 热路径写配置。

`AddListenChat(nickname=display_name)` 签名未改。

TEST-06 单元：**PASS**。

本轮真机 Start（2026-09-20 13:38，监听数量 3）后读取 `config.local.json`：

| display_name | id | platform_conversation_id | conversation_type |
|---|---|---|---|
| ceshi | conv_b35d9b7aaba2 | wxid_rvzydi2xoif022 | PRIVATE |
| 哈 | conv_2f82b3dbce7e | 51989154176@chatroom | GROUP |
| QIYE | conv_6fbe0f455b94 | 58847495172@chatroom | GROUP |

三个 id 均未重生。私聊 PRIVATE、群 GROUP 均为真实 wxid 落盘，**PASS**。  
群 **回复** 真机（哈 @扶级 走独立 Prompt）：**PASS**（TEST-LIVE-02 / 03 / 05）。

TEST-LIVE-06：未改真实微信昵称。保存逻辑携带隐藏 `conversation_id` 时，display_name 变成 `ceshi_renamed_live06` 后 id 仍为 `conv_b35d9b7aaba2`（未写入生产）。自动 TEST-03 仍 **PASS**。

---

## 6. 重名

第一阶段 WECHAT `display_name` 不允许重复。

保存时返回：

```text
VALIDATION_ERROR
存在重复监听对象名称。
```

禁止 `prompt_mapping` 后一条覆盖前一条。TEST-04：**PASS**。
