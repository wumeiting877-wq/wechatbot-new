# P0-P1 实施报告

> 日期：2026-09-19  
> 对照：`wechatbot-new-项目优化方向总结.md` + 第一阶段修订版提示词  
> 范围：STEP 2～STEP 7。未进入第二阶段。未改 Stop Bot / 无限回复 / GUI 中断。

---

## 1. 密钥写在可跟踪的 Python 配置里

- **问题**：`config.py` 同时是示例、运行配置和 Git 跟踪文件，本地已写入真实 API Key。
- **根因**：配置与代码未分离；WebUI 用正则改 Python 源码。
- **修改文件**：`app_config.py`、`config.py`（shim）、`config.example.json`、`.env.example`、`.gitignore`、`config_editor.py`
- **修改方式**：运行配置写入 `config.local.json`，密钥写入 `.env`；WebUI `parse_config()` / `update_config()` 改为读写结构化文件；旧 `config.py` 已迁移到 `config.py.legacy.bak`（gitignore）。
- **测试方法**：`tests/test_config_validate.py`
- **测试结果**：PASS。`config.local.json` 不含 `sk-`。
- **是否闭环**：是（本地隔离）。**必须轮换已经在旧 `config.py` 出现过的 API Key。**
- **剩余风险**：历史备份 / 旧提交里可能仍有 Key。

## 2. 运行数据未按真实目录忽略

- **问题**：`.gitignore` 写了 `core_memory/`，代码用 `CoreMemory/`。
- **根因**：大小写不一致。
- **修改文件**：`.gitignore`
- **修改方式**：同时忽略 `CoreMemory/`、`Memory_Temp/`、`runtime_control/`、`chat_contexts.json`、`recurring_reminders.json`、`.env`、`config.local.json`。
- **测试方法**：对照代码路径人工核对。
- **测试结果**：规则已对齐。
- **是否闭环**：是。本阶段未搬迁现有目录，避免破坏读取逻辑。
- **剩余风险**：若这些文件已被 Git 跟踪，需要另做 `git rm --cached`。

## 3. `__init__.py` import 启动 Run.exe

- **问题**：`import` 即 `os.system('Run.exe')`。
- **根因**：把目录当包导入会产生启动副作用。
- **修改文件**：`__init__.py`
- **修改方式**：改为无副作用包说明。
- **测试方法**：阅读文件。
- **测试结果**：无 `os.system`。
- **是否闭环**：是。

## 4. WebUI secret 随机、密码明文

- **问题**：`secret_key` 每次启动变化；密码明文写在配置里。
- **根因**：没有持久 secret；没有哈希。
- **修改文件**：`app_config.py`、`config_editor.py`、`templates/config_editor.html`
- **修改方式**：`FLASK_SECRET_KEY` 写入 `.env` 并固定；登录走 `verify_webui_password`；页面密码框留空表示不修改。
- **测试方法**：配置加载后检查 `.env` 含 `FLASK_SECRET_KEY`。
- **测试结果**：已生成并持久化。
- **是否闭环**：部分。仍默认本机 `127.0.0.1`、登录开关默认关。完整 CSRF 未铺到所有表单。

## 5. 未配置能力静默 DEGRADED

- **问题**：识图/联网/辅助模型 Key 缺失时 Bot 进入 `DEGRADED`，页面没有能力矩阵。
- **根因**：可选能力失败被当成整体降级。
- **修改文件**：`capabilities.py`、`bot.py`、`config_editor.py`、`templates/config_editor.html`
- **修改方式**：统一 `READY / DISABLED / NOT_CONFIGURED / ERROR`；未配置只关对应调用，不把主聊天打成 DEGRADED；首页展示能力状态。
- **测试方法**：`tests/test_capabilities.py`
- **测试结果**：PASS。
- **是否闭环**：是（信息可见）。运行中 Bot 进程需重启后新逻辑才完全生效。

## 6. API 失败一律报余额不足

- **问题**：`raise RuntimeError("阿文提示：api余额不足")`。
- **根因**：重试耗尽后没有按真实错误分类。
- **修改文件**：`llm_errors.py`、`bot.py`
- **修改方式**：区分 AUTH / RATE_LIMIT / TIMEOUT / NETWORK / MODEL / SERVICE / BALANCE / FILTER；用户看到通用不可用文案，日志记录 code。
- **测试方法**：`tests/test_llm_errors.py`
- **测试结果**：PASS。
- **是否闭环**：是。

## 7. 普通消息可能多次打主模型

- **问题**：情绪识别、联网检测在辅助模型未就绪时回退主模型；提醒缺少可测预筛模块；每次回复都重读 `chat_contexts.json`。
- **根因**：分类任务与主回复共用主模型；磁盘 IO 在热路径。
- **修改文件**：`reminder_rules.py`、`bot.py`
- **修改方式**：提醒关键词预筛抽出；情绪/联网检测不回退主模型；聊天上下文按文件 mtime 热读。
- **测试方法**：`tests/test_reminder_rules.py`；代码审查主路径。
- **测试结果**：预筛 PASS。普通文本默认：无提醒关键词、无联网检测、无情绪 LLM → 只打 1 次主模型。
- **是否闭环**：基本是。命中提醒关键词仍会为解析调用模型（预期行为）。

## 8. 宣称与实现不一致

- **问题**：README 写支持语音、合并转发；定时重启配置有效。
- **根因**：兼容层降级，文档未跟上。
- **修改文件**：`readme.md`、`templates/config_editor.html`、`capabilities.py`、`test_bot.py`
- **修改方式**：标明语音转文字、合并转发、定时重启当前不可用；`test_bot.py` 注明是手工脚本。
- **测试方法**：文档对照 `wxbot.py`。
- **测试结果**：已对齐。
- **是否闭环**：是。

## 9. 低风险结构拆分

- **问题**：规则散落在 `bot.py`，无法单测。
- **根因**：上帝文件。
- **修改文件**：`group_rules.py`、`url_safety.py`、`reminder_rules.py`、`app_config.py`、`llm_errors.py`
- **修改方式**：先搬迁群聊触发、SSRF、提醒预筛、配置、错误分类。**未拆** `message_listener` / `handle_wxauto_message` / `process_user_messages` / 发送主链。
- **测试方法**：对应 tests。
- **测试结果**：PASS。
- **是否闭环**：本阶段目标完成。主链拆分留给下一阶段。

## 10. 依赖版本不一致

- **问题**：`requirements.txt` 的 `wechatauto-replica` 低于 `pyproject.toml`。
- **修改文件**：`requirements.txt`、`pyproject.toml`
- **修改方式**：统一 `>=1.2.0`；py-modules 补上新模块。
- **是否闭环**：是。`openai==1.84.0` 未升级，仅记录。
