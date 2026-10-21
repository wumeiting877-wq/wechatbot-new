# P7-G2 Implementation Report

> 日期：2026-09-23  
> 结论：已实现只读调查详情。没有改 Store schema，没有改三态。

---

## 新增

```text
operations_diagnostic_service.py
templates/operations_message.html
tests/test_p7g2_diagnostics.py
```

`OperationsDiagnosticService.get_message_diagnostics` 读取 Message、四路 processing、确定相关的实体、本消息的 evidence、最近 20 条 engine audit，以及本消息的人工重试审计。

三态来自既有 `OperationsReadModel.message_view`。诊断层只附加证据和事实说明。

---

## 修改

```text
operations_routes.py
templates/operations.html
```

路由只增加 GET。列表每条消息增加「查看详情」。`operations_action_service.py` 未改。四份 Store、Read Model 的分类函数未改。

---

## 源码约束

`operations_diagnostic_service.py` 不含：

```text
write_processing
commit_apply
create_topic
create_task
create_decision
create_risk
retry_topic(
retry_downstream(
Engine(
Extractor
send_reply
```

服务不调用写入方法。测试在读取前后确认 processing 仍为缺失。

---

## 关联实现

实体进入详情，只因下面三者之一：

```text
created_msg_id 等于当前 message_id
本消息的 CREATED_BY / UPDATED_BY / RELATED
当前 processing 记录里已经写下的实体 id
```

最后一条是 processing 自己的字段，不是从标题或审计猜出来的 decision。

Audit 文件仍由 Store 整文件读出，服务再按 message 过滤并只返回最近 20 条。`AUDIT_FAILED_PRESENT` 看全部命中记录，避免失败记录被截掉后标记消失；页面表格仍只显示 20 条。这不新增索引，也不改 audit schema。

---

## 未做

```text
自动重试
Reminder / 催办 / 日报 / 周报
批量操作
新的 AI Engine
Dashboard 改版
CSRF 框架
RBAC
为诊断补 schema 字段
```
