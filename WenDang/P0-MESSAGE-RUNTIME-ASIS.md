# P0 消息运行时 AS-IS

> 扫描日期：2026-09-20  
> 范围：只读当时仓库真实代码与本地 `runtime_control/events.jsonl`  
> **文档性质：整改前 AS-IS 快照，不再代表当前代码**  
> 当前实现见 `P0-MESSAGE-GATEWAY-DESIGN.md`  
> 真实微信最终回归已完成，见 `P0-CLOSURE-REPORT.md`  
> **P0 STATUS = CLOSED**  
> 不覆盖 Prompt / 配置管理（上一阶段已收口）

---

## 1. 完整消息链路（当前真实路径）

```text
手机/电脑微信发出
    ↓ 多端同步
电脑微信 4.x 写入本地 SQLite（当前登录号的 message_*.db）
    ↓ 约每秒轮询（wechatauto Listener，非 UI 抓消息）
wxbot.WeChat._make_listen_cb
    ↓ 构造 WxMessage
message.listener.message_listener(msg, chat)
    ↓ classify_incoming_attr（attr=self / tickle / 非好友）
    ↓ BotRuntime.admit_message（状态 / 去重 / self_names / 回声）
    ↓ 语音/链接/引用/合并 归一化
    ↓ decide_should_process（私聊监听名单 / 群 @ 关键词）
    ↓ handle_wxauto_message 或 handle_emoji_message(Timer 3s)
        ↓ 命令 / 提醒 / 图片识别 / URL 抓取
        ↓ 写入 bot.user_queues
    ↓ InactiveUserChecker 线程每 1s 扫队列
    ↓ process_user_messages
        ↓ 可选联网 LLM
        ↓ 主模型 LLM
        ↓ send_reply（先入 BotRuntime.SendQueue）
    ↓ SendWorker 线程真正发送
        ↓ wx.SendMsg / SendFiles / tickle / 撤回
        ↓ wechatauto GUI：打开会话 → 坐标/OCR 输入 → 回车
    ↓ 电脑微信发出
    ↓ 本地库再次出现该消息 → 监听回调回流
```

本项目**不读手机微信、不走网页版**。收消息走解密库；发消息走电脑微信窗口自动化。

---

## 2. 当前消息入口

| 项 | 位置 |
|---|---|
| 启动 | `bot.py` `main()` → `WeChat()` → `wx.AddListenChat(nickname=..., callback=message_listener)` |
| 阻塞循环 | `bot.py` `wx.KeepRunning()`（主线程） |
| 监听线程 | `wxbot.WeChat._listener_start()` → wechatauto Listener（DB 轮询） |
| 回调包装 | `wxbot.WeChat._make_listen_cb` → `WxMessage(row, chat, db, media, self_wxid)` |
| 业务入口 | `message/listener.py` `message_listener(msg, chat)` |
| 守护补监听 | `bot.py` `keep_alive()` 每 5 秒检查 `wx.listen`，丢失则再次 `AddListenChat` |
| 采集来源 | 电脑微信登录账号的本地库；`WeChat()` **未指定 account=**，多账号时默认挑一份数据目录 |

`msg` 字段当前实际有：`type` / `attr` / `sender` / `content` / `local_id` / `create_time` / `sort_seq`。  
没有单独的 `direction`、`sender_wxid`、`platform_message_id` 业务字段。

---

## 3. 当前 self 判断位置

**唯一把 `attr` 写成 `"self"` 的地方：**

`wxbot.py` `WxMessage.__init__`

```text
is_self = sender_id in (2, "2") or str(sender_id) == self._self_wxid
self.attr = "self" if is_self else "friend"
```

随后发送者显示名被改成当前库主人昵称（`_resolve_sender`：`attr==self` → `get_self_info()["nick_name"]`）。

**丢弃位置（两层）：**

1. `message/pipeline.py` `classify_incoming_attr`：`attr=="self"` → `drop / self_message`
2. `message/listener.py`：命中后打日志「检测到 Bot 自己发送的消息」，写入 `bot_last_sent_msg`，直接 `return`
3. `bot_runtime.py` `admit_message`：`attr=="self"` **或** `sender_name in self.self_names` 再丢一次

`self_names` 启动时设为 `{ROBOT_WX_NAME, wx.wxid, "Self"}`（`bot.py` `main()`）。

**未使用：** sender wxid 交叉验证、outbound 映射、消息方向、平台 `sender_username`。

---

## 4. 当前去重机制

`BotRuntime.admit_message`（`bot_runtime.py`）：

| 规则 | 键 | TTL | 副作用 |
|---|---|---|---|
| 已处理 ID | `make_message_id`：`chat:local_id:create_time:sort_seq`，无 local_id 则 `chat+content+create_time` 的 md5 | 120s | 重复丢弃 |
| 刚发出回声 | `chat_id::原文` 对比 `_recent_sent` | 30s | 当 self 丢弃 |
| 同窗口同文本 | `chat_id::原文` 对比 `_recent_contents` | **5 秒** | 短时相同内容丢弃 |

