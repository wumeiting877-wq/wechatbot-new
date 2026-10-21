# P3-G2 Gate 0：当前真实源码审计

> 日期：2026-09-21  
> 性质：**READ ONLY**。本文件写完前未修改业务代码。  
> 依据：`P3-G1-IMPLEMENTATION-REPORT.md`、`P3-G1-TEST-REPORT.md`、`P3-G1-REGRESSION-REPORT.md`、`P3-G2-READINESS.md`、`P3-G1-DEFERRED-ISSUES.md` 与真实源码。

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
P3-G0 = COMPLETE
P3-G1 = COMPLETE
P3-G2 = NOT STARTED
```

---

## 冻结基线核对

| 项 | 文档 | 本轮核对 |
|---|---|---|
| P0 | CLOSED（`P0-CLOSURE-REPORT.md`） | 保持。禁止改 identity / dedupe / outbound / trigger / reply_format / `evaluate_inbound` |
| P1 / P2 | CLOSED（`P1-P2-CLOSURE-REPORT.md`） | 保持。禁止改 Chat Prompt 正文 |
| P3-G1 | COMPLETE，39 Topic tests OK | 源码存在：`topic_store.py` / `topic_engine.py` / `topic_extractor_client.py` / `prompts/extractors/TOPIC_EXTRACTOR.md` |
| G1 回归 | P0 59 / P1-P2 103 | 文档记录；本轮 Gate 1 后再实测 |
| G2 就绪 | `P3-G2-READINESS.md` = YES | 与源码一致：Engine 离线可用，listener **尚未**调用 Topic |
| 延期 | listener 旁路、真实 LLM、真机 | 正是本轮范围；P4 / UI / 自动 RESOLVED 仍禁止 |

G1 文档与真实 listener **没有严重不一致**。不构成 BLOCKER。

```text
G2 Gate 0 = PASS
允许进入 Gate 1（只接 Side-path，不接真实 LLM）
```

---

## 1. `message/listener.py` 当前真实 early-return 在哪里？

`message_listener` 的判定顺序（真实变量名）：

1. **STOPPED 快路径**（约 L42–46）  
   `if not runtime.is_accepting_work()` → 仍调用 `runtime.evaluate_inbound(inbound)` 写 P0 审计 → **直接 `return`**。  
   不进入 `STEP_ADMIT`。Topic Side-path **不得**插在这里，否则 Stop 后仍可能投递。

2. **attr 过滤**（约 L48–59）  
   `self_tickle` / 非好友 `drop`：在 `evaluate_inbound` **之前** return。这些不是合法入站，Topic 不应处理。

3. **P0 主判定**（约 L66–83，`STEP_ADMIT`）  

```text
verdict = runtime.evaluate_inbound(inbound, listen_users=..., is_group=..., ...)
if verdict.get("action") != REPLY:
    ... return
