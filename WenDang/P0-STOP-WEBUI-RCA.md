# P0 Stop Bot 后 WebUI 失联 — 根因分析

> 日期：2026-09-20  
> 范围：只取证 `config_editor.py` 的 `start_bot` / `stop_bot` / `stop_bot_process` 与 Windows CTRL_BREAK  
> 未改：Prompt / 配置管理  
> 结论标记只允许 `CONFIRMED` 或 `NOT CONFIRMED`

---

## 1. 进程模型（代码）

```text
config_editor.py  WebUI  PID A
        │
        ├── Start Bot
        ▼
bot.py            PID B   creationflags=CREATE_NEW_PROCESS_GROUP
```

`start_bot()` 使用 `subprocess.Popen([sys.executable, bot.py], creationflags=CREATE_NEW_PROCESS_GROUP)`。  
`stop_bot()` 先写 `STOP_REQUEST`，等待最多 12 秒，再对 `current_bot_pid` 与 `bot_process.pid` 调用 `stop_bot_process()`。  
原 `stop_bot_process()` 在 Windows 上执行：`os.kill(pid, CTRL_BREAK)` → wait → `terminate` → `kill`。  
原实现**没有**校验目标是否为 `bot.py`，也**没有**拒绝 WebUI 自身 PID。

---

## 2. 实测探针

探针脚本：`tests/_ctrl_break_probe.py`、`tests/_flask_ctrl_break_server.py`。  
Bot 侧均以 `CREATE_NEW_PROCESS_GROUP` 拉起，再对 Bot PID 发送 `CTRL_BREAK`。

### 2.1 独立控制台父/子进程

```text
WEB_PID = 33020
BOT_PID = 28848
BOT_PPID = 33020
parent_received_sigbreak = false
child_received_sigbreak = true
parent_still_alive = true
```

根因「父进程收到 SIGBREAK」：`NOT CONFIRMED`

### 2.2 当前控制台 inline（当前进程当 WebUI）

```text
WEB_PID = 19888
BOT_PID = 39288
BOT_PPID = 19888
parent_received_sigbreak = false
child_received_sigbreak = true
parent_still_alive = true
```

根因「同控制台导致 WebUI 收到 SIGBREAK」：`NOT CONFIRMED`

### 2.3 Flask 请求线程发送 CTRL_BREAK（最接近生产）

```text
WEB_PID = 37360
BOT_PID = 18112
BOT_PPID = 37360
stop thread = Thread-3 (process_request_thread)
is_main_thread = false
PING_BEFORE = 200
STOP = child_rc 0
PING_AFTER = 200
WEB_PROCESS_ALIVE = True
```

根因「Flask 请求线程里的 CTRL_BREAK 会关掉 WebUI」：`NOT CONFIRMED`

子进程收到 CTRL_BREAK 并退出：`CONFIRMED`

---

## 3. 与症状相关、已由代码确认的事实

| 项 | 结论 |
|---|---|
| Bot 启动时已使用 `CREATE_NEW_PROCESS_GROUP` | `CONFIRMED` |
| `os.kill(pid, CTRL_BREAK_EVENT)` 会发给该 PID 对应的 process group | `CONFIRMED`（子进程 SIGBREAK 已收到） |
| CTRL_BREAK 打到 WebUI 父进程 / Flask 主线程 | `NOT CONFIRMED`（三次探针父进程均存活） |
| Werkzeug `serve_forever` 遇到 `KeyboardInterrupt` 会 `server_close()`，之后 `/bot_status` 变为 Failed to fetch | `CONFIRMED`（读 `werkzeug/serving.py`） |
| WebUI 原进程未忽略 SIGBREAK | `CONFIRMED` |
| `stop_bot_process` 仅凭数字 PID 即可 kill，无 cmdline / 创建时间 / 非 WebUI 校验 | `CONFIRMED` |
| 心跳 `current_bot_pid` 原逻辑不校验是否为 `bot.py` | `CONFIRMED` |
| 前端 `checkBotStatus` 任意 fetch 失败即展示「后台已关闭，请重新启动」 | `CONFIRMED` |
| 前端 `toggleBot` 在后台不可达时展示「后台服务不可用，请检查服务状态。配置未保存。」 | `CONFIRMED` |
| `GET /status` 原先不存在，存活探测走 `GET /bot_status` | `CONFIRMED` |
| 真实微信 Stop Bot 当时的 WEB_PID / BOT_PID / 谁收到 CTRL_BREAK 的现场日志 | `NOT CONFIRMED`（本轮未连正在跑的真机 WebUI+Bot 会话） |

