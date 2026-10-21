# P3-G2 实施报告

> 日期：2026-09-21  
> 阶段：P3-G2 Topic Side-path 接入  
> Gate 0：`P3-G2-G0-CURRENT-STATE-AUDIT.md` = PASS

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
P3-G0 = COMPLETE
P3-G1 = COMPLETE
P3-G2 = COMPLETE
```

未进入 P4。未改 Trigger / Self / Dedupe / Outbound / `evaluate_inbound`。  
结束时 `TOPIC_ENGINE_ENABLED` 模块默认仍为 **false**。真机窗口仅给 QIYE Agent 绑定了 `extractor_prompt_name=TOPIC_EXTRACTOR`，未改 `chat_prompt_name`。

---

## 1. 修改了哪些文件

| 文件 | 作用 |
|---|---|
| `message/listener.py` | 在 `evaluate_inbound` 之后、`action != REPLY` 之前插入 `try_enqueue_topic_sidepath` |
| `topic_sidepath.py` | **新增** bounded queue + 单 worker + 入队资格 + 审计 + Stop hook |
| `topic_extractor_client.py` | 无注入 `llm_call` 时走独立 `get_extractor_response`；非 JSON 供应商文案标 `EXTRACTOR_EXCEPTION` |
| `llm_client.py` | **仅新增** `get_extractor_response` 及辅助函数；纳入 `install_into` EXPORTS，避免 Bot 宿主 NameError |
| `topic_extractor_client.py` | 独立 `get_extractor_response`；可经 `runtime_control/TOPIC_EXTRACTOR_TIMEOUT_SEC` 注入超时 |
| `tests/test_topic_sidepath.py` | Gate 1 CASE-S1～S10 |
| `tests/test_topic_live_adapter.py` | Gate 2 隔离 + 真实模型离线 CASE |

未修改：

```text
message/identity.py
message/dedupe.py
message/outbound.py
message/trigger.py
message/reply_format.py
bot_runtime.py
prompts/QIYE.md
prompts/企业_1.md
```

`config.local.json` 真机仅改 QIYE Agent 的 `extractor_prompt_name`。

---

## 2. listener 插入位置

真实代码（`STEP_ADMIT`）：

```text
verdict = runtime.evaluate_inbound(...)
try_enqueue_topic_sidepath(inbound, verdict, runtime=runtime)
if verdict.get("action") != REPLY:
    return
# 原 Chat 链
```

STOPPED 快路径仍在 `STEP_ADMIT` 之前 return，Topic **不会**投递。

---

## 3. 为什么这个位置不会改变 Trigger

- 插入点在 `evaluate_inbound` **之后**
- `try_enqueue` 只读 `verdict`，不写 `action` / `reason`
- Topic 决策不映射为 `REPLY` / `NO_ACTION` / `UPDATE_ONLY`
- 未 @ 群消息仍是 Trigger `unauthorized` → Chat 0 回复；Side-path 仍可入队

---

## 4. Side-path queue / worker 架构

```text
listener  →  put_nowait（永不阻塞）
                ↓
         queue.Queue(maxsize=32)
                ↓
         1 个守护线程 TopicSidepathWorker
                ↓
         TopicEngine.process_inbound
                ↓
         Topic Store
```

- 满员：丢弃任务，审计 `TOPIC_QUEUE_FULL`
- 禁止每条消息开新线程
- 不复用 `SendQueue`（那是微信发送队列）

---

## 5. 如何判断合法入站

用 **已完成的 P0 verdict**，不重做 Self/Dedupe：

允许：`EXTERNAL + INBOUND + NEW`，且 `action == REPLY` **或** `reason == unauthorized`

拒绝：`STOPPED` / `SELF` / `OUTBOUND` / `SYSTEM` / `DUPLICATE` / 开关关闭 / Conversation 无法解析

---

## 6. 为什么未 @ 群消息可以分析但不回复

当前 `ACCEPT_ALL_GROUP_CHAT_MESSAGES=false`、`ENABLE_GROUP_AT_REPLY=true`。  
未 @ → Trigger `NO_ACTION` + `unauthorized` → listener early-return，0 条 `handle_wxauto_message`。  
同一 verdict 对 Topic 仍是合法入站，故 enqueue=1。

---

## 7. Stop Bot 如何阻止 Topic

1. STOPPED 时 listener 在 ADMIT 前 return，不调用 enqueue  
2. `classify_topic_skip` 检查 `runtime.is_accepting_work()` 与 `reason==stopped`  
3. worker 取任务后再查一次；已停止则丢弃  
4. `register_stop_hook` / `register_emergency_hook` → `shutdown()` 丢弃队列，**不等待** Extractor 20s

---

## 8. Self / Dedupe / Outbound

均以 P0 verdict 为准：`identity=SELF`、`dedupe=DUPLICATE`、outbound extra / `outbound*` reason。Side-path 不调用 `is_self_message` / `DedupeIndex` / `OutboundGuard` 自己重判。

---

## 9. Extractor 如何调用真实 LLM

新增 `llm_client.get_extractor_response`：

- 使用生产 `MODEL` / 主模型 client  
- `store_context` 强制忽略（不写会话上下文）  
- `temperature=0.2`，`max_tokens=1200`，独立 timeout 20s  
- **不**调用 `get_user_prompt` / `resolve_chat_prompt` / `get_deepseek_response`  
- 失败抛异常，不返回 Chat 用户可见错误文案，不 `send_reply`

`TopicExtractorClient` 无注入时走该入口。测试 Gate 1 仍注入 Heuristic。

---

## 10. Topic 与 Chat 如何物理隔离

| | Topic | Chat |
|---|---|---|
| Prompt | `prompts/extractors/TOPIC_EXTRACTOR.md` | `prompts/*.md` |
| 调用 | `get_extractor_response` | `get_deepseek_response` |
| 上下文 | 不写 `chat_contexts` | 可写 |
| 回复 | 无 `send_reply` / `SendMsg` | 原链 |
| 失败 | Store `FAILED` + audit | 原 Chat 错误语义 |

全局搜索：Topic 模块没有 `send_reply(` / `wx.SendMsg(`。

---

## 11. `TOPIC_ENGINE_ENABLED` 如何工作

```text
topic_engine.py 模块常量 = False   # 默认，测试仍断言 false
环境变量 TOPIC_ENGINE_ENABLED=true 可开启
runtime_control/TOPIC_ENGINE_ENABLED 文件若存在则覆盖环境变量（真机 R10 运行中关闭）
false → listener 完全不投递，不写 Topic Store
```

未写入 `config.local.json` schema。

---

## 12. 审计事件

`TOPIC_SIDE_PATH_ENQUEUED` / `TOPIC_SIDE_PATH_SKIPPED` / `TOPIC_QUEUE_FULL` / `TOPIC_PROCESS_SUCCESS` / `TOPIC_PROCESS_FAILED` / `CONVERSATION_NOT_RESOLVED`

preview ≤ 80 字。不记录 API Key。
