# P6-G0-FIX-LIFECYCLE Live Report

> 日期：2026-09-22 20:06～20:08  
> 窗口：最小 Stop/Start 生命周期。四个 Engine 保持 **false**。未跑 Real Topic/Task/Decision/Risk LLM。未让操作员发业务测试句。

运行中的 WebUI（`:5000` PID **15396**）是本轮改代码**之前**已启动的 `config_editor.py`。  
**新 `bot.py` 由 Popen 从磁盘加载，keep_alive 修复已进入真机 Bot。**  
`start_bot_preflight` 的 HTTP 409 需重启 WebUI 后才会替换旧路由；本次重复 Start 仍由旧逻辑「Flask 句柄仍活则不再 Popen」挡住第二棵树。

结束后系统回到 **STOPPED**，无残留 `bot.py`。WebUI 15396 仍在。

---

## 拓扑（LIVE-L1）

第一次 Start（20:06:16）：

| 角色 | PID | cmdline |
|---|---|---|
| WebUI | **15396** | `Python311\python.exe` `config_editor.py` 监听 `127.0.0.1:5000` |
| wrapper | **34552** | `.venv\Scripts\python.exe` `...\wechatbot-new\bot.py`（父=15396） |
| 真实 Bot | **34236** | `Python311\python.exe` `...\wechatbot-new\bot.py`（父=34552）=`status.json pid` |

```text
state        = RUNNING
wechat       = connected（智群Agent）
listen_count = 3
alive        = true
today_received = 0
```

`events.jsonl`：

```text
20:06:20  STOPPED → STARTING（进程启动）
20:06:25  微信连接：正常 智群Agent
20:06:26  监听对象数量：3
20:06:26  STARTING → RUNNING（主循环已就绪）
```

逻辑 Bot = 1 棵进程树。不是两个独立 Listener。

---

## LIVE-L2 收一条测试消息

**未执行。** RUNNING 窗口 `today_received=0`，本轮不发微信业务句。  
listener 侧只证明：单 worker PID、监听对象 3 个（配置项），不是「一条 inbound 的 callback 计数」。

---

## LIVE-L3 Stop Bot

20:07:40～20:07:42：

```text
RUNNING → STOPPING（stop_flag）
STOPPING → STOPPED（stop_flag）
HTTP 200  {"state":"STOPPED","web_pid":15396}
alive=false
bot.py 进程 = 无（34552 与 34236 均消失）
```

WebUI PID 15396 未死。未 taskkill python。

---

## LIVE-L4 Stop 后超过 keep_alive 周期

Stop 后再等 **7 秒**（原 keep_alive 周期 5 秒）：

```text
bot.py = NONE
state  = STOPPED
events 无新 AddListenChat / 无 STARTING
```

listener 未重生。

---

## LIVE-L5 Stop 后发消息

**未向微信发送。** Stop 后 Bot PID 已不存在，不能再跑 Chat/Topic/Task/Decision/Risk。  
离线 LIFE-08 已锁定 `reason=stopped`。

---

## LIVE-L6 再次 Start

20:08:15：

| 角色 | PID |
|---|---|
| WebUI | 15396 |
| wrapper | **15712** |
| 真实 Bot | **46952** = status.json pid |

```text
state=RUNNING wechat=connected listen_count=3
bot.py 进程树 = 2（wrapper+worker），逻辑 Bot = 1
```

`events.jsonl`：`20:08:22` 微信连接正常；`20:08:23` 监听对象数量：3；RUNNING。

---

## LIVE-L7 重复 Start

在 15712/46952 仍活时再次 POST `/start_bot`：

```text
HTTP 200  {"pid":15712,"status":"started"}   # 旧 WebUI 成功码，未第二次 Popen
bot.py 仍只有 15712 + 46952
```

没有第二棵 Bot。新代码在源码层对同一情况返回 **409 already_running**（离线 LIFE-05/05b）。重启 WebUI 后才会看到 409。

随后再次 Stop（20:08:40～20:08:42）：

```text
RUNNING → STOPPING → STOPPED
bot.py = NONE
web_pid = 15396
四个 Engine 开关 = false
```

---

## 判定

| Gate | 结果 |
|---|---|
| LIVE-L1 Start + PID 拓扑 | **PASS** |
| LIVE-L2 收测试消息 | **NOT RUN**（无 inbound） |
| LIVE-L3 Stop 至进程退出 | **PASS** |
| LIVE-L4 无 listener 重生 | **PASS** |
| LIVE-L5 Stop 后消息 | **NOT RUN**（进程已死；无发信） |
| LIVE-L6 再 Start 单实例 | **PASS** |
| LIVE-L7 拒绝第二 Bot | **PASS**（未第二 Popen） |

生命周期 BLOCKER 的真机部分：**成立**。Inbound 路径未在本窗口用手测微信。
