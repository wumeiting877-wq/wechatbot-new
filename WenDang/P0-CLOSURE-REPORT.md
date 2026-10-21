# P0 最终收口报告

> 日期：2026-09-20  
> 项目：wechatbot-new 消息底座  
> 依据：`P0-MESSAGE-RUNTIME-ASIS.md`、`P0-SELF-ROOT-CAUSE.md`、`P0-MESSAGE-GATEWAY-DESIGN.md`、`P0-IMPLEMENTATION-REPORT.md`、`P0-TEST-REPORT.md`、`P0-REMAINING-RISKS.md`、`P0-STOP-WEBUI-RCA.md`、`P0-STOP-START-LIFECYCLE-TEST.md`、`P0-WECHAT-PLAINTEXT-FIX-REPORT.md`  
> 真实微信最终回归：已完成  
> 本文件收口后 **不再修改 P0 业务代码**

---

## 一、P0 原始问题

P0 要稳定的是消息底座，不是 Prompt、不是配置管理、也不是 Topic Engine。

原始故障与缺口：

1. **Self 误判**：同机主微信 `ceshi` 向分身机器人发普通消息，后端当成 `self=true` 丢弃，不进 AI。
2. **去重不可靠**：监听重复捕获可能双处理；短时同文本又可能误杀用户连发。
3. **Outbound 回流**：机器人自己发出的内容再次进入监听后，可能再次触发回复，形成循环。
4. **Stop 不是杀开关**：Stop 后仍可能继续处理、排队发送；WebUI 还可能一起失联，无法再 Start。
5. **没有统一 Trigger**：过了 attr 过滤就进 AI，日志看不出 INBOUND/OUTBOUND、SELF/EXTERNAL、NO_ACTION/REPLY。
6. **微信气泡残留 Markdown**：表格 `|---|---|`、标题、加粗直接打进微信；正文还曾分段发送。
7. **前端误报**：Stop 后出现 `stopped is not defined`，或把 Stop 失败显示成「后台已关闭」。

---

## 二、根因

### 1. Self 误判 — CONFIRMED

```text
WxMessage.__init__
    sender_id in (2, "2")  →  attr = "self"
        ↓
classify_incoming_attr(attr=="self")
        ↓
reason = self_message
        ↓
message_listener 丢弃，不进 AI
```

运行日志 2026-09-19 10:09:34：电脑微信登录号是 **扶级**，会话 **ceshi**，打出「检测到 Bot 自己发送的消息」。  
当时能把入站行标成 self 的有效条件只有 **`sender_id==2`**。没有用 sender wxid / bot wxid / direction / outbound。

微信客户端为何写 `sender_id=2`：无 SQLite dump，**NOT CONFIRMED**。项目误判路径 **CONFIRMED**。

### 2. Stop 后 WebUI 失联

「CTRL_BREAK 因未建独立 process group 打到 WebUI」：**NOT CONFIRMED**（代码已有 `CREATE_NEW_PROCESS_GROUP`，三次探针父进程均存活）。

已确认代码缺口：

- 停止时只拿数字 PID kill，不校验是不是 `bot.py`
- WebUI 不忽略 SIGBREAK；Werkzeug 主线程一旦 KeyboardInterrupt 会 `server_close()`
- 前端把 Stop / 状态 fetch 失败映射成「后台已关闭」

### 3. Markdown 表格

发出前只清了加粗/标题/代码块，**没有识别 Markdown Table**。全局删 `|` 会误伤业务竖线，因此必须按 separator 行结构化转换。

---

## 三、最终架构

```text
微信本地库轮询
    → WxMessage（稳定身份字段；禁止仅凭 sender_id==2 标 self）
    → message_listener
    → evaluate_inbound
          stopped → outbound → self → system → dedupe → trigger
    → REPLY：现有私聊名单 / 群规则 → LLM
    → send_reply
          WeChatPlainTextFormatter
          正文一次发送
          register_outbound
          wx.SendMsg
    → 回流 → Outbound Guard → NO_ACTION
```

状态机：`STOPPED / STARTING / RUNNING / STOPPING / ERROR / DEGRADED`  
可工作：仅 `RUNNING`、`DEGRADED`。  
Stop：`STOP_REQUEST` → `STOPPING` → 禁收、清队列、取消 LLM/UI → `STOPPED`。超时只杀已校验 Bot PID。  
WebUI PID 与 Bot PID 身份隔离。

---

## 四、修改文件

| 文件 | 变更 |
|---|---|
| `message/identity.py` | 新增 `is_self_message` |
| `message/dedupe.py` | 新增统一去重 |
| `message/outbound.py` | 新增 Outbound Guard |
| `message/trigger.py` | 新增 NO_ACTION / REPLY |
| `message/reply_format.py` | 微信纯文本 + 一次发送 |
| `message/listener.py` | 走网关准入 |
| `message/pipeline.py` | attr=self 不再无条件 DROP |
| `wxbot.py` | 稳定身份字段；禁止 sender_id==2 单独标 self |
| `bot_runtime.py` | evaluate_inbound、优雅停止 |
| `bot.py` | outbound 登记；纯文本发出 |
| `webui_bot_process.py` | PID 校验、隔离 CTRL_BREAK |
| `config_editor.py` | Start/Stop、`/status`、心跳校验 |
| `static/js/config_editor.js` | 去掉未定义 `stopped`；Stop 失败先探活 |
| `tests/test_p0_message_runtime.py` | TEST-01～12 |
| `tests/test_runtime_admit.py` | 对齐新 Self 规则 |
| `tests/test_wechat_reply_format.py` | TEST-A01～A04 |
| `tests/test_webui_bot_process.py` | 进程隔离 |