---

## 4. 根因陈述

**「Stop Bot 的 CTRL_BREAK 因为未建独立 process group，把 WebUI 一并打断」：`NOT CONFIRMED`**

代码里已经有 `CREATE_NEW_PROCESS_GROUP`。隔离探针、同控制台探针、Flask 请求线程探针都显示：

- Bot 子进程收到 SIGBREAK 并退出
- WebUI / 父进程未收到 SIGBREAK，HTTP 仍然可访问

**「仅凭 PID 数字停止、可能误伤 WebUI」：代码缺陷 `CONFIRMED`，现场误伤 `NOT CONFIRMED`。**

没有进程身份校验时，一旦 `current_bot_pid` 被写成 WebUI PID，`os.kill` / `terminate` / `kill` 会打到 PID A。本轮没有捕获到一次真实心跳把 WebUI PID 写成 BOT_PID 的日志，所以现场是否由此触发：`NOT CONFIRMED`。

**「前端把 Stop 请求失败直接显示成后台已关闭」：`CONFIRMED`（表现层）。**

若 `/stop_bot` 连接被重置，`error.message` 为 `Failed to fetch`；5 秒轮询 `/bot_status` 再失败则显示「后台已关闭」。这与用户描述一致，但它是后端真死或请求失败之后的 UI 映射，不是后端退出的原因。

---

## 5. 针对已确认风险的修复（不是把未确认项写成已确认）

即使 CTRL_BREAK 打到父进程在探针中为 `NOT CONFIRMED`，下列防护仍然落地，因为它们对应已确认的代码缺口，且符合目标进程模型：

1. WebUI 启动时 `SIGBREAK -> SIG_IGN`，避免万一主线程收到 KeyboardInterrupt 就 `server_close()`。
2. 发送 CTRL_BREAK 期间 `SetConsoleCtrlHandler(NULL, TRUE)`，只发给已校验的 Bot process group。
3. 停止前校验 PID / cmdline（必须是本项目 `bot.py` 或 `bot.exe`）/ 非 WebUI PID / 创建时间。
4. 心跳 PID 同样校验，拒绝写成 `config_editor.py`。
5. 优雅停止成功后先等进程自己退出；只有仍存活才强制结束。
6. `GET /status` 与 `GET /bot_status` 在 WebUI 存活时继续 200。
7. 前端 Stop 失败时先再探活 `/bot_status`：后台仍在则不要改口成「停止成功」，也不要在后台仍可达时把按钮锁死成必须重跑 `config_editor.py`。

---

## 6. 本轮当时不能宣布的事项（取证时）

取证当日真机 Stop → Start 多轮、以及 `ceshi → robot` 微信回归尚未跑完，故当时 **不宣布 P0 CLOSED**。

---

## 7. 真实微信最终回归（2026-09-20）

下列项已在真实微信 + WebUI 环境通过：

| 项 | 结果 |
|---|---|
| Stop Bot 不再导致 WebUI 退出 | PASS |
| Stop 后 `GET /status`、`GET /bot_status` 保持可访问 | PASS |
| Stop 后可以再次 Start | PASS |
| Bot PID 与 WebUI PID 身份隔离校验 | PASS |
| Stop → Start 多轮回归 | PASS |
| 页面不再出现 `stopped is not defined` | PASS |
| 页面不再因为 Stop 错误显示「后台已关闭」 | PASS |

前端「后台已关闭」横幅仍只在 `/bot_status` **真正不可达** 时显示；Stop 成功且 WebUI 存活时走「机器人已停止」，不误报后台退出。

详见 `P0-STOP-START-LIFECYCLE-TEST.md`、`P0-CLOSURE-REPORT.md`。  
**P0 STATUS = CLOSED**
