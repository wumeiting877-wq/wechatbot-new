# WeChatBot New｜企业智能助手管理平台

> Windows 本机微信智能助手：通过网页配置监听会话与 AI 角色，在微信中自动回复；并提供主题、任务、风险、决策等消息协同能力的旁路处理、查询与运维排障能力。

## 项目定位

本项目运行在一台已登录微信的 Windows 电脑上。管理员在本机 WebUI 中配置要监听的联系人或群聊、绑定的 Prompt 与模型后，机器人即可接收微信消息、经安全网关判定后调用大语言模型，并把文本回复发送回微信。

项目同时包含企业消息协同的演进能力：可将入站消息以**旁路方式**抽取为主题、任务、风险和决策，并保留处理记录、审计信息、失败诊断与人工重试入口。这些引擎不改变聊天回复判定，也不会自行向微信发送催办消息。

当前它是一个可本机部署、可配置和可运维的微信助手，**不是**多租户 SaaS，也尚未提供完善的企业协同看板、RBAC 或完整工作流闭环。

## 功能概览

| 能力 | 说明 | 状态 |
| --- | --- | --- |
| 微信自动回复 | 私聊监听、群聊 @ / 关键词触发、消息合并、上下文、纯文本回复 | 可用，需真实微信环境验证 |
| 会话与角色配置 | Conversation、AgentConfig、Prompt 绑定；兼容旧 `LISTEN_LIST` 配置 | 可用 |
| 本机 WebUI | 配置管理、Prompt 管理、Bot 启停、运行概览、日志与审计 | 可用 |
| 消息运行时保护 | 停止/紧急停止、自消息与出站过滤、去重、限流、审计 | 可用 |
| 记忆与提醒 | 对话记忆、核心记忆、自然语言提醒、文本指令 | 可选功能 |
| 图片/表情、联网、链接抓取 | 按开关和独立 API Key 启用；链接抓取带 SSRF 防护 | 可选功能 |
| 主题/任务/风险/决策抽取 | JSON Store、旁路引擎、处理证据、重试与诊断 | 已实现，默认关闭 |
| 协同查询与业务动作 | 意图识别、查询回复投递、任务生命周期/指令/授权等模块 | 已实现，需按场景配置和验证 |
| 运维页面 | `/operations` 只读查看处理状态、问题消息和诊断；支持受控重试操作 | 可用 |
| 企业看板与权限体系 | Topic/Task 专用业务看板、多角色 RBAC、跨群知识库 | 未完成 |

## 核心流程

```text
本机微信消息
  → 消息网关（停止 / 出站 / 自消息 / 系统消息 / 去重 / 触发规则）
  ├─→ 聊天主链：会话 → Agent / Prompt → LLM → 出站保护 → 微信文本回复
  └─→ 协同旁路：主题 → 任务 / 风险 / 决策 → JSON Store、审计、诊断与运维视图
```

旁路引擎与聊天主链相互隔离：引擎失败不应阻断自动回复；聊天是否回复也不由引擎决定。

## 运行要求

- Windows 10/11
- Python 3.9 或更高版本
- 已登录的桌面微信（微信收发基于 `wechatauto-replica[guia]`）
- 至少一个兼容 OpenAI SDK 的大模型接口与 API Key
- 建议使用虚拟环境

主要依赖见 [requirements.txt](requirements.txt) 与 [pyproject.toml](pyproject.toml)。当前包版本为 `2.2.5`。

## 快速开始

以下命令均在项目根目录执行。

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.example.json config.local.json
Copy-Item .env.example .env
```

在 `.env` 中至少填写主模型密钥：

```dotenv
DEEPSEEK_API_KEY=你的密钥
```

随后启动 WebUI：

```powershell
python config_editor.py
```

浏览器访问 `http://127.0.0.1:5000/`。首次使用建议在页面中完成以下配置：

1. 填写主模型地址与模型名；默认示例为 DeepSeek 兼容接口。
2. 在“监听对象”中添加要监听的微信联系人或群聊，并绑定 Prompt。
3. 在“Prompt 管理”中检查或编辑 `prompts/` 下的人设文件。
4. 确认桌面微信已登录后，点击“Start Bot”。
5. 先用测试联系人或测试群验证收发、停止和紧急停止流程。

项目在 `pyproject.toml` 中定义了以下命令行入口：

```powershell
wechatbot-webui
wechatbot
```

当前企业协同模块仍以源码目录运行为主要验证方式；如使用安装包，请先在目标环境完成一次启动验证。`Run.exe` 为遗留入口；开发、排障和企业场景建议使用 `config_editor.py` 或 `wechatbot-webui`。

## 配置与密钥

| 文件 | 用途 | 是否应提交 |
| --- | --- | --- |
| `config.example.json` | 可公开的配置样例 | 是 |
| `config.local.json` | 本机运行配置；首次启动会按默认值补齐 | 否 |
| `.env.example` | 密钥模板 | 是 |
| `.env` | API Key、WebUI 密码哈希、Flask 密钥 | 否 |

