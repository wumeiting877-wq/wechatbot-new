# P4 Task 离线测试数据集

> 日期：2026-09-21  
> 阶段：P4-G0  
> 用途：离线抽取验证。**不**验证 Risk / Decision / 提醒 / 微信发送。  
> 不跑真实微信。  
> 机器可读副本：`tests/fixtures/task_engine/zhiqun_task_cases.json`

P4 不再测 Topic 分类。每个 CASE 都 **预置** 已形成的 Topic + 必要的 Topic 消息 Evidence。  
期望断言只针对 Task：是否创建、是否更新、负责人文字、截止原文、是否 DONE。

---

## 1. 固定 Conversation / Topic 种子

```text
conversation.id            conv_zhiqun_demo01
conversation.display_name  智群Demo
conversation_type          GROUP

Topic A  topic_demo_erp     title=ERP 数据同步异常
Topic B  topic_demo_perm    title=权限整改
Topic C  topic_demo_demo    title=现场演示准备
```

人员只作 `sender_name` / 正文点名。不验收 `assignee_id`，不验收 `due_at` 绝对时间。

消息 id 尽量与 P3 `zhiqun_demo.json` 对齐，便于以后串 Replay，但 **本数据集按 CASE 隔离 run**，不与 P3 Engine 状态混合。

---

## 2. 创建规则（所有 CASE 共用）

```text
NEW_TASK 必须：明确动作对象 +（assignee_text 或「我 + 具体动作」）
无负责人的「需要…」     → 不建
问题事实 / 建议 / 收到  → 不建
完成陈述                → 不建、不 DONE
TASK_UPDATE 必须命中 existing_tasks.id
v1 只写 status=OPEN
1 消息最多 5 个 Task；不同负责人可多条
同一人连续步骤          → 1 个 Task
```

---

## 3. CASE-T01 明确负责人 + 截止时间

**Topic：** A（已有 ERP 上下文：0905 提问、0906 空编码）

```text
09:08  周敏  王强今天 16 点前把空值处理规则做完，再跑一次回归。
```

| 期望 | 值 |
|---|---|
| decision | `NEW_TASK` 恰好 1 条（规则+回归合并，不拆两个） |
| title | 近义白名单：处理供应商编码空值规则 / 处理空值规则 / 空值处理规则 |
| assignee_text | `王强` |
| due_text | `今天 16 点前` |
| due_at | 空（不验收绝对时间） |
| status | `OPEN` |
| evidence | 含当前消息 id |
| sender 周敏 | **不得**写成负责人 |

---

## 4. CASE-T02 无负责人

**Topic：** A

```text
需要再跑一次回归。
```

| 期望 | 值 |
|---|---|
| 创建 Task | **否** |
| 理由 | 无点名、非「我 + 动作」、属于需求陈述 |

规则已定：**不允许**本句写成 `assignee_text=""` 的 Task。v1 宁可漏。

---

## 5. CASE-T03 无截止时间

**Topic：** B（已有 0907 质检员可见采购价格）

```text
李娜把权限问题修一下。
```

| 期望 | 值 |
|---|---|
| decision | `NEW_TASK` 1 条 |
| assignee_text | `李娜` |
| due_text | 空 |
| status | `OPEN` |

---

## 6. CASE-T04 一条消息两个 Task

**Topic：** 当前预置为 A（P3 单主 Topic 遗产；见 LIMITATION）

```text
王强处理供应商编码，李娜修权限。
```

| 期望 | 值 |
|---|---|
| v1 是否两个 Task | **是** |
| NEW_TASK | 2 |
| T4a | assignee `王强`，title 含供应商编码/空值/编码 |
| T4b | assignee `李娜`，title 含权限 |
| 两者 topic_id | 都是当前 Topic A |
| 不新建 Topic | 是 |

说明：李娜这条在业务上更像 Topic B。P4 v1 **不跨 Topic 改挂**。本 CASE 验收的是基数，不是跨主题路由。

---

## 7. CASE-T05 Task 更新

**预置：** T01 已存在 Task `task_demo_nullrule`  
assignee 王强，due_text=今天 16 点前，topic A

```text
1. （历史）王强今天 16 点前把空值处理规则做完
2. （当前）改到 17 点前。
```

| 期望 | 值 |
|---|---|
| NEW_TASK | 0 |
| TASK_UPDATE | 1，task_id=原 Task |
| due_text | `17 点前`（或 `改到 17 点前` 中抽出的 `17 点前`） |
| 同一 topic 下 OPEN Task 数 | 仍为 1 |

---

## 8. CASE-T06 收到

**Topic：** A，可带 T01 已有 Task

```text
收到
```

| 期望 | 值 |
|---|---|
| NEW_TASK | 0 |
| TASK_UPDATE | 0 |
| 预筛或 UNRELATED | 是 |
| 不改已有 Task | 是 |

---

## 9. CASE-T07 Topic 中的问题事实

