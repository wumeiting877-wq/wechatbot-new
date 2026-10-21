# P4-G2 实施报告

> 日期：2026-09-21  
> 项目：wechatbot-new  
> 阶段：**P4-G2**（Topic Side-path 后接入 Task Engine）  
> Gate 0：`P4-G2-G0-CURRENT-STATE-AUDIT.md` = PASS（不必改 listener）

```text
P0 / P1 / P2     = CLOSED（本轮未解冻）
P3-G0 / G1 / G2  = COMPLETE
P4-G0 / G1       = COMPLETE
P4-G2            = COMPLETE（Gate 1 + Gate 2 + 真机 TA-R1～R13 PASS）
```

未改 Trigger / Self / Dedupe / Outbound / `evaluate_inbound` / Topic decision schema / Topic Prompt / Chat Prompt。  
结束时 `TOPIC_ENGINE_ENABLED` / `TASK_ENGINE_ENABLED` 模块默认仍为 **false**。测试窗口开关已恢复 false。未写生产长期开启指令。

---

## 1. 新增文件

```text
task_sidepath.py
tests/test_task_sidepath.py
tests/test_task_live_adapter.py
```

文档：

```text
WenDang/P4-G2-G0-CURRENT-STATE-AUDIT.md
WenDang/P4-G2-IMPLEMENTATION-REPORT.md
WenDang/P4-G2-AUTOMATED-TEST-REPORT.md
WenDang/P4-G2-REAL-LLM-TEST-REPORT.md
WenDang/P4-G2-LIVE-WECHAT-TEST-REPORT.md
WenDang/P4-G2-REGRESSION-REPORT.md
WenDang/P4-G2-DEFERRED-ISSUES.md
WenDang/P4-G2-CLOSURE-REPORT.md
```

未新增 listener 第二条 Task Side-path。未进入 Risk / Decision。

## 2. 修改文件

| 文件 | 作用 |
|---|---|
| `topic_sidepath.py` | **最小解冻**：`__init__` 可注入 `task_sidepath`；Topic 成功路径末尾 `_maybe_enqueue_task`；显式注入时 `shutdown` 一并停 Task |
| `task_engine.py` | 仅更新模块注释：G2 由 Topic Side-path 非阻塞投递；仍不改 `process_record` 语义 |

未修改：

```text
message/listener.py
message/trigger.py
message/identity.py
message/dedupe.py
message/outbound.py
bot_runtime.py
topic_engine.py
topic_store.py
topic_extractor_client.py
prompts/QIYE.md
prompts/企业_1.md
prompts/extractors/TOPIC_EXTRACTOR.md
prompts/extractors/TASK_EXTRACTOR.md
config.local.json
```

`DEFAULT_EXTRACTOR_PROMPT_NAME` 仍为 `TOPIC_EXTRACTOR`。  
Task Engine 仍显式 `resolve_extractor_prompt("TASK_EXTRACTOR")`。

## 3. 挂钩位置

```text
listener
  → try_enqueue_topic_sidepath          # P3-G2 已有，本轮未再插入
      → Topic worker
          → TopicEngine.process_inbound
          → TOPIC_PROCESS_SUCCESS
          → try_enqueue_task_after_topic   # 本轮新增，失败隔离
              → Task queue put_nowait
              → Task worker
              → TaskEngine.process_record(conversation, topic, message)
```

Topic 成功且允许触发 Task 的 decision：

```text
NEW_TOPIC / EXISTING_TOPIC / TOPIC_UPDATE
且 topic_id != null
```

禁止触发：

```text
UNRELATED / SKIPPED / FAILED / DISABLED / CONVERSATION_NOT_RESOLVED / 无 topic_id
```

`conversation` 来自 Topic worker payload（已 `resolve_topic_conversation`）。  
`topic` / `message` 通过 `TopicStore.get_topic` / `get_message` 读取。不改 listener。

## 4. 为什么不同步等 Task LLM

Topic worker concurrency=1。Task Extractor timeout 默认 20s。同步等待会让 Topic 队列积压、Stop 变慢。

因此：

```text
Topic 成功 → put_nowait（通常 < 1ms）→ Topic worker 继续
Task LLM 在独立 TaskSidepathWorker 执行
```

Queue：`queue.Queue(maxsize=32)`，单 worker。满则 `TASK_QUEUE_FULL`，丢弃本次 Task，不影响 Topic / Chat。

## 5. 双开关

```text
topic_engine.py      TOPIC_ENGINE_ENABLED = False
task_engine.py       TASK_ENGINE_ENABLED  = False

覆盖顺序（与 Topic 相同模型）：
runtime_control/TASK_ENGINE_ENABLED  >  环境变量  >  模块常量
```

| Topic | Task | 结果 |
|---|---|---|
| false | true | 无 Topic 输入，Task 不运行 |
| true | false | Topic 正常，Task enqueue=0 |
| true | true | Topic → Task |

未写入 `config.local.json` schema。

## 6. Stop Bot

复用现有 `register_stop_hook` / `register_emergency_hook`。不改 `bot_runtime.py`。

- listener STOPPED 快路径仍在 `STEP_ADMIT` 之前，不会投递新 Topic  
- Task `try_enqueue` 检查 `runtime.is_accepting_work()`  
- Task worker 取到任务后若已 Stop / 开关关闭，丢弃不处理新微信业务  
- `shutdown` 清空未处理 Task 队列  
- 不要求强杀正在执行的 Task LLM 线程

## 7. 隔离

- Task 失败只写 Task FAILED Processing + audit  
- 不 rollback 已成功的 Topic / TopicMessageLink / TopicProcessingRecord  
- Task 不得创建或修改 Topic  
- 全局搜索 Task 四文件 + `topic_sidepath.py`：**无** `send_reply(` / `wx.SendMsg(` / `SendMsg(`  
- listener **无** `task_sidepath` / `try_enqueue_task`

## 8. 真机窗口

已完成。QIYE / ceshi / 扶级。TA-R1～TA-R13 = **13 PASS**。详见 `P4-G2-LIVE-WECHAT-TEST-REPORT.md`。

测试窗口曾打开两个开关；结束后：

```text
runtime_control/TOPIC_ENGINE_ENABLED = false
runtime_control/TASK_ENGINE_ENABLED  = false
```
