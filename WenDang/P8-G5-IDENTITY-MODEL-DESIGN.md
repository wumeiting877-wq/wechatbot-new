# P8-G5 Identity Model Design

> 日期：2026-09-23  
> 分级：MODEL-A  
> Source of Truth：A. 本地显式人员目录

---

## 1. 本 Gate 建立什么

```text
Person
WechatIdentityBinding
AssigneeAlias
只读 Resolver
```

不建立 `MY_TASKS`，不建立 `TASKS_BY_ASSIGNEE`，不写 Task 负责人链接。

## 2. 文件

```text
data/identity/people.json
data/identity/wechat_bindings.json
data/identity/assignee_aliases.json
```

根目录跟 Task Store 一样，是调用方传入的项目根。测试使用临时目录。仓库里不放真实人员。

三个文件分开锁。读缺失文件得到空列表，并且不创建文件。已存在但无法解析的文件返回 `CORRUPT`，不改原字节。

`store_io.read_json` 的损坏回退不用于这三份文件。

## 3. Person

```text
person_id         person_ 加字母或数字，例如 person_001
canonical_name    显示姓名，可以重复
status            ACTIVE 或 DISABLED
created_at
updated_at
```

`person_id` 与姓名分开。`李明`、`张三` 不能当主键。

```text
person_001  张三
person_002  张三
```

这是合法的两个人。

没有删除接口。`set_person_status` 把状态改成 `DISABLED`，行还在。重复创建同一个 `person_id` 返回 `DUPLICATE_PERSON_ID`。

创建只接受调用方给出的 `person_id`。不会从 `sender_name` 或姓名生成主键。

## 4. 微信绑定

```text
wxid
person_id
display_name      可空，只是备注
binding_source    MANUAL 或 TRUSTED_DIRECTORY
created_at
```

目标关系：

```text
wxid → 恰好一个 person_id
```

人员必须已经存在。同一个 wxid 再绑同一个 person，保持原行。再绑另一个 person，返回 `CONFLICT`，原文件不变。

`TRUSTED_DIRECTORY` 只是调用方显式声明的来源标签。本 Gate 没有通讯录同步。其他来源字符串会被拒绝。

## 5. Alias

```text
exact_text
person_id
created_at
```

保存前只做 strip。这是管理员登记的完整字符串，不是模糊规则。

```text
李明 → person_001
老李 → person_001
```

可以同时存在，因为文本不同。

```text
张三 → person_001
张三 → person_002
```

第二次写入返回 `CONFLICT`。

`canonical_name` 不会自动变成 alias。目录里有一个叫李明的人，在登记 alias 之前，`resolve_exact_alias("李明")` 仍是 `NOT_FOUND`。

## 6. Resolver

`identity_resolver.py` 只有：

```text
resolve_wxid(store, wxid)
resolve_exact_alias(store, text)
```

返回：

```text
RESOLVED     恰好一个 person_id
NOT_FOUND    没有对应行
AMBIGUOUS    同一个键指向多个 person_id，或人员行本身重复
```

`resolve_exact_alias` 对输入 strip 之后做全等比较。下面这些在只登记了 `李明` 时都是 `NOT_FOUND`：

```text
李明负责
由李明
研发部李明
@李明
```

除非管理员把整段字符串本身登记为 alias。

找不到时不创建 Person。`DISABLED` 的人如果仍有绑定，解析结果仍是 `RESOLVED`，并带上 `status`。查询还没开放，所以这不会改变回复。下一 Gate 若使用解析结果，要单独决定禁用人员能不能查任务。

手改文件造成同一 alias 或同一 wxid 指向两人时，Resolver 返回 `AMBIGUOUS`，不挑选。此时 Store 拒绝继续写入，避免在坏数据上再追加。

## 7. 唯一性

```text
person_id     唯一
wxid          最多一个 person
exact alias   最多一个 person
canonical_name  允许重复
```

## 8. 模块边界

身份模块只依赖 JSON、文件锁、时间戳。它不调用聊天、抽取、四个 Engine、QueryService、发送。

查询路由保持 P8-G4 的固定拒绝。即使目录里已经有李明，`我有什么任务` 仍然是固定安全回复。