**Topic：** A 可先由本句在 P3 侧建出；本 CASE 预置 A 或允许空 existing_tasks

```text
ERP 同步失败了。
```

| 期望 | 值 |
|---|---|
| 因「业务问题」建 Task | **否** |
| decision | `UNRELATED` |

---

## 10. CASE-T08 建议

**Topic：** A，existing 可含 T01 Task，也可为空

```text
我建议供应商编码缺失的数据先进异常池。
```

| 期望 | 值 |
|---|---|
| 抽成「把数据放异常池」Task | **否** |
| NEW_TASK | 0 |
| 不把建议者王强写成新事项负责人 | 是 |

若 existing 已有空值规则 Task：v1 **不要求** 对本句做 UPDATE（建议尚未被确认执行）。允许 UNRELATED。禁止 NEW。

---

## 11. CASE-T09 明确确认执行（上下文）

这是关键上下文测试，**必须带上文**，禁止单句拍脑袋。

**预置消息：**

```text
0908 周敏  王强今天 16 点前把空值处理规则做完，再跑一次回归。
0914 王强  我建议供应商编码缺失的数据先进异常池，不阻塞正常订单。
```

**预置 Task：** T01 那条 OPEN Task（王强 / 空值规则 / 今天 16 点前）

**当前：**

```text
0915 周敏  可以，先按照这个方案做，明天看看异常池数量。
```

| 期望 | 值 |
|---|---|
| NEW_TASK | 0（不要第二条「按方案做」，不要凭空补负责人） |
| TASK_UPDATE | 允许 1 条：description 纳入异常池方案；assignee 仍为王强 |
| 或 UNRELATED | 若模型无法安全命中，UNRELATED **优于** 乱 NEW |
| 禁止 | assignee_text 改成周敏；新建无主 Task |

G1 验收建议：**不得 NEW**；UPDATE 或 UNRELATED 都算 PASS；NEW 为 FAIL。

无预置 Task 的退化：仅本句 → UNRELATED（缺动作对象与负责人）。可作为可选子 CASE `CASE-T09b`，不阻塞 T09。

---

## 12. CASE-T10 任务完成表述

**预置：** T01 OPEN Task

```text
空值规则已经处理完了。
```

| 期望 | 值 |
|---|---|
| 自动 DONE | **否**（P4 v1 明确禁止） |
| NEW_TASK | 0 |
| status | 仍为 OPEN |
| decision | `UNRELATED`（不采用 TASK_COMPLETE） |

与 P3 不自动 RESOLVED 对齐。

---

## 13. 智群 Demo 主样本对照（不单独当硬 CASE，供 G1 串跑参考）

若把 P3 Demo 消息按时间灌进 **已形成的 A/B/C Topic**（假设 P3 归属正确）：

| msg | 期望 Task 行为 |
|---|---|
| 0905 解决了吗 | UNRELATED |
| 0906 126 条为空 | UNRELATED（事实） |
| 0907 质检员看到价格 | UNRELATED（事实） |
| **0908** 王强 16 点前… | **NEW_TASK** ≈ T01 |
| 0909 收到，16 点前给结果 | UNRELATED（确认，非新事项） |
| 0910 周五演示 15:30 | UNRELATED（事件约束，未指派） |
| 0911 演示必须包含… | UNRELATED（范围，未指派） |
| **0913** 权限我中午前修复 | **NEW_TASK** ≈ T03（assignee 李娜，due 中午前，自称） |
| 0914 我建议异常池 | UNRELATED ≈ T08 |
| **0915** 按照这个方案做 | 不得 NEW ≈ T09 |
| 0917 最好准备离线数据 | UNRELATED（建议） |
| **0919** 赵凯明天 12 点前准备… | **NEW_TASK** |
| 0920 收到 | UNRELATED ≈ T06 |
| 0923 不要用管理员账号 | UNRELATED（约束） |
| 0925 我建 demo-viewer | 可选 NEW_TASK（我 + 具体动作，assignee=李娜）；G1 主门槛不强制 |

主样本 **不**验收 Risk/Decision。0923/0925 的双 Topic 问题仍是 P3 的，不在本数据集翻案。

---

## 14. G1 离线门槛（建议）

```text
CASE-T01  1 个 OPEN Task，负责人王强，due_text 含 16 点
CASE-T02  0 Task
CASE-T03  1 个 Task，李娜，due 空
CASE-T04  2 个 Task
CASE-T05  仍 1 个 Task，due 变为 17 点
CASE-T06  0 新 Task
CASE-T07  0 Task
CASE-T08  0 新 Task
CASE-T09  0 新 Task
CASE-T10  status 仍 OPEN，0 DONE
Task 失败注入不影响 Topic fixture
不调用 send_reply
P0 / P1 / P2 / P3 回归仍绿
```

不验收：真机微信、绝对时间、自动催办、跨 Topic 改挂、Risk/Decision。
