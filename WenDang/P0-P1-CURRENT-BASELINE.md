# P0-P1 当前基线报告

> 扫描日期：2026-09-19  
> 扫描方式：READ ONLY  
> 代码版本：v2.2.5

---

## 4.1 当前项目版本

| 项 | 值 |
|---|---|
| 当前版本号 | 2.2.5（`pyproject.toml`） |
| Python 要求 | >=3.9 |
| 主要依赖 | `wechatauto-replica[guia]>=1.2.0`（pyproject）/ `>=1.0.4`（requirements 不一致）；`openai==1.84.0`；Flask；psutil；filelock；requests；beautifulsoup4；lxml |
| 启动入口 | `python config_editor.py` / `wechatbot-webui`；遗留 `Run.exe` |
| WebUI 入口 | `config_editor.py` → Flask `127.0.0.1:5000` |
| Bot 入口 | `bot.py` `main()`，由 WebUI 用 `sys.executable` 拉起子进程 |
| 微信适配层 | `wxbot.py`（wechatauto-replica，读库 + GUI 发送） |
| runtime 控制 | `bot_runtime.py` |

---

## 4.2 已闭环能力

以下问题在本阶段扫描中**未发现回归**，代码路径仍由 `bot_runtime` 控制。本轮**不得重复整改**。

| 能力 | 结论 | 证据 |
|---|---|---|
| 无限回复 | BASELINE PASS | `admit_message` 去重 / 内容窗口去重 / `allow_reply` 限流（10s 冷却、每分钟 5 条） |
| Stop Bot | BASELINE PASS | 紧急停止标志文件 + 监视线程；`is_send_blocked()` 贯穿发送与 AI |
| 停止后发送 | BASELINE PASS | `submit_send` / `ensure_can_send` / 队列清空；紧急 hook 清空 `user_queues` |
| GUI 控制释放 | BASELINE PASS | 紧急停止后不再进入发送队列；本轮不改 GUI 中断机制 |

---

## 4.3 当前核心结构

```text
WebUI          config_editor.py + templates/config_editor.html
Bot            bot.py (main / 线程编排 / 消息主链)
Runtime        bot_runtime.py
WeChat Adapter wxbot.py
Config         config.py（Python 源码兼运行配置，WebUI 正则改写）
Memory         CoreMemory/ + Memory_Temp/ + chat_contexts.json
Reminder       recurring_reminders.json + bot.py 提醒函数
LLM            bot.py 内 OpenAI 客户端（主/辅助/识图/联网）
Logs           runtime_control/events.jsonl + 控制台日志
```

---

## 4.4 当前技术债

| 项 | 现状 |
|---|---|
| `bot.py` | 约 4640 行，职责过载 |
| `config_editor.py` | 约 4040 行 |
| `config_editor.html` | 约 5350 行 |
| 全局变量 | `can_send_messages`、`is_sending_message`、`user_queues`、`chat_contexts`、`wx` 等仍与 runtime 双轨并存（本轮不强行删除） |
| 常驻线程 | keep_alive / InactiveUserChecker / MemoryManager / ReminderChecker / AutoMessageChecker / BotHeartbeatThread / MemoryUsageMonitor + runtime 控制线程 |
| 配置来源 | 仅 `config.py`，WebUI `parse_config()` / `update_config()` 正则改 Python |
| 运行数据 | `CoreMemory/`、`Memory_Temp/`、`chat_contexts.json`、`runtime_control/`、论坛 `forum_data/` 散落根目录 |
| 真实 Key | `config.py` 中存在真实 DeepSeek API Key（须立即隔离并轮换） |
| 自动化测试 | 无 pytest/unittest；`test_bot.py` 会连真实微信，不能当 CI |
| `__init__.py` | `os.system('Run.exe')` import 副作用 |
| 登录 | `ENABLE_LOGIN_PASSWORD = False`；`secret_key` 每次随机；密码明文 |
| 能力状态 | 未配置 Key 时后台降级，Bot 进入 `DEGRADED`，页面缺少能力矩阵 |
| API 错误 | `call_chat_api_with_retry` 最终 `raise RuntimeError("阿文提示：api余额不足")` |
| LLM 成本 | 普通文本：提醒有关键词预筛；联网/表情在辅助模型未就绪时会回退打主模型；`get_deepseek_response` 每次 `load_chat_contexts()` |
| 宣称不一致 | README 写支持语音/合并转发；兼容层语音 `to_text()` 返回空；合并转发 `get_messages()` 常为 None；定时重启 `if False and ENABLE_SCHEDULED_RESTART` |

---

## 4.5 本轮执行范围（对照修订版提示词）

按 STEP 2 → STEP 8 推进，不进入第二阶段，不重复改 Stop Bot / 无限回复。