```

这是 G1 文档描述的语义等价位置。  
**Topic Side-path 唯一允许插入点：`evaluate_inbound(...)` 完成之后、`action != REPLY` early-return 之前。**

4. **空内容**（约 L113–119）  
   已判定 `REPLY` 之后。Topic 不依赖这条路径。

真实代码用 `verdict.get("action")`（dict），不是 `verdict.action`。不重构 listener。

---

## 2. `evaluate_inbound` 返回对象实际包含哪些字段？

`BotRuntime.evaluate_inbound` → `decide_trigger` → `_verdict()`，返回 **dict**：

| 字段 | 含义 |
|---|---|
| `action` | `REPLY` / `NO_ACTION`（`UPDATE_ONLY` 存在但未接线，本轮禁止使用） |
| `reason` | `stopped` / outbound 原因 / self 原因 / `bot_or_system` / `duplicate_*` / `unauthorized` / 监听命中原因 |
| `direction` | `INBOUND` / `OUTBOUND` |
| `identity` | `EXTERNAL` / `SELF` |
| `dedupe` | `NEW` / `DUPLICATE` |
| `message` | `InboundMessage.as_dict()` |
| `extra` | outbound/self/dedupe 细节，或 `listen_reason` / `content_for_handler` |

内部顺序（禁止改）：`stopped → outbound → self → system → duplicate → trigger`。

---

## 3. 如何判断 self / outbound / duplicate / system / stopped？

全部以 **已完成的 verdict** 为准，不重写 P0：

| 拦截 | 判断 |
|---|---|
| Stopped | `reason == "stopped"`，或 `runtime.is_accepting_work() == False` |
| Self | `identity == "SELF"`，或 `reason` 为 `self` / `sender_wxid_equals_bot_wxid` 等 |
| Outbound | `direction == "OUTBOUND"`，或 `reason` 含 `outbound` |
| Duplicate | `dedupe == "DUPLICATE"`，或 `reason` 含 `duplicate` |
| System / recall | `reason == "bot_or_system"`（`raw_type in {system, recall}`） |

**未 @ 群消息**：`action == NO_ACTION` 且 `reason == "unauthorized"`，同时 `identity == EXTERNAL`、`direction == INBOUND`、`dedupe == NEW`。  
这只表示 Trigger 不回复，**允许**进入 Topic。

当前配置与文档一致：

```text
ACCEPT_ALL_GROUP_CHAT_MESSAGES = false
ENABLE_GROUP_AT_REPLY = true
```

---

## 4. 当前 worker / queue 是否有可复用实现？

| 现成队列 | 用途 | 能否给 Topic 用 |
|---|---|---|
| `BotRuntime.SendQueue` | 微信 **发送** worker | **否**。Stop 会清空；与旁路观察者职责相反 |
| `bot.py` `AsyncHTTPHandler.log_queue` | 远程日志 | **否** |
| `user_queues` | Chat 合并回复 | **否**。会进入回复链 |

**结论**：没有可复用的 Topic worker。允许新增很小的 `topic_sidepath.py`：bounded queue + **concurrency=1** + `put_nowait` 满则丢弃。禁止复用 SendQueue。

---

## 5. TopicEngine 的真实调用入口是什么？

```text
TopicEngine.process_inbound(inbound, conversations=...)
  → resolve_topic_conversation（chat_wxid / display_name，禁止把 InboundMessage.conversation_id 当 conv_*）
  → project_inbound_to_message_record
  → process_record

