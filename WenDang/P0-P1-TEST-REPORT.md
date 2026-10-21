# P0-P1 测试报告

> 日期：2026-09-19  
> 环境：Windows，项目目录 `wechatbot-new`  
> 命令：`python -m unittest discover -s tests -v`

未运行 `test_bot.py`（会连接真实微信并发送消息）。

---

## 汇总

| 测试名称 | 类型 | 执行命令 | 结果 | 证据 |
|---|---|---|---|---|
| CapabilityTests | 单元 | `python -m unittest tests.test_capabilities` | PASS | 5 tests ok |
| ConfigValidateTests | 单元 | `python -m unittest tests.test_config_validate` | PASS | 6 tests ok；密钥不写入 JSON |
| GroupRulesTests | 单元 | `python -m unittest tests.test_group_rules` | PASS | @ / 关键词 / 未触发 / 频率 |
| LlmErrorTests | 单元 | `python -m unittest tests.test_llm_errors` | PASS | AUTH / 429 / timeout / 余额 / 非余额 |
| ReminderRulesTests | 单元 | `python -m unittest tests.test_reminder_rules` | PASS | 普通聊天不进提醒；明确提醒进入 |
| AdmitMessageTests | 单元 | `python -m unittest tests.test_runtime_admit` | PASS | 正常 / 重复 / 自身 / 停止 |
| SsrfTests | 单元 | `python -m unittest tests.test_ssrf` | PASS | 127.0.0.1 / localhost / 内网 / 公网 |
| compile | 语法 | `python -m compileall` 项目模块 | PASS | 无语法错误 |

**合计：33 tests，OK，0.281s**

---

## 已闭环运行时能力（本轮只锁测试，不重构）

| 测试名称 | 类型 | 结果 | 证据 |
|---|---|---|---|
| 无限回复 / 去重 | 单元 admit | PASS | 重复 message_id 拦截 |
| 自回复防护 | 单元 admit | PASS | attr=self / 自身昵称拦截 |
| Stop 后丢弃新消息 | 单元 admit | PASS | STOPPED 状态拒绝准入 |

---

## 未做的测试

| 项 | 原因 |
|---|---|
| 真实微信收发 | 提示词禁止自动化控制真实微信 |
| WebUI 浏览器端到端 | 会占用 5000 端口并可能结束已有进程 |
| Flask 登录哈希手工点选 | 需本地启动 WebUI 后人工验证 |