问题：

- 去重键含会话，但 **5 秒同窗口同文本** 会把用户连发同一句话误杀。
- 无 `platform_message_id` 业务层；无 `event_hash`；无 dedupe reason 结构体。
- 监听回调若对同一 `local_id` 打多次，ID 去重有效；若 ID 抖动则可能双处理。

---

## 5. 当前回复触发逻辑

没有 `NO_ACTION / UPDATE_ONLY / REPLY` 状态机。

当前等价于：**过了 self/去重之后，命中规则就进 AI。**

私聊：`who in LISTEN_LIST` → 处理。  
群聊：`group_rules.evaluate_group_trigger`（全局接收 / @机器人 / 关键词 / 概率）。

之后 `handle_wxauto_message`：

- `/命令`
- 提醒关键词 → 可能再调 LLM 解析
- 图片/表情识别
- URL 抓取
- **一律入 `user_queues`，等待合并后调主模型**

普通文本默认会打主模型（`plan_llm_calls_for_text`）。

---

## 6. 当前发送逻辑

| 步骤 | 位置 |
|---|---|
| 入队 | `send_reply(..., _direct=False)` → `runtime.submit_send(send_reply, ..., _direct=True)` |
| 发送队列 | `BotRuntime.send_queue`：`queue.Queue` + 守护线程 `SendWorker` |
| 真正发送 | `send_reply(..., _direct=True)` |
| 文本 | `wx.SendMsg(msg=content, who=user_id)` → `wxbot.WeChat.SendMsg` → wechatauto 坐标/OCR |
| 表情/文件 | `wx.SendFiles` |
| 拍一拍/撤回 | `msg.tickle()` / `select_option('撤回')`（UIA + OCR） |
| 发送后 | `runtime.remember_sent` + `note_replied` |
| 并发标志 | 全局 `is_sending_message`；发送前最多等 15s |

`SendQueue.submit` / `ensure_can_send` 检查 `is_send_blocked()`（紧急停止或 `_send_blocked`）。  
**不检查 `state == RUNNING`。** STOPPING 若未置 `_send_blocked`，队列仍可发。

分段发送循环内每段会再 `ensure_can_send`。单次 `wx.SendMsg` 内部鼠标动作**没有**协作取消点。

---

## 7. Stop Bot 当前实际停止了什么

WebUI：`POST /stop_bot` → `stop_bot_process(pid)`：

1. Windows：`CTRL_BREAK`（`bot.py` 转成 `KeyboardInterrupt`）
2. 等最多 8s
3. 超时 `terminate` → 再超时 `kill`
4. 前端 `applyRuntimeStatus`：进程不在则显示已停止
5. **不写 STOPPING 状态机，不等待 Bot 内部清理完成**

紧急停止：`POST /emergency_stop` → 写 `runtime_control/EMERGENCY_STOP` → Bot 内 `EmergencyStopWatcher` 每 100ms 轮询 → `activate_emergency`（禁发、清空 SendQueue、hook 清空 `user_queues`）→ **`os._exit(0)`**。

若进程因 CTRL_BREAK 进入 `main()` `finally`：

- `wx.StopListening(True)`
- 尝试恢复微信窗口
- `runtime.set_state("STOPPED")`（非 emergency 时）
- 取消短期提醒 Timer
- 关异步日志线程

---

## 8. Stop Bot 没有停止什么（当前缺口）

| 缺口 | 证据 |
|---|---|
| 不是统一 STOPPING→STOPPED 杀开关 | `/stop_bot` 直接杀 PID；前端以进程存活当停止 |
| 不保证先禁业务再杀 | 杀进程与 SendWorker / LLM 竞态 |
| 进行中的 `wx.SendMsg` 鼠标/键盘 | 一次阻塞调用，无中断 API |
| 进行中的 OpenAI HTTP | `stream=False`，无 cancel；仅在调用前/后检查 `is_send_blocked` |
| `keep_alive` / 提醒 / 主动消息 / 记忆 / 心跳 / 内存监控 | 守护线程，随进程死；无协作 stop event |
| wechatauto Listener | 依赖 `StopListening` 或进程退出 |
| `emoji_timer`（3s Timer） | 紧急 hook 不清它；进程被杀才停 |
| 前端「已停止」 | 进程死即可，不要求内部 STOPPED |

普通 Stop 与 Emergency 行为不一致：普通停靠杀进程，紧急停靠标志文件 + `_exit`。

---

## 9. 鼠标控制在哪里启动 / 如何结束

