# P2 第二阶段实施报告

> 日期：2026-09-19  
> 对照：`wechatbot-new-项目优化方向总结.md` 第二阶段 + `P0-P1-NEXT-PHASE-PLAN.md`  
> 原则：先搬迁再清理；不改 Stop Bot / 无限回复 / GUI 中断。

---

## 第一批（已完成）

### 1. 消息主链拆到 `message/` 包

- `message/pipeline.py`：可观测 pipeline + 纯决策函数
- `message/listener.py` / `handler.py` / `processor.py`
- `message/bind.py`：绑定 `bot.py` 宿主（兼容 `python bot.py` 的 `__main__`）

### 2. 消息处理可观测 + LLM metrics

每条消息记录步骤；`plan_llm_calls_for_text` 锁定普通文本默认 1 次主模型。  
首页展示今日 LLM 次数 / 主模型次数 / 失败次数 / 最近调用。

### 3. 论坛从 `config_editor.py` 剥离

`forum_routes.py` Flask Blueprint。

### 4. 编码工具搬出

`file_io.py`。

---

## 第二批（后半段，已完成）

### 5. `bot.py` 继续拆出 llm / memory / reminder

| 模块 | 职责 | 安装方式 |
|---|---|---|
| `llm_client.py` | 主模型 / 辅助模型 / 识图 / 联网 | `install_llm(bot)` |
| `memory_store.py` | 聊天上下文 / 核心记忆 / 临时记忆 | `install_memory(bot)` |
| `reminders.py` | 提醒解析、持久化、到期检查 | `install_reminders(bot)` |

函数体仍使用原来的全局名（`logger`、`chat_contexts` 等），由 `module_install.rebind` 把 `__globals__` 指到 `bot` 宿主。行为与未拆分时一致。  
`keep_alive` / `main()` / Stop Bot 仍在 `bot.py`。

当前 `bot.py` 约 1937 行、38 个 `def`（启动、微信循环、表情包等保留在宿主）。

### 6. Prompt / 记忆带锁原子写

`store_io.py`：`atomic_write_text` / `atomic_write_json` / `read_json` / `update_json`（FileLock + 临时文件 replace）。  
WebUI 保存 Prompt、核心记忆、会话上下文，以及 bot 侧 `save_chat_contexts` / `save_core_memory_to_json` / `save_recurring_reminders` 走同一套写入。

### 7. 操作审计

`audit.py`：写入 `runtime_control/audit.jsonl`。  
记录启动/停止、紧急停止、保存配置、Prompt 增删改、记忆/上下文保存。详情走 `mask_secrets`。  
接口：`/api/runtime/audit`；首页「最近操作审计」面板。

### 8. WebUI 路由拆分（低风险，不动 runtime）

`webui_data.py`：Prompt / 会话上下文 / 核心记忆路由。  
`config_editor.py` 末尾 `register_data_routes`。  
**未搬** `/start_bot` `/stop_bot` `/emergency_stop` `/submit_config`。

### 9. 单页 HTML 拆静态资源

- `static/css/config_editor.css`
- `static/js/config_editor.js`
- `static/css/config_editor_extra.css`
- `static/js/config_editor_logs.js`

`templates/config_editor.html` 约 1062 行，用 `url_for('static', ...)` 引用。未引入 Vue。

### 10. 测试

新增：`test_store_io`、`test_audit`、`test_memory_store`、`test_reminders_parse`、`test_llm_client`、`test_webui_data`、`test_module_install`。  
不连接真实微信。合计 **71 tests，OK**。

---

## 验收对照

| 标准 | 状态 |
|---|---|
| 改群聊规则不必打开 4000 行文件 | 已在第一阶段抽出 `group_rules.py`，pipeline 复用 |
| 单条普通文本默认只打 1 次主模型 | `plan_llm_calls_for_text` 单测锁定 |
| 核心运行时逻辑有测试 | admit / 群规则 / pipeline / LLM / 记忆合并 / 提醒 JSON / 审计 / 原子写 |
| Stop Bot / 无限回复 / GUI 中断 | 未改；runtime 路由仍在 `config_editor.py` |

---

## 明确未做（留给第三阶段）

- 知识库 / RAG / 多租户 / 多 Bot
- 全量 Vue 或把 HTML 再拆成多页模板
- 把 runtime 启停从 `config_editor.py` 再拆出去
- `bot.py` 宿主里剩余的微信循环 / 表情包 / keep_alive 继续下沉（需单独回归）
