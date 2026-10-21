# P6-G0 Gate 0：当前真实运行时拓扑

> 日期：2026-09-22  
> 性质：**READ ONLY**。依据真实源码 + P5-G4 真机 `events.jsonl` / Store，不根据旧文档推断。  
> 正式副本：`P6-G0-RUNTIME-TOPOLOGY.md`

仓库内 **只有一个** `bot.py`：`wechatbot-new/bot.py`。

---

## 1. 进程角色（禁止把 WebUI / wrapper 当 Bot）

| 角色 | 如何识别 | 是否跑 listener |
|---|---|---|
| WebUI | `config_editor.py` | 否 |
| Bot wrapper | WebUI `Popen([sys.executable, bot.py])` 的 PID（`current_bot_pid`） | 不一定。Windows 可能再拉起子解释器 |
| **Bot 身份** | `bot.py` 内 `os.getpid()`，写入 `runtime_control/status.json` 的 `pid`，心跳同此 PID | **是** |

P5-G4 真机：WebUI `27624/15396`，wrapper `8096`，Bot `44864`。

---

## 2. 真实调用链（已核对源码）

```text
电脑微信 4.x 写入本地 SQLite
        ↓ 约 1s 轮询
wechatauto.db.Listener  （每进程 1 个 poll 线程）
        ↓ callback 列表（add_listener 为 append）
wxbot.WeChat._make_listen_cb
        ↓ 构造 WxMessage（platform_message_id = chat_wxid:local_id）
message.listener.message_listener
        ↓ inbound_from_wx_message
        ↓ classify_incoming_attr（self_tickle / 非好友可提前 return）
        ↓ BotRuntime.evaluate_inbound
              stopped → outbound → self → system → duplicate → trigger
        ↓ try_enqueue_topic_sidepath   ← listener 内唯一 Topic 入口
              （在 verdict.action != REPLY 判断之前；unauthorized 仍可入队）
        ↓ 若 REPLY：handle_wxauto_message → Chat LLM → send_reply
              否则 abort，Chat = 0

TopicSidepath（模块单例 get_sidepath）
        ↓ queue.Queue(maxsize=32) put_nowait
        ↓ daemon 单 worker TopicSidepathWorker
        ↓ TopicEngine.process_inbound
              upsert MessageRecord
              has_successful_processing → replay skip extractor
              否则 TopicExtractorClient.extract → Store commit
        ↓ TOPIC SUCCESS 且带 topic_id 时平行 fan-out（互不闸门）
              ├─ try_enqueue_task_after_topic
              ├─ try_enqueue_decision_after_topic
              └─ try_enqueue_risk_after_topic
        ↓ 各自独立 queue + 单 worker + 独立 Store
```

唯一 Bot 启动入口：`bot.py` `main()` → `WeChat()` → 对每个 `user_names` `AddListenChat(..., callback=message_listener)` → `wx.KeepRunning()`。

守护：`keep_alive` 每 5 秒若 `wx.listen` 缺人，再次 `AddListenChat`。

---

## 3. 每进程实例数（代码层）

| 对象 | 数量 |
|---|---|
| `WeChat()` | 1 / Bot 进程 |
| `db.Listener` poll 线程 | 1（`_listener_start` 若已存活则 return） |
| 每监听会话 callback | `add_listener` **append**；`wx.listen` 有同名则 `AddListenChat` 拒绝 |
| `BotRuntime` / P0 `DedupeIndex` | 1 / 进程（内存） |
| Topic / Task / Decision / Risk worker | 各 1 daemon 线程（sidepath 单例） |

**单 Bot 进程 严格对应 1 个 DB Listener 线程。**  
不能从代码证明「机器上永远只有一个 Bot 进程」：Stop 后进程可能残留，`start_bot` 不扫描孤儿 `bot.py`。

---

## 4. 开关默认（本轮未改）

```text
TOPIC_ENGINE_ENABLED    = false   （模块常量 + runtime_control 文件）
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

审计时刻四个 `runtime_control/*_ENGINE_ENABLED` 均为 `false`。
