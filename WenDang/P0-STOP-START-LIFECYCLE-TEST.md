# P0 Stop / Start 生命周期测试

> 日期：2026-09-20  
> 环境：Windows，WebUI `config_editor.py` + Bot `bot.py` 子进程 + 真实电脑微信  
> **P0 STATUS = CLOSED**

---

## 1. 目标进程模型

```text
WebUI  PID A   python config_editor.py
    │
    └── Start Bot
        Bot PID B   python bot.py     CREATE_NEW_PROCESS_GROUP
```

停止时只允许操作 **已校验的 PID B**。  
PID A 必须继续提供 `GET /status`、`GET /bot_status`。

---

## 2. 校验规则

`webui_bot_process.inspect_bot_process`：

| 拒绝原因 | 含义 |
|---|---|
| `pid_is_webui_self` | 目标就是 WebUI |
| `pid_is_config_editor` | cmdline 是配置页，不是 bot |
| `cmdline_not_bot` | 不是本项目 `bot.py` / `bot.exe` |
| `create_time_mismatch` | 不是这次 Start 拉起的进程 |

心跳写入 `current_bot_pid` 走同一套校验。

Stop 路径：

1. 写 `STOP_REQUEST`
2. 等最多 12 秒进入 `STOPPED` 或进程退出
3. 仍存活才对 PID B 发隔离 `CTRL_BREAK` / terminate / kill

---

## 3. 自动测试

`tests/test_webui_bot_process.py`：

| 用例 | 结果 |
|---|---|
| Windows 启动使用 `CREATE_NEW_PROCESS_GROUP` | PASS |
| 拒绝空 PID / WebUI 自身 PID | PASS |
| 拒绝当前非 bot 进程 | PASS |
| `GET /status` 返回 200，含 `state`、`web_pid` | PASS |
| `start_bot` / `stop_bot` 走 helper，不再裸 `os.kill(..., CTRL_BREAK)` | PASS |

`tests/test_p0_message_runtime.py` TEST-06～10：Stop 禁发、清队列、停后新消息 NO_ACTION、再 Start 恢复。**PASS**。

---

## 4. 真实微信最终回归

| 项 | 结果 |
|---|---|
| Stop Bot 不再导致 WebUI 退出 | PASS |
| Stop 后 `/status`、`/bot_status` 保持可访问 | PASS |
| Stop 后可以再次 Start | PASS |
| Bot PID 与 WebUI PID 身份隔离校验 | PASS |
| Stop → Start 多轮回归 | PASS |
| 页面不再出现 `stopped is not defined` | PASS |
| 页面不再因为 Stop 错误显示「后台已关闭」 | PASS |

前端约定：

- `toggleBot` 使用 `statusData.status` / `statusData.state`，不再引用未定义的 `stopped`。
- Stop 请求异常时先再拉 `/bot_status`：WebUI 仍在则不展示「后台已关闭」。
- 「后台已关闭，请重新启动」只在状态接口真正失败时显示。

---

## 5. 已知限制（不阻塞 P0）

进行中的一次 `wx.SendMsg` 内部鼠标动作没有协作取消 API。  
Stop 会禁止后续发送；若该次 GUI 调用卡住，12 秒后结束 **Bot PID**，WebUI 继续存活。