未改 Prompt / 配置管理。

---

## 五、真实测试结果

真实微信环境，ceshi → robot，最终回归全部通过：

| # | 项 | 结果 |
|---|---|---|
| 1 | 微信真实环境 ceshi → robot 已验证 | PASS |
| 2 | 同机微信分身不再误判 self | PASS |
| 3 | 自身回复回流不会再次触发 | PASS |
| 4 | Markdown 表格、标题、加粗已转换为微信纯文本 | PASS |
| 5 | 回复正文一次性发送，不再分段 | PASS |
| 6 | Stop Bot 不再导致 WebUI 退出 | PASS |
| 7 | Stop 后 `/status`、`/bot_status` 保持可访问 | PASS |
| 8 | Stop 后可以再次 Start | PASS |
| 9 | Bot PID 与 WebUI PID 已做身份隔离校验 | PASS |
| 10 | Stop → Start 多轮回归通过 | PASS |
| 11 | 页面不再出现 `stopped is not defined` | PASS |
| 12 | 页面不再因为 Stop 错误显示「后台已关闭」 | PASS |

验收对照：

| 标准 | 结果 |
|---|---|
| 普通用户 → 机器人 = INBOUND | PASS |
| 机器人 → 用户 = OUTBOUND | PASS |
| 同机分身 ceshi → robot self=false | PASS |
| 同一消息重复捕获只处理一次 | PASS（单测锁定，真机路径已启用同一网关） |
| 机器人回复回流 = NO_ACTION | PASS |
| 无限回复循环不可复现 | PASS |
| Stop 阻止新处理 / 新 AI / 待发队列 | PASS |
| Stop 后不再继续发送新业务消息 | PASS |
| Stop 后 WebUI 可访问并可再次 Start | PASS |

---

## 六、自动测试结果

收口当日复跑：

```text
python -m unittest tests.test_p0_message_runtime tests.test_runtime_admit tests.test_pipeline tests.test_wechat_reply_format tests.test_webui_bot_process tests.test_webui_data
```

**59 tests, OK**

覆盖：TEST-01～12、admit、pipeline、纯文本 A01～A04、WebUI PID 隔离与 `/status`。

---

## 七、Stop / Start 生命周期

```text
Start  → STARTING → RUNNING
Stop   → 写 STOP_REQUEST → STOPPING
       → 禁止新任务 / 清空发送队列 / 取消 LLM 与 UI
       → STOPPED
       → 进程仍在则只结束已校验 Bot PID
Start  → 再次拉起 bot.py（独立 process group）
```

已验证：

- WebUI 在 Stop 后继续提供 HTTP
- `/status`、`/bot_status` 返回 200
- 可再次 Start
- 多轮 Stop → Start 通过
- 不会把 WebUI PID 当成 Bot 杀掉

详见 `P0-STOP-START-LIFECYCLE-TEST.md`、`P0-STOP-WEBUI-RCA.md`。

---

## 八、Self / Dedupe / Outbound Guard

**Self**

- 充分条件：sender wxid == bot wxid，或 direction=OUTBOUND，或 outbound 命中。
- `sender_id==2` 且无 wxid 确认 → EXTERNAL，reason=`sender_id_2_unconfirmed_identity`。
- 昵称、窗口、鼠标、设备不是充分条件。

**Dedupe**

- 优先 `platform_message_id`。
- 否则 `event_hash`（会话 + 发送者 + 类型 + 2s 桶 + 正文）。
- 重复捕获只处理一次；两人同一句、用户连发同一句不误杀。

**Outbound Guard**

- `SendMsg` 前 `register_outbound`。
- 回流按 platform_message_id 或 conversation+content_hash 匹配。
- 命中 `NO_ACTION`，不进 AI。20 轮单测 + 真机回流均通过。

日志字段：`INBOUND/OUTBOUND`、`SELF/EXTERNAL`、`DUPLICATE/NEW`、`NO_ACTION/REPLY`、`reason`。

---

## 九、当前已知但不阻塞 P0 的限制

1. 已经进入 wechatauto `SendMsg` 内部的鼠标动作无协作取消 API；超时后只结束 Bot PID。
2. 进行中的 OpenAI `stream=False` 请求等返回后丢弃。
3. `UPDATE_ONLY` / Topic Engine 预留，未实现。
4. `can_send_messages` / `is_sending_message` 与 runtime 双轨仍在。
5. 微信客户端写 `sender_id=2` 的内部机制 NOT CONFIRMED；项目已不依赖该字段。
6. 语音转写、合并转发仍不可用。
7. 配置热更新有限；CSRF 未全覆盖；历史 API Key 需人工轮换。

完整列表见 `P0-REMAINING-RISKS.md`。这些项 **不阻止宣布 P0 CLOSED**。

---

## 十、P0 CLOSED 结论

真实微信最终回归 12 项全部 PASS。  
自动测试 59 项 OK。  
P0 验收标准已满足。

**P0 STATUS = CLOSED**

P0 冻结：

- 除非未来出现回归 Bug，否则不要继续修改 P0 代码。
- 不自动进入 P3 / Topic Engine。
- 等待下一阶段指令。
