# P6-G0 下一 Gate 计划

> 当前：`P6-G0 = BLOCKED`  
> N2 RCA = **DONE**（两个微信 local_id，不是 worker 双跑）  
> **禁止在未给指令时改源码。**

---

## 下一 Gate 建议顺序

### P6-G0-FIX-LIFECYCLE（需明确指令）

目标：证明单 Bot ↔ 单 Listener，Stop 后线程退出。

1. `keep_alive` 在 STOPPING/STOPPED 不得 `AddListenChat`
2. Stop 后 join 或保证进程退出（现有 P0 Stop 语义，禁止重构大改）
3. `start_bot` 拒绝在已有本项目 `bot.py` 存活时再 Popen
4. 自动化：Stop 后 `wx.listen` 为空且 keep_alive 不再补注册

### P6-G0-FIX-OBS（可并行，最小改动）

`get_extractor_response` 的 `note_llm_call` / 日志 purpose 按调用方区分 Topic/Task/Decision/Risk。  
不改 LLM 参数、不改 Prompt。

### 不进入下一 Gate 的项

```text
正文时间窗去重当 N2 修复
全局锁 / sleep
新 queue / 新 worker
改四个 EXTRACTOR 决策语义
Progress / Dashboard / 催办 / 自动 RESOLVED
生产长期 ENABLE 四个 Engine
为 DJ-R8 / RK-R9 改 DECISION_EXTRACTOR
```

---

## 建议新增测试（修复 Gate 才写）

见 RCA §14。  
同文不同 local_id 的用例必须先 **锁定当前行为（enqueue=2）**，再谈产品要不要变。

---

## 完成定义（若要宣称 P6-G0 COMPLETE）

```text
一条 platform_message_id
  → 最多一个 MessageRecord
  → 最多一次 Topic enqueue
  → 最多一次 Topic Extractor
  → 最多一次 Topic Store 成功 commit
  → 最多一次 Task / Decision / Risk fan-out

Stop Bot 后 keep_alive 不再注册
Restart 前无第二 bot.py Listener
P0–P5 venv 回归全 PASS
四个开关仍为 false
```

N2 样本已证明：**上述不变式对单条 local_id 成立。**  
未证明：**Stop/Restart 生命周期。** 故仍 BLOCKED。
