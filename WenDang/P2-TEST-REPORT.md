# P2 测试报告

> 日期：2026-09-19  
> 环境：Windows，项目目录 `wechatbot-new`  
> 命令：`python -m compileall -q .` 后 `python -m unittest discover -s tests -v`

未运行 `test_bot.py`（会连接真实微信并发送消息）。

---

## 汇总

**合计：71 tests，OK**（第一批 48 + 后半段 23）

compileall 覆盖拆出的 `llm_client.py` / `memory_store.py` / `reminders.py` / `webui_data.py` / `store_io.py` / `audit.py` / `module_install.py` 以及瘦身后的 `bot.py`、`config_editor.py`。

### 后半段新增覆盖

- 带锁原子写 JSON/文本，缺失文件返回默认值
- 审计写入/读取紧急停止；详情脱敏 API Key
- `merge_context` 合并连续同 role；`sanitize_user_id_for_filename` 保留中文、拦截路径字符
- `extract_last_json_or_null` 处理 null / markdown / 最后一个 JSON 对象
- `strip_before_thought_tags`、LLM purpose、usage tokens
- Prompt/记忆路由已从 `config_editor.py` 的 `@app.route` 剥离；启停与紧急停止仍在主文件
- 静态 CSS/JS 文件存在，模板引用 `url_for('static', ...)`，首页有操作审计面板
- `module_install.rebind` 使函数读宿主全局名

### 仍由第一批覆盖

- 普通文本默认只规划 1 次主模型
- 群聊 @ 触发不必打开 bot.py
- 自身拍一拍 / 非监听对象会被 pipeline 拒绝
- LLM 调用次数、失败、token 进入 snapshot
- 论坛 Blueprint 路由已剥离

---

## 未做的手工验证

未对着真实浏览器点击回归。改用 Flask `test_client`：首页 `/`、`/static/css/config_editor.css`、`/static/js/config_editor.js` 均为 200，HTML 含审计面板与 CSS 引用；启停/紧急停止/Prompt/记忆/审计路由均已注册。Stop Bot / 紧急停止未改代码路径。
