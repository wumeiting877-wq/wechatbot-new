# P6-G0 真实运行时拓扑

> 日期：2026-09-22  
> 性质：**READ ONLY**  
> Gate 0 摘要：`P6-G0-GATE0-CURRENT-RUNTIME-TOPOLOGY.md`

---

## 微信事件 → Topic Extractor

```text
微信 SQLite 新行（local_id / sort_seq）
   ↓
wechatauto Listener.poll
   ↓ 对该 username 的 callbacks[] 逐个调用（append 语义）
wxbot._make_listen_cb → WxMessage
   platform_message_id = "{chat_wxid}:{local_id}"
   ↓
message_listener
   1. inbound_from_wx_message
   2. 若 not is_accepting_work：evaluate_inbound 后 return（不 enqueue Topic）
   3. attr 过滤（self_tickle / 非好友）
   4. evaluate_inbound → verdict
   5. try_enqueue_topic_sidepath(inbound, verdict)     # 仅此一处
   6. 若 action != REPLY：abort（Chat 不跑）
   7. 否则 handle_wxauto_message → Chat
   ↓
TopicSidepath.try_enqueue
   开关 / STOPPED / SELF / OUTBOUND / SYSTEM / DUPLICATE → skip
   unauthorized + NO_ACTION → 允许入队（旁路观察者）
   put_nowait；满则 TOPIC_QUEUE_FULL，不阻塞 listener
   ↓
Topic worker _loop
   get(timeout=0.05)；无成功路径自动 requeue
   异常只记 FAILED，不重投
   ↓
TopicEngine
   MessageRecord.id = msg_ + sha1_12(conv_id|platform_message_id)
   成功 processing 后 replay 不再调 Extractor
   ↓ SUCCESS + topic_id
   Task / Decision / Risk 各 enqueue 一次（replayed 成功仍会 fan-out）
```

---

## Stop / Start

```text
WebUI POST /stop_bot
   → STOP_REQUEST
   → BotRuntime.begin_graceful_stop
        hooks: wx.StopListening(True)   # 清 wx.listen
              TopicSidepath.shutdown    # 清 queue、停 worker 循环、级联 Task/Decision/Risk
   → state=STOPPED

未 join 的线程（仍可能活着，直到进程退出）：
   keep_alive / heartbeat / AutoMessage / InactiveUserChecker / Memory* / 日志 HTTP worker

keep_alive 在 StopListening 清空 wx.listen 后会把缺失用户再次 AddListenChat。
若 Bot 进程未退出：STOPPED 状态下 listener 可能被重新拉起。
新消息仍会被 evaluate_inbound 标 stopped，Topic 不入队。
```

```text
WebUI POST /start_bot
   仅当 bot_process is None 或 poll()!=None 时 Popen 新 bot.py
   不扫描已有孤儿 bot.py / 不核对 status.json pid 是否仍存活
```

---

## 本阶段禁止改动的边界

listener / Trigger / Self / Dedupe / Outbound / 四个 Extractor decision schema / Chat Prompt 均冻结。  
本文件只描述现状。
