# P6-G0 Closure Report

> 日期：2026-09-22  
> 指令：P6-G0-FIX-LIFECYCLE  
> 未进入 P6-G1。

```text
P0 = CLOSED
P1 = CLOSED
P2 = CLOSED
P3 Topic Engine = COMPLETE
P4 Task Engine  = COMPLETE
P5-G0 = COMPLETE
P5-G1 = COMPLETE
P5-G2 = COMPLETE
P5-G3 = COMPLETE
P5-G4 = COMPLETE

P6-G0 = COMPLETE
P6-G0 BLOCKER = CLOSED
```

---

## BLOCKER 关闭

| ID | 原状 | 本轮 |
|---|---|---|
| B1 keep_alive 不响应 Stop | STOP 后可能再 AddListenChat，KeepRunning 不退出 | **CLOSED**。STOPPING 起 AddListenChat=0；STOPPED 后线程退出；真机 Stop 后 bot.py 消失且 7s 内不重生 |
| B2 start_bot 不扫孤儿 | 只看 Flask `bot_process.poll()` | **CLOSED**。preflight = status.json pid + cmdline 身份。真机重复 Start 未第二 Popen |
| B3 OBS 假阳性 | 成功日志一律 `topic_extractor` | **CLOSED**（非功能 BLOCKER）。四引擎 purpose 已区分 |

N2 双 Topic：**不是 BUG**。RCA 保持。本轮加自动测试防止误修。

---

## Message 不变式

仍由 P0 + Store + Side-path 保证（未改语义）：

```text
一个 platform_message_id
  → 最多一个 MessageRecord
  → 最多一次 Topic enqueue
  → 最多一次 Topic Extractor
  → 最多一次 Topic Store SUCCESS
  → 最多一次 Task / Decision / Risk fan-out
```

同正文、不同 `platform_message_id` → 两条消息（N2 锁定测试 PASS）。

---

## Stop / Restart / 实例数

| 门槛 | 证明 |
|---|---|
| STOPPING 后 keep_alive 不再 AddListenChat | LIFE-02/03 + 真机 L4 |
| STOPPED 后 listener 不重生 | 真机 L4，bot.py=NONE |
| STOPPED 后 Bot process 退出 | 真机 L3：wrapper+worker 均死；不只 poll() |
| 已有旧 Bot → 拒绝第二次启动 | LIFE-05 + 真机 L7 未第二 Popen |
| 旧 Bot 不存在 → 正常启动 | LIFE-06 + 真机 L1/L6 |
| active Bot ≤ 1 | 真机一棵树（wrapper+status pid） |
| active DB Listener ≤ 1 | 单 worker 进程；Stop 后不再 `_listener_start` |
| callback / 会话 = 1 | 启动路径仍每会话一次 `AddListenChat`；Stop 后不叠加 |

---

## 回归 / 开关

```text
unittest discover = 530 OK（含原 334 超集）
新增 LIFE / N2 / OBS = PASS
TOPIC_ENGINE_ENABLED    = false
TASK_ENGINE_ENABLED     = false
DECISION_ENGINE_ENABLED = false
RISK_ENGINE_ENABLED     = false
```

---

## 真机缺口（不重新打开 BLOCKER）

- LIVE-L2 / LIVE-L5 未发微信测试句。Stop 后进程已不存在，无法处理 inbound。
- 运行中 WebUI 15396 尚未加载 409 preflight 源码。重启 WebUI 后 `/start_bot` 对活 Bot 返回 409。当前 Case B（句柄仍活）已在真机挡住第二 Popen。

---

## 下一步

停止于 P6-G0。等待指令再进入 P6-G1。  
优先已提交：

```text
WenDang/P6-G0-FIX-LIFECYCLE-IMPLEMENTATION.md
WenDang/P6-G0-FIX-LIFECYCLE-TEST-REPORT.md
WenDang/P6-G0-FIX-LIFECYCLE-LIVE-REPORT.md
WenDang/P6-G0-CLOSURE-REPORT.md
```
