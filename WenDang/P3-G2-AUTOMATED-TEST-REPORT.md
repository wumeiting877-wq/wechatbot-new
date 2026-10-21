# P3-G2 自动测试报告

> 日期：2026-09-21  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`

---

## Gate 1 Side-path（Heuristic / Mock）

命令：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_sidepath
```

结果：**12 tests, OK**

| CASE | 结果 | 说明 |
|---|---|---|
| S1 未 @ 群消息 | PASS | enqueue=1，Chat reply=0，Topic Store 有 Topic |
| S2 @ Agent | PASS | enqueue=1，Chat reply=1，无第二条回复 |
| S3 self | PASS | enqueue=0，reply=0 |
| S4 outbound | PASS | enqueue=0 |
| S5 duplicate | PASS | 第二次 enqueue=0 |
| S6 system/recall | PASS | enqueue=0 |
| S7 STOPPED | PASS | enqueue=0，reply=0 |
| S8 worker exception | PASS | Chat 仍 1 次回复 |
| S9 Queue Full | PASS | listener < 0.5s，审计 `TOPIC_QUEUE_FULL` |
| S10 ENABLED=false | PASS | enqueue=0，@ 仍按原 Chat 回复 1 次 |
| 插入位置 | PASS | `evaluate_inbound` 之后、`action != REPLY` 之前 |
| verdict 不改写 | PASS | unauthorized 保持 NO_ACTION |

---

## Gate 2 隔离（不打生产模型）

命令：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_live_adapter.ExtractorIsolationTests
```

结果：**7 tests, OK**

| 项 | 结果 |
|---|---|
| `get_extractor_response` 不走 Chat Prompt / 会话上下文 | PASS |
| Chat `get_deepseek_response` 源码行为未改 | PASS |
| Topic 模块无 `send_reply` / `wx.SendMsg` | PASS |
| markdown JSON / 空输出 / HTTP error / timeout | PASS |
| Extractor timeout → Topic FAILED、无脏 Topic | PASS |
| content 为空时仅在 reasoning 含 JSON 才回退 | PASS |
| Extractor 辅助函数纳入 `install_into` EXPORTS | PASS |

---

## G1 离线 Topic 回归

命令：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_store tests.test_extractor_prompt tests.test_topic_engine_offline
```

结果：**39 tests, OK**（与 G1 基线一致，未删测、未 skip）
