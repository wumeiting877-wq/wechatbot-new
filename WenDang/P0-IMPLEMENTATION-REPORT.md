# P0 实施报告

> 日期：2026-09-20  
> 范围：Self / Dedupe / Outbound Guard / Trigger / Stop Kill Switch / 微信纯文本 / WebUI-Bot 进程隔离  
> 未改：Prompt / 配置管理  
> **P0 STATUS = CLOSED**

---

## 1. Self 判断

- **问题**：同机主微信 ceshi → 分身 robot，入站被标 `self=true` 并丢弃。
- **根因**：`WxMessage` 把 `sender_id==2` 写成 `attr=self`，`classify_incoming_attr` 无条件 DROP。见 `P0-SELF-ROOT-CAUSE.md`。
- **修改文件**：`wxbot.py`、`message/identity.py`、`message/pipeline.py`、`message/listener.py`、`bot_runtime.py`
- **修改方式**：抽出 `is_self_message()`；仅 wxid / direction / outbound 可判 self；`sender_id==2` 无 wxid 确认时 EXTERNAL。
- **测试**：`tests/test_p0_message_runtime.py` TEST-01/02；真实微信 ceshi → robot。
- **结果**：单元 PASS；真机 PASS。
- **是否闭环**：是。

## 2. 消息去重

- **问题**：监听层可能重复回调；旧 5 秒同窗口同文本会误杀用户连发。
- **修改文件**：`message/dedupe.py`、`bot_runtime.py`、`message/listener.py`
- **修改方式**：统一 `DedupeIndex`：优先 `platform_message_id`，否则含发送者的 `event_hash`。
- **测试**：TEST-04 / TEST-05 / TEST-05b。
- **结果**：PASS。
- **是否闭环**：是。

## 3. Outbound Loop Guard

- **问题**：机器人自己发出的内容回流后可能再次进 AI。
- **修改文件**：`message/outbound.py`、`bot.py`（`send_reply` 发送前 `register_outbound`）、`bot_runtime.py`
- **修改方式**：发送前登记 conversation + content hash；回流 `NO_ACTION`。
- **测试**：TEST-03、TEST-11（20 轮）；真实微信自身回复回流。
- **结果**：PASS。
- **是否闭环**：是。

## 4. Trigger Engine

- **问题**：过了 attr 过滤就进 AI，没有统一动作。
- **修改文件**：`message/trigger.py`、`bot_runtime.py`
- **修改方式**：`NO_ACTION` / `REPLY`；`UPDATE_ONLY` 预留。stopped / outbound / self / duplicate / unauthorized 先拦截。
- **测试**：TEST-09 / TEST-12。
- **结果**：PASS。
- **是否闭环**：P0 范围是。Topic Engine 不属于 P0。

## 5. Stop Bot Kill Switch

- **问题**：Stop 只杀 PID、前端以进程死活当停止；进行中发送与队列可能继续。
- **修改文件**：`bot_runtime.py`、`bot.py`、`config_editor.py`
- **修改方式**：`STOP_REQUEST` → `STOPPING` → 禁收、清队列、取消 LLM/UI → `STOPPED`。`ensure_can_send` 要求 RUNNING/DEGRADED。
- **测试**：TEST-06～10。
- **结果**：PASS。
- **是否闭环**：是。进行中的单次 `SendMsg` 无协作取消点，列为已知限制。

## 6. WebUI 与 Bot 进程隔离

- **问题**：Stop 后页面像后台一起关掉，无法再 Start。
- **根因**：见 `P0-STOP-WEBUI-RCA.md`。CTRL_BREAK 打到父进程 **NOT CONFIRMED**；无 PID 身份校验、前端把 Stop 失败映射成「后台已关闭」**CONFIRMED**。
- **修改文件**：`webui_bot_process.py`、`config_editor.py`、`static/js/config_editor.js`
- **修改方式**：独立 process group；WebUI `SIGBREAK` 忽略；隔离 `CTRL_BREAK`；`inspect_bot_process` 拒绝 WebUI PID / `config_editor.py`；心跳同样校验；`GET /status` 与 `/bot_status` 同存活；Stop 失败先探活。
- **测试**：`tests/test_webui_bot_process.py`；真实微信 Stop → Start 多轮。
- **结果**：PASS。
- **是否闭环**：是。

## 7. 微信纯文本

- **问题**：回复仍带 Markdown 表格 / 标题 / 加粗；正文曾按换行分段。
- **修改文件**：`message/reply_format.py`、`bot.py`
- **修改方式**：`WeChatPlainTextFormatter`；仅识别到 table separator 时改写表格；正文一次发送。
- **测试**：`tests/test_wechat_reply_format.py` TEST-A01～A04；真实微信回复。
- **结果**：PASS。
- **是否闭环**：是。

---

## 修改文件清单

| 文件 | 角色 |
|---|---|
| `message/identity.py` | 新增。`InboundMessage` / `is_self_message` |
| `message/dedupe.py` | 新增。统一去重 |
| `message/outbound.py` | 新增。Outbound Guard |
| `message/trigger.py` | 新增。NO_ACTION / REPLY |
| `message/reply_format.py` | 微信纯文本 + 一次发送 |
| `message/listener.py` | 走 `evaluate_inbound` |
| `message/pipeline.py` | `attr=self` 不再无条件 DROP |
| `wxbot.py` | 禁止仅凭 `sender_id==2` 标 self；补 wxid / platform_message_id |
| `bot_runtime.py` | `evaluate_inbound`、优雅停止、outbound/dedupe 接入 |
| `bot.py` | 发送前登记 outbound；纯文本格式化 |
| `webui_bot_process.py` | 新增。PID 校验、隔离 CTRL_BREAK |
| `config_editor.py` | Start/Stop、`/status`、心跳校验 |
| `static/js/config_editor.js` | Stop 失败探活；去掉错误的 `stopped` 未定义引用 |
| `tests/test_p0_message_runtime.py` | TEST-01～12 |
| `tests/test_runtime_admit.py` | 旧 admit 路径对齐新规则 |
| `tests/test_wechat_reply_format.py` | 纯文本 |
| `tests/test_webui_bot_process.py` | 进程隔离 |

未改 Prompt / 配置管理相关文件。
