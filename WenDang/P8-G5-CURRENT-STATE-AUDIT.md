# P8-G5 Current State Audit

> 日期：2026-09-23  
> 方式：先只读现有代码与配置，再决定本 Gate 能不能建立独立身份目录。

---

## 1. 进入本 Gate 时的状态

```text
P8-G0 = COMPLETE
P8-G1 = COMPLETE
P8-G2 = COMPLETE
P8-G3 = COMPLETE
P8-G4 = BLOCKED / TYPE C
```

P8-G4 的结论继续有效：当时没有确定性身份连接键，所以 `MY_TASKS` 和 `TASKS_BY_ASSIGNEE` 不能做。

进入本 Gate 时的非 live 基线是 715 OK。四个 Engine 开关都是 `false`。

```text
TOPIC_ENGINE_ENABLED=false
TASK_ENGINE_ENABLED=false
DECISION_ENGINE_ENABLED=false
RISK_ENGINE_ENABLED=false
```

个人身份查询仍是固定句：

```text
我有什么任务
→ 当前暂不支持按个人身份查询任务。

张三负责什么
→ 当前暂不支持按人员身份查询任务。
```

这条路径在分类器之前收口，不读 Task Store，不调用 QueryService。

## 2. 本 Gate 要补的缺口

P8-G4 已经证明消息侧和任务侧没有共同人员主键：

```text
sender_wxid          有值时能标识发送账号
Task.assignee_text   自由文本
中间                 没有 person_id
```

本 Gate 只补这层身份目录，不开放查询。

## 3. 结论

现有后台、监听配置、微信本地联系人查询、运维页面，都不能当作人员目录。

第一版 Source of Truth 采用：

```text
A. 项目本地显式人员目录
```

架构允许把它放在独立 JSON Store 里，不必改 Task schema，也不必改四个 Engine 或 P8 查询路由。分类是 MODEL-A。
