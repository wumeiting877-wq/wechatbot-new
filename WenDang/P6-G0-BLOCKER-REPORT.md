# P6-G0 BLOCKER Report

> 日期：2026-09-22  
> N2 Duplicate Topic Extractor：**已解释，不是本文件的代码 BUG。**  
> P6-G0 仍 **BLOCKED**，因为无法证明「Restart 不产生双 listener / Stop 彻底清理线程」。

未改源码。未修。

---

## B1  Stop Bot 不停止 keep_alive（STOP 条件命中）

`wx.StopListening(True)` 会：

- 停 `db.Listener`
- `wx.listen.clear()`

`bot.py` `keep_alive` 是 `while True`，**不看** `runtime.is_accepting_work()`。  
Stop 后 5 秒内会把「丢失」的用户再次 `AddListenChat`。

`wechatauto.db.Listener.add_listener` 对同一 username **append** callback。  
若 listener 线程仍活着且 `wx.listen` 被清过再补，可能叠 callback。  
P0 对同一 `platform_message_id` 会 DUPLICATE，Topic 可挡；**不能**当作 Stop 已干净。

P5-G4 Gate 0 已见：state=STOPPED 后 `bot.py` 进程树仍在。

---

## B2  start_bot 不扫孤儿 Bot

`POST /start_bot` 只看 Flask 持有的 `bot_process.poll()`。  
不扫描项目目录下其它 `bot.py`，不把 `status.json.pid` 当存活 Bot 身份。

Windows 上 wrapper PID ≠ `status.json` 的 Bot PID。杀 wrapper 可能留下 worker。再点 Start → **两个 Listener 打同一微信库**。  
那才会让同一 `local_id` 在 **两个 DedupeIndex** 里都是 NEW。  
N2 真机样本 **不是** 这条路径；这条路径仍是生产风险。

---

## B3  观测假阳性（非功能 BLOCKER，但是 RCA 干扰项）

`llm_client.get_extractor_response` 成功一律：

```text
note_llm_call("topic_extractor", "extractor", ...)
log "Topic Extractor LLM ok"
```

Task / Decision / Risk 共用此入口。一句 inbound 在 events 里会出现多条 `extractor/topic_extractor`。  
禁止在未改标签前用该日志证明「Topic Extractor 调用了两次」。

---

## 明确不是 BLOCKER 的

| 项 | 说明 |
|---|---|
| N2 同文两次 Topic | 两个 local_id，P0 按设计不去重。见 RCA |
| 四个 Engine 开关 | 默认 false，本轮未写长期 ENABLE |
| DJ-R8 / RK-R9 | 继续 Deferred |
| Store 脏写 | N2 未产生重复 Topic/Task/Decision/Risk 实体 |
| 仓库两个 bot.py | **无**，仅 `wechatbot-new/bot.py` |

---

## 判定

```text
P6-G0 = BLOCKED
允许进入 P6-G1 = NO
```

修复 Gate 必须先拿到指令。候选顺序：

1. Stop 后禁止 keep_alive 再 AddListenChat（或随进程退出）
2. start_bot 以 `status.json.pid` + cmdline 扫孤儿，禁止第二 Listener
3. Extractor 日志 purpose 分引擎

全部不得改 decision schema，不得上正文时间窗去重冒充 N2 修复。