TopicEngine.process_record(record, conversation)
```

`enabled` 默认跟随模块常量 `TOPIC_ENGINE_ENABLED`。Side-path 在已通过开关判定后，应对 **本次 Engine 实例** 传 `enabled=True`，否则入队后仍会被标 `DISABLED`。

---

## 6. `topic_extractor_client.py` 当前是否已经能调用真实 LLM？

**不能直接调用。**

- `TopicExtractorClient.extract()`：无 `llm_call` 时抛 `LLM_NOT_CONFIGURED`
- `HeuristicTopicExtractor`：G1 离线确定性实现
- 签名需要：`llm_call(messages, temperature, max_tokens, timeout, store_context=False, model=...)`
- 现有 `get_deepseek_response` **不能**当 Extractor 用：会走 Chat Prompt / `chat_contexts` / Chat temperature / Chat 用户错误文案，且 Stop 时返回 `None` 可能被当成回复语义

Gate 1 使用 Heuristic / mock。  
Gate 2 才允许对 `llm_client.py` **新增**独立 Extractor 入口，禁止改现有 Chat 函数。

---

## 7. `TOPIC_ENGINE_ENABLED` 当前在哪里定义？

```text
topic_engine.py
TOPIC_ENGINE_ENABLED = False
```

- 不在 `config.local.json` schema 中
- 无环境变量读取
- G1 测试断言该常量默认 `false`

本轮：**保持模块默认 false**。Side-path 用环境变量 `TOPIC_ENGINE_ENABLED=true` 覆盖开启，不改 `config.local.json` schema，不把 Topic 数据写入该文件。

`false` 时 listener 完全不投递，行为近似 P3 不存在。

---

## 8. AgentConfig 如何安全绑定 extractor？

生产现状（`config.local.json`，不记录 Key）：

| Agent | `chat_prompt_name` | `extractor_prompt_name` |
|---|---|---|
| `agt_679873182096`（ceshi / 哈） | `企业_1` | `null` |
| `agt_38b43979a544`（QIYE 群） | `QIYE` | `null` |

已有 `resolve_extractor_prompt` → `prompts/extractors/{name}.md`。  
Engine 构造参数默认 `extractor_prompt_name=TOPIC_EXTRACTOR`，**尚未**按 Conversation→Agent 读取字段。

安全策略：

- **禁止**改 `chat_prompt_name`
- **禁止**把 `TOPIC_EXTRACTOR` 配进 Chat Prompt
- Gate 1/2 离线不改生产 `AGENT_CONFIGS`
- 真机前仅给**测试会话**对应 Agent 绑定 `extractor_prompt_name = TOPIC_EXTRACTOR`
- 代码侧：Agent 字段有值则用；`null` 时 fallback `TOPIC_EXTRACTOR`（仅当 Side-path 已开启）

测试群候选（已在监听名单，不自动扩名单）：

- 群「哈」`conv_2f82b3dbce7e` / `51989154176@chatroom`
- 群「QIYE」`conv_6fbe0f455b94` / `58847495172@chatroom`

---

## 9. Topic Engine shutdown 应如何跟 Stop Bot / 程序退出协同？

现成钩子（**不改** `bot_runtime.py` 语义，只注册）：

- `runtime.register_stop_hook`
- `runtime.register_emergency_hook`
- `runtime.is_accepting_work()` / `begin_graceful_stop`

Side-path 应：

1. 入队前再查 `is_accepting_work()`；Stop 后新消息不入队  
2. worker 取任务后若已 STOPPED，丢弃、不写业务 Topic  
3. Stop hook：停止接受、`get_nowait` 丢弃队列、**不等待** Extractor 20s  
4. worker 守护线程，concurrency=1  

Stop Bot = Chat 停止 + Topic 停止。页面显示已停止时，不得继续入库。

---

## 10. G2 是否真的只需最小插入 listener？

**是。** 不需要改 Trigger / Self / Dedupe / Outbound / InboundMessage / `evaluate_inbound`。

所需工作：

1. 新增 `topic_sidepath.py`（enqueue / worker / shutdown / 审计）  
2. 在 `STEP_ADMIT` 中 `evaluate_inbound` 之后插入 `try_enqueue_topic_sidepath(inbound, verdict, runtime=runtime)`  
3. 入队条件用 verdict 的 identity/direction/dedupe/reason，**不**用 `action == REPLY`  
4. Gate 1 使用 Heuristic；Gate 2 再接真实 LLM 新入口  

禁止：把 Topic 放到 `evaluate_inbound` 之前、放进 `decide_trigger`、把 Topic 决策映射成 REPLY/NO_ACTION。

---

## 与 G1 文档的差异（非 BLOCKER）

| 差异 | 处理 |
|---|---|
| 文档写 `verdict.action`，源码是 dict | 按源码 `verdict.get("action")` |
| STOPPED 在 `STEP_ADMIT` 前就 return | Side-path 只插 ADMIT 路径，Stop 自然不投递 |
| `SendQueue` 看起来像 worker | 不得复用 |
| Extractor 还不能打真实模型 | Gate 1 不接；Gate 2 新增函数 |
| `extractor_prompt_name` 生产仍为 null | 不全局改；真机再绑测试 Agent |

---

## 禁止触碰（本轮仍冻结）

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

`UPDATE_ONLY` 禁止使用、禁止接线。

---

## Gate 0 结论

```text
真实 listener 结构与 G1 文档：一致（语义等价插入点存在）
必须解冻 P0 才能接 Topic：NO
BLOCKER-01 ～ BLOCKER-08：未发现

G2 Gate 0 = PASS
下一步 = Gate 1 Side-path + Heuristic / Mock
不在本 Gate 接真实 LLM、不启动真机
```
