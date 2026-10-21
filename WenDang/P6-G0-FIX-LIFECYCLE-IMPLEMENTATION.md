# P6-G0-FIX-LIFECYCLE Implementation Report

> 日期：2026-09-22  
> 范围：Stop / Start 生命周期最小修复。未进入 P6-G1。未改 N2 去重语义。未改四个 Engine 业务。

本轮之前：`P6-G0 = BLOCKED`（B1 keep_alive 不响应 Stop；B2 start_bot 不扫孤儿 Bot）。

---

## 1. 修改了哪些文件？

| 文件 | 动作 |
|---|---|
| `bot_lifecycle.py` | **新增**。keep_alive tick/loop、有限 join |
| `bot.py` | keep_alive 改为绑定 Runtime；Stop hook 停监听 + 有限 join |
| `bot_runtime.py` | `_lifecycle_stop` Event；STOPPING 起禁止补监听 |
| `webui_bot_process.py` | status PID 候选、`start_bot_preflight`、身份确认 |
| `config_editor.py` | Start 前 preflight；Stop 用 identity 判断存活 |
| `llm_client.py` | Extractor 日志 purpose 可区分引擎（OBS） |
| `topic_extractor_client.py` | `_default_extractor_llm_call` 设 `purpose=topic_extractor` |
| `task_extractor_client.py` | `purpose=task_extractor` |
| `decision_extractor_client.py` | `purpose=decision_extractor` |
| `risk_extractor_client.py` | `purpose=risk_extractor` |
| `tests/test_bot_lifecycle.py` | **新增** LIFE-01～08 / N2 Store / OBS |
| `tests/test_p0_message_runtime.py` | N2 防误修 |
| `tests/test_topic_sidepath.py` | N2 双 enqueue |
| `tests/test_llm_client.py` | OBS purpose |
| `tests/test_webui_bot_process.py` | preflight |

未改：Trigger / Self / Dedupe key / Outbound / Chat Prompt / 四个 EXTRACTOR schema / Engine 决策 / Risk severity / Dashboard。

---

## 2. 为什么每个文件必须修改？

1. **`bot_lifecycle.py`**：把 `keep_alive` 从 `bot.py` 的 `while True` 抽成可测循环，避免测试导入微信。
2. **`bot.py`**：生产入口必须调用该循环；Stop hook 必须先发 stop signal，再 `StopListening`，再有限 join。
3. **`bot_runtime.py`**：Stop 信号必须在 `begin_graceful_stop` 进入 STOPPING 时立刻置位，堵住 StopListening 与 keep_alive tick 之间的竞态。
4. **`webui_bot_process.py`**：已有 `inspect_bot_process`；Start 防护必须复用它，禁止扫全机 python。
5. **`config_editor.py`**：`/start_bot` 原先只看 Flask `bot_process.poll()`；`/stop_bot` 原先可用 `pid_exists` 把复用 PID 当成 Bot。
6. **Extractor 客户端 + `llm_client.py`**：仅改日志标签，消除 RCA 假阳性。测试锁定行为。

---

## 3. keep_alive 原问题是什么？

`keep_alive` 是 `while True` + `time.sleep(5)`，**不看** `STOPPING` / `STOPPED`。

`wx.StopListening(True)` 会：

- `_listener_stop()` → 置 `_listener_stop_event`（`KeepRunning` 本可退出）
- `wx.listen.clear()`

随后 keep_alive 发现「监听对象缺失」，调用 `AddListenChat`。`wxbot.AddListenChat` 在 `_listener_is_listening=False` 时会 `_listener_start()`，**清掉** `_listener_stop_event`。于是：

```text
StopListening → KeepRunning 本应退出
    → keep_alive AddListenChat → Listener 重生
    → Bot 进程不退出
```

这是 B1 的根因。不是双 listener 对同一 `local_id` 回调（N2 RCA 已排除）。

---

## 4. Stop signal 如何传递？

```text
WebUI POST /stop_bot
  → trigger_graceful_stop 写 runtime_control/STOP_REQUEST
  → EmergencyStopWatcher 见 stop_flag
  → BotRuntime.begin_graceful_stop
       set_state(STOPPING)
       _lifecycle_stop.set()          # 立即禁止 AddListenChat
       hooks:
         signal_lifecycle_stop
         wx.StopListening(True)
         join_keep_alive_thread(timeout=2s)
       set_state(STOPPED)
```

keep_alive 的 `wait` 绑定 `runtime.lifecycle_stop_event()`，不再 `time.sleep`。

---

## 5. keep_alive 如何退出？

`run_keep_alive_loop` 在以下任一成立时退出：

