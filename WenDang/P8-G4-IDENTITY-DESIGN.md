# P8-G4 Identity Design

> 日期：2026-09-23  
> 结论：不实现。TYPE C 没有可接入的身份键。

---

## 1. 不进入的设计

规范里的这些部分只在 TYPE A 或安全 TYPE B 时才允许写代码：

```text
identity_resolver.py
IdentityResult：RESOLVED / NOT_FOUND / AMBIGUOUS / UNSUPPORTED
MY_TASKS
TASKS_BY_ASSIGNEE
pending 里保存 person_id
按 canonical name 格式化「你在本会话」
```

本系统没有 `person_id`，也没有 wxid 到规范姓名的目录。`assignee_text` 是自由文本。按这些步骤做，必然落到昵称或原文匹配。规范禁止这种 fallback。

因此不新增解析器，不扩展 Query 枚举，不改 Query Service，不改 Formatter，不改 P8-G3 delivery。

## 2. 继续生效的路由

```text
我有什么任务
张三负责什么
```

仍由 `query_router._identity_disposition` 在分类器之前收口，回复 P8-G2 的固定句。

不允许改成：

```text
这里是当前全部任务。
```

也不把任务标题混进回复。

## 3. 同名与未绑定

现在没有人员目录，所以做不到「两个张三 → AMBIGUOUS」这种有目录之后的精确状态。正确行为是不猜：固定说明暂不支持按人员查询，Task Store 过滤次数为 0。

发送者未绑定到负责人时，同样不退回 Chat，不改列全部任务。

## 4. 以后如果有身份模型

必须单独开阶段，并且先证明：

```text
发送者稳定 id → 唯一 person
Task 负责人 → 同一个 person
重名 → AMBIGUOUS，不合并任务
解析失败 → 不退回 sender_name
查询范围仍是当前 Conversation
pending 保存的是 person id，发送前再读 Task
0 模糊匹配，0 LLM 认人，0 Store 写入
```

在那之前不要给 Task 加 `assignee_id`。
