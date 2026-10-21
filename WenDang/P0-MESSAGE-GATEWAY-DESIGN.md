# P0 消息网关设计（最终落地）

> 日期：2026-09-20  
> 对照：整改前 `P0-MESSAGE-RUNTIME-ASIS.md`  
> 状态：**已实现，真实微信回归通过，P0 CLOSED**  
> 冻结：除非回归 Bug，否则不再修改本设计对应的 P0 代码

---

## 1. 目标

把「监听回调里随手丢弃」改成可观测的消息网关：

```text
采集 → 解析身份 → Outbound Guard → Self → Dedupe → Trigger → 处理/发送
```

每条消息必须留下：

- `INBOUND` / `OUTBOUND`
- `SELF` / `EXTERNAL`
- `DUPLICATE` / `NEW`
- `NO_ACTION` / `REPLY`
- `reason`

---

## 2. 最终链路

```text
电脑微信本地库轮询（wechatauto Listener）
    ↓
wxbot.WxMessage（抽出 sender_wxid / platform_message_id / direction）
    ↓
message.listener.message_listener
    ↓
inbound_from_wx_message
    ↓
BotRuntime.evaluate_inbound
        1. bot_state 非 RUNNING/DEGRADED → NO_ACTION stopped
        2. OutboundGuard.match → NO_ACTION outbound
        3. is_self_message → NO_ACTION self（仅稳定身份）
        4. DedupeIndex.check → NO_ACTION duplicate
        5. decide_trigger → 现有私聊名单 / 群规则
    ↓ REPLY
handle_wxauto_message → user_queues → LLM
    ↓
send_reply
        strip_markdown_for_wechat
        split_message_with_context（只拆 tickle/recall）
        register_outbound
        wx.SendMsg（一次正文）
    ↓
回流再次进入 evaluate_inbound → Outbound Guard → NO_ACTION
```

---

## 3. Self

统一函数：`message.identity.is_self_message(message, runtime_identity)`

| 条件 | 结果 |
|---|---|
| `direction == OUTBOUND` | self=true |
| `sender_wxid == bot_wxid` | self=true |
| `sender_id` 字符串等于 `bot_wxid` | self=true |
| `sender_id == 2` 且没有 wxid 确认 | **self=false**，reason=`sender_id_2_unconfirmed_identity` |
| 其他 | self=false，reason=`external_sender` |

禁止作为充分条件：同一设备、当前窗口、鼠标刚发送、聊天对象名、昵称文本。

`WxMessage` 不再仅凭 `sender_id==2` 写 `attr=self`。  
`classify_incoming_attr` 对 `attr=self` 只记 hint，不再无条件 DROP。

---

## 4. Dedupe

`message.dedupe.DedupeIndex`

1. 优先 `platform_message_id`（`chat_wxid:local_id`）
2. 否则 `event_hash` = SHA256(会话 + 发送者 + 类型 + 2 秒时间桶 + 归一化正文)

同一条监听重复捕获只处理一次。  
两个发送者同一句、用户故意连发同一句（不同 id）不误杀。

---

## 5. Outbound Loop Guard

发送真正执行前：`runtime.register_outbound(conversation_id, content)`。

回流匹配顺序：

1. platform_message_id
2. conversation + content_hash（TTL 60s）

命中 → `NO_ACTION`，不进 AI / Trigger / Reply。  
即使 Self 偶发错误，也不形成无限回复。

---

## 6. Trigger

`NO_ACTION` / `UPDATE_ONLY`（预留） / `REPLY`

P0 的 `NO_ACTION`：self、outbound、duplicate、bot/system、unauthorized、stopped。  
`REPLY`：沿用现有私聊监听名单与群规则。  
不实现 Topic Engine。

---

## 7. 状态机与 Kill Switch

状态：`STOPPED / STARTING / RUNNING / STOPPING / ERROR / DEGRADED`  
可工作：仅 `RUNNING`、`DEGRADED`。

Stop Bot：

1. WebUI 写 `STOP_REQUEST`
2. Bot 进入 `STOPPING`：禁收、停消费、取消 LLM、清发送队列、禁 UI automation
3. `STOPPED` 后前端才显示已停止
4. 超时只对已校验的 Bot PID 发隔离 `CTRL_BREAK` / terminate / kill
5. 拒绝 WebUI 自身 PID、`config_editor.py`、非本项目 `bot.py`

任何 outbound 执行前再检查 `ensure_can_send()`。

---

## 8. 微信纯文本

发出前统一 `WeChatPlainTextFormatter`：

- 标题、加粗、代码围栏、链接 → 纯文本
- 仅当识别到 Markdown Table separator 时改写表格为「列名：值」
- 不把业务里的 `A | B` 当表格删掉
- 正文一次发送，不再按 `$` 或换行分段；`[tickle]` / `[recall]` 仍单独动作
