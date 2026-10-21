# P2 后续计划

> 第二阶段两批均已完成，见 `P2-IMPLEMENTATION-REPORT.md`。

---

## 第二阶段已完成

1. 消息 pipeline 正式拆分（`message/`）
2. 论坛 / NPC 从 `config_editor.py` 剥离（`forum_routes.py`）
3. LLM metrics（runtime + 首页）
4. 编码工具拆到 `file_io.py`
5. `bot.py` 拆出 `llm_client` / `memory_store` / `reminders`（先搬迁，函数名与行为不变）
6. Prompt / 记忆 / 会话上下文走 `store_io` 带锁原子写
7. 操作审计（配置保存、紧急停止等）+ 首页面板 + `/api/runtime/audit`
8. Prompt / 记忆路由拆到 `webui_data.py`；HTML 拆出 CSS/JS
9. 不依赖微信的单元测试（71 项）

---

## 第三阶段再做（按业务需要）

对照优化方向总结「产品化」：

1. 首页运行概览 / 日志中心继续按使用反馈打磨（骨架已有）
2. 业务化配置体验（监听对象、群策略、模型、Prompt）
3. Prompt / 记忆分库管理的界面（底层原子写已有）
4. 如有真实多部门需求，再考虑多 Bot 实例

仍可单独开一小步、但不阻塞产品化：

- `bot.py` 剩余微信循环 / 表情包 / `keep_alive` 继续下沉（需专项回归）
- runtime 启停路由从 `config_editor.py` 再拆（高风险，单独做）

---

## 明确仍不做

- 知识库 / RAG / 多租户 / RBAC / 多机器人平台
- Redis / 消息队列 / 微服务 / Kubernetes
- 语音转写、合并转发（等 wechatauto 真正支持）
- 论坛 / NPC 增强
- 全量 Vue / asyncio 重写
