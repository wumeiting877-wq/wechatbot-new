# P1 Conversation 模型设计

> 日期：2026-09-20  
> 对照：`P1-P2-CURRENT-STATE-AUDIT.md`、实施方案第 35 节  
> 原则：不改 P0；不删除 LISTEN_LIST；微信操作第一阶段仍可用 nickname  
> 本文件是设计，不是已经落地的代码

---

## 1. 为什么不用 Group 当第一实体

当前项目同时服务：

- 微信私聊（现场 `ceshi`、`哈`）
- 微信群（配置结构与私聊相同，运行时靠 `@chatroom` 识别）

如果第一实体叫 Group，私聊只能伪装成群。实施方案写的是 Group，但当前仓库更适合：

```text
Conversation
├── PRIVATE
└── GROUP
```

Group 作为 `conversation_type=GROUP` 的 Conversation。不要为了名字把 ceshi 写成群。

---

## 2. 推荐模型（第一阶段只实现 WECHAT）

```text
Conversation

id                        conv_xxxxxxxx          内部主键，业务层只用这个
platform                  WECHAT                 枚举预留，代码只写 WECHAT
platform_conversation_id  wxid 或 xxx@chatroom   可空；解析成功后回写
conversation_type         PRIVATE | GROUP        可先 UNKNOWN，解析后更新
display_name              ceshi / 群名           展示与 AddListenChat 用
enabled                   true | false           单对象暂停
agent_config_id           agt_xxxxxxxx           P2；第一阶段可暂存 prompt_name
reply_policy              INHERIT | ...          默认继承全局群策略
permission_scope          DEFAULT                预留，本阶段不实现权限引擎
metadata                  { "nickname": ..., "remark": ..., "source": "listen_list" }
created_at / updated_at   ISO-8601
```

不要提前实现：

```text
WEWORK / DINGTALK / FEISHU / SLACK / TEAMS
```

枚举可以出现在注释和校验白名单里，运行时拒绝非 WECHAT。

---

## 3. 身份分层

```text
内部 conversation_id
        ↓
platform = WECHAT
        ↓
platform_conversation_id （wxid / @chatroom，可空）
        ↓
display_name / nickname / remark   （操作层）
```

规则：

1. 业务状态（将来的 Topic / 上下文 / 绑定）挂 `conversation.id`。  
2. wechatauto `AddListenChat(nickname=display_name)` **第一阶段保持现有调用**。这是 P0 已验证入口，不改签名。  
3. 解析成功后把 `chat._wxid` 写回 `platform_conversation_id`。下次优先用已存 wxid 校验，nickname 只作显示和 GUI 发送名。  
4. 解析失败：该 Conversation `enabled` 可保持 true，但 Bot 启动应明确报错（与现在找不到窗口就 `sys.exit(1)` 一致），不要静默听成别人。

---

## 4. LISTEN_LIST 兼容适配器

**禁止删除** `LISTEN_LIST`。

```text
config.local.json
    LISTEN_LIST  [[nickname, prompt_name], ...]     继续可读写
    CONVERSATIONS  [...]                            新权威列表（下一轮落地）
            │
            ▼
    Compatibility Adapter
            │
            ├─ 若 CONVERSATIONS 为空：从 LISTEN_LIST 生成
            ├─ 若两者都在：以 CONVERSATIONS 为准，LISTEN_LIST 由 adapter 投影回去
            └─ WebUI 旧表单仍提交 nickname + prompt_file
```

映射示例（当前真实数据，不是假设的 ceshi→QIYE）：

```text
["ceshi", "企业_1"]
    → Conversation
        id = conv_<stable>
        platform = WECHAT
        platform_conversation_id = ""          # 启动 AddListenChat 成功后再写
        conversation_type = UNKNOWN            # 解析后 PRIVATE 或 GROUP
        display_name = "ceshi"
        enabled = true
        agent_config_id = 由 prompt_name「企业_1」生成或挂接的 AgentConfig
        reply_policy = INHERIT
        metadata.nickname = "ceshi"
        metadata.source = "listen_list_v1"

["哈", "企业_1"]
    → 另一 Conversation，可与 ceshi 共享同一 AgentConfig（同一 Prompt）

["QIYE", "QIYE"]
    → 第三 Conversation，AgentConfig 指向 Prompt「QIYE」
```