| 项 | 说明 |
|---|---|
| 启动点 | `SendWorker` 调用 `send_reply(_direct=True)` → `wx.SendMsg` / `SendFiles` / `tickle` / `RecallLastMessage` |
| 实现 | wechatauto GUI：打开会话、坐标点击输入框、OCR、键盘输入、回车。`wxbot.py` 文件头写明「发送走坐标/OCR」 |
| 收消息 | **不**驱动鼠标 |
| 结束点 | `SendMsg` 返回；`finally: is_sending_message = False` |
| 中断 | 紧急停止后不再入队；**已开始的 GUI 发送无协作取消**。进程 `_exit` / `kill` 是硬中断 |

---

## 10. 当前是否存在后台队列

**是，至少三层：**

| 队列 | 位置 | 生产者 | 消费者 |
|---|---|---|---|
| 会话合并队列 | `bot.py` `user_queues` + `queue_lock` | `handle_wxauto_message`、提醒、主动消息 | `check_inactive_users` → `process_user_messages` |
| 发送队列 | `BotRuntime.send_queue` (`queue.Queue`) | `send_reply` | `SendWorker` |
| 日志 HTTP 队列 | `AsyncHTTPHandler.log_queue` | logging | 其 worker 线程 |
| 表情延迟 | `threading.Timer(3.0)` | `handle_emoji_message` | Timer 回调 |

`user_queues` 按用户合并，等待 `QUEUE_WAITING_TIME`（本地配置 7s）后一次性送 LLM。

---

## 11. 当前是否存在多个消费者

**是。**

| 线程 / 任务 | 名称 | 作用 |
|---|---|---|
| 主线程 | `KeepRunning` | 微信监听阻塞循环 |
| wechatauto | Listener | DB 轮询，回调 `message_listener` |
| `keep_alive` | 每 5s 补监听 | |
| `InactiveUserChecker` | 每 1s 消费 `user_queues` | |
| `SendWorker` | 消费发送队列 | |
| `AutoMessageChecker` | 主动消息入 `user_queues`（配置关闭则空转） | |
| `ReminderChecker` | 到期提醒入队 | |
| `MemoryManager` | 记忆总结 | |
| `BotHeartbeatThread` | 向 WebUI 报 PID | |
| `MemoryUsageMonitor` | 内存 | |
| `EmergencyStopWatcher` | 紧急标志 | |
| `RuntimeStatusWriter` | 每 2s 写 status.json | |
| `emoji_timer` | 3s 一次性 Timer | |
| 短期提醒 | `threading.Timer` 若干 | |
| `AsyncHTTPHandler.worker` | 远程日志 | |

消息业务主消费者实际是：**Listener 回调（入队） + InactiveUserChecker（LLM） + SendWorker（GUI 发送）**。三者并发，靠 `session_busy` / `is_sending_message` / `queue_lock` 部分串行。

---

## 12. 运行状态机 AS-IS

`BotRuntime` 已声明：`STOPPED / STARTING / RUNNING / STOPPING / ERROR / DEGRADED`。

实际：

- 启动：`STARTING` → `RUNNING` 或 `DEGRADED`
- 退出：`finally` 设 `STOPPED`（emergency 除外）
- 紧急：`STOPPING` 后立刻 `_exit`，WebUI 再标 `STOPPED`
- 普通 Stop Bot：**不经过 Bot 内 STOPPING 流程**，外部杀进程

`is_accepting_work()` 允许 `RUNNING | DEGRADED | STARTING`。  
`ensure_can_send()` **只看** `is_send_blocked()`，不看 `state == RUNNING`。

---

## 13. 涉及文件 / 类 / 函数清单

| 文件 | 类 / 函数 | 角色 |
|---|---|---|
| `wxbot.py` | `WxMessage` | 解析 DB 行，写 `attr` |
| `wxbot.py` | `WeChat.AddListenChat` `_make_listen_cb` `SendMsg` | 监听与发送 |
| `message/listener.py` | `message_listener` | 入站主入口 |
| `message/pipeline.py` | `classify_incoming_attr` `decide_should_process` | 属性过滤 / 触发 |
| `message/handler.py` | `handle_wxauto_message` | 命令/媒体/入业务队列 |
| `message/processor.py` | `check_inactive_users` `process_user_messages` | 合并 + AI |
| `message/bind.py` | `host()` | 绑定 `bot.py` 全局 |
| `bot_runtime.py` | `BotRuntime` `SendQueue` | 状态、去重、发送队列、紧急停 |
| `bot.py` | `main` `send_reply` `keep_alive` `handle_emoji_message` | 编排、发送、线程 |
| `llm_client.py` | `get_deepseek_response` `call_chat_api_with_retry` | AI；调用前检查紧急停 |
| `group_rules.py` | `evaluate_group_trigger` | 群触发 |
| `config_editor.py` | `start_bot` `stop_bot` `stop_bot_process` `emergency_stop` | WebUI 启停 |
| `static/js/config_editor.js` | `toggleBot` `applyRuntimeStatus` | 按钮与状态展示 |

无独立 Trigger Engine、无 outbound 登记表、无 `is_self_message()`。
