# P6-G4 Direct Create Call-site Audit

> 日期：2026-09-22  
> Gate 0：READ ONLY。全仓扫描 `create_task(` / `create_decision(` / `create_risk(` 以及 `store.create_*`。

---

## 定义点（仅 3 处）

| 方法 | 文件 | 类 |
|---|---|---|
| `create_task` | `task_store.py` | `TaskStore` |
| `create_decision` | `decision_store.py` | `DecisionStore` |
| `create_risk` | `risk_store.py` | `RiskStore` |

无 wrapper / helper / service 再包一层。  
无 `getattr(..., "create_task")` 动态转发。

---

## 生产运行链：零调用

以下模块 **均不出现** `create_task(` / `create_decision(` / `create_risk(`：

```text
task_engine.py          → 只调用 commit_apply
decision_engine.py      → 只调用 commit_apply
risk_engine.py          → 只调用 commit_apply
task_sidepath.py
decision_sidepath.py
risk_sidepath.py
downstream_retry.py
bot.py
bot_runtime.py
webui_data.py
webui_bot_process.py
config_editor.py
forum_routes.py
reminders.py
message/processor.py
message/pipeline.py
message/handler.py
message/listener.py
```

WebUI / Flask 路由不创建 Task / Decision / Risk。

---

## 测试调用点

### Task

| 文件 | 函数 | 场景 | 分类 |
|---|---|---|---|
| `tests/test_task_store.py` | `test_task_create_normal_and_ids_correct` 等全部 create 用例 | Store 单测 | 测试专用 |
| `tests/test_task_engine_offline.py` | `_prepare` | 写入 `existing_tasks` fixture | 测试专用 |
| `tests/test_task_live_adapter.py` | `_prepare` | 同上 | 测试专用 |
| `tests/test_risk_engine_offline.py` | `_prepare` | 写入 `candidate_tasks` 供 Risk 读取 | 测试专用 |
| `tests/test_risk_store.py` | `test_legal_task_id_can_be_written` | Risk.task_id FK fixture | 测试专用 |

### Decision

| 文件 | 函数 | 场景 | 分类 |
|---|---|---|---|
| `tests/test_decision_store.py` | `test_decision_create_normal_and_ids_correct` 等 | Store 单测 | 测试专用 |
| `tests/test_decision_engine_offline.py` | `_prepare` | `existing_decisions` fixture | 测试专用 |
| `tests/test_decision_live_adapter.py` | `_prepare` | 同上 | 测试专用 |

### Risk

| 文件 | 函数 | 场景 | 分类 |
|---|---|---|---|
| `tests/test_risk_store.py` | `test_new_risk_normal_and_ids_correct` 等 | Store 单测 | 测试专用 |
| `tests/test_risk_engine_offline.py` | `_prepare` | `existing_risks` fixture | 测试专用 |
| `tests/test_risk_live_adapter.py` | `_prepare` | 同上 | 测试专用 |

---

## Gate 0 必答

### Task `create_task`

1. 是否被 Engine 调用？**否**（Engine 走 `commit_apply`）
2. 是否被 WebUI/API 调用？**否**
3. 是否存在真实生产调用点？**否**
4. 是否只在测试中使用？**是**
5. 调用方是否自己生成 id？**有时**。Store 单测多数让 `make_task_id` 生成；部分显式传 `id`；Engine fixture 的 `existing_tasks` 常带固定 id
6. 相同 id 第二次调用代表：
   - 生产：**不适用**（无调用）
   - 当前实现：suffix `_2`（碰撞新建，不是幂等）
   - 判定：**C. 无法把生产语义说成幂等**；测试里它是 fixture / 碰撞工具，不是重试同一逻辑实体

### Decision `create_decision`

同上 1–4 全是否 / 只测试。  
5. 同 Task。  
6. **C**。无生产语义。当前 suffix。

### Risk `create_risk`

同上 1–4 全是否 / 只测试。  
5. 同 Task。  
6. **C**。无生产语义。当前 suffix。

---

## STOP 条件判定

```text
create_* 是公开业务 API？  否
相同 id 重复调用的生产语义不明确？  因无生产调用而不适用
```

**不触发 STOP。** 不把 `create_*` 改成幂等。  
继续处理 Evidence collision。Gate 2 走情况 A。

语义锁定见 `P6-G4-DIRECT-CREATE-SEMANTICS-REPORT.md`。