- `stop_event.is_set()`（即 `_lifecycle_stop`）
- `runtime.state == STOPPED`
- `wait(interval)` 返回 True（event 已置位则立即返回，不等 5 秒）

STOPPING 期间 `keep_alive_tick` 的 `add_listen_count` 必须为 0。

---

## 6. 是否存在 join？

存在。仅针对 keep_alive 线程。Side-path worker 仍用原 `_stop` Event（P3/P4/P5 语义，本轮不重构）。

---

## 7. join 是否有 timeout？

有。`KEEP_ALIVE_JOIN_TIMEOUT_SEC = 2.0`。禁止无限 join。测试 `test_join_keep_alive_has_timeout` 锁定：卡死线程时 join 0.2s 返回且不阻塞 Stop。

---

## 8. Bot process 如何确认退出？

不只看 `bot_process.poll()`。

Stop 后：

1. `status.json` 可为 `STOPPED`（Bot 内 `begin_graceful_stop`）
2. `_bot_process_alive()` 对候选 PID 调用 `inspect_bot_process`（pid + cmdline 含本项目 `bot.py` + 非 WebUI）
3. 候选 PID = Flask 句柄 + `current_bot_pid` + **`status.json pid`**
4. 真机：Stop 后 wrapper PID 与 `status.json` 工作 PID 均消失

Windows 拓扑（真机确认）：

```text
WebUI PID        = config_editor.py
wrapper PID      = Popen(.venv python bot.py)
真实 Bot PID     = status.json pid（子进程 python bot.py）
```

KeepRunning 在 StopListening 且 keep_alive 不再 `_listener_start` 后返回，主进程 `finally` 退出。

---

## 9. Start 如何识别孤儿 Bot？

`start_bot_preflight`：

- `status.json.pid`
- Flask `bot_process` / `current_bot_pid`
- 可选：WebUI 子进程（不扫全机 python）

每个 PID 必须通过 `inspect_bot_process`（cmdline 含本项目 `bot.py`）。命中则拒绝第二次 `Popen`（HTTP 409 `already_running`）。

---

## 10. 如何避免误杀其他 Python？

- 不 `taskkill` python.exe
- 不按进程名杀
- 不按模糊 `bot.py` 杀全部
- `inspect_bot_process` 拒绝：空 PID、WebUI 自身、`config_editor.py`、cmdline 不是 bot、cwd/cmdline 不属于本项目
- PID 复用且 cmdline 不是本项目 bot.py → `cmdline_not_bot`，**不识别、不杀、允许 Start**

复用已有 `psutil`（项目已依赖）。未引入新重量级库。

---

## 11. 如何保证单 Bot？

- Start 前 preflight：`living_project_bot` 或 Flask 句柄仍活 → 不 Popen
- 真机：重复 Start 后仍只有 1 个 wrapper + 1 个 worker（同一棵树）
- `active_project_bot_count` 以 identity 确认的存活 bot.py 计，wrapper/worker 属同一启动

---

## 12. 如何保证单 Listener？

- 启动时每个会话一次 `AddListenChat(..., callback=message_listener)`
- keep_alive 只在 RUNNING/DEGRADED/STARTING 且未 stop 时补缺失项
- STOPPING 起 AddListenChat=0，因此 StopListening 清空后 **不会** 再 `_listener_start`
- 每个 Bot 进程最多一条 wechatauto `db.Listener` 线程（`_listener_start` 若线程仍活则 return）

---

## 13. N2 去重语义是否保持？

保持。

```text
dedupe key = platform_message_id
TTL        = 120s   (BotRuntime.PROCESSED_ID_TTL)
```

同正文、不同 `platform_message_id` → 两次 NEW、两个 MessageRecord。  
未做正文时间窗 / hash / 全局锁 / sleep / 模糊相似度。

---

## 14. 四个 Engine 是否仍 false？

是。

```text
模块常量 TOPIC_ENGINE_ENABLED    = False
模块常量 TASK_ENGINE_ENABLED     = False
模块常量 DECISION_ENGINE_ENABLED = False
模块常量 RISK_ENGINE_ENABLED     = False

runtime_control/TOPIC_ENGINE_ENABLED    = false
runtime_control/TASK_ENGINE_ENABLED     = false
runtime_control/DECISION_ENGINE_ENABLED = false
runtime_control/RISK_ENGINE_ENABLED     = false
```

未写生产长期 ENABLE。

---

## 不变式（本轮锁定）

```text
RUNNING  → keep_alive 可补监听
STOPPING → AddListenChat count = 0
STOPPED  → keep_alive thread terminated；Bot PID 退出
Start    → 已有本项目 Bot 则拒绝第二次 Popen
```
