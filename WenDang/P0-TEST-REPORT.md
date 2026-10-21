# P0 测试与验收

> 日期：2026-09-20  
> 范围：消息底座 P0（Self / Dedupe / Outbound Guard / Stop Bot / Trigger / 微信纯文本 / Stop-Start 生命周期）  
> 未改：Prompt / 配置管理（上一阶段已收口）  
> **P0 STATUS = CLOSED**

---

## 单元测试（本机已跑）

命令：

```text
python -m unittest tests.test_p0_message_runtime tests.test_runtime_admit tests.test_pipeline tests.test_wechat_reply_format tests.test_webui_bot_process tests.test_webui_data
```

结果：**59 tests, OK**（2026-09-20 收口当日复跑）

| 用例 | 结果 |
|---|---|
| TEST-01 不同身份 ceshi→robot，INBOUND self=false | PASS |
| TEST-02 sender_id=2 且无 wxid 确认，INBOUND self=false | PASS |
| TEST-03 机器人发出内容回流，NO_ACTION | PASS |
| TEST-04 同一 platform_message_id 捕获 3 次，只 REPLY 1 次 | PASS |
| TEST-05 10 条不同普通消息均 REPLY | PASS |
| TEST-05b 用户短时重复同一句（不同 id）不误杀 | PASS |
| TEST-06 Stop 后禁止后续发送 / 新入队 | PASS |
| TEST-07 队列 5 条待发，Stop 后 pending=0 | PASS |
| TEST-08 自动化循环检查 allow_ui_automation，Stop 后中断 | PASS |
| TEST-09 Stop 后新消息 NO_ACTION，不发、不调 UI、llm_aborted | PASS |
| TEST-10 Start 后恢复 REPLY | PASS |
| TEST-11 自身回复回流 20 轮均 NO_ACTION | PASS |
| TEST-12 日志字段含 INBOUND/OUTBOUND、SELF/EXTERNAL、DUPLICATE/NEW、NO_ACTION/REPLY 及 reason | PASS |
| TEST-A01 标题 `##` 转为纯文本 | PASS |
| TEST-A02 加粗 `**` 转为纯文本 | PASS |
| TEST-A03 Markdown 表格转为「列名：值」 | PASS |
| TEST-A04 混合 Markdown 仍只拆成 1 条正文 | PASS |
| WebUI `/status` 存活、PID 拒绝 WebUI 自身、独立 process group | PASS |

同机分身根因：**CONFIRMED**（见 `P0-SELF-ROOT-CAUSE.md`）。  
决策函数：`sender_id==2` 不再判 self。真实微信已复验通过。

---

## 真实微信最终回归（已完成）

环境：电脑微信在线，监听对象 ceshi；同机微信分身登录机器人号。

| 项 | 结果 |
|---|---|
| ceshi → robot 普通消息 | PASS：INBOUND，self=false，产生回复 |
| 同机微信分身不再误判 self | PASS |
| 自身回复回流不再二次触发 | PASS |
| Markdown 表格 / 标题 / 加粗转为微信纯文本 | PASS |
| 回复正文一次性发送，不再按换行分段 | PASS |
| Stop Bot 不再导致 WebUI 退出 | PASS |
| Stop 后 `/status`、`/bot_status` 保持可访问 | PASS |
| Stop 后可以再次 Start | PASS |
| Bot PID 与 WebUI PID 身份隔离校验 | PASS |
| Stop → Start 多轮回归 | PASS |
| 页面不再出现 `stopped is not defined` | PASS |
| 页面不再因为 Stop 错误显示「后台已关闭」 | PASS |

详见 `P0-STOP-START-LIFECYCLE-TEST.md`、`P0-WECHAT-PLAINTEXT-FIX-REPORT.md`、`P0-CLOSURE-REPORT.md`。

---

## 无法协作中断的线程 / 调用（已知限制，不阻塞 P0）

| 项 | 停法 | 说明 |
|---|---|---|
| wechatauto `SendMsg` 内部鼠标/键盘 | 协作取消点只在调用前与动作之间；调用中需进程结束 | 优雅停止 12s 超时后 WebUI 仍会 kill **已校验的 Bot PID** |
| OpenAI HTTP `stream=False` | 调用前/重试前检查 abort；进行中的一次请求等返回后丢弃 | 紧急停止仍 `os._exit(0)` |
| `KeepRunning` / Listener | `StopListening`；失败则杀进程 | 依赖 wechatauto |

可中断：`user_queues` 消费、`SendQueue` 未执行任务、emoji Timer、主动消息线程、新 UI automation、新 LLM 调用。

---

## 关键行为变化（已冻结）

1. `is_self_message(message, runtime_identity)` 只用 sender wxid / bot wxid / direction / outbound。昵称与 `sender_id==2` 不足。
2. 统一 dedupe：`platform_message_id` 优先，否则 `event_hash`（会话+发送者+类型+2s 时间桶+正文）。
3. 发送前 `register_outbound`；回流 `NO_ACTION`。
4. Stop Bot：写 `STOP_REQUEST` → `STOPPING` → 禁收、清队列、取消 LLM/UI、StopListening → `STOPPED`；超时只杀已校验的 Bot PID。前端仅 `STOPPED` 显示已停止。
5. Trigger：`NO_ACTION` / `REPLY`（`UPDATE_ONLY` 预留）。
6. outbound 执行前检查 `bot_state in (RUNNING, DEGRADED)`。
7. 微信发出前走 `WeChatPlainTextFormatter`；正文一次发送。
8. WebUI 与 Bot PID 隔离：`inspect_bot_process` + `SIGBREAK` 忽略 + 隔离 `CTRL_BREAK`。
