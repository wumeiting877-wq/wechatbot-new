# P0 Self 判断根因

> 日期：2026-09-20  
> 方法：对照当前代码路径 + 本地运行日志 `runtime_control/events.jsonl`  
> 场景：同一手机主微信 `ceshi` → 微信分身机器人账号；电脑微信登录机器人号并监听 `ceshi`

---

## 结论

**CONFIRMED**

导致 `ceshi → robot` 被判断成 `self = true` 的字段与逻辑是：

```text
WxMessage.__init__
    sender_id in (2, "2")   →  attr = "self"
        ↓
classify_incoming_attr(attr=="self")
        ↓
reason = "self_message"
        ↓
message_listener 丢弃，不进 AI
```

没有使用 sender wxid / bot wxid / direction / outbound mapping。  
`sender_id == 2` 被硬编码为「自己发的消息」。

---

## 1. 运行态事件（本机已发生，不是推演）

`runtime_control/events.jsonl`：

| 时间 | 证据 |
|---|---|
| 2026-09-19 10:08:51 | `微信连接：正常 扶级` |
| 2026-09-19 10:08:51 | `监听对象数量：2` |
| 2026-09-19 10:08:51 | `STARTING → RUNNING` |
| **2026-09-19 10:09:34** | **`检测到 Bot 自己发送的消息（会话：ceshi），已忽略`** |
| 2026-09-19 10:09:59 | `会话：ceshi 收到消息：回复`（后续一条被当成好友消息并进 AI） |

当前登录账号昵称是 **扶级**，不是 ceshi。会话窗口是 **ceshi**。  
该条在入站后被标成 Bot 自己发送并忽略。

这条日志**只**在 `message/listener.py` 的 `attr_decision["reason"] == "self_message"` 分支打印。

---

## 2. 该日志对应的唯一代码路径

`classify_incoming_attr` 只有 `attr == "self"` 才返回 `self_message`：

```144:156:wechatbot-new/message/pipeline.py
def classify_incoming_attr(msgattr: str, content: str) -> dict:
    ...
    if attr == "self":
        return {"action": "drop", "reason": "self_message", "content": text}
```

`attr` 只有 `WxMessage` 会写成 `"self"`：

```107:113:wechatbot-new/wxbot.py
        sender_id = row.get("sender_id")
        ...
        is_self = sender_id in (2, "2") or str(sender_id) == self._self_wxid
        self.attr = "self" if is_self else "friend"
```

两条条件：

| 条件 | 能否在监听回调里成立 |
|---|---|
| `sender_id in (2, "2")` | 能。wechatauto 把库字段 `real_sender_id` 原样放到 `sender_id`。微信 4.x 约定 **2 = 本库主人**。 |
| `str(sender_id) == self._self_wxid` | 监听行里的 `sender_id` 是短整数，`self_wxid` 是 `wxid_...` 字符串。整数转字符串后不会相等。 |

因此，10:09:34 那条 ceshi 会话消息要打出「检测到 Bot 自己发送的消息」，**必须**走过 `attr="self"`，而当前代码能把入站行标成 `self` 的有效条件只有 **`sender_id == 2`**。

---

## 3. 该消息运行态字段（能确认 / 当时日志未打印）

当时 listener **没有**把 identity 字段写入 events.jsonl。下表区分「已由日志确认」和「当时未采集」。

