# P8-G5 Closure Report

> 日期：2026-09-23  
> 状态：COMPLETE

---

## 1. 结论

```text
P8-G5 = COMPLETE
分级 = MODEL-A
Source of Truth = A. 本地显式人员目录
MY_TASKS 仍未实现
TASKS_BY_ASSIGNEE 仍未实现
```

人员主键、微信账号绑定和精确别名已经可以单独成立。查询路由没有放开。

## 2. 已证明

```text
person_id 稳定，且与显示姓名分开
同名可以是两个 person
wxid → 恰好一个 person_id
精确 alias → 恰好一个 person_id
重复绑定和重复 alias 拒绝覆盖
损坏文件不会被重置成空目录
0 模糊匹配
0 模型认人
0 查询行为变化
四个 Engine 开关 = false
```

`我有什么任务` 仍然回复「当前暂不支持按个人身份查询任务。」QueryService 调用次数为 0。

## 3. 证据

```text
tests.test_p8g5_identity_model        20 OK
tests.test_p8g1_collaboration_query   42 OK
tests.test_p8g2_query_intent          25 OK
tests.test_p8g3_query_delivery        22 OK
tests.test_p8g4_identity               3 OK
Non-Live discover                     735 OK，排除 Real Extractor 42 条
```

735 = 旧 715 + 本 Gate 20。旧用例没有新增失败。

## 4. 文档

```text
WenDang/P8-G5-CURRENT-STATE-AUDIT.md
WenDang/P8-G5-G0-IDENTITY-MODEL-AUDIT.md
WenDang/P8-G5-IDENTITY-MODEL-DESIGN.md
WenDang/P8-G5-TASK-BINDING-OPTIONS.md
WenDang/P8-G5-IMPLEMENTATION-REPORT.md
WenDang/P8-G5-TEST-REPORT.md
WenDang/P8-G5-REGRESSION-REPORT.md
WenDang/P8-G5-DEFERRED-ISSUES.md
WenDang/P8-G5-CLOSURE-REPORT.md
```

生产代码：

```text
identity_store.py
identity_resolver.py
```

## 5. 停在这里

不进入：

```text
P8-G6 MY_TASKS / TASKS_BY_ASSIGNEE
Task schema 增加负责人 id
历史任务自动写绑定
昵称或模型认人
查询路由放开
```

任务负责人绑定的后续形状是独立 `TaskIdentityLink`，本 Gate 没有写这层数据。

等待下一步指令。