不要将真实 API Key 写进 Prompt、源码或 `config.example.json`。`.env`、`config.local.json`、运行日志和 `data/` 已在 `.gitignore` 中排除。

常用配置项：

- `LISTEN_LIST`：旧版监听列表；启动时可迁移/投影至 `CONVERSATIONS`。
- `CONVERSATIONS`、`AGENT_CONFIGS`：会话与角色绑定的结构化配置。
- `DEEPSEEK_BASE_URL`、`MODEL`、`MAX_TOKEN`、`TEMPERATURE`：聊天主模型。
- `ENABLE_GROUP_AT_REPLY`、`ENABLE_GROUP_KEYWORD_REPLY`：群聊触发策略。
- `ENABLE_MEMORY`、`ENABLE_REMINDERS`、`ENABLE_ONLINE_API`：可选能力开关。
- `ENABLE_LOGIN_PASSWORD`：为本机 WebUI 启用密码保护；服务仍固定监听 `127.0.0.1`。

配置变更后，建议先停止 Bot，再保存并重新启动，使监听与运行时配置完整生效。

## 协同旁路引擎

主题、任务、风险、决策引擎采用本地 JSON/JSONL Store，而非 SQL 数据库。它们的模块开关默认均为 `false`：

- `TOPIC_ENGINE_ENABLED`
- `TASK_ENGINE_ENABLED`
- `RISK_ENGINE_ENABLED`
- `DECISION_ENGINE_ENABLED`

开关可以由模块默认值、环境变量或 `runtime_control/` 下的同名控制文件解析。启用前请先在测试会话验证，因为引擎会把抽取结果写入 `data/`，并可能消耗模型额度。

当前可通过以下路径检查处理情况：

- `http://127.0.0.1:5000/operations`：运维概览、需关注的消息及调查入口。
- `/api/operations/status`：运行时与引擎状态。
- `/api/operations/messages`、`/api/operations/issues`：消息处理状态与待处理问题。
- `/api/operations/messages/<message_id>/diagnostics`：单消息的诊断详情。

这些能力主要用于开发、验证与运维；它们不等同于面向业务用户的任务看板。

## 项目结构

```text
.
├─ config_editor.py          # Flask WebUI、配置与 Bot 子进程管理
├─ bot.py / bot_runtime.py   # 微信 Bot 主进程、运行状态和安全网关
├─ wxbot.py                  # 微信自动化适配层
├─ message/                  # 入站处理、身份、去重、触发、出站保护
├─ prompts/                  # 聊天 Prompt 和抽取器 Prompt
├─ conversation_store.py     # Conversation 与旧监听列表迁移/投影
├─ agent_store.py            # AgentConfig 与 Prompt 绑定
├─ topic_*.py                # 主题抽取、存储和旁路调度
├─ task_*.py                 # 任务抽取、生命周期、指令与目标解析
├─ risk_*.py / decision_*.py # 风险、决策抽取与旁路调度
├─ query_*.py                # 协同查询意图、路由、格式化与投递
├─ business_action_*.py      # 业务动作、授权、会话与审计
├─ operations_*.py           # 运维读取模型、诊断、路由与受控操作
├─ templates/ static/        # Flask 页面与前端资源
├─ tests/                    # unittest 离线测试
└─ WenDang/                  # 阶段报告、变更记录与设计材料
```

运行时产生的主题、任务、风险、决策、审计和状态文件位于 `data/`、`runtime_control/` 等目录，不应手动批量删除。

## 测试

项目使用 Python `unittest`。在不连接微信、也不调用真实模型的情况下，可运行离线测试：

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

也可以针对单模块执行，例如：

```powershell
python -m unittest tests.test_p7g0_operations_read_model
python -m unittest tests.test_pipeline
```

离线测试不能证明真实微信 GUI 自动化、外部模型额度/可用性或实际群聊发送行为；上线前仍应使用隔离账号进行手工验证。

## 已知边界与安全提示

- 机器人真实发送微信消息，错误配置可能造成误回复或重复回复。先使用测试号，必要时点击“紧急停止”。
- 微信里已发起的 GUI 发送与进行中的模型 HTTP 请求无法完全中途取消。
- 语音转文字、合并转发内容还原依赖底层微信兼容层，当前不应视为稳定能力。
- `ENABLE_SCHEDULED_RESTART` 配置项当前没有有效运行链路，不应依赖它做可用性保障。
- WebUI 默认仅监听本机回环地址。若修改部署方式或暴露端口，请自行补充网络隔离、认证和 CSRF 防护。
- 系统没有多租户隔离、完整 RBAC、企业通讯录或正式任务/主题看板；不要将其直接作为生产级企业协同平台使用。

## 许可证与致谢

本项目基于 [KouriChat](https://github.com/KouriChat/KouriChat) 改造，并使用 `wechatauto-replica` 适配微信 4.x。代码以 [GNU GPL-3.0-or-later](LICENSE) 发布。

依赖与许可证合规信息见 [DEPENDENCIES.txt](DEPENDENCIES.txt)。