稳定 id 生成（无数据库时）：

```text
id = "conv_" + sha1("WECHAT|" + display_name)[:12]
```

同名冲突时 **禁止** 用同一 hash。发现重复 display_name 视为 VALIDATION_ERROR，要求用户先改名或补 platform_conversation_id。这比静默合并安全。

投影回 LISTEN_LIST（给旧 Bot 启动路径）：

```text
LISTEN_LIST = [
  [c.display_name, prompt_name_of(c.agent_config_id)]
  for c in conversations if c.enabled
]
```

第一阶段 Bot 仍读 `user_names` / `prompt_mapping`。Adapter 在启动前把 enabled 的 Conversation 投影成这两份结构。P0 的 `AddListenChat` / `listen_users` 接口不变。

---

## 5. enabled 与暂停

当前缺口：UI 写死「已启用」，只能删行或全局 Stop。

目标：

```text
Conversation.enabled = false
    → 不进入投影 LISTEN_LIST
    → 不 AddListenChat
    → 不影响其它 enabled=true 的对象
```

实现约束：

- 保存配置仍建议 **Stop 后保存再 Start**（与现网一致，避免运行中改监听集合）。  
- 不要在 P0 `evaluate_inbound` 里新造一套暂停逻辑去改 Self/Dedupe。暂停发生在「谁被加入 listen_users」这一层。

---

## 6. 私聊 / 群聊

配置保存时允许 `conversation_type=UNKNOWN`。

Bot 启动 `AddListenChat` 成功后：

```text
if chat._wxid.endswith("@chatroom"):
    conversation_type = GROUP
else:
    conversation_type = PRIVATE
回写 platform_conversation_id = chat._wxid
```

群触发规则第一阶段 **继续用全局配置**（`ENABLE_GROUP_AT_REPLY` 等）。  
`reply_policy=INHERIT` 表示用全局。不要本轮把群策略拆到每个群，除非只加字段不下沉逻辑。

---

## 7. 落地方式（按当前技术栈）

当前没有业务数据库。配置已在 `config.local.json` + `.env`。

推荐：**先 JSON，不上数据库**。

```text
config.local.json
  LISTEN_LIST          兼容投影
  CONVERSATIONS        Conversation 数组
  AGENT_CONFIGS        P2 轻量配置（可同期或紧随）
```

不要为 P1 引入 SQLite/ORM。P3 Topic 再评估是否要独立 store。

校验：

- `id` 唯一  
- `display_name` 在 WECHAT 下建议唯一（当前底层限制）  
- `platform` 仅 WECHAT  
- `enabled` 必须是 bool  
- 绑定的 `agent_config_id` 必须存在（或退化为仍存在的 prompt 文件名，过渡期）

---

## 8. 与 P0 的调用边界

允许调用：

```text
wx.AddListenChat(nickname=..., callback=message_listener)
runtime.evaluate_inbound(..., listen_users=投影后的 user_names)
InboundMessage.chat_wxid          # 只读，用于回写 platform_conversation_id
```

禁止：

```text
修改 is_self_message / DedupeIndex / OutboundGuard
修改 decide_trigger 的 P0 拦截顺序
把 listen_users 突然改成 wxid 而 who 仍是 nickname
```

回写 wxid 应在 `AddListenChat` 成功之后、进入消息循环之前，写配置文件或内存后择机 save。不要在 listener 热路径里每次写盘。

---

## 9. 风险与第一阶段不做的事

做：

- 内部 ID  
- enabled  
- 持久化 wxid（能拿到就存）  
- Adapter  

不做：

- 多平台  
- 权限引擎  
- 每个群独立 Trigger Engine  
- 改 wechatauto 搜索算法（记录风险即可）  
- 为了 Conversation 重构 `bot.py` 消息主链  

已知残留风险（OPTIONAL / FUTURE）：

- wechatauto 仍按显示名 GUI 发送  
- 同名联系人 `search_contact` 取第一条  
- 备注与昵称同时匹配时的优先级（当前：`nickname in (nick_name, remark)`，先遍历到谁算谁）
