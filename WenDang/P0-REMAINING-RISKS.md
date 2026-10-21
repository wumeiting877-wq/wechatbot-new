# P0 剩余风险

> 日期：2026-09-20  
> 范围：消息底座 P0  
> **P0 STATUS = CLOSED**  
> 已解决项移出 Active Risk。下列问题真实存在，**不阻塞下一阶段**。

---

## Active Risk（不阻塞 P0 / 不阻塞下一阶段）

1. **进行中的 `wx.SendMsg` 鼠标/键盘无法协作取消**  
   wechatauto 一次 GUI 发送是阻塞调用。Stop 能禁止新发送、清空未执行队列，并在调用前检查 `allow_ui_automation()`。已经进入 `SendMsg` 内部的动作只能等返回，或 12 秒超时后结束 **已校验的 Bot PID**。WebUI 不会被一起停掉。

2. **进行中的 OpenAI HTTP 无法中途取消**  
   主模型调用 `stream=False`。Stop 后会设 abort，下一次调用前生效；当前这一次等返回后丢弃，不发出。紧急停止仍 `os._exit(0)`。

3. **`UPDATE_ONLY` / Topic Engine 未实现**  
   Trigger 已预留 `UPDATE_ONLY`。完整 Topic / Task / Risk 引擎属于后续阶段，不是 P0 缺口。

4. **发送标志双轨仍在**  
   `can_send_messages` / `is_sending_message` 与 `BotRuntime` 并存。P0 已把杀开关接到 runtime。后续拆发送主链时再收敛，本轮不强行删除。

5. **微信客户端为何把同机分身入站写成 `sender_id=2`：NOT CONFIRMED**  
   无当时 SQLite row dump。项目已不再用该字段判 self，真机 ceshi → robot 已通过。不阻塞下一阶段。

6. **语音转写 / 合并转发仍不可用**  
   依赖 wechatauto 能力，P0 未承诺修复。

7. **配置热更新仍有限**  
   主模型客户端、监听列表仍需重启 Bot 才完全生效。属配置面限制，不是消息网关回归。

8. **已出现过的 API Key 需人工轮换**  
   旧 `config.py` 曾含真实 Key，已迁 `.env`。若历史备份外传，须在服务商控制台作废。安全债，不阻塞消息底座。

9. **管理面 CSRF 未全覆盖**  
   WebUI 仍绑定 `127.0.0.1`。改为对外监听前必须补 CSRF。不阻塞 P0。

---

## 已移出 Active Risk（本轮已关闭）

| 原风险 | 关闭依据 |
|---|---|
| ceshi → robot 被判 self | 真机 PASS；`sender_id==2` 不再充分 |
| 同机微信分身误判 self | 真机 PASS |
| 自身回复回流再次触发 / 无限回复 | 真机 + TEST-03/11 PASS |
| 同一消息重复捕获多次处理 | TEST-04 PASS |
| Stop 后继续发队列 / 新消息仍进 AI | TEST-06/07/09 PASS |
| Stop 把 WebUI 一起打掉 | 真机 PASS；PID 隔离 |
| Stop 后 `/status`、`/bot_status` 不可访问 | 真机 PASS |
| Stop 后无法再 Start | 真机多轮 PASS |
| 页面 `stopped is not defined` | 真机 PASS |
| Stop 误报「后台已关闭」 | 真机 PASS |
| 微信回复残留 Markdown 表格/标题/加粗 | 真机 PASS |
| 回复正文按换行分段发送 | 真机 PASS |

无限回复、Stop 后继续发送、鼠标在 Stop 后仍被新任务占用：**不再列为待解决问题**。

---

## 冻结

P0 代码冻结。除非未来出现回归 Bug，否则不要继续修改 P0 业务代码。  
本文件不自动开启 P3。
