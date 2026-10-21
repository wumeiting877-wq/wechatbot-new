# P8-G5 Implementation Report

> 日期：2026-09-23  
> 分级：MODEL-A

---

## 1. 新增

```text
identity_store.py
identity_resolver.py
tests/test_p8g5_identity_model.py
```

`IdentityStore` 写入：

```text
data/identity/people.json
data/identity/wechat_bindings.json
data/identity/assignee_aliases.json
```

调用方显式执行 `create_person`、`bind_wechat`、`add_alias`、`set_person_status`。消息处理和查询路径没有引用这两个模块。

## 2. 约束怎么落地

```text
person_id                 必须匹配 person_ 加字母或数字
canonical_name            允许重复，不参与解析
wxid 再绑另一个 person    CONFLICT，不覆盖
alias 再绑另一个 person   CONFLICT，不覆盖
同一对重复写入            保持原行
损坏 JSON                 CORRUPT，原字节保留
缺失文件                  空列表，不创建文件
手改造成的一键多人        Resolver 返回 AMBIGUOUS，Store 停止继续写
```

写入在 FileLock 内完成，用临时文件加 `os.replace`。替换失败时原文件保留，临时文件被清掉。

Resolver 只有 `resolve_wxid` 和 `resolve_exact_alias`。比较是 strip 后的全等。没有姓名回退。

## 3. 没有改的生产路径

```text
query_router.py
collaboration_query.py
query_service.py
agent_reply_delivery.py
task_store.py
task_engine.py
四个 Engine 开关
config.local.json
P0 入站身份
```

没有 `task_person_links.json`。没有历史任务扫描。没有人员管理页面。

`我有什么任务` 仍走 P8-G4 的固定句，QueryService 调用次数为 0。
