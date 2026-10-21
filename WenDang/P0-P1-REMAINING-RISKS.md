# P0-P1 剩余风险

> 只记录本阶段没有解决的问题。  
> 无限回复、Stop Bot 卡死、停止后继续发送、鼠标持续被控制：**不列为待解决问题**（基线 PASS，本轮测试未回归）。

---

1. **已泄露 API Key 需要人工轮换**  
   旧 `config.py` 里出现过真实 DeepSeek Key，现已迁到本地 `.env`。若该文件曾经提交、打包或外传，必须在服务商控制台作废并换新 Key。

2. **若运行数据已被 Git 跟踪，gitignore 不会自动取消跟踪**  
   需要对已入库的 `CoreMemory/`、`chat_contexts.json` 等执行 `git rm --cached`（本轮未动远程仓库）。

3. **配置热更新仍有限**  
   Bot 进程启动后，主模型客户端、监听列表仍需重启 Bot 才完全生效。WebUI 已停止用正则改 Python，但“保存后立即热更新全部项”未做。

4. **管理面 CSRF 未全覆盖**  
   固定了 Flask secret、HttpOnly/SameSite Cookie，并保持绑定 `127.0.0.1`。所有 POST 表单的 CSRF token 未铺开，一旦改成 `0.0.0.0` 仍不安全。

5. **`can_send_messages` / `is_sending_message` 双轨仍在**  
   提示词要求本阶段不强行删除高风险全局变量。后续拆发送主链时再收敛到 `bot_runtime`。

6. **`bot.py` / `config_editor.py` 仍然过大**  
   只抽出了配置、群规则、SSRF、提醒预筛、错误分类。消息主链未拆。

7. **openai==1.84.0 未升级**  
   仅统一了 `wechatauto-replica` 版本下限。SDK 安全升级需单独评估。

8. **角色论坛仍在主配置页**  
   未增强，也未从页面剥离。下一阶段再迁到扩展。

9. **WebUI 能力矩阵未做浏览器实机验收**  
   前端已加能力状态卡片，但本机未启动 Flask 做点击验证，避免抢占 5000 端口。
