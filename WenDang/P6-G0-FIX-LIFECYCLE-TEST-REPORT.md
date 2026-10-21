# P6-G0-FIX-LIFECYCLE Test Report

> 日期：2026-09-22  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> Real LLM：本轮生命周期不要求。完整 discover 时 Real* 类也跑过且 OK（见回归 V2）。

---

## Targeted（先跑）

```text
.\.venv\Scripts\python.exe -m unittest tests.test_bot_lifecycle tests.test_webui_bot_process tests.test_llm_client tests.test_p0_message_runtime tests.test_topic_sidepath.TopicSidepathTests.test_n2_same_text_different_platform_id_enqueues_twice -v
```

```text
Ran 49 tests in 1.464s
OK
```

---

## LIFE-01 ～ LIFE-08

| ID | 内容 | 结果 | 证据 |
|---|---|---|---|
| LIFE-01 | RUNNING 时 keep_alive 补 1 个 listener | **PASS** | `test_life_01_running_keep_alive_adds_one_listener` |
| LIFE-02 | STOPPING 后不再 AddListenChat | **PASS** | `test_life_02_stopping_keep_alive_does_not_add_listen` |
| LIFE-03 | StopListening 清空后多周期仍 empty | **PASS** | mock wait，**无 5s sleep**；4 次 tick，`add_listen_count=0` |
| LIFE-04 | Start→Stop→Start 仍 1 listener | **PASS** | `test_life_04_start_stop_start_single_listener` |
| LIFE-05 | Flask 句柄丢失但 status PID 是本项目活 Bot → 拒绝 Popen | **PASS** | `test_life_05_status_pid_alive_refuses_second_popen` |
| LIFE-05b | Flask 句柄仍活 → 拒绝 | **PASS** | `flask_bot_process_alive` |
| LIFE-06 | stale pid 不存在 → 允许 Start | **PASS** | `test_life_06_stale_pid_allows_start` |
| LIFE-07 | PID 复用且 cmdline≠本项目 bot.py → 不识别、不杀 | **PASS** | `cmdline_not_bot`；真实当前进程亦拒绝 |
| LIFE-08 | Stop 后 callback `reason=stopped`，不进 Chat/Topic | **PASS** | enabled Topic sidepath 仍 `SKIP_STOPPED` |

额外：

- `test_stopped_keep_alive_thread_exits`：Stop 后线程终止
- `test_join_keep_alive_has_timeout`：join 有 timeout，不会卡死 Stop
- `test_bot_py_keep_alive_no_unconditional_while_true`：生产 `keep_alive` 不再 `while True`

测试间隔使用 `interval=0.01` / `Event.wait`，不 sleep 5 秒。

---

## N2 防误修

| 测试 | 期望 | 结果 |
|---|---|---|
| `test_n2_same_text_different_platform_message_id_two_new`（P0） | 同文 pid A/B → 两次 NEW、两次 REPLY | **PASS** |
| `test_n2_same_text_different_platform_id_two_new`（lifecycle） | 同上 | **PASS** |
| `test_n2_same_content_different_platform_ids_two_message_records` | MessageRecord A ≠ B | **PASS** |
| `test_n2_same_text_different_platform_id_enqueues_twice` | Topic enqueue=2 | **PASS** |

未引入正文时间窗去重。P0 `test_05b` / `test_04` 仍 PASS。

---

## OBS

| 测试 | 结果 |
|---|---|
| `_extractor_log_purpose` 四引擎标签不同 | **PASS** |
| `get_extractor_response` 的 HTTP `create()` 不含 `purpose=` | **PASS** |
| 四个 `_default_extractor_llm_call` 分别 setdefault purpose | **PASS** |

未改 Prompt / model / timeout / parser / store_context。

---

## 开关

`test_engine_flags_remain_false`：**PASS**（四个模块常量仍 False）。