| 字段 | 值 | 来源 |
|---|---|---|
| 当前机器人身份 | 扶级 | events：`微信连接：正常 扶级` |
| 当前登录账号 | 电脑微信登录号昵称 扶级（非 ceshi） | 同上；若昵称是 ceshi，启动会因「监听列表包含自己」直接退出 |
| conversation / chat_name | ceshi | 日志「会话：ceshi」 |
| 消息采集来源 | 电脑微信本地库轮询（wxbot Listener） | 代码；收消息不走 UI |
| self 判断结果 | true（按 attr=self 丢弃） | 10:09:34 日志 |
| self 判断使用的字段 | `msg.attr`（由 `sender_id` 写出） | 代码 |
| self 判定原因 | `self_message` ← `attr=="self"` ← `sender_id in (2,"2")` | 代码路径唯一 |
| direction | 未建模。业务把 attr=self 当自己发出 | 代码无 INBOUND/OUTBOUND |
| 时间戳 | 2026-09-19 10:09:34 | events.ts |
| message_id | 当时未记录 | listener 在 attr 丢弃时尚未调用 `make_message_id` |
| platform_message_id | 当时未记录 | 未采集 |
| sender_id（库内整数） | 当时未打印；路径要求为 2 | 见第 2 节 |
| sender_name | 当时未打印。代码在 attr=self 时会改成库主人昵称「扶级」或「我」 | `_resolve_sender` |
| sender_wxid / sender_username | 未使用。`sender_id==2` 时 wechatauto 通常不填 username | 代码 |
| receiver_id / receiver_name | 未采集。私聊对端即窗口 ceshi | 代码 |
| raw message type | 当时未打印 | 未采集 |
| 当前窗口标题 | 收消息不读 UI 标题 | 代码 |
| 当前聊天对象 | 监听会话名 ceshi | 日志 |

**未采集不等于未发生。** 能确认的是判断依据，不是那一行 SQLite 的完整 dump。

---

## 4. 为什么同机分身会让这条变成 sender_id=2

本条只陈述项目侧已确认事实。微信客户端为何把对端消息写成 `real_sender_id=2`，**本轮没有抓到该行的 SQLite dump，不在此当作已复现的客户端内部机制。**

项目侧已确认：

1. 电脑端监听的是机器人号（昵称 扶级），会话是 ceshi。
2. 该入站消息被标 `attr=self` 并丢弃。
3. 项目把 `sender_id==2` 直接映射为 self，没有第二身份字段纠正。

同机主微信 + 分身是用户给出的操作条件；它与「对端消息被写成 2」在时间上对齐，但 **WeChat 写库原因 NOT CONFIRMED（无 row dump）。**  
**项目误判路径 CONFIRMED。**

---

## 5. 25 秒后为何又变成可回复

10:09:59 同一会话出现 `会话：ceshi 收到消息：回复`，并进入主模型。  
说明：

- 并非所有 ceshi 会话消息都会被标 self。
- 只有 `attr=="self"` 的那条被丢。
- 后续一条 `attr` 为 friend，才进入 `admit_message` 并记 MESSAGE 日志。

这与「仅当库字段 `sender_id==2` 才标 self」一致：不是窗口名 ceshi 导致 self，而是**该条的 sender_id/attr**。

---

## 6. 禁止再依赖的信号（当前却在用）

| 当前用法 | 问题 |
|---|---|
| `sender_id==2` | 同机分身/多端同步下会把对端写成 2 |
| `attr=="self"` 无条件 DROP | 放大上一行的误标 |
| `sender_name in self_names` | 昵称文本；且 attr=self 时 sender 已被改成机器人昵称，二次误伤 |
| 无 outbound 对照 | 真自己发出与误标无法区分 |

未使用稳定身份：bot wxid、sender wxid、direction、platform_message_id、outbound mapping。

---

## 7. 整改指向（本文件不改代码，仅锁定根因）

`is_self_message` 必须用稳定身份。  
`sender_id==2` 且 **没有** 确认 `sender_wxid == bot_wxid` 时，不得判 self。  
真回流靠 outbound 登记拦截。

---

## 8. 整改后真实微信回归（2026-09-20）

根因未改写：项目误判路径仍是 **CONFIRMED**。  
修复已落地，并在真实微信环境验证：

| 项 | 结果 |
|---|---|
| ceshi → robot（真实微信） | INBOUND，self=false，进入回复 |
| 同机主微信 ceshi + 分身 robot | 不再因 `sender_id==2` 误判 self |
| 机器人自身回复回流 | NO_ACTION，不再二次触发 |

详见 `P0-CLOSURE-REPORT.md`。  
**P0 STATUS = CLOSED**
