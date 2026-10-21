# P8-G4 Closure Report

> 日期：2026-09-23  
> 状态：BLOCKED / TYPE C

---

## 1. 结论

没有确定性身份连接键。`MY_TASKS` 和 `TASKS_BY_ASSIGNEE` 不能安全实现。

```text
P8-G4 = BLOCKED
NEEDS IDENTITY MODEL UPGRADE
```

这是本 Gate 的正确结束。保持 P8-G2 的固定安全回复。没有为了变绿去改 Task schema，也没有用昵称对负责人。

## 2. 硬门槛

```text
sender_name == assignee_text 仍然不能查「我的任务」
同名不猜，不把两个人的任务混在一起
自由文本负责人不做模糊匹配
Classifier 不判断「我」或「张三」是谁
不读 Task Store 做身份过滤
不写 Store
不跨会话
四个 Engine 开关 = false
P8-G1 42 PASS
P8-G2 25 PASS
P8-G3 22 PASS
P8-G4 3 PASS
Non-Live 旧 712 PASS，合计 715 PASS
```

没有触发「旧用例新增失败」。实现路径在 TYPE 判断之后停止，因为分类是 C。

## 3. 证据

```text
tests.test_p8g4_identity               3 OK
tests.test_p8g1_collaboration_query   42 OK
tests.test_p8g2_query_intent          25 OK
tests.test_p8g3_query_delivery        22 OK
Non-Live discover                     715 OK，排除 Real Extractor 42 条
```

文档：

```text
WenDang/P8-G4-CURRENT-STATE-AUDIT.md
WenDang/P8-G4-G0-IDENTITY-AUDIT.md
WenDang/P8-G4-IDENTITY-CLASSIFICATION.md
WenDang/P8-G4-IDENTITY-DESIGN.md
WenDang/P8-G4-BLOCKER-REPORT.md
WenDang/P8-G4-TEST-REPORT.md
WenDang/P8-G4-REGRESSION-REPORT.md
WenDang/P8-G4-DEFERRED-ISSUES.md
WenDang/P8-G4-CLOSURE-REPORT.md
```

没有 `P8-G4-IMPLEMENTATION-REPORT.md`。没有 `identity_resolver.py`。

## 4. 停止在这里

不进入：

```text
MY_TASKS 实现
TASKS_BY_ASSIGNEE 实现
Task schema 增加负责人 id
昵称或 LLM 认人
跨会话查询
写 Command
组织权限
P6-G6 processing
```

等待下一步指令。
